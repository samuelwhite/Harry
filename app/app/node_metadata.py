from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any, Dict, List, Optional

from app.config import DATA_DIR


def _safe_dict(value: Any) -> Dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _safe_list(value: Any) -> List[Any]:
    return value if isinstance(value, list) else []


def _normalize_key(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "").strip()).lower()


def _service_file() -> Path:
    return Path(os.environ.get("HARRY_NODE_METADATA_FILE", str(DATA_DIR / "node_metadata.json")))


def _service_json() -> str:
    return (os.environ.get("HARRY_NODE_METADATA_JSON") or "").strip()


def _normalize_entry(key_hint: str, value: Any) -> Optional[Dict[str, Any]]:
    raw = _safe_dict(value)
    node = _normalize_key(raw.get("node") or raw.get("name") or raw.get("hostname") or key_hint)
    if not node:
        return None

    display_name = str(raw.get("display_name") or raw.get("name") or raw.get("hostname") or key_hint or "").strip()
    role = str(raw.get("role") or "").strip()
    character = str(raw.get("character") or "").strip()
    location = str(raw.get("location") or "").strip()
    tags = [str(tag).strip() for tag in _safe_list(raw.get("tags")) if str(tag).strip()]

    return {
        "node": node,
        "display_name": display_name or node,
        "role": role,
        "character": character,
        "location": location,
        "tags": tags,
    }


def load_node_metadata() -> Dict[str, Dict[str, Any]]:
    source = _service_json()
    if source:
        try:
            parsed = json.loads(source)
        except Exception:
            parsed = []
    else:
        path = _service_file()
        if not path.exists() or not path.is_file():
            parsed = []
        else:
            try:
                parsed = json.loads(path.read_text(encoding="utf-8"))
            except Exception:
                parsed = []

    if isinstance(parsed, dict):
        if isinstance(parsed.get("nodes"), list):
            parsed = parsed.get("nodes")
        elif isinstance(parsed.get("items"), list):
            parsed = parsed.get("items")
        else:
            parsed = [
                {"node": key, **value}
                for key, value in parsed.items()
                if isinstance(value, dict)
            ]

    out: Dict[str, Dict[str, Any]] = {}
    for item in _safe_list(parsed):
        if not isinstance(item, dict):
            continue
        key_hint = str(item.get("node") or item.get("name") or item.get("hostname") or "").strip()
        entry = _normalize_entry(key_hint, item)
        if not entry:
            continue
        out[_normalize_key(entry["node"])] = entry

    return out


def get_node_metadata(node: str) -> Dict[str, Any]:
    key = _normalize_key(node)
    if not key:
        return {}
    return load_node_metadata().get(key, {})


def node_display_name(node: str) -> str:
    meta = get_node_metadata(node)
    if meta.get("display_name"):
        return str(meta["display_name"])

    if (os.environ.get("HARRY_SCREENSHOT_MODE") or "").strip().lower() in ("1", "true", "yes", "on"):
        aliases = {
            "DESKTOP-8QV3E94": "compute-node-1",
            "Desktop-Sam": "gaming-pc-1",
            "DESKTOP-SAM": "gaming-pc-1",
            "alfred": "server-1",
            "cortex": "ai-node-1",
            "jarvis": "compute-node-2",
            "lois-edge": "edge-node-1",
            "pi-kiosk": "kiosk-1",
            "pihole": "network-node-1",
        }
        return aliases.get(node, node)

    return node


def node_meta_summary(node: str) -> str:
    meta = get_node_metadata(node)
    bits: List[str] = []
    if meta.get("role"):
        bits.append(str(meta["role"]))
    if meta.get("character") and meta.get("character") not in bits:
        bits.append(str(meta["character"]))
    if meta.get("location"):
        bits.append(str(meta["location"]))
    if meta.get("tags"):
        bits.append(", ".join(str(tag) for tag in meta.get("tags") or []))
    return " · ".join(bits)
