from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Iterable, List, Optional, Tuple

from app.db_helpers import STALE_SECONDS, _parse_ts, _safe_str
from app.node_metadata import node_display_name, prime_privacy_aliases


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def format_duration(minutes: float | int | None) -> str:
    try:
        mins = max(0, int(round(float(minutes or 0))))
    except Exception:
        mins = 0

    if mins < 1:
        return "just now"
    if mins < 60:
        return f"about {mins} minute" + ("s" if mins != 1 else "")

    hours, rem_minutes = divmod(mins, 60)
    if mins < 24 * 60:
        if rem_minutes:
            return f"{hours}h {rem_minutes}m"
        return f"about {hours} hour" + ("" if hours == 1 else "s")

    days, rem_hours = divmod(hours, 24)
    if rem_hours:
        return f"{days}d {rem_hours}h"
    if days == 1:
        return "1d"
    return f"{days}d"


def format_relative_ago(dt: Optional[datetime], *, now: Optional[datetime] = None) -> str:
    if not dt:
        return "unknown"

    now = now or _now_utc()
    delta = now - dt
    seconds = int(delta.total_seconds())
    if seconds < 0:
        return "just now"
    if seconds < 60:
        return "just now"

    minutes = seconds // 60
    if minutes < 60:
        return f"{minutes} minute" + ("s" if minutes != 1 else "") + " ago"

    if minutes < 24 * 60:
        hours, rem_minutes = divmod(minutes, 60)
        if rem_minutes:
            return f"{hours}h {rem_minutes}m ago"
        return f"about {hours} hours ago"

    days, rem_hours = divmod(minutes // 60, 24)
    if days == 1 and rem_hours == 0:
        return "yesterday"
    if rem_hours:
        return f"{days}d {rem_hours}h ago"
    return f"{days}d ago"


def _event_time(event: Dict[str, Any]) -> Optional[datetime]:
    created_at = _parse_ts(_safe_str(event.get("created_at") or ""))
    return created_at


def _node_label(event: Dict[str, Any]) -> str:
    node = _safe_str(event.get("node_id") or event.get("machine_id") or "").strip()
    if not node:
        return ""
    return node_display_name(node)


def _event_sort_key(event: Dict[str, Any]) -> Tuple[datetime, int]:
    ts = _event_time(event) or datetime(1970, 1, 1, tzinfo=timezone.utc)
    try:
        event_id = int(event.get("id") or 0)
    except Exception:
        event_id = 0
    return (ts, event_id)


def _current_node_record(
    current_nodes: Optional[Dict[str, Dict[str, Any]]],
    node_id: str,
) -> Optional[Dict[str, Any]]:
    if not current_nodes or not node_id:
        return None
    record = current_nodes.get(node_id)
    return record if isinstance(record, dict) else None


def _node_is_currently_stale(
    node_id: str,
    current_nodes: Optional[Dict[str, Dict[str, Any]]],
    *,
    now: datetime,
) -> bool:
    record = _current_node_record(current_nodes, node_id)
    if not record:
        return False

    if record.get("stale") is True:
        return True

    ts = _parse_ts(_safe_str(record.get("ts") or ""))
    if not ts:
        return False
    return (now - ts).total_seconds() >= STALE_SECONDS


def _node_is_currently_degraded(
    node_id: str,
    current_nodes: Optional[Dict[str, Dict[str, Any]]],
) -> bool:
    record = _current_node_record(current_nodes, node_id)
    if not record:
        return False

    payload = record.get("payload") if isinstance(record.get("payload"), dict) else {}
    agent_status = payload.get("agent_status") if isinstance(payload.get("agent_status"), dict) else {}
    state = _safe_str(agent_status.get("state") or "").strip().lower()
    if state in {"bootstrapping", "degraded", "error"}:
        return True
    return agent_status.get("ok") is False


def _recovery_detail(minutes: float | int | None, *, known: bool = True) -> str:
    if not known or minutes is None:
        return "Recovered; duration unknown."

    mins = max(0.0, float(minutes))
    if mins < 1:
        return "Recovered after a short gap"
    return f"Recovered after {format_duration(mins)}"


def _format_event_title(
    event: Dict[str, Any],
    *,
    now: datetime,
    current_nodes: Optional[Dict[str, Dict[str, Any]]] = None,
) -> Tuple[str, str]:
    typ = _safe_str(event.get("type") or "").strip()
    node = _node_label(event) or "this node"
    node_id = _safe_str(event.get("node_id") or event.get("machine_id") or "").strip()
    message = _safe_str(event.get("message") or "").strip()
    metadata = event.get("metadata") if isinstance(event.get("metadata"), dict) else {}

    if typ == "agent.first_seen":
        return (f"Harry noticed {node} for the first time", "First check-in")
    if typ == "agent.heartbeat_missed":
        gap_seconds = metadata.get("age_seconds") or metadata.get("gap_seconds")
        gap_mins = float(gap_seconds or 0) / 60.0 if gap_seconds is not None else None
        if _node_is_currently_stale(node_id, current_nodes, now=now):
            detail = f"No response for {format_duration(gap_mins)}" if gap_mins is not None else "Waiting for a fresh heartbeat."
            return (f"{node} is not checking in right now", detail)
        detail = f"Missed a heartbeat for {format_duration(gap_mins)}" if gap_mins is not None else "Missed a heartbeat earlier."
        return (f"Harry missed a heartbeat from {node}", detail)
    if typ == "agent.heartbeat_restored":
        gap_seconds = metadata.get("gap_seconds")
        gap_mins = float(gap_seconds or 0) / 60.0 if gap_seconds is not None else None
        detail = _recovery_detail(gap_mins, known=gap_seconds is not None)
        return (f"{node} recovered", detail)
    if typ == "agent.offline":
        state = _safe_str(metadata.get("state") or "").strip()
        detail = message or (f"Last known state: {state}" if state else "Last known state unavailable")
        if _node_is_currently_stale(node_id, current_nodes, now=now) or _node_is_currently_degraded(node_id, current_nodes):
            return (f"{node} is not checking in right now", detail)
        return (f"{node} reported trouble earlier", detail)
    if typ == "hardware.gpu_detected":
        count = metadata.get("gpu_count")
        detail = f"Reported {count} GPU" + ("s" if count and int(count) != 1 else "") if count else "GPU hardware detected"
        return (f"{node} reported GPU hardware", detail)
    if typ == "storage.disk_warning":
        used = metadata.get("used_pct")
        detail = f"Disk usage reached {int(round(float(used)))}%" if used is not None else (message or "Storage deserves attention")
        return (f"Storage needs attention on {node}", detail)
    if typ == "summary.refreshed":
        return (f"Summary refreshed for {node}", message or "Cached summary updated")

    title = _safe_str(event.get("title") or "").strip() or typ.replace(".", " ").strip().title() or "Event"
    detail = message
    return (title, detail)


def prepare_activity_items(
    events: Iterable[Dict[str, Any]],
    *,
    now: Optional[datetime] = None,
    current_nodes: Optional[Dict[str, Dict[str, Any]]] = None,
) -> List[Dict[str, Any]]:
    now = now or _now_utc()
    prime_privacy_aliases(
        [
            _safe_str(e.get("node_id") or e.get("machine_id") or "").strip()
            for e in events
            if isinstance(e, dict)
        ]
        + list((current_nodes or {}).keys())
    )
    ordered = sorted([e for e in events if isinstance(e, dict)], key=_event_sort_key, reverse=True)
    items: List[Dict[str, Any]] = []
    used: set[int] = set()
    pair_window = timedelta(minutes=45)
    latest_restored: Dict[str, datetime] = {}

    for event in ordered:
        typ = _safe_str(event.get("type") or "").strip()
        node_id = _safe_str(event.get("node_id") or event.get("machine_id") or "").strip()
        created_at = _event_time(event)
        if typ == "agent.heartbeat_restored" and node_id and created_at and node_id not in latest_restored:
            latest_restored[node_id] = created_at

    for idx, event in enumerate(ordered):
        if idx in used:
            continue

        created_at = _event_time(event)
        typ = _safe_str(event.get("type") or "").strip()
        node_id = _safe_str(event.get("node_id") or event.get("machine_id") or "").strip()
        node_label = _node_label(event)
        level = _safe_str(event.get("level") or "info").strip().lower() or "info"

        if typ == "agent.heartbeat_restored" and created_at and node_id:
            partner_idx = None
            for j in range(idx + 1, len(ordered)):
                other = ordered[j]
                if j in used:
                    continue
                if _safe_str(other.get("type") or "").strip() != "agent.heartbeat_missed":
                    continue
                other_node = _safe_str(other.get("node_id") or other.get("machine_id") or "").strip()
                if other_node != node_id:
                    continue
                other_ts = _event_time(other)
                if not other_ts:
                    continue
                if created_at - other_ts > pair_window:
                    continue
                partner_idx = j
                break

            if partner_idx is not None:
                missed = ordered[partner_idx]
                used.add(partner_idx)
                missed_ts = _event_time(missed)
                gap_minutes = (created_at - missed_ts).total_seconds() / 60.0 if missed_ts else None
                items.append(
                    {
                        "id": event.get("id"),
                        "level": "success",
                        "type": "agent.heartbeat_pair",
                        "created_at": _safe_str(event.get("created_at") or ""),
                        "relative_time": format_relative_ago(created_at, now=now),
                        "title": f"{node_label or node_id} briefly dropped offline, then recovered",
                        "detail": _recovery_detail(gap_minutes),
                        "node_id": node_id,
                        "node_label": node_label,
                        "badge": "SUCCESS",
                        "tone": "ok",
                    }
                )
                continue

        if typ == "agent.heartbeat_missed" and node_id:
            restored_at = latest_restored.get(node_id)
            if restored_at and created_at and restored_at > created_at and not _node_is_currently_stale(node_id, current_nodes, now=now):
                continue

        title, detail = _format_event_title(event, now=now, current_nodes=current_nodes)
        badge = level.upper()
        tone = "info"
        if level in ("error", "danger", "critical"):
            tone = "bad"
            badge = "ERROR"
        elif level in ("warning", "warn", "degraded"):
            tone = "warn"
            badge = "WARNING"
        elif level in ("success", "ok", "healthy"):
            tone = "ok"
            badge = "SUCCESS"

        items.append(
            {
                "id": event.get("id"),
                "level": level,
                "type": typ or "event",
                "created_at": _safe_str(event.get("created_at") or ""),
                "relative_time": format_relative_ago(created_at, now=now),
                "title": title,
                "detail": detail,
                "node_id": node_id,
                "node_label": node_label,
                "badge": badge,
                "tone": tone,
            }
        )

    return items
