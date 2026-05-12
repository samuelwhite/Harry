from __future__ import annotations

import json
import importlib.util
import sys
import types
from pathlib import Path


def _load_windows_agent(monkeypatch):
    fake_psutil = types.SimpleNamespace(
        cpu_count=lambda logical=True: 8,
        cpu_percent=lambda interval=1: 12.5,
        virtual_memory=lambda: types.SimpleNamespace(percent=34.5),
        disk_usage=lambda path: types.SimpleNamespace(percent=56.7, total=100 * 1024 * 1024 * 1024),
    )
    monkeypatch.setitem(sys.modules, "psutil", fake_psutil)

    path = Path(__file__).resolve().parents[1] / "agent" / "windows" / "harry_agent.py"
    spec = importlib.util.spec_from_file_location("harry_windows_agent_update", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_windows_updater_version_compare_is_strictly_newer(monkeypatch):
    win_agent = _load_windows_agent(monkeypatch)

    assert win_agent._is_newer_version("0.2.6", "0.2.5") is True
    assert win_agent._is_newer_version("0.2.5", "0.2.5") is False
    assert win_agent._is_newer_version("0.2.4", "0.2.5") is False


def test_windows_updater_schedules_helper_when_brain_is_newer(monkeypatch, tmp_path):
    win_agent = _load_windows_agent(monkeypatch)
    monkeypatch.setattr(win_agent, "BRAIN_URL", "http://brain.example:8789", raising=False)
    monkeypatch.setattr(win_agent, "_install_root", lambda: tmp_path)
    (tmp_path / "update_agent.ps1").write_text("Write-Host 'ok'\n", encoding="utf-8")

    calls = []
    monkeypatch.setattr(win_agent, "_fetch_brain_discovery", lambda: {
        "service": "harry-brain",
        "ok": True,
        "agent_version": "0.2.6",
        "agent_download_url": "http://brain.example:8789/downloads/windows-agent-exe",
    })
    monkeypatch.setattr(win_agent, "_launch_windows_updater", lambda url: calls.append(url) or True)

    assert win_agent.maybe_self_update() is True
    assert calls == ["http://brain.example:8789/downloads/windows-agent-exe"]


def test_windows_updater_skips_when_brain_is_not_newer(monkeypatch, tmp_path):
    win_agent = _load_windows_agent(monkeypatch)
    monkeypatch.setattr(win_agent, "BRAIN_URL", "http://brain.example:8789", raising=False)
    monkeypatch.setattr(win_agent, "_install_root", lambda: tmp_path)
    (tmp_path / "update_agent.ps1").write_text("Write-Host 'ok'\n", encoding="utf-8")

    calls = []
    monkeypatch.setattr(win_agent, "_fetch_brain_discovery", lambda: {
        "service": "harry-brain",
        "ok": True,
        "agent_version": "0.2.5",
        "agent_download_url": "http://brain.example:8789/downloads/windows-agent-exe",
    })
    monkeypatch.setattr(win_agent, "_launch_windows_updater", lambda url: calls.append(url) or True)

    assert win_agent.maybe_self_update() is False
    assert calls == []


def test_windows_agent_version_flag_prints_version(monkeypatch, capsys):
    win_agent = _load_windows_agent(monkeypatch)
    monkeypatch.setattr(sys, "argv", ["harry_agent.py", "--version"])

    win_agent.main()

    out = capsys.readouterr().out.strip()
    assert out == "0.2.5"


def test_windows_agent_diagnostics_flag_prints_summary(monkeypatch, capsys):
    win_agent = _load_windows_agent(monkeypatch)
    monkeypatch.setattr(sys, "argv", ["harry_agent.py", "--diagnostics"])
    monkeypatch.setattr(
        win_agent,
        "_fetch_brain_discovery",
        lambda: {
            "ok": True,
            "service": "harry-brain",
            "agent_version": "0.2.5",
            "canonical_base_url": "http://brain.example:8789",
            "recommended_lan_url": "http://192.168.1.10:8789",
        },
    )
    monkeypatch.setattr(win_agent, "_probe_brain_health", lambda: (True, 200, "ok"))
    monkeypatch.setattr(win_agent, "_probe_ingest", lambda payload: (True, 200, "accepted"))
    monkeypatch.setattr(win_agent, "_service_status", lambda: "RUNNING")
    monkeypatch.setattr(
        win_agent,
        "build_payload",
        lambda: {
            "node": "workstation-1",
            "ts": "2026-05-10T12:00:00Z",
            "facts": {"gpus": [{"name": "Intel Iris Xe"}]},
        },
    )

    win_agent.main()

    out = capsys.readouterr().out.strip()
    data = json.loads(out)
    assert data["agent_version"] == "0.2.5"
    assert data["discovery_ok"] is True
    assert data["gpu_count"] == 1
    assert data["payload_node"] == "workstation-1"
    assert data["service_status"] == "RUNNING"
    assert data["health_check_ok"] is True
    assert data["ingest_probe_ok"] is True


def test_windows_agent_send_once_flag_runs_single_send(monkeypatch):
    win_agent = _load_windows_agent(monkeypatch)
    calls = []
    monkeypatch.setattr(sys, "argv", ["harry_agent.py", "--send-once"])
    monkeypatch.setattr(win_agent, "run_once", lambda: calls.append("run") or 0)

    try:
        win_agent.main()
    except SystemExit as exc:
        assert exc.code == 0

    assert calls == ["run"]


def test_windows_agent_once_flag_still_runs_single_send(monkeypatch):
    win_agent = _load_windows_agent(monkeypatch)
    calls = []
    monkeypatch.setattr(sys, "argv", ["harry_agent.py", "--once"])
    monkeypatch.setattr(win_agent, "run_once", lambda: calls.append("run") or 1)

    try:
        win_agent.main()
    except SystemExit as exc:
        assert exc.code == 1

    assert calls == ["run"]
