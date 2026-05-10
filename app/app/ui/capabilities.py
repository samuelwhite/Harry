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


def gpu_capability_hint(gpu: Any) -> str:
    if not isinstance(gpu, dict):
        return ""

    hint = str(gpu.get("capability_hint") or "").strip()
    if hint:
        return hint

    name = str(gpu.get("name") or "").lower()
    vendor = str(gpu.get("vendor") or "").lower()
    integrated = bool(gpu.get("integrated"))

    if "nvidia" in vendor or "nvidia" in name or "geforce" in name or "quadro" in name:
        return "CUDA capable"
    if integrated:
        return "Integrated graphics"
    if "intel" in vendor or "intel" in name or "iris" in name or "uhd" in name:
        return "Integrated graphics"
    if "amd" in vendor or "radeon" in name:
        return "Dedicated graphics"
    return ""
