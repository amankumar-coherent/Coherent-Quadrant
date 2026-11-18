"""Google's block pages are detected so the session is reset, not scraped."""
from __future__ import annotations

from vendor_intel.scraping.google_ai_mode import AiModeSession


class _Page:
    def __init__(self, text): self._t = text
    def inner_text(self, sel, timeout=0): return self._t


def _showing(text):
    c = AiModeSession.__new__(AiModeSession)
    c._page = _Page(text)
    return AiModeSession._flagged_page_showing(c)


def test_sign_in_wall_is_treated_as_a_flagged_session():
    """Google's sign-in wall (owner 2026-10-29, Japan Fashion E-Commerce): not a
    reCAPTCHA, and a signed-out scraping profile can never satisfy it."""
    assert _showing("Sign in to continue\nSign in to verify you're a human and see more results.")
    assert _showing("Verifying your request") == "Verifying your request"
    assert "Sign in" in _showing("Sign in to verify you are a human. Please continue.")


def test_a_normal_results_page_is_not_flagged():
    assert _showing("Rakuten Group operates Rakuten Ichiba, a large online marketplace.") == ""
    # the phrase inside a long ordinary page must not trigger a profile reset
    long_page = "Sign in to continue reading. " + ("fashion e-commerce results. " * 40)
    assert _showing(long_page) == ""


def test_an_unreadable_page_is_not_flagged():
    c = AiModeSession.__new__(AiModeSession)
    class Boom:
        def inner_text(self, *a, **k): raise RuntimeError("gone")
    c._page = Boom()
    assert AiModeSession._flagged_page_showing(c) == ""


def test_repeated_blocks_stop_the_session_instead_of_resetting_forever(monkeypatch):
    """When Google has flagged the IP, every fresh profile is blocked too, so resetting
    cannot help (owner 2026-10-29: 183 sign-in walls, 3 usable answers, "reset #44").
    The session must give up so the step's own handling takes over."""
    from vendor_intel.scraping import google_ai_mode as gam
    s = gam.AiModeSession.__new__(gam.AiModeSession)
    s.flagged_blocks = gam._MAX_FLAGGED_BLOCKS - 1
    assert s.flagged_blocks < gam._MAX_FLAGGED_BLOCKS
    s.flagged_blocks += 1
    assert s.flagged_blocks >= gam._MAX_FLAGGED_BLOCKS, "threshold must trip"
    assert gam._MAX_FLAGGED_BLOCKS >= 3, "a couple of walls are normal; do not trip early"


def test_the_threshold_is_tunable_by_env(monkeypatch):
    import importlib
    from vendor_intel.scraping import google_ai_mode as gam
    monkeypatch.setenv("GOOGLE_AI_MODE_MAX_FLAGGED_BLOCKS", "2")
    importlib.reload(gam)
    try:
        assert gam._MAX_FLAGGED_BLOCKS == 2
    finally:
        monkeypatch.delenv("GOOGLE_AI_MODE_MAX_FLAGGED_BLOCKS", raising=False)
        importlib.reload(gam)


def test_a_block_page_gets_time_to_be_solved_before_any_reset(monkeypatch):
    """Owner 2026-11-14: take time to solve the CAPTCHA, do not close the browser at once.
    The wait comes before the cookie / profile reset on both block paths."""
    import inspect
    from vendor_intel.scraping import google_ai_mode as gam
    src = inspect.getsource(gam.AiModeSession.ask)
    wait = src.index("_wait_for_block_page_clear(f\"Google '{flagged}' page\"")
    assert wait < src.index('self._reopen_after_block(_sorry_cool_off(3 - verify_left))')
    sorry = src.index('_wait_for_block_page_clear("Google /sorry/')
    assert sorry < src.index("self._reopen_after_block(", sorry)
    monkeypatch.delenv("GOOGLE_AI_MODE_CAPTCHA_WAIT", raising=False)
    assert gam._captcha_wait() == 120.0
    monkeypatch.setenv("GOOGLE_AI_MODE_CAPTCHA_WAIT", "0")
    assert gam._captcha_wait() == 0.0


def test_a_cleared_block_page_is_reported_solved():
    from vendor_intel.scraping import google_ai_mode as gam
    s = gam.AiModeSession.__new__(gam.AiModeSession)

    class _NoButton:
        def count(self): return 0

    class P:
        url = "https://www.google.com/search?q=x"
        def get_by_role(self, *a, **k): return _NoButton()
        def wait_for_timeout(self, ms): pass
        def inner_text(self, sel, timeout=0): return "Ethanolamine producers include BASF and Dow." * 20
    s._page = P()
    assert s._wait_for_block_page_clear("test", 5) is True
    assert s._wait_for_block_page_clear("test", 0) is False


def test_the_sign_in_wall_gets_a_fresh_profile_at_once():
    """Owner 2026-11-15 (screenshot): sign-in wall -> close, delete profile + cookies, new browser."""
    import inspect
    from vendor_intel.scraping import google_ai_mode as gam
    src = inspect.getsource(gam.AiModeSession.ask)
    block = src.split('if flagged.startswith("Sign in"):', 1)[1][:500]
    assert 'reset_profile(reason="signin")' in block
    assert "_wait_for_block_page_clear" not in block


def test_a_machine_wide_pause_does_not_close_the_browser():
    """Owner 2026-11-15: browsers stay open (and keep their CAPTCHA chance) through a pause."""
    import inspect
    from vendor_intel.scraping import google_ai_mode as gam
    src = inspect.getsource(gam.AiModeSession.ask)
    head = src.split("_ip_backoff_wait()", 1)[0]
    assert "self.close()" not in head.split("while attempts_left > 0:", 1)[1]


def test_a_block_page_never_clears_the_cookies():
    """Owner 2026-11-15: cookie-less sessions drew the sign-in wall; cookies are kept."""
    import inspect
    from vendor_intel.scraping import google_ai_mode as gam
    src = inspect.getsource(gam.AiModeSession.ask)
    assert "reset_session(reason=f\"Google '{flagged}' page\")" not in src


def test_a_crashed_profile_is_marked_clean_before_launch(tmp_path):
    """Owner 2026-11-15: no "Restore pages?" bubble on relaunched browsers."""
    import json
    from vendor_intel.scraping import google_ai_mode as gam
    d = tmp_path / "Default"
    d.mkdir()
    (d / "Preferences").write_text(json.dumps({"profile": {"exit_type": "Crashed"}}), encoding="utf-8")
    gam._mark_profile_exited_cleanly(tmp_path)
    data = json.loads((d / "Preferences").read_text(encoding="utf-8"))
    assert data["profile"]["exit_type"] == "Normal" and data["session"]["restore_on_startup"] == 5
