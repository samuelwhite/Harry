from __future__ import annotations

from datetime import datetime, timedelta, timezone

from app.health import compute_health


def test_compute_health_flags_stale_and_schema_mismatch():
    now = datetime.now(timezone.utc)
    payload = {
        "ts": (now - timedelta(minutes=61)).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "schema_version": "0.2.2",
        "facts": {"cpu_cores": 4},
        "metrics": {},
    }

    health = compute_health(
        payload,
        ctx={
            "schema_current": "0.2.3",
            "schema_behind_warn_min": 15,
            "schema_behind_crit_min": 60,
        },
    )

    assert health["state"] == "critical"
    assert any("Node stale" in reason for reason in health["reasons"])
    assert any("Agent not updating" in reason for reason in health["reasons"])


def test_compute_health_warns_on_resource_pressure():
    now = datetime.now(timezone.utc)
    payload = {
        "ts": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "schema_version": "0.2.3",
        "facts": {"cpu_cores": 4},
        "metrics": {
            "cpu_load_1m": 7.5,
            "mem_used_pct": 91,
            "disk_used": [{"mount": "/", "used_pct": 96}],
            "gpu": [{"name": "gpu0", "temp_c": 96}],
        },
    }

    health = compute_health(payload, ctx={"schema_current": "0.2.3"})

    assert health["state"] == "critical"
    assert health["score"] < 100
    assert any("RAM high" in reason for reason in health["reasons"])
    assert any("Disk / critical" in reason for reason in health["reasons"])
    assert any("GPU overheating" in reason for reason in health["reasons"])
