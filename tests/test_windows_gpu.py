from __future__ import annotations

import importlib.util
import sys
import types
from pathlib import Path

from app.harry_normalise import normalise_for_schema


def _load_windows_agent(monkeypatch):
    fake_psutil = types.SimpleNamespace(
        cpu_count=lambda logical=True: 8,
        cpu_percent=lambda interval=1: 12.5,
        virtual_memory=lambda: types.SimpleNamespace(percent=34.5),
        disk_usage=lambda path: types.SimpleNamespace(percent=56.7, total=100 * 1024 * 1024 * 1024),
    )
    monkeypatch.setitem(sys.modules, "psutil", fake_psutil)

    path = Path(__file__).resolve().parents[1] / "agent" / "windows" / "harry_agent.py"
    spec = importlib.util.spec_from_file_location("harry_windows_agent", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_windows_get_gpus_returns_single_gpu(monkeypatch):
    win_agent = _load_windows_agent(monkeypatch)
    monkeypatch.setattr(
        win_agent,
        "run_ps_json",
        lambda ps: [
            {
                "Name": "NVIDIA GeForce RTX 4080",
                "AdapterRAM": 17163091968,
                "DriverVersion": "551.76",
                "VideoProcessor": "NVIDIA GeForce RTX 4080",
                "PNPDeviceID": "PCI\\VEN_10DE&DEV_2704",
                "Status": "OK",
            }
        ],
    )

    gpus = win_agent.get_gpus()

    assert len(gpus) == 1
    gpu = gpus[0]
    assert gpu["name"] == "NVIDIA GeForce RTX 4080"
    assert gpu["mem_total_mb"] == 16368
    assert gpu["driver"] == "551.76"
    assert gpu["driver_version"] == "551.76"
    assert gpu["video_processor"] == "NVIDIA GeForce RTX 4080"
    assert gpu["status"] == "OK"
    assert gpu["pnp_device_id"] == "PCI\\VEN_10DE&DEV_2704"
    assert gpu["vendor"] == "NVIDIA"
    assert gpu["cuda_capable"] is True
    assert gpu["capability_hint"] == "CUDA capable"


def test_windows_get_gpus_keeps_multiple_same_name_devices(monkeypatch):
    win_agent = _load_windows_agent(monkeypatch)
    monkeypatch.setattr(
        win_agent,
        "run_ps_json",
        lambda ps: [
            {
                "Name": "NVIDIA GeForce RTX 4080",
                "AdapterRAM": 17163091968,
                "DriverVersion": "551.76",
                "PNPDeviceID": "PCI\\VEN_10DE&DEV_2704&0001",
            },
            {
                "Name": "NVIDIA GeForce RTX 4080",
                "AdapterRAM": 17163091968,
                "DriverVersion": "551.76",
                "PNPDeviceID": "PCI\\VEN_10DE&DEV_2704&0002",
            },
        ],
    )

    gpus = win_agent.get_gpus()

    assert len(gpus) == 2
    assert {gpu["pnp_device_id"] for gpu in gpus} == {
        "PCI\\VEN_10DE&DEV_2704&0001",
        "PCI\\VEN_10DE&DEV_2704&0002",
    }


def test_windows_get_gpus_handles_missing_results(monkeypatch):
    win_agent = _load_windows_agent(monkeypatch)
    monkeypatch.setattr(win_agent, "run_ps_json", lambda ps: None)

    assert win_agent.get_gpus() == []


def test_windows_get_gpus_handles_partial_payload(monkeypatch):
    win_agent = _load_windows_agent(monkeypatch)
    monkeypatch.setattr(
        win_agent,
        "run_ps_json",
        lambda ps: [{"Name": "Intel UHD Graphics", "PNPDeviceID": "PCI\\VEN_8086&DEV_A7A1"}],
    )

    gpus = win_agent.get_gpus()

    assert len(gpus) == 1
    assert gpus[0]["name"] == "Intel UHD Graphics"
    assert gpus[0]["mem_total_mb"] is None
    assert gpus[0]["driver"] is None
    assert gpus[0]["vendor"] == "Intel"
    assert gpus[0]["integrated"] is True
    assert gpus[0]["capability_hint"] == "Integrated graphics"


def test_normalise_for_schema_promotes_windows_fact_gpu_payload():
    payload = {
        "schema_version": "0.2.3",
        "agent_version": "0.2.3-windows-dev",
        "node": "desktop-1",
        "ts": "2026-05-07T12:00:00Z",
        "facts": {
            "gpus": [
                {
                    "name": "NVIDIA GeForce RTX 4080",
                    "vram_mb": 16384,
                    "driver_version": "551.76",
                    "pnp_device_id": "PCI\\VEN_10DE&DEV_2704",
                    "video_processor": "NVIDIA GeForce RTX 4080",
                    "status": "OK",
                    "vendor": "NVIDIA",
                    "cuda_capable": True,
                    "capability_hint": "CUDA capable",
                }
            ]
        },
        "metrics": {"disk_used": [], "temps_c": {}, "gpu": [], "extensions": {}},
        "derived": {"health": {"state": "unknown", "worst_severity": "unknown", "reasons": []}, "extensions": {}},
        "advice": [],
    }

    normalised = normalise_for_schema(payload, contract_version="0.2.3")

    assert normalised["agent_version"] == "0.2.3"
    assert len(normalised["metrics"]["gpu"]) == 1
    gpu = normalised["metrics"]["gpu"][0]
    assert gpu["name"] == "NVIDIA GeForce RTX 4080"
    assert gpu["mem_total_mb"] == 16384.0
    assert gpu["driver"] == "551.76"
    assert gpu["bus_id"] == "PCI\\VEN_10DE&DEV_2704"
    assert gpu["video_processor"] == "NVIDIA GeForce RTX 4080"
    assert gpu["status"] == "OK"
    assert gpu["vendor"] == "NVIDIA"
    assert gpu["cuda_capable"] is True
    assert gpu["capability_hint"] == "CUDA capable"
