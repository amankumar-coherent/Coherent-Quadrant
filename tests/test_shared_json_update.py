"""Several browsers write the same evidence file (gap-fill step): no lost fix, no damaged JSON."""
import json
from concurrent.futures import ThreadPoolExecutor

from vendor_intel.pipeline.quadrant_pipeline import update_json_locked


def test_concurrent_updates_keep_every_fix_and_valid_json(tmp_path):
    f = tmp_path / "param_detail_prescored_x.json"
    f.write_text(json.dumps({"A": {"x": {"parameters": {}}}}), encoding="utf-8")

    def worker(w: int) -> None:
        for i in range(15):
            def put(d, _k=f"w{w}_p{i}"):
                d["A"]["x"]["parameters"][_k] = {"score": 70, "assessed_on": "why " * 200}
            update_json_locked(f, put)

    with ThreadPoolExecutor(12) as pool:
        list(pool.map(worker, range(12)))
    data = json.loads(f.read_text(encoding="utf-8"))  # valid JSON
    assert len(data["A"]["x"]["parameters"]) == 12 * 15  # no update lost
    assert not list(tmp_path.glob("*.lock")) and not list(tmp_path.glob("*.tmp"))


def test_stale_lock_of_a_dead_holder_is_taken_over(tmp_path):
    import os
    import time

    f = tmp_path / "e.json"
    f.write_text("{}", encoding="utf-8")
    lock = tmp_path / "e.json.lock"
    lock.write_text("", encoding="utf-8")
    os.utime(lock, (time.time() - 600, time.time() - 600))
    update_json_locked(f, lambda d: d.update(ok=1), stale_after=30)
    assert json.loads(f.read_text(encoding="utf-8")) == {"ok": 1}
