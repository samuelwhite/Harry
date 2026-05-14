from __future__ import annotations

import os
import subprocess
from pathlib import Path


def _bash_exe() -> str:
    return r"C:\Program Files\Git\bin\bash.exe"


def _extract_shell_function(script: str, name: str) -> str:
    lines = script.splitlines()
    start = next(i for i, line in enumerate(lines) if line.startswith(f"{name}() {{"))

    extracted: list[str] = []
    for line in lines[start:]:
        extracted.append(line)
        if line.strip() == "}":
            break

    return "\n".join(extracted)


def _write_shell_snippet(tmp_path: Path, script: str, names: list[str], replacements: dict[str, str] | None = None) -> Path:
    parts = ["set -euo pipefail"]
    replacements = replacements or {}

    for name in names:
        fn = _extract_shell_function(script, name)
        for old, new in replacements.items():
            fn = fn.replace(old, new)
        parts.append(fn)

    snippet = tmp_path / "snippet.sh"
    snippet.write_text("\n\n".join(parts) + "\n", encoding="utf-8")
    return snippet


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
    assert "set -a" in script
    assert '. "$CONFIG_FILE"' in script
    assert "set +a" in script
    assert script.index("set -a") < script.index('. "$CONFIG_FILE"') < script.index("set +a")
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


def test_install_agent_honors_synology_override_before_detection(tmp_path):
    script = Path("scripts/install-agent.sh").read_text(encoding="utf-8")
    snippet = _write_shell_snippet(tmp_path, script, ["need_cmd", "detect_platform"])

    fakebin = tmp_path / "fakebin"
    fakebin.mkdir()
    systemctl = fakebin / "systemctl"
    systemctl.write_text("#!/usr/bin/env sh\nexit 42\n", encoding="utf-8")
    os.chmod(systemctl, 0o755)

    cmd = f'source "{snippet.as_posix()}"; detect_platform'
    env = os.environ.copy()
    env["PATH"] = f"{fakebin.as_posix()}{os.pathsep}{env.get('PATH', '')}"
    env["HARRY_PLATFORM"] = "synology-dsm"
    result = subprocess.run([_bash_exe(), "-lc", cmd], env=env, capture_output=True, text=True, check=True)

    assert result.stdout.strip() == "synology-dsm"


def test_install_agent_synology_markers_beats_systemctl_with_override_path(tmp_path):
    script = Path("scripts/install-agent.sh").read_text(encoding="utf-8")
    version_file = tmp_path / "VERSION"
    synoinfo_file = tmp_path / "synoinfo.conf"
    version_file.write_text("productversion=7.2\n", encoding="utf-8")
    synoinfo_file.write_text("unique=1\n", encoding="utf-8")

    replacements = {
        "/etc.defaults/VERSION": version_file.as_posix(),
        "/etc/synoinfo.conf": synoinfo_file.as_posix(),
    }
    snippet = _write_shell_snippet(tmp_path, script, ["need_cmd", "detect_platform"], replacements=replacements)

    fakebin = tmp_path / "fakebin"
    fakebin.mkdir()
    systemctl = fakebin / "systemctl"
    systemctl.write_text("#!/usr/bin/env sh\nexit 42\n", encoding="utf-8")
    os.chmod(systemctl, 0o755)

    cmd = f'PATH="{fakebin.as_posix()}:$PATH" source "{snippet.as_posix()}"; detect_platform'
    result = subprocess.run([_bash_exe(), "-lc", cmd], capture_output=True, text=True, check=True)

    assert result.stdout.strip() == "synology-dsm"


def test_install_agent_reads_existing_base_url_from_supported_config_formats(tmp_path):
    script = Path("scripts/install-agent.sh").read_text(encoding="utf-8")
    service_file = tmp_path / "harry-agent.service"
    install_root = tmp_path / "harry"
    install_root.mkdir()
    env_file = install_root / "harry-agent.env"

    base_url = "http://192.168." + "7.200:8789"
    cases = [
        (f'Environment="HARRY_BASE_URL={base_url}"', "linux-systemd"),
        (f'HARRY_BASE_URL="{base_url}"', "linux-systemd"),
        (f"HARRY_BASE_URL={base_url}", "linux-systemd"),
    ]

    for contents, platform in cases:
        service_file.write_text(contents + "\n", encoding="utf-8")
        snippet = _write_shell_snippet(
            tmp_path,
            script,
            ["read_configured_value", "current_configured_base_url"],
            replacements={"/etc/systemd/system/harry-agent.service": service_file.as_posix()},
        )
        cmd = (
            f'source "{snippet.as_posix()}"; '
            f'current_configured_base_url "{platform}" "{install_root.as_posix()}"'
        )
        result = subprocess.run([_bash_exe(), "-lc", cmd], capture_output=True, text=True, check=True)
        assert result.stdout.strip() == base_url

    env_file.write_text(f'HARRY_BASE_URL="{base_url}"\n', encoding="utf-8")
    snippet = _write_shell_snippet(tmp_path, script, ["read_configured_value", "current_configured_base_url"])
    cmd = (
        f'source "{snippet.as_posix()}"; '
        f'current_configured_base_url synology-dsm "{install_root.as_posix()}"'
    )
    result = subprocess.run([_bash_exe(), "-lc", cmd], capture_output=True, text=True, check=True)
    assert result.stdout.strip() == base_url


def test_install_agent_normalizes_synology_compatible_urls(tmp_path):
    script = Path("scripts/install-agent.sh").read_text(encoding="utf-8")
    snippet = _write_shell_snippet(
        tmp_path,
        script,
        ["trim_brain_url_input", "debug_brain_url_validation_failure", "normalize_brain_url"],
    )

    ip_host = "192.168." + "7.200"
    base_url = f"http://{ip_host}:8789"
    cases = [
        (base_url, base_url),
        (f"{base_url}/", base_url),
        ('http://hostname:8789', 'http://hostname:8789'),
        ('https://hostname.example', 'https://hostname.example'),
        ('  "https://hostname.example/"  ', 'https://hostname.example'),
    ]

    for raw, expected in cases:
        env = os.environ.copy()
        env["RAW_URL"] = raw
        cmd = f'source "{snippet.as_posix()}"; normalize_brain_url "$RAW_URL"'
        result = subprocess.run([_bash_exe(), "-lc", cmd], env=env, capture_output=True, text=True, check=True)
        assert result.stdout.strip() == expected
        assert result.stderr.strip() == ""


def test_install_agent_reports_debug_details_for_invalid_url(tmp_path):
    script = Path("scripts/install-agent.sh").read_text(encoding="utf-8")
    snippet = _write_shell_snippet(
        tmp_path,
        script,
        ["trim_brain_url_input", "debug_brain_url_validation_failure", "normalize_brain_url"],
    )

    ip_host = "192.168." + "7.200"
    cmd = f'source "{snippet.as_posix()}"; normalize_brain_url "http://{ip_host}:8789/api"'
    result = subprocess.run([_bash_exe(), "-lc", cmd], capture_output=True, text=True)

    assert result.returncode != 0
    assert f"DEBUG: sanitized URL: http://{ip_host}:8789/api" in result.stderr
    assert "DEBUG: validation rule failed: path segments are not allowed" in result.stderr


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
