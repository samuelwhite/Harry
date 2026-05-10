from __future__ import annotations

from app.harry_normalise import normalise_for_schema
from app.ui.capabilities import gpu_state_message, gpu_capability_hint


def test_normalise_for_schema_defaults_missing_capabilities_to_empty_dict():
    payload = {
        "schema_version": "0.2.3",
        "node": "node-1",
        "ts": "2026-05-07T12:00:00Z",
        "facts": {},
        "metrics": {"disk_used": [], "temps_c": {}, "gpu": [], "extensions": {}},
        "derived": {"health": {"state": "unknown", "worst_severity": "unknown", "reasons": []}, "extensions": {}},
        "advice": [],
    }

    normalised = normalise_for_schema(payload, contract_version="0.2.3")

    assert normalised["capabilities"] == {}


def test_normalise_for_schema_preserves_windows_capabilities():
    payload = {
        "schema_version": "0.2.3",
        "node": "desktop-1",
        "ts": "2026-05-07T12:00:00Z",
        "capabilities": {
            "gpu": True,
            "docker": False,
            "systemd": False,
            "temperature": False,
            "smart": False,
        },
        "facts": {},
        "metrics": {"disk_used": [], "temps_c": {}, "gpu": [], "extensions": {}},
        "derived": {"health": {"state": "unknown", "worst_severity": "unknown", "reasons": []}, "extensions": {}},
        "advice": [],
    }

    normalised = normalise_for_schema(payload, contract_version="0.2.3")

    assert normalised["capabilities"]["gpu"] is True
    assert normalised["capabilities"]["docker"] is False


def test_normalise_for_schema_preserves_linux_capabilities():
    payload = {
        "schema_version": "0.2.3",
        "node": "server-1",
        "ts": "2026-05-07T12:00:00Z",
        "capabilities": {
            "gpu": True,
            "docker": True,
            "systemd": True,
            "temperature": True,
            "smart": True,
        },
        "facts": {},
        "metrics": {"disk_used": [], "temps_c": {}, "gpu": [], "extensions": {}},
        "derived": {"health": {"state": "unknown", "worst_severity": "unknown", "reasons": []}, "extensions": {}},
        "advice": [],
    }

    normalised = normalise_for_schema(payload, contract_version="0.2.3")

    assert normalised["capabilities"] == {
        "gpu": True,
        "docker": True,
        "systemd": True,
        "temperature": True,
        "smart": True,
    }


def test_gpu_state_message_covers_all_user_facing_states():
    assert gpu_state_message({"gpu": False}, []) == "GPU reporting unsupported by this agent"
    assert gpu_state_message({"gpu": True}, []) == "No GPU detected"
    assert gpu_state_message({}, []) == "GPU data unavailable"
    assert gpu_state_message({"gpu": False}, [{"name": "GPU0"}]) == ""


def test_gpu_capability_hint_infers_common_hardware_families():
    assert gpu_capability_hint({"name": "NVIDIA GeForce RTX 3080"}) == "CUDA capable"
    assert gpu_capability_hint({"name": "Intel Iris Xe", "integrated": True}) == "Integrated graphics"
    assert gpu_capability_hint({"name": "AMD Radeon RX 7800 XT"}) == "Dedicated graphics"
