from __future__ import annotations

import json
import os
import subprocess
import sys
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
    assert "HARRY_BACKOFF_ENABLE=0" in script
    assert "HARRY_SELF_UPDATE=0" in script
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


def test_linux_agent_resource_backoff_writes_status_and_log(tmp_path):
    script = Path("agent/harry_agent.sh").read_text(encoding="utf-8")
    snippet = _write_shell_snippet(tmp_path, script, ["resource_backoff_skip"])

    log_file = tmp_path / "harry-agent.log"
    status_file = tmp_path / "status.json"
    cmd = (
        f'export LOG_FILE="{log_file.as_posix()}"; '
        f'export STATUS_FILE="{status_file.as_posix()}"; '
        'export HARRY_NODE="nas-1"; '
        'log_fail(){ printf "%s\\n" "$1" >> "$LOG_FILE"; }; '
        'status_mark_failure(){ printf "%s|%s\\n" "$1" "$2" >> "$STATUS_FILE"; }; '
        f'source "{snippet.as_posix()}"; '
        'resource_backoff_skip "memory_pressure" "mem_used=100.00 threshold=92"'
    )

    result = subprocess.run([_bash_exe(), "-lc", cmd], capture_output=True, text=True, check=True)

    assert "Resource backoff triggered; telemetry skipped." in result.stderr
    assert "reason=memory_pressure mem_used=100.00 threshold=92 telemetry_skipped" in result.stderr
    assert "resource_backoff node=nas-1 reason=memory_pressure mem_used=100.00 threshold=92 telemetry_skipped" in log_file.read_text(encoding="utf-8")
    assert 'resource_backoff|reason=memory_pressure mem_used=100.00 threshold=92 telemetry_skipped' in status_file.read_text(encoding="utf-8")


def test_linux_agent_uses_shared_dsm_memory_snapshot_for_backoff_and_telemetry():
    script = Path("agent/harry_agent.sh").read_text(encoding="utf-8")

    assert "collect_memory_snapshot" in script
    assert "memory_snapshot_from_env" in script
    assert "memory_snapshot_from_proc" in script
    assert "HARRY_MEM_USED_PCT" in script
    assert "memory_method" in script
    assert "calculated_cache_adjusted" in script
    assert "memavailable" in script
    assert "fallback" in script


def test_linux_agent_payload_reports_auto_update_mode(tmp_path):
    ip_host = "192.168." + "7.200"
    env = os.environ.copy()
    env["HARRY_PLATFORM"] = "linux-systemd"
    env["HARRY_SELF_UPDATE"] = "1"
    env["HARRY_BACKOFF_ENABLE"] = "0"
    env["HARRY_BASE_URL"] = f"http://{ip_host}:8789"
    env["HARRY_INGEST_URL"] = f"http://{ip_host}:8789/ingest"
    env["HARRY_AGENT_VERSION"] = "0.2.5"
    env["HARRY_SCHEMA_VERSION"] = "0.2.3"
    env["HARRY_BRAIN_VERSION"] = "2026.05.15"
    env["HARRY_NODE"] = "node-1"
    env["PYTHON"] = "python"
    env["CURL"] = "python"

    result = subprocess.run(
        [_bash_exe(), "agent/harry_agent.sh", "--print", "--no-update"],
        env=env,
        capture_output=True,
        text=True,
        check=True,
    )

    payload = json.loads(result.stdout)
    assert payload["capabilities"]["self_update_enabled"] is True
    assert payload["capabilities"]["update_mode"] == "auto"


def test_synology_agent_payload_reports_manual_update_mode(tmp_path):
    ip_host = "192.168." + "7.200"
    env = os.environ.copy()
    env["HARRY_PLATFORM"] = "synology-dsm"
    env["HARRY_SELF_UPDATE"] = "0"
    env["HARRY_BACKOFF_ENABLE"] = "0"
    env["HARRY_BASE_URL"] = f"http://{ip_host}:8789"
    env["HARRY_INGEST_URL"] = f"http://{ip_host}:8789/ingest"
    env["HARRY_AGENT_VERSION"] = "0.2.5"
    env["HARRY_SCHEMA_VERSION"] = "0.2.3"
    env["HARRY_BRAIN_VERSION"] = "2026.05.15"
    env["HARRY_NODE"] = "nas-1"
    env["PYTHON"] = "python"
    env["CURL"] = "python"

    result = subprocess.run(
        [_bash_exe(), "agent/harry_agent.sh", "--print", "--no-update"],
        env=env,
        capture_output=True,
        text=True,
        check=True,
    )

    payload = json.loads(result.stdout)
    assert payload["capabilities"]["self_update_enabled"] is False
    assert payload["capabilities"]["update_mode"] == "manual"


def test_synology_memory_uses_cache_adjusted_calculation_when_memavailable_is_bad(tmp_path):
    script = Path("agent/harry_agent.sh").read_text(encoding="utf-8")
    meminfo = tmp_path / "meminfo"
    meminfo.write_text(
        "\n".join(
            [
                "MemTotal:       8000000 kB",
                "MemFree:        6000000 kB",
                "Buffers:         100000 kB",
                "Cached:         1200000 kB",
                "SReclaimable:     200000 kB",
                "MemAvailable:      50000 kB",
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    snippet = _write_shell_snippet(
        tmp_path,
        script,
        ["read_meminfo_kb", "collect_memory_snapshot"],
        replacements={"/proc/meminfo": meminfo.as_posix()},
    )

    env = os.environ.copy()
    env["HARRY_PLATFORM"] = "synology-dsm"
    env["HARRY_NODE"] = "nas-1"
    env["PYTHON"] = "python"

    log_file = tmp_path / "harry.log"
    cmd = (
        f'LOG_FILE="{log_file.as_posix()}"; '
        'log_fail(){ printf "%s\\n" "$1" >> "$LOG_FILE"; }; '
        f'source "{snippet.as_posix()}"; '
        'collect_memory_snapshot; '
        'printf "%s|%s|%s|%s|%s\\n" '
        '"$HARRY_MEM_METHOD" "$HARRY_MEM_USED_PCT" "$HARRY_MEM_USED_KB" "$HARRY_MEM_AVAILABLE_KB" "$HARRY_MEM_FREE_KB"'
    )

    result = subprocess.run([_bash_exe(), "-lc", cmd], env=env, capture_output=True, text=True, check=True)

    method, used_pct, used_kb, available_kb, free_kb = result.stdout.strip().split("|")
    assert method == "calculated_cache_adjusted"
    assert used_kb == "500000"
    assert available_kb == "7500000"
    assert free_kb == "6000000"
    assert used_pct == "6.25"
    assert "DEBUG: memory method=calculated_cache_adjusted" in result.stderr
    assert "memory_method node=nas-1 platform=synology-dsm method=calculated_cache_adjusted" in log_file.read_text(encoding="utf-8")


def test_synology_storage_telemetry_keeps_volume_mounts_and_skips_pseudo_mounts(tmp_path):
    script = Path("agent/harry_agent.sh").read_text(encoding="utf-8")
    fakebin = tmp_path / "fakebin"
    fakebin.mkdir()

    df = fakebin / "df.cmd"
    df.write_text(
        r"""@echo off
echo Filesystem     1B-blocks      Used Available Use%% Mounted on
echo /dev/vg1/volume_1 1000000   400000    600000  40%% /volume1
echo /dev/vg2/volume_2 2000000   500000   1500000  25%% /volume2
echo /dev/vg3/volume_3 3000000  1500000   1500000  50%% /volume3
echo tmpfs           100000      1000     99000   1%% /run
echo overlay         500000     10000    490000   2%% /var/lib/docker/overlay2/123
echo /dev/loop0      100000      20000     80000  20%% /snap/test
""",
        encoding="utf-8",
    )
    os.chmod(df, 0o755)

    env = os.environ.copy()
    env["PATH"] = f"{fakebin.as_posix()}{os.pathsep}{env.get('PATH', '')}"
    env["HARRY_PLATFORM"] = "synology-dsm"
    env["HARRY_BACKOFF_ENABLE"] = "0"
    env["HARRY_SELF_UPDATE"] = "0"
    env["HARRY_BASE_URL"] = "http://192.168." + "7.200:8789"
    env["HARRY_INGEST_URL"] = "http://192.168." + "7.200:8789/ingest"
    env["HARRY_AGENT_VERSION"] = "0.2.5"
    env["HARRY_SCHEMA_VERSION"] = "0.2.3"
    env["HARRY_BRAIN_VERSION"] = "2026.05.15"

    python_code = script.split('"$PYTHON" - <<\'PY\' >"$TMP_PAYLOAD" 2>"$TMP_ERR"\n', 1)[1].rsplit("\nPY\n", 1)[0]
    fake_df_output = """Filesystem     1B-blocks      Used Available Use% Mounted on\n/dev/vg1/volume_1 1000000   400000    600000  40% /volume1\n/dev/vg2/volume_2 2000000   500000   1500000  25% /volume2\n/dev/vg3/volume_3 3000000  1500000   1500000  50% /volume3\next4            500000      10000    490000   2% /var/lib/docker/containers/xyz\ntmpfs           100000      1000     99000   1% /run\noverlay         500000     10000    490000   2% /var/lib/docker/overlay2/123\n/dev/loop0      100000      20000     80000  20% /snap/test\n"""
    python_code = (
        "import shutil, subprocess\n"
        "_orig_shutil_which = shutil.which\n"
        "_orig_check_output = subprocess.check_output\n"
        f"_fake_df_output = {fake_df_output!r}\n"
        "shutil.which = lambda x: 'df.cmd' if x == 'df' else _orig_shutil_which(x)\n"
        "def _fake_check_output(cmd, stderr=None, text=None, **kwargs):\n"
        "    if isinstance(cmd, (list, tuple)) and cmd and cmd[0] == 'df':\n"
        "        return _fake_df_output\n"
        "    return _orig_check_output(cmd, stderr=stderr, text=text, **kwargs)\n"
        "subprocess.check_output = _fake_check_output\n"
        + python_code
    )
    result = subprocess.run([sys.executable, "-c", python_code], env=env, capture_output=True, text=True, check=True)
    payload = json.loads(result.stdout)
    disk_used = payload["metrics"]["disk_used"]
    storage_debug = payload["metrics"]["extensions"]["storage_debug"]

    assert [m["mount"] for m in disk_used] == ["/volume1", "/volume2", "/volume3"]
    assert disk_used[0]["fs"] == "/dev/vg1/volume_1"
    assert disk_used[0]["total_b"] == 1000000
    assert disk_used[0]["used_b"] == 400000
    assert disk_used[0]["free_b"] == 600000
    assert disk_used[0]["used_pct"] == 40.0
    assert disk_used[0]["device"] == "/dev/vg1/volume_1"
    assert any("pseudo_filesystem" in line and "tmpfs" in line for line in storage_debug)
    assert any("docker_runtime_mount" in line for line in storage_debug)
    assert any("loop_mount" in line for line in storage_debug)


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
