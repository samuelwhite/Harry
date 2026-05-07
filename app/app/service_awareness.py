from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from app.config import DATA_DIR
from app.health import compute_health
from app.ui.db import STALE_SECONDS, get_latest_node_records, _parse_ts, _safe_str


def _safe_dict(value: Any) -> Dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _safe_list(value: Any) -> List[Any]:
    return value if isinstance(value, list) else []


def _iso_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _service_file() -> Path:
    return Path(os.environ.get("HARRY_SERVICES_FILE", str(DATA_DIR / "services.json")))


def _service_json_override() -> str:
    return (os.environ.get("HARRY_SERVICES_JSON") or "").strip()


def _normalize_status(value: Any) -> str:
    sev = str(value or "").strip().lower()
    if sev in ("online", "healthy", "running", "up", "ok", "success"):
        return "online"
    if sev in ("degraded", "warning", "warn", "slow", "partial"):
        return "degraded"
    if sev in ("offline", "down", "error", "failed", "stopped", "dead"):
        return "offline"
    return "unknown"


def _normalize_type(value: Any) -> str:
    kind = str(value or "manual").strip().lower()
    if kind in ("docker", "systemd", "http", "manual"):
        return kind
    return "manual"


def _normalize_service_spec(value: Any) -> Optional[Dict[str, Any]]:
    raw = _safe_dict(value)
    name = _safe_str(raw.get("name") or raw.get("service") or raw.get("display_name")).strip()
    if not name:
        return None

    node = _safe_str(raw.get("node") or raw.get("machine_id") or raw.get("host") or raw.get("hostname")).strip()
    role = _safe_str(raw.get("role") or raw.get("category") or "").strip()
    service_type = _normalize_type(raw.get("type"))
    url = _safe_str(raw.get("url") or raw.get("href") or "").strip()
    port = raw.get("port")
    try:
        port = int(port) if port not in (None, "") else None
    except Exception:
        port = None

    tags = [str(tag).strip() for tag in _safe_list(raw.get("tags")) if str(tag).strip()]

    return {
        "name": name,
        "role": role,
        "node": node or None,
        "type": service_type,
        "url": url or None,
        "port": port,
        "tags": tags,
        "docker_service": _safe_str(raw.get("docker_service") or raw.get("container") or "").strip() or None,
        "systemd_unit": _safe_str(raw.get("systemd_unit") or raw.get("unit") or "").strip() or None,
        "process": _safe_str(raw.get("process") or raw.get("command") or "").strip() or None,
        "metadata": raw.get("metadata") if isinstance(raw.get("metadata"), dict) else {},
    }


def _load_specs_from_source() -> List[Dict[str, Any]]:
    service_json = _service_json_override()
    if service_json:
        try:
            parsed = json.loads(service_json)
        except Exception:
            parsed = []
    else:
        service_file = _service_file()
        if not service_file.exists() or not service_file.is_file():
            parsed = []
        else:
            try:
                parsed = json.loads(service_file.read_text(encoding="utf-8"))
            except Exception:
                parsed = []

    if isinstance(parsed, dict):
        parsed = parsed.get("services") or parsed.get("items") or []

    specs: List[Dict[str, Any]] = []
    for item in _safe_list(parsed):
        spec = _normalize_service_spec(item)
        if spec:
            specs.append(spec)
    return specs


def _extract_telemetry_services(payload: Dict[str, Any]) -> List[Dict[str, Any]]:
    services: List[Dict[str, Any]] = []

    candidates = [
        payload.get("services"),
        _safe_dict(payload.get("facts")).get("services"),
        _safe_dict(_safe_dict(payload.get("facts")).get("extensions")).get("services"),
        _safe_dict(payload.get("metrics")).get("services"),
        _safe_dict(_safe_dict(payload.get("metrics")).get("extensions")).get("services"),
        _safe_dict(payload.get("extensions")).get("services"),
    ]

    for candidate in candidates:
        for item in _safe_list(candidate):
            if not isinstance(item, dict):
                continue
            spec = _normalize_service_spec(item)
            if spec:
                services.append(spec)

    return services


def _status_from_health(node_health: Dict[str, Any]) -> str:
    state = str(node_health.get("state") or "unknown").lower()
    if state == "critical":
        return "offline"
    if state == "warning":
        return "degraded"
    if state == "healthy":
        return "online"
    return "unknown"


def _match_telemetry_service(spec: Dict[str, Any], telemetry: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    spec_name = str(spec.get("name") or "").strip().lower()
    spec_role = str(spec.get("role") or "").strip().lower()
    spec_port = spec.get("port")

    for item in telemetry:
        item_name = str(item.get("name") or "").strip().lower()
        item_role = str(item.get("role") or "").strip().lower()
        item_port = item.get("port")

        if spec_name and item_name == spec_name:
            return item
        if spec_role and item_role == spec_role:
            return item
        if spec_port is not None and item_port is not None and str(spec_port) == str(item_port):
            return item

    return None


def _service_row_from_spec(spec: Dict[str, Any], latest: Dict[str, Dict[str, Any]]) -> Dict[str, Any]:
    node = spec.get("node")
    rec = latest.get(node) if node else None
    payload = rec.get("payload") if isinstance(rec, dict) and isinstance(rec.get("payload"), dict) else {}
    telemetry = _extract_telemetry_services(payload)
    telemetry_match = _match_telemetry_service(spec, telemetry)
    capabilities = _safe_dict(payload.get("capabilities"))

    status = "unknown"
    health = "unknown"
    message = "No matching node yet."
    last_checked = None

    if rec:
        last_checked = rec.get("ts")
        node_health = compute_health(payload, ctx={})
        health = str(node_health.get("state") or "unknown").lower()
        status = _status_from_health(node_health)
        message = "Derived from the latest node snapshot."

        if node_health.get("state") == "critical" and any("stale" in str(r).lower() for r in (node_health.get("reasons") or [])):
            status = "offline"
            message = "Node has stopped reporting."

        service_type = str(spec.get("type") or "manual").lower()
        if service_type == "docker" and capabilities.get("docker") is False:
            status = "degraded"
            message = "Docker reporting is unsupported by this agent."
        elif service_type == "systemd" and capabilities.get("systemd") is False:
            status = "degraded"
            message = "systemd reporting is unsupported by this agent."

        if telemetry_match:
            telemetry_status = _normalize_status(
                telemetry_match.get("status") or telemetry_match.get("state") or telemetry_match.get("health")
            )
            if telemetry_status != "unknown":
                status = telemetry_status
                message = "Derived from node-reported service telemetry."

        health = status

    url = spec.get("url")
    if telemetry_match and telemetry_match.get("url"):
        url = telemetry_match.get("url")
    elif not url and spec.get("node") and spec.get("port") and spec.get("type") in ("http", "manual"):
        url = f"http://{spec['node']}:{spec['port']}"

    row = {
        "name": spec["name"],
        "role": spec.get("role") or "",
        "node": spec.get("node") or None,
        "machine_id": spec.get("node") or None,
        "type": spec.get("type") or "manual",
        "status": status,
        "health": health,
        "last_checked": last_checked or _iso_now(),
        "url": url,
        "port": spec.get("port"),
        "message": message,
        "tags": spec.get("tags") or [],
        "metadata": {
            "source": "config" if spec.get("node") or spec.get("url") or spec.get("port") else "derived",
            "node_health": node_health.get("state") if rec else None,
            "capabilities": capabilities,
            "telemetry": telemetry_match or {},
            "spec": spec.get("metadata") or {},
        },
    }
    return row


def _brain_service_row() -> Dict[str, Any]:
    return {
        "name": "Harry Brain",
        "role": "Brain",
        "node": None,
        "machine_id": None,
        "type": "manual",
        "status": "online",
        "health": "online",
        "last_checked": _iso_now(),
        "url": None,
        "port": None,
        "message": "The Brain API is responding.",
        "tags": ["brain"],
        "metadata": {"source": "built-in"},
    }


def build_service_rows() -> List[Dict[str, Any]]:
    latest = get_latest_node_records()
    specs = _load_specs_from_source()

    rows: List[Dict[str, Any]] = []
    seen: set[str] = set()

    for spec in specs:
        row = _service_row_from_spec(spec, latest)
        key = row["name"].strip().lower()
        if key in seen:
            continue
        seen.add(key)
        rows.append(row)

    brain_row = _brain_service_row()
    if brain_row["name"].strip().lower() not in seen:
        rows.append(brain_row)

    rows.sort(key=lambda r: (str(r.get("status") or ""), str(r.get("name") or "")))
    return rows
