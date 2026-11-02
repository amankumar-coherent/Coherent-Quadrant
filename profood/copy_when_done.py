#!/usr/bin/env python3
"""Copy each finished market's <slug>_quadrant.json and <slug>_report.html into a folder.

    .venv\Scripts\python.exe profood\copy_when_done.py "<folder>" "India X Market" "India Y Market" ...

Polls until every named (country india) market has passed VERIFY (profood/watchdog.py's
`status`), copying each once; existing files are never overwritten.
"""
from __future__ import annotations

import shutil
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "profood"))
import watchdog as wd  # noqa: E402

from vendor_intel.pipeline.web_expand import default_output_dir  # noqa: E402


def main() -> int:
    dest, markets = Path(sys.argv[1]), sys.argv[2:]
    todo = list(markets)
    while todo:
        for name in list(todo):
            out = Path(default_output_dir(name, "india"))
            if wd.status(ROOT / "logs" / "parallel" / f"{out.name}.log") != "done":
                continue
            for f in (out / f"{out.name}_quadrant.json", out / f"{out.name}_report.html"):
                if f.exists() and not (dest / f.name).exists():
                    shutil.copy2(f, dest / f.name)
            print(f"[{time.strftime('%H:%M:%S')}] copied {name} -> {dest} "
                  f"({len(list(dest.glob('*_quadrant.json')))} json, {len(list(dest.glob('*_report.html')))} html)", flush=True)
            todo.remove(name)
        if todo:
            time.sleep(120)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
