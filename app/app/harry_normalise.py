import json
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple


def _num(x: Any) -> Optional[float]:
    try:
        if x is None:
            return None
        if isinstance(x, str):
            s = x.strip()
            if s.endswith("%"):
                s = s[:-1].strip()
            if s == "":
                return None
            return float(s)
        return float(x)
    except Exception:
        return None


def _clamp(v: Optional[float], lo: float = 0.0, hi: float = 100.0) -> Optional[float]:
    if v is None:
        return None
    return max(lo, min(hi, v))


def _pick_first(*vals):
    for v in vals:
        if v is not None:
            return v
    return None


def _safe_get(d: Dict[str, Any], *path, default=None):
    cur = d
    for p in path:
        if not isinstance(cur, dict) or p not in cur:
            return default
        cur = cur[p]
    return cur


def _ver_tuple(v: str) -> Tuple[int, int, int]:
    try:
        parts = (v or "").strip().split(".")
        parts = (parts + ["0", "0", "0"])[:3]
        return (int(parts[0]), int(parts[1]), int(parts[2]))
    except Exception:
        return (0, 0, 0)


def _iso_utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def normalise_harry_snapshot(payload: Dict[str, Any]) -> Dict[str, Any]:
    node = payload.get("node")
    ts = payload.get("ts")

    facts = payload.get("facts") or {}
    metrics = payload.get("metrics") or {}

    ram_used_pct = _pick_first(
        _num(_safe_get(metrics, "ram", "used_pct")),
        _num(_safe_get(metrics, "ram", "pct")),
        _num(_safe_get(metrics, "memory", "used_pct")),
        _num(_safe_get(metrics, "memory", "pct")),
        _num(_safe_get(metrics, "mem_used_pct")),
    )
    ram_used_pct = _clamp(ram_used_pct)

    disk_used_list = _safe_get(metrics, "disk_used", default=None)
    storage_used_pct = None
    mounts_norm: List[Dict[str, Any]] = []

    if isinstance(disk_used_list, list) and disk_used_list:
        for m in disk_used_list:
            if not isinstance(m, dict):
                continue
            mount = m.get("mount") or m.get("mnt") or m.get("path")
            fs = m.get("fs") or m.get("filesystem") or m.get("name")
            used_pct = _pick_first(_num(m.get("used_pct")), _num(m.get("pct")), _num(m.get("use%")))
            used_pct = _clamp(used_pct)
            size_gb = _pick_first(_num(m.get("size_gb")), _num(m.get("size")), _num(m.get("total_gb")))
            mounts_norm.append({"mount": mount, "fs": fs, "used_pct": used_pct, "size_gb": size_gb})

        root = next((x for x in mounts_norm if x.get("mount") in ("/", "/root")), None)
        if root and root.get("used_pct") is not None:
            storage_used_pct = root["used_pct"]
        else:
            pcts = [x["used_pct"] for x in mounts_norm if x.get("used_pct") is not None]
            storage_used_pct = max(pcts) if pcts else None

    storage_used_pct = _pick_first(
        storage_used_pct,
        _num(_safe_get(metrics, "storage", "used_pct")),
        _num(_safe_get(metrics, "disk", "used_pct")),
    )
    storage_used_pct = _clamp(storage_used_pct)

    gpus_in = _safe_get(metrics, "gpus", default=None)
    if not isinstance(gpus_in, list):
        gpus_in = _safe_get(metrics, "gpu", default=None)

    gpu_max_used_pct = None
    gpu_max_temp_c = None
    gpus_norm: List[Dict[str, Any]] = []

    if isinstance(gpus_in, list) and gpus_in:
        for g in gpus_in:
            if not isinstance(g, dict):
                continue
            name = g.get("name") or g.get("model") or g.get("gpu")
            temp_c = _pick_first(_num(g.get("temp_c")), _num(g.get("temp")), _num(g.get("temperature_c")))
            util_pct = _pick_first(_num(g.get("util_pct")), _num(g.get("util")), _num(g.get("gpu_util_pct")))
            mem_used_pct = _pick_first(
                _num(g.get("mem_used_pct")),
                _num(g.get("memory_used_pct")),
                _num(g.get("vram_used_pct")),
                _num(g.get("pct")),
            )
            mem_used_pct = _clamp(mem_used_pct)
            util_pct = _clamp(util_pct)

            if mem_used_pct is None:
                mt = _num(g.get("mem_total_mb"))
                mu = _num(g.get("mem_used_mb"))
                if mt and mt > 0 and mu is not None:
                    mem_used_pct = _clamp((mu / mt) * 100.0)

            gpus_norm.append({"name": name, "temp_c": temp_c, "util_pct": util_pct, "mem_used_pct": mem_used_pct})

        useds = [x["mem_used_pct"] for x in gpus_norm if x.get("mem_used_pct") is not None]
        temps = [x["temp_c"] for x in gpus_norm if x.get("temp_c") is not None]
        gpu_max_used_pct = max(useds) if useds else None
        gpu_max_temp_c = max(temps) if temps else None

    temps_c = _safe_get(metrics, "temps_c", default=None)

    return {
        "node": node,
        "ts": ts,
        "agent_status": payload.get("agent_status") if isinstance(payload.get("agent_status"), dict) else {},
        "facts": {
            "model": facts.get("model"),
            "cpu": facts.get("cpu"),
            "bios_version": facts.get("bios_version") or _safe_get(facts, "extensions", "bios_version"),
        },
        "metrics": {
            "ram": {"used_pct": ram_used_pct},
            "storage": {"used_pct": storage_used_pct},
            "gpu": {"max_used_pct": gpu_max_used_pct, "max_temp_c": gpu_max_temp_c},
            "temps_c": temps_c,
            "extensions": {
                "mounts": mounts_norm,
                "gpus": gpus_norm,
                "raw_metrics_keys": sorted(list(metrics.keys())) if isinstance(metrics, dict) else [],
            },
        },
        "extensions": {"raw": payload},
    }


def normalise_for_schema(payload: Dict[str, Any], contract_version: str = "unknown") -> Dict[str, Any]:
    if not contract_version or str(contract_version).strip().lower() == "unknown":
        contract_version = "0.2.3"

    def _safe_dict(x: Any) -> Dict[str, Any]:
        return x if isinstance(x, dict) else {}

    def _safe_list(x: Any) -> List[Any]:
        return x if isinstance(x, list) else []

    v = _ver_tuple(contract_version)
    is_022_plus = v >= (0, 2, 2)
    is_021 = v <= (0, 2, 1)

    node = (payload.get("node") or _safe_dict(payload.get("facts")).get("hostname") or "unknown")
    ts = payload.get("ts") or _iso_utc_now()
    agent_version = str(payload.get("agent_version") or "unknown")
    agent_status = payload.get("agent_status") if isinstance(payload.get("agent_status"), dict) else {}

    facts_in = _safe_dict(payload.get("facts"))
    metrics_in = _safe_dict(payload.get("metrics"))

    facts_ext = _safe_dict(facts_in.get("extensions"))
    if facts_in.get("bios_version") is not None and facts_ext.get("bios_version") is None:
        facts_ext["bios_version"] = facts_in.get("bios_version")

    disks_in = _safe_list(facts_in.get("disks"))
    disks_out: List[Dict[str, Any]] = []
    disks_rich: List[Dict[str, Any]] = []
    for d in disks_in:
        if not isinstance(d, dict):
            continue
        disks_out.append({"name": d.get("name"), "type": d.get("type"), "size_gb": d.get("size_gb")})
        rich = {}
        for k in ("model", "serial", "smart_power_on_hours"):
            if d.get(k) is not None:
                rich[k] = d.get(k)
        if rich:
            rich["name"] = d.get("name")
            disks_rich.append(rich)
    if disks_rich:
        facts_ext["disks_rich"] = disks_rich

    facts_out = {
        "hostname": facts_in.get("hostname"),
        "model": facts_in.get("model"),
        "cpu": facts_in.get("cpu"),
        "cpu_cores": facts_in.get("cpu_cores"),
        "ram_total_gb": facts_in.get("ram_total_gb"),
        "ram_max_gb": facts_in.get("ram_max_gb"),
        "ram_slots_total": facts_in.get("ram_slots_total"),
        "ram_slots_used": facts_in.get("ram_slots_used"),
        "ram_type": facts_in.get("ram_type"),
        "bios_release_date": facts_in.get("bios_release_date"),
        "disks": disks_out,
        "gpus": facts_in.get("gpus") if isinstance(facts_in.get("gpus"), list) else [],
        "extensions": facts_ext,
    }

    metrics_ext = _safe_dict(metrics_in.get("extensions"))

    disk_used_in = _safe_list(metrics_in.get("disk_used"))
    disk_used_out: List[Dict[str, Any]] = []
    mounts_raw: List[Dict[str, Any]] = []

    for m in disk_used_in:
        if not isinstance(m, dict):
            continue
        mount = m.get("mount") or m.get("mnt") or m.get("path")
        fs = m.get("fs") or m.get("filesystem") or m.get("name")
        used_pct = m.get("used_pct")
        if used_pct is None:
            used_pct = m.get("pct") or m.get("use%")
        used_pct_f = _num(used_pct)

        raw = dict(m)
        raw["mount"] = mount
        raw["fs"] = fs
        raw["used_pct"] = used_pct_f
        mounts_raw.append(raw)

        if used_pct_f is None:
            continue

        item = {"mount": mount, "used_pct": used_pct_f}
        if is_022_plus and fs:
            item["fs"] = fs
        disk_used_out.append(item)

    if mounts_raw:
        metrics_ext["mounts_raw"] = mounts_raw

    temps_out: Dict[str, Any] = {}
    temps_in = metrics_in.get("temps_c")

    if is_021:
        if isinstance(temps_in, dict) and temps_in:
            metrics_ext["temps_c_raw"] = temps_in
        temps_out = {}
    else:
        if isinstance(temps_in, dict):
            cleaned: Dict[str, float] = {}
            for k, val in temps_in.items():
                n = _num(val)
                if n is None:
                    continue
                cleaned[str(k)] = float(n)
            temps_out = cleaned
            if temps_in and temps_out != temps_in:
                metrics_ext["temps_c_raw"] = temps_in

    gpu_in = metrics_in.get("gpu")
    if not isinstance(gpu_in, list):
        gpu_in = []

    gpu_out: List[Dict[str, Any]] = []
    gpu_raw: List[Dict[str, Any]] = []

    for g in gpu_in:
        if not isinstance(g, dict):
            continue
        gpu_raw.append(dict(g))

        name = g.get("name") or g.get("model") or "GPU"
        util_pct = _clamp(_num(g.get("util_pct")))
        temp_c = _num(g.get("temp_c"))

        if is_021:
            item: Dict[str, Any] = {"name": name}
            if util_pct is not None:
                item["util_pct"] = util_pct
            if temp_c is not None:
                item["temp_c"] = temp_c
            gpu_out.append(item)
        else:
            mem_total_mb = _num(g.get("mem_total_mb"))
            mem_used_mb = _num(g.get("mem_used_mb"))
            mem_used_pct = _clamp(_num(g.get("mem_used_pct")))

            if mem_used_pct is None and mem_total_mb and mem_total_mb > 0 and mem_used_mb is not None:
                mem_used_pct = _clamp((mem_used_mb / mem_total_mb) * 100.0)

            item = {"name": name}
            if util_pct is not None:
                item["util_pct"] = util_pct
            if temp_c is not None:
                item["temp_c"] = temp_c
            if mem_total_mb is not None:
                item["mem_total_mb"] = mem_total_mb
            if mem_used_mb is not None:
                item["mem_used_mb"] = mem_used_mb
            if mem_used_pct is not None:
                item["mem_used_pct"] = mem_used_pct
            if g.get("driver") is not None:
                item["driver"] = str(g.get("driver"))
            if g.get("bus_id") is not None:
                item["bus_id"] = str(g.get("bus_id"))

            gpu_out.append(item)

    if gpu_raw:
        metrics_ext["gpu_raw"] = gpu_raw

    metrics_out = {
        "cpu_load_1m": metrics_in.get("cpu_load_1m"),
        "mem_used_pct": metrics_in.get("mem_used_pct"),
        "disk_used": disk_used_out,
        "temps_c": temps_out,
        "gpu": gpu_out,
        "extensions": metrics_ext,
    }

    derived_in = payload.get("derived")
    if not isinstance(derived_in, dict):
        derived_in = {"health": {"state": "unknown", "worst_severity": "unknown", "reasons": []}, "extensions": {}}

    advice_in = payload.get("advice")
    if not isinstance(advice_in, list):
        advice_in = []

    return {
        "schema_version": str(contract_version),
        "agent_version": agent_version,
        "agent_status": agent_status,
        "node": node,
        "ts": ts,
        "facts": facts_out,
        "metrics": metrics_out,
        "derived": derived_in,
        "advice": advice_in,
    }


def loads_payload(payload_text: str) -> Dict[str, Any]:
    try:
        return json.loads(payload_text)
    except Exception:
        return {}
