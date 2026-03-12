import json
import os
import platform
import time
import urllib.request
import urllib.error

try:
    import psutil
except ImportError:
    print("psutil not installed")
    exit(1)

BRAIN_URL = os.environ.get("HARRY_BASE_URL", "http://127.0.0.1:8789")
ENDPOINT = f"{BRAIN_URL}/agent/report"


def collect():
    return {
        "node": platform.node(),
        "os": platform.system(),
        "platform": platform.platform(),
        "cpu_percent": psutil.cpu_percent(interval=1),
        "ram_percent": psutil.virtual_memory().percent,
        "disk_percent": psutil.disk_usage("/").percent,
        "timestamp": time.time(),
    }


def send(payload):
    data = json.dumps(payload).encode("utf-8")

    req = urllib.request.Request(
        ENDPOINT,
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    try:
        with urllib.request.urlopen(req, timeout=5) as resp:
            resp.read()
    except urllib.error.URLError as e:
        print("Failed to send:", e)


def main():
    print("Harry Windows Agent starting")
    print("Brain:", BRAIN_URL)

    while True:
        payload = collect()
        send(payload)
        time.sleep(30)


if __name__ == "__main__":
    main()
