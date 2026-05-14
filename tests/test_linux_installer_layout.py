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


def test_install_agent_supports_synology_dsm_mode():
    script = Path("scripts/install-agent.sh").read_text(encoding="utf-8")

    assert "detect_platform" in script
    assert "synology-dsm" in script
    assert "linux-systemd" in script
    assert "linux-generic" in script
    assert "case \"${HARRY_PLATFORM:-}\"" in script
    assert "resolve_synology_install_root" in script
    assert "run-harry-agent.sh" in script
    assert "HARRY_STATUS_DIR" in script
    assert "HARRY_BRAIN_URL_CACHE_FILE" in script
    assert "Task Scheduler" in script
    assert "/usr/syno/bin:/usr/syno/sbin" in script
    assert "systemctl enable harry-agent.timer" in script
    assert "systemctl start harry-agent.timer" in script
    assert "enable --now" not in script


def test_install_agent_synology_markers_beats_systemctl():
    script = Path("scripts/install-agent.sh").read_text(encoding="utf-8")

    syno_idx = script.index('if [ -f /etc.defaults/VERSION ] && [ -f /etc/synoinfo.conf ]; then')
    sysd_idx = script.index('if need_cmd systemctl && [ -d /run/systemd/system ]; then')
    assert syno_idx < sysd_idx


def test_install_agent_override_mode_is_respected():
    script = Path("scripts/install-agent.sh").read_text(encoding="utf-8")

    assert 'case "${HARRY_PLATFORM:-}"' in script
    assert "synology-dsm|linux-systemd|linux-generic" in script
    assert "echo \"$HARRY_PLATFORM\"" in script


def test_update_harry_script_describes_safe_update_flow():
    script = Path("scripts/update-harry.sh").read_text(encoding="utf-8")

    assert "git stash push --include-untracked" in script
    assert "git pull" in script
    assert "docker compose up -d --build" in script
    assert "chmod +x \"$AGENT_SCRIPT\"" in script
    assert "chmod o+x \"$ROOT_DIR\" \"$ROOT_DIR/agent\"" in script
    assert "systemctl daemon-reload" in script
    assert "harry-agent.service" in script
    assert "docker compose ps" in script
