import pytest


@pytest.fixture(autouse=True)
def _no_real_browser(monkeypatch):
    """Force the Google AI Mode backend off for every test.

    Without this, a test that forgets to mock the backend launches real Chrome
    windows and hangs indefinitely instead of failing on an assertion.
    """
    monkeypatch.setenv("GOOGLE_AI_MODE_ENABLED", "false")
    # Extension tests use temp profiles; keep the repo's bundled extensions/
    # out of them unless a test opts back in.
    monkeypatch.setenv("GOOGLE_AI_MODE_BUNDLED_EXTENSIONS", "false")
