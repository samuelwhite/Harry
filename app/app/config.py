# /opt/harry/brain/app/config.py
from __future__ import annotations

import os
from pathlib import Path

DATA_DIR = Path(os.environ.get("HARRY_DATA_DIR", "/data"))
DB_PATH = Path(os.environ.get("HARRY_DB", str(DATA_DIR / "harry.db")))
