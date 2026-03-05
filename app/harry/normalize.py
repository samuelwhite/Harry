from __future__ import annotations

from typing import Any, Dict


def normalize_snapshot(s: Dict[str, Any]) -> Dict[str, Any]:
    s = dict(s or {})
    s.setdefault("facts", {})
    s.setdefault("metrics", {})

    facts = dict(s["facts"] or {})
    metrics = dict(s["metrics"] or {})

    facts.setdefault("disks", [])
    facts.setdefault("gpus", [])
    metrics.setdefault("disk_used", [])
    metrics.setdefault("temps_c", {})
    metrics.setdefault("gpu", [])

    # Defensive numeric coercion
    for k in ("cpu_load_1m", "mem_used_pct"):
        v = metrics.get(k)
        if v is None:
            metrics[k] = 0.0
            continue
        try:
            metrics[k] = float(v)
        except Exception:
            metrics[k] = 0.0

    s["facts"] = facts
    s["metrics"] = metrics
    return s
