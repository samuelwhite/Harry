from __future__ import annotations

import json
from datetime import datetime, timezone

from fastapi.testclient import TestClient

import app.config as config
import app.main as main
from app import service_awareness as sa
from app.ui import fleet as fleet_ui
from app.ui import db as dbmod


def _setup_temp_db(monkeypatch, tmp_path):
    db_path = tmp_path / "harry.db"
    monkeypatch.setattr(config, "DB_PATH", db_path, raising=False)
    monkeypatch.setattr(main, "DB_PATH", db_path, raising=False)
    monkeypatch.setattr(dbmod, "DB_PATH", str(db_path), raising=False)
    main._init_db()
    return db_path


def _snapshot(ts: datetime, node: str = "node-1", *, docker: bool = True, systemd: bool = True):
    return {
        "schema_version": "0.2.3",
        "node": node,
        "ts": ts.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "capabilities": {
            "gpu": False,
            "docker": docker,
            "systemd": systemd,
            "temperature": True,
            "smart": False,
        },
        "facts": {"hostname": node},
        "metrics": {"disk_used": [], "temps_c": {}, "gpu": [], "extensions": {}},
        "derived": {"health": {"state": "healthy", "worst_severity": "unknown", "reasons": []}, "extensions": {}},
        "advice": [],
    }


def test_service_row_uses_telemetry_status_and_url():
    now = datetime.now(timezone.utc).replace(microsecond=0)
    now_s = now.strftime("%Y-%m-%dT%H:%M:%SZ")
    spec = {
        "name": "Jellyfin",
        "role": "Media",
        "node": "node-1",
        "type": "docker",
        "port": 8096,
    }
    latest = {
        "node-1": {
            "ts": now_s,
            "payload": {
                "node": "node-1",
                "ts": now_s,
                "capabilities": {"docker": True, "systemd": True},
                "facts": {"hostname": "node-1"},
                "metrics": {"disk_used": [], "temps_c": {}, "gpu": [], "extensions": {}},
                "derived": {"health": {"state": "healthy", "worst_severity": "unknown", "reasons": []}, "extensions": {}},
                "services": [
                    {
                        "name": "Jellyfin",
                        "status": "running",
                        "url": "http://node-1:8096",
                        "port": 8096,
                    }
                ],
                "advice": [],
            },
        }
    }

    row = sa._service_row_from_spec(spec, latest)

    assert row["name"] == "Jellyfin"
    assert row["role"] == "Media"
    assert row["status"] == "online"
    assert row["health"] == "online"
    assert row["url"] == "http://node-1:8096"
    assert row["last_checked"] == now_s


def test_build_service_rows_uses_config_and_node_health(monkeypatch, tmp_path):
    _setup_temp_db(monkeypatch, tmp_path)
    monkeypatch.setenv(
        "HARRY_SERVICES_JSON",
        json.dumps(
            [
                {
                    "name": "Jellyfin",
                    "role": "Media",
                    "node": "node-1",
                    "type": "docker",
                    "port": 8096,
                    "tags": ["media", "video"],
                }
            ]
        ),
    )

    now = datetime.now(timezone.utc).replace(microsecond=0)
    with TestClient(main.app) as client:
        assert client.post("/ingest", json=_snapshot(now)).status_code == 200

    rows = sa.build_service_rows()
    jellyfin = next(row for row in rows if row["name"] == "Jellyfin")
    brain = next(row for row in rows if row["name"] == "Harry Brain")
    html = fleet_ui.render_fleet_live(hours=72, debug=False)

    assert jellyfin["status"] == "online"
    assert jellyfin["health"] == "online"
    assert jellyfin["tags"] == ["media", "video"]
    assert jellyfin["last_checked"] == now.strftime("%Y-%m-%dT%H:%M:%SZ")
    assert brain["status"] == "online"
    assert "Watched services" in html
    assert "Jellyfin" in html


def test_render_fleet_live_uses_small_system_status_when_no_service_config(monkeypatch, tmp_path):
    _setup_temp_db(monkeypatch, tmp_path)

    now = datetime.now(timezone.utc).replace(microsecond=0)
    with TestClient(main.app) as client:
        assert client.post("/ingest", json=_snapshot(now)).status_code == 200

    html = fleet_ui.render_fleet_live(hours=72, debug=False)

    assert "Brain health" in html
    assert "Watched services" not in html
    assert "Brain API" in html
    assert "Discovery endpoint" in html
    assert "Local telemetry agent" in html
    assert "Service checks for Harry Brain and the local telemetry agent." in html


def test_render_fleet_live_explains_missing_machine_telemetry_when_brain_is_online(monkeypatch, tmp_path):
    _setup_temp_db(monkeypatch, tmp_path)

    html = fleet_ui.render_fleet_live(hours=72, debug=False)

    assert "Local telemetry agent" in html
    assert "not reporting right now" in html


def test_api_services_returns_service_rows(monkeypatch, tmp_path):
    _setup_temp_db(monkeypatch, tmp_path)
    monkeypatch.setenv(
        "HARRY_SERVICES_JSON",
        json.dumps(
            [
                {
                    "name": "Ollama",
                    "role": "LLM",
                    "node": "node-1",
                    "type": "http",
                    "url": "http://node-1:11434",
                }
            ]
        ),
    )

    now = datetime.now(timezone.utc).replace(microsecond=0)
    with TestClient(main.app) as client:
        assert client.post("/ingest", json=_snapshot(now)).status_code == 200
        resp = client.get("/api/services")

    assert resp.status_code == 200
    data = resp.json()
    assert data["ok"] is True
    assert data["count"] == len(data["services"])
    assert any(row["name"] == "Ollama" for row in data["services"])
    assert any(row["name"] == "Harry Brain" for row in data["services"])
