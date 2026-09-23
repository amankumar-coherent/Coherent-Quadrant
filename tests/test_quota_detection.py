"""A quota page must be detected however long the rendered page is.

Live capture: AI Mode returned "You've reached the request limit for AI
responses at the moment. Try again in a little while." The log said

    · discover-round-64: AI Mode JSON parse OK
    → substep 1a.64: +0 (total 221)

so a per-IP rate limit was recorded as an empty market. Fifteen rounds were
spent that way, and three in a row would have declared the market exhausted
at 221 of a 300 target.

The cause: the check was guarded by `len(text) < 600`, but the extracted text
is the WHOLE page — nav chrome plus the echoed prompt — which always exceeds
that.
"""
from __future__ import annotations

import inspect

from vendor_intel.pipeline import discovery_rounds as dr
from vendor_intel.scraping import google_ai_mode as gam

CHROME = (
    "Skip to main content\nAccessibility help\nAI Mode\nAll\nImages\nVideos\n"
    "News\nMore\nSign in\nAI Mode conversation: "
)
PROMPT = (
    "You identify the BRANDS sold in a market and the COMPANY behind each "
    "brand. No invented names, no media, associations, research firms or geo "
    "labels. Return compact JSON only: " + "x" * 400
)
QUOTA_PAGE = (
    CHROME + PROMPT + "\n" + PROMPT + "\n"
    "You've reached the request limit for AI responses at the moment. "
    "Try again in a little while."
)


def test_the_live_quota_page_is_longer_than_the_old_guard():
    """Why the guard never fired."""
    assert len(QUOTA_PAGE) > 600


def test_the_quota_wording_is_recognised():
    low = QUOTA_PAGE.lower()
    assert any(m in low for m in gam.QUOTA_MARKERS)


def test_the_quota_check_has_no_length_guard():
    """A long page must still be caught — that was the whole defect."""
    src = inspect.getsource(gam.AiModeSession.ask)
    quota_line = next(
        line for line in src.split("\n") if "QUOTA_MARKERS" in line
    )
    assert "len(text)" not in quota_line, "the length guard must not come back"


def test_the_refusal_check_keeps_its_length_guard():
    """Refusal phrases CAN appear inside a long genuine answer, so that guard
    is still wanted — the two checks are not interchangeable."""
    src = inspect.getsource(gam.AiModeSession.ask)
    refusal_line = next(
        line for line in src.split("\n") if "REFUSAL_MARKERS" in line
    )
    assert "len(text) < 600" in refusal_line


def test_a_quota_error_is_not_an_empty_market():
    """The consequence: three of these must never read as "exhausted"."""
    err = gam.AiModeCaptcha(
        "AI response request limit reached for this IP (3 this run) — "
        "only waiting helps"
    )
    assert dr._is_blocked(err) is True


def test_a_quota_run_reports_blocked_not_exhausted():
    def ask(system, user, label):
        raise gam.AiModeCaptcha("AI response request limit reached for this IP")

    _, stats = dr.discover_in_rounds(
        "M", "Manufacturer", ask_json=ask, target=300,
        dedupe_key=lambda s: s.strip().lower(),
        already_found=[{"brand": "A", "verdict": "in_market"}],
    )
    assert stats["stopped_because"] == "blocked"
    assert stats["blocked_rounds"] >= 1


# --- automatic recovery ----------------------------------------------------


def test_a_quota_page_triggers_a_profile_reset():
    """Cookie-clearing alone did not recover from a quota page; archiving the
    whole profile did — CAPTCHAs went 7 -> 1 and answers resumed at once. So
    the run does it itself instead of waiting to be told."""
    src = inspect.getsource(gam.AiModeSession.ask)
    quota_block = src.split("QUOTA_MARKERS", 1)[1][:1200]
    assert "reset_profile" in quota_block
    assert "continue" in quota_block, "it must retry on the clean profile"


def test_reset_profile_archives_rather_than_deletes():
    """A run must stay inspectable afterwards; nothing is destroyed."""
    src = inspect.getsource(gam.AiModeSession.reset_profile)
    assert ".rename(" in src
    assert "rmtree" not in src and "unlink" not in src


def test_reset_profile_survives_a_locked_directory():
    """Windows keeps file handles open; a failed rename must not kill the
    run — the fresh browser simply reuses the old profile."""
    src = inspect.getsource(gam.AiModeSession.reset_profile)
    rename_part = src.split(".rename(", 1)[1]
    assert "except Exception" in rename_part


def test_reset_profile_cools_off_before_retrying():
    src = inspect.getsource(gam.AiModeSession.reset_profile)
    assert "time.sleep(cool_off)" in src


def test_the_quota_counter_is_cleared_by_the_reset():
    """Otherwise a later genuine quota hit inherits a stale count."""
    src = inspect.getsource(gam.AiModeSession.reset_profile)
    assert "self.quota_hits = 0" in src


# --- a locked profile must not cost a whole market -------------------------


def test_a_locked_profile_is_cleared_and_retried():
    """Observed: Wearable Glucometer ran 0 companies in 0 minutes because a
    browser from the previous market still held the profile lock, so every AI
    Mode call failed with "Opening in existing browser session"."""
    src = inspect.getsource(gam.AiModeSession._ensure_browser)
    assert "existing browser session" in src
    assert "_kill_orphan_browsers" in src


def test_only_a_lock_error_is_retried():
    """Any other launch failure must still surface, not be silently retried."""
    src = inspect.getsource(gam.AiModeSession._ensure_browser)
    # The guard reads: if it is NOT a lock error, re-raise.
    assert 'if "existing browser session" not in str(err).lower():' in src
    guard = src.split('not in str(err).lower():', 1)[1][:80]
    assert "raise" in guard


def test_the_orphan_kill_is_scoped_to_our_profile():
    """It must never touch the user's own Chrome windows."""
    src = inspect.getsource(gam._kill_orphan_browsers)
    assert "CommandLine -like" in src
    assert "marker" in src


def test_the_orphan_kill_never_breaks_a_run():
    src = inspect.getsource(gam._kill_orphan_browsers)
    assert "except Exception" in src


# --- a CAPTCHA storm is a soured profile, not bad luck ---------------------


def test_sustained_captchas_trigger_a_profile_reset():
    """Observed while scoring Wearable Glucometer: 31 CAPTCHAs in one run,
    every scoring query walled, 3 of every 4 companies left unscored. Nothing
    escalated past "solve it in the browser window"."""
    src = inspect.getsource(gam.AiModeSession.ask)
    block = src.split("_CAPTCHAS_BEFORE_PROFILE_RESET", 1)[1][:400]
    assert "reset_profile" in block
    assert 'reason="captchas"' in block


def test_the_captcha_threshold_is_above_ordinary_noise():
    """Single CAPTCHAs are normal on bundled Chromium; firing on one would
    archive the profile constantly and lose the warm history."""
    assert gam._CAPTCHAS_BEFORE_PROFILE_RESET >= 3


def test_the_captcha_counter_resets_after_the_profile_is_rebuilt():
    """Otherwise the next CAPTCHA on the fresh profile instantly re-triggers."""
    src = inspect.getsource(gam.AiModeSession.ask)
    block = src.split('reset_profile(reason="captchas")', 1)[1][:120]
    assert "self.captcha_count = 0" in block


def test_a_solvable_captcha_is_still_solved_first():
    """The reset is an escalation, not a replacement — a CAPTCHA the
    extension can clear must not cost a profile."""
    src = inspect.getsource(gam.AiModeSession.ask)
    solve = src.index("_wait_for_captcha_clear")
    reset = src.index("_CAPTCHAS_BEFORE_PROFILE_RESET")
    assert solve < reset, "solving must be attempted before archiving"
