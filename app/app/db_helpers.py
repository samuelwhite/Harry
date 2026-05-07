from __future__ import annotations

import json
import os
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

import app.config as config

STALE_SECONDS = int(os.environ.get("HARRY_STALE_SECONDS", "3600"))
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


def _db_path() -> Path:
    return Path(os.environ.get("HARRY_DB_PATH") or config.DB_PATH)


def _db() -> sqlite3.Connection:
    db_path = _db_path()
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
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
