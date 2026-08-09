#!/usr/bin/env python3
"""Add-on entrypoint wrapper (keeps PATH / PYTHONPATH simple under s6)."""

from __future__ import annotations

import os
import sys

APP_ROOT = os.environ.get("XIAOMUSIC_APP_ROOT", "/app")
if APP_ROOT not in sys.path:
    sys.path.insert(0, APP_ROOT)

os.chdir(APP_ROOT)

from xiaomusic.ha_main import main  # noqa: E402

if __name__ == "__main__":
    main()
