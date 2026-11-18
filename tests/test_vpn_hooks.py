"""Proton VPN hooks in google_ai_mode (owner 2026-11-17): no guard = no effect;
after a switch each browser starts once on a fresh profile; blocks are logged."""
import json

from vendor_intel.scraping import google_ai_mode as g


def _session(monkeypatch, tmp_path):
    prof = tmp_path / "profile"
    monkeypatch.setattr(g, "profile_dir_for", lambda channel: str(prof))
    s = g.AiModeSession()
    calls = []
    monkeypatch.setattr(s, "reset_profile", lambda **kw: calls.append(kw.get("reason")))
    return s, prof, calls


def test_no_guard_does_nothing(monkeypatch, tmp_path):
    monkeypatch.setenv("VPN_DIR", str(tmp_path / "vpn"))
    s, prof, calls = _session(monkeypatch, tmp_path)
    (prof / "Default").mkdir(parents=True)
    s._vpn_hooks()
    assert calls == [] and not (prof / ".vpn_gen").exists()


def test_fresh_profile_once_per_switch(monkeypatch, tmp_path):
    vpn = tmp_path / "vpn"
    vpn.mkdir()
    monkeypatch.setenv("VPN_DIR", str(vpn))
    (vpn / "state.json").write_text(json.dumps({"switches": 3}))
    s, prof, calls = _session(monkeypatch, tmp_path)
    (prof / "Default").mkdir(parents=True)
    s._vpn_hooks()
    s._vpn_hooks()
    assert calls == ["vpn3"]
    (vpn / "state.json").write_text(json.dumps({"switches": 4}))
    s._vpn_hooks()
    assert calls == ["vpn3", "vpn4"]


def test_new_profile_is_not_reset(monkeypatch, tmp_path):
    vpn = tmp_path / "vpn"
    vpn.mkdir()
    monkeypatch.setenv("VPN_DIR", str(vpn))
    (vpn / "state.json").write_text(json.dumps({"switches": 1}))
    s, prof, calls = _session(monkeypatch, tmp_path)
    s._vpn_hooks()
    assert calls == [] and (prof / ".vpn_gen").read_text() == "1"


def test_block_report_line(monkeypatch, tmp_path):
    monkeypatch.setenv("VPN_DIR", str(tmp_path / "vpn"))
    g.vpn_report_block("signin")
    line = (tmp_path / "vpn" / "blocks.log").read_text().split()
    assert line[2] == "signin" and len(line) == 3
