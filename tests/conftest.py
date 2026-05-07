from __future__ import annotations

import os
import tempfile
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
APP_DIR = ROOT / "app"
TEST_TMP = ROOT / ".pytest-tmp"

TEST_TMP.mkdir(exist_ok=True)

for name in ("TMPDIR", "TEMP", "TMP"):
    os.environ.setdefault(name, str(TEST_TMP))

tempfile.tempdir = str(TEST_TMP)

if str(APP_DIR) not in sys.path:
    sys.path.insert(0, str(APP_DIR))
