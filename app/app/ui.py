# /opt/harry/brain/app/app/ui.py
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, PlainTextResponse

router = APIRouter()

import json
import os
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from app.rules import evaluate as rules_evaluate
from app.health import compute_health
from app.versions import BRAIN_VERSION, AGENT_VERSION

# Prefer the newer advice engine if available
try:
    from app.advice_engine import build_advice_and_health as advice_build
except Exception:  # pragma: no cover
    advice_build = None


PKG_DIR = Path(__file__).resolve().parent
PROJECT_DIR = PKG_DIR.parent
SCHEMA_CURRENT_FILE = PROJECT_DIR / "schemas" / "harry" / "current.json"

# UI CSS extracted to avoid f-string brace issues
CSS = """
:root {
  --bgA: #0b1220;
  --bgB: #0a1830;
  --bgC: #0b1a2b;
  --stroke: rgba(255,255,255,0.12);
  --text: rgba(255,255,255,0.92);
  --muted: rgba(255,255,255,0.62);

  --ok: #34d399;
  --warn: #fbbf24;
  --bad: #fb7185;
  --stale: #fb7185;
}

* { box-sizing: border-box; }

html, body {
  margin: 0;
  padding: 0;
  overflow-x: hidden;
}

body {
  padding: 18px 18px 30px;
  font-family: ui-sans-serif, system-ui, -apple-system, Segoe UI, Roboto, Helvetica, Arial;
  background:
    radial-gradient(900px 700px at 20% 18%, rgba(90,110,255,0.24), rgba(10,18,32,0.0) 60%),
    radial-gradient(900px 700px at 82% 10%, rgba(120,70,255,0.18), rgba(10,18,32,0.0) 55%),
    radial-gradient(900px 700px at 60% 92%, rgba(0,210,255,0.10), rgba(10,18,32,0.0) 55%),
    linear-gradient(180deg, var(--bgB) 0%, var(--bgA) 48%, #070b14 100%);
  color: var(--text);
}

a { color: inherit; text-decoration: none; }
a:hover { text-decoration: underline; }

.page {
  width: 100%;
  max-width: 1400px;
  margin: 0 auto;
  padding: 0;
}

.h1 { font-size: 26px; font-weight: 800; margin: 0 0 6px; }
.sub { color: var(--muted); font-size: 12.5px; margin: 0 0 14px; display:flex; gap:12px; flex-wrap:wrap; }

/* --- Strong section headers (vNext polish) --- */
.section { margin: 14px 0 18px; }
.sectionhead {
  display:flex;
  justify-content:space-between;
  align-items:flex-end;
  gap: 12px;
  flex-wrap: wrap;
  margin: 0 0 10px;
}
.h2 { font-size: 16.5px; font-weight: 950; letter-spacing: 0.25px; margin: 0; }
.h2sub { margin: 4px 0 0; color: var(--muted); font-size: 12.5px; font-style: italic; }
.divider { height: 1px; background: rgba(255,255,255,0.08); margin: 12px 0 16px; }

/* Top nav chips */
.navchips { display:flex; gap:10px; flex-wrap:wrap; margin: 10px 0 12px; }
.chip {
  display:inline-flex; align-items:center; gap:8px;
  padding:7px 10px; border-radius:999px;
  border:1px solid var(--stroke);
  background: rgba(255,255,255,0.05);
  font-size:12px;
}
.chip:hover { background: rgba(255,255,255,0.09); }
.chip .tiny { color: rgba(255,255,255,0.62); font-weight: 700; }

.topwarnwrap { display:flex; flex-wrap:wrap; gap:10px; margin: 10px 0 16px; }
.topwarn {
  font-size: 12.5px; padding: 9px 12px; border-radius: 999px;
  border: 1px solid var(--stroke); background: rgba(255,255,255,0.05);
  box-shadow: 0 10px 30px rgba(0,0,0,0.30);
}
.topwarn.bad, .topwarn.stale {
  border-color: rgba(251, 113, 133, 0.35);
  background: rgba(251, 113, 133, 0.12);
}
.topwarn.warn {
  border-color: rgba(251, 191, 36, 0.35);
  background: rgba(251, 191, 36, 0.12);
}

.nodes {
  display: grid;
  gap: 18px;
  grid-template-columns: 1fr;
}

@media (min-width: 1600px) {
  .nodes { grid-template-columns: 1fr 1fr; }
}

@media (max-width: 1100px) {
  .nodes { grid-template-columns: repeat(auto-fit, minmax(360px, 1fr)); }
}
@media (max-width: 900px) {
  body { padding: 12px 12px 24px; }
  .nodes { grid-template-columns: 1fr; }
}

.card {
  border: 1px solid var(--stroke);
  background: linear-gradient(180deg, rgba(255,255,255,0.08), rgba(255,255,255,0.04));
  border-radius: 18px;
  padding: 16px 16px 14px;
  box-shadow: 0 18px 50px rgba(0,0,0,0.40);
  backdrop-filter: blur(6px);
  min-width: 0;
}

.cardtop { display:flex; justify-content:space-between; gap:14px; flex-wrap:wrap; margin-bottom:12px; }
.title { display:flex; align-items:center; gap:10px; min-width: 0; }
.nodename { font-size: 22px; font-weight: 900; }
.model { font-size: 18px; font-weight: 700; color: rgba(255,255,255,0.70); }
.nodever { margin-top: 4px; font-size: 10px; color: rgba(255,255,255,0.60); }
.nodever.ok { color: rgba(255,255,255,0.68); }
.nodever.behind { color: rgba(251,191,36,0.92); }
.nodever.unknown { color: rgba(255,255,255,0.50); }
.subtitle { margin-top: 4px; font-size: 12.5px; color: rgba(255,255,255,0.72); font-style: italic; }

.pill {
  display:inline-flex; align-items:center; gap:8px;
  padding:7px 10px; border-radius:999px;
  border:1px solid var(--stroke);
  background: rgba(255,255,255,0.05);
  font-size:12px;
  white-space:nowrap;
  margin: 0 8px 8px 0;
}
.pill.neutral { background: rgba(255,255,255,0.045); }
.pill.warn {
  border-color: rgba(251,191,36,0.35);
  background: rgba(251,191,36,0.10);
}
.pill.bad {
  border-color: rgba(251,113,133,0.35);
  background: rgba(251,113,133,0.10);
}

.dot { width: 12px; height: 12px; border-radius:999px; background: rgba(255,255,255,0.40); box-shadow: 0 0 0 4px rgba(255,255,255,0.06); display:inline-block; }
.dot.ok { background: var(--ok); box-shadow: 0 0 0 4px rgba(52,211,153,0.18); }
.dot.warn { background: var(--warn); box-shadow: 0 0 0 4px rgba(251,191,36,0.18); }
.dot.bad { background: var(--bad); box-shadow: 0 0 0 4px rgba(251,113,133,0.18); }
.dot.stale { background: var(--stale); box-shadow: 0 0 0 4px rgba(251,113,133,0.18); }
.dot.neutral { background: rgba(255,255,255,0.55); box-shadow: 0 0 0 4px rgba(255,255,255,0.10); }

.row { display:grid; gap:12px; }
.row2 { grid-template-columns: 1fr 220px 1.1fr; }
.row3 { grid-template-columns: 1.2fr 0.8fr 0.9fr; margin-top:12px; }
@media (max-width: 980px) {
  .row2, .row3 { grid-template-columns: 1fr; }
}

.kvbox, .rammeta, .panel {
  border: 1px solid rgba(255,255,255,0.10);
  border-radius: 14px;
  background: rgba(0,0,0,0.16);
  padding: 12px;
  min-width: 0;
}
.panel { min-height: 140px; }
.k { font-size: 12px; color: var(--muted); margin-bottom: 8px; }
.v.big { font-size: 14.5px; font-weight: 800; color: rgba(255,255,255,0.92); }

.ramtop { display:flex; justify-content:space-between; align-items:baseline; gap:10px; }
.ramright { font-size: 16px; font-weight: 900; }
.rambottom { display:flex; justify-content:space-between; gap:10px; margin-top:6px; color: rgba(255,255,255,0.62); font-size:12px; }
.rightmuted { text-align:right; }

.ph { font-size:12px; color: rgba(255,255,255,0.75); letter-spacing:0.4px; font-weight:900; margin-bottom:10px; }
.bar { height:10px; border-radius:999px; background: rgba(255,255,255,0.09); overflow:hidden; border:1px solid rgba(255,255,255,0.08); margin-top:8px; }
.bar.ram { height:12px; }
.fill { height:100%; width:0%; background: linear-gradient(90deg, rgba(52,211,153,0.95), rgba(52,211,153,0.40)); }
.muted { color: rgba(255,255,255,0.62); font-size:13px; }

.gpuitem { display:flex; justify-content:space-between; gap:10px; padding:7px 0; border-bottom:1px solid rgba(255,255,255,0.08); }
.gpuitem:last-child { border-bottom:none; }
.gpuname { font-weight:900; min-width: 0; }
.gpumeta { color: rgba(255,255,255,0.72); font-size:12.5px; text-align:right; }

.adviceitem { display:flex; gap:10px; align-items:baseline; padding:6px 0; border-bottom:1px solid rgba(255,255,255,0.08); }
.adviceitem:last-child { border-bottom:none; }
.tag {
  font-size:12px; font-weight:900;
  padding:4px 10px; border-radius:999px;
  border:1px solid rgba(255,255,255,0.12);
  background: rgba(255,255,255,0.06);
  text-transform:lowercase;
  min-width:52px; text-align:center;
}
.tag.ok { border-color: rgba(52,211,153,0.35); background: rgba(52,211,153,0.10); }
.tag.warn { border-color: rgba(251,191,36,0.35); background: rgba(251,191,36,0.10); }
.tag.bad { border-color: rgba(251,113,133,0.35); background: rgba(251,113,133,0.10); }
.msg { font-size:13px; color: rgba(255,255,255,0.88); }

.trendrow {
  display: grid;
  gap: 10px;
  grid-template-columns: repeat(3, 1fr);
  width: 100%;
  margin-top: 12px;
}
@media (max-width: 720px) {
  .trendrow { grid-template-columns: 1fr; }
}
.trenditem {
  border: 1px solid rgba(255,255,255,0.10);
  background: rgba(255,255,255,0.04);
  border-radius: 14px;
  padding: 10px;
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 10px;
  min-width: 0;
}
.tk { font-weight: 900; white-space: nowrap; }
.tv { flex: 1; min-width: 0; display:flex; justify-content:flex-end; }
.tv svg { display:block; width: 100%; height: auto; max-width: 100%; }

/* --- Top "quick glance" blocks --- */
.mapwrap, .invwrap, .advwrap {
  border: 1px solid var(--stroke);
  background: rgba(255,255,255,0.04);
  border-radius: 18px;
  padding: 14px;
  box-shadow: 0 18px 50px rgba(0,0,0,0.35);
  margin: 0;
}
.maphead {
  display:flex; justify-content:space-between; align-items:flex-end; gap:12px; flex-wrap:wrap;
  margin-bottom: 10px;
}
.actions { display:flex; gap:10px; flex-wrap:wrap; }
.btn {
  display:inline-flex; align-items:center; gap:8px;
  padding:8px 10px; border-radius: 12px;
  border:1px solid var(--stroke);
  background: rgba(255,255,255,0.06);
  font-size:12.5px;
}
.btn:hover { background: rgba(255,255,255,0.10); }

/* Legend */
.legend {
  display:flex;
  gap: 10px;
  flex-wrap: wrap;
  margin-top: 10px;
  padding-top: 10px;
  border-top: 1px solid rgba(255,255,255,0.08);
}
.legend .item {
  display:inline-flex;
  align-items:center;
  gap: 8px;
  padding: 7px 10px;
  border-radius: 999px;
  border: 1px solid rgba(255,255,255,0.10);
  background: rgba(255,255,255,0.04);
  font-size: 12px;
  color: rgba(255,255,255,0.86);
}
.legend .mut { color: rgba(255,255,255,0.62); }

/* Inventory */
table.inv { width:100%; border-collapse: collapse; }
.inv th, .inv td {
  border-bottom: 1px solid rgba(255,255,255,0.08);
  padding: 10px 8px;
  text-align: left;
  vertical-align: top;
  font-size: 12.5px;
}
.inv th { color: rgba(255,255,255,0.70); font-weight: 900; font-size: 12px; letter-spacing: 0.3px; }
.inv tr:last-child td { border-bottom: none; }
.inv .mono { font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, "Liberation Mono", "Courier New", monospace; }
.inv .right { text-align:right; }
.inv .status { white-space:nowrap; }
.inv .advicecol { white-space:nowrap; }
.badgetxt {
  display:inline-flex;
  align-items:center;
  gap:8px;
  padding: 4px 9px;
  border-radius: 999px;
  border: 1px solid rgba(255,255,255,0.10);
  background: rgba(255,255,255,0.04);
  font-size: 11.5px;
  font-weight: 900;
  letter-spacing: 0.2px;
}
.badgetxt.ok { border-color: rgba(52,211,153,0.25); background: rgba(52,211,153,0.08); }
.badgetxt.warn { border-color: rgba(251,191,36,0.35); background: rgba(251,191,36,0.10); }
.badgetxt.bad { border-color: rgba(251,113,133,0.35); background: rgba(251,113,133,0.10); }
.badgetxt.stale { border-color: rgba(251,113,133,0.35); background: rgba(251,113,133,0.10); }

/* Advice queue */
.advrow {
  display:flex;
  justify-content:space-between;
  gap: 12px;
  padding: 10px 0;
  border-bottom: 1px solid rgba(255,255,255,0.08);
}
.advrow:last-child { border-bottom: none; }
.advleft { min-width: 0; }
.advnode { font-weight: 950; letter-spacing: 0.2px; }
.advmsg { margin-top: 4px; color: rgba(255,255,255,0.80); font-size: 12.5px; }
.advright { display:flex; gap:10px; align-items:flex-start; flex-wrap:wrap; justify-content:flex-end; }
.advsmall { color: rgba(255,255,255,0.62); font-size: 12px; }

/* --- Per-node Details collapse (kept) --- */
.details {
  margin-top: 12px;
  border-top: 1px solid rgba(255,255,255,0.08);
  padding-top: 10px;
}
.details summary {
  cursor: pointer;
  list-style: none;
  display: inline-flex;
  align-items:center;
  gap:10px;
  font-weight: 900;
  color: rgba(255,255,255,0.86);
  padding: 8px 10px;
  border-radius: 12px;
  border: 1px solid rgba(255,255,255,0.10);
  background: rgba(255,255,255,0.04);
}
.details summary::-webkit-details-marker { display:none; }
.details .detailsmuted { color: rgba(255,255,255,0.62); font-weight: 600; font-size: 12.5; }

/* --- Fleet line pulse (fun, but useful) --- */
.linkline {
  stroke: rgba(255,255,255,0.18);
  stroke-width: 2;
  fill: none;
}
.linkline.pulse {
  stroke: rgba(255,255,255,0.55);
  stroke-width: 2.6;
  filter: drop-shadow(0 0 6px rgba(255,255,255,0.18));
  stroke-dasharray: 10 999;
  animation: pulseDash 1.1s ease-out 1;
}
@keyframes pulseDash {
  from { stroke-dashoffset: 0; opacity: 1; }
  to   { stroke-dashoffset: -220; opacity: 0.25; }
}
.nodeDot.ping {
  animation: dotPing 0.75s ease-out 1;
}
@keyframes dotPing {
  0%   { filter: drop-shadow(0 0 0 rgba(255,255,255,0.0)); transform: scale(1); }
  35%  { filter: drop-shadow(0 0 10px rgba(255,255,255,0.22)); transform: scale(1.12); }
  100% { filter: drop-shadow(0 0 0 rgba(255,255,255,0.0)); transform: scale(1); }
}

/* Footer versions */
.footerline {
  margin-top: 18px;
  padding-top: 12px;
  border-top: 1px solid rgba(255,255,255,0.08);
  color: rgba(255,255,255,0.68);
  font-size: 12px;
  text-align: center;
}

/* Make SVG links actually clickable */
svg a { cursor: pointer; pointer-events: auto; }
svg text { pointer-events: auto; }
"""

# JS kept out of f-strings so braces don't explode
JS_PULSE = r"""
(() => {
  const POLL_MS = 9000;
  const MAX_ANIM_MS = 1200;

  let lastSeen = {};
  let started = false;

  function safeId(node) {
    return String(node).replace(/[^a-zA-Z0-9_-]/g, "_");
  }

  function trigger(node) {
    const id = safeId(node);
    const path = document.getElementById(`link-${id}`);
    const dot  = document.getElementById(`dot-${id}`);

    if (path) {
      path.classList.remove("pulse");
      void path.getBoundingClientRect();
      path.classList.add("pulse");
      setTimeout(() => path.classList.remove("pulse"), MAX_ANIM_MS);
    }

    if (dot) {
      dot.classList.remove("ping");
      void dot.getBoundingClientRect();
      dot.classList.add("ping");
      setTimeout(() => dot.classList.remove("ping"), 900);
    }
  }

  async function poll() {
    try {
      const r = await fetch("/inventory", { cache: "no-store" });
      if (!r.ok) return;
      const data = await r.json();
      const nodes = (data && data.nodes) ? data.nodes : [];

      const next = {};
      const changed = [];

      for (const n of nodes) {
        const node = n.node;
        const ts = n.last_seen || "";
        next[node] = ts;

        if (started && lastSeen[node] && ts && ts !== lastSeen[node]) {
          changed.push(node);
        }
      }

      lastSeen = next;
      if (!started) started = true;

      for (const node of changed) trigger(node);

    } catch (_) {
    }
  }

  poll();
  setInterval(poll, POLL_MS);
})();
"""


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


def _fmt_dt(dt: Optional[datetime]) -> str:
    if not dt:
        return "—"
    return dt.astimezone(timezone.utc).strftime("%a %d %b %Y %H:%M")


def _ago(dt: Optional[datetime]) -> str:
    if not dt:
        return "unknown"
    now = _utcnow()
    delta = now - dt
    if delta.total_seconds() < -60:
        return "in the future (clock?)"
    if delta.total_seconds() < 60:
        return "just now"
    mins = int(delta.total_seconds() // 60)
    if mins < 60:
        return f"{mins}m ago"
    hrs = mins // 60
    if hrs < 24:
        return f"{hrs}h ago"
    days = hrs // 24
    return f"{days}d ago"


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


def _html_escape(s: str) -> str:
    return (
        s.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
        .replace("'", "&#39;")
    )


def _safe_dom_id(s: str) -> str:
    out = []
    for ch in (s or ""):
        if ch.isalnum() or ch in ("-", "_"):
            out.append(ch)
        else:
            out.append("_")
    return "".join(out) or "node"


def _load_schema_current() -> str:
    try:
        if not SCHEMA_CURRENT_FILE.exists() or not SCHEMA_CURRENT_FILE.is_file():
            return "unknown"
        data = json.loads(SCHEMA_CURRENT_FILE.read_text(encoding="utf-8"))
        return data.get("schema_version") or data.get("contract_version") or "unknown"
    except Exception:
        return "unknown"


def _db() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
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


def _worst_severity(advice: List[Dict[str, Any]]) -> str:
    worst = "ok"
    for a in advice:
        sev = str(a.get("severity") or a.get("level") or "").lower()
        if sev == "bad":
            return "bad"
        if sev == "warn":
            worst = "warn"
    return worst


def _headline_line(sev: str) -> str:
    sev = (sev or "ok").lower()
    if sev == "bad":
        return "Intervention advised."
    if sev == "warn":
        return "A bit spicy. Keep an eye on it."
    if sev == "info":
        return "Not urgent. Just noted."
    return "Nothing concerning detected."


def _bios_display(facts: Dict[str, Any], raw_facts: Dict[str, Any]) -> str:
    for src in (facts, raw_facts):
        if src.get("bios_version"):
            return str(src["bios_version"])
        ex = src.get("extensions")
        if isinstance(ex, dict):
            bv = ex.get("bios_version") or ex.get("bios")
            if bv:
                if isinstance(bv, dict):
                    return str(bv.get("version") or bv.get("bios_version") or "—")
                return str(bv)
    return "—"


def _get_ram_used_pct(metrics: Dict[str, Any], raw_metrics: Dict[str, Any]) -> Optional[float]:
    for src in (metrics, raw_metrics):
        v = _fnum(src.get("mem_used_pct"))
        if v is not None:
            return _clamp(v, 0.0, 100.0)
        ram = src.get("ram")
        if isinstance(ram, dict):
            v2 = _fnum(ram.get("used_pct"))
            if v2 is not None:
                return _clamp(v2, 0.0, 100.0)
    return None


def _cpu_temp(metrics: Dict[str, Any], raw_metrics: Dict[str, Any]) -> Optional[float]:
    def pick(temps: Dict[str, Any]) -> Optional[float]:
        if not isinstance(temps, dict) or not temps:
            return None
        preferred = []
        for k in temps.keys():
            ks = str(k).lower()
            if any(x in ks for x in ("package", "tdie", "tctl", "cpu")):
                preferred.append(k)
        for k in preferred:
            v = _fnum(temps.get(k))
            if v is not None:
                return float(v)
        core_vals: List[float] = []
        for k, v in temps.items():
            if "core" in str(k).lower():
                n = _fnum(v)
                if n is not None:
                    core_vals.append(float(n))
        if core_vals:
            return max(core_vals)
        any_vals: List[float] = []
        for v in temps.values():
            n = _fnum(v)
            if n is not None:
                any_vals.append(float(n))
        return max(any_vals) if any_vals else None

    for src in (metrics, raw_metrics):
        temps = src.get("temps_c")
        if isinstance(temps, dict):
            v = pick(temps)
            if v is not None:
                return v
    return None


def _get_load(metrics: Dict[str, Any], raw_metrics: Dict[str, Any]) -> Optional[float]:
    for src in (metrics, raw_metrics):
        v = _fnum(src.get("cpu_load_1m"))
        if v is not None:
            return v
    return None


def _ram_total_display(facts: Dict[str, Any], raw_facts: Dict[str, Any]) -> str:
    for src in (raw_facts, facts):
        ram_total_gb = src.get("ram_total_gb")
        ram_max_gb = src.get("ram_max_gb")
        ram_slots_total = src.get("ram_slots_total")
        ram_type = src.get("ram_type")

        if ram_total_gb:
            if ram_max_gb and str(ram_max_gb) != str(ram_total_gb):
                base = f"{ram_total_gb}GB / {ram_max_gb}GB"
            else:
                base = f"{ram_total_gb}GB / {ram_total_gb}GB"
        else:
            base = "—"

        slots_bits = []
        if ram_slots_total:
            slots_bits.append(f"Slots: {ram_slots_total}")
        if ram_type:
            slots_bits.append(str(ram_type))
        if slots_bits:
            return base + "\n" + " · ".join(slots_bits)
        if base != "—":
            return base
    return "—"


def _map_engine_sev(sev: str) -> str:
    s = (sev or "").lower().strip()
    if s in ("crit", "critical", "red"):
        return "bad"
    if s in ("warn", "warning", "amber", "yellow"):
        return "warn"
    if s in ("ok", "green"):
        return "ok"
    if s == "":
        return "ok"
    return s


def _advice_normalised_snapshot(snapshot: Dict[str, Any]) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []

    if advice_build:
        try:
            adv, _health = advice_build(snapshot)
            if isinstance(adv, list):
                for a in adv:
                    if not isinstance(a, dict):
                        continue
                    sev = _map_engine_sev(str(a.get("severity") or "info"))
                    msg = a.get("message") or a.get("text") or ""
                    if msg:
                        out.append(
                            {
                                "severity": sev,
                                "message": str(msg),
                                "evidence": a.get("evidence") if isinstance(a.get("evidence"), dict) else {},
                            }
                        )
        except Exception:
            pass

    if not out:
        try:
            items = rules_evaluate(snapshot) or []
        except Exception:
            items = []
        for a in items:
            if not isinstance(a, dict):
                continue
            lvl = str(a.get("level") or a.get("severity") or "ok").lower()
            lvl = _map_engine_sev(lvl)
            msg = a.get("text") or a.get("message") or ""
            if msg:
                out.append({"severity": lvl, "message": str(msg)})

    try:
        facts = snapshot.get("facts") if isinstance(snapshot.get("facts"), dict) else {}
        rt = facts.get("ram_total_gb")
        rm = facts.get("ram_max_gb")
        if isinstance(rt, (int, float)) and isinstance(rm, (int, float)) and rm > rt:
            gap = int(rm - rt)
            out.append(
                {
                    "severity": "warn",
                    "message": f"RAM headroom available: {int(rt)}GB installed, supports {int(rm)}GB. (+{gap}GB potential).",
                    "evidence": {"ram_total_gb": rt, "ram_max_gb": rm},
                }
            )
    except Exception:
        pass

    return out


def _get_disk_physical(payload: Dict[str, Any], metrics: Dict[str, Any], raw: Dict[str, Any]) -> List[Dict[str, Any]]:
    ex = metrics.get("extensions")
    if isinstance(ex, dict):
        dp = ex.get("disk_physical")
        if isinstance(dp, list):
            return [d for d in dp if isinstance(d, dict)]
    raw_metrics = raw.get("metrics") if isinstance(raw.get("metrics"), dict) else {}
    raw_ex = raw_metrics.get("extensions") if isinstance(raw_metrics.get("extensions"), dict) else {}
    dp = raw_ex.get("disk_physical")
    if isinstance(dp, list):
        return [d for d in dp if isinstance(d, dict)]
    return []


def _get_gpu_list(metrics: Dict[str, Any], raw: Dict[str, Any]) -> List[Dict[str, Any]]:
    g = metrics.get("gpu")
    if isinstance(g, list) and g:
        return [x for x in g if isinstance(x, dict)]
    ex = metrics.get("extensions")
    if isinstance(ex, dict):
        g2 = ex.get("gpus")
        if isinstance(g2, list) and g2:
            return [x for x in g2 if isinstance(x, dict)]
    raw_metrics = raw.get("metrics") if isinstance(raw.get("metrics"), dict) else {}
    for k in ("gpus", "gpu"):
        v = raw_metrics.get(k)
        if isinstance(v, list) and v:
            return [x for x in v if x and isinstance(x, dict)]
    return []


def _sparkline(values: List[Optional[float]], w: int = 340, h: int = 36) -> str:
    pts: List[Tuple[float, float]] = []
    vs = [v for v in values if v is not None]

    if len(vs) < 3:
        return ""

    vmin, vmax = min(vs), max(vs)
    span = vmax - vmin
    pad = 0.5 if span < 0.5 else span * 0.2

    vmin -= pad
    vmax += pad

    n = len(values)

    for i, v in enumerate(values):
        if v is None:
            continue

        x = (i / max(1, (n - 1))) * (w - 2) + 1
        y = (1 - ((v - vmin) / (vmax - vmin))) * (h - 2) + 1
        pts.append((x, y))

    if len(pts) < 2:
        return ""

    d = "M " + " L ".join(f"{x:.2f},{y:.2f}" for x, y in pts)

    return (
        f'<svg viewBox="0 0 {w} {h}" preserveAspectRatio="none" xmlns="http://www.w3.org/2000/svg">'
        f'<path d="{d}" fill="none" stroke="rgba(255,255,255,0.62)" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>'
        f"</svg>"
    )


def _trend_series(history: List[Dict[str, Any]]) -> Dict[str, List[Optional[float]]]:
    ram: List[Optional[float]] = []
    disk: List[Optional[float]] = []
    gpu: List[Optional[float]] = []

    for row in history:
        p = row.get("payload") if isinstance(row.get("payload"), dict) else {}
        raw = _raw_payload(p)
        metrics = _get_metrics(p)
        raw_metrics = raw.get("metrics") if isinstance(raw.get("metrics"), dict) else {}

        ram.append(_get_ram_used_pct(metrics, raw_metrics))

        chosen_disk = None
        du = metrics.get("disk_used")
        mounts: List[Dict[str, Any]] = [m for m in du if isinstance(m, dict)] if isinstance(du, list) else []

        root = next((m for m in mounts if str(m.get("mount") or "") in ("/", "/root")), None)
        if root:
            v = _fnum(root.get("used_pct"))
            if v is None:
                v = _fnum(root.get("pct"))
            if v is not None:
                chosen_disk = _clamp(v, 0.0, 100.0)

        if chosen_disk is None and mounts:
            vals = []
            for m in mounts:
                v = _fnum(m.get("used_pct"))
                if v is None:
                    v = _fnum(m.get("pct"))
                if v is not None:
                    vals.append(v)
            if vals:
                chosen_disk = _clamp(max(vals), 0.0, 100.0)

        disk.append(chosen_disk)

        gmax = None
        gl = _get_gpu_list(metrics, raw)
        if gl:
            vals = []
            for gg in gl:
                if not isinstance(gg, dict):
                    continue
                vals.append(_fnum(gg.get("mem_used_pct")) or _fnum(gg.get("vram_used_pct")) or _fnum(gg.get("util_pct")))
            vals = [x for x in vals if x is not None]
            gmax = max(vals) if vals else None
        gpu.append(None if gmax is None else _clamp(gmax, 0.0, 100.0))

    return {"ram": ram, "disk": disk, "gpu": gpu}


def _trend_block(label: str, svg: str, empty_text: Optional[str] = None) -> str:
    text = empty_text

    if not svg and not text:
        text = "Collecting history... check back in ~15m"

    if text:
        return (
            f"<div class='trenditem'>"
            f"<div class='tk'>{_html_escape(label)}</div>"
            f"<div class='tv'><span class='muted'>{_html_escape(text)}</span></div>"
            f"</div>"
        )

    return (
        f"<div class='trenditem'>"
        f"<div class='tk'>{_html_escape(label)}</div>"
        f"<div class='tv'>{svg}</div>"
        f"</div>"
    )


def _agent_version_state(actual: str, expected: str) -> str:
    a = (actual or "").strip()
    e = (expected or "").strip()

    if not a or a == "unknown":
        return "unknown"
    if not e or e == "unknown":
        return "ok"
    if a == e:
        return "ok"
    return "behind"


@dataclass
class NodeView:
    node: str
    node_id: str

    model: str
    cpu: str
    bios: str
    agent_version: str
    ram_total: str
    ram_used_pct: Optional[float]
    load1: Optional[float]
    temp_c: Optional[float]
    ts: Optional[datetime]
    stale: bool
    health_state: str
    health_score: int
    age_minutes: Optional[float]

    advice: List[Dict[str, Any]]
    advice_sev: str
    advice_counts: Dict[str, int]

    worst: str
    headline: str
    disks_physical: List[Dict[str, Any]]
    gpus: List[Dict[str, Any]]
    trend_ram_svg: str
    trend_disk_svg: str
    trend_gpu_svg: str

    debug: Dict[str, Any]


def _build_node_view(conn: sqlite3.Connection, node: str, rec: Dict[str, Any], hours: int = 72) -> NodeView:
    payload = rec.get("payload") if isinstance(rec.get("payload"), dict) else {}
    raw = _raw_payload(payload)

    facts = _get_facts(payload)
    metrics = _get_metrics(payload)

    raw_facts = raw.get("facts") if isinstance(raw.get("facts"), dict) else {}
    raw_metrics = raw.get("metrics") if isinstance(raw.get("metrics"), dict) else {}

    ts = _parse_ts(_safe_str(rec.get("ts") or payload.get("ts") or ""))

    health = compute_health(payload, ctx={})
    health_state = str(health.get("state") or "healthy").lower()
    try:
        health_score = int(health.get("score") or 0)
    except Exception:
        health_score = 0

    age_minutes = health.get("age_minutes")
    try:
        age_minutes = float(age_minutes) if age_minutes is not None else None
    except Exception:
        age_minutes = None

    stale = health_state == "critical" and any(
        "stale" in str(r).lower() for r in (health.get("reasons") or [])
    )

    model = _safe_str(raw_facts.get("model") or facts.get("model") or "")
    cpu = _safe_str(raw_facts.get("cpu") or facts.get("cpu") or "")
    bios = _bios_display(facts, raw_facts)
    agent_version = _safe_str(payload.get("agent_version") or "unknown")

    ram_total = _ram_total_display(facts, raw_facts)
    ram_used_pct = _get_ram_used_pct(metrics, raw_metrics)
    load1 = _get_load(metrics, raw_metrics)
    temp_c = _cpu_temp(metrics, raw_metrics)

    advice_real = _advice_normalised_snapshot(payload)
    real_warn = sum(1 for a in advice_real if str(a.get("severity")).lower() == "warn")
    real_bad = sum(1 for a in advice_real if str(a.get("severity")).lower() == "bad")
    advice_sev = "bad" if real_bad else ("warn" if real_warn else "ok")

    advice = list(advice_real)

    delayed = health_state == "warning" and any(
        "delayed" in str(r).lower() for r in (health.get("reasons") or [])
    )

    if stale:
        advice = [{"severity": "bad", "message": f"Node has stopped reporting (last seen {_ago(ts)})."}] + advice
    elif delayed:
        advice = [{"severity": "warn", "message": f"Node reporting delayed (last seen {_ago(ts)})."}] + advice

    if stale:
        worst = "stale"
    elif delayed:
        worst = "warn"
    else:
        worst = _worst_severity([a for a in advice if str(a.get("severity")).lower() in ("warn", "bad")])

    if stale:
        headline = "Node appears stale."
    elif delayed:
        headline = "Node reporting looks delayed."
    else:
        headline = _headline_line("bad" if worst == "bad" else ("warn" if worst == "warn" else "ok"))

    disks_physical = _get_disk_physical(payload, metrics, raw)
    gpus = _get_gpu_list(metrics, raw)

    hist = _fetch_history(conn, node, hours=hours, limit=MAX_HISTORY_ROWS)
    series = _trend_series(hist)

    debug: Dict[str, Any] = {}
    try:
        debug = {
            "facts": {
                "ram_total_gb": raw_facts.get("ram_total_gb") or facts.get("ram_total_gb"),
                "ram_max_gb": raw_facts.get("ram_max_gb") or facts.get("ram_max_gb"),
                "ram_slots_used": raw_facts.get("ram_slots_used") or facts.get("ram_slots_used"),
                "ram_slots_total": raw_facts.get("ram_slots_total") or facts.get("ram_slots_total"),
                "ram_type": raw_facts.get("ram_type") or facts.get("ram_type"),
                "cpu_cores": raw_facts.get("cpu_cores") or facts.get("cpu_cores"),
            },
            "metrics": {
                "mem_used_pct": raw_metrics.get("mem_used_pct") if raw_metrics else metrics.get("mem_used_pct"),
                "cpu_load_1m": raw_metrics.get("cpu_load_1m") if raw_metrics else metrics.get("cpu_load_1m"),
                "temps_c_keys": sorted(list((metrics.get("temps_c") or {}).keys())) if isinstance(metrics.get("temps_c"), dict) else [],
                "disk_used": metrics.get("disk_used") if isinstance(metrics.get("disk_used"), list) else [],
            },
        }
    except Exception:
        debug = {}

    return NodeView(
        node=node,
        node_id=_safe_dom_id(node),
        model=model,
        cpu=cpu,
        bios=bios,
        agent_version=agent_version,
        ram_total=ram_total,
        ram_used_pct=ram_used_pct,
        load1=load1,
        temp_c=temp_c,
        ts=ts,
        stale=stale,
        health_state=health_state,
        health_score=health_score,
        age_minutes=age_minutes,
        advice=advice,
        advice_sev=advice_sev,
        advice_counts={"warn": real_warn, "bad": real_bad},
        worst=worst,
        headline=headline,
        disks_physical=disks_physical,
        gpus=gpus,
        trend_ram_svg=_sparkline(series["ram"]),
        trend_disk_svg=_sparkline(series["disk"]),
        trend_gpu_svg=_sparkline(series["gpu"]),
        debug=debug,
    )


def _sev_dot(sev: str) -> str:
    sev = (sev or "ok").lower()
    if sev == "bad":
        return "dot bad"
    if sev == "warn":
        return "dot warn"
    if sev == "stale":
        return "dot stale"
    if sev == "neutral":
        return "dot neutral"
    return "dot ok"


def _pill(sev: str, text: str) -> str:
    sev = (sev or "neutral").lower()
    return f'<span class="pill {sev}"><span class="{_sev_dot(sev)}"></span>{_html_escape(text)}</span>'


def _badge_text(sev: str, label: str) -> str:
    sev = (sev or "ok").lower()
    cls = sev if sev in ("ok", "warn", "bad", "stale") else "ok"
    return f'<span class="badgetxt {cls}">{_html_escape(label)}</span>'


def _top_action(nv: NodeView) -> Optional[Tuple[str, str]]:
    if nv.stale:
        return ("stale", f"Stopped reporting ({_ago(nv.ts)}).")
    if not nv.advice:
        return None

    for sev in ("bad", "warn"):
        for a in nv.advice:
            if str(a.get("severity") or "").lower() == sev:
                msg = _safe_str(a.get("message") or "").strip()
                if msg:
                    return (sev, msg)

    return None


def _render_gpus(gpus: List[Dict[str, Any]]) -> str:
    if not gpus:
        return "<div class='muted'>None detected.</div>"

    out: List[str] = []
    for g in gpus[:4]:
        name = _safe_str(g.get("name") or "GPU")
        util = _fnum(g.get("util_pct"))
        temp = _fnum(g.get("temp_c"))

        mt = _fnum(g.get("mem_total_mb"))
        mu = _fnum(g.get("mem_used_mb"))
        mp = _fnum(g.get("mem_used_pct"))

        if mp is None and mt and mt > 0 and mu is not None:
            mp = (mu / mt) * 100.0

        left_bits = []
        if util is not None:
            left_bits.append(f"Util {util:.0f}%")
        if temp is not None:
            left_bits.append(f"Temp {temp:.0f}°C")

        right_bits = []
        if mt is not None and mu is not None:
            pct_txt = f"{mp:.0f}%" if mp is not None else "—"
            right_bits.append(f"VRAM {mu:.0f}/{mt:.0f} MB ({pct_txt})")
        elif mp is not None:
            right_bits.append(f"VRAM {mp:.0f}%")

        drv = g.get("driver")
        bus = g.get("bus_id")
        if drv:
            right_bits.append(f"drv {drv}")
        if bus:
            right_bits.append(f"bus {bus}")

        out.append(
            f"<div class='gpuitem'>"
            f"<div class='gpuname'>{_html_escape(name)}<div class='muted' style='font-size:12px; margin-top:2px;'>{_html_escape(' • '.join(left_bits))}</div></div>"
            f"<div class='gpumeta'>{_html_escape(' • '.join(right_bits))}</div>"
            f"</div>"
        )
    return "".join(out)


def _render_advice(advice: List[Dict[str, Any]]) -> str:
    if not advice:
        return "<div class='muted'>All clear. (Boring is good.)</div>"
    out: List[str] = []
    for a in advice[:10]:
        sev = str(a.get("severity") or "ok").lower()
        msg = _safe_str(a.get("message") or "")
        tag_class = "warn" if sev == "info" else sev
        out.append(
            f"<div class='adviceitem'><span class='tag {tag_class}'>{_html_escape(sev)}</span>"
            f"<span class='msg'>{_html_escape(msg)}</span></div>"
        )
    return "".join(out)


def _render_debug(nv: NodeView) -> str:
    d = nv.debug or {}
    pretty = _html_escape(json.dumps(d, indent=2, ensure_ascii=False))
    return f"""
<div class="panel" style="min-height:unset;">
  <div class="ph">DEBUG (inputs to advice)</div>
  <pre style="margin:0; padding:10px; border-radius:12px; overflow:auto; background:rgba(0,0,0,0.30); border:1px solid rgba(255,255,255,0.08); font-size:12px; line-height:1.35;">{pretty}</pre>
</div>
"""


def _render_storage_physical(disks: List[Dict[str, Any]]) -> str:
    if not disks:
        return "<div class='muted'>No disk data.</div>"
    blocks: List[str] = []
    for d in disks[:6]:
        disk = _safe_str(d.get("disk") or "disk")
        size = _safe_str(d.get("size") or d.get("disk_size") or "")
        model = _safe_str(d.get("model") or d.get("disk_model") or "")
        serial = _safe_str(d.get("serial") or d.get("disk_serial") or "")
        pct = _fnum(d.get("pct"))
        mounts = d.get("mounts") if isinstance(d.get("mounts"), list) else []

        headline = f"{disk} ({size} • {model})".strip()
        pct_txt = "—" if pct is None else f"{pct:.1f}%"
        bar_pct = 0.0 if pct is None else _clamp(pct, 0, 100)

        lines = []
        for m in mounts[:10]:
            if not isinstance(m, dict):
                continue
            mp = _safe_str(m.get("mount") or "")
            mpct = _fnum(m.get("pct") if m.get("pct") is not None else m.get("used_pct"))
            mpct_txt = "—" if mpct is None else f"{mpct:.1f}%"
            lines.append(f"<div class='kv'><span class='k'>{_html_escape(mp)}</span><span class='v'>{_html_escape(mpct_txt)}</span></div>")

        extra = f" • SN {serial}" if serial else ""
        blocks.append(
            f"""
            <div class="diskblock">
              <div class="diskhead">
                <div class="diskname">{_html_escape(headline)}{_html_escape(extra)}</div>
                <div class="diskpct">{_html_escape(pct_txt)}</div>
              </div>
              <div class="bar"><div class="fill" style="width:{bar_pct:.1f}%"></div></div>
              <div class="diskmounts">{''.join(lines)}</div>
            </div>
            """
        )
    return "".join(blocks)


def _render_top_banner(nodes: List[NodeView]) -> str:
    pills: List[str] = []
    for nv in nodes:
        if nv.worst in ("bad", "warn", "stale"):
            if nv.worst == "stale":
                msg = f"{nv.node} — Node has stopped reporting (last seen {_ago(nv.ts)})."
            elif nv.worst == "bad":
                msg = f"{nv.node} — Needs attention."
            else:
                msg = f"{nv.node} — Warning."
            pills.append(f"<span class='topwarn {nv.worst}'>{_html_escape(msg)}</span>")
    if not pills:
        return ""
    return f"<div class='topwarnwrap'>{''.join(pills)}</div>"


def _render_fleet_map(nodeviews: List[NodeView], brain_name: str) -> str:
    nodes_sorted = sorted(list(nodeviews), key=lambda x: x.node)
    others = [nv for nv in nodes_sorted if nv.node != brain_name]
    n = max(1, len(others))

    w = 980
    h = 140 + n * 68

    bx, by = 120, 80
    nx = 520
    start_y = 86
    step = 68

    PULSE_RECENT_SECONDS = int(os.environ.get("HARRY_PULSE_RECENT_SECONDS", "90"))

    def dot_color(sev: str) -> str:
        sev = (sev or "ok").lower()
        if sev == "bad":
            return "#fb7185"
        if sev == "warn":
            return "#fbbf24"
        if sev == "stale":
            return "#fb7185"
        return "#34d399"

    svg: List[str] = []
    svg.append(
        f'<svg viewBox="0 0 {w} {h}" width="100%" height="auto" '
        f'xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink">'
    )
    svg.append(
        '<defs>'
        '<filter id="g" x="-30%" y="-30%" width="160%" height="160%">'
        '<feGaussianBlur stdDeviation="6" result="b"/>'
        '<feMerge><feMergeNode in="b"/><feMergeNode in="SourceGraphic"/></feMerge>'
        "</filter>"
        '<filter id="pg" x="-50%" y="-50%" width="200%" height="200%">'
        '<feGaussianBlur stdDeviation="3" result="pb"/>'
        '<feMerge><feMergeNode in="pb"/><feMergeNode in="SourceGraphic"/></feMerge>'
        "</filter>"
        "</defs>"
    )

    svg.append(
        f'<rect x="{bx-70}" y="{by-28}" width="220" height="56" rx="16" '
        f'fill="rgba(255,255,255,0.06)" stroke="rgba(255,255,255,0.18)"/>'
    )
    svg.append(
        f'<text x="{bx+40}" y="{by-4}" text-anchor="middle" '
        f'fill="rgba(255,255,255,0.92)" font-size="16" font-weight="800">Harry Brain</text>'
    )
    svg.append(
        f'<text x="{bx+40}" y="{by+16}" text-anchor="middle" '
        f'fill="rgba(255,255,255,0.70)" font-size="12">{_html_escape(brain_name)}</text>'
    )

    now = _utcnow()

    for i, nv in enumerate(others):
        y = start_y + i * step
        sid = nv.node_id

        path_d = f"M {nx-40} {y} C {nx-120} {y}, {bx+260} {by}, {bx+150} {by}"
        svg.append(f'<path id="link-{sid}" class="linkline" d="{path_d}"/>')

        col = dot_color(nv.worst)
        svg.append(f'<circle id="dot-{sid}" class="nodeDot" cx="{nx-40}" cy="{y}" r="10" fill="{col}" filter="url(#g)"/>')

        label = nv.node
        meta = _ago(nv.ts)

        agent_state = _agent_version_state(nv.agent_version, AGENT_VERSION)
        agent_line = f"Agent {nv.agent_version or 'unknown'}"
        if agent_state == "behind":
            agent_line += " · behind"

        agent_fill = "rgba(255,255,255,0.62)"
        if agent_state == "behind":
            agent_fill = "rgba(251,191,36,0.92)"
        elif agent_state == "unknown":
            agent_fill = "rgba(255,255,255,0.45)"

        svg.append(
            f'<a xlink:href="#node-{sid}" href="#node-{sid}">'
            f'<text x="{nx}" y="{y+2}" fill="rgba(255,255,255,0.92)" font-size="14" font-weight="800">'
            f"{_html_escape(label)}</text></a>"
        )
        svg.append(
            f'<text x="{nx}" y="{y+20}" fill="{agent_fill}" font-size="10">'
            f"{_html_escape(agent_line)}</text>"
        )
        svg.append(
            f'<text x="{nx+190}" y="{y+2}" fill="rgba(255,255,255,0.62)" font-size="12">'
            f"{_html_escape(meta)}</text>"
        )

        recent = False
        if nv.ts:
            try:
                recent = (now - nv.ts).total_seconds() <= PULSE_RECENT_SECONDS
            except Exception:
                recent = False

        if recent:
            svg.append(
                f'''
                <circle r="4" fill="rgba(255,255,255,0.80)" filter="url(#pg)">
                  <animateMotion dur="1.4s" repeatCount="1" path="{path_d}" />
                  <animate attributeName="r" values="3;5;3" dur="1.4s" repeatCount="1" />
                  <animate attributeName="opacity" values="0.0;1.0;0.0" dur="1.4s" repeatCount="1" />
                </circle>
                '''
            )

    svg.append("</svg>")
    return "".join(svg)


def _render_upgrade_shortlist(nodeviews: List[NodeView], max_items: int = 10) -> str:
    items: List[Tuple[str, str, str, str]] = []
    for nv in nodeviews:
        for a in (nv.advice or []):
            sev = str(a.get("severity") or "info").lower()
            if sev not in ("warn", "bad"):
                continue
            msg = _safe_str(a.get("message") or "")
            if not msg:
                continue
            items.append((sev, nv.node, nv.node_id, msg))

    if not items:
        return """
<div class="invwrap">
  <div class="maphead">
    <div>
      <div class="h2">Upgrade shortlist</div>
      <div class="h2sub">The loud bits. Sorted by “do something about it”.</div>
    </div>
  </div>
  <div class="muted">All quiet on the upgrade front. (Suspicious.)</div>
</div>
"""

    order = {"bad": 0, "warn": 1}
    items.sort(key=lambda x: (order.get(x[0], 9), x[1], x[3]))
    items = items[:max_items]

    rows: List[str] = []
    for sev, node, node_id, msg in items:
        dot = _sev_dot("bad" if sev == "bad" else "warn")
        rows.append(
            f"""
<div class="adviceitem" style="border-bottom:1px solid rgba(255,255,255,0.08); padding:10px 0;">
  <span class="{dot}"></span>
  <a href="#node-{node_id}" style="font-weight:900;">{_html_escape(node)}</a>
  <span class="tag {'bad' if sev=='bad' else 'warn'}" style="margin-left:10px;">{_html_escape(sev)}</span>
  <span class="msg" style="margin-left:10px;">{_html_escape(msg)}</span>
</div>
"""
        )

    return f"""
<div class="invwrap">
  <div class="maphead">
    <div>
      <div class="h2">Upgrade shortlist</div>
      <div class="h2sub">The loud bits. Sorted by “do something about it”.</div>
    </div>
    <div class="actions">
      <a class="btn" href="#node-details">Jump to node details</a>
    </div>
  </div>
  {''.join(rows)}
</div>
"""


def _render_inventory_table(nodeviews: List[NodeView]) -> str:
    rows: List[str] = []
    for nv in nodeviews:
        dot = _sev_dot(nv.worst)

        model = nv.model or "—"
        cpu = nv.cpu or "—"
        ram_lines = (nv.ram_total.splitlines() if nv.ram_total else [])
        ram_main = (ram_lines[0] if len(ram_lines) >= 1 else "—")
        ram_meta = (ram_lines[1] if len(ram_lines) >= 2 else "")
        bios = nv.bios or "—"
        last = f"{_fmt_dt(nv.ts)} ({_ago(nv.ts)})"

        if nv.stale:
            adv = _badge_text("stale", "STALE")
            hint = "stopped reporting"
        else:
            sev = (nv.advice_sev or "ok").lower()
            if sev == "bad":
                adv = _badge_text("bad", f"BAD {nv.advice_counts.get('bad', 0)}")
            elif sev == "warn":
                adv = _badge_text("warn", f"WARN {nv.advice_counts.get('warn', 0)}")
            else:
                adv = _badge_text("ok", "OK")
            ta = _top_action(nv)
            hint = (ta[1] if ta else "—")

        rows.append(
            f"""
<tr>
  <td class="status"><span class="{dot}"></span> <a href="#node-{nv.node_id}">{_html_escape(nv.node)}</a></td>
  <td>{_html_escape(model)}</td>
  <td>{_html_escape(cpu)}</td>
  <td class="right mono">
    <div>{_html_escape(ram_main)}</div>
    <div class="muted" style="margin-top:2px; font-size:12px;">{_html_escape(ram_meta)}</div>
  </td>
  <td class="mono">{_html_escape(bios)}</td>
  <td class="mono">{_html_escape(last)}</td>
  <td class="advicecol">{adv}<div class="advsmall">{_html_escape(hint)}</div></td>
</tr>
"""
        )

    return f"""
<table class="inv">
  <thead>
    <tr>
      <th>Node</th>
      <th>Model</th>
      <th>CPU</th>
      <th class="right">RAM</th>
      <th>BIOS</th>
      <th>Last seen</th>
      <th>Advice</th>
    </tr>
  </thead>
  <tbody>
    {''.join(rows)}
  </tbody>
</table>
"""


def _render_advice_queue(nodeviews: List[NodeView]) -> str:
    items: List[Tuple[int, str, NodeView, str]] = []
    for nv in nodeviews:
        if nv.stale:
            items.append((0, "stale", nv, f"Stopped reporting (last seen {_ago(nv.ts)})."))
            continue

        sev = (nv.advice_sev or "ok").lower()
        if sev in ("bad", "warn"):
            ta = _top_action(nv)
            msg = ta[1] if ta else "Recommendation available."
            items.append((1 if sev == "bad" else 2, sev, nv, msg))

    if not items:
        return ""

    items.sort(key=lambda t: (t[0], t[2].node))

    rows: List[str] = []
    for _, sev, nv, msg in items[:18]:
        label = "STALE" if sev == "stale" else ("BAD" if sev == "bad" else "WARN")
        badge = _badge_text("stale" if sev == "stale" else sev, label)
        ago = _ago(nv.ts)
        rows.append(
            f"""
<div class="advrow">
  <div class="advleft">
    <div class="advnode">{_html_escape(nv.node)} <span class="advsmall">{_html_escape(nv.model or '')}</span></div>
    <div class="advmsg">{_html_escape(msg)}</div>
  </div>
  <div class="advright">
    {badge}
    <span class="advsmall">{_html_escape(ago)}</span>
    <a class="btn" href="#node-{nv.node_id}">Jump</a>
  </div>
</div>
"""
        )

    return f"""
<div class="section" id="advice">
  <div class="sectionhead">
    <div>
      <div class="h2">Upgrade recommendations</div>
      <div class="h2sub">Harry’s shortlist. If you ignore this, at least do it consciously.</div>
    </div>
    <div class="actions">
      <a class="btn" href="#inventory">Inventory</a>
      <a class="btn" href="#fleet">Fleet</a>
      <a class="btn" href="#details">Details</a>
    </div>
  </div>
  <div class="advwrap">
    {''.join(rows)}
  </div>
</div>
"""


def _render_node_card(nv: NodeView, hours: int, debug: bool) -> str:
    dot = _sev_dot(nv.worst)
    model = f" ({nv.model})" if nv.model else ""
    agent_state = _agent_version_state(nv.agent_version, AGENT_VERSION)

    pills: List[str] = []
    if nv.load1 is not None:
        pills.append(_pill("neutral", f"Load {nv.load1:.2f}"))
    if nv.temp_c is not None:
        pills.append(_pill("neutral", f"CPU {nv.temp_c:.1f}°C"))
    pills.append(_pill("neutral", f"Updated {_fmt_dt(nv.ts)} ({_ago(nv.ts)})"))

    if nv.stale:
        pills.insert(0, _pill("bad", "STALE · stopped reporting"))
    elif nv.health_state == "warning" and nv.age_minutes is not None and nv.age_minutes > 15:
        pills.insert(0, _pill("warn", "DELAYED · reporting slow"))
    else:
        sev = (nv.advice_sev or "ok").lower()
        if sev == "bad":
            pills.insert(0, _pill("bad", f"ADVICE · BAD {nv.advice_counts.get('bad', 0)}"))
        elif sev == "warn":
            pills.insert(0, _pill("warn", f"ADVICE · WARN {nv.advice_counts.get('warn', 0)}"))
        else:
            pills.insert(0, _pill("neutral", "ADVICE · OK"))

    top_action = _top_action(nv)
    top_action_line = ""
    if top_action and top_action[0] in ("bad", "warn", "stale"):
        sev, msg = top_action
        top_action_line = (
            f'<div style="margin-top:8px;">'
            f'{_pill("bad" if sev in ("bad","stale") else "warn", "Recommendation")} '
            f'<span class="muted" style="font-size:13px;">{_html_escape(msg)}</span>'
            f"</div>"
        )

    ram_pct = 0.0 if nv.ram_used_pct is None else _clamp(nv.ram_used_pct, 0, 100)
    used_label = "—" if nv.ram_used_pct is None else f"{ram_pct:.2f}%"

    debug_html = _render_debug(nv) if debug else ""

    return f"""
    <section class="card" id="node-{nv.node_id}">
      <div class="cardtop">
        <div class="left">
          <div class="title">
            <span class="{dot}"></span>
            <a class="nodename" href="/node/{_html_escape(nv.node)}?hours={hours}">{_html_escape(nv.node)}</a>
            <span class="model">{_html_escape(model)}</span>
          </div>
          <div class="nodever {agent_state}">
            Agent {_html_escape(nv.agent_version or 'unknown')}{' · behind' if agent_state == 'behind' else ''}
          </div>
          <div class="subtitle">{_html_escape(nv.headline)}</div>
          {top_action_line}
        </div>
        <div class="right">
          {''.join(pills)}
        </div>
      </div>

      <div class="row row2">
        <div class="kvbox">
          <div class="k">CPU</div>
          <div class="v big">{_html_escape(nv.cpu or '—')}</div>
        </div>
        <div class="kvbox">
          <div class="k">BIOS</div>
          <div class="v big">{_html_escape(nv.bios or '—')}</div>
        </div>
        <div class="rammeta">
          <div class="ramtop">
            <div class="k">RAM</div>
            <div class="ramright">{_html_escape(nv.ram_total.splitlines()[0] if nv.ram_total else "—")}</div>
          </div>
          <div class="bar ram"><div class="fill" style="width:{ram_pct:.1f}%"></div></div>
          <div class="rambottom">
            <div class="muted">Used: {_html_escape(used_label)}</div>
            <div class="muted rightmuted">{_html_escape(nv.ram_total.splitlines()[1] if "\n" in nv.ram_total else "")}</div>
          </div>
        </div>
      </div>

      <details class="details">
        <summary>Details <span class="detailsmuted">Storage · GPUs · Advice · Trends{(' · Debug' if debug else '')}</span></summary>

        <div class="row row3">
          <div class="panel">
            <div class="ph">STORAGE (PHYSICAL)</div>
            <div class="pv">{_render_storage_physical(nv.disks_physical)}</div>
          </div>
          <div class="panel">
            <div class="ph">GPUS</div>
            <div class="pv">{_render_gpus(nv.gpus)}</div>
          </div>
          <div class="panel">
            <div class="ph">ADVICE</div>
            <div class="pv">{_render_advice(nv.advice)}</div>
          </div>
        </div>

        {debug_html}

        <div class="trendrow">
          {_trend_block("RAM trend", nv.trend_ram_svg)}
          {_trend_block("Disk trend", nv.trend_disk_svg)}
          {_trend_block("GPU trend", nv.trend_gpu_svg, "No GPU detected" if not nv.gpus else None)}
        </div>
      </details>
    </section>
    """


def _facts_pick(payload: Dict[str, Any]) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    raw = _raw_payload(payload)
    facts = _get_facts(payload)
    raw_facts = raw.get("facts") if isinstance(raw.get("facts"), dict) else {}
    return facts, raw_facts


def _inventory_row(node: str, payload: Dict[str, Any], ts: str) -> Dict[str, Any]:
    facts, raw_facts = _facts_pick(payload)

    model = raw_facts.get("model") or facts.get("model")
    cpu = raw_facts.get("cpu") or facts.get("cpu")
    bios = _bios_display(facts, raw_facts)
    agent_version = payload.get("agent_version") or "unknown"

    ram_total_gb = raw_facts.get("ram_total_gb") or facts.get("ram_total_gb")
    ram_max_gb = raw_facts.get("ram_max_gb") or facts.get("ram_max_gb")
    ram_slots_total = raw_facts.get("ram_slots_total") or facts.get("ram_slots_total")
    ram_slots_used = raw_facts.get("ram_slots_used") or facts.get("ram_slots_used")
    ram_type = raw_facts.get("ram_type") or facts.get("ram_type")

    bios_date = raw_facts.get("bios_release_date") or facts.get("bios_release_date")

    disks = facts.get("disks") if isinstance(facts.get("disks"), list) else []
    gpus = facts.get("gpus") if isinstance(facts.get("gpus"), list) else []

    metrics = _get_metrics(payload)
    if not gpus:
        gpus = _get_gpu_list(metrics, _raw_payload(payload))

    def clean_list(xs: List[Any], keys: List[str]) -> List[Dict[str, Any]]:
        out = []
        for x in xs:
            if not isinstance(x, dict):
                continue
            out.append({k: x.get(k) for k in keys if k in x})
        return out

    return {
        "node": node,
        "last_seen": ts,
        "agent_version": agent_version,
        "model": model,
        "cpu": cpu,
        "bios_version": bios,
        "bios_release_date": bios_date,
        "ram_total_gb": ram_total_gb,
        "ram_max_gb": ram_max_gb,
        "ram_slots_total": ram_slots_total,
        "ram_slots_used": ram_slots_used,
        "ram_type": ram_type,
        "disks": clean_list(disks, ["name", "type", "size_gb", "model", "serial"]),
        "gpus": clean_list(gpus, ["name", "driver", "bus_id", "mem_total_mb"]),
    }


def _inventory_md(rows: List[Dict[str, Any]]) -> str:
    lines: List[str] = []
    lines.append("# HARRY — Hardware Inventory")
    lines.append("")
    for r in rows:
        lines.append(f"## {r.get('node')}")
        lines.append(f"- Last seen: `{r.get('last_seen')}`")
        lines.append(f"- Agent: `{r.get('agent_version') or 'unknown'}`")
        lines.append(f"- Model: `{r.get('model') or '—'}`")
        lines.append(f"- CPU: `{r.get('cpu') or '—'}`")
        rt = r.get("ram_total_gb")
        rm = r.get("ram_max_gb")
        rs = r.get("ram_slots_total")
        ru = r.get("ram_slots_used")
        rtype = r.get("ram_type")
        ram_bits = []
        if rt is not None:
            ram_bits.append(f"{rt}GB")
        if rm is not None and rm != rt:
            ram_bits.append(f"max {rm}GB")
        if rs is not None:
            ram_bits.append(f"slots {ru or '—'}/{rs}")
        if rtype:
            ram_bits.append(str(rtype))
        lines.append(f"- RAM: `{ ' · '.join(ram_bits) if ram_bits else '—' }`")
        lines.append(f"- BIOS: `{r.get('bios_version') or '—'}` ({r.get('bios_release_date') or '—'})")

        disks = r.get("disks") or []
        if disks:
            lines.append("- Disks:")
            for d in disks:
                nm = d.get("name") or "disk"
                tp = d.get("type") or "unknown"
                sz = d.get("size_gb")
                mdl = d.get("model") or ""
                lines.append(f"  - `{nm}` {tp} {sz}GB {('- ' + mdl) if mdl else ''}".rstrip())
        else:
            lines.append("- Disks: `—`")

        gpus = r.get("gpus") or []
        if gpus:
            lines.append("- GPUs:")
            for g in gpus:
                lines.append(f"  - `{g.get('name') or 'GPU'}`")
        else:
            lines.append("- GPUs: `—`")

        lines.append("")
    return "\n".join(lines).strip() + "\n"


@router.get("/ui/health")
def ui_health() -> PlainTextResponse:
    return PlainTextResponse("ok\n")


@router.get("/inventory")
def inventory(request: Request) -> Any:
    fmt = (request.query_params.get("format") or "json").lower().strip()

    with _db() as conn:
        if not _db_has_ingest(conn):
            if fmt == "md":
                return PlainTextResponse("# HARRY — Hardware Inventory\n\n_No ingest data yet._\n", media_type="text/markdown")
            return JSONResponse({"ok": False, "error": "no_ingest_table"}, status_code=200)

        latest = _fetch_latest_per_node(conn)
        rows: List[Dict[str, Any]] = []
        for node, rec in latest.items():
            payload = rec.get("payload") if isinstance(rec.get("payload"), dict) else {}
            rows.append(_inventory_row(node, payload, rec.get("ts") or ""))

        rows.sort(key=lambda r: str(r.get("node") or ""))

    if fmt == "md":
        return PlainTextResponse(_inventory_md(rows), media_type="text/markdown")
    return JSONResponse({"generated_at": _utcnow().isoformat().replace("+00:00", "Z"), "nodes": rows})


@router.get("/", response_class=HTMLResponse)
def index(request: Request) -> HTMLResponse:
    hours_q = request.query_params.get("hours", None)
    try:
        hours = int(hours_q) if hours_q is not None else DUMP_DEFAULT_HOURS
    except Exception:
        hours = DUMP_DEFAULT_HOURS
    hours = int(_clamp(hours, 1, 24 * 14))

    debug = (request.query_params.get("debug") or "").strip().lower() in ("1", "true", "yes", "y")

    with _db() as conn:
        if not _db_has_ingest(conn):
            return HTMLResponse("<h1>HARRY</h1><p>No DB / ingest table yet.</p>", status_code=200)

        latest = _fetch_latest_per_node(conn)
        nodeviews: List[NodeView] = []
        for node, rec in latest.items():
            nodeviews.append(_build_node_view(conn, node, rec, hours=hours))

        def sort_key(nv: NodeView) -> Tuple[int, int, str]:
            if nv.stale:
                return (0, 0, nv.node)
            if (nv.advice_sev or "ok") == "bad":
                return (1, -int(nv.advice_counts.get("bad", 0)), nv.node)
            if (nv.advice_sev or "ok") == "warn":
                return (2, -int(nv.advice_counts.get("warn", 0)), nv.node)
            return (3, 0, nv.node)

        nodeviews.sort(key=sort_key)

        generated = _utcnow().isoformat().replace("+00:00", "Z")
        brain_name = (os.environ.get("HARRY_BRAIN_NODE") or "brain").strip()
        schema_current = _load_schema_current()

        stale_n = sum(1 for n in nodeviews if n.stale)
        bad_n = sum(1 for n in nodeviews if not n.stale and (n.advice_sev or "ok") == "bad")
        warn_n = sum(1 for n in nodeviews if not n.stale and (n.advice_sev or "ok") == "warn")

        advice_queue_html = _render_advice_queue(nodeviews)
        shortlist_html = _render_upgrade_shortlist(nodeviews, max_items=12)

        fleet_map_html = f"""
<div class="section" id="fleet">
  <div class="sectionhead">
    <div>
      <div class="h2">Fleet map</div>
      <div class="h2sub">Brain → nodes, with freshness + actual agent version per node.</div>
    </div>
    <div class="actions">
      <a class="btn" href="/inventory">Export inventory (JSON)</a>
      <a class="btn" href="/inventory?format=md">Export inventory (MD)</a>
      <a class="btn" href="/dump?hours={hours}">Export dump ({hours}h)</a>
    </div>
  </div>

  <div class="mapwrap">
    {_render_fleet_map(nodeviews, brain_name=brain_name)}
    <div class="legend">
      <span class="item"><span class="dot ok"></span> <span>fresh</span> <span class="mut">· within {int(STALE_SECONDS//60)}m</span></span>
      <span class="item"><span class="dot stale"></span> <span>stale</span> <span class="mut">· stopped reporting</span></span>
      <span class="item"><span class="dot warn"></span> <span>advice badge</span> <span class="mut">· WARN/BAD count</span></span>
      <span class="item"><span class="mut">Tip:</span> click a node name to jump to its card</span>
    </div>
  </div>
</div>
"""

        inventory_html = f"""
<div class="section" id="inventory">
  <div class="sectionhead">
    <div>
      <div class="h2">Inventory at a glance</div>
      <div class="h2sub">Hardware facts + a visible advice flag (because Harry is meant to have opinions).</div>
    </div>
    <div class="actions">
      <a class="btn" href="/inventory">Inventory (JSON)</a>
      <a class="btn" href="/inventory?format=md">Inventory (MD)</a>
      <a class="btn" href="/dump?hours={hours}">Dump ({hours}h)</a>
      <a class="btn" href="/?hours={hours}">Refresh</a>
    </div>
  </div>

  <div class="invwrap">
    {_render_inventory_table(nodeviews)}
  </div>
</div>
"""

        shortlist_section_html = f"""
<div class="section" id="shortlist">
  <div class="sectionhead">
    <div>
      <div class="h2">Upgrade shortlist</div>
      <div class="h2sub">The loud bits. Sorted by “do something about it”.</div>
    </div>
    <div class="actions">
      <a class="btn" href="#details">Details</a>
      <a class="btn" href="#inventory">Inventory</a>
    </div>
  </div>
  {shortlist_html}
</div>
"""

        node_details_html = f"""
<div class="section" id="details">
  <div class="sectionhead">
    <div>
      <div class="h2">Node details</div>
      <div class="h2sub">Everything else. Open when you’re nosy. (You are.)</div>
    </div>
    <div class="actions">
      <a class="btn" href="#fleet">Back to fleet</a>
      <a class="btn" href="#inventory">Back to inventory</a>
      <a class="btn" href="#advice">Back to advice</a>
    </div>
  </div>

  <div class="nodes" id="node-details">
    {''.join(_render_node_card(nv, hours=hours, debug=debug) for nv in nodeviews)}
  </div>
</div>
"""

        footer_versions_html = (
            f'<div class="footerline">'
            f'Harry Brain {_html_escape(BRAIN_VERSION)} | '
            f'Dist Agent {_html_escape(AGENT_VERSION)} | '
            f'Schema {_html_escape(schema_current)}'
            f"</div>"
        )

        debug_chip = f'<a class="chip" href="/?hours={hours}&debug=0">Debug <span class="tiny">(on)</span></a>' if debug else f'<a class="chip" href="/?hours={hours}&debug=1">Debug <span class="tiny">(off)</span></a>'

        html = f"""
<!doctype html>
<html>
<head>
  <meta charset="utf-8"/>
  <meta name="viewport" content="width=device-width, initial-scale=1"/>
  <title>HARRY — HARdware Review buddY</title>
  <style>{CSS}</style>
</head>
<body>
  <div class="page">
    <div class="h1">HARRY — HARdware Review buddY</div>
    <div class="sub">
      <span>Generated {generated}</span>
      <span>·</span>
      <span>{stale_n} stale</span>
      <span>·</span>
      <span>{bad_n} bad</span>
      <span>·</span>
      <span>{warn_n} warn</span>
      <span>·</span>
      <a href="/dump?hours={hours}">/dump?hours={hours}</a>
      <span>·</span>
      <a href="/inventory">/inventory</a>
      <span>·</span>
      <a href="/inventory?format=md">inventory.md</a>
      <span>·</span>
      <a href="/?hours={hours}">refresh</a>
    </div>

    <div class="navchips">
      <a class="chip" href="#advice">Recommendations <span class="tiny">({bad_n + warn_n + stale_n})</span></a>
      <a class="chip" href="#fleet">Fleet <span class="tiny">({len(nodeviews)})</span></a>
      <a class="chip" href="#shortlist">Shortlist</a>
      <a class="chip" href="#inventory">Inventory</a>
      <a class="chip" href="#details">Details</a>
      {debug_chip}
    </div>

    {_render_top_banner(nodeviews)}

    {advice_queue_html}
    <div class="divider"></div>

    {fleet_map_html}
    <div class="divider"></div>

    {shortlist_section_html}
    <div class="divider"></div>

    {inventory_html}
    <div class="divider"></div>

    {node_details_html}

    {footer_versions_html}
  </div>

  <script>{JS_PULSE}</script>
</body>
</html>
"""
        return HTMLResponse(html)


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
    hours = int(_clamp(hours, 1, 24 * 30))
    with _db() as conn:
        latest = _fetch_latest_per_node(conn)
        nodes: Dict[str, Any] = {}
        for node, rec in latest.items():
            hist = _fetch_history(conn, node, hours=hours, limit=500)
            nodes[node] = {"latest": rec, "history": hist}
        return JSONResponse({"generated_at": _utcnow().isoformat().replace("+00:00", "Z"), "hours": hours, "nodes": nodes})


@router.get("/node/{node}", response_class=HTMLResponse)
def node_detail(request: Request, node: str) -> HTMLResponse:
    hours_q = request.query_params.get("hours", None)
    try:
        hours = int(hours_q) if hours_q is not None else DUMP_DEFAULT_HOURS
    except Exception:
        hours = DUMP_DEFAULT_HOURS
    hours = int(_clamp(hours, 1, 24 * 14))

    node = node.strip()
    with _db() as conn:
        cur = conn.execute("SELECT ts, node, payload FROM ingest WHERE node = ? ORDER BY ts DESC LIMIT 1", (node,))
        row = cur.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="not_found")

        try:
            payload = json.loads(row["payload"])
        except Exception:
            payload = {"bad_payload": True, "raw": row["payload"]}

        raw = _raw_payload(payload)

        pretty_payload = _html_escape(json.dumps(payload, indent=2, ensure_ascii=False))
        pretty_raw = _html_escape(json.dumps(raw, indent=2, ensure_ascii=False)) if raw else "—"

        html = f"""
<!doctype html>
<html>
<head>
  <meta charset="utf-8"/>
  <meta name="viewport" content="width=device-width, initial-scale=1"/>
  <title>HARRY • {_html_escape(node)}</title>
  <style>
    * {{ box-sizing: border-box; }}
    html, body {{ margin:0; padding:0; overflow-x:hidden; }}
    body {{
      padding: 18px;
      font-family: ui-sans-serif, system-ui, -apple-system, Segoe UI, Roboto, Helvetica, Arial;
      background: #070b14; color: rgba(255,255,255,0.92);
    }}
    a {{ color: inherit; text-decoration: none; }}
    a:hover {{ text-decoration: underline; }}
    .wrap {{ max-width: 1100px; margin: 0 auto; }}
    .h1 {{ font-size: 22px; font-weight: 900; margin: 0 0 6px; }}
    .sub {{ color: rgba(255,255,255,0.65); font-size: 12.5px; margin: 0 0 14px; display:flex; gap:12px; flex-wrap:wrap; }}
    .panel {{
      border: 1px solid rgba(255,255,255,0.10);
      background: rgba(255,255,255,0.04);
      border-radius: 14px;
      padding: 12px;
      margin: 12px 0;
    }}
    pre {{
      margin: 0;
      padding: 12px;
      border-radius: 12px;
      overflow: auto;
      background: rgba(0,0,0,0.35);
      border: 1px solid rgba(255,255,255,0.08);
      font-size: 12px;
      line-height: 1.35;
    }}
  </style>
</head>
<body>
  <div class="wrap">
    <div class="h1">{_html_escape(node)}</div>
    <div class="sub">
      <span>{_html_escape(row["ts"])}</span>
      <span>•</span>
      <a href="/?hours={hours}">Back</a>
      <span>•</span>
      <a href="/debug/latest/{_html_escape(node)}">debug/latest</a>
      <span>•</span>
      <a href="/dump?hours={hours}">dump?hours={hours}</a>
    </div>

    <div class="panel">
      <div style="font-weight:900; margin-bottom:10px;">Normalised payload (stored in DB)</div>
      <pre>{pretty_payload}</pre>
    </div>

    <div class="panel">
      <div style="font-weight:900; margin-bottom:10px;">Raw payload (if captured)</div>
      <pre>{pretty_raw}</pre>
    </div>
  </div>
</body>
</html>
"""
        return HTMLResponse(html)
