"""Markets file parsing for the parallel launcher."""
import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("rmp", ROOT / "scripts" / "run_markets_parallel.py")
rmp = importlib.util.module_from_spec(spec)
spec.loader.exec_module(rmp)


def test_markets_file_with_optional_country_and_dedupe(tmp_path):
    f = tmp_path / "m.txt"
    f.write_text("Global Smart Ring Market\n# comment\n\nSmart Ring Market | India\n"
                 "Hearing Aids Market\tgermany\nGlobal Smart Ring Market\n", encoding="utf-8")
    got = rmp.read_markets(f, ["Pet Food Market"], "global")
    assert got == [("Pet Food Market", "global"), ("Global Smart Ring Market", "global"),
                   ("Smart Ring Market", "india"), ("Hearing Aids Market", "germany")]


def test_same_market_different_country_is_two_runs():
    got = rmp.read_markets(None, ["Smart Ring Market", "Smart Ring Market | india"], "global")
    assert len(got) == 2
