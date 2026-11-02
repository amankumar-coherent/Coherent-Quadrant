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
