from __future__ import annotations

import os
import sys
from pathlib import Path


def _default_data_dir() -> Path:
    explicit = os.environ.get("HARRY_DATA_DIR")
    if explicit:
        return Path(explicit)

    if os.name == "nt":
        base = Path(os.environ.get("PROGRAMDATA", r"C:\ProgramData"))
        return base / "Harry" / "brain" / "data"

    return Path("/data")


DATA_DIR = _default_data_dir()
DB_PATH = Path(os.environ.get("HARRY_DB", str(DATA_DIR / "harry.db")))
