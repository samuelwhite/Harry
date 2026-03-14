#!/usr/bin/env bash
set -euo pipefail

# -----------------------------------------------------------------------------
# Harry Agent (self-updating, robust)
# -----------------------------------------------------------------------------

AGENT_VERSION="0.2.3"
SCHEMA_VERSION="0.2.3"
BRAIN_VERSION="2026.03.08"

CURL="${CURL:-/usr/bin/curl}"
PYTHON="${PYTHON:-python3}"

if ! command -v "$PYTHON" >/dev/null 2>&1; then
  PYTHON="python"
fi

NODE_DEFAULT="$(hostname 2>/dev/null || true)"
NODE_DEFAULT="${NODE_DEFAULT:-unknown}"
export HARRY_NODE="${HARRY_NODE:-$NODE_DEFAULT}"

# -----------------------------------------------------------------------------
# Failure logging helper
# -----------------------------------------------------------------------------
LOG_FILE="${HARRY_LOG_FILE:-/var/log/harry-agent.log}"
if ! ( touch "$LOG_FILE" >/dev/null 2>&1 ); then
  LOG_FILE="/tmp/harry-agent.log"
  touch "$LOG_FILE" >/dev/null 2>&1 || true
fi

log_fail() {
  local msg="$1"
  printf '[%s] %s\n' "$(date -u +'%Y-%m-%dT%H:%M:%SZ')" "$msg" >> "$LOG_FILE" 2>/dev/null || true
}

# -----------------------------------------------------------------------------
# Local runtime status
# -----------------------------------------------------------------------------
STATUS_DIR="${HARRY_STATUS_DIR:-/var/lib/harry-agent}"
STATUS_FILE="${HARRY_STATUS_FILE:-$STATUS_DIR/status.json}"

if ! mkdir -p "$STATUS_DIR" >/dev/null 2>&1; then
  STATUS_DIR="/tmp"
  STATUS_FILE="${HARRY_STATUS_FILE:-$STATUS_DIR/status.json}"
fi

iso_now() {
  date -u +'%Y-%m-%dT%H:%M:%SZ'
}

status_mark_start() {
  [ "${PRINT_ONLY:-0}" = "1" ] && return 0
  STATUS_FILE="$STATUS_FILE" "$PYTHON" - <<'PY'
import json, os, tempfile
from datetime import datetime, timezone

path = os.environ["STATUS_FILE"]
now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

data = {}
try:
    with open(path, "r", encoding="utf-8") as fh:
        raw = json.load(fh)
        if isinstance(raw, dict):
            data = raw
except Exception:
    data = {}

state = "bootstrapping" if not data.get("last_success_at") else "running"
data["state"] = state
data["stage"] = "collecting"
data["last_run_at"] = now
data.setdefault("consecutive_failures", 0)
data["ok"] = True
data.setdefault("error_code", None)
data.setdefault("error_summary", None)

fd, tmp = tempfile.mkstemp(
    prefix="harry-agent-status-",
    suffix=".json",
    dir=(os.path.dirname(path) or "."),
)
os.close(fd)
with open(tmp, "w", encoding="utf-8") as fh:
    json.dump(data, fh, separators=(",", ":"), ensure_ascii=False)
os.replace(tmp, path)
PY
}

status_mark_sending() {
  [ "${PRINT_ONLY:-0}" = "1" ] && return 0
  STATUS_FILE="$STATUS_FILE" "$PYTHON" - <<'PY'
import json, os, tempfile
from datetime import datetime, timezone

path = os.environ["STATUS_FILE"]
now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

data = {}
try:
    with open(path, "r", encoding="utf-8") as fh:
        raw = json.load(fh)
        if isinstance(raw, dict):
            data = raw
except Exception:
    data = {}

data["state"] = data.get("state") or "running"
data["stage"] = "sending"
data["last_run_at"] = data.get("last_run_at") or now
data.setdefault("consecutive_failures", 0)
data["ok"] = True
data.setdefault("error_code", None)
data.setdefault("error_summary", None)

fd, tmp = tempfile.mkstemp(
    prefix="harry-agent-status-",
    suffix=".json",
    dir=(os.path.dirname(path) or "."),
)
os.close(fd)
with open(tmp, "w", encoding="utf-8") as fh:
    json.dump(data, fh, separators=(",", ":"), ensure_ascii=False)
os.replace(tmp, path)
PY
}

status_mark_success() {
  [ "${PRINT_ONLY:-0}" = "1" ] && return 0
  STATUS_FILE="$STATUS_FILE" "$PYTHON" - <<'PY'
import json, os, tempfile
from datetime import datetime, timezone

path = os.environ["STATUS_FILE"]
now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

data = {}
try:
    with open(path, "r", encoding="utf-8") as fh:
        raw = json.load(fh)
        if isinstance(raw, dict):
            data = raw
except Exception:
    data = {}

data["state"] = "healthy"
data["stage"] = "complete"
data["last_run_at"] = data.get("last_run_at") or now
data["last_success_at"] = now
data["last_error_at"] = None
data["consecutive_failures"] = 0
data["ok"] = True
data["error_code"] = None
data["error_summary"] = None

fd, tmp = tempfile.mkstemp(
    prefix="harry-agent-status-",
    suffix=".json",
    dir=(os.path.dirname(path) or "."),
)
os.close(fd)
with open(tmp, "w", encoding="utf-8") as fh:
    json.dump(data, fh, separators=(",", ":"), ensure_ascii=False)
os.replace(tmp, path)
PY
}

status_mark_failure() {
  [ "${PRINT_ONLY:-0}" = "1" ] && return 0

  local err_code="${1:-agent_failed}"
  local err_summary="${2:-unknown_error}"

  STATUS_FILE="$STATUS_FILE" STATUS_ERR_CODE="$err_code" STATUS_ERR_SUMMARY="$err_summary" "$PYTHON" - <<'PY'
import json, os, tempfile
from datetime import datetime, timezone

path = os.environ["STATUS_FILE"]
err_code = os.environ.get("STATUS_ERR_CODE") or "agent_failed"
err_summary = os.environ.get("STATUS_ERR_SUMMARY") or "unknown_error"
now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

data = {}
try:
    with open(path, "r", encoding="utf-8") as fh:
        raw = json.load(fh)
        if isinstance(raw, dict):
            data = raw
except Exception:
    data = {}

fails = int(data.get("consecutive_failures") or 0) + 1
state = "error" if fails >= 3 else "degraded"

data["state"] = state
data["stage"] = "failed"
data["last_run_at"] = data.get("last_run_at") or now
data["last_error_at"] = now
data["consecutive_failures"] = fails
data["ok"] = False
data["error_code"] = err_code[:80]
data["error_summary"] = err_summary[:240]

fd, tmp = tempfile.mkstemp(
    prefix="harry-agent-status-",
    suffix=".json",
    dir=(os.path.dirname(path) or "."),
)
os.close(fd)
with open(tmp, "w", encoding="utf-8") as fh:
    json.dump(data, fh, separators=(",", ":"), ensure_ascii=False)
os.replace(tmp, path)
PY
}

if ! command -v "$CURL" >/dev/null 2>&1; then
  log_fail "dependency_missing node=${HARRY_NODE} command=curl"
  echo "curl not found; cannot run agent. Install curl and retry." >&2
  exit 20
fi

HARRY_BASE_URL="${HARRY_BASE_URL:-}"
HARRY_INGEST_URL="${HARRY_INGEST_URL:-}"
HARRY_URL="${HARRY_URL:-}"

if [ -n "$HARRY_BASE_URL" ]; then
  HARRY_BASE_URL="${HARRY_BASE_URL%/}"
  HARRY_INGEST_URL="${HARRY_INGEST_URL:-$HARRY_BASE_URL/ingest}"
else
  if [ -z "$HARRY_INGEST_URL" ] && [ -n "$HARRY_URL" ]; then
    HARRY_INGEST_URL="$HARRY_URL"
  fi
  HARRY_INGEST_URL="${HARRY_INGEST_URL:-http://127.0.0.1:8787/ingest}"

  if [[ "$HARRY_INGEST_URL" == */ingest ]]; then
    HARRY_BASE_URL="${HARRY_INGEST_URL%/ingest}"
  else
    HARRY_BASE_URL="${HARRY_INGEST_URL%/*}"
  fi
fi

DIST_URL="${HARRY_BASE_URL%/}/dist/harry_agent.sh"

SELF_UPDATE="${HARRY_SELF_UPDATE:-1}"
PRINT_ONLY=0
NO_UPDATE=0

for arg in "${@:-}"; do
  case "$arg" in
    --print|--dry-run) PRINT_ONLY=1 ;;
    --no-update) NO_UPDATE=1 ;;
  esac
done

json_is_valid_file() {
  local f="$1"
  "$PYTHON" - <<'PY' "$f" >/dev/null 2>&1
import sys, json
p = sys.argv[1]
with open(p, "r", encoding="utf-8") as fh:
    json.loads(fh.read())
PY
}

# -----------------------------------------------------------------------------
# Self-update
# -----------------------------------------------------------------------------
self_update() {
  if [ "$SELF_UPDATE" = "0" ] || [ "$NO_UPDATE" = "1" ] || [ "${HARRY_SKIP_SELF_UPDATE:-0}" = "1" ]; then
    return 0
  fi

  local me
  me="$(readlink -f "$0" 2>/dev/null || echo "$0")"
  if [ ! -f "$me" ]; then
    return 0
  fi

  local tmp
  tmp="$(mktemp /tmp/harry_agent.XXXXXX.sh)"

  if ! "$CURL" -fsSL "$DIST_URL" -o "$tmp" >/dev/null 2>&1; then
    rm -f "$tmp" >/dev/null 2>&1 || true
    log_fail "self_update_failed node=${HARRY_NODE} reason=download_failed dist_url=${DIST_URL}"
    return 0
  fi

  if [ ! -s "$tmp" ]; then
    rm -f "$tmp" >/dev/null 2>&1 || true
    log_fail "self_update_failed node=${HARRY_NODE} reason=empty_candidate dist_url=${DIST_URL}"
    return 0
  fi

  chmod 755 "$tmp" >/dev/null 2>&1 || true

  if ! bash -n "$tmp" >/dev/null 2>&1; then
    rm -f "$tmp" >/dev/null 2>&1 || true
    log_fail "self_update_failed node=${HARRY_NODE} reason=bash_syntax_invalid dist_url=${DIST_URL}"
    return 0
  fi

  local tmp_payload
  tmp_payload="$(mktemp /tmp/harry_agent_payload.XXXXXX.json)"
  if ! bash "$tmp" --print --no-update >"$tmp_payload" 2>/dev/null; then
    rm -f "$tmp" "$tmp_payload" >/dev/null 2>&1 || true
    log_fail "self_update_failed node=${HARRY_NODE} reason=candidate_print_check_failed dist_url=${DIST_URL}"
    return 0
  fi

  if [ ! -s "$tmp_payload" ] || ! json_is_valid_file "$tmp_payload"; then
    rm -f "$tmp" "$tmp_payload" >/dev/null 2>&1 || true
    log_fail "self_update_failed node=${HARRY_NODE} reason=candidate_invalid_json dist_url=${DIST_URL}"
    return 0
  fi
  rm -f "$tmp_payload" >/dev/null 2>&1 || true

  if cmp -s "$tmp" "$me" >/dev/null 2>&1; then
    rm -f "$tmp" >/dev/null 2>&1 || true
    return 0
  fi

  cp -a "$me" "$me.lkg" >/dev/null 2>&1 || true

  if mv -f "$tmp" "$me" >/dev/null 2>&1; then
    chmod 755 "$me" >/dev/null 2>&1 || true
    export HARRY_SKIP_SELF_UPDATE=1
    exec "$me" "$@"
  fi

  rm -f "$tmp" >/dev/null 2>&1 || true
  log_fail "self_update_failed node=${HARRY_NODE} reason=replace_failed path=${me}"
  return 0
}

self_update "$@"

# -----------------------------------------------------------------------------
# Back off under load / memory pressure
# -----------------------------------------------------------------------------
BACKOFF_ENABLE="${HARRY_BACKOFF_ENABLE:-1}"
MAX_LOAD_PER_CORE="${HARRY_MAX_LOAD_PER_CORE:-1.5}"
MAX_MEM_USED_PCT="${HARRY_MAX_MEM_USED_PCT:-92}"

if [ "$BACKOFF_ENABLE" = "1" ]; then
  CORES="$(getconf _NPROCESSORS_ONLN 2>/dev/null || nproc 2>/dev/null || echo 1)"
  CORES="${CORES:-1}"

  LOAD1=""
  if [ -r /proc/loadavg ]; then
    LOAD1="$(awk '{print $1}' /proc/loadavg 2>/dev/null || true)"
  fi

  MEM_USED=""
  if [ -r /proc/meminfo ]; then
    MEM_USED="$(
      awk '
        /^MemTotal:/ {t=$2}
        /^MemAvailable:/ {a=$2}
        END { if (t>0) printf "%.2f", (100.0*(t-a)/t); }' /proc/meminfo 2>/dev/null || true
    )"
  fi

  if [ -n "$LOAD1" ]; then
    TOO_BUSY="$(
      LOAD1="$LOAD1" CORES="$CORES" MAX_LOAD_PER_CORE="$MAX_LOAD_PER_CORE" \
      "$PYTHON" - <<'PY'
import os
try:
    load1 = float(os.environ.get("LOAD1", "0") or 0)
    cores = float(os.environ.get("CORES", "1") or 1)
    thr   = float(os.environ.get("MAX_LOAD_PER_CORE", "1.5") or 1.5)
    print("1" if load1 > cores * thr else "0")
except Exception:
    print("0")
PY
    )"
    if [ "$TOO_BUSY" = "1" ]; then
      exit 0
    fi
  fi

  if [ -n "$MEM_USED" ]; then
    TOO_FULL="$(
      MEM_USED="$MEM_USED" MAX_MEM_USED_PCT="$MAX_MEM_USED_PCT" \
      "$PYTHON" - <<'PY'
import os
try:
    m   = float(os.environ.get("MEM_USED", "0") or 0)
    thr = float(os.environ.get("MAX_MEM_USED_PCT", "92") or 92)
    print("1" if m > thr else "0")
except Exception:
    print("0")
PY
    )"
    if [ "$TOO_FULL" = "1" ]; then
      exit 0
    fi
  fi
fi

# -----------------------------------------------------------------------------
# Build payload in Python
# -----------------------------------------------------------------------------
status_mark_start

TMP_PAYLOAD="$(mktemp /tmp/harry_agent_payload.XXXXXX.json)"
TMP_ERR="$(mktemp /tmp/harry_agent_err.XXXXXX.log)"

export HARRY_AGENT_VERSION="$AGENT_VERSION"
export HARRY_SCHEMA_VERSION="$SCHEMA_VERSION"
export HARRY_BRAIN_VERSION="$BRAIN_VERSION"
export HARRY_STATUS_FILE="$STATUS_FILE"

set +e
"$PYTHON" - <<'PY' >"$TMP_PAYLOAD" 2>"$TMP_ERR"
import json, os, re, subprocess, shutil, socket, math
from datetime import datetime, timezone

AGENT_VERSION = os.environ.get("HARRY_AGENT_VERSION") or "unknown"
SCHEMA_VERSION = os.environ.get("HARRY_SCHEMA_VERSION") or "unknown"
BRAIN_VERSION = os.environ.get("HARRY_BRAIN_VERSION") or "unknown"
STATUS_FILE = os.environ.get("HARRY_STATUS_FILE") or "/var/lib/harry-agent/status.json"

def which(x): return shutil.which(x)

def run(cmd):
    try:
        out = subprocess.check_output(cmd, stderr=subprocess.DEVNULL, text=True)
        return out.strip()
    except Exception:
        return ""

def read(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    except Exception:
        return ""

def to_int(x):
    try:
        if x is None: return None
        s = str(x).strip()
        if not s: return None
        return int(float(s))
    except Exception:
        return None

def to_float(x):
    try:
        if x is None: return None
        s = str(x).strip()
        if not s: return None
        return float(s)
    except Exception:
        return None

def parse_capacity_to_gb(s: str):
    s = (s or "").strip()
    m = re.search(r"(\d+(?:\.\d+)?)\s*(KB|MB|GB|TB)", s, flags=re.I)
    if not m:
        return None
    n = float(m.group(1))
    u = m.group(2).upper()
    if u == "KB": return n / 1024 / 1024
    if u == "MB": return n / 1024
    if u == "GB": return n
    if u == "TB": return n * 1024
    return None

def read_agent_status():
    try:
        with open(STATUS_FILE, "r", encoding="utf-8") as fh:
            data = json.load(fh)
            if isinstance(data, dict):
                return data
    except Exception:
        pass
    return {
        "state": "bootstrapping",
        "stage": "starting",
        "ok": True,
        "error_code": None,
        "error_summary": None,
        "consecutive_failures": 0,
    }

hostname = run(["hostname"]) or socket.gethostname() or "unknown"
node = (os.environ.get("HARRY_NODE") or "").strip() or hostname
ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

model = None
bios_version = None
bios_release_date = None
ram_slots_total = None
ram_slots_used = None
ram_type = None
ram_max_gb = None

if which("dmidecode"):
    model = run(["dmidecode","-s","system-product-name"]) or None
    bios_version = run(["dmidecode","-s","bios-version"]) or None
    bios_date_raw = (run(["dmidecode","-s","bios-release-date"]) or "").strip()
    if bios_date_raw:
        m = re.match(r"^(\d{1,2})/(\d{1,2})/(\d{4})$", bios_date_raw)
        if m:
            mm, dd, yy = m.groups()
            bios_release_date = f"{yy}-{int(mm):02d}-{int(dd):02d}"
        else:
            bios_release_date = bios_date_raw

    memtxt = run(["dmidecode","-t","memory"]) or ""
    if memtxt:
        for line in memtxt.splitlines():
            if "Maximum Capacity:" in line:
                cap = line.split(":",1)[1].strip()
                gb = parse_capacity_to_gb(cap)
                if gb:
                    ram_max_gb = int(round(gb))
                    break

        total = len(re.findall(r"^Memory Device$", memtxt, flags=re.MULTILINE))
        used = 0
        types = []
        for msz in re.findall(r"^\s*Size:\s*(.+)$", memtxt, flags=re.MULTILINE):
            s = (msz or "").strip().lower()
            if not s: continue
            if "no module installed" in s: continue
            if s.startswith("0"): continue
            used += 1
        for t in re.findall(r"^\s*Type:\s*(.+)$", memtxt, flags=re.MULTILINE):
            tt = (t or "").strip()
            if tt and tt.lower() not in ("unknown", "other"):
                types.append(tt)
        if total > 0:
            ram_slots_total = total
            ram_slots_used = used
        if types:
            ram_type = types[0]

cpu = None
cpu_cores = None
if which("lscpu"):
    txt = run(["lscpu"])
    for line in txt.splitlines():
        if ":" not in line: continue
        k,v = line.split(":",1)
        k = k.strip().lower()
        v = v.strip()
        if k == "model name" and v:
            cpu = v
        if k == "cpu(s)" and v:
            cpu_cores = to_int(v)

meminfo = read("/proc/meminfo")
ram_total_gb = None
mem_used_pct = None
try:
    d = {}
    for line in meminfo.splitlines():
        m = re.match(r"^(\w+):\s+(\d+)", line)
        if m:
            d[m.group(1)] = int(m.group(2))
    total_kb = d.get("MemTotal", 0)
    avail_kb = d.get("MemAvailable", 0)
    if total_kb > 0:
        ram_total_gb = int(math.ceil(total_kb / 1024 / 1024))
        used = total_kb - avail_kb
        mem_used_pct = (used/total_kb) * 100.0
except Exception:
    pass

load1 = None
try:
    load1 = to_float((read("/proc/loadavg").split() or [""])[0])
except Exception:
    pass

facts_disks = []
lsblk_json = ""
if which("lsblk"):
    lsblk_json = run(["lsblk","-J","-b","-o","NAME,TYPE,SIZE,MODEL,SERIAL,ROTA,TRAN"])
try:
    jb = json.loads(lsblk_json) if lsblk_json else {}
    for dev in (jb.get("blockdevices") or []):
        if not isinstance(dev, dict): continue
        if dev.get("type") != "disk": continue
        name = dev.get("name") or ""
        size_b = float(dev.get("size") or 0)
        size_gb = round(size_b/1024/1024/1024, 1) if size_b else None

        rota = dev.get("rota")
        tran = (dev.get("tran") or "").lower()
        dtype = "unknown"
        if name.startswith("nvme"):
            dtype = "nvme"
        elif tran == "usb":
            dtype = "usb"
        else:
            try:
                if int(rota) == 1:
                    dtype = "hdd"
                elif int(rota) == 0:
                    dtype = "ssd"
            except Exception:
                pass

        facts_disks.append({
            "name": name,
            "type": dtype,
            "size_gb": size_gb,
            "model": (dev.get("model") or "").replace("\n"," ").strip() or None,
            "serial": (dev.get("serial") or "").replace("\n"," ").strip() or None,
        })
except Exception:
    pass

disk_used = []
if which("df"):
    df_txt = run(["df", "-B1", "-P"])
    lines = [l for l in df_txt.splitlines() if l.strip()]
    for l in lines[1:]:
        parts = l.split()
        if len(parts) < 6:
            continue

        fs = parts[0]
        total_b = to_float(parts[1])
        used_b = to_float(parts[2])
        mount = parts[5]

        fs_l = (fs or "").lower()
        mount_l = (mount or "").lower()

        if fs_l in ("udev", "tmpfs", "devtmpfs", "overlay", "squashfs", "efivarfs"):
            continue
        if mount_l.startswith(("/proc", "/sys", "/run", "/dev")):
            continue
        if "/var/lib/docker/" in mount_l:
            continue

        used_pct = None
        size_gb = None

        if total_b and total_b > 0 and used_b is not None:
            used_pct = (used_b / total_b) * 100.0
            size_gb = total_b / 1024 / 1024 / 1024

        disk_used.append({
            "fs": fs,
            "mount": mount,
            "used_pct": used_pct,
            "size_gb": round(size_gb, 2) if size_gb is not None else None,
        })

disk_physical = []
if which("lsblk"):
    j = run(["lsblk","-J","-b","-o","NAME,TYPE,SIZE,MODEL,SERIAL,ROTA,TRAN,MOUNTPOINTS,FSUSE%,FSTYPE"])
    try:
        jb = json.loads(j) if j else {}
        for dev in (jb.get("blockdevices") or []):
            if not isinstance(dev, dict): continue
            if dev.get("type") != "disk": continue

            name = dev.get("name") or ""
            size_b = float(dev.get("size") or 0)
            size_s = f"{size_b/1024/1024/1024:.0f}GB" if size_b else "—"
            model_s = (dev.get("model") or "").replace("\n"," ").strip() or ""
            serial_s = (dev.get("serial") or "").replace("\n"," ").strip() or ""

            rota = dev.get("rota")
            tran = (dev.get("tran") or "").lower()
            dtype = "unknown"
            if name.startswith("nvme"):
                dtype = "nvme"
            elif tran == "usb":
                dtype = "usb"
            else:
                try:
                    dtype = "hdd" if int(rota) == 1 else "ssd"
                except Exception:
                    pass

            mounts = []
            worst = None
            kids = dev.get("children") or []
            stack = kids[:] if isinstance(kids, list) else []
            while stack:
                c = stack.pop(0)
                if not isinstance(c, dict): continue
                cc = c.get("children")
                if isinstance(cc, list):
                    stack.extend(cc)
                mps = c.get("mountpoints") or c.get("mountpoint")
                mlist = []
                if isinstance(mps, list):
                    mlist = [x for x in mps if x]
                elif isinstance(mps, str) and mps:
                    mlist = [mps]

                fsuse = c.get("fsuse%")
                if isinstance(fsuse, str):
                    fsuse = fsuse.strip().replace("%","")
                pct = to_float(fsuse)

                for mp in mlist:
                    mp_s = str(mp)
                    blob = mp_s.lower()
                    if any(x in blob for x in ("/var/lib/docker", "overlay", "tmpfs", "/proc", "/sys", "/run")):
                        continue
                    if pct is not None:
                        worst = pct if worst is None else max(worst, pct)
                    mounts.append({"mount": mp_s, "pct": pct})

            disk_physical.append({
                "disk": name,
                "type": dtype,
                "size": size_s,
                "model": model_s or None,
                "serial": serial_s or None,
                "pct": worst,
                "mounts": mounts[:12],
            })
    except Exception:
        pass

temps = {}
if which("sensors"):
    s = run(["sensors"])
    for line in s.splitlines():
        if ":" not in line: continue
        if "°C" not in line: continue
        k, v = line.split(":", 1)
        k = k.strip()
        m = re.search(r"([-+]?\d+(?:\.\d+)?)\s*°C", v)
        if m:
            temps[k] = float(m.group(1))

gpus = []
if which("nvidia-smi"):
    out = run([
        "nvidia-smi",
        "--query-gpu=name,driver_version,pci.bus_id,utilization.gpu,temperature.gpu,memory.total,memory.used",
        "--format=csv,noheader,nounits",
    ])
    for line in [l.strip() for l in out.splitlines() if l.strip()]:
        parts = [p.strip() for p in line.split(",")]
        if len(parts) < 7: continue
        name, driver, bus, util, temp, mem_t, mem_u = parts[:7]
        gpus.append({
            "name": name,
            "driver": driver,
            "bus_id": bus,
            "util_pct": to_float(util),
            "temp_c": to_float(temp),
            "mem_total_mb": to_int(mem_t),
            "mem_used_mb": to_int(mem_u),
        })

agent_status = read_agent_status()
agent_status.setdefault("ok", True)
agent_status.setdefault("error_code", None)
agent_status.setdefault("error_summary", None)
agent_status.setdefault("consecutive_failures", 0)

payload = {
  "schema_version": SCHEMA_VERSION,
  "agent_version": AGENT_VERSION,
  "node": node,
  "ts": ts,
  "agent_status": agent_status,
  "facts": {
    "hostname": hostname,
    "model": model,
    "cpu": cpu,
    "cpu_cores": cpu_cores,
    "ram_total_gb": ram_total_gb,
    "ram_max_gb": ram_max_gb,
    "ram_slots_total": ram_slots_total,
    "ram_slots_used": ram_slots_used,
    "ram_type": ram_type,
    "bios_release_date": bios_release_date,
    "bios_version": bios_version,
    "disks": facts_disks,
    "gpus": [],
    "extensions": {}
  },
  "metrics": {
    "cpu_load_1m": load1,
    "mem_used_pct": mem_used_pct,
    "disk_used": disk_used,
    "temps_c": temps,
    "gpu": gpus,
    "extensions": {
      "disk_physical": disk_physical
    }
  },
  "derived": {
    "health": {"state":"unknown","worst_severity":"unknown","reasons":[]},
    "extensions": {}
  },
  "advice": []
}

print(json.dumps(payload, separators=(",",":"), ensure_ascii=False))
PY
PY_EXIT=$?
set -e

if [ "$PY_EXIT" -ne 0 ]; then
  log_fail "payload_generation_failed node=${HARRY_NODE} python_exit=${PY_EXIT}"
  status_mark_failure "payload_generation_failed" "python_exit_${PY_EXIT}"
  echo "❌ Payload generation failed:" >&2
  sed -n '1,120p' "$TMP_ERR" >&2 || true
  rm -f "$TMP_PAYLOAD" "$TMP_ERR" >/dev/null 2>&1 || true
  exit 1
fi

if [ ! -s "$TMP_PAYLOAD" ]; then
  log_fail "payload_generation_failed node=${HARRY_NODE} reason=empty_output"
  status_mark_failure "payload_generation_failed" "empty_output"
  rm -f "$TMP_PAYLOAD" "$TMP_ERR" >/dev/null 2>&1 || true
  exit 1
fi

if ! json_is_valid_file "$TMP_PAYLOAD"; then
  log_fail "payload_generation_failed node=${HARRY_NODE} reason=invalid_json_output"
  status_mark_failure "payload_generation_failed" "invalid_json_output"
  rm -f "$TMP_PAYLOAD" "$TMP_ERR" >/dev/null 2>&1 || true
  exit 1
fi

if [ "$PRINT_ONLY" = "1" ]; then
  cat "$TMP_PAYLOAD"
  rm -f "$TMP_PAYLOAD" "$TMP_ERR" >/dev/null 2>&1 || true
  exit 0
fi

# -----------------------------------------------------------------------------
# Send to Brain
# -----------------------------------------------------------------------------
status_mark_sending

TMP_RESP="$(mktemp /tmp/harry_agent_resp.XXXXXX.json)"

set +e
HTTP_CODE="$(
  "$CURL" -sS -o "$TMP_RESP" -w "%{http_code}" \
    -X POST "${HARRY_INGEST_URL}" \
    -H "Content-Type: application/json" \
    --data-binary @"$TMP_PAYLOAD"
)"
CURL_EXIT=$?
set -e

if [ "$CURL_EXIT" -ne 0 ]; then
  resp="$(cat "$TMP_RESP" 2>/dev/null || true)"
  log_fail "ingest_failed node=${HARRY_NODE} reason=curl_exit_${CURL_EXIT} url=${HARRY_INGEST_URL} resp=${resp}"
  status_mark_failure "ingest_failed" "curl_exit_${CURL_EXIT}"
  rm -f "$TMP_PAYLOAD" "$TMP_ERR" "$TMP_RESP" >/dev/null 2>&1 || true
  exit 0
fi

if [ "$HTTP_CODE" != "200" ]; then
  resp="$(cat "$TMP_RESP" 2>/dev/null || true)"
  log_fail "ingest_failed node=${HARRY_NODE} reason=http_${HTTP_CODE} url=${HARRY_INGEST_URL} resp=${resp}"
  status_mark_failure "ingest_failed" "http_${HTTP_CODE}"
  rm -f "$TMP_PAYLOAD" "$TMP_ERR" "$TMP_RESP" >/dev/null 2>&1 || true
  exit 0
fi

status_mark_success
rm -f "$TMP_PAYLOAD" "$TMP_ERR" "$TMP_RESP" >/dev/null 2>&1 || true
exit 0
