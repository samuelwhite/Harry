# app/health.py
from datetime import datetime, timezone
from typing import Dict, Any, Optional


def _severity_rank(level: str) -> int:
    """
    Convert a health state into an ordinal rank.

    Harry health is intentionally simple:
      healthy < warning < critical

    Using an explicit ranking helper keeps comparisons obvious and avoids
    scattered string-order assumptions elsewhere in the codebase.
    """
    return {"healthy": 0, "warning": 1, "critical": 2}.get(level, 0)


def compute_health(payload: Dict[str, Any], ctx: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """
    Compute a small, explainable health summary from a snapshot payload.

    Important design note:
    Harry's health model is intentionally heuristic rather than "smart".
    The goal is to produce a clear operational signal that humans can inspect,
    not to hide judgement inside an opaque scoring engine.

    ctx allows the Brain to inject version-policy information such as schema
    mismatch tolerances without hard-coding those values into every caller.
    """
    ctx = ctx or {}

    reasons = []
    worst = "healthy"
    score = 100

    now = datetime.now(timezone.utc)

    # ---- Staleness ----------------------------------------------------------
    # Freshness is one of the most important signals in Harry because a perfect
    # old snapshot is still operationally misleading.
    age_minutes = None
    try:
        ts = datetime.fromisoformat(payload["ts"].replace("Z", "+00:00"))
        age_minutes = (now - ts).total_seconds() / 60

        if age_minutes > 30:
            reasons.append(f"Node stale ({int(age_minutes)}m since last report)")
            worst = "critical"
            score -= 40
        elif age_minutes > 15:
            reasons.append(f"Node delayed ({int(age_minutes)}m since last report)")
            worst = max(worst, "warning", key=_severity_rank)
            score -= 20
    except Exception:
        reasons.append("Invalid timestamp")
        worst = "critical"
        score -= 50

    # ---- Schema mismatch (soft, then escalates) -----------------------------
    # Version mismatch is not always immediately bad because rolling updates
    # exist. Harry therefore treats fresh mismatch softly and only escalates
    # when the node remains behind for longer than expected.
    schema_current = ctx.get("schema_current")
    schema_warn_min = ctx.get("schema_behind_warn_min", 15)
    schema_crit_min = ctx.get("schema_behind_crit_min", 60)

    schema_reported = payload.get("schema_version") or payload.get("schema") or "unknown"

    if schema_current and schema_reported != "unknown" and schema_reported != schema_current:
        if age_minutes is None:
            reasons.append(f"Schema behind ({schema_reported} vs {schema_current})")
            worst = max(worst, "warning", key=_severity_rank)
            score -= 5
        elif age_minutes >= schema_crit_min:
            reasons.append(f"Agent not updating (schema {schema_reported} vs {schema_current})")
            worst = "critical"
            score -= 25
        elif age_minutes >= schema_warn_min:
            reasons.append(f"Schema behind ({schema_reported} vs {schema_current})")
            worst = max(worst, "warning", key=_severity_rank)
            score -= 10
        else:
            reasons.append(f"Schema rolling update ({schema_reported} → {schema_current})")
            score -= 2

    metrics = payload.get("metrics", {}) or {}

    # ---- CPU ----------------------------------------------------------------
    # Harry uses simple per-core load rather than trying to infer intent from
    # workloads. This keeps the signal understandable across mixed hardware.
    load = metrics.get("cpu_load_1m")
    if load is None:
        load = metrics.get("load_1")  # legacy fallback

    cores = payload.get("facts", {}).get("cpu_cores", 1) or 1
    try:
        load = float(load) if load is not None else None
    except Exception:
        load = None

    if load is not None and cores:
        per_core = load / cores
        if per_core > 2.5:
            reasons.append("High CPU load")
            worst = "critical"
            score -= 30
        elif per_core > 1.5:
            reasons.append("Elevated CPU load")
            worst = max(worst, "warning", key=_severity_rank)
            score -= 15

    # ---- RAM ----------------------------------------------------------------
    mem_used = metrics.get("mem_used_pct")
    try:
        mem_used = float(mem_used) if mem_used is not None else None
    except Exception:
        mem_used = None

    if mem_used is not None:
        if mem_used > 95:
            reasons.append("RAM critical")
            worst = "critical"
            score -= 30
        elif mem_used > 85:
            reasons.append("RAM high")
            worst = max(worst, "warning", key=_severity_rank)
            score -= 15

    # ---- Disk ---------------------------------------------------------------
    # We treat each mount independently because a single full filesystem is
    # often enough to create a real operational problem.
    for disk in metrics.get("disk_used", []) or []:
        if not isinstance(disk, dict):
            continue

        pct = disk.get("used_pct", disk.get("pct"))
        try:
            pct = float(pct) if pct is not None else None
        except Exception:
            pct = None

        if pct is not None:
            mount = disk.get("mount", "?")
            if pct > 95:
                reasons.append(f"Disk {mount} critical")
                worst = "critical"
                score -= 25
            elif pct > 85:
                reasons.append(f"Disk {mount} high")
                worst = max(worst, "warning", key=_severity_rank)
                score -= 10

    # ---- GPU ----------------------------------------------------------------
    # GPU telemetry is optional because many Harry nodes will not have one.
    for gpu in metrics.get("gpu", []) or []:
        if not isinstance(gpu, dict):
            continue

        temp = gpu.get("temp_c")
        try:
            temp = float(temp) if temp is not None else None
        except Exception:
            temp = None

        if temp is not None:
            if temp > 95:
                reasons.append("GPU overheating")
                worst = "critical"
                score -= 25
            elif temp > 85:
                reasons.append("GPU hot")
                worst = max(worst, "warning", key=_severity_rank)
                score -= 10

    score = max(score, 0)

    return {
        "state": worst,
        "score": score,
        "reasons": reasons,
        "age_minutes": age_minutes,
    }
