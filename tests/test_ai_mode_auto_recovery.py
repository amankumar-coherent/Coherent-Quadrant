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

        def reset_session():
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
    # escalating wait on the fresh profile: 120 s, then 240 s
    assert [c[2] for c in s.calls] == [120.0, 240.0]


def test_quota_gives_up_after_the_reset_budget(make_session, monkeypatch):
    monkeypatch.setenv("GOOGLE_AI_MODE_MAX_RESETS", "2")
    s = make_session([QUOTA, QUOTA, QUOTA, GOOD])
    with pytest.raises(gam.AiModeCaptcha):
        s.ask("q")
    assert len(s.calls) == 2


def test_no_answer_escalates_to_a_full_profile_reset(make_session):
    s = make_session([NOANSWER, NOANSWER, NOANSWER, GOOD])
    assert s.ask("q", retries=3) == GOOD
    kinds = [c[0] for c in s.calls]
    # 1st: reword only; 2nd: cookies + relaunch; 3rd: whole profile reset
    assert kinds == ["reset_session", "reset_profile"]
    assert s.calls[-1][1] == "noanswer"


def test_a_good_answer_clears_the_no_answer_streak(make_session):
    s = make_session([NOANSWER, GOOD])
    assert s.ask("q") == GOOD
    assert s.soft_failures == 0 and s.calls == []


def test_crashed_browser_is_reopened_and_query_retried(make_session):
    s = make_session([RuntimeError("Target page, context or browser has been closed"), GOOD])
    assert s.ask("q") == GOOD
    assert s.calls == [("reopen_browser",)]


def test_ordinary_navigation_error_does_not_reopen(make_session):
    s = make_session([RuntimeError("net::ERR_TIMED_OUT"), GOOD])
    assert s.ask("q") == GOOD
    assert s.calls == []
