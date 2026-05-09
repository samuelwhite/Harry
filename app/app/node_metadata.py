from __future__ import annotations

import json
import os
import re
from hashlib import sha1
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


def _truthy_env(name: str) -> bool:
    return (os.environ.get(name) or "").strip().lower() in ("1", "true", "yes", "on")


def privacy_mode_enabled() -> bool:
    return _truthy_env("HARRY_PRIVACY_MODE") or _truthy_env("HARRY_ANONYMIZE_UI")


def _load_metadata_document() -> Any:
    source = _service_json()
    if source:
        try:
            return json.loads(source)
        except Exception:
            return []

    path = _service_file()
    if not path.exists() or not path.is_file():
        return []

    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return []


def _collect_privacy_alias_overrides(source: Any) -> Dict[str, str]:
    overrides: Dict[str, str] = {}

    env_source = (os.environ.get("HARRY_PRIVACY_ALIASES_JSON") or "").strip()
    if env_source:
        try:
            parsed = json.loads(env_source)
        except Exception:
            parsed = {}
        if isinstance(parsed, dict):
            for key, value in parsed.items():
                key_norm = _normalize_key(key)
                value_txt = str(value or "").strip()
                if key_norm and value_txt:
                    overrides[key_norm] = value_txt

    top_level = {}
    if isinstance(source, dict):
        top_level = source.get("privacy_aliases") or source.get("privacyAliases") or {}
    if isinstance(top_level, dict):
        for key, value in top_level.items():
            key_norm = _normalize_key(key)
            value_txt = str(value or "").strip()
            if key_norm and value_txt and key_norm not in overrides:
                overrides[key_norm] = value_txt

    return overrides


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
    parsed = _load_metadata_document()

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


_PRIVACY_ALIAS_CACHE: Dict[str, Dict[str, str]] = {}
_PRIVACY_REVERSE_CACHE: Dict[str, Dict[str, str]] = {}
_PRIVACY_ROUTE_CACHE: Dict[str, Dict[str, str]] = {}
_PRIVACY_BASE_CACHE: Dict[str, Dict[str, str]] = {}
_PRIVACY_FAMILY_COUNT: Dict[str, Dict[str, int]] = {}


def reset_privacy_aliases() -> None:
    _PRIVACY_ALIAS_CACHE.clear()
    _PRIVACY_REVERSE_CACHE.clear()
    _PRIVACY_ROUTE_CACHE.clear()
    _PRIVACY_BASE_CACHE.clear()
    _PRIVACY_FAMILY_COUNT.clear()


def _privacy_cache_key() -> str:
    if not privacy_mode_enabled():
        return "disabled"

    overrides = _collect_privacy_alias_overrides(_load_metadata_document())
    signature = sha1(
        json.dumps(sorted(overrides.items()), ensure_ascii=False).encode("utf-8")
    ).hexdigest()
    return f"enabled:{signature}"


def _privacy_base_label(node: str, meta: Optional[Dict[str, Any]] = None) -> str:
    meta = meta or get_node_metadata(node)

    bits = [
        str(meta.get("role") or ""),
        str(meta.get("character") or ""),
        str(meta.get("location") or ""),
        " ".join(str(tag) for tag in (meta.get("tags") or []) if str(tag).strip()),
        node,
    ]
    haystack = " ".join(part.strip().lower() for part in bits if part.strip())

    def has(*needles: str) -> bool:
        return any(needle in haystack for needle in needles)

    if has("offline", "stale", "hidden node"):
        return "Offline Node"
    if has("dns", "pihole", "unbound", "bind", "dnsmasq"):
        return "DNS Server"
    if has("media", "plex", "jellyfin", "emby", "sonarr", "radarr", "music", "video"):
        return "Media Server"
    if has("ai", "llm", "gpu", "model", "cortex", "ml", "inference"):
        return "AI Node"
    if has("mobile", "phone", "tablet", "android", "iphone", "ios", "ipad"):
        return "Mobile Device"
    if has("windows", "win10", "win11", "windows workstation"):
        return "Windows Workstation"
    if has("linux", "ubuntu", "debian", "fedora", "arch", "raspbian"):
        return "Linux Host"
    if has("nas", "storage", "fileserver", "file server", "backup", "backup server"):
        return "NAS"
    if has("workstation", "desktop", "laptop", "pc", "work pc", "gaming", "office"):
        return "Workstation"
    if has("server"):
        return "Server"

    return "Node"


def _privacy_ordered_nodes(known_nodes: Any) -> List[str]:
    nodes = []
    for item in known_nodes or []:
        node = _normalize_key(item)
        if node:
            nodes.append(node)
    return sorted(set(nodes))


def _privacy_route_slug(value: str) -> str:
    text = _normalize_key(value)
    text = re.sub(r"[^a-z0-9_-]+", "-", text)
    text = re.sub(r"-+", "-", text).strip("-")
    return text or "node"


def _privacy_assign_aliases(nodes: List[str], metadata_by_node: Optional[Dict[str, Dict[str, Any]]] = None) -> None:
    if not privacy_mode_enabled():
        return

    cache_key = _privacy_cache_key()
    aliases = _PRIVACY_ALIAS_CACHE.setdefault(cache_key, {})
    reverse = _PRIVACY_REVERSE_CACHE.setdefault(cache_key, {})
    routes = _PRIVACY_ROUTE_CACHE.setdefault(cache_key, {})
    bases = _PRIVACY_BASE_CACHE.setdefault(cache_key, {})
    family_counts = _PRIVACY_FAMILY_COUNT.setdefault(cache_key, {})
    overrides = _collect_privacy_alias_overrides(_load_metadata_document())

    metadata_by_node = metadata_by_node or {}

    for node in nodes:
        if node in aliases:
            continue

        base = overrides.get(node) or _privacy_base_label(node, metadata_by_node.get(node))
        if base == "Workstation":
            family_counts[base] = family_counts.get(base, 0) + 1
            alias = f"{base} {family_counts[base]}"
        elif base == "Node":
            family_counts[base] = family_counts.get(base, 0) + 1
            alias = f"{base} {family_counts[base]}"
        else:
            count = family_counts.get(base, 0)
            alias = base if count == 0 else f"{base} {count + 1}"
            family_counts[base] = count + 1

        candidate = alias
        suffix = 2
        while candidate.lower() in (value.lower() for value in aliases.values()):
            candidate = f"{alias} {suffix}"
            suffix += 1

        aliases[node] = candidate
        bases[node] = base
        route = _privacy_route_slug(candidate)
        routes[route] = node
        reverse[candidate.lower()] = node


def prime_privacy_aliases(known_nodes: Any, metadata_by_node: Optional[Dict[str, Dict[str, Any]]] = None) -> None:
    nodes = _privacy_ordered_nodes(known_nodes)
    _privacy_assign_aliases(nodes, metadata_by_node=metadata_by_node)


def _privacy_alias_for(node: str, metadata_by_node: Optional[Dict[str, Any]] = None) -> str:
    node = _normalize_key(node)
    if not node:
        return ""

    if not privacy_mode_enabled():
        return node

    cache_key = _privacy_cache_key()
    aliases = _PRIVACY_ALIAS_CACHE.setdefault(cache_key, {})
    if node in aliases:
        return aliases[node]

    context: Optional[Dict[str, Dict[str, Any]]] = None
    if isinstance(metadata_by_node, dict):
        if node in metadata_by_node and isinstance(metadata_by_node.get(node), dict):
            context = metadata_by_node  # already a node->meta mapping
        else:
            context = {node: metadata_by_node}

    _privacy_assign_aliases([node], metadata_by_node=context)
    return aliases.get(node, node)


def node_route_id(node: str, metadata_by_node: Optional[Dict[str, Any]] = None) -> str:
    label = _privacy_alias_for(node, metadata_by_node=metadata_by_node)
    if not privacy_mode_enabled():
        return node
    return _privacy_route_slug(label)


def resolve_node_reference(reference: str) -> str:
    node = _normalize_key(reference)
    if not node:
        return ""

    if not privacy_mode_enabled():
        return node

    cache_key = _privacy_cache_key()
    aliases = _PRIVACY_ALIAS_CACHE.get(cache_key, {})
    reverse = _PRIVACY_REVERSE_CACHE.get(cache_key, {})
    routes = _PRIVACY_ROUTE_CACHE.get(cache_key, {})

    if node in aliases:
        return node
    if node in reverse:
        return reverse[node]
    if node in routes:
        return routes[node]

    for actual, alias in aliases.items():
        if _privacy_route_slug(alias) == node:
            return actual

    return node


def node_display_name(node: str, metadata_by_node: Optional[Dict[str, Any]] = None) -> str:
    meta = get_node_metadata(node)
    if meta.get("display_name"):
        if not privacy_mode_enabled():
            return str(meta["display_name"])

    if privacy_mode_enabled():
        return _privacy_alias_for(node, metadata_by_node=metadata_by_node or meta)

    if (os.environ.get("HARRY_SCREENSHOT_MODE") or "").strip().lower() in ("1", "true", "yes", "on"):
        aliases = {
            "DESKTOP-EXAMPLE": "workstation-1",
            "WORKSTATION-01": "workstation-1",
            "media-server": "media-server-1",
            "ai-node": "ai-node-1",
            "nas-box": "nas-1",
            "home-assistant-host": "automation-node-1",
            "pi-kiosk": "kiosk-1",
            "network-gateway": "network-node-1",
        }
        return aliases.get(node, node)

    return node


def node_meta_summary(node: str, metadata_by_node: Optional[Dict[str, Any]] = None) -> str:
    meta = get_node_metadata(node)
    if privacy_mode_enabled():
        base = _privacy_base_label(node, metadata_by_node or meta)
        if base == "Node":
            return ""
        if base == "Workstation":
            return "Workstation"
        return base

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
