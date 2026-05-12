from __future__ import annotations

from pathlib import Path


def test_windows_installer_mentions_brain_discovery_and_public_port():
    script = Path("agent/windows/install_agent.ps1").read_text(encoding="utf-8")
    dist_script = Path("app/dist/windows/install_agent.ps1").read_text(encoding="utf-8")
    payload_script = Path("installers/windows/payload/install_agent.ps1").read_text(encoding="utf-8")
    packaged_script = Path("installers/windows/brain-payload/_internal/dist/windows/install_agent.ps1").read_text(encoding="utf-8")

    for text in (script, dist_script, payload_script, packaged_script):
        assert "Get-DiscoveryCandidates" in text
        assert "Discover-HarryBrain" in text
        assert "Test-BrainDiscoveryCandidate" in text
        assert "Searching for Harry Brain" in text
        assert "Discovery candidates" in text
        assert "Installer mode:" in text
        assert "HARRY_INSTALLER_MODE" in text
        assert "update_agent.ps1" in text
        assert "diagnose.ps1" in text
        assert "HARRY_PUBLIC_BASE_URL" in text
        assert "harry.local" in text
        assert "harry-brain.local" in text
        assert "/discover" in text
        assert "/.well-known/harry-brain" in text
        assert "8789" in text
        assert "Harry Brain address" in text
        assert "brain_auto_discovery_failed_noninteractive" in text
        assert "Stop-HarryAgentService" in text
        assert "Invoke-TaskKillBestEffort" in text
        assert "Wait-HarryAgentServiceProcessExit" in text
        assert "Wait-HarryAgentServiceProcessStart" in text
        assert "Test-HarryAgentServiceRunning" in text
        assert "Start-HarryAgentService" in text
        assert "Invoke-AgentOneShotSend" in text
        assert "Wait-FirstTelemetryResult" in text
        assert "Write-RuntimeMarker" in text
        assert "one_shot_send_result" in text
        assert "first_telemetry_marker_found" in text
        assert "Test-InstalledAgentState" in text
        assert "taskkill.exe" in text
        assert "sc.exe" in text
        assert 'query "HarryAgent"' in text or "query $ServiceName" in text
        assert 'Join-Path $InstallRoot "logs"' in text
        assert "HarryAgent.install.log" in text
        assert "config.public_base_url = $brain" in text
        assert "config.brain_url = $brain" in text
        assert "config.ingest_url = \"$brain/ingest\"" in text
        assert "config.agent_version = $agentVersion" in text
        assert "Starting Harry Agent service..." in text
        assert "install_validation_success" in text
        assert "payload_source=" in text
        assert "install_target=" in text
        assert "payload_copy_same_path_avoided" in text
        assert "Start-Transcript" in text
        assert "Stop-Transcript" in text
        assert "installer_mode=$InstallerMode" in text
        assert "install_validation_start session=" in text
        assert "first_telemetry_success" in text
        assert "Harry Agent installed successfully." in text


def test_windows_installer_examples_are_public_and_generic():
    script = Path("agent/windows/install_agent.ps1").read_text(encoding="utf-8")
    dist_script = Path("app/dist/windows/install_agent.ps1").read_text(encoding="utf-8")
    payload_script = Path("installers/windows/payload/install_agent.ps1").read_text(encoding="utf-8")
    packaged_script = Path("installers/windows/brain-payload/_internal/dist/windows/install_agent.ps1").read_text(encoding="utf-8")

    for text in (script, dist_script, payload_script, packaged_script):
        assert "harry-brain:8787" not in text
        assert "White" + " Family" not in text
        assert "harry." + "white" + "familyhome.net" not in text


def test_windows_agent_installer_sources_runtime_agent_package():
    agent_iss = Path("installers/windows/iss/HarryAgent.iss").read_text(encoding="utf-8")
    brain_iss = Path("installers/windows/iss/HarryBrain.iss").read_text(encoding="utf-8")

    assert "{tmp}\\HarryAgentPayload" in agent_iss
    assert "install_agent.ps1" in agent_iss
    assert "powershell.exe" in agent_iss
    assert "HarryAgentSetup.exe" not in agent_iss or "install_agent.ps1" in agent_iss
    assert "CurStepChanged" in agent_iss
    assert "StopHarryAgentServiceForUpgrade" in agent_iss
    assert "HarryAgentService.exe" in agent_iss
    assert "RunInstallAgentScript" in agent_iss
    assert "ssPostInstall" in agent_iss
    assert "ResultCode" in agent_iss
    assert "Exec(" in agent_iss
    assert "HarryAgentPayload" in agent_iss
    assert "CreateInputOptionPage" in agent_iss
    assert "CreateInputQueryPage" in agent_iss
    assert "-InstallerMode" in agent_iss
    assert "-BrainUrl" in agent_iss
    assert "SW_HIDE" in agent_iss
    assert "npbstMarquee" in agent_iss
    assert "WizardForm.StatusLabel.Caption" in agent_iss
    assert "Harry Agent installed successfully." in agent_iss
    assert "SetInstallerBusyStatus" in agent_iss
    assert "SetInstallerIdleStatus" in agent_iss

    assert "install_agent.ps1" in brain_iss
    assert "HarryAgentSetup.exe" not in brain_iss


def test_windows_brain_payload_has_current_agent_version():
    payload_script = Path("installers/windows/brain-payload/_internal/dist/harry_agent.sh").read_text(encoding="utf-8")
    setup_iss = Path("installers/windows/iss/HarryBrain.iss").read_text(encoding="utf-8")

    assert 'AGENT_VERSION="0.2.5"' in payload_script
    assert 'AGENT_VERSION="0.2.3"' not in payload_script
    assert "BRAIN_VERSION=\"2026.05.09\"" in payload_script
    assert "AppVersion=2026.05.09" in setup_iss


def test_windows_agent_docs_mention_diagnostics_commands():
    readme = Path("agent/windows/README.txt").read_text(encoding="utf-8")
    start_here = Path("agent/windows/START-HERE.txt").read_text(encoding="utf-8")

    for text in (readme, start_here):
        assert "--diagnostics" in text
        assert "--version" in text


def test_windows_installer_logs_are_documented():
    readme = Path("README.md").read_text(encoding="utf-8")
    script = Path("agent/windows/install_agent.ps1").read_text(encoding="utf-8")
    diagnose = Path("agent/windows/diagnose.ps1").read_text(encoding="utf-8")

    assert "C:\\ProgramData\\Harry\\logs\\HarryAgent.install.log" in readme
    assert "C:\\ProgramData\\Harry\\logs\\HarryAgent.runtime.log" in readme
    assert "C:\\ProgramData\\Harry\\logs\\HarryAgentService.wrapper.log" in readme
    assert "Install log:" in script
    assert "Runtime log:" in script
    assert "Payload source path:" in script
    assert "Install target path:" in script
    assert "Installed files:" in diagnose
    assert "Configured Brain URL:" in diagnose
    assert "Service status:" in diagnose
    assert "Health / discovery test:" in diagnose
    assert "discovery_skipped_manual_mode" in script
    assert "Manual Brain address mode selected" in script
    assert "connection mode" in script.lower()
    assert "Waiting for first telemetry send" in script
    assert "install_validation_start session=" in script
    assert "first_telemetry_success" in script


def test_windows_installer_error_handling_and_exit_codes_are_explicit():
    script = Path("agent/windows/install_agent.ps1").read_text(encoding="utf-8")
    iss = Path("installers/windows/iss/HarryAgent.iss").read_text(encoding="utf-8")

    assert "taskkill_process_absent" in script
    assert "Post-install validation failed" in script
    assert "exit 1" in script
    assert "ExitCode" in script or "ResultCode" in iss
    assert "CurStepChanged" in iss
    assert "ssPostInstall" in iss
    assert "Harry Agent installer failed" in iss or "failed" in iss.lower()
    assert "same_path_avoided" in script
    assert "HARRY_INSTALLER_MODE" in script
    assert "Select-Object -First 1" in script
    assert "return @($discovered)" in script
    assert "return @($discovered)" in script
    assert "Select-Object -First 1" in script
    assert "Manual Brain address mode selected" in script
    assert "Run-AgentOnce" not in script
    assert "Press Enter to exit" not in script
