from __future__ import annotations

import json
import os
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

PKG_DIR = Path(__file__).resolve().parent.parent
PROJECT_DIR = PKG_DIR.parent
SCHEMA_CURRENT_FILE = PROJECT_DIR / "schemas" / "harry" / "current.json"

DB_PATH = os.environ.get("HARRY_DB_PATH", "/data/harry.db")
STALE_SECONDS = int(os.environ.get("HARRY_STALE_SECONDS", "3600"))
DUMP_DEFAULT_HOURS = int(os.environ.get("HARRY_DUMP_HOURS", "72"))
MAX_NODES = int(os.environ.get("HARRY_MAX_NODES", "200"))
MAX_HISTORY_ROWS = int(os.environ.get("HARRY_MAX_HISTORY_ROWS", "800"))


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _parse_ts(s: str) -> Optional[datetime]:
    if not s:
        return None
    try:
        if s.endswith("Z"):
            s = s[:-1] + "+00:00"
        return datetime.fromisoformat(s)
    except Exception:
        return None


def _clamp(n: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, n))


def _fnum(v: Any) -> Optional[float]:
    try:
        if v is None:
            return None
        if isinstance(v, str):
            s = v.strip()
            if s.endswith("%"):
                s = s[:-1].strip()
            return float(s)
        return float(v)
    except Exception:
        return None


def _safe_str(v: Any) -> str:
    return "" if v is None else str(v)


def _load_schema_current() -> str:
    try:
        if not SCHEMA_CURRENT_FILE.exists() or not SCHEMA_CURRENT_FILE.is_file():
            return "unknown"
        data = json.loads(SCHEMA_CURRENT_FILE.read_text(encoding="utf-8"))
        return data.get("schema_version") or data.get("contract_version") or "unknown"
    except Exception:
        return "unknown"


def _ensure_hidden_nodes_table(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS hidden_nodes (
            node TEXT PRIMARY KEY,
            hidden_at TEXT NOT NULL
        )
        """
    )
    conn.commit()


def _ensure_acknowledged_recommendations_table(conn: sqlite3.Connection) -> None:
    try:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS acknowledged_recommendations (
                node TEXT NOT NULL,
                advice_key TEXT NOT NULL,
                acknowledged_at TEXT NOT NULL,
                reason TEXT,
                expires_at TEXT,
                PRIMARY KEY (node, advice_key)
            )
            """
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_acknowledged_recommendations_node ON acknowledged_recommendations(node)"
        )
        conn.commit()
    except Exception:
        # If the database path is read-only or otherwise unavailable, keep
        # rendering and read-only behavior working. Acknowledgements will only
        # persist once the Brain has a writable local DB.
        pass


def _ensure_events_table(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            created_at TEXT NOT NULL,
            level TEXT NOT NULL,
            type TEXT NOT NULL,
            title TEXT NOT NULL,
            message TEXT NOT NULL,
            node_id TEXT,
            machine_id TEXT,
            metadata TEXT
        )
        """
    )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_events_created_at ON events(created_at DESC)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_events_node_created_at ON events(node_id, created_at DESC)")
    conn.commit()


def _db() -> sqlite3.Connection:
    db_path = Path(DB_PATH)
    db_path.parent.mkdir(parents=True, exist_ok=True)

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    _ensure_hidden_nodes_table(conn)
    _ensure_acknowledged_recommendations_table(conn)
    _ensure_events_table(conn)
    return conn


def _db_has_ingest(conn: sqlite3.Connection) -> bool:
    try:
        cur = conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='ingest'")
        return cur.fetchone() is not None
    except Exception:
        return False


def _fetch_latest_per_node(conn: sqlite3.Connection) -> Dict[str, Dict[str, Any]]:
    out: Dict[str, Dict[str, Any]] = {}
    q = """
    SELECT i1.*
    FROM ingest i1
    JOIN (
      SELECT node, MAX(ts) AS max_ts
      FROM ingest
      GROUP BY node
    ) latest
      ON i1.node = latest.node AND i1.ts = latest.max_ts
    LEFT JOIN hidden_nodes h
      ON i1.node = h.node
    WHERE h.node IS NULL
    ORDER BY i1.node ASC
    LIMIT ?
    """
    for row in conn.execute(q, (MAX_NODES,)):
        try:
            payload = json.loads(row["payload"])
        except Exception:
            payload = {"node": row["node"], "ts": row["ts"], "bad_payload": True, "raw": row["payload"]}
        out[row["node"]] = {"ts": row["ts"], "payload": payload, "row_id": row["id"]}
    return out


def _fetch_latest_hidden_per_node(conn: sqlite3.Connection) -> Dict[str, Dict[str, Any]]:
    out: Dict[str, Dict[str, Any]] = {}
    q = """
    SELECT i1.*, h.hidden_at
    FROM ingest i1
    JOIN (
      SELECT node, MAX(ts) AS max_ts
      FROM ingest
      GROUP BY node
    ) latest
      ON i1.node = latest.node AND i1.ts = latest.max_ts
    JOIN hidden_nodes h
      ON i1.node = h.node
    ORDER BY i1.node ASC
    LIMIT ?
    """
    for row in conn.execute(q, (MAX_NODES,)):
        try:
            payload = json.loads(row["payload"])
        except Exception:
            payload = {"node": row["node"], "ts": row["ts"], "bad_payload": True, "raw": row["payload"]}
        out[row["node"]] = {
            "ts": row["ts"],
            "payload": payload,
            "row_id": row["id"],
            "hidden_at": row["hidden_at"],
        }
    return out


def _fetch_acknowledged_recommendations(conn: sqlite3.Connection, node: str | None = None) -> List[Dict[str, Any]]:
    q = """
    SELECT node, advice_key, acknowledged_at, reason, expires_at
    FROM acknowledged_recommendations
    """
    params: tuple[Any, ...] = ()
    if node:
        q += " WHERE node = ?"
        params = (node,)
    q += " ORDER BY acknowledged_at DESC, node ASC, advice_key ASC"

    rows = conn.execute(q, params).fetchall()
    out: List[Dict[str, Any]] = []
    for row in rows:
        out.append(
            {
                "node": row["node"],
                "advice_key": row["advice_key"],
                "acknowledged_at": row["acknowledged_at"],
                "reason": row["reason"],
                "expires_at": row["expires_at"],
            }
        )
    return out


def _fetch_history(conn: sqlite3.Connection, node: str, hours: int, limit: int = MAX_HISTORY_ROWS) -> List[Dict[str, Any]]:
    since = (_utcnow() - timedelta(hours=hours)).strftime("%Y-%m-%dT%H:%M:%SZ")
    q = """
    SELECT ts, payload
    FROM ingest
    WHERE node = ? AND ts >= ?
    ORDER BY ts ASC
    LIMIT ?
    """
    out: List[Dict[str, Any]] = []
    for row in conn.execute(q, (node, since, limit)):
        try:
            payload = json.loads(row["payload"])
        except Exception:
            continue
        out.append({"ts": row["ts"], "payload": payload})
    return out


def _raw_payload(p: Dict[str, Any]) -> Dict[str, Any]:
    ex = p.get("extensions")
    if isinstance(ex, dict):
        raw = ex.get("raw")
        if isinstance(raw, dict):
            return raw
    return {}


def _get_facts(p: Dict[str, Any]) -> Dict[str, Any]:
    facts = p.get("facts")
    return facts if isinstance(facts, dict) else {}


def _get_metrics(p: Dict[str, Any]) -> Dict[str, Any]:
    metrics = p.get("metrics")
    return metrics if isinstance(metrics, dict) else {}


def _event_row(row: sqlite3.Row) -> Dict[str, Any]:
    metadata = {}
    try:
        raw = row["metadata"]
        if raw:
            parsed = json.loads(raw)
            if isinstance(parsed, dict):
                metadata = parsed
    except Exception:
        metadata = {}

    return {
        "id": row["id"],
        "created_at": row["created_at"],
        "level": row["level"],
        "type": row["type"],
        "title": row["title"],
        "message": row["message"],
        "node_id": row["node_id"],
        "machine_id": row["machine_id"],
        "metadata": metadata,
    }


def _insert_event(
    conn: sqlite3.Connection,
    *,
    created_at: Optional[str] = None,
    level: str,
    type: str,
    title: str,
    message: str,
    node_id: Optional[str] = None,
    machine_id: Optional[str] = None,
    metadata: Optional[Dict[str, Any]] = None,
) -> int:
    payload = json.dumps(metadata or {}, separators=(",", ":"), ensure_ascii=False)
    ts = created_at or _utcnow().isoformat().replace("+00:00", "Z")
    cur = conn.execute(
        """
        INSERT INTO events(created_at, level, type, title, message, node_id, machine_id, metadata)
        VALUES(?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (ts, level, type, title, message, node_id, machine_id, payload),
    )
    return int(cur.lastrowid or 0)


def record_event(
    *,
    level: str,
    type: str,
    title: str,
    message: str,
    node_id: Optional[str] = None,
    machine_id: Optional[str] = None,
    metadata: Optional[Dict[str, Any]] = None,
    created_at: Optional[str] = None,
) -> int:
    with _db() as conn:
        event_id = _insert_event(
            conn,
            created_at=created_at,
            level=level,
            type=type,
            title=title,
            message=message,
            node_id=node_id,
            machine_id=machine_id,
            metadata=metadata,
        )
        conn.commit()
        return event_id


def _get_latest_event_for_node_type(conn: sqlite3.Connection, node_id: str, type: str) -> Optional[Dict[str, Any]]:
    cur = conn.execute(
        """
        SELECT id, created_at, level, type, title, message, node_id, machine_id, metadata
        FROM events
        WHERE node_id = ? AND type = ?
        ORDER BY created_at DESC, id DESC
        LIMIT 1
        """,
        (node_id, type),
    )
    row = cur.fetchone()
    return _event_row(row) if row else None


def _sync_offline_events(conn: sqlite3.Connection) -> None:
    latest = _fetch_latest_per_node(conn)
    now = _utcnow()

    for node, rec in latest.items():
        ts = _parse_ts(rec.get("ts") or "")
        if not ts:
            continue

        age_seconds = (now - ts).total_seconds()
        if age_seconds < STALE_SECONDS:
            continue

        existing = _get_latest_event_for_node_type(conn, node, "agent.heartbeat_missed")
        if existing:
            existing_ts = _parse_ts(existing.get("created_at") or "")
            if existing_ts and existing_ts >= ts:
                continue

        age_minutes = int(age_seconds // 60)
        message = f"Missed heartbeat for about {age_minutes}m."
        _insert_event(
            conn,
            level="warning",
            type="agent.heartbeat_missed",
            title="Agent missed heartbeat",
            message=message,
            node_id=node,
            metadata={"age_seconds": int(age_seconds), "latest_report_at": rec.get("ts")},
        )
    conn.commit()


def get_recent_events(limit: int = 50, sync_stale: bool = True) -> List[Dict[str, Any]]:
    limit = max(1, min(int(limit or 50), 500))
    with _db() as conn:
        if sync_stale:
            try:
                _sync_offline_events(conn)
            except Exception:
                pass

        rows = conn.execute(
            """
            SELECT id, created_at, level, type, title, message, node_id, machine_id, metadata
            FROM events
            ORDER BY created_at DESC, id DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
        return [_event_row(row) for row in rows]


def get_latest_node_records() -> Dict[str, Dict[str, Any]]:
    with _db() as conn:
        if not _db_has_ingest(conn):
            return {}
        return _fetch_latest_per_node(conn)


def get_latest_hidden_node_records() -> Dict[str, Dict[str, Any]]:
    with _db() as conn:
        if not _db_has_ingest(conn):
            return {}
        return _fetch_latest_hidden_per_node(conn)


def get_latest_node_record(node: str):
    with _db() as conn:
        cur = conn.execute(
            "SELECT ts, node, payload FROM ingest WHERE node = ? ORDER BY ts DESC LIMIT 1",
            (node,),
        )
        return cur.fetchone()


def hide_node(node: str) -> None:
    node = (node or "").strip()
    if not node:
        return
    with _db() as conn:
        conn.execute(
            """
            INSERT INTO hidden_nodes (node, hidden_at)
            VALUES (?, ?)
            ON CONFLICT(node) DO UPDATE SET hidden_at = excluded.hidden_at
            """,
            (node, _utcnow().isoformat().replace("+00:00", "Z")),
        )
        conn.commit()


def unhide_node(node: str) -> None:
    node = (node or "").strip()
    if not node:
        return
    with _db() as conn:
        conn.execute("DELETE FROM hidden_nodes WHERE node = ?", (node,))
        conn.commit()


def delete_node(node: str) -> None:
    node = (node or "").strip()
    if not node:
        return
    with _db() as conn:
        conn.execute("DELETE FROM hidden_nodes WHERE node = ?", (node,))
        conn.execute("DELETE FROM acknowledged_recommendations WHERE node = ?", (node,))
        if _db_has_ingest(conn):
            conn.execute("DELETE FROM ingest WHERE node = ?", (node,))
        conn.commit()


def acknowledge_recommendation(
    node: str,
    advice_key: str,
    *,
    reason: Optional[str] = None,
    expires_at: Optional[str] = None,
) -> None:
    node = (node or "").strip()
    advice_key = (advice_key or "").strip()
    if not node or not advice_key:
        return
    with _db() as conn:
        conn.execute(
            """
            INSERT INTO acknowledged_recommendations (node, advice_key, acknowledged_at, reason, expires_at)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(node, advice_key) DO UPDATE SET
                acknowledged_at = excluded.acknowledged_at,
                reason = excluded.reason,
                expires_at = excluded.expires_at
            """,
            (node, advice_key, _utcnow().isoformat().replace("+00:00", "Z"), reason, expires_at),
        )
        conn.commit()


def restore_recommendation(node: str, advice_key: str) -> None:
    node = (node or "").strip()
    advice_key = (advice_key or "").strip()
    if not node or not advice_key:
        return
    with _db() as conn:
        conn.execute(
            "DELETE FROM acknowledged_recommendations WHERE node = ? AND advice_key = ?",
            (node, advice_key),
        )
        conn.commit()


def get_acknowledged_recommendation_keys(node: str) -> set[str]:
    node = (node or "").strip()
    if not node:
        return set()
    try:
        with _db() as conn:
            rows = _fetch_acknowledged_recommendations(conn, node)
        return {str(row["advice_key"]) for row in rows if row.get("advice_key")}
    except Exception:
        return set()


def get_acknowledged_recommendations(node: str | None = None) -> List[Dict[str, Any]]:
    try:
        with _db() as conn:
            rows = _fetch_acknowledged_recommendations(conn, node)
        return rows
    except Exception:
        return []


def get_dump(hours: int = DUMP_DEFAULT_HOURS) -> Dict[str, Any]:
    hours = int(_clamp(hours, 1, 24 * 30))
    with _db() as conn:
        latest = _fetch_latest_per_node(conn)
        nodes: Dict[str, Any] = {}
        for node, rec in latest.items():
            hist = _fetch_history(conn, node, hours=hours, limit=500)
            nodes[node] = {"latest": rec, "history": hist}
        return {"generated_at": _utcnow().isoformat().replace("+00:00", "Z"), "hours": hours, "nodes": nodes}
