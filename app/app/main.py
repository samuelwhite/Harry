# /opt/harry/brain/app/app/main.py
from __future__ import annotations

import json
import re
import sqlite3
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from fastapi import FastAPI, Request
from starlette.responses import FileResponse, JSONResponse, Response

from app.config import DATA_DIR, DB_PATH
from app.harry_normalise import normalise_for_schema
from app.harry_schema import validate_harry_snapshot
from app.health import compute_health
from app.versions import (
    BRAIN_VERSION,
    AGENT_VERSION,
    SCHEMA_BEHIND_WARN_MIN,
    SCHEMA_BEHIND_CRIT_MIN,
)

# -----------------------------------------------------------------------------
# Path layout
# -----------------------------------------------------------------------------
# We keep these paths explicit and close to startup because Harry is intended
# to be understandable by humans first. The repo structure is part of the
# product's operating model, so making it obvious here is useful.
PKG_DIR = Path(__file__).resolve().parent
PROJECT_DIR = PKG_DIR.parent

DIST_DIR = PROJECT_DIR / "dist"
SCHEMA_DIR = PROJECT_DIR / "schemas"
LOG_DIR = DATA_DIR / "logs"

# Loaded at startup from schemas/harry/current.json.
# This is the schema version the Brain currently expects to receive.
SCHEMA_CURRENT = "unknown"

# Dist health is checked at startup so we can refuse to serve a broken agent.
# This protects auto-updating agents from downloading syntactically invalid
# distributed scripts.
DIST_OK: bool = True
DIST_ERROR: str | None = None

app = FastAPI(title="harry-brain", version=BRAIN_VERSION)

from app.ui import router as ui_router
app.include_router(ui_router)


def _iso_utc_now() -> str:
    """Return a compact ISO8601 UTC timestamp used across logs and responses."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _ensure_log_dir() -> None:
    """Ensure the Brain log directory exists."""
    LOG_DIR.mkdir(parents=True, exist_ok=True)


def _touch_log_files() -> None:
    """
    Create known log files on startup.

    Harry prefers explicit files to "magic" logging destinations because that
    makes troubleshooting easier for small infrastructure environments.
    """
    _ensure_log_dir()
    for name in ("brain.log", "ingest.log", "errors.log"):
        try:
            (LOG_DIR / name).touch(exist_ok=True)
        except Exception:
            pass


def _write_log(filename: str, message: str) -> None:
    """
    Append a single timestamped log line.

    Logging must never be allowed to break the Brain itself. If logging fails,
    Harry should continue to operate rather than crashing over observability.
    """
    try:
        _ensure_log_dir()
        ts = _iso_utc_now()
        with (LOG_DIR / filename).open("a", encoding="utf-8") as fh:
            fh.write(f"{ts} {message}\n")
    except Exception:
        # Never let logging break the app.
        pass


def log_brain(message: str) -> None:
    """Write a Brain/system lifecycle event."""
    _write_log("brain.log", message)


def log_ingest(message: str) -> None:
    """Write a successful ingest event."""
    _write_log("ingest.log", message)


def log_error(message: str) -> None:
    """Write an ingest/normalisation/schema/database error."""
    _write_log("errors.log", message)


def _db():
    """
    Open the SQLite database.

    Harry intentionally uses SQLite because it keeps deployment friction low
    and matches the project's "small, boring, understandable" design goal.
    """
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    return sqlite3.connect(str(DB_PATH))


def _init_db():
    """
    Initialise the ingest table.

    We only persist accepted snapshots. Anything invalid is rejected before it
    reaches storage so the DB remains a trusted source for UI/API reads.
    """
    conn = _db()
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS ingest (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ts TEXT NOT NULL,
            node TEXT NOT NULL,
            payload TEXT NOT NULL
        )
        """
    )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_ingest_node_ts ON ingest(node, ts)")
    conn.commit()
    conn.close()


def _load_current_schema_version() -> str:
    """
    Read the currently active schema version.

    Harry keeps schema versioning file-based so it is obvious, inspectable,
    and easy to reason about outside the application itself.
    """
    p = SCHEMA_DIR / "harry" / "current.json"
    if not p.exists() or not p.is_file():
        return "unknown"
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        return data.get("schema_version") or data.get("contract_version") or "unknown"
    except Exception:
        return "unknown"


def _validate_dist_agent(path: Path) -> Tuple[bool, str | None]:
    """
    Validate the distributed agent before serving it.

    Why validate at serve-time/startup?
    Because Harry agents can self-update from /dist/harry_agent.sh, so the
    Brain must avoid acting as a distribution point for broken scripts.

    Current checks are intentionally simple and operationally useful:
      - file exists
      - file is non-empty
      - no literal tabs (helps avoid heredoc indentation accidents)
      - bash parser accepts it
    """
    try:
        if not path.exists() or not path.is_file():
            return False, "missing"
        if path.stat().st_size <= 0:
            return False, "empty"
        raw = path.read_text(encoding="utf-8", errors="replace")
        if "\t" in raw:
            return False, "contains_tab_characters"
        r = subprocess.run(["bash", "-n", str(path)], capture_output=True, text=True)
        if r.returncode != 0:
            err = (r.stderr or r.stdout or "").strip()
            return False, f"bash_syntax_error: {err[:400]}"
        return True, None
    except Exception as e:
        return False, f"exception: {e}"


@app.on_event("startup")
def _startup():
    """
    Application startup sequence.

    This is intentionally explicit and linear:
      1. ensure logs exist
      2. initialise DB
      3. load schema version
      4. validate distributed agent

    This makes startup behaviour easy to inspect in logs and easier for other
    contributors to modify safely.
    """
    global SCHEMA_CURRENT, DIST_OK, DIST_ERROR

    _touch_log_files()
    log_brain(f"startup begin brain_version={BRAIN_VERSION} agent_version={AGENT_VERSION}")

    try:
        _init_db()
        log_brain(f"db_init ok path={DB_PATH}")
    except Exception as e:
        log_error(f"db_init_failed path={DB_PATH} error={e}")
        raise

    try:
        SCHEMA_CURRENT = _load_current_schema_version()
        log_brain(f"schema_current={SCHEMA_CURRENT}")
    except Exception as e:
        SCHEMA_CURRENT = "unknown"
        log_error(f"schema_load_failed error={e}")

    dist_path = DIST_DIR / "harry_agent.sh"
    ok, err = _validate_dist_agent(dist_path)
    DIST_OK = ok
    DIST_ERROR = err

    if DIST_OK:
        log_brain(f"dist_check ok path={dist_path}")
    else:
        log_error(f"dist_check_failed path={dist_path} error={DIST_ERROR or 'unknown'}")


def _find_schema_file(version: str) -> Path | None:
    """
    Resolve a requested schema file.

    If the exact version is not present, we fall back to current.json rather
    than throwing unexpected internal errors. This keeps schema serving simple.
    """
    base = SCHEMA_DIR / "harry"
    p = base / f"{version}.json"
    if p.exists() and p.is_file():
        return p
    c = base / "current.json"
    if c.exists() and c.is_file():
        return c
    return None


def _render_agent_template(text: str) -> str:
    """
    Stamp version placeholders into the distributed agent at response time.

    This lets the checked-in dist template stay generic while the served agent
    always reflects the Brain's current version contract.
    """
    return (
        text.replace("__HARRY_AGENT_VERSION__", AGENT_VERSION)
        .replace("__HARRY_SCHEMA_VERSION__", SCHEMA_CURRENT)
        .replace("__HARRY_BRAIN_VERSION__", BRAIN_VERSION)
    )


def _parse_ts_utc(s: str) -> Optional[datetime]:
    """Parse a stored ISO UTC timestamp safely."""
    if not s:
        return None
    try:
        if s.endswith("Z"):
            s = s[:-1] + "+00:00"
        return datetime.fromisoformat(s)
    except Exception:
        return None


def _now_utc() -> datetime:
    """Current UTC time helper."""
    return datetime.now(timezone.utc)


def _read_log_lines(path: Path) -> List[str]:
    """
    Read a log file into lines.

    This is used for doctor diagnostics only, so failures should degrade
    gracefully rather than bubbling up as API errors.
    """
    try:
        if not path.exists() or not path.is_file():
            return []
        return path.read_text(encoding="utf-8", errors="replace").splitlines()
    except Exception:
        return []


def _parse_log_line(line: str) -> Optional[Tuple[datetime, str]]:
    """
    Parse a single Harry log line into (timestamp, remainder).

    Log format is:
      2026-03-08T20:12:03Z message...

    If parsing fails we ignore the line. Doctor should be robust against
    partial/corrupt log content.
    """
    try:
        if len(line) < 21:
            return None
        ts_s, rest = line[:20], line[21:]
        ts = datetime.fromisoformat(ts_s.replace("Z", "+00:00"))
        return ts, rest
    except Exception:
        return None


def _extract_kv(rest: str) -> Dict[str, str]:
    """
    Extract simple key=value tokens from a log message.

    This is intentionally lightweight rather than a full parser. Harry log
    lines are designed to remain human-readable first, machine-friendly second.
    """
    out: Dict[str, str] = {}
    for key, value in re.findall(r'([a-zA-Z0-9_]+)=(".*?"|\S+)', rest):
        v = value.strip()
        if len(v) >= 2 and v[0] == '"' and v[-1] == '"':
            v = v[1:-1]
        out[key] = v
    return out


def _error_log_summary(hours: int = 24) -> Dict[str, Any]:
    """
    Summarise recent Brain-side errors from errors.log.

    This currently reflects Brain/ingest/schema/database failures, not remote
    per-node agent-local file logs. That limitation is intentional and honest:
    the Brain should not pretend it knows what it has not ingested or read.
    """
    path = LOG_DIR / "errors.log"
    lines = _read_log_lines(path)
    cutoff = _now_utc() - timedelta(hours=hours)

    total = 0
    last_error: Optional[Dict[str, Any]] = None
    node_failures: Dict[str, int] = {}

    for line in lines:
        parsed = _parse_log_line(line)
        if not parsed:
            continue

        ts, rest = parsed
        if ts < cutoff:
            continue

        total += 1
        kv = _extract_kv(rest)
        node = kv.get("node")
        if node:
            node_failures[node] = node_failures.get(node, 0) + 1

        last_error = {
            "ts": ts.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "message": rest,
            "node": node,
        }

    worst_nodes = sorted(
        [{"node": n, "errors": c} for n, c in node_failures.items()],
        key=lambda x: (-int(x["errors"]), str(x["node"])),
    )

    return {
        "errors_last_24h": total,
        "last_error": last_error,
        "node_failures": worst_nodes[:20],
    }


@app.get("/schema/harry/{version}", response_model=None)
def schema(version: str):
    """Serve a schema file by version."""
    p = _find_schema_file(version)
    if not p:
        return JSONResponse(status_code=404, content={"ok": False, "error": "not_found"})
    return FileResponse(str(p), media_type="application/json")


@app.get("/dist/harry_agent.sh", response_model=None)
def dist_agent_sh():
    """
    Serve the distributed agent script.

    This endpoint refuses to serve a known-invalid dist agent. That is safer
    than blindly returning whatever exists on disk, because agents may update
    themselves from this path.
    """
    global DIST_OK, DIST_ERROR
    if not DIST_OK:
        return JSONResponse(
            status_code=503,
            content={"ok": False, "error": "dist_invalid", "detail": DIST_ERROR or "unknown"},
        )

    p = DIST_DIR / "harry_agent.sh"
    if not p.exists() or not p.is_file():
        return JSONResponse(status_code=404, content={"ok": False, "error": "not_found"})

    raw = p.read_text(encoding="utf-8")
    stamped = _render_agent_template(raw)
    return Response(content=stamped, media_type="text/plain; charset=utf-8")


@app.get("/health", response_model=None)
def health():
    """
    Minimal machine-readable service health.

    /health is intentionally small and boring. Richer diagnostics belong in
    /doctor(.json), so liveness checks remain easy to consume.
    """
    overall_ok = bool(DIST_OK)

    return {
        "ok": overall_ok,
        "brain_version": BRAIN_VERSION,
        "agent_version": AGENT_VERSION,
        "schema_current": SCHEMA_CURRENT,
        "dist_ok": DIST_OK,
        "dist_error": DIST_ERROR,
    }


@app.get("/version", response_model=None)
def version():
    """
    Version contract endpoint.

    This is cleaner than /health for tooling that only wants version
    information and not service/diagnostic state.
    """
    return {
        "brain_version": BRAIN_VERSION,
        "agent_expected": AGENT_VERSION,
        "schema_current": SCHEMA_CURRENT,
    }


@app.get("/api", response_model=None)
def api_root():
    """Small API root summary for quick manual inspection."""
    overall_ok = bool(DIST_OK)

    return {
        "ok": overall_ok,
        "service": "harry-brain",
        "brain_version": BRAIN_VERSION,
        "agent_version": AGENT_VERSION,
        "schema_current": SCHEMA_CURRENT,
        "dist_ok": DIST_OK,
        "dist_error": DIST_ERROR,
    }


def _fetch_latest_payloads(limit_nodes: int = 200) -> List[Dict[str, Any]]:
    """
    Return the most recent payload per node.

    This is used by doctor and API views. We keep it best-effort and tolerant
    of individual bad rows because diagnostics should degrade gracefully.
    """
    q = """
    SELECT i.node, i.ts, i.payload
    FROM ingest i
    JOIN (
        SELECT node, MAX(ts) AS max_ts
        FROM ingest
        GROUP BY node
    ) latest
      ON latest.node = i.node AND latest.max_ts = i.ts
    ORDER BY i.ts DESC
    LIMIT ?
    """
    out: List[Dict[str, Any]] = []
    try:
        conn = _db()
        cur = conn.execute(q, (int(limit_nodes),))
        rows = cur.fetchall()
        conn.close()
    except Exception as e:
        log_error(f"fetch_latest_payloads_failed limit_nodes={limit_nodes} error={e}")
        return out

    for row in rows:
        try:
            node, ts, payload_s = row[0], row[1], row[2]
        except Exception:
            continue

        try:
            payload = json.loads(payload_s)
        except Exception:
            continue

        if not isinstance(payload, dict):
            continue

        payload.setdefault("node", node)
        payload.setdefault("ts", ts)
        out.append(payload)

    return out


def _node_summary(payload: Dict[str, Any], ctx: Dict[str, Any]) -> Dict[str, Any]:
    """
    Shape a single node summary for /nodes.

    /nodes is intended to be an operational endpoint: small, current-state,
    and useful for future UI/API/automation consumers.
    """
    facts = payload.get("facts") if isinstance(payload.get("facts"), dict) else {}
    metrics = payload.get("metrics") if isinstance(payload.get("metrics"), dict) else {}

    try:
        h = compute_health(payload, ctx=ctx)
    except Exception as e:
        h = {"state": "critical", "score": 0, "reasons": [f"health_exception: {e}"], "age_minutes": None}

    # Pick a representative disk percentage for quick fleet display.
    disk_pct: Optional[float] = None
    disk_used = metrics.get("disk_used")
    if isinstance(disk_used, list):
        vals: List[float] = []
        for d in disk_used:
            if not isinstance(d, dict):
                continue
            try:
                v = d.get("used_pct", d.get("pct"))
                if v is not None:
                    vals.append(float(v))
            except Exception:
                continue
        if vals:
            disk_pct = max(vals)

    return {
        "node": payload.get("node", "unknown"),
        "last_seen": payload.get("ts", "unknown"),
        "agent_version": payload.get("agent_version") or "unknown",
        "schema_version": payload.get("schema_version") or payload.get("schema") or "unknown",
        "health": h.get("state", "unknown"),
        "health_score": h.get("score"),
        "health_reasons": h.get("reasons") or [],
        "age_minutes": h.get("age_minutes"),
        "model": facts.get("model"),
        "cpu": facts.get("cpu"),
        "ram_total_gb": facts.get("ram_total_gb"),
        "cpu_load_1m": metrics.get("cpu_load_1m"),
        "ram_used_pct": metrics.get("mem_used_pct"),
        "disk_used_pct": disk_pct,
    }


@app.get("/nodes", response_model=None)
def nodes():
    """
    Current fleet state endpoint.

    This is intentionally different from /inventory:
      - /nodes = operational current state
      - /inventory = hardware export/detail view

    Keeping those concerns separate should make future extensions cleaner.
    """
    payloads = _fetch_latest_payloads(limit_nodes=500)

    ctx = {
        "schema_current": SCHEMA_CURRENT,
        "schema_behind_warn_min": SCHEMA_BEHIND_WARN_MIN,
        "schema_behind_crit_min": SCHEMA_BEHIND_CRIT_MIN,
    }

    rows = [_node_summary(p, ctx=ctx) for p in payloads]
    rows.sort(key=lambda x: (str(x.get("node") or "")))

    return {
        "generated_at": _iso_utc_now(),
        "count": len(rows),
        "nodes": rows,
    }


def _doctor_json() -> Dict[str, Any]:
    """
    Build the richer diagnostics view.

    Doctor is where Harry can be more opinionated and descriptive than /health.
    It combines:
      - service/version state
      - DB reachability
      - latest fleet health
      - recent Brain-side error log summary
    """
    base: Dict[str, Any] = {
        "ok": bool(DIST_OK),
        "service": "harry-brain",
        "brain_version": BRAIN_VERSION,
        "agent_version": AGENT_VERSION,
        "schema_current": SCHEMA_CURRENT,
        "dist_ok": DIST_OK,
        "dist_error": DIST_ERROR,
    }

    try:
        conn = _db()
        conn.execute("SELECT 1")
        conn.close()
        db_ok = True
        db_error = None
    except Exception as e:
        db_ok = False
        db_error = str(e)

    payloads = _fetch_latest_payloads(limit_nodes=500)

    ctx = {
        "schema_current": SCHEMA_CURRENT,
        "schema_behind_warn_min": SCHEMA_BEHIND_WARN_MIN,
        "schema_behind_crit_min": SCHEMA_BEHIND_CRIT_MIN,
    }

    nodes: List[Dict[str, Any]] = []
    worst_state = "healthy"
    worst_score: Optional[int] = None

    for p in payloads:
        try:
            h = compute_health(p, ctx=ctx)
        except Exception as e:
            h = {"state": "critical", "score": 0, "reasons": [f"health_exception: {e}"]}

        state = str(h.get("state") or "healthy")
        try:
            score = int(h.get("score") or 0)
        except Exception:
            score = 0

        if state == "critical":
            worst_state = "critical"
        elif state == "warning" and worst_state != "critical":
            worst_state = "warning"

        if worst_score is None or score < worst_score:
            worst_score = score

        nodes.append(
            {
                "node": p.get("node", "unknown"),
                "ts": p.get("ts", "unknown"),
                "health": h,
            }
        )

    nodes_sorted = sorted(
        nodes,
        key=lambda x: int(((x.get("health") or {}).get("score") or 0)),
    )

    error_summary = _error_log_summary(hours=24)

    overall_ok = bool(DIST_OK) and bool(db_ok) and worst_state != "critical"

    base.update(
        {
            "ok": overall_ok,
            "db_ok": db_ok,
            "db_error": db_error,
            "fleet": {
                "nodes": len(nodes),
                "worst_state": worst_state if nodes else "unknown",
                "worst_score": worst_score if nodes else None,
                "worst_nodes": nodes_sorted[:5],
            },
            "errors": error_summary,
        }
    )
    return base


@app.get("/doctor.json", response_model=None)
def doctor_json():
    """Structured diagnostics for automation or external tooling."""
    return _doctor_json()


@app.get("/doctor", response_model=None)
def doctor():
    """Human-readable diagnostics endpoint."""
    d = _doctor_json()

    lines: List[str] = []
    lines.append("Doctor Harry")
    lines.append("===========")
    lines.append(f"ok: {d.get('ok')}")
    lines.append(f"brain_version: {d.get('brain_version')}")
    lines.append(f"agent_version: {d.get('agent_version')}")
    lines.append(f"schema_current: {d.get('schema_current')}")
    lines.append(f"dist_ok: {d.get('dist_ok')}")
    if not d.get("dist_ok"):
        lines.append(f"dist_error: {d.get('dist_error')}")

    lines.append(f"db_ok: {d.get('db_ok')}")
    if not d.get("db_ok"):
        lines.append(f"db_error: {d.get('db_error')}")

    fleet = d.get("fleet") or {}
    lines.append(f"fleet_nodes: {fleet.get('nodes')}")
    lines.append(f"fleet_worst_state: {fleet.get('worst_state')}")
    lines.append(f"fleet_worst_score: {fleet.get('worst_score')}")

    errors = d.get("errors") or {}
    lines.append(f"errors_last_24h: {errors.get('errors_last_24h', 0)}")

    last_error = errors.get("last_error")
    if isinstance(last_error, dict):
        lines.append(f"last_error_ts: {last_error.get('ts')}")
        lines.append(f"last_error_node: {last_error.get('node') or '—'}")
        lines.append(f"last_error: {last_error.get('message')}")

    node_failures = errors.get("node_failures") or []
    if node_failures:
        lines.append("")
        lines.append("Node failures (last 24h)")
        lines.append("----------------------")
        for item in node_failures[:10]:
            lines.append(f"- {item.get('node')}: {item.get('errors')}")

    worst_nodes = fleet.get("worst_nodes") or []
    if worst_nodes:
        lines.append("")
        lines.append("Worst nodes")
        lines.append("----------")
        for item in worst_nodes:
            n = item.get("node")
            h = item.get("health") or {}
            state = h.get("state")
            score = h.get("score")
            reasons = h.get("reasons") or []
            reason = reasons[0] if reasons else ""
            lines.append(f"- {n}: {state} ({score}) {reason}")

    return Response(content="\n".join(lines) + "\n", media_type="text/plain; charset=utf-8")


@app.post("/ingest", response_model=None)
async def ingest(req: Request):
    """
    Accept a snapshot from an agent.

    Ingest flow is:
      1. parse JSON
      2. normalise to current contract
      3. validate against schema
      4. enrich for local observability
      5. persist

    The order matters:
    we only write trusted, contract-shaped payloads into the DB.
    """
    body = await req.body()
    if not body or not body.strip():
        log_error("ingest_invalid_json reason=empty_body")
        return JSONResponse(status_code=400, content={"ok": False, "error": "invalid_json"})

    try:
        payload = json.loads(body)
    except Exception as e:
        log_error(f"ingest_invalid_json reason=parse_failed error={e}")
        return JSONResponse(status_code=400, content={"ok": False, "error": "invalid_json"})

    try:
        payload = normalise_for_schema(payload, contract_version=SCHEMA_CURRENT)
    except Exception as e:
        log_error(f"ingest_normalise_failed error={e}")
        return JSONResponse(status_code=400, content={"ok": False, "error": "normalise_failed"})

    errors = validate_harry_snapshot(payload)
    if errors:
        node_hint = payload.get("node") or payload.get("facts", {}).get("hostname") or "unknown"
        log_error(
            "ingest_schema_validation_failed "
            f"node={node_hint} details={json.dumps(errors[:10], ensure_ascii=False)}"
        )
        return JSONResponse(
            status_code=400,
            content={"ok": False, "error": "schema_validation_failed", "details": errors[:10]},
        )

    # These enrichments are local/debugging friendly and do not change the
    # schema contract in a breaking way for Harry itself.
    payload.setdefault("agent_version", payload.get("agent_version") or "unknown")
    payload.setdefault("schema_version", payload.get("schema_version") or payload.get("schema") or "unknown")
    payload["schema_current"] = SCHEMA_CURRENT
    payload["brain_version"] = BRAIN_VERSION

    node = payload.get("node") or payload.get("facts", {}).get("hostname") or "unknown"
    ts = payload.get("ts") or _iso_utc_now()

    try:
        conn = _db()
        conn.execute(
            "INSERT INTO ingest(ts, node, payload) VALUES(?, ?, ?)",
            (ts, node, json.dumps(payload, separators=(",", ":"), ensure_ascii=False)),
        )
        conn.commit()
        conn.close()
    except Exception as e:
        log_error(f"ingest_db_insert_failed node={node} ts={ts} error={e}")
        return JSONResponse(status_code=500, content={"ok": False, "error": "db_write_failed"})

    log_ingest(
        f"ingest_accepted node={node} ts={ts} "
        f"agent_version={payload.get('agent_version', 'unknown')} "
        f"schema_version={payload.get('schema_version', 'unknown')}"
    )

    return {"ok": True, "node": node, "ts": ts}
