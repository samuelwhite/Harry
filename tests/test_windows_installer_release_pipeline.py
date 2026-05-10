from __future__ import annotations

from pathlib import Path

from app.versions import BRAIN_VERSION


def test_windows_installer_release_script_describes_current_pipeline():
    script = Path("scripts/build-windows-installer.ps1").read_text(encoding="utf-8")

    assert "sync_windows_artifacts.py" in script
    assert "ISCC.exe" in script
    assert "HarryAgent.iss" in script
    assert "HarryAgentSetup.exe" in script
    assert "HarryAgentSetup.manifest.json" in script
    assert "downloads" in script
    assert "brain_version" in script
    assert "agent_version" in script
    assert "schema_current" in script


def test_windows_installer_iss_sources_current_runtime_artifacts():
    iss = Path("installers/windows/iss/HarryAgent.iss").read_text(encoding="utf-8")

    assert f'MyAppVersion "{BRAIN_VERSION}"' in iss
    assert "..\\..\\..\\app\\dist\\windows\\*" in iss
    assert "install_agent.ps1" in iss


def test_windows_installer_manifest_is_expected_runtime_name():
    router = Path("app/app/ui/router.py").read_text(encoding="utf-8")

    assert "HarryAgentSetup.manifest.json" in router
    assert "Windows agent installer is stale or missing its manifest" in router
    assert "Run scripts/build-windows-installer.ps1" in router or "build-windows-installer.ps1" in router
