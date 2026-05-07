from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient

import app.config as config
import app.main as main
from app import machine_summary as ms
from app.ui import fleet as fleet_ui
from app.ui import db as dbmod


def _setup_temp_db(monkeypatch, tmp_path):
    db_path = tmp_path / "harry.db"
    monkeypatch.setattr(config, "DB_PATH", db_path, raising=False)
    monkeypatch.setattr(main, "DB_PATH", db_path, raising=False)
    monkeypatch.setattr(dbmod, "DB_PATH", str(db_path), raising=False)
    main._init_db()
    return db_path


def _snapshot(ts: datetime, *, node: str = "node-1", error: bool = False, gpu: bool = True, disk_used: float = 92.0):
    payload = {
        "schema_version": "0.2.3",
        "node": node,
        "ts": ts.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "agent_status": {
            "state": "error" if error else "healthy",
            "ok": not error,
            "stage": "probe" if error else "running",
            "error_summary": "probe failed" if error else None,
        },
        "facts": {
            "hostname": node,
            "gpus": [{"name": "GPU0"}] if gpu else [],
        },
        "metrics": {
            "cpu_load_1m": 0.2,
            "mem_used_pct": 42.0,
            "disk_used": [{"mount": "/", "used_pct": disk_used}],
            "temps_c": {},
            "gpu": [{"name": "GPU0"}] if gpu else [],
            "extensions": {},
        },
        "derived": {"health": {"state": "unknown", "worst_severity": "unknown", "reasons": []}, "extensions": {}},
        "advice": [],
    }
    return payload


def test_ingest_records_activity_events(monkeypatch, tmp_path):
    _setup_temp_db(monkeypatch, tmp_path)

    now = datetime.now(timezone.utc).replace(microsecond=0)
    first = now - timedelta(hours=2)

    with TestClient(main.app) as client:
        r1 = client.post("/ingest", json=_snapshot(first))
        assert r1.status_code == 200

        r2 = client.post("/ingest", json=_snapshot(now, error=True))
        assert r2.status_code == 200

        resp = client.get("/api/events?limit=20")
        assert resp.status_code == 200
        data = resp.json()

    assert data["ok"] is True
    assert data["count"] == len(data["events"])

    event_types = {event["type"] for event in data["events"]}
    assert "agent.first_seen" in event_types
    assert "agent.heartbeat_missed" in event_types
    assert "agent.heartbeat_restored" in event_types
    assert "agent.offline" in event_types
    assert "hardware.gpu_detected" in event_types
    assert "storage.disk_warning" in event_types


def test_summary_refresh_records_event(monkeypatch, tmp_path):
    _setup_temp_db(monkeypatch, tmp_path)
    monkeypatch.setenv("HARRY_ENABLE_LLM_SUMMARIES", "1")
    monkeypatch.setattr(ms, "SUMMARY_CACHE_DIR", tmp_path / "machine_summaries")

    now = datetime.now(timezone.utc).replace(microsecond=0)
    result = ms.get_machine_summary(_snapshot(now))

    assert result is not None
    assert result["summary"]

    events = dbmod.get_recent_events(limit=10, sync_stale=False)
    assert any(event["type"] == "summary.refreshed" for event in events)


def test_fleet_view_includes_recent_activity(monkeypatch, tmp_path):
    _setup_temp_db(monkeypatch, tmp_path)

    now = datetime.now(timezone.utc).replace(microsecond=0)
    with TestClient(main.app) as client:
        r = client.post("/ingest", json=_snapshot(now))
        assert r.status_code == 200

    dbmod.record_event(
        level="info",
        type="demo.note",
        title="Demo event",
        message="Harry noticed something worth mentioning.",
        node_id="node-1",
    )

    html = fleet_ui.render_fleet_live(hours=72, debug=False)

    assert "Recent activity" in html
    assert "Demo event" in html
    assert "Harry noticed something worth mentioning." in html


def test_fleet_view_shows_empty_activity_state(monkeypatch, tmp_path):
    _setup_temp_db(monkeypatch, tmp_path)

    html = fleet_ui.render_fleet_live(hours=72, debug=False)

    assert "No recent activity yet" in html
