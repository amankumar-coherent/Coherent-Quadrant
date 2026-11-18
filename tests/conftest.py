import pytest


@pytest.fixture(autouse=True)
def _no_real_browser(monkeypatch, tmp_path_factory):
    """Force the Google AI Mode backend off for every test.

    Without this, a test that forgets to mock the backend launches real Chrome
    windows and hangs indefinitely instead of failing on an assertion.
    """
    monkeypatch.setenv("GOOGLE_AI_MODE_ENABLED", "false")
    # Extension tests use temp profiles; keep the repo's bundled extensions/
    # out of them unless a test opts back in.
    monkeypatch.setenv("GOOGLE_AI_MODE_BUNDLED_EXTENSIONS", "false")
    # The machine-wide Google back-off writes a shared file in data/ that a live run
    # reads: a test's fake block must never pause a real run.
    monkeypatch.setenv("GOOGLE_AI_MODE_IP_BACKOFF", "0")
    # Never switch the real VPN from a test.
    for name in ("GOOGLE_AI_MODE_ROTATE_CMD", "GOOGLE_AI_MODE_WIREGUARD_CONFIGS", "GOOGLE_AI_MODE_PROXY"):
        monkeypatch.delenv(name, raising=False)
    # The Proton VPN hooks read a shared folder a live guard writes (state.json, PAUSE):
    # a test must never see a real switch and reset or pause a fake browser.
    monkeypatch.setenv("VPN_DIR", str(tmp_path_factory.mktemp("vpn")))
    # A machine's .env may point at its own extension folder; tests must not
    # depend on it.
    monkeypatch.delenv("GOOGLE_AI_MODE_EXTENSIONS", raising=False)
