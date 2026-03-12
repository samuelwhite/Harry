import json
import math
import os
import socket
import subprocess
import time
import urllib.request
import urllib.error

try:
    import psutil
except ImportError:
    print("psutil not installed")
    raise SystemExit(1)

AGENT_VERSION = "0.2.3-windows-dev"
SCHEMA_VERSION = "0.2.3"

BRAIN_URL = os.environ.get("HARRY_BASE_URL", "http://127.0.0.1:8787").rstrip("/")
ENDPOINT = f"{BRAIN_URL}/ingest"
POLL_SECONDS = 30


def iso_now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def run_ps_one_line(ps: str) -> str | None:
    try:
        r = subprocess.run(
            ["powershell", "-NoProfile", "-Command", ps],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if r.returncode != 0:
            return None
        out = (r.stdout or "").strip()
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
    return run_ps_one_line("(Get-CimInstance Win32_Processor | Select-Object -First 1 -ExpandProperty Name)")


def get_ram_total_gb() -> int | None:
    try:
        total_bytes = psutil.virtual_memory().total
        return int(math.ceil(total_bytes / (1024 ** 3)))
    except Exception:
        return None


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


def build_payload() -> dict:
    hostname = get_hostname()
    disk_used_pct = get_disk_used_pct()

    return {
        "node": hostname,
        "agent_version": AGENT_VERSION,
        "schema_version": SCHEMA_VERSION,
        "ts": iso_now(),
        "agent_status": {
            "ok": True,
            "error_code": None,
            "error_summary": None,
        },
        "facts": {
            "hostname": hostname,
            "model": get_model(),
            "bios_version": get_bios_version(),
            "cpu": get_cpu_name(),
            "ram_total_gb": get_ram_total_gb(),
            "gpus": [],
            "extensions": {},
        },
        "metrics": {
            "cpu_load_1m": get_cpu_load_1m(),
            "mem_used_pct": get_mem_used_pct(),
            "disk_used": [
                {
                    "mount": "C:\\",
                    "used_pct": disk_used_pct,
                    "fs": "NTFS",
                }
            ],
            "temps_c": {},
            "gpu": [],
            "extensions": {},
        },
        "derived": {
            "health": {"state": "unknown", "worst_severity": "unknown", "reasons": []},
            "extensions": {},
        },
        "advice": [],
    }


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
