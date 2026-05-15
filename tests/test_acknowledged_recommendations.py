from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone

from fastapi.testclient import TestClient

import app.config as config
import app.main as main
from app.ui import db as dbmod
from app.ui import inventory as inventory_ui
from app.ui import node as node_ui


def _setup_temp_db(monkeypatch, tmp_path):
    db_path = tmp_path / "harry.db"
    monkeypatch.setattr(config, "DB_PATH", db_path, raising=False)
    monkeypatch.setattr(main, "DB_PATH", db_path, raising=False)
    monkeypatch.setattr(dbmod, "DB_PATH", str(db_path), raising=False)
    main._init_db()
    return db_path


def _insert_snapshot(db_path, payload):
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            "INSERT INTO ingest(ts, node, payload) VALUES(?, ?, ?)",
            (payload["ts"], payload["node"], json.dumps(payload)),
        )
        conn.commit()


def _sample_snapshot(*, node: str = "nas-1") -> dict:
    now = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    return {
        "schema_version": "0.2.3",
        "node": node,
        "ts": now,
        "facts": {"cpu_cores": 4},
        "metrics": {
            "cpu_load_1m": 0.6,
            "mem_used_pct": 25.0,
            "disk_used": [
                {
                    "mount": "/volume1",
                    "fs": "/dev/vg1/volume_1",
                    "device": "/dev/vg1/volume_1",
                    "total_b": 1000000000,
                    "used_b": 880000000,
                    "free_b": 120000000,
                    "used_pct": 88.0,
                }
            ],
            "temps_c": {},
            "gpu": [],
            "extensions": {},
        },
        "derived": {"health": {"state": "healthy", "worst_severity": "ok", "reasons": []}, "extensions": {}},
        "advice": [
            {
                "id": "disk_warn_now",
                "category": "storage",
                "severity": "warn",
                "message": "Storage is getting tight (88%).",
                "recommendation": "Plan a cleanup or storage upgrade soon.",
            }
        ],
    }


def test_acknowledged_warning_calms_overview_and_stays_visible(monkeypatch, tmp_path):
    db_path = _setup_temp_db(monkeypatch, tmp_path)
    snapshot = _sample_snapshot()
    _insert_snapshot(db_path, snapshot)

    with TestClient(main.app) as client:
        before = client.get("/").text
        assert "ADVICE · WARN" in before
        assert "Storage is getting tight (88%)." in before

        ack = client.post("/node/nas-1/ack?key=disk_warn_now&next=/", follow_redirects=False)
        assert ack.status_code == 303

        after = client.get("/").text
        assert "ADVICE · ACKED 1" in after
        assert "Everything looks calm." in after
        assert "ADVICE · WARN" not in after

        node_html = node_ui.render_node_detail("nas-1", hours=24)
        assert "Acknowledged warnings" in node_html
        assert "Restore warning" in node_html
        assert "Storage is getting tight (88%)." in node_html

        inventory_html = inventory_ui.render_inventory_page(hours=24, debug=False)
        assert "Recommendations" in inventory_html
        assert "Acknowledged warnings" in inventory_html

        diagnostics_html = client.get("/diagnostics").text
        assert "Acknowledged warnings" in diagnostics_html


def test_restore_warning_reactivates_overview_warning(monkeypatch, tmp_path):
    db_path = _setup_temp_db(monkeypatch, tmp_path)
    snapshot = _sample_snapshot()
    _insert_snapshot(db_path, snapshot)

    with TestClient(main.app) as client:
        assert client.post("/node/nas-1/ack?key=disk_warn_now&next=/", follow_redirects=False).status_code == 303
        acknowledged = client.get("/").text
        assert "ADVICE · ACKED 1" in acknowledged

        assert client.post("/node/nas-1/restore?key=disk_warn_now&next=/", follow_redirects=False).status_code == 303
        restored = client.get("/").text
        assert "ADVICE · WARN" in restored
        assert "ADVICE · ACKED 1" not in restored


def test_acknowledgements_persist_across_restart(monkeypatch, tmp_path):
    db_path = _setup_temp_db(monkeypatch, tmp_path)
    snapshot = _sample_snapshot()
    _insert_snapshot(db_path, snapshot)

    with TestClient(main.app) as client:
        assert client.post("/node/nas-1/ack?key=disk_warn_now&next=/", follow_redirects=False).status_code == 303

    # Simulate a Brain restart by opening a new client against the same DB.
    with TestClient(main.app) as client:
        html = client.get("/").text
        assert "ADVICE · ACKED 1" in html
        assert "Acknowledged warnings" in client.get("/diagnostics").text


def test_unknown_ack_key_does_not_break_rendering(monkeypatch, tmp_path):
    db_path = _setup_temp_db(monkeypatch, tmp_path)
    snapshot = _sample_snapshot()
    _insert_snapshot(db_path, snapshot)

    dbmod.acknowledge_recommendation("nas-1", "missing-key")

    with TestClient(main.app) as client:
        assert client.get("/").status_code == 200
        assert client.get("/node/nas-1").status_code == 200
