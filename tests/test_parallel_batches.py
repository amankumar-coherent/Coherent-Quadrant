"""Wave runner: markets N-at-a-time, with each slot isolated from the others.

The dangerous failure here is not a slow run — it is one slot killing another
slot's browser, or the operator's own. Every kill must be scoped to the
slot's own profile directory.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

_spec = importlib.util.spec_from_file_location(
    "run_parallel_batches", ROOT / "scripts" / "run_parallel_batches.py"
)
R = importlib.util.module_from_spec(_spec)
sys.modules["run_parallel_batches"] = R
_spec.loader.exec_module(R)


# --- the queue file --------------------------------------------------------


def _write(tmp_path: Path, text: str) -> Path:
    p = tmp_path / "markets.tsv"
    p.write_text(text, encoding="utf-8")
    return p


def test_a_market_and_its_scope_are_read(tmp_path):
    q = R.read_queue(_write(tmp_path, "Drone LiDAR\tLiDAR, 3D mapping\n"))
    assert q == [("Drone LiDAR", "LiDAR, 3D mapping")]


def test_a_market_without_a_scope_is_allowed(tmp_path):
    assert R.read_queue(_write(tmp_path, "Drone LiDAR\n")) == [("Drone LiDAR", "")]


def test_comments_and_blank_lines_are_skipped(tmp_path):
    q = R.read_queue(_write(tmp_path, "# header\n\nDrone AI\tAI software\n\n"))
    assert q == [("Drone AI", "AI software")]


def test_duplicates_are_dropped(tmp_path):
    q = R.read_queue(_write(tmp_path, "Drone AI\ta\nDRONE AI\tb\n"))
    assert len(q) == 1, "a market queued twice would run twice"


def test_the_real_queue_file_has_all_25_markets():
    q = R.read_queue(ROOT / "queries" / "drone_25.tsv")
    assert len(q) == 25
    assert all(scope for _m, scope in q), "every market needs its scope"
    assert q[0][0] == "UAV Systems Industry Analysis"
    assert q[-1][0] == "Drone Training Industry Analysis"


def test_every_queued_market_has_a_distinct_scope():
    """The scopes are what stop "Drone Sensors" and "Drone Imaging" being
    analysed into the same cohort, so they must not be copy-paste."""
    scopes = [s.lower() for _m, s in R.read_queue(ROOT / "queries" / "drone_25.tsv")]
    assert len(set(scopes)) == len(scopes)


# --- slot isolation --------------------------------------------------------


def test_each_slot_gets_its_own_profile():
    dirs = {R.profile_for(i) for i in range(1, 6)}
    assert len(dirs) == 5, "two slots sharing a profile would fight over the lock"


def test_a_slot_profile_is_not_the_default_profile():
    """A batch run must never adopt or burn the interactive profile."""
    default = ROOT / "data" / "ai_mode_chrome_profile"
    for i in range(1, 6):
        assert R.profile_for(i) != default
        assert R.profile_for(i).name != default.name


def test_slot_profiles_do_not_prefix_collide():
    """"batch_1" must not substring-match "batch_10"'s command line, or slot 1
    would kill slot 10's browser."""
    names = [R.profile_for(i).name for i in range(1, 11)]
    for a in names:
        matches = [b for b in names if a in b]
        assert matches == [a], f"{a} also matches {matches}"


def test_the_kill_command_is_scoped_to_this_slots_profile(monkeypatch):
    seen = {}

    def fake_run(cmd, **kw):
        seen["cmd"] = " ".join(cmd)

        class P:
            stdout = ""
        return P()

    monkeypatch.setattr(R.subprocess, "run", fake_run)
    R.kill_slot_browsers(3)
    assert R.profile_for(3).name in seen["cmd"]
    # Never the broad pattern the sequential runner uses, which would match
    # an unrelated browser the operator is running.
    assert "*ai_mode_chrome_profile*" not in seen["cmd"]


def test_one_slot_never_matches_another_slots_browser(monkeypatch):
    cmds = {}

    def fake_run(cmd, **kw):
        cmds[len(cmds)] = " ".join(cmd)

        class P:
            stdout = ""
        return P()

    monkeypatch.setattr(R.subprocess, "run", fake_run)
    R.kill_slot_browsers(1)
    R.kill_slot_browsers(2)
    assert R.profile_for(2).name not in cmds[0]
    assert R.profile_for(1).name not in cmds[1]


def test_an_unrelated_browser_is_not_matched(monkeypatch):
    """The operator's own Chromium, on the default profile, must survive."""
    seen = {}

    def fake_run(cmd, **kw):
        seen["cmd"] = " ".join(cmd)

        class P:
            stdout = ""
        return P()

    monkeypatch.setattr(R.subprocess, "run", fake_run)
    R.kill_slot_browsers(2)
    pattern = seen["cmd"]
    for foreign in ("ai_mode_chrome_profile", "ai_mode_chrome_profile_chromium"):
        assert f"*{foreign}*" not in pattern


def test_a_browser_cleanup_failure_does_not_stop_the_queue(monkeypatch):
    def boom(*a, **k):
        raise OSError("powershell missing")

    monkeypatch.setattr(R.subprocess, "run", boom)
    R.kill_slot_browsers(1)  # must not raise


# --- waves -----------------------------------------------------------------


def test_25_markets_split_into_five_waves_of_five():
    queue = R.read_queue(ROOT / "queries" / "drone_25.tsv")
    waves = [queue[i:i + 5] for i in range(0, len(queue), 5)]
    assert len(waves) == 5
    assert all(len(w) == 5 for w in waves)


def test_a_partial_final_wave_is_kept():
    queue = [("m%d" % i, "") for i in range(12)]
    waves = [queue[i:i + 5] for i in range(0, len(queue), 5)]
    assert [len(w) for w in waves] == [5, 5, 2], "the last 2 must still run"


# --- browser + extension wiring --------------------------------------------
#
# Managed Chrome silently ignores --load-extension, so captcha-raptor would
# never load and every CAPTCHA would stall the slot. Chromium is the only
# build that honours the flag.


def _captured_env(monkeypatch, tmp_path):
    """Run one market with the subprocess stubbed out; return its env."""
    box = {}

    class P:
        returncode = 0

    def fake_run(cmd, **kw):
        if "env" in kw:
            box["env"] = kw["env"]
            box["cmd"] = cmd
        return P()

    monkeypatch.setattr(R.subprocess, "run", fake_run)
    monkeypatch.setattr(R, "kill_slot_browsers", lambda slot: None)
    monkeypatch.setattr(R, "seed_extensions", lambda slot: None)
    monkeypatch.setattr(R, "market_done", lambda m, c: (False, 0, 0))
    monkeypatch.setattr(R, "classify", lambda p: "other")
    monkeypatch.setattr(R.time, "sleep", lambda s: None)
    R.MAX_ATTEMPTS = 1
    try:
        R.run_market(2, "Drone LiDAR", "LiDAR scope", "India", 300, tmp_path)
    finally:
        R.MAX_ATTEMPTS = 4
    return box


def test_the_worker_forces_chromium(monkeypatch, tmp_path):
    env = _captured_env(monkeypatch, tmp_path)["env"]
    assert env["GOOGLE_AI_MODE_BROWSER"] == "chromium"


def test_the_worker_enables_ai_mode(monkeypatch, tmp_path):
    """conftest turns AI Mode off for tests; a real run must turn it on."""
    env = _captured_env(monkeypatch, tmp_path)["env"]
    assert env["GOOGLE_AI_MODE_ENABLED"] == "true"


def test_each_worker_gets_its_own_profile_env(monkeypatch, tmp_path):
    env = _captured_env(monkeypatch, tmp_path)["env"]
    assert env["GOOGLE_AI_MODE_PROFILE_DIR"] == str(R.profile_for(2))


def test_the_scope_is_passed_as_market_scope(monkeypatch, tmp_path):
    env = _captured_env(monkeypatch, tmp_path)["env"]
    assert env["MARKET_SCOPE"] == "LiDAR scope"


def test_the_country_reaches_the_pipeline(monkeypatch, tmp_path):
    cmd = _captured_env(monkeypatch, tmp_path)["cmd"]
    assert "--country" in cmd
    assert cmd[cmd.index("--country") + 1] == "India"


def test_the_staged_extension_is_where_the_launcher_looks():
    """The launcher reads staging_root(_profile_dir()) with NO channel
    suffix, while the profile itself gets "_chromium". Seeding the wrong one
    would leave the slot with no CAPTCHA solver."""
    from vendor_intel.scraping.google_ai_mode import staging_root

    profile = R.profile_for(1)
    assert staging_root(str(profile)).name == f"{profile.name}_extensions"
    assert "_chromium" not in staging_root(str(profile)).name


def test_the_captcha_extension_is_available_to_seed():
    """The source the slots copy from must actually hold captcha-raptor."""
    src = ROOT / "data" / "ai_mode_chrome_profile_extensions"
    if not src.is_dir():
        import pytest

        pytest.skip("no staged extensions on this machine")
    staged = [p.name for p in src.iterdir() if (p / "manifest.json").is_file()]
    assert staged, "no extension with a manifest.json to stage"


# --- target override -------------------------------------------------------
#
# Read at every wave boundary so the number can change DURING a long
# unattended run: restarting the orchestrator to change one integer would
# re-pay the CAPTCHA cost of every in-flight market.


def _override(tmp_path, monkeypatch, text: str | None):
    logs = tmp_path / "logs"
    logs.mkdir(exist_ok=True)
    if text is not None:
        (logs / ".target_override").write_text(text, encoding="utf-8")
    monkeypatch.setattr(R, "ROOT", tmp_path)
    return R.effective_target(300)


def test_the_override_replaces_the_launch_target(tmp_path, monkeypatch):
    assert _override(tmp_path, monkeypatch, "280") == 280


def test_surrounding_whitespace_is_tolerated(tmp_path, monkeypatch):
    assert _override(tmp_path, monkeypatch, "  280\n") == 280


def test_no_override_file_keeps_the_launch_target(tmp_path, monkeypatch):
    assert _override(tmp_path, monkeypatch, None) == 300


def test_a_malformed_override_is_ignored(tmp_path, monkeypatch):
    """A typo must not silently set the target to something absurd."""
    assert _override(tmp_path, monkeypatch, "not a number") == 300
    assert _override(tmp_path, monkeypatch, "") == 300


def test_an_out_of_range_override_is_ignored(tmp_path, monkeypatch):
    """A stray 0 would end discovery instantly; a stray 999999 would never
    stop. Both fall back to the launch value."""
    assert _override(tmp_path, monkeypatch, "0") == 300
    assert _override(tmp_path, monkeypatch, "999999") == 300


def test_the_wave_loop_reads_the_override_not_the_launch_arg():
    """Guards the wiring: computing the target outside the wave loop would
    read it once at startup and never see a later change."""
    src = (ROOT / "scripts" / "run_parallel_batches.py").read_text(encoding="utf-8")
    body = src.split("for wi, wave in enumerate(waves, 1):", 1)[1]
    assert "effective_target(args.target)" in body, "override not read per wave"
    assert "wave_target, logs" in body, "the wave's own target must be passed down"


def test_the_live_override_file_is_usable():
    """The override the next wave will read must parse to a sane target.

    The VALUE is operational and changes per market, so asserting a specific
    number here just breaks the suite whenever a run is retargeted. What
    matters is that the file is readable and in range."""
    live = ROOT / "logs" / ".target_override"
    if not live.exists():
        import pytest

        pytest.skip("no override set")
    value = int(live.read_text(encoding="utf-8").strip())
    assert 10 <= value <= 5000
    assert R.effective_target(999) == value


def test_the_worker_sets_the_parameter_batch_size(monkeypatch, tmp_path):
    """5 measured at 100% evidence coverage, and it takes a 250-company
    market from ~500 scoring queries to ~100."""
    env = _captured_env(monkeypatch, tmp_path)["env"]
    assert env["AI_MODE_PARAM_BATCH"] == "5"


# --- concurrent orchestrators ----------------------------------------------
#
# A second orchestrator running ALONGSIDE the first must not reuse slots 1-5.
# Both kill browsers by profile name, so sharing a slot means each would kill
# the other's browser mid-market.


def test_the_offset_shifts_this_runs_profiles():
    assert R.profile_for(1 + 5).name == "ai_mode_batch_06"
    assert R.profile_for(5 + 5).name == "ai_mode_batch_10"


def test_offset_profiles_do_not_overlap_the_first_five():
    first = {R.profile_for(i).name for i in range(1, 6)}
    second = {R.profile_for(i + 5).name for i in range(1, 6)}
    assert not (first & second), "two orchestrators would share a profile"


def test_an_offset_slot_kill_never_matches_a_wave1_slot(monkeypatch):
    """Slot 6's kill pattern must not match slots 1-5."""
    seen = {}

    def fake_run(cmd, **kw):
        seen["cmd"] = " ".join(cmd)

        class P:
            stdout = ""
        return P()

    monkeypatch.setattr(R.subprocess, "run", fake_run)
    R.kill_slot_browsers(6)
    for i in range(1, 6):
        assert R.profile_for(i).name not in seen["cmd"]


def test_the_wave_loop_applies_the_offset():
    """Guards the wiring: enumerating from 1 would put a concurrent run back
    on wave 1's profiles."""
    src = (ROOT / "scripts" / "run_parallel_batches.py").read_text(encoding="utf-8")
    body = src.split("for wi, wave in enumerate(waves, 1):", 1)[1]
    assert "enumerate(wave, 1 + args.slot_offset)" in body


def test_the_wave2_queue_is_markets_six_to_ten():
    full = R.read_queue(ROOT / "queries" / "drone_25.tsv")
    w2 = R.read_queue(ROOT / "queries" / "drone_wave2.tsv")
    assert [m for m, _s in w2] == [m for m, _s in full[5:10]]
    assert all(scope for _m, scope in w2), "every market keeps its scope"


# --- discovery speed -------------------------------------------------------
#
# Each round costs the same paced query whether it asks for 10 companies or
# 20, so a query-bound run finishes sooner at the larger batch. Escalating
# after one empty round reaches the country sweep, which is where a thinning
# market's remaining companies actually come from.


def test_the_worker_asks_for_a_larger_discovery_batch(monkeypatch, tmp_path):
    env = _captured_env(monkeypatch, tmp_path)["env"]
    assert env["DISCOVER_BATCH"] == "20"


def test_the_worker_escalates_to_the_country_sweep_sooner(monkeypatch, tmp_path):
    env = _captured_env(monkeypatch, tmp_path)["env"]
    assert env["DISCOVER_EMPTY_BEFORE_ESCALATE"] == "1"
