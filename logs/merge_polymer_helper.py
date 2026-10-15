"""Merge the polymer-focused helper search into Global Medical Films Market (owner 2026-10-12).

The helper market ("Global Medical-Grade Polymer Materials Market") ran discovery and
verification with the SAME polymer-only brief; its verified companies are Medical Films'
players. Adds the new ones to Medical Films' verified list, then marks discovery done.
"""
import json
import shutil
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from vendor_intel.pipeline.quadrant_pipeline import dedupe_companies, norm_name, row_name  # noqa: E402
from vendor_intel.pipeline.web_expand import default_output_dir  # noqa: E402

MF = Path(default_output_dir("Global Medical Films Market", "global"))
H = Path(default_output_dir("Global Medical-Grade Polymer Materials Market", "global"))
ck = MF / "chatgpt_checkpoint_batch_all.json"
shutil.copy(ck, MF / "_pipeline" / f"checkpoint_before_polymer_merge_{time.strftime('%H%M%S')}.json")
mf = json.loads(ck.read_text(encoding="utf-8"))
hp = json.loads((H / "chatgpt_checkpoint_batch_all.json").read_text(encoding="utf-8"))
have = {norm_name(row_name(r)) for r in mf["data"]["verified"]}
new = [r for r in hp["data"].get("verified") or [] if norm_name(row_name(r)) not in have]
mf["data"]["verified"] += new
seen_rej = {norm_name(str(r.get("name"))) for r in mf["data"].get("rejected_mid") or []}
mf["data"].setdefault("rejected_mid", []).extend(
    r for r in hp["data"].get("rejected_mid") or [] if norm_name(str(r.get("name"))) not in seen_rej)
ck.write_text(json.dumps(mf, ensure_ascii=False), encoding="utf-8")
for m in ("country_steps_done", "verify_only_done"):
    (MF / "_pipeline" / m).write_text("done\n", encoding="utf-8")
print(f"[merge] +{len(new)} verified from the polymer search -> "
      f"{len(dedupe_companies(mf['data']['verified'])[0])} Medical Films companies", flush=True)
