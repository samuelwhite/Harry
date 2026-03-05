# /opt/harry/brain/app/app/main.py
from __future__ import annotations

import json
import sqlite3
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from fastapi import FastAPI, Request
from starlette.responses import FileResponse, JSONResponse, Response

from app.config import DATA_DIR, DB_PATH
from app.harry_normalise import normalise_for_schema
from app.harry_schema import validate_harry_snapshot
from app.health import compute_health

PKG_DIR = Path(__file__).resolve().parent
PROJECT_DIR = PKG_DIR.parent

DIST_DIR = PROJECT_DIR / "dist"
SCHEMA_DIR = PROJECT_DIR / "schemas"

# Versions: single source of truth
BRAIN_VERSION = "2026.03.1"  # brain patch release
AGENT_VERSION = "0.2.3"      # dist agent release (stamped into dist)
SCHEMA_CURRENT = "unknown"   # read at startup

# Dist health (set at startup)
DIST_OK: bool = True
DIST_ERROR: str | None = None

app = FastAPI(title="harry-brain", version=BRAIN_VERSION)

from app.ui import router as ui_router
app.include_router(ui_router)

def _db():
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    return sqlite3.connect(str(DB_PATH))


def _init_db():
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
    Validate dist agent before serving it:
      - exists + non-empty
      - no literal tabs (helps avoid python heredoc tab landmines)
      - bash parses (bash -n)
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
    global SCHEMA_CURRENT, DIST_OK, DIST_ERROR
    _init_db()
    SCHEMA_CURRENT = _load_current_schema_version()

    dist_path = DIST_DIR / "harry_agent.sh"
    ok, err = _validate_dist_agent(dist_path)
    DIST_OK = ok
    DIST_ERROR = err


def _iso_utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _find_schema_file(version: str) -> Path | None:
    base = SCHEMA_DIR / "harry"
    p = base / f"{version}.json"
    if p.exists() and p.is_file():
        return p
    c = base / "current.json"
    if c.exists() and c.is_file():
        return c
    return None


def _render_agent_template(text: str) -> str:
    return (
        text.replace("__HARRY_AGENT_VERSION__", AGENT_VERSION)
            .replace("__HARRY_SCHEMA_VERSION__", SCHEMA_CURRENT)
            .replace("__HARRY_BRAIN_VERSION__", BRAIN_VERSION)
    )


@app.get("/schema/harry/{version}", response_model=None)
def schema(version: str):
    p = _find_schema_file(version)
    if not p:
        return JSONResponse(status_code=404, content={"ok": False, "error": "not_found"})
    return FileResponse(str(p), media_type="application/json")


@app.get("/dist/harry_agent.sh", response_model=None)
def dist_agent_sh():
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
    overall_ok = bool(DIST_OK)

    return {
        "ok": overall_ok,
        "brain_version": BRAIN_VERSION,
        "agent_version": AGENT_VERSION,
        "schema_current": SCHEMA_CURRENT,
        "dist_ok": DIST_OK,
        "dist_error": DIST_ERROR,
    }


@app.get("/api", response_model=None)
def api_root():
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
    Return most recent payload per node (best-effort).
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
    except Exception:
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

        # Ensure ts/node are present for compute_health()
        payload.setdefault("node", node)
        payload.setdefault("ts", ts)
        out.append(payload)

    return out


def _doctor_json() -> Dict[str, Any]:
    # Core service status (like /health, but doctor can be richer)
    base: Dict[str, Any] = {
        "ok": bool(DIST_OK),
        "service": "harry-brain",
        "brain_version": BRAIN_VERSION,
        "agent_version": AGENT_VERSION,
        "schema_current": SCHEMA_CURRENT,
        "dist_ok": DIST_OK,
        "dist_error": DIST_ERROR,
    }

    # DB quick check
    try:
        conn = _db()
        conn.execute("SELECT 1")
        conn.close()
        db_ok = True
        db_error = None
    except Exception as e:
        db_ok = False
        db_error = str(e)

    # Fleet view (latest snapshot per node)
    payloads = _fetch_latest_payloads(limit_nodes=500)

    # Compute health per node
    ctx = {
        "schema_current": SCHEMA_CURRENT,
        "schema_behind_warn_min": 15,
        "schema_behind_crit_min": 60,
    }

    nodes: List[Dict[str, Any]] = []
    worst_state = "healthy"
    worst_score: Optional[int] = None

    for p in payloads:
        try:
            h = compute_health(p, ctx=ctx)
        except Exception as e:
            h = {"state": "critical", "score": 0, "reasons": [f"health_exception: {e}"]}

        # normalise
        state = str(h.get("state") or "healthy")
        try:
            score = int(h.get("score") or 0)
        except Exception:
            score = 0

        # Aggregate worst state
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

    # Sort nodes worst-first (lowest score)
    nodes_sorted = sorted(
        nodes,
        key=lambda x: int(((x.get("health") or {}).get("score") or 0)),
    )

    # Overall ok policy:
    # - dist must be ok
    # - db must be ok
    # - fleet worst state must not be critical
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
        }
    )
    return base


@app.get("/doctor.json", response_model=None)
def doctor_json():
    return _doctor_json()


@app.get("/doctor", response_model=None)
def doctor():
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
    body = await req.body()
    if not body or not body.strip():
        return JSONResponse(status_code=400, content={"ok": False, "error": "invalid_json"})

    try:
        payload = json.loads(body)
    except Exception:
        return JSONResponse(status_code=400, content={"ok": False, "error": "invalid_json"})

    payload = normalise_for_schema(payload, contract_version=SCHEMA_CURRENT)

    errors = validate_harry_snapshot(payload)
    if errors:
        return JSONResponse(
            status_code=400,
            content={"ok": False, "error": "schema_validation_failed", "details": errors[:10]},
        )

    # Enrich for UI/debugging (non-breaking)
    payload.setdefault("agent_version", payload.get("agent_version") or "unknown")
    payload.setdefault("schema_version", payload.get("schema_version") or payload.get("schema") or "unknown")
    payload["schema_current"] = SCHEMA_CURRENT
    payload["brain_version"] = BRAIN_VERSION

    node = payload.get("node") or payload.get("facts", {}).get("hostname") or "unknown"
    ts = payload.get("ts") or _iso_utc_now()

    conn = _db()
    conn.execute(
        "INSERT INTO ingest(ts, node, payload) VALUES(?, ?, ?)",
        (ts, node, json.dumps(payload, separators=(",", ":"), ensure_ascii=False)),
    )
    conn.commit()
    conn.close()

    return {"ok": True, "node": node, "ts": ts}


try:
    from app.ui import router as ui_router
    app.include_router(ui_router)
except Exception as e:
    print("UI failed to load:", e)
