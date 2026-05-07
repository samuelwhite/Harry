from __future__ import annotations

import importlib


def test_db_path_prefers_harry_db_path(monkeypatch, tmp_path):
    monkeypatch.setenv("HARRY_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("HARRY_DB_PATH", str(tmp_path / "custom" / "harry.db"))

    import app.config as config

    config = importlib.reload(config)

    assert str(config.DB_PATH) == str(tmp_path / "custom" / "harry.db")

