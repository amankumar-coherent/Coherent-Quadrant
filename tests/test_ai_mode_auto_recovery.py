"""Automatic recovery inside AiModeSession.ask():

* quota page             -> archive profile + fresh browser, retry (up to
                            GOOGLE_AI_MODE_MAX_RESETS per query, escalating wait)
* "AI response wasn't generated" -> reword, then cookies+relaunch, then a
                            full profile reset on the 3rd in a row
* browser crashed/closed -> reopen the browser and retry
"""
from __future__ import annotations

import pytest

from vendor_intel.scraping import google_ai_mode as gam

QUOTA = "You've reached the request limit for AI responses at the moment. Try again in a little while."
NOANSWER = "Something went wrong, and an AI response wasn't generated."
GOOD = "Here is the answer: Oura, Ultrahuman, RingConn. " * 3


class FakePage:
    def __init__(self, script):
        self.script = list(script)  # each item: text to render, or an Exception
        self.url = "https://www.google.com/search?udm=50"
        self.current = ""

    def goto(self, url, **kw):
        item = self.script.pop(0)
        if isinstance(item, Exception):
            raise item
        self.current = item

    def evaluate(self, js):
        return self.current


@pytest.fixture
def make_session(monkeypatch):
    monkeypatch.setattr(gam.time, "sleep", lambda s: None)

    def make(script):
        s = gam.AiModeSession()
        page = FakePage(script)
        s.calls = []
        s._page = page
        monkeypatch.setattr(s, "_ensure_browser", lambda: setattr(s, "_page", s._page or page))
        monkeypatch.setattr(s, "_pace", lambda: None)
        monkeypatch.setattr(s, "_wait_for_answer", lambda *a, **k: None)

        def reset_profile(*, reason="quota", cool_off=120.0):
            s.calls.append(("reset_profile", reason, cool_off))
            s.soft_failures = 0

        def reset_session(*, reason=""):
            s.calls.append(("reset_session",))

        def reopen_browser(*, reason=""):
            s.calls.append(("reopen_browser",))

        monkeypatch.setattr(s, "reset_profile", reset_profile)
        monkeypatch.setattr(s, "reset_session", reset_session)
        monkeypatch.setattr(s, "reopen_browser", reopen_browser)
        return s

    return make


def test_quota_resets_profile_and_retries_until_it_answers(make_session):
    s = make_session([QUOTA, QUOTA, GOOD])
    assert s.ask("q") == GOOD
    assert [c[:2] for c in s.calls] == [("reset_profile", "quota")] * 2
    # no cool-off on the fresh profile (owner 2026-10-11: only reset)
    assert [c[2] for c in s.calls] == [0.0, 0.0]


def test_quota_gives_up_after_the_reset_budget(make_session, monkeypatch):
    monkeypatch.setenv("GOOGLE_AI_MODE_MAX_RESETS", "2")
    s = make_session([QUOTA, QUOTA, QUOTA, GOOD])
    with pytest.raises(gam.AiModeCaptcha):
        s.ask("q")
    # 2 budgeted resets for this query, then one more so the NEXT query starts on a
    # fresh browser instead of the blocked one (owner 2026-11-07)
    assert [c[:2] for c in s.calls] == [("reset_profile", "quota")] * 3


def test_no_answer_escalates_to_a_full_profile_reset(make_session):
    s = make_session([NOANSWER, NOANSWER, NOANSWER, GOOD])
    assert s.ask("q", retries=3) == GOOD
    kinds = [c[0] for c in s.calls]
    # 1st and 2nd: cookies + relaunch; 3rd: whole profile reset
    assert kinds == ["reset_session", "reset_session", "reset_profile"]
    assert s.calls[-1][1] == "noanswer"


def test_a_good_answer_clears_the_no_answer_streak(make_session):
    s = make_session([NOANSWER, GOOD])
    assert s.ask("q") == GOOD
    # one relaunch for the failed page, then the good answer resets the streak
    assert s.soft_failures == 0 and s.calls == [("reset_session",)]


def test_crashed_browser_is_reopened_and_query_retried(make_session):
    s = make_session([RuntimeError("Target page, context or browser has been closed"), GOOD])
    assert s.ask("q") == GOOD
    assert s.calls == [("reopen_browser",)]


def test_ordinary_navigation_error_does_not_reopen(make_session):
    s = make_session([RuntimeError("net::ERR_TIMED_OUT"), GOOD])
    assert s.ask("q") == GOOD
    assert s.calls == []


def test_a_block_pauses_every_browser_and_doubles_until_google_answers(monkeypatch, tmp_path):
    """Google's block follows the IP (owner 2026-11-07): one browser's block pauses all of
    them through a shared file, the pause doubles per further block, and one good answer
    anywhere clears it."""
    monkeypatch.setenv("GOOGLE_AI_MODE_IP_BACKOFF", "60")
    monkeypatch.setenv("GOOGLE_AI_MODE_IP_BACKOFF_MAX", "1800")
    monkeypatch.setenv("GOOGLE_AI_MODE_IP_BACKOFF_FILE", str(tmp_path / "backoff.json"))
    clock = [1_000_000.0]
    monkeypatch.setattr(gam.time, "time", lambda: clock[0])
    waits = []
    for _ in range(7):
        waits.append(gam._ip_backoff_note_block())
        clock[0] = gam._ip_backoff_read()["until"] + 1   # the test search after the pause
    assert waits == [60, 120, 240, 480, 960, 1800, 1800]
    clock[0] -= 2                # back inside the last pause
    # ten browsers blocked in the same burst count once (owner 2026-11-09)
    level = gam._ip_backoff_read()["level"]
    for _ in range(9):
        gam._ip_backoff_note_block()
    assert gam._ip_backoff_read()["level"] == level
    gam._ip_backoff_note_ok()
    assert gam._ip_backoff_read()["level"] == 0
    gam._ip_backoff_wait()          # cleared: returns at once
    assert gam._ip_backoff_note_block() == 60   # starts over after a good answer


def test_after_a_pause_only_one_browser_tests_google(monkeypatch, tmp_path):
    monkeypatch.setenv("GOOGLE_AI_MODE_IP_BACKOFF", "60")
    monkeypatch.setenv("GOOGLE_AI_MODE_IP_BACKOFF_FILE", str(tmp_path / "backoff.json"))
    monkeypatch.setattr(gam.time, "sleep", lambda s: None)
    gam._ip_backoff_write({"level": 3, "until": gam.time.time() - 1, "updated": gam.time.time() - 300})
    gam._ip_backoff_wait()          # pause over: this browser claims the test search
    data = gam._ip_backoff_read()
    assert data["probe_until"] > gam.time.time() and data["probe_by"]
    assert gam._ip_backoff_active()  # the others still see the pause until it answers
    gam._ip_backoff_note_ok()
    assert not gam._ip_backoff_active()


def test_the_shared_pause_is_off_in_tests_by_default(tmp_path, monkeypatch):
    monkeypatch.setenv("GOOGLE_AI_MODE_IP_BACKOFF_FILE", str(tmp_path / "backoff.json"))
    assert gam._ip_backoff_note_block() == 0.0
    assert not (tmp_path / "backoff.json").exists()
