#!/usr/bin/env python3
"""Start the AI Overview bridge that the Chrome extension talks to.

  python run_ai_bridge.py
  python run_ai_bridge.py --market "Smartphone Market" --port 15552

Then load `extension/` at chrome://extensions (Developer mode -> Load unpacked),
open the popup, and press Start. See AI_OVERVIEW.md.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "src"))

from vendor_intel.evidence.bridge import main

if __name__ == "__main__":
    main()
