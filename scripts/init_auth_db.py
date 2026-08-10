#!/usr/bin/env python3
"""Create auth tables in Postgres.

  .venv\\Scripts\\python.exe scripts/init_auth_db.py
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from vendor_intel.placeholders.load_keys import apply_env_overrides

apply_env_overrides()


def main() -> None:
    from vendor_intel.auth.config import get_auth_settings
    from vendor_intel.auth.db import init_db

    settings = get_auth_settings()
    print(f"Connecting to: {settings.database_url.split('@')[-1]}")
    init_db()
    print("Auth tables ready: users, otp_challenges, sessions, auth_events")


if __name__ == "__main__":
    main()
