import json
import math
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
            timeout=5,
        )
        if result.returncode != 0:
            return None
        out = (result.stdout or "").strip()
        return out or None
    except Exception:
        return None


def get_hostname() -> str:
    return socket.gethostname()


def get_model() -> str | None:
    return run_ps_one_line("(Get-CimInstance Win32_ComputerSystem).Model")


def get_bios_version() -> str | None:
    return run_ps_one_line("(Get-CimInstance Win32_BIOS).SMBIOSBIOSVersion")


def get_cpu_name() -> str | None:
    return run_ps_one_line(
        "(Get-CimInstance Win32_Processor | Select-Object -First 1 -ExpandProperty Name)"
    )


def get_cpu_cores() -> int | None:
    try:
        return psutil.cpu_count(logical=True)
    except Exception:
        return None


def get_ram_total_gb() -> int | None:
    try:
        total_bytes = psutil.virtual_memory().total
        return int(math.ceil(total_bytes / (1024 ** 3)))
    except Exception:
        return None


def get_cpu_load_1m() -> float | None:
    try:
        # Windows does not expose Linux load average in the same way.
        # Use CPU utilisation as a temporary surrogate.
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


def build_payload() -> dict:
    now = iso_now()
    hostname = get_hostname()

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
            "ram_total_gb": get_ram_total_gb(),
            "ram_max_gb": None,
            "ram_slots_total": None,
            "ram_slots_used": None,
            "ram_type": None,
            "bios_release_date": None,
            "bios_version": get_bios_version(),
            "disks": [],
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
