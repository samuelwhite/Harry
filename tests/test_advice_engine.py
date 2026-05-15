from __future__ import annotations

from datetime import datetime, timedelta, timezone

from app import advice_engine


def test_storage_fill_prediction_appears_when_history_supports_it(monkeypatch):
    now = datetime.now(timezone.utc)
    history = [
        (
            now - timedelta(hours=60 - idx * 12),
            {
                "metrics": {
                    "disk_used": [
                        {
                            "mount": "/volume1",
                            "used_pct": 50 + idx * 2,
                            "size_gb": 100,
                        }
                    ],
                    "temps_c": {},
                    "gpu": [],
                }
            },
        )
        for idx in range(6)
    ]

    def fake_history(node: str, hours: int, limit: int = 900):
        if hours >= 72:
            return history
        return []

    monkeypatch.setattr(advice_engine, "_fetch_history_payloads", fake_history)

    advice, health = advice_engine.build_advice_and_health(
        {
            "node": "nas-1",
            "facts": {},
            "metrics": {
                "disk_used": [
                    {
                        "mount": "/volume1",
                        "used_pct": 60,
                        "size_gb": 100,
                    }
                ],
                "temps_c": {},
                "gpu": [],
            },
        }
    )

    forecast = next((a for a in advice if str(a.get("id") or "").startswith("disk_fill_forecast_")), None)

    assert forecast is not None
    assert "hit 100%" in str(forecast.get("message") or "")
    assert health["worst_severity"] in {"info", "warn", "crit"}


def test_high_memory_recommendation_appears_for_sustained_high_usage(monkeypatch):
    now = datetime.now(timezone.utc)
    memory_history = [
        (
            now - timedelta(hours=5 - idx),
            {
                "metrics": {
                    "mem_used_pct": 86,
                    "disk_used": [],
                    "temps_c": {},
                    "gpu": [],
                }
            },
        )
        for idx in range(6)
    ]

    def fake_history(node: str, hours: int, limit: int = 900):
        if hours <= 6:
            return memory_history
        return []

    monkeypatch.setattr(advice_engine, "_fetch_history_payloads", fake_history)

    advice, _health = advice_engine.build_advice_and_health(
        {
            "node": "nas-1",
            "facts": {},
            "metrics": {"disk_used": [], "temps_c": {}, "gpu": [], "mem_used_pct": 10},
        }
    )

    memory_advice = next((a for a in advice if a.get("id") == "mem_sustained_high"), None)

    assert memory_advice is not None
    assert "consistently high" in str(memory_advice.get("message") or "")


def test_synology_sustained_load_near_core_count_is_info(monkeypatch):
    now = datetime.now(timezone.utc)
    load_history = [
        (
            now - timedelta(hours=5 - idx),
            {
                "capabilities": {"synology_dsm": True},
                "facts": {"cpu_cores": 2},
                "metrics": {
                    "cpu_load_1m": 1.9,
                    "disk_used": [],
                    "temps_c": {},
                    "gpu": [],
                },
            },
        )
        for idx in range(6)
    ]

    def fake_history(node: str, hours: int, limit: int = 900):
        if hours <= 6:
            return load_history
        return []

    monkeypatch.setattr(advice_engine, "_fetch_history_payloads", fake_history)

    advice, health = advice_engine.build_advice_and_health(
        {
            "node": "nas-1",
            "capabilities": {"synology_dsm": True},
            "facts": {"cpu_cores": 2},
            "metrics": {"cpu_load_1m": 1.9, "disk_used": [], "temps_c": {}, "gpu": []},
        }
    )

    cpu_advice = next((a for a in advice if a.get("id") == "cpu_load_sustained"), None)

    assert cpu_advice is not None
    assert cpu_advice.get("severity") == "info"
    assert "consistently elevated" in str(cpu_advice.get("message") or "")
    assert health["worst_severity"] == "info"


def test_overloaded_cpu_still_warns_on_synology(monkeypatch):
    now = datetime.now(timezone.utc)
    load_history = [
        (
            now - timedelta(hours=5 - idx),
            {
                "capabilities": {"synology_dsm": True},
                "facts": {"cpu_cores": 2},
                "metrics": {
                    "cpu_load_1m": 3.2,
                    "disk_used": [],
                    "temps_c": {},
                    "gpu": [],
                },
            },
        )
        for idx in range(6)
    ]

    def fake_history(node: str, hours: int, limit: int = 900):
        if hours <= 6:
            return load_history
        return []

    monkeypatch.setattr(advice_engine, "_fetch_history_payloads", fake_history)

    advice, health = advice_engine.build_advice_and_health(
        {
            "node": "nas-1",
            "capabilities": {"synology_dsm": True},
            "facts": {"cpu_cores": 2},
            "metrics": {"cpu_load_1m": 3.2, "disk_used": [], "temps_c": {}, "gpu": []},
        }
    )

    cpu_advice = next((a for a in advice if a.get("id") == "cpu_load_sustained"), None)

    assert cpu_advice is not None
    assert cpu_advice.get("severity") == "warn"
    assert "consistently heavy" in str(cpu_advice.get("message") or "")
    assert health["worst_severity"] == "warn"
