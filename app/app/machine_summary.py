from __future__ import annotations

import hashlib
import json
import os
import re
import threading
import time
from pathlib import Path
from typing import Any, Dict, List, Optional
from urllib import request as urllib_request

from app.config import DATA_DIR


SUMMARY_CACHE_DIR = DATA_DIR / "machine_summaries"
SUMMARY_TTL_SECONDS = int(os.environ.get("HARRY_SUMMARY_TTL_SECONDS", str(24 * 60 * 60)))

_INFLIGHT: set[str] = set()
_LOCK = threading.Lock()


def _enabled() -> bool:
    return (os.environ.get("HARRY_ENABLE_LLM_SUMMARIES") or "").strip().lower() in ("1", "true", "yes", "on")


def _llm_base_url() -> str:
    return (os.environ.get("HARRY_LLM_BASE_URL") or "").strip().rstrip("/")


def _llm_model() -> str:
    return (os.environ.get("HARRY_LLM_MODEL") or "local-model").strip() or "local-model"


def _safe_name(node: str) -> str:
    clean = re.sub(r"[^a-zA-Z0-9_.-]+", "_", (node or "").strip())
    return clean or "unknown"


def _cache_path(node: str) -> Path:
    return SUMMARY_CACHE_DIR / f"{_safe_name(node)}.json"


def _iso_now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _safe_dict(value: Any) -> Dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _safe_list(value: Any) -> List[Any]:
    return value if isinstance(value, list) else []


def _max_disk_used_pct(payload: Dict[str, Any]) -> Optional[float]:
    metrics = _safe_dict(payload.get("metrics"))
    disk_used = _safe_list(metrics.get("disk_used"))
    vals: List[float] = []
    for disk in disk_used:
        if not isinstance(disk, dict):
            continue
        pct = disk.get("used_pct", disk.get("pct"))
        try:
            if pct is not None:
                vals.append(float(pct))
        except Exception:
            continue
    return max(vals) if vals else None


def _gpu_present(payload: Dict[str, Any]) -> bool:
    facts = _safe_dict(payload.get("facts"))
    metrics = _safe_dict(payload.get("metrics"))
    gpus = _safe_list(metrics.get("gpu")) or _safe_list(facts.get("gpus"))
    return any(isinstance(g, dict) for g in gpus)


def _should_attempt_summary(payload: Dict[str, Any]) -> bool:
    return _gpu_present(payload) or bool(_llm_base_url())


def _summary_fingerprint(payload: Dict[str, Any]) -> str:
    facts = _safe_dict(payload.get("facts"))
    metrics = _safe_dict(payload.get("metrics"))
    capabilities = _safe_dict(payload.get("capabilities"))
    gpu_names = []
    for g in _safe_list(metrics.get("gpu")) + _safe_list(facts.get("gpus")):
        if isinstance(g, dict):
            name = str(g.get("name") or g.get("model") or g.get("gpu") or "").strip()
            if name:
                gpu_names.append(name)

    bits = {
        "node": payload.get("node"),
        "schema_version": payload.get("schema_version"),
        "model": facts.get("model"),
        "cpu": facts.get("cpu"),
        "cpu_load_1m": metrics.get("cpu_load_1m"),
        "mem_used_pct": metrics.get("mem_used_pct"),
        "disk_used_pct": _max_disk_used_pct(payload),
        "gpu_names": sorted(set(gpu_names)),
        "gpu_capability": capabilities.get("gpu"),
    }
    raw = json.dumps(bits, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()[:16]


def _render_local_summary(payload: Dict[str, Any]) -> str:
    facts = _safe_dict(payload.get("facts"))
    metrics = _safe_dict(payload.get("metrics"))
    capabilities = _safe_dict(payload.get("capabilities"))

    health_state = str(_safe_dict(payload.get("derived")).get("health", {}).get("state") or "healthy").lower()
    cpu_load = metrics.get("cpu_load_1m")
    mem_used = metrics.get("mem_used_pct")
    disk_used = _max_disk_used_pct(payload)
    gpu_present = _gpu_present(payload) and capabilities.get("gpu", True) is not False

    def band(value: Optional[float], low: float, high: float) -> str:
        if value is None:
            return "unknown"
        if value < low:
            return "low"
        if value < high:
            return "moderate"
        return "high"

    cpu_band = band(cpu_load if isinstance(cpu_load, (int, float)) else None, 35, 75)
    mem_band = band(mem_used if isinstance(mem_used, (int, float)) else None, 55, 85)

    parts = []
    if health_state == "critical":
        parts.append("This machine needs attention.")
    elif health_state == "warning":
        parts.append("A few things deserve a closer look.")
    else:
        parts.append("Everything looks calm.")

    parts.append(f"CPU load is {cpu_band}.")
    parts.append(f"Memory use is {mem_band}.")

    if disk_used is not None and disk_used >= 90:
        parts.append("Storage is the thing to watch here.")
    elif disk_used is not None and disk_used >= 75:
        parts.append("Disk usage is getting warm.")

    if gpu_present:
        parts.append("AI-capable hardware is available on this node.")

    model = str(facts.get("model") or "").strip()
    if model:
        parts.append(f"Hardware: {model}.")

    return " ".join(parts).strip()


def _load_cache(node: str) -> Optional[Dict[str, Any]]:
    path = _cache_path(node)
    if not path.exists() or not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else None
    except Exception:
        return None


def _write_cache(record: Dict[str, Any]) -> None:
    try:
        SUMMARY_CACHE_DIR.mkdir(parents=True, exist_ok=True)
        path = _cache_path(str(record.get("node") or "unknown"))
        path.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception:
        pass


def _call_local_llm(prompt: str) -> str:
    base_url = _llm_base_url()
    if not base_url:
        raise RuntimeError("llm_base_url_not_configured")

    body = json.dumps(
        {
            "model": _llm_model(),
            "messages": [
                {"role": "system", "content": "You write short, factual machine summaries."},
                {"role": "user", "content": prompt},
            ],
            "temperature": 0.2,
            "stream": False,
        }
    ).encode("utf-8")

    req = urllib_request.Request(
        f"{base_url}/v1/chat/completions",
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    with urllib_request.urlopen(req, timeout=15) as resp:
        data = json.loads(resp.read().decode("utf-8", errors="replace"))

    choices = data.get("choices") if isinstance(data, dict) else None
    if isinstance(choices, list) and choices:
        first = choices[0] if isinstance(choices[0], dict) else {}
        message = first.get("message") if isinstance(first.get("message"), dict) else {}
        text = str(message.get("content") or "").strip()
        if text:
            return text

    raise RuntimeError("llm_response_missing_content")


def build_machine_summary(payload: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    if not _enabled():
        return None
    if not _should_attempt_summary(payload):
        return None

    node = str(payload.get("node") or payload.get("facts", {}).get("hostname") or "unknown")
    fingerprint = _summary_fingerprint(payload)
    local_text = _render_local_summary(payload)
    source = "local"

    if _llm_base_url():
        prompt = (
            "Summarize this node in one or two short factual sentences. "
            "Keep the hardware facts visible and avoid fluff.\n\n"
            f"{local_text}"
        )
        try:
            llm_text = _call_local_llm(prompt).strip()
            if llm_text:
                local_text = llm_text
                source = "llm"
        except Exception:
            pass

    record = {
        "node": node,
        "fingerprint": fingerprint,
        "generated_at": _iso_now(),
        "source": source,
        "summary": local_text,
    }
    _write_cache(record)
    return record


def _summary_stale(record: Dict[str, Any]) -> bool:
    ts = str(record.get("generated_at") or "")
    if not ts:
        return True
    try:
        if ts.endswith("Z"):
            ts = ts[:-1] + "+00:00"
        # RFC3339-ish parsed by fromisoformat
        from datetime import datetime, timezone

        dt = datetime.fromisoformat(ts)
        now = datetime.now(timezone.utc)
        return (now - dt).total_seconds() > SUMMARY_TTL_SECONDS
    except Exception:
        return True


def _maybe_queue_refresh(payload: Dict[str, Any], fingerprint: str) -> None:
    if not _enabled() or not _llm_base_url():
        return

    with _LOCK:
        if fingerprint in _INFLIGHT:
            return
        _INFLIGHT.add(fingerprint)

    def _runner() -> None:
        try:
            build_machine_summary(payload)
        finally:
            with _LOCK:
                _INFLIGHT.discard(fingerprint)

    threading.Thread(target=_runner, daemon=True).start()


def get_machine_summary(payload: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    if not _enabled():
        return None
    if not _should_attempt_summary(payload):
        return None

    node = str(payload.get("node") or payload.get("facts", {}).get("hostname") or "unknown")
    fingerprint = _summary_fingerprint(payload)
    cached = _load_cache(node)
    if cached and cached.get("fingerprint") == fingerprint and not _summary_stale(cached):
        return cached

    local = {
        "node": node,
        "fingerprint": fingerprint,
        "generated_at": _iso_now(),
        "source": "local",
        "summary": _render_local_summary(payload),
    }
    _write_cache(local)
    _maybe_queue_refresh(payload, fingerprint)
    return local
