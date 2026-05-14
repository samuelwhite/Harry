from __future__ import annotations

from app.harry_normalise import normalise_for_schema
from app.harry_schema import validate_harry_snapshot


def test_validate_harry_snapshot_accepts_minimal_valid_payload():
    payload = {
        "schema_version": "0.2.3",
        "node": "node-1",
        "ts": "2026-05-07T12:00:00Z",
        "facts": {},
        "metrics": {
            "disk_used": [],
            "temps_c": {},
            "gpu": [],
            "extensions": {},
        },
        "derived": {"health": {"state": "unknown", "worst_severity": "unknown", "reasons": []}, "extensions": {}},
        "advice": [],
    }

    assert validate_harry_snapshot(payload) == []


def test_normalise_for_schema_promotes_legacy_metrics_shape():
    payload = {
        "schema_version": "0.2.1",
        "agent_version": "1.2.3",
        "node": "node-1",
        "ts": "2026-05-07T12:00:00Z",
        "facts": {
            "hostname": "node-1",
            "bios_version": "1.0.0",
            "disks": [{"name": "sda", "size_gb": 512, "model": "Disk", "serial": "ABC"}],
            "gpus": [{"name": "GPU0"}],
        },
        "metrics": {
            "cpu_load_1m": 1.25,
            "mem_used_pct": 88,
            "disk_used": [{"mount": "/", "pct": 91, "fs": "ext4", "size_gb": 512}],
            "temps_c": {"Package": 73.2},
            "gpu": [{"name": "GPU0", "mem_total_mb": 8, "mem_used_mb": 2}],
        },
        "derived": {},
        "advice": [],
    }

    normalised = normalise_for_schema(payload, contract_version="0.2.3")

    assert normalised["schema_version"] == "0.2.3"
    assert normalised["facts"]["extensions"]["bios_version"] == "1.0.0"
    assert normalised["metrics"]["disk_used"][0]["used_pct"] == 91.0
    assert normalised["metrics"]["gpu"][0]["mem_used_pct"] == 25.0
    assert normalised["metrics"]["extensions"]["mounts_raw"][0]["mount"] == "/"


def test_normalise_for_schema_preserves_synology_storage_byte_fields():
    payload = {
        "schema_version": "0.2.1",
        "node": "nas-1",
        "ts": "2026-05-07T12:00:00Z",
        "facts": {},
        "metrics": {
            "disk_used": [
                {
                    "mount": "/volume1",
                    "fs": "/dev/vg1/volume_1",
                    "device": "/dev/vg1/volume_1",
                    "total_b": 1000000,
                    "used_b": 400000,
                    "free_b": 600000,
                    "used_pct": 40.0,
                    "pct": 40.0,
                    "size_gb": 0.93,
                }
            ],
            "temps_c": {},
            "gpu": [],
            "extensions": {},
        },
        "derived": {},
        "advice": [],
    }

    normalised = normalise_for_schema(payload, contract_version="0.2.3")
    volume = normalised["metrics"]["disk_used"][0]

    assert volume["mount"] == "/volume1"
    assert volume["fs"] == "/dev/vg1/volume_1"
    assert volume["device"] == "/dev/vg1/volume_1"
    assert volume["total_b"] == 1000000
    assert volume["used_b"] == 400000
    assert volume["free_b"] == 600000
    assert volume["used_pct"] == 40.0


def test_normalise_for_schema_strips_platform_suffix_from_agent_version():
    payload = {
        "schema_version": "0.2.3",
        "agent_version": "0.2.3-windows-dev",
        "node": "node-1",
        "ts": "2026-05-07T12:00:00Z",
        "facts": {},
        "metrics": {"disk_used": [], "temps_c": {}, "gpu": [], "extensions": {}},
        "derived": {"health": {"state": "unknown", "worst_severity": "unknown", "reasons": []}, "extensions": {}},
        "advice": [],
    }

    normalised = normalise_for_schema(payload, contract_version="0.2.3")

    assert normalised["agent_version"] == "0.2.3"
