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
        assert "update_agent.ps1" in text
        assert "diagnose.ps1" in text
        assert "HARRY_PUBLIC_BASE_URL" in text
        assert "harry.local" in text
        assert "harry-brain.local" in text
        assert "/discover" in text
        assert "/.well-known/harry-brain" in text
        assert "8789" in text
        assert "No Brain was auto-discovered." in text
        assert "Harry Brain address" in text
        assert "ERROR: No Brain address provided." in text
        assert "brain_auto_discovery_failed_noninteractive" in text
        assert "Stop-HarryAgentService" in text
        assert "Wait-HarryAgentServiceProcessExit" in text
        assert "Wait-HarryAgentServiceProcessStart" in text
        assert "Start-HarryAgentService" in text
        assert "Run-AgentOnce" in text
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

    assert "..\\..\\..\\app\\dist\\windows\\*" in agent_iss
    assert "install_agent.ps1" in agent_iss
    assert "powershell.exe" in agent_iss
    assert "HarryAgentSetup.exe" not in agent_iss or "install_agent.ps1" in agent_iss
    assert "CurStepChanged" in agent_iss
    assert "StopHarryAgentServiceForUpgrade" in agent_iss
    assert "HarryAgentService.exe" in agent_iss
    assert "Flags: waituntilterminated" in agent_iss

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
    assert "Installed files:" in diagnose
    assert "Configured Brain URL:" in diagnose
    assert "Service status:" in diagnose
    assert "Health / discovery test:" in diagnose
