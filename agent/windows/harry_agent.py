import json
import os
import socket
import subprocess
import time
import urllib.error
import urllib.request

try:
    import psutil
except ImportError:
    print("psutil not installed")
    raise SystemExit(1)

AGENT_VERSION = "0.2.3-windows-dev"
SCHEMA_VERSION = "0.2.3"
CONFIG_PATH = r"C:\ProgramData\Harry\agent_config.json"
POLL_SECONDS = 30


def iso_now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def load_config() -> dict:
    try:
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
            return data if isinstance(data, dict) else {}
    except Exception:
        return {}


config = load_config()
BRAIN_URL = (
    config.get("brain_url")
    or os.environ.get("HARRY_BASE_URL")
    or "http://127.0.0.1:8787"
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
$arr  = Get-CimInstance Win32_PhysicalMemoryArray | Select-Object MemoryDevices, MaxCapacity

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

    # Many systems report silly/unsafe max values here, so keep it conservative.
    max_vals = []
    for arr in arrays:
        try:
            mc = arr.get("MaxCapacity")
            if mc:
                # Win32_PhysicalMemoryArray MaxCapacity is in KB
                gb = int(mc) / 1024 / 1024
                if 1 <= gb <= 128:
                    max_vals.append(int(round(gb)))
        except Exception:
            pass
    if max_vals:
        info["ram_max_gb"] = sum(max_vals)

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


def build_payload() -> dict:
    now = iso_now()
    hostname = get_hostname()
    mem = get_memory_info()

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
            "gpus": [],
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
            "gpu": [],
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


def main() -> None:
    print("Harry Windows Agent starting")
    print("Brain:", BRAIN_URL)
    print("Endpoint:", ENDPOINT)

    while True:
        payload = build_payload()
        print("Sending payload for node:", payload["node"])
        send(payload)
        time.sleep(POLL_SECONDS)


if __name__ == "__main__":
    main()
