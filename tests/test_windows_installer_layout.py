from __future__ import annotations

from pathlib import Path


def test_windows_installer_mentions_brain_discovery_and_public_port():
    script = Path("agent/windows/install_agent.ps1").read_text(encoding="utf-8")
    dist_script = Path("app/dist/windows/install_agent.ps1").read_text(encoding="utf-8")

    for text in (script, dist_script):
        assert "Get-DiscoveryCandidates" in text
        assert "Discover-HarryBrain" in text
        assert "Test-BrainDiscoveryCandidate" in text
        assert "harry.local" in text
        assert "harry-brain.local" in text
        assert "/discover" in text
        assert "/.well-known/harry-brain" in text
        assert "8789" in text


def test_windows_installer_examples_are_public_and_generic():
    script = Path("agent/windows/install_agent.ps1").read_text(encoding="utf-8")
    dist_script = Path("app/dist/windows/install_agent.ps1").read_text(encoding="utf-8")

    for text in (script, dist_script):
        assert "harry-brain:8787" not in text
        assert "White" + " Family" not in text
        assert "harry." + "white" + "familyhome.net" not in text
