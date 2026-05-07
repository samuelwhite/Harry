from __future__ import annotations

from typing import Any, Dict, List, Optional


def _capabilities_dict(value: Any) -> Dict[str, Any]:
    return value if isinstance(value, dict) else {}


def status_copy(
    *,
    health_state: str = "healthy",
    stale: bool = False,
    delayed: bool = False,
    cpu_pressure_now: Optional[float] = None,
    disk_used_pct: Optional[float] = None,
    gpus: Optional[List[Dict[str, Any]]] = None,
    capabilities: Any = None,
) -> str:
    caps = _capabilities_dict(capabilities)
    gpu_present = bool(gpus and any(isinstance(g, dict) for g in gpus))
    state = (health_state or "healthy").lower()

    if stale:
        return "Harry has not heard from this machine recently."
    if delayed:
        return "Harry is hearing from this machine a little late."
    if disk_used_pct is not None and disk_used_pct >= 90:
        return "Storage is the thing to watch here."
    if cpu_pressure_now is not None and cpu_pressure_now >= 80:
        return "This machine is working hard right now."
    if gpu_present and caps.get("gpu") is not False:
        return "AI-capable hardware is available on this node."
    if state == "critical":
        return "This machine needs attention."
    if state == "warning":
        return "A few things deserve a closer look."
    if state == "info":
        return "Not urgent. Just noted."
    return "Everything looks calm."
