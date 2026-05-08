from __future__ import annotations

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
