from __future__ import annotations

from pathlib import Path

from app.versions import BRAIN_VERSION


def test_windows_installer_release_script_describes_current_pipeline():
    script = Path("scripts/build-windows-installer.ps1").read_text(encoding="utf-8")
    deploy = Path("scripts/deploy-windows-installer.ps1").read_text(encoding="utf-8")
    release = Path("scripts/release-windows-installer.ps1").read_text(encoding="utf-8")

    assert "sync_windows_artifacts.py" in script
    assert "ISCC.exe" in script
    assert "HarryAgent.iss" in script
    assert "HarryAgentSetup.exe" in script
    assert "HarryAgentSetup.manifest.json" in script
    assert "PYTHONPATH" in script
    assert "Failed to import app.versions or load app.ui.db" in script
    assert "Windows installer version metadata was empty or invalid" in script
    assert "Installer artifact:" in script
    assert "Manifest:" in script
    assert "downloads" in script
    assert "Brain version:" in script
    assert "Agent version:" in script
    assert "Schema version:" in script

    assert "TargetHost" in deploy
    assert "TargetPath" in deploy
    assert "TargetUser" in deploy
    assert "scp" in deploy
    assert "Windows installer EXE not found" in deploy
    assert "Windows installer manifest not found" in deploy
    assert "manifest versions do not match" in deploy
    assert "Copying Windows installer artifacts" in deploy

    assert "Build complete." in release
    assert "Next steps:" in release
    assert "TargetHost" in release
    assert "TargetUser" in release
    assert "Deploying Windows installer artifacts" in release
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
    gitignore = Path(".gitignore").read_text(encoding="utf-8")
    readme = Path("README.md").read_text(encoding="utf-8")

    assert "HarryAgentSetup.manifest.json" in router
    assert "Windows agent installer is stale or missing its manifest" in router
    assert "Run scripts/build-windows-installer.ps1" in router or "build-windows-installer.ps1" in router
    assert "!downloads/HarryAgentSetup.exe" in gitignore
    assert "!downloads/HarryAgentSetup.manifest.json" in gitignore
    assert "committed in `downloads/`" in readme
    assert "normal `git pull` or `update-harry` refreshes them" in readme
    assert "generated, but committed here as the latest stable artifact" in readme
    assert "optional manual build-and-copy flow" in readme
    assert "C:\\ProgramData\\Harry\\logs\\HarryAgent.install.log" in readme
    assert "C:\\ProgramData\\Harry\\logs\\HarryAgent.runtime.log" in readme
    assert "C:\\ProgramData\\Harry\\diagnose.ps1" in readme
    assert "--diagnostics" in readme
    assert "--once" in readme
