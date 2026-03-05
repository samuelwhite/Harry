# /opt/harry/brain/app/app/advice_engine.py
from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple
from datetime import datetime, timedelta, timezone
import os
import sqlite3
import json
import re


# -----------------------------
# Helpers
# -----------------------------

def _utcnow() -> datetime:
    return datetime.now(timezone.utc)

def _parse_ts(s: str) -> Optional[datetime]:
    if not s:
        return None
    try:
        if s.endswith("Z"):
            s = s[:-1] + "+00:00"
        return datetime.fromisoformat(s).astimezone(timezone.utc)
    except Exception:
        return None

def _fnum(v: Any) -> Optional[float]:
    try:
        if v is None:
            return None
        if isinstance(v, str):
            s = v.strip()
            if s.endswith("%"):
                s = s[:-1].strip()
            return float(s)
        return float(v)
    except Exception:
        return None

def _clamp(v: Optional[float], lo: float = 0.0, hi: float = 100.0) -> Optional[float]:
    if v is None:
        return None
    return max(lo, min(hi, float(v)))

def _median(xs: List[float]) -> Optional[float]:
    xs2 = sorted([float(x) for x in xs if x is not None])
    if not xs2:
        return None
    n = len(xs2)
    mid = n // 2
    if n % 2 == 1:
        return xs2[mid]
    return (xs2[mid - 1] + xs2[mid]) / 2.0

def _severity_rank(sev: str) -> int:
    return {"info": 0, "warn": 1, "crit": 2}.get((sev or "info").lower(), 0)

def _state_from_worst(worst: str) -> str:
    return {"crit": "red", "warn": "amber", "info": "green"}.get((worst or "info").lower(), "unknown")

def _safe_id(s: str) -> str:
    s = (s or "").strip()
    s = re.sub(r"[^a-zA-Z0-9_]+", "_", s)
    s = re.sub(r"_+", "_", s).strip("_")
    return s[:80] or "unknown"

def _linear_slope_pct_per_day(points: List[Tuple[datetime, float]]) -> Optional[float]:
    """
    Least-squares slope on (t_days, pct). Returns pct/day.
    """
    if len(points) < 3:
        return None
    t0 = points[0][0]
    xs: List[float] = []
    ys: List[float] = []
    for t, y in points:
        dt = (t - t0).total_seconds() / 86400.0
        xs.append(dt)
        ys.append(float(y))
    n = len(xs)
    xbar = sum(xs) / n
    ybar = sum(ys) / n
    num = sum((xs[i] - xbar) * (ys[i] - ybar) for i in range(n))
    den = sum((xs[i] - xbar) ** 2 for i in range(n))
    if den <= 1e-12:
        return None
    return num / den

def _forecast_days_to_full(current_pct: float, slope_pct_per_day: float) -> Optional[float]:
    if slope_pct_per_day <= 0.0:
        return None
    remaining = 100.0 - float(current_pct)
    if remaining <= 0:
        return 0.0
    return remaining / slope_pct_per_day

def _fmt_eta(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%a %d %b %Y")

def _add(
    advice: List[Dict[str, Any]],
    reasons: List[Dict[str, Any]],
    *,
    id: str,
    node: str,
    category: str,
    severity: str,
    message: str,
    recommendation: str,
    confidence: float = 0.7,
    refs: Optional[List[str]] = None,
    evidence: Optional[Dict[str, Any]] = None,
    field: str = "",
    value: Any = None,
) -> None:
    advice.append({
        "id": id,
        "node": node,
        "category": category,
        "severity": severity,
        "message": message,
        "recommendation": recommendation,
        "confidence": float(confidence),
        "refs": refs or [],
        "evidence": evidence or {},
    })
    reasons.append({
        "code": id,
        "severity": severity,
        "message": message,
        "field": field,
        "value": value,
        "evidence": evidence or {},
    })


# -----------------------------
# DB / history
# -----------------------------

DB_PATH = os.environ.get("HARRY_DB_PATH", "/data/harry.db")

def _db() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def _fetch_history_payloads(node: str, hours: int, limit: int = 1200) -> List[Tuple[datetime, Dict[str, Any]]]:
    since = (_utcnow() - timedelta(hours=hours)).strftime("%Y-%m-%dT%H:%M:%SZ")
    q = """
    SELECT ts, payload
    FROM ingest
    WHERE node = ? AND ts >= ?
    ORDER BY ts ASC
    LIMIT ?
    """
    out: List[Tuple[datetime, Dict[str, Any]]] = []
    try:
        with _db() as conn:
            for row in conn.execute(q, (node, since, int(limit))):
                ts = _parse_ts(str(row["ts"] or ""))
                if not ts:
                    continue
                try:
                    payload = json.loads(row["payload"])
                except Exception:
                    continue
                if isinstance(payload, dict):
                    out.append((ts, payload))
    except Exception:
        return []
    return out


# -----------------------------
# Disk extraction (per target)
# -----------------------------
# We try very hard to infer a size if available.
# Supported size hints we’ll attempt:
# - size_gb, total_gb
# - size_bytes, total_bytes
# - size like "931.5G" (string) on some tools (best-effort)

def _parse_size_gb(v: Any) -> Optional[float]:
    if v is None:
        return None
    if isinstance(v, (int, float)):
        # if it looks like bytes (very large), convert
        if v > 10_000_000_000:  # >10GB in bytes
            return float(v) / (1024.0**3)
        # otherwise assume already GB
        if v > 0:
            return float(v)
        return None
    if isinstance(v, str):
        s = v.strip().upper()
        # bytes as string
        if s.isdigit():
            n = float(s)
            if n > 10_000_000_000:
                return n / (1024.0**3)
            return n
        # 931.5G / 1.8T
        m = re.match(r"^\s*([0-9]*\.?[0-9]+)\s*([KMGTP])B?\s*$", s)
        if m:
            num = float(m.group(1))
            unit = m.group(2)
            mult = {"K": 1/1024/1024, "M": 1/1024, "G": 1.0, "T": 1024.0, "P": 1024.0*1024.0}.get(unit, 1.0)
            return num * mult
    return None

def _pct_from_obj(d: Dict[str, Any]) -> Optional[float]:
    for k in ("used_pct", "pct"):
        v = _fnum(d.get(k))
        if v is not None:
            return _clamp(v)
    return None

def _extract_disk_targets(metrics: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    """
    Returns dict of disk targets keyed by a stable id:
      key -> {kind, label, used_pct, size_gb?, mount?, disk?}
    Preference:
      1) metrics.extensions.disk_physical (per disk)
      2) metrics.disk_used (per mount)
    """
    out: Dict[str, Dict[str, Any]] = {}

    ex = metrics.get("extensions") if isinstance(metrics.get("extensions"), dict) else {}
    phys = ex.get("disk_physical")
    if isinstance(phys, list) and phys:
        for d in phys:
            if not isinstance(d, dict):
                continue
            used = _pct_from_obj(d)
            if used is None:
                continue
            name = str(d.get("name") or d.get("disk") or d.get("device") or "disk").strip()
            label = name
            size_gb = (
                _parse_size_gb(d.get("size_gb"))
                or _parse_size_gb(d.get("total_gb"))
                or _parse_size_gb(d.get("size"))
                or _parse_size_gb(d.get("size_bytes"))
                or _parse_size_gb(d.get("total_bytes"))
            )
            key = f"phys:{name}"
            out[key] = {
                "kind": "physical",
                "label": label,
                "used_pct": float(used),
                "size_gb": size_gb,
                "disk": name,
            }
        # If physical exists, we stop here (by design: more meaningful than mounts)
        if out:
            return out

    du = metrics.get("disk_used")
    if isinstance(du, list) and du:
        for m in du:
            if not isinstance(m, dict):
                continue
            used = _pct_from_obj(m)
            if used is None:
                continue
            mount = str(m.get("mount") or m.get("path") or "mount").strip()
            label = mount
            size_gb = (
                _parse_size_gb(m.get("size_gb"))
                or _parse_size_gb(m.get("total_gb"))
                or _parse_size_gb(m.get("size"))
                or _parse_size_gb(m.get("size_bytes"))
                or _parse_size_gb(m.get("total_bytes"))
            )
            key = f"mnt:{mount}"
            out[key] = {
                "kind": "mount",
                "label": label,
                "used_pct": float(used),
                "size_gb": size_gb,
                "mount": mount,
            }

    return out

def _pick_overall_disk_pct(metrics: Dict[str, Any]) -> Optional[float]:
    # “single number” fallback: max target used%
    targets = _extract_disk_targets(metrics)
    if not targets:
        return None
    return _clamp(max(t["used_pct"] for t in targets.values() if isinstance(t.get("used_pct"), (int, float))))


# -----------------------------
# CPU temp selection
# -----------------------------

def _cpu_temp_c(metrics: Dict[str, Any]) -> Optional[float]:
    temps = metrics.get("temps_c")
    if not isinstance(temps, dict) or not temps:
        return None

    preferred = []
    for k in temps.keys():
        ks = str(k).lower()
        if any(x in ks for x in ("package", "tdie", "tctl", "cpu")):
            preferred.append(k)

    for k in preferred:
        v = _fnum(temps.get(k))
        if v is not None:
            return float(v)

    core_vals = []
    for k, v in temps.items():
        if "core" in str(k).lower():
            n = _fnum(v)
            if n is not None:
                core_vals.append(float(n))
    if core_vals:
        return max(core_vals)

    any_vals = []
    for v in temps.values():
        n = _fnum(v)
        if n is not None:
            any_vals.append(float(n))
    return max(any_vals) if any_vals else None


# -----------------------------
# Main engine
# -----------------------------

def build_advice_and_health(payload: Dict[str, Any]) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    """
    Returns:
      advice: list[dict]
      health: dict (state, worst_severity, reasons)

    Uses:
      - snapshot rules
      - history-derived sustained rules
      - per-disk forecasting + headroom when sizes can be inferred
    """
    node = payload.get("node", "unknown")
    facts = payload.get("facts", {}) if isinstance(payload.get("facts"), dict) else {}
    metrics = payload.get("metrics", {}) if isinstance(payload.get("metrics"), dict) else {}

    advice: List[Dict[str, Any]] = []
    reasons: List[Dict[str, Any]] = []

    # Tunables
    H_SUSTAIN_HOURS = int(os.environ.get("HARRY_ADVICE_SUSTAIN_HOURS", "6"))
    H_FORECAST_HOURS = int(os.environ.get("HARRY_ADVICE_FORECAST_HOURS", "72"))  # longer is better for rate stability
    FORECAST_MIN_POINTS = int(os.environ.get("HARRY_ADVICE_FORECAST_MIN_POINTS", "6"))
    FORECAST_MIN_SLOPE_PCT_PER_DAY = float(os.environ.get("HARRY_ADVICE_FORECAST_MIN_SLOPE", "0.05"))
    FORECAST_MAX_ITEMS = int(os.environ.get("HARRY_ADVICE_FORECAST_MAX_ITEMS", "2"))

    # -----------------------------
    # Snapshot: STORAGE (single number + headroom if possible)
    # -----------------------------
    disk_now = _pick_overall_disk_pct(metrics)
    if disk_now is not None:
        if disk_now >= 92:
            sev = "crit"
            msg = f"Storage is critically high ({disk_now:.0f}%)."
            rec = "Free space (logs/backups/media) or expand storage."
            conf = 0.85
            code = "disk_crit_now"
        elif disk_now >= 85:
            sev = "warn"
            msg = f"Storage is getting tight ({disk_now:.0f}%)."
            rec = "Plan a cleanup or storage upgrade soon."
            conf = 0.80
            code = "disk_warn_now"
        elif disk_now >= 70:
            sev = "warn"
            msg = f"Storage is climbing ({disk_now:.0f}%)."
            rec = "Worth checking what’s growing before it becomes a problem."
            conf = 0.70
            code = "disk_rising"
        else:
            sev = ""
            msg = ""
            rec = ""
            conf = 0.0
            code = ""

        if sev:
            _add(
                advice, reasons,
                id=code,
                node=node,
                category="storage",
                severity=sev,
                message=msg,
                recommendation=rec,
                confidence=conf,
                field="metrics.disk_used or metrics.extensions.disk_physical",
                value=disk_now,
                evidence={"used_pct": disk_now},
            )

    # -----------------------------
    # Snapshot: MEMORY
    # -----------------------------
    mem = _clamp(_fnum(metrics.get("mem_used_pct")))
    if mem is not None:
        if mem >= 90:
            _add(
                advice, reasons,
                id="mem_crit_now",
                node=node,
                category="memory",
                severity="crit",
                message=f"Memory usage is very high ({mem:.0f}%).",
                recommendation="Investigate memory-heavy processes; add RAM if persistent.",
                confidence=0.80,
                field="metrics.mem_used_pct",
                value=mem,
                evidence={"mem_used_pct": mem},
            )
        elif mem >= 80:
            _add(
                advice, reasons,
                id="mem_warn_now",
                node=node,
                category="memory",
                severity="warn",
                message=f"Memory usage is high ({mem:.0f}%).",
                recommendation="Keep an eye on it; tune services or plan a RAM upgrade if this is typical.",
                confidence=0.75,
                field="metrics.mem_used_pct",
                value=mem,
                evidence={"mem_used_pct": mem},
            )

    # -----------------------------
    # Snapshot: CPU LOAD (instant)
    # -----------------------------
    load = _fnum(metrics.get("cpu_load_1m"))
    cores = facts.get("cpu_cores")
    if isinstance(load, (int, float)) and isinstance(cores, int) and cores > 0:
        if float(load) > float(cores) * 1.25:
            _add(
                advice, reasons,
                id="cpu_load_warn_now",
                node=node,
                category="cpu",
                severity="warn",
                message=f"CPU load (1m) is {float(load):.2f} on {cores} cores.",
                recommendation="Check for runaway processes or schedule heavy jobs during quieter periods.",
                confidence=0.65,
                field="metrics.cpu_load_1m",
                value=float(load),
                evidence={"cpu_load_1m": float(load), "cpu_cores": cores},
            )

    # -----------------------------
    # Snapshot: TEMPERATURE
    # -----------------------------
    cpu_t = _cpu_temp_c(metrics)
    if cpu_t is not None:
        if cpu_t >= 88:
            _add(
                advice, reasons,
                id="temp_cpu_crit_now",
                node=node,
                category="temperature",
                severity="crit",
                message=f"CPU temperature is hot ({cpu_t:.0f}°C).",
                recommendation="Check cooling, dust, airflow, and thermal paste.",
                confidence=0.80,
                field="metrics.temps_c",
                value=cpu_t,
                evidence={"cpu_temp_c": cpu_t},
            )
        elif cpu_t >= 78:
            _add(
                advice, reasons,
                id="temp_cpu_warn_now",
                node=node,
                category="temperature",
                severity="warn",
                message=f"CPU temperature is warm ({cpu_t:.0f}°C).",
                recommendation="Monitor cooling; consider cleaning and improving airflow.",
                confidence=0.70,
                field="metrics.temps_c",
                value=cpu_t,
                evidence={"cpu_temp_c": cpu_t},
            )

    # -----------------------------
    # HISTORY: sustained RAM / CPU load baseline
    # -----------------------------
    hist_sustain = _fetch_history_payloads(str(node), hours=H_SUSTAIN_HOURS, limit=900)
    if hist_sustain:
        mem_series: List[float] = []
        load_series: List[float] = []

        for ts, p in hist_sustain:
            m = p.get("metrics") if isinstance(p.get("metrics"), dict) else {}
            mv = _clamp(_fnum(m.get("mem_used_pct")))
            if mv is not None:
                mem_series.append(float(mv))
            lv = _fnum(m.get("cpu_load_1m"))
            if isinstance(lv, (int, float)):
                load_series.append(float(lv))

        mem_med = _median(mem_series)
        if mem_med is not None:
            if mem_med >= 80:
                _add(
                    advice, reasons,
                    id="mem_sustained_high",
                    node=node,
                    category="memory",
                    severity="warn" if mem_med < 88 else "crit",
                    message=f"Memory is consistently high (median {mem_med:.0f}% over ~{H_SUSTAIN_HOURS}h).",
                    recommendation="If this is the normal baseline, consider adding RAM or slimming services.",
                    confidence=0.78,
                    field="history(metrics.mem_used_pct)",
                    value=mem_med,
                    evidence={"median_mem_used_pct": mem_med, "window_hours": H_SUSTAIN_HOURS},
                )
            elif mem_med >= 60:
                _add(
                    advice, reasons,
                    id="mem_sustained_moderate",
                    node=node,
                    category="memory",
                    severity="info",
                    message=f"Memory baseline is elevated (median {mem_med:.0f}% over ~{H_SUSTAIN_HOURS}h).",
                    recommendation="Not urgent, but it reduces headroom for spikes—worth keeping an eye on.",
                    confidence=0.65,
                    field="history(metrics.mem_used_pct)",
                    value=mem_med,
                    evidence={"median_mem_used_pct": mem_med, "window_hours": H_SUSTAIN_HOURS},
                )

        if load_series and isinstance(cores, int) and cores > 0:
            load_med = _median(load_series)
            if load_med is not None and load_med > float(cores) * 0.85:
                _add(
                    advice, reasons,
                    id="cpu_load_sustained",
                    node=node,
                    category="cpu",
                    severity="warn",
                    message=f"CPU load is consistently heavy (median {load_med:.2f} on {cores} cores over ~{H_SUSTAIN_HOURS}h).",
                    recommendation="Consider moving workloads, scheduling batch jobs, or upgrading CPU if this is typical.",
                    confidence=0.65,
                    field="history(metrics.cpu_load_1m)",
                    value=load_med,
                    evidence={"median_cpu_load_1m": load_med, "cpu_cores": cores, "window_hours": H_SUSTAIN_HOURS},
                )

    # -----------------------------
    # HISTORY: per-disk forecasting + headroom (worst 1–2 only)
    # -----------------------------
    hist_forecast = _fetch_history_payloads(str(node), hours=H_FORECAST_HOURS, limit=1500)
    if hist_forecast:
        # key -> list[(ts, used_pct)] plus last-known size
        series: Dict[str, List[Tuple[datetime, float]]] = {}
        last_meta: Dict[str, Dict[str, Any]] = {}

        for ts, p in hist_forecast:
            m = p.get("metrics") if isinstance(p.get("metrics"), dict) else {}
            targets = _extract_disk_targets(m)
            for key, info in targets.items():
                used = info.get("used_pct")
                if not isinstance(used, (int, float)):
                    continue
                series.setdefault(key, []).append((ts, float(used)))
                # keep the most recent size/label
                last_meta[key] = info

        forecasts: List[Dict[str, Any]] = []
        for key, pts in series.items():
            # compact identical values (reduces slope noise)
            compact: List[Tuple[datetime, float]] = []
            last_y = None
            for t, y in pts:
                if last_y is None or abs(y - last_y) >= 0.2:
                    compact.append((t, y))
                    last_y = y

            if len(compact) < max(FORECAST_MIN_POINTS, 4):
                continue

            slope = _linear_slope_pct_per_day(compact)
            if slope is None or slope <= FORECAST_MIN_SLOPE_PCT_PER_DAY:
                continue

            used_now2 = float(compact[-1][1])
            ts_now2 = compact[-1][0]
            days = _forecast_days_to_full(used_now2, slope)
            if days is None:
                continue

            meta = last_meta.get(key, {})
            label = str(meta.get("label") or key)
            size_gb = meta.get("size_gb") if isinstance(meta.get("size_gb"), (int, float)) else None

            # headroom in GB if size is known-ish
            free_gb = None
            gb_per_day = None
            if size_gb and size_gb > 1:
                free_gb = max(0.0, float(size_gb) * (1.0 - used_now2 / 100.0))
                gb_per_day = float(size_gb) * (slope / 100.0)

            eta = ts_now2 + timedelta(days=float(days))

            # severity by urgency (days)
            if days <= 14:
                sev = "crit"
            elif days <= 30:
                sev = "warn"
            else:
                sev = "info"

            forecasts.append({
                "key": key,
                "label": label,
                "sev": sev,
                "days": float(days),
                "eta": eta,
                "slope": float(slope),
                "used_now": used_now2,
                "size_gb": size_gb,
                "free_gb": free_gb,
                "gb_per_day": gb_per_day,
                "window_hours": H_FORECAST_HOURS,
            })

        # pick the worst few:
        # sort by severity rank then soonest ETA then highest used
        forecasts.sort(key=lambda f: (-_severity_rank(f["sev"]), f["days"], -f["used_now"]))
        forecasts = forecasts[: max(1, FORECAST_MAX_ITEMS)]

        for f in forecasts:
            label = f["label"]
            days = f["days"]
            eta = f["eta"]
            slope = f["slope"]
            used_now2 = f["used_now"]
            size_gb = f["size_gb"]
            free_gb = f["free_gb"]
            gb_per_day = f["gb_per_day"]

            # Message + headroom line when available
            eta_str = _fmt_eta(eta)
            if free_gb is not None and gb_per_day is not None and gb_per_day > 0.01:
                headroom = f"~{free_gb:.0f}GB free, growing ~{gb_per_day:.1f}GB/day."
            elif free_gb is not None:
                headroom = f"~{free_gb:.0f}GB free."
            else:
                headroom = f"Growing ~{slope:.2f}%/day."

            _add(
                advice, reasons,
                id=f"disk_fill_forecast_{_safe_id(f['key'])}",
                node=node,
                category="storage_forecast",
                severity=f["sev"],
                message=f"{label}: at the current rate, it will hit 100% in ~{days:.0f} days (by {eta_str}).",
                recommendation=f"{headroom} Identify what’s growing (logs/backups/media) or plan additional storage.",
                confidence=0.70,
                field="history(storage_used_pct)",
                value={"key": f["key"], "slope_pct_per_day": slope, "used_pct": used_now2},
                evidence={
                    "target": f["key"],
                    "label": label,
                    "used_pct_now": used_now2,
                    "slope_pct_per_day": slope,
                    "window_hours": f["window_hours"],
                    "eta_utc": eta.isoformat().replace("+00:00", "Z"),
                    "days_to_full": days,
                    "size_gb": size_gb,
                    "free_gb": free_gb,
                    "gb_per_day": gb_per_day,
                },
            )

    # -----------------------------
    # Health aggregation + sorting
    # -----------------------------
    worst = "info"
    for r in reasons:
        sev = str(r.get("severity", "info"))
        if _severity_rank(sev) > _severity_rank(worst):
            worst = sev

    health = {
        "state": _state_from_worst(worst),
        "worst_severity": worst,
        "reasons": reasons,
    }

    advice.sort(key=lambda a: (-_severity_rank(str(a.get("severity", "info"))), str(a.get("category", "")), str(a.get("id", ""))))
    return advice, health
