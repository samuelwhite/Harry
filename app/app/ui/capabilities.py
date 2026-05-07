from __future__ import annotations

from typing import Any, Dict, List


def _capabilities_dict(value: Any) -> Dict[str, Any]:
    return value if isinstance(value, dict) else {}


def gpu_state_message(capabilities: Any, gpus: List[Dict[str, Any]]) -> str:
    if isinstance(gpus, list) and any(isinstance(g, dict) for g in gpus):
        return ""

    caps = _capabilities_dict(capabilities)
    gpu_cap = caps.get("gpu")
    if gpu_cap is False:
        return "GPU reporting unsupported by this agent"
    if gpu_cap is True:
        return "No GPU detected"
    return "GPU data unavailable"
