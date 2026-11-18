"""IP switching on a Google block (ip_rotate + the shared pause in google_ai_mode)."""
from __future__ import annotations

from vendor_intel.scraping import google_ai_mode as gam
from vendor_intel.scraping import ip_rotate


def _setup(monkeypatch, tmp_path, ips):
    monkeypatch.setenv("GOOGLE_AI_MODE_ROTATE_STATE", str(tmp_path / "state.json"))
    monkeypatch.setenv("GOOGLE_AI_MODE_ROTATE_CMD", "switch-vpn")
    seq = list(ips)
    monkeypatch.setattr(ip_rotate, "public_ip", lambda timeout=6.0: seq.pop(0) if len(seq) > 1 else seq[0])
    runs = []
    monkeypatch.setattr(ip_rotate, "_run", lambda cmd, shell=False, timeout=90.0: runs.append(cmd) or 0)
    monkeypatch.setattr(ip_rotate.time, "sleep", lambda s: None)
    return runs


def test_switching_is_off_unless_configured(monkeypatch, tmp_path):
    monkeypatch.setenv("GOOGLE_AI_MODE_ROTATE_STATE", str(tmp_path / "state.json"))
    assert not ip_rotate.enabled()
    assert ip_rotate.rotate() is False


def test_rotate_runs_the_command_and_confirms_a_new_ip(monkeypatch, tmp_path):
    runs = _setup(monkeypatch, tmp_path, ["1.1.1.1", "2.2.2.2"])
    assert ip_rotate.rotate() is True
    assert runs == ["switch-vpn"]
    state = ip_rotate._read_state()
    assert state["ip"] == "2.2.2.2" and state["switches"] == 1
    # a second block straight after does not switch again before the new IP is tried
    assert ip_rotate.rotate() is False
    assert runs == ["switch-vpn"]


def test_an_unchanged_ip_is_not_a_switch(monkeypatch, tmp_path):
    _setup(monkeypatch, tmp_path, ["1.1.1.1"])
    assert ip_rotate.rotate(wait_for_new_ip=0.0) is False
    assert ip_rotate._read_state()["last_ok"] is False


def test_only_one_process_switches_at_a_time(monkeypatch, tmp_path):
    runs = _setup(monkeypatch, tmp_path, ["1.1.1.1", "2.2.2.2"])
    lock = ip_rotate._take_lock()
    assert lock is not None
    assert ip_rotate.rotate() is False and runs == []
    lock.unlink()


def test_wireguard_moves_to_the_next_config(monkeypatch, tmp_path):
    for name in ("de-1", "fr-2", "nl-3"):
        (tmp_path / f"{name}.conf").write_text("[Interface]\n", encoding="utf-8")
    monkeypatch.setenv("GOOGLE_AI_MODE_WIREGUARD_CONFIGS", str(tmp_path))
    monkeypatch.setattr(ip_rotate, "_is_admin", lambda: True)
    runs = []
    monkeypatch.setattr(ip_rotate, "_run", lambda cmd, shell=False, timeout=90.0: runs.append(cmd) or 0)
    monkeypatch.setattr(ip_rotate.time, "sleep", lambda s: None)
    state = {"tunnel": "fr-2"}
    assert ip_rotate._switch_wireguard(state) == "nl-3"
    assert runs[0][1:] == ["/uninstalltunnelservice", "fr-2"]
    assert runs[1][1] == "/installtunnelservice" and runs[1][2].endswith("nl-3.conf")


def test_a_block_switches_ip_and_shortens_the_pause(monkeypatch, tmp_path):
    _setup(monkeypatch, tmp_path, ["1.1.1.1", "2.2.2.2"])
    monkeypatch.setenv("GOOGLE_AI_MODE_IP_BACKOFF", "60")
    monkeypatch.setenv("GOOGLE_AI_MODE_IP_BACKOFF_FILE", str(tmp_path / "backoff.json"))
    monkeypatch.setenv("GOOGLE_AI_MODE_ROTATE_SETTLE", "15")
    assert gam._ip_backoff_note_block() == 15
    data = gam._ip_backoff_read()
    assert data["level"] == 1 and data["until"] - gam.time.time() <= 16
    # other browsers blocked in the same burst neither switch again nor lengthen the pause
    assert gam._ip_backoff_note_block() <= 15
    assert ip_rotate._read_state()["switches"] == 1


def test_without_admin_the_switch_goes_to_the_elevated_task(monkeypatch, tmp_path):
    (tmp_path / "de-1.conf").write_text("[Interface]\n", encoding="utf-8")
    monkeypatch.setenv("GOOGLE_AI_MODE_WIREGUARD_CONFIGS", str(tmp_path))
    monkeypatch.setattr(ip_rotate, "_is_admin", lambda: False)
    runs = []
    monkeypatch.setattr(ip_rotate, "_run", lambda cmd, shell=False, timeout=90.0: runs.append(cmd) or 0)
    assert ip_rotate._switch_wireguard({}) == "task CoherentQuadrant_VPN_Switch"
    assert runs[-1] == ["schtasks", "/run", "/tn", "CoherentQuadrant_VPN_Switch"]
    monkeypatch.setenv("IP_ROTATE_IN_TASK", "1")    # the task itself never re-launches itself
    assert ip_rotate._switch_wireguard({}) == ""


def test_proxy_list_is_shared_out_by_slot(monkeypatch):
    monkeypatch.delenv("GOOGLE_AI_MODE_PROXY", raising=False)
    assert gam._proxy_for("data/ai_mode_batch_41_chromium") == ""
    monkeypatch.setenv("GOOGLE_AI_MODE_PROXY", "socks5://127.0.0.1:1, socks5://127.0.0.1:2")
    assert gam._proxy_for("data/ai_mode_batch_41_chromium") == "socks5://127.0.0.1:2"
    assert gam._proxy_for("data/ai_mode_batch_42_chromium") == "socks5://127.0.0.1:1"
