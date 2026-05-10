from __future__ import annotations

from pathlib import Path


def test_install_agent_prefers_packaged_script_before_repo_fallback():
    script = Path("scripts/install-agent.sh").read_text(encoding="utf-8")

    packaged = script.find("PACKAGED_AGENT_SCRIPT")
    repo = script.find("DEV_AGENT_SCRIPT")
    assert packaged != -1
    assert repo != -1
    assert packaged < repo
    assert "Tried Brain download" in script
    assert "HARRY_PUBLIC_BASE_URL" in script


def test_install_sh_stages_agent_script_into_packaged_scripts():
    script = Path("install.sh").read_text(encoding="utf-8")

    assert 'cp -a "$SCRIPT_DIR/agent/harry_agent.sh" "$INSTALL_DIR/scripts/harry_agent.sh"' in script
