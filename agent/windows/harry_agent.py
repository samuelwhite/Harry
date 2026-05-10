import argparse
import json
import os
import re
import socket
import subprocess
import time
import sys
from pathlib import Path
import urllib.error
import urllib.request

try:
    import psutil
except ImportError:
    print("psutil not installed")
    raise SystemExit(1)

AGENT_VERSION = "0.2.5"
SCHEMA_VERSION = "0.2.3"
CONFIG_PATH = r"C:\ProgramData\Harry\agent_config.json"
POLL_SECONDS = 30
UPDATE_SCRIPT_NAME = "update_agent.ps1"


def iso_now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def load_config() -> dict:
    try:
        with open(CONFIG_PATH, "r", encoding="utf-8-sig") as f:
            data = json.load(f)
            return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _version_key(value: str | None) -> tuple[int, ...]:
    raw = (value or "").strip()
    if not raw or raw.lower() == "unknown":
        return ()

    core = re.split(r"[-+]", raw, maxsplit=1)[0]
    parts: list[int] = []
    for chunk in core.split("."):
        match = re.search(r"\d+", chunk)
        if not match:
            return ()
        parts.append(int(match.group(0)))
    return tuple(parts)


def _is_newer_version(candidate: str | None, current: str | None) -> bool:
    c = _version_key(candidate)
    cur = _version_key(current)
    return bool(c and cur and c > cur)


def _install_root() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


def _update_script_path() -> Path:
    return _install_root() / UPDATE_SCRIPT_NAME


def _brain_update_script_url(discovery: dict | None = None) -> str:
    if discovery and isinstance(discovery, dict):
        candidate = str(discovery.get("agent_update_script_url") or "").strip()
        if candidate:
            return candidate
    return f"{BRAIN_URL.rstrip('/')}/downloads/windows-update-script"


def _fetch_brain_discovery() -> dict | None:
    discover_url = f"{BRAIN_URL.rstrip('/')}/discover"
    req = urllib.request.Request(
        discover_url,
        headers={"Accept": "application/json"},
        method="GET",
    )

    try:
        with urllib.request.urlopen(req, timeout=5) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
    except Exception:
        return None

    try:
        data = json.loads(raw)
    except Exception:
        return None

    if not isinstance(data, dict):
        return None
    if data.get("service") != "harry-brain" or data.get("ok") is not True:
        return None
    return data


def _launch_windows_updater(update_url: str) -> bool:
    script = _update_script_path()
    if not script.exists():
        remote_script_url = _brain_update_script_url()
        try:
            data = urllib.request.urlopen(remote_script_url, timeout=5).read()
            script.parent.mkdir(parents=True, exist_ok=True)
            script.write_bytes(data)
        except Exception as exc:
            print(f"Windows updater script fetch failed: {exc}")

    if not script.exists():
        print(f"Windows updater not found at {script}")
        return False

    powershell_exe = (
        Path(os.environ.get("SystemRoot", r"C:\Windows"))
        / "System32"
        / "WindowsPowerShell"
        / "v1.0"
        / "powershell.exe"
    )

    cmd = [
        str(powershell_exe),
        "-NoProfile",
        "-ExecutionPolicy",
        "Bypass",
        "-File",
        str(script),
        "-BrainUrl",
        BRAIN_URL,
        "-AgentDownloadUrl",
        update_url,
        "-CurrentVersion",
        AGENT_VERSION,
    ]

    try:
        creationflags = 0
        creationflags |= getattr(subprocess, "DETACHED_PROCESS", 0)
        creationflags |= getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
        subprocess.Popen(
            cmd,
            cwd=str(script.parent),
            creationflags=creationflags,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        print(f"Windows updater scheduled from {update_url}")
        return True
    except Exception as exc:
        print(f"Windows updater launch failed: {exc}")
        return False


def maybe_self_update() -> bool:
    if os.environ.get("HARRY_SKIP_SELF_UPDATE") == "1":
        return False
    if os.environ.get("HARRY_SELF_UPDATE", "1") == "0":
        return False
    if os.name != "nt":
        return False

    discovery = _fetch_brain_discovery()
    if not discovery:
        return False

    remote_agent_version = str(discovery.get("agent_version") or "").strip()
    if not remote_agent_version or remote_agent_version.lower() == "unknown":
        return False

    if not _is_newer_version(remote_agent_version, AGENT_VERSION):
        return False

    update_url = str(
        discovery.get("agent_download_url")
        or f"{BRAIN_URL.rstrip('/')}/downloads/windows-agent-exe"
    ).strip()
    if not update_url:
        return False

    print(
        "Windows agent update available:",
        f"local={AGENT_VERSION}",
        f"remote={remote_agent_version}",
    )
    return _launch_windows_updater(update_url)


config = load_config()
BRAIN_URL = (
    config.get("public_base_url")
    or config.get("brain_url")
    or os.environ.get("HARRY_PUBLIC_BASE_URL")
    or os.environ.get("HARRY_BASE_URL")
    or "http://harry-brain:8789"
).rstrip("/")
ENDPOINT = f"{BRAIN_URL}/ingest"


def run_ps_one_line(ps: str) -> str | None:
    try:
        result = subprocess.run(
            ["powershell", "-NoProfile", "-Command", ps],
            capture_output=True,
            text=True,
            timeout=8,
        )
        if result.returncode != 0:
            return None
        out = (result.stdout or "").strip()
        return out or None
    except Exception:
        return None


def run_ps_json(ps: str):
    try:
        result = subprocess.run(
            ["powershell", "-NoProfile", "-Command", ps],
            capture_output=True,
            text=True,
            timeout=12,
        )
        if result.returncode != 0:
            return None
        out = (result.stdout or "").strip()
        if not out:
            return None
        return json.loads(out)
    except Exception:
        return None


def get_hostname() -> str:
    return socket.gethostname()


def get_model() -> str | None:
    return run_ps_one_line("(Get-CimInstance Win32_ComputerSystem).Model")


def get_bios_version() -> str | None:
    return run_ps_one_line("(Get-CimInstance Win32_BIOS).SMBIOSBIOSVersion")


def get_bios_release_date() -> str | None:
    ps = r"""
$dt = (Get-CimInstance Win32_BIOS).ReleaseDate
if ($dt) {
  try {
    [System.Management.ManagementDateTimeConverter]::ToDateTime($dt).ToString("yyyy-MM-dd")
  } catch {
    try {
      (Get-Date $dt).ToString("yyyy-MM-dd")
    } catch {
      $null
    }
  }
}
"""
    return run_ps_one_line(ps)


def get_cpu_name() -> str | None:
    return run_ps_one_line(
        "(Get-CimInstance Win32_Processor | Select-Object -First 1 -ExpandProperty Name)"
    )


def get_cpu_cores() -> int | None:
    try:
        return psutil.cpu_count(logical=True)
    except Exception:
        return None


def get_memory_info() -> dict:
    ps = r"""
$mods = Get-CimInstance Win32_PhysicalMemory | Select-Object BankLabel, Capacity, SMBIOSMemoryType, Speed, Manufacturer, PartNumber
$arr  = Get-CimInstance Win32_PhysicalMemoryArray | Select-Object MemoryDevices, MaxCapacity, MaxCapacityEx

[pscustomobject]@{
  modules = @($mods)
  arrays  = @($arr)
} | ConvertTo-Json -Compress -Depth 4
"""
    data = run_ps_json(ps)
    info = {
        "ram_total_gb": None,
        "ram_slots_total": None,
        "ram_slots_used": None,
        "ram_type": None,
        "ram_max_gb": None,
    }
    if not data:
        return info

    modules = data.get("modules") or []
    arrays = data.get("arrays") or []

    if isinstance(modules, dict):
        modules = [modules]
    if isinstance(arrays, dict):
        arrays = [arrays]

    total_bytes = 0
    used = 0
    ram_type = None

    type_map = {
        "20": "DDR",
        "21": "DDR2",
        "24": "DDR3",
        "26": "DDR4",
        "34": "DDR5",
    }

    for mod in modules:
        cap = mod.get("Capacity")
        try:
            if cap:
                total_bytes += int(cap)
                used += 1
        except Exception:
            pass

        mt = mod.get("SMBIOSMemoryType")
        if mt is not None and ram_type is None:
            ram_type = type_map.get(str(mt).strip())

    if total_bytes > 0:
        gb = total_bytes / (1024 ** 3)
        info["ram_total_gb"] = int(gb) if gb.is_integer() else round(gb, 1)

    if used > 0:
        info["ram_slots_used"] = used

    slots_total = 0
    for arr in arrays:
        try:
            md = arr.get("MemoryDevices")
            if md:
                slots_total += int(md)
        except Exception:
            pass
    if slots_total > 0:
        info["ram_slots_total"] = slots_total

    max_vals = []
    for arr in arrays:
        try:
            mcx = arr.get("MaxCapacityEx")
            if mcx:
                gb = int(mcx) / (1024 ** 3)
                if 1 <= gb <= 128:
                    max_vals.append(int(round(gb)))
                    continue
        except Exception:
            pass

        try:
            mc = arr.get("MaxCapacity")
            if mc:
                gb = int(mc) / 1024 / 1024
                if 1 <= gb <= 128:
                    max_vals.append(int(round(gb)))
        except Exception:
            pass

    if max_vals:
        info["ram_max_gb"] = sum(max_vals)
    else:
        info["ram_max_gb"] = None

    info["ram_type"] = ram_type
    return info


def get_cpu_load_1m() -> float | None:
    try:
        return round(psutil.cpu_percent(interval=1) / 100.0, 2)
    except Exception:
        return None


def get_mem_used_pct() -> float | None:
    try:
        return round(psutil.virtual_memory().percent, 2)
    except Exception:
        return None


def get_disk_used_pct() -> float | None:
    try:
        return round(psutil.disk_usage("C:\\").percent, 2)
    except Exception:
        return None


def get_disk_size_gb() -> float | None:
    try:
        total_bytes = psutil.disk_usage("C:\\").total
        return round(total_bytes / (1024 ** 3), 2)
    except Exception:
        return None


def get_disks() -> list[dict]:
    ps = r"""
$items = Get-CimInstance Win32_DiskDrive | Select-Object Model, SerialNumber, Size, MediaType
$items | ConvertTo-Json -Compress
"""
    data = run_ps_json(ps)
    if not data:
        return []

    if isinstance(data, dict):
        data = [data]

    disks = []
    for d in data:
        size_gb = None
        try:
            if d.get("Size"):
                size_gb = round(int(d["Size"]) / (1024 ** 3), 1)
        except Exception:
            pass

        media = (d.get("MediaType") or "").strip() or None

        disks.append(
            {
                "name": d.get("Model") or "disk",
                "type": None,
                "size_gb": size_gb,
                "model": d.get("Model"),
                "serial": d.get("SerialNumber"),
                "media_type": media,
            }
        )
    return disks


def get_gpus() -> list[dict]:
    ps = r"""
$items = Get-CimInstance Win32_VideoController |
  Select-Object Name, Caption, Description, AdapterRAM, DriverVersion, VideoProcessor, PNPDeviceID, Status, AdapterCompatibility, InstalledDisplayDrivers |
  Where-Object {
    ($_.Name -and $_.Name.Trim() -ne "") -or
    ($_.Caption -and $_.Caption.Trim() -ne "") -or
    ($_.Description -and $_.Description.Trim() -ne "")
  }

if (-not $items) {
  $items = Get-CimInstance Win32_PnPEntity |
    Where-Object { $_.PNPClass -eq "Display" } |
    Select-Object Name, Caption, Description, PNPDeviceID, Status, AdapterCompatibility
}

$items | ConvertTo-Json -Compress
"""
    data = run_ps_json(ps)
    if not data:
        return []

    if isinstance(data, dict):
        data = [data]

    gpus = []
    seen = set()

    for g in data:
        name = (g.get("Name") or g.get("Caption") or g.get("Description") or g.get("VideoProcessor") or "").strip()
        if not name:
            continue

        pnp = (g.get("PNPDeviceID") or "").strip()
        key = f"{name.lower()}::{pnp.lower()}"
        if key == "::":
            key = name.lower()
        if key in seen:
            continue
        seen.add(key)

        vram_mb = None
        try:
            if g.get("AdapterRAM") is not None:
                vram_mb = int(int(g["AdapterRAM"]) / (1024 * 1024))
        except Exception:
            pass

        vendor = (g.get("AdapterCompatibility") or "").strip() or None
        if not vendor:
            lowered = name.lower()
            if "nvidia" in lowered or "geforce" in lowered or "quadro" in lowered or "rtx" in lowered or "gtx" in lowered:
                vendor = "NVIDIA"
            elif "intel" in lowered or "iris" in lowered or "uhd graphics" in lowered:
                vendor = "Intel"
            elif "amd" in lowered or "radeon" in lowered:
                vendor = "AMD"

        pnp_upper = pnp.upper()
        integrated = False

        lower_name = name.lower()
        if "vega" in lower_name or "radeon(tm)" in lower_name:
            integrated = True
        if "intel" in lower_name or "uhd graphics" in lower_name or "iris xe" in lower_name:
            integrated = True
        if "PCI\\VEN_" in pnp_upper:
            integrated = False if "NVIDIA" in name.upper() or "GEFORCE" in name.upper() else integrated

        cuda_capable = bool(vendor and vendor.upper() == "NVIDIA")
        directml_capable = bool(vendor and vendor.upper() in {"NVIDIA", "AMD", "INTEL"})
        dedicated = not integrated and vendor is not None

        capability_hint = None
        if cuda_capable:
            capability_hint = "CUDA capable"
        elif integrated:
            capability_hint = "Integrated graphics"
        elif dedicated:
            capability_hint = "Dedicated graphics"
        elif directml_capable:
            capability_hint = "DirectML capable"

        gpus.append(
            {
                "name": name,
                "vendor": vendor,
                "vram_mb": vram_mb,
                "mem_total_mb": vram_mb,
                "driver": g.get("DriverVersion"),
                "driver_version": g.get("DriverVersion"),
                "video_processor": g.get("VideoProcessor"),
                "status": g.get("Status"),
                "pnp_device_id": g.get("PNPDeviceID"),
                "integrated": integrated,
                "dedicated": dedicated,
                "cuda_capable": cuda_capable,
                "directml_capable": directml_capable,
                "capability_hint": capability_hint,
            }
        )

    return gpus


def build_payload() -> dict:
    now = iso_now()
    hostname = get_hostname()
    mem = get_memory_info()
    gpus = get_gpus()

    payload = {
        "schema_version": SCHEMA_VERSION,
        "agent_version": AGENT_VERSION,
        "node": hostname,
        "ts": now,
        "agent_status": {
            "state": "running",
            "stage": "collecting",
            "ok": True,
            "error_code": None,
            "error_summary": None,
            "consecutive_failures": 0,
            "last_run_at": now,
            "last_success_at": now,
            "last_error_at": None,
        },
        "capabilities": {
            "gpu": True,
            "docker": False,
            "systemd": False,
            "temperature": False,
            "smart": False,
        },
        "facts": {
            "hostname": hostname,
            "model": get_model(),
            "cpu": get_cpu_name(),
            "cpu_cores": get_cpu_cores(),
            "ram_total_gb": mem["ram_total_gb"],
            "ram_max_gb": mem["ram_max_gb"],
            "ram_slots_total": mem["ram_slots_total"],
            "ram_slots_used": mem["ram_slots_used"],
            "ram_type": mem["ram_type"],
            "bios_release_date": get_bios_release_date(),
            "bios_version": get_bios_version(),
            "disks": get_disks(),
            "gpus": gpus,
            "extensions": {},
        },
        "metrics": {
            "cpu_load_1m": get_cpu_load_1m(),
            "mem_used_pct": get_mem_used_pct(),
            "disk_used": [
                {
                    "fs": "NTFS",
                    "mount": "C:\\",
                    "used_pct": get_disk_used_pct(),
                    "size_gb": get_disk_size_gb(),
                }
            ],
            "temps_c": {},
            "gpu": gpus,
            "extensions": {},
        },
        "derived": {
            "health": {
                "state": "unknown",
                "worst_severity": "unknown",
                "reasons": [],
            },
            "extensions": {},
        },
        "advice": [],
    }
    return payload


def send(payload: dict) -> None:
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        ENDPOINT,
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            body = resp.read().decode("utf-8", errors="replace")
            print(f"Sent OK: HTTP {resp.status} {body}")
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")
        print(f"HTTP error: {e.code} {body}")
    except urllib.error.URLError as e:
        print(f"Failed to send: {e}")


def build_diagnostics_summary() -> dict:
    discovery = _fetch_brain_discovery() or {}
    payload = build_payload()
    gpus = payload.get("facts", {}).get("gpus")
    if not isinstance(gpus, list):
        gpus = []

    return {
        "agent_version": AGENT_VERSION,
        "brain_url": BRAIN_URL,
        "endpoint": ENDPOINT,
        "discovery_ok": bool(discovery.get("ok")),
        "discovery_service": discovery.get("service"),
        "discovery_agent_version": discovery.get("agent_version"),
        "discovery_canonical_base_url": discovery.get("canonical_base_url"),
        "discovery_recommended_lan_url": discovery.get("recommended_lan_url"),
        "gpu_count": len(gpus),
        "payload_node": payload.get("node"),
        "payload_last_seen": payload.get("ts"),
        "ingest_url": ENDPOINT,
    }


def main() -> None:
    parser = argparse.ArgumentParser(add_help=True)
    parser.add_argument("--version", action="store_true", help="Print the agent version and exit.")
    parser.add_argument(
        "--diagnostics",
        action="store_true",
        help="Print a local diagnostics summary and exit without sending telemetry.",
    )
    args = parser.parse_args()

    if args.version:
        print(AGENT_VERSION)
        return

    if args.diagnostics:
        print(json.dumps(build_diagnostics_summary(), indent=2, sort_keys=True))
        return

    print("Harry Windows Agent starting")
    print("Brain:", BRAIN_URL)
    print("Endpoint:", ENDPOINT)

    if maybe_self_update():
        print("Windows agent update started; exiting to let the updater replace the binary.")
        return

    while True:
        payload = build_payload()
        print("Sending payload for node:", payload["node"])
        send(payload)
        time.sleep(POLL_SECONDS)


if __name__ == "__main__":
    main()
