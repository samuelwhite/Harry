# /opt/harry/brain/app/app/main.py
from __future__ import annotations

import json
import re
import sqlite3
import subprocess
import sys
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

PKG_DIR = Path(__file__).resolve().parent

if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
    PROJECT_DIR = Path(sys._MEIPASS)
else:
    PROJECT_DIR = PKG_DIR.parent

DIST_DIR = PROJECT_DIR / "dist"
SCHEMA_DIR = PROJECT_DIR / "schemas"
LOG_DIR = DATA_DIR / "logs"

SCHEMA_CURRENT = "unknown"
DIST_OK: bool = True
DIST_ERROR: str | None = None

app = FastAPI(title="harry-brain", version=BRAIN_VERSION)

from app.ui import router as ui_router
app.include_router(ui_router)


def _iso_utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _ensure_log_dir() -> None:
    LOG_DIR.mkdir(parents=True, exist_ok=True)


def _touch_log_files() -> None:
    _ensure_log_dir()
    for name in ("brain.log", "ingest.log", "errors.log"):
        try:
            (LOG_DIR / name).touch(exist_ok=True)
        except Exception:
            pass


def _write_log(filename: str, message: str) -> None:
    try:
        _ensure_log_dir()
        ts = _iso_utc_now()
        with (LOG_DIR / filename).open("a", encoding="utf-8") as fh:
            fh.write(f"{ts} {message}\n")
    except Exception:
        pass


def log_brain(message: str) -> None:
    _write_log("brain.log", message)


def log_ingest(message: str) -> None:
    _write_log("ingest.log", message)


def log_error(message: str) -> None:
    _write_log("errors.log", message)


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


def _parse_ts_utc(s: str) -> Optional[datetime]:
    if not s:
        return None
    try:
        if s.endswith("Z"):
            s = s[:-1] + "+00:00"
        return datetime.fromisoformat(s)
    except Exception:
        return None


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _read_log_lines(path: Path) -> List[str]:
    try:
        if not path.exists() or not path.is_file():
            return []
        return path.read_text(encoding="utf-8", errors="replace").splitlines()
    except Exception:
        return []


def _parse_log_line(line: str) -> Optional[Tuple[datetime, str]]:
    try:
        if len(line) < 21:
            return None
        ts_s, rest = line[:20], line[21:]
        ts = datetime.fromisoformat(ts_s.replace("Z", "+00:00"))
        return ts, rest
    except Exception:
        return None


def _extract_kv(rest: str) -> Dict[str, str]:
    out: Dict[str, str] = {}
    for key, value in re.findall(r'([a-zA-Z0-9_]+)=(".*?"|\S+)', rest):
        v = value.strip()
        if len(v) >= 2 and v[0] == '"' and v[-1] == '"':
            v = v[1:-1]
        out[key] = v
    return out


def _error_log_summary(hours: int = 24) -> Dict[str, Any]:
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


def _agent_status_view(payload: Dict[str, Any]) -> Dict[str, Any]:
    raw = payload.get("agent_status")
    if not isinstance(raw, dict):
        raw = {}

    return {
        "state": raw.get("state") or ("healthy" if raw.get("ok") is True else "unknown"),
        "stage": raw.get("stage"),
        "ok": raw.get("ok"),
        "error_code": raw.get("error_code"),
        "error_summary": raw.get("error_summary"),
        "consecutive_failures": raw.get("consecutive_failures"),
        "last_run_at": raw.get("last_run_at"),
        "last_success_at": raw.get("last_success_at"),
        "last_error_at": raw.get("last_error_at"),
    }


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


@app.get("/version", response_model=None)
def version():
    return {
        "brain_version": BRAIN_VERSION,
        "agent_expected": AGENT_VERSION,
        "schema_current": SCHEMA_CURRENT,
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
    facts = payload.get("facts") if isinstance(payload.get("facts"), dict) else {}
    metrics = payload.get("metrics") if isinstance(payload.get("metrics"), dict) else {}

    try:
        h = compute_health(payload, ctx=ctx)
    except Exception as e:
        h = {"state": "critical", "score": 0, "reasons": [f"health_exception: {e}"], "age_minutes": None}

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
        "agent_status": _agent_status_view(payload),
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
    agent_issues: List[Dict[str, Any]] = []

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

        agent_status = _agent_status_view(p)
        agent_state = str(agent_status.get("state") or "unknown").lower()

        if agent_state in ("error", "degraded", "bootstrapping"):
            sev = "critical" if agent_state == "error" else "warning"
            if sev == "critical":
                worst_state = "critical"

            agent_issues.append(
                {
                    "node": p.get("node", "unknown"),
                    "severity": sev,
                    "state": agent_state,
                    "stage": agent_status.get("stage"),
                    "error_code": agent_status.get("error_code"),
                    "error_summary": agent_status.get("error_summary"),
                    "consecutive_failures": agent_status.get("consecutive_failures"),
                    "last_error_at": agent_status.get("last_error_at"),
                    "last_success_at": agent_status.get("last_success_at"),
                }
            )

        nodes.append(
            {
                "node": p.get("node", "unknown"),
                "ts": p.get("ts", "unknown"),
                "health": h,
                "agent_status": agent_status,
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
            "agent": {
                "issues": agent_issues[:20],
                "critical": sum(1 for x in agent_issues if x.get("severity") == "critical"),
                "warning": sum(1 for x in agent_issues if x.get("severity") == "warning"),
            },
            "errors": error_summary,
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

    agent = d.get("agent") or {}
    lines.append(f"agent_critical: {agent.get('critical', 0)}")
    lines.append(f"agent_warning: {agent.get('warning', 0)}")

    errors = d.get("errors") or {}
    lines.append(f"errors_last_24h: {errors.get('errors_last_24h', 0)}")

    last_error = errors.get("last_error")
    if isinstance(last_error, dict):
        lines.append(f"last_error_ts: {last_error.get('ts')}")
        lines.append(f"last_error_node: {last_error.get('node') or '—'}")
        lines.append(f"last_error: {last_error.get('message')}")

    agent_issues = agent.get("issues") or []
    if agent_issues:
        lines.append("")
        lines.append("Agent issues")
        lines.append("------------")
        for item in agent_issues[:10]:
            lines.append(
                f"- {item.get('node')}: {item.get('state')} "
                f"(stage={item.get('stage')}, failures={item.get('consecutive_failures')}, "
                f"error={item.get('error_summary') or '—'})"
            )

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
