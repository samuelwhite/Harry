from __future__ import annotations

import json

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, JSONResponse, PlainTextResponse

from .db import (
    DUMP_DEFAULT_HOURS,
    _clamp,
    _db,
    _db_has_ingest,
    _fetch_latest_per_node,
    _utcnow,
    get_dump,
)
from .diagnostics import render_diagnostics_page
from .fleet import render_fleet_page
from .inventory import _inventory_md, build_inventory_rows, render_inventory_page
from .node import render_node_detail

router = APIRouter()


@router.get("/ui/health")
def ui_health() -> PlainTextResponse:
    return PlainTextResponse("ok\n")


@router.get("/inventory", response_class=HTMLResponse)
def inventory_page(request: Request):
    hours_q = request.query_params.get("hours", None)
    try:
        hours = int(hours_q) if hours_q is not None else DUMP_DEFAULT_HOURS
    except Exception:
        hours = DUMP_DEFAULT_HOURS
    hours = int(_clamp(hours, 1, 24 * 14))

    debug = (request.query_params.get("debug") or "").strip().lower() in ("1", "true", "yes", "y")
    fmt = (request.query_params.get("format") or "html").lower().strip()

    with _db() as conn:
        if not _db_has_ingest(conn):
            rows = []
        else:
            latest = _fetch_latest_per_node(conn)
            rows = build_inventory_rows(latest)

    if fmt == "md":
        if not rows:
            return PlainTextResponse("# HARRY — Hardware Inventory\n\n_No ingest data yet._\n", media_type="text/markdown")
        return PlainTextResponse(_inventory_md(rows), media_type="text/markdown")

    return HTMLResponse(render_inventory_page(hours=hours, debug=debug))


@router.get("/inventory.json")
def inventory_json(request: Request) -> JSONResponse:
    hours_q = request.query_params.get("hours", None)
    try:
        hours = int(hours_q) if hours_q is not None else DUMP_DEFAULT_HOURS
    except Exception:
        hours = DUMP_DEFAULT_HOURS
    hours = int(_clamp(hours, 1, 24 * 14))

    with _db() as conn:
        if not _db_has_ingest(conn):
            return JSONResponse(
                {
                    "ok": True,
                    "generated_at": _utcnow().isoformat().replace("+00:00", "Z"),
                    "hours": hours,
                    "nodes": [],
                },
                status_code=200,
            )

        latest = _fetch_latest_per_node(conn)
        rows = build_inventory_rows(latest)

    return JSONResponse(
        {
            "ok": True,
            "generated_at": _utcnow().isoformat().replace("+00:00", "Z"),
            "hours": hours,
            "nodes": rows,
        }
    )


@router.get("/", response_class=HTMLResponse)
def index(request: Request) -> HTMLResponse:
    hours_q = request.query_params.get("hours", None)
    try:
        hours = int(hours_q) if hours_q is not None else DUMP_DEFAULT_HOURS
    except Exception:
        hours = DUMP_DEFAULT_HOURS
    hours = int(_clamp(hours, 1, 24 * 14))

    debug = (request.query_params.get("debug") or "").strip().lower() in ("1", "true", "yes", "y")
    return HTMLResponse(render_fleet_page(hours=hours, debug=debug))


@router.get("/diagnostics", response_class=HTMLResponse)
def diagnostics(request: Request) -> HTMLResponse:
    hours_q = request.query_params.get("hours", None)
    try:
        hours = int(hours_q) if hours_q is not None else DUMP_DEFAULT_HOURS
    except Exception:
        hours = DUMP_DEFAULT_HOURS
    hours = int(_clamp(hours, 1, 24 * 14))

    debug = (request.query_params.get("debug") or "").strip().lower() in ("1", "true", "yes", "y")
    return HTMLResponse(render_diagnostics_page(hours=hours, debug=debug))


@router.get("/debug/latest/{node}")
def debug_latest(node: str) -> JSONResponse:
    node = node.strip()
    with _db() as conn:
        cur = conn.execute("SELECT ts, node, payload FROM ingest WHERE node = ? ORDER BY ts DESC LIMIT 1", (node,))
        row = cur.fetchone()
        if not row:
            return JSONResponse({"ok": False, "error": "not_found", "node": node}, status_code=404)
        try:
            payload = json.loads(row["payload"])
        except Exception:
            payload = {"bad_payload": True, "raw": row["payload"]}
        return JSONResponse({"node": row["node"], "ts": row["ts"], "payload": payload})


@router.get("/dump")
def dump(hours: int = DUMP_DEFAULT_HOURS) -> JSONResponse:
    return JSONResponse(get_dump(hours=hours))


@router.get("/node/{node}", response_class=HTMLResponse)
def node_detail(request: Request, node: str) -> HTMLResponse:
    hours_q = request.query_params.get("hours", None)
    try:
        hours = int(hours_q) if hours_q is not None else DUMP_DEFAULT_HOURS
    except Exception:
        hours = DUMP_DEFAULT_HOURS
    hours = int(_clamp(hours, 1, 24 * 14))

    return HTMLResponse(render_node_detail(node=node.strip(), hours=hours))

