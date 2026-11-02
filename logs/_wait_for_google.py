#!/usr/bin/env python3
"""Wait until Google answers this machine again, then start the market run.

    .venv/Scripts/python.exe logs/_wait_for_google.py "Fashion E-commerce Market" japan

Google blocks a whole machine (sign-in wall + CAPTCHAs on every fresh profile), and a
reset cannot clear that -- only time can. Rather than run ten browsers into the block,
this probes with ONE browser and one short query every PROBE_EVERY seconds, and starts
the real run the first time a probe comes back with an answer. Nothing market-specific:
the market, country and run arguments are the command line.
"""
from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

PROBE_EVERY = int(os.getenv("PROBE_EVERY") or "1200")   # 20 minutes between probes
MAX_WAIT = int(os.getenv("MAX_WAIT") or "43200")        # give up after 12 hours
PROBE_QUESTION = ('Name three companies that sell fashion online in Japan. Reply with a JSON '
                  'object {"companies":["...","...","..."]} and nothing else.')


def log(msg: str) -> None:
    line = f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] {msg}"
    print(line, flush=True)
    with (ROOT / "logs" / "wait_for_google.log").open("a", encoding="utf-8") as fh:
        fh.write(line + "\n")


def probe() -> bool:
    """One browser, one query. True when Google actually answered."""
    env = {**os.environ, "PYTHONPATH": str(ROOT / "src"), "PYTHONIOENCODING": "utf-8",
           "GOOGLE_AI_MODE_ENABLED": "true", "GOOGLE_AI_MODE_BROWSER": "chromium",
           "GOOGLE_AI_MODE_PROFILE_DIR": str(ROOT / "data" / "ai_mode_probe"),
           # one probe must not spend ages resetting; fail fast and wait instead
           "GOOGLE_AI_MODE_MAX_FLAGGED_BLOCKS": "2"}
    code = (
        "import sys\n"
        "from vendor_intel.scraping.google_ai_mode import AiModeSession\n"
        "s = AiModeSession()\n"
        "try:\n"
        f"    t = s.ask({PROBE_QUESTION!r}, retries=1, captcha_rounds=1)\n"
        "    sys.exit(0 if (t or '').strip() else 1)\n"
        "except Exception:\n"
        "    sys.exit(1)\n"
        "finally:\n"
        "    try: s.close()\n"
        "    except Exception: pass\n"
    )
    try:
        r = subprocess.run([sys.executable, "-c", code], cwd=str(ROOT), env=env,
                           timeout=300, capture_output=True, text=True)
        return r.returncode == 0
    except subprocess.TimeoutExpired:
        return False


def main() -> int:
    market, country, *run_args = sys.argv[1:]
    started = time.time()
    attempt = 0
    while time.time() - started < MAX_WAIT:
        attempt += 1
        ok = probe()
        waited = int((time.time() - started) / 60)
        log(f"probe {attempt}: {'ANSWERED' if ok else 'still blocked'} ({waited} min waited)")
        if ok:
            cmd = [sys.executable, str(ROOT / "profood" / "supervise_market.py"), market,
                   "--country", country] + run_args
            log(f"Google is answering again -- starting the run: {' '.join(cmd[2:])}")
            out = (ROOT / "logs" / "supervise_japan_fashion.out").open("a", encoding="utf-8")
            subprocess.Popen(cmd, cwd=str(ROOT),
                             env={**os.environ, "PYTHONPATH": str(ROOT / "src"),
                                  "PYTHONIOENCODING": "utf-8"},
                             stdout=out, stderr=subprocess.STDOUT)
            return 0
        time.sleep(PROBE_EVERY)
    log(f"gave up: still blocked after {MAX_WAIT // 3600} hours")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
