from __future__ import annotations

import json
import os
from dataclasses import dataclass
from statistics import mean
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import quote

from app.health import compute_health
from app.rules import evaluate as rules_evaluate
from app.versions import AGENT_VERSION, BRAIN_VERSION
from app.ui.db import (
    STALE_SECONDS,
    _db,
    _fnum,
    _fetch_history,
    _fetch_latest_hidden_per_node,
    _get_facts,
    _get_metrics,
    _load_schema_current,
    _parse_ts,
    _raw_payload,
    _safe_str,
    _utcnow,
    _clamp,
)
from app.ui.templates import (
    _ago,
    _badge_text,
    _fmt_dt,
    _html_escape,
    _pill,
    _safe_dom_id,
    _sev_dot,
    render_shell,
)

try:
    from app.advice_engine import build_advice_and_health as advice_build
except Exception:
    advice_build = None


SCREENSHOT_NAME_ALIASES = {
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


def _screenshot_mode_enabled() -> bool:
    return (os.environ.get("HARRY_SCREENSHOT_MODE") or "").strip().lower() in ("1", "true", "yes", "on")


def _display_node_name(name: str) -> str:
    clean = (name or "").strip()
    if not _screenshot_mode_enabled():
        return clean
    return SCREENSHOT_NAME_ALIASES.get(clean, clean)


def _fleet_sidebar(hours: int, debug: bool) -> List[Dict[str, Any]]:
    debug_q = "&debug=1" if debug else ""
    return [
        {
            "label": "Fleet",
            "items": [
                {"label": "Overview", "href": f"/?hours={hours}{debug_q}", "sub": True},
                {"label": "Nodes", "href": "#fleet-table", "sub": True},
                {"label": "Trends", "href": "#fleet-trends", "sub": True},
                {"label": "Hidden Nodes", "href": "#hidden-nodes", "sub": True},
            ],
        },
        {
            "label": "Inventory",
            "items": [
                {"label": "Summary", "href": f"/inventory?hours={hours}{debug_q}", "sub": True},
                {"label": "Comparison Table", "href": f"/inventory?hours={hours}{debug_q}#comparison-table", "sub": True},
                {"label": "Details", "href": f"/inventory?hours={hours}{debug_q}#node-details", "sub": True},
            ],
        },
        {
            "label": "Diagnostics",
            "items": [
                {"label": "Summary", "href": f"/diagnostics?hours={hours}{debug_q}", "sub": True},
                {"label": "Recommendations", "href": f"/diagnostics?hours={hours}{debug_q}#recommendations", "sub": True},
                {"label": "Statistics", "href": f"/diagnostics?hours={hours}{debug_q}#statistics", "sub": True},
            ],
        },
        {
            "label": "Downloads",
            "items": [
                {"label": "Agent Installers", "href": "/downloads#downloads-overview", "page": "downloads", "sub": True},
                {"label": "Available Downloads", "href": "/downloads#downloads-files", "page": "downloads", "sub": True},
                {"label": "Add a Node", "href": "/downloads#downloads-instructions", "page": "downloads", "sub": True},
            ],
        },
    ]


def _global_actions(hours: int, debug: bool) -> List[Dict[str, str]]:
    debug_target = "0" if debug else "1"
    return [
        {"label": "Dump JSON", "href": f"/dump?hours={hours}"},
        {"label": "Inventory JSON", "href": f"/inventory.json?hours={hours}"},
        {"label": "Debug toggle", "href": f"/?hours={hours}&debug={debug_target}"},
    ]


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
        cpu = src.get("cpu")
        if isinstance(cpu, dict):
            for k in ("load_1", "load1", "load_avg_1m", "load"):
                v2 = _fnum(cpu.get(k))
                if v2 is not None:
                    return v2
    return None


def _ram_total_display(facts: Dict[str, Any], raw_facts: Dict[str, Any]) -> str:
    for src in (raw_facts, facts):
        ram_total_gb = src.get("ram_total_gb")
        ram_max_gb = src.get("ram_max_gb")
        ram_slots_total = src.get("ram_slots_total")
        ram_type = src.get("ram_type")

        if ram_total_gb:
            if ram_max_gb and str(ram_max_gb) != str(ram_total_gb):
                base = f"{ram_total_gb}GB / firmware max {ram_max_gb}GB"
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
    if s == "info":
        return "info"
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
                    "severity": "info",
                    "message": f"RAM headroom available: {int(rt)}GB installed, supports {int(rm)}GB. (+{gap}GB potential).",
                    "evidence": {"ram_total_gb": rt, "ram_max_gb": rm},
                }
            )
    except Exception:
        pass

    sev_rank = {"bad": 0, "warn": 1, "info": 2, "ok": 3}
    out.sort(key=lambda a: (sev_rank.get(str(a.get("severity") or "ok").lower(), 9), str(a.get("message") or "").lower()))
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


def _pick_disk_used_pct(metrics: Dict[str, Any]) -> Optional[float]:
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

    return chosen_disk


def _to_float(x: Any) -> Optional[float]:
    try:
        if x is None or x == "":
            return None
        return float(x)
    except Exception:
        return None


def _to_int(x: Any) -> Optional[int]:
    try:
        if x is None or x == "":
            return None
        return int(float(x))
    except Exception:
        return None


def _logical_cores(facts: Dict[str, Any], raw_facts: Dict[str, Any], metrics: Dict[str, Any], raw_metrics: Dict[str, Any]) -> Optional[int]:
    candidates: List[Any] = []

    for src in (raw_facts, facts, raw_metrics, metrics):
        if not isinstance(src, dict):
            continue
        candidates.extend(
            [
                src.get("logical_cores"),
                src.get("cpu_threads"),
                src.get("threads"),
                src.get("thread_count"),
                src.get("cpu_logical_cores"),
                src.get("cpu_cores"),
                src.get("cores"),
                src.get("cpu_count"),
            ]
        )
        ex = src.get("extensions")
        if isinstance(ex, dict):
            candidates.extend(
                [
                    ex.get("logical_cores"),
                    ex.get("cpu_threads"),
                    ex.get("threads"),
                    ex.get("cpu_cores"),
                ]
            )
        cpu = src.get("cpu")
        if isinstance(cpu, dict):
            candidates.extend(
                [
                    cpu.get("logical_cores"),
                    cpu.get("threads"),
                    cpu.get("count"),
                    cpu.get("cpu_threads"),
                    cpu.get("cpu_cores"),
                ]
            )

    for c in candidates:
        v = _to_int(c)
        if v is not None and v > 0:
            return v
    return None


def _cpu_pressure_pct(load_value: Optional[float], logical_cores: Optional[int]) -> Optional[float]:
    if load_value is None or logical_cores is None or logical_cores <= 0:
        return None
    return max(0.0, (float(load_value) / float(logical_cores)) * 100.0)


def _clamp_pct(v: Optional[float], hi: float = 200.0) -> Optional[float]:
    if v is None:
        return None
    return max(0.0, min(float(v), hi))


def _mean_or_none(vals: List[Optional[float]]) -> Optional[float]:
    cleaned = [float(v) for v in vals if v is not None]
    return mean(cleaned) if cleaned else None


def _max_or_none(vals: List[Optional[float]]) -> Optional[float]:
    cleaned = [float(v) for v in vals if v is not None]
    return max(cleaned) if cleaned else None


def _cpu_pressure_band(v: Optional[float]) -> str:
    if v is None:
        return "unknown"
    if v < 40:
        return "idle"
    if v < 65:
        return "moderate"
    if v < 85:
        return "elevated"
    if v < 100:
        return "saturated"
    return "overloaded"


def _cpu_pressure_advice(now_v: Optional[float], avg_v: Optional[float], peak_v: Optional[float]) -> List[Dict[str, Any]]:
    advice: List[Dict[str, Any]] = []

    if avg_v is not None and avg_v >= 85:
        advice.append(
            {
                "severity": "bad",
                "message": "Sustained high CPU pressure over the last 72h.",
                "evidence": {"avg72_cpu_pressure_pct": round(avg_v, 1)},
            }
        )
    elif avg_v is not None and avg_v >= 65:
        advice.append(
            {
                "severity": "warn",
                "message": "Moderately elevated CPU pressure over the last 72h.",
                "evidence": {"avg72_cpu_pressure_pct": round(avg_v, 1)},
            }
        )

    if peak_v is not None and peak_v >= 120:
        advice.append(
            {
                "severity": "warn",
                "message": "CPU demand exceeded estimated core capacity at peak times.",
                "evidence": {"peak72_cpu_pressure_pct": round(peak_v, 1)},
            }
        )

    if now_v is not None and now_v >= 100:
        advice.append(
            {
                "severity": "warn",
                "message": "Current CPU demand is at or above estimated core capacity.",
                "evidence": {"current_cpu_pressure_pct": round(now_v, 1)},
            }
        )

    return advice


def _temp_pressure_pct(temp_c: Optional[float]) -> float:
    if temp_c is None:
        return 0.0
    return float(_clamp(((temp_c - 20.0) / 80.0) * 100.0, 0.0, 100.0))


def _activity_score(
    cpu_pressure_avg_72h: Optional[float],
    ram_used_pct: Optional[float],
    temp_c: Optional[float],
    disk_used_pct: Optional[float],
) -> float:
    cpu_v = float(cpu_pressure_avg_72h or 0.0)
    ram_v = float(ram_used_pct or 0.0)
    temp_v = _temp_pressure_pct(temp_c)
    disk_v = float(disk_used_pct or 0.0)
    return round((cpu_v * 0.50) + (ram_v * 0.30) + (temp_v * 0.15) + (disk_v * 0.05), 2)


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


def _line_chart(
    values: List[Optional[float]],
    w: int = 900,
    h: int = 110,
    y_min: Optional[float] = None,
    y_max: Optional[float] = None,
) -> str:
    pts: List[Tuple[float, float]] = []
    vs = [v for v in values if v is not None]
    if len(vs) < 3:
        return ""

    lo = min(vs) if y_min is None else y_min
    hi = max(vs) if y_max is None else y_max

    if hi <= lo:
        hi = lo + 1.0

    if y_min is None or y_max is None:
        span = hi - lo
        pad = 0.5 if span < 0.5 else span * 0.15
        lo -= pad
        hi += pad

    n = len(values)

    for i, v in enumerate(values):
        if v is None:
            continue
        x = (i / max(1, n - 1)) * (w - 20) + 10
        y = (1 - ((v - lo) / (hi - lo))) * (h - 20) + 10
        pts.append((x, y))

    if len(pts) < 2:
        return ""

    d = "M " + " L ".join(f"{x:.2f},{y:.2f}" for x, y in pts)

    return f"""
<svg viewBox="0 0 {w} {h}" preserveAspectRatio="none" class="widechart" xmlns="http://www.w3.org/2000/svg">
  <rect x="0" y="0" width="{w}" height="{h}" rx="12" fill="rgba(255,255,255,0.02)"/>
  <line x1="10" y1="{h-10}" x2="{w-10}" y2="{h-10}" stroke="rgba(255,255,255,0.10)" stroke-width="1"/>
  <line x1="10" y1="{h/2:.2f}" x2="{w-10}" y2="{h/2:.2f}" stroke="rgba(255,255,255,0.06)" stroke-width="1"/>
  <line x1="10" y1="10" x2="{w-10}" y2="10" stroke="rgba(255,255,255,0.04)" stroke-width="1"/>
  <path d="{d}" fill="none" stroke="rgba(255,255,255,0.80)" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"/>
</svg>
"""


def _trend_series(history: List[Dict[str, Any]], logical_cores: Optional[int] = None) -> Dict[str, List[Optional[float]]]:
    ram: List[Optional[float]] = []
    disk: List[Optional[float]] = []
    gpu: List[Optional[float]] = []
    cpu: List[Optional[float]] = []
    temp: List[Optional[float]] = []

    for row in history:
        p = row.get("payload") if isinstance(row.get("payload"), dict) else {}
        raw = _raw_payload(p)
        metrics = _get_metrics(p)
        raw_metrics = raw.get("metrics") if isinstance(raw.get("metrics"), dict) else {}

        ram.append(_get_ram_used_pct(metrics, raw_metrics))

        load_val = _get_load(metrics, raw_metrics)
        cpu.append(_clamp_pct(_cpu_pressure_pct(load_val, logical_cores)))

        temp.append(_cpu_temp(metrics, raw_metrics))
        disk.append(_pick_disk_used_pct(metrics))

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

    return {"ram": ram, "disk": disk, "gpu": gpu, "cpu": cpu, "temp": temp}


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


def _node_action_url(node: str, action: str, next_url: str) -> str:
    return f"/node/{quote(node, safe='')}/{action}?next={quote(next_url, safe='')}"


def _action_form(url: str, label: str, confirm_text: Optional[str] = None) -> str:
    confirm_attr = f' onclick="return confirm(\'{_html_escape(confirm_text)}\')"' if confirm_text else ""
    return (
        f'<form method="post" action="{_html_escape(url)}" style="display:inline-block; margin:0 6px 6px 0;">'
        f'<button class="btn" type="submit"{confirm_attr}>{_html_escape(label)}</button>'
        f"</form>"
    )


@dataclass
class NodeView:
    node: str
    node_id: str
    model: str
    cpu: str
    bios: str
    agent_version: str
    ram_total: str
    logical_cores: Optional[int]
    ram_used_pct: Optional[float]
    load1: Optional[float]
    cpu_pressure_now: Optional[float]
    cpu_pressure_avg_72h: Optional[float]
    cpu_pressure_peak_72h: Optional[float]
    cpu_pressure_band: str
    activity_score: float
    temp_c: Optional[float]
    disk_used_pct: Optional[float]
    gpu_used_pct: Optional[float]
    ts: Optional[Any]
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
    trend_cpu_svg: str
    trend_temp_svg: str
    trend_ram_wide_svg: str
    trend_disk_wide_svg: str
    trend_gpu_wide_svg: str
    trend_cpu_wide_svg: str
    trend_temp_wide_svg: str
    trend_ram_values: List[Optional[float]]
    trend_disk_values: List[Optional[float]]
    trend_gpu_values: List[Optional[float]]
    trend_cpu_values: List[Optional[float]]
    trend_temp_values: List[Optional[float]]
    debug: Dict[str, Any]


def build_node_view(conn, node: str, rec: Dict[str, Any], hours: int = 72) -> NodeView:
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

    stale = health_state == "critical" and any("stale" in str(r).lower() for r in (health.get("reasons") or []))

    model = _safe_str(raw_facts.get("model") or facts.get("model") or "")
    cpu = _safe_str(raw_facts.get("cpu") or facts.get("cpu") or "")
    bios = _bios_display(facts, raw_facts)
    agent_version = _safe_str(payload.get("agent_version") or "unknown")

    ram_total = _ram_total_display(facts, raw_facts)
    ram_used_pct = _get_ram_used_pct(metrics, raw_metrics)
    load1 = _get_load(metrics, raw_metrics)
    logical_cores = _logical_cores(facts, raw_facts, metrics, raw_metrics)
    cpu_pressure_now = _clamp_pct(_cpu_pressure_pct(load1, logical_cores))
    temp_c = _cpu_temp(metrics, raw_metrics)
    disk_used_pct = _pick_disk_used_pct(metrics)

    disks_physical = _get_disk_physical(payload, metrics, raw)
    gpus = _get_gpu_list(metrics, raw)

    hist = _fetch_history(conn, node, hours=hours)
    series = _trend_series(hist, logical_cores=logical_cores)
    gpu_used_pct = next((v for v in reversed(series["gpu"]) if v is not None), None)
    cpu_pressure_avg_72h = _mean_or_none(series["cpu"])
    cpu_pressure_peak_72h = _max_or_none(series["cpu"])
    cpu_pressure_band = _cpu_pressure_band(cpu_pressure_avg_72h if cpu_pressure_avg_72h is not None else cpu_pressure_now)
    activity_score = _activity_score(cpu_pressure_avg_72h, ram_used_pct, temp_c, disk_used_pct)

    advice = list(_advice_normalised_snapshot(payload))
    advice.extend(_cpu_pressure_advice(cpu_pressure_now, cpu_pressure_avg_72h, cpu_pressure_peak_72h))
    advice.sort(
        key=lambda a: (
            {"bad": 0, "warn": 1, "info": 2, "ok": 3}.get(str(a.get("severity") or "ok").lower(), 9),
            str(a.get("message") or "").lower(),
        )
    )

    delayed = health_state == "warning" and any("delayed" in str(r).lower() for r in (health.get("reasons") or []))

    if stale:
        advice = [{"severity": "bad", "message": f"Node has stopped reporting (last seen {_ago(ts)})."}] + advice
    elif delayed:
        advice = [{"severity": "warn", "message": f"Node reporting delayed (last seen {_ago(ts)})."}] + advice

    real_warn = sum(1 for a in advice if str(a.get("severity")).lower() == "warn")
    real_bad = sum(1 for a in advice if str(a.get("severity")).lower() == "bad")
    advice_sev = "bad" if real_bad else ("warn" if real_warn else "ok")

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

    debug: Dict[str, Any] = {}
    try:
        debug = {
            "facts": {
                "ram_total_gb": raw_facts.get("ram_total_gb") if raw_facts.get("ram_total_gb") is not None else facts.get("ram_total_gb"),
                "ram_max_gb": raw_facts.get("ram_max_gb") if raw_facts.get("ram_max_gb") is not None else facts.get("ram_max_gb"),
                "ram_slots_used": raw_facts.get("ram_slots_used") if raw_facts.get("ram_slots_used") is not None else facts.get("ram_slots_used"),
                "ram_slots_total": raw_facts.get("ram_slots_total") if raw_facts.get("ram_slots_total") is not None else facts.get("ram_slots_total"),
                "ram_type": raw_facts.get("ram_type") if raw_facts.get("ram_type") is not None else facts.get("ram_type"),
                "cpu_cores": raw_facts.get("cpu_cores") or facts.get("cpu_cores"),
                "logical_cores": logical_cores,
            },
            "metrics": {
                "mem_used_pct": raw_metrics.get("mem_used_pct") if raw_metrics else metrics.get("mem_used_pct"),
                "cpu_load_1m": raw_metrics.get("cpu_load_1m") if raw_metrics else metrics.get("cpu_load_1m"),
                "cpu_pressure_now_pct": cpu_pressure_now,
                "cpu_pressure_avg_72h_pct": cpu_pressure_avg_72h,
                "cpu_pressure_peak_72h_pct": cpu_pressure_peak_72h,
                "cpu_pressure_band": cpu_pressure_band,
                "activity_score": activity_score,
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
        logical_cores=logical_cores,
        ram_used_pct=ram_used_pct,
        load1=load1,
        cpu_pressure_now=cpu_pressure_now,
        cpu_pressure_avg_72h=cpu_pressure_avg_72h,
        cpu_pressure_peak_72h=cpu_pressure_peak_72h,
        cpu_pressure_band=cpu_pressure_band,
        activity_score=activity_score,
        temp_c=temp_c,
        disk_used_pct=disk_used_pct,
        gpu_used_pct=gpu_used_pct,
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
        trend_cpu_svg=_sparkline(series["cpu"]),
        trend_temp_svg=_sparkline(series["temp"]),
        trend_ram_wide_svg=_line_chart(series["ram"], y_min=0, y_max=100),
        trend_disk_wide_svg=_line_chart(series["disk"], y_min=0, y_max=100),
        trend_gpu_wide_svg=_line_chart(series["gpu"], y_min=0, y_max=100),
        trend_cpu_wide_svg=_line_chart(series["cpu"], y_min=0, y_max=200),
        trend_temp_wide_svg=_line_chart(series["temp"], y_min=20, y_max=100),
        trend_ram_values=series["ram"],
        trend_disk_values=series["disk"],
        trend_gpu_values=series["gpu"],
        trend_cpu_values=series["cpu"],
        trend_temp_values=series["temp"],
        debug=debug,
    )


def _top_action(nv: NodeView) -> Optional[Tuple[str, str]]:
    if nv.stale:
        return ("stale", f"Stopped reporting ({_ago(nv.ts)}).")
    if not nv.advice:
        return None
    for sev in ("bad", "warn", "info"):
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
        tag_class = "info" if sev == "info" else sev
        out.append(
            f"<div class='adviceitem'><span class='tag {tag_class}'>{_html_escape(sev)}</span>"
            f"<span class='msg'>{_html_escape(msg)}</span></div>"
        )
    return "".join(out)


def _render_debug(nv: NodeView) -> str:
    pretty = _html_escape(json.dumps(nv.debug or {}, indent=2, ensure_ascii=False))
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
        display_name = _display_node_name(nv.node)
        if nv.worst in ("bad", "warn", "stale"):
            if nv.worst == "stale":
                msg = f"{display_name} — Node has stopped reporting (last seen {_ago(nv.ts)})."
            elif nv.worst == "bad":
                msg = f"{display_name} — Needs attention."
            else:
                msg = f"{display_name} — Warning."
            pills.append(f"<span class='topwarn {nv.worst}'>{_html_escape(msg)}</span>")
    if not pills:
        pills.append("<span class='topwarn ok'>Nothing to report… yet.</span>")
    return f"<div class='topwarnwrap'>{''.join(pills)}</div>"


def _fleet_outlier_pills(nodeviews: List[NodeView]) -> str:
    active = [n for n in nodeviews if not n.stale]
    if not active:
        return ""

    pills: List[str] = []

    busiest = max(active, key=lambda n: n.cpu_pressure_avg_72h if n.cpu_pressure_avg_72h is not None else -1.0)
    if busiest.cpu_pressure_avg_72h is not None:
        pills.append(_pill("neutral", f"Busiest: {_display_node_name(busiest.node)} · Avg CPU {busiest.cpu_pressure_avg_72h:.0f}%"))

    hottest = max(active, key=lambda n: n.temp_c if n.temp_c is not None else -999.0)
    if hottest.temp_c is not None:
        pills.append(_pill("neutral", f"Hottest: {_display_node_name(hottest.node)} · {hottest.temp_c:.1f}°C"))

    rammiest = max(active, key=lambda n: n.ram_used_pct if n.ram_used_pct is not None else -1.0)
    if rammiest.ram_used_pct is not None:
        pills.append(_pill("neutral", f"Most RAM pressure: {_display_node_name(rammiest.node)} · {rammiest.ram_used_pct:.0f}%"))

    return f"<div class='actions' style='margin:10px 0 2px 0; flex-wrap:wrap;'>{''.join(pills)}</div>" if pills else ""


def _render_fleet_stats(nodeviews: List[NodeView]) -> str:
    total = len(nodeviews)
    stale_n = sum(1 for n in nodeviews if n.stale)
    bad_n = sum(1 for n in nodeviews if not n.stale and (n.advice_sev or "ok") == "bad")
    warn_n = sum(1 for n in nodeviews if not n.stale and (n.advice_sev or "ok") == "warn")
    healthy_n = max(0, total - stale_n - bad_n - warn_n)

    return f"""
<div class="section" id="fleet-stats">
  <div class="stats">
    <div class="stat">
      <div class="statk">Nodes</div>
      <div class="statv">{total}</div>
    </div>
    <div class="stat">
      <div class="statk">Healthy</div>
      <div class="statv">{healthy_n}</div>
    </div>
    <div class="stat">
      <div class="statk">Warnings</div>
      <div class="statv">{warn_n + bad_n}</div>
    </div>
    <div class="stat">
      <div class="statk">Stale</div>
      <div class="statv">{stale_n}</div>
    </div>
  </div>
</div>
"""


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

    pulse_recent_seconds = int(os.environ.get("HARRY_PULSE_RECENT_SECONDS", "90"))

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
        f'fill="rgba(255,255,255,0.70)" font-size="12">{_html_escape(_display_node_name(brain_name))}</text>'
    )

    now = _utcnow()

    for i, nv in enumerate(others):
        y = start_y + i * step
        sid = nv.node_id

        path_d = f"M {nx-40} {y} C {nx-120} {y}, {bx+260} {by}, {bx+150} {by}"
        svg.append(f'<path id="link-{sid}" class="linkline" d="{path_d}"/>')

        col = dot_color(nv.worst)
        svg.append(f'<circle id="dot-{sid}" class="nodeDot" cx="{nx-40}" cy="{y}" r="10" fill="{col}" filter="url(#g)"/>')

        label = _display_node_name(nv.node)
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
            f'<a xlink:href="/node/{_html_escape(nv.node)}" href="/node/{_html_escape(nv.node)}">'
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
                recent = (now - nv.ts).total_seconds() <= pulse_recent_seconds
            except Exception:
                recent = False

        if recent:
            svg.append(
                f"""
                <circle r="4" fill="rgba(255,255,255,0.80)" filter="url(#pg)">
                  <animateMotion dur="1.4s" repeatCount="1" path="{path_d}" />
                  <animate attributeName="r" values="3;5;3" dur="1.4s" repeatCount="1" />
                  <animate attributeName="opacity" values="0.0;1.0;0.0" dur="1.4s" repeatCount="1" />
                </circle>
                """
            )

    svg.append("</svg>")
    return "".join(svg)


def _render_inventory_table(nodeviews: List[NodeView], hours: int) -> str:
    rows: List[str] = []
    next_url = f"/?hours={hours}"

    for nv in nodeviews:
        display_name = _display_node_name(nv.node)
        dot = _sev_dot(nv.worst)
        model = nv.model or "—"
        cpu = nv.cpu or "—"
        ram_lines = nv.ram_total.splitlines() if nv.ram_total else []
        ram_main = ram_lines[0] if len(ram_lines) >= 1 else "—"
        ram_meta = ram_lines[1] if len(ram_lines) >= 2 else ""
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
            hint = ta[1] if ta else f"CPU {nv.cpu_pressure_band}"

        hide_btn = _action_form(_node_action_url(nv.node, "hide", next_url), "Hide")

        rows.append(
            f"""
<tr>
  <td class="status"><span class="{dot}"></span> <a href="/node/{_html_escape(nv.node)}">{_html_escape(display_name)}</a></td>
  <td>{_html_escape(model)}</td>
  <td>{_html_escape(cpu)}</td>
  <td class="right mono">
    <div>{_html_escape(ram_main)}</div>
    <div class="muted" style="margin-top:2px; font-size:12px;">{_html_escape(ram_meta)}</div>
  </td>
  <td class="mono">{_html_escape(bios)}</td>
  <td class="mono">{_html_escape(last)}</td>
  <td class="advicecol">{adv}<div class="advsmall">{_html_escape(hint)}</div></td>
  <td>{hide_btn}</td>
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
      <th>Actions</th>
    </tr>
  </thead>
  <tbody>
    {''.join(rows)}
  </tbody>
</table>
"""


def _render_advice_queue(nodeviews: List[NodeView]) -> str:
    items: List[Tuple[int, float, str, str, str, str]] = []

    sev_rank = {"stale": 0, "bad": 1, "warn": 2, "info": 3}

    for nv in nodeviews:
        if nv.stale:
            items.append((0, -(nv.activity_score), nv.node, "STALE", f"Stopped reporting (last seen {_ago(nv.ts)}).", nv.model or ""))
            continue

        for a in nv.advice:
            sev = str(a.get("severity") or "ok").lower()
            if sev not in ("bad", "warn", "info"):
                continue
            msg = _safe_str(a.get("message") or "").strip()
            if not msg:
                continue
            items.append((sev_rank.get(sev, 9), -(nv.activity_score), nv.node, sev.upper(), msg, nv.model or ""))

    if not items:
        return "<div class='muted'>No active recommendations.</div>"

    items.sort(key=lambda t: (t[0], t[1], t[2], t[4]))

    rows: List[str] = []
    for _, _, node, label, msg, model in items[:40]:
        display_name = _display_node_name(node)
        sev_cls = "stale" if label == "STALE" else label.lower()
        badge = _badge_text(sev_cls, label)
        rows.append(
            f"""
<div class="advrow">
  <div class="advleft">
    <div class="advnode"><a href="/node/{_html_escape(node)}">{_html_escape(display_name)}</a> <span class="advsmall">{_html_escape(model)}</span></div>
    <div class="advmsg">{_html_escape(msg)}</div>
  </div>
  <div class="advright">
    {badge}
  </div>
</div>
"""
        )
    return f"<div class='advwrap'>{''.join(rows)}</div>"


def _render_trend_chart_row(
    label: str,
    svg: str,
    latest_value: Optional[float],
    latest_fmt: str,
    scale_label: str,
    extra_meta: Optional[str] = None,
    fallback: str = "Collecting history...",
) -> str:
    meta_parts: List[str] = []
    latest_txt = "—"
    if latest_value is not None:
        latest_txt = latest_fmt.format(latest_value)
    meta_parts.append(f"Now {latest_txt}")
    if extra_meta:
        meta_parts.append(extra_meta)
    meta_parts.append(scale_label)

    meta_html = "".join(f"<span>{_html_escape(p)}</span>" for p in meta_parts)

    if not svg:
        return f"""
<div class="trendchartrow">
  <div class="trendcharthead">
    <div class="trendchartlabel">{_html_escape(label)}</div>
    <div class="trendchartmeta">
      {meta_html}
    </div>
  </div>
  <div class="trendchartbody"><span class="muted">{_html_escape(fallback)}</span></div>
  <div class="trendchartfoot">72h history</div>
</div>
"""

    return f"""
<div class="trendchartrow">
  <div class="trendcharthead">
    <div class="trendchartlabel">{_html_escape(label)}</div>
    <div class="trendchartmeta">
      {meta_html}
    </div>
  </div>
  <div class="trendchartbody">{svg}</div>
  <div class="trendchartfoot">72h history</div>
</div>
"""


def _render_fleet_trends(nodeviews: List[NodeView], hours: int) -> str:
    cards: List[str] = []

    for nv in nodeviews:
        display_name = _display_node_name(nv.node)
        pills: List[str] = []
        if nv.ram_used_pct is not None:
            pills.append(_pill("neutral", f"RAM {nv.ram_used_pct:.0f}%"))
        if nv.cpu_pressure_now is not None:
            pills.append(_pill("neutral", f"CPU pressure {nv.cpu_pressure_now:.1f}%"))
        elif nv.load1 is not None:
            pills.append(_pill("neutral", f"Load {nv.load1:.2f}"))
        pills.append(_pill("neutral", f"CPU {nv.cpu_pressure_band}"))
        if nv.temp_c is not None:
            pills.append(_pill("neutral", f"CPU {nv.temp_c:.1f}°C"))
        pills.append(_pill("neutral", f"Activity {nv.activity_score:.1f}"))
        pills.append(_pill("neutral", f"Updated {_ago(nv.ts)}"))

        cpu_extra = None
        cpu_meta_bits: List[str] = []
        if nv.cpu_pressure_avg_72h is not None:
            cpu_meta_bits.append(f"Avg72h {nv.cpu_pressure_avg_72h:.0f}%")
        if nv.cpu_pressure_peak_72h is not None:
            cpu_meta_bits.append(f"Peak {nv.cpu_pressure_peak_72h:.0f}%")
        if nv.logical_cores is not None:
            cpu_meta_bits.append(f"{nv.logical_cores} threads")
        if cpu_meta_bits:
            cpu_extra = " · ".join(cpu_meta_bits)

        trend_sections: List[str] = [
            _render_trend_chart_row("RAM usage", nv.trend_ram_wide_svg, nv.ram_used_pct, "{:.1f}%", "Scale 0–100%"),
            _render_trend_chart_row("CPU pressure", nv.trend_cpu_wide_svg, nv.cpu_pressure_now, "{:.1f}%", "Scale 0–200%", extra_meta=cpu_extra),
            _render_trend_chart_row("Temperature", nv.trend_temp_wide_svg, nv.temp_c, "{:.1f}°C", "Scale 20–100°C"),
            _render_trend_chart_row("Disk usage", nv.trend_disk_wide_svg, nv.disk_used_pct, "{:.1f}%", "Scale 0–100%"),
        ]

        if nv.gpus and nv.trend_gpu_wide_svg:
            trend_sections.append(
                _render_trend_chart_row("GPU activity", nv.trend_gpu_wide_svg, nv.gpu_used_pct, "{:.1f}%", "Scale 0–100%")
            )

        cards.append(
            f"""
<div class="card trendcard">
  <div class="sectionhead">
    <div>
      <div class="h2"><a href="/node/{_html_escape(nv.node)}?hours={hours}">{_html_escape(display_name)}</a></div>
      <div class="h2sub">{_html_escape(nv.model or nv.cpu or 'Hardware trends')}</div>
    </div>
    <div class="actions trendpills">
      {''.join(pills)}
    </div>
  </div>

  {''.join(trend_sections)}
</div>
"""
        )

    return f"""
<div class="section" id="fleet-trends">
  <div class="sectionhead">
    <div>
      <div class="h2">Trends</div>
      <div class="h2sub">Larger 72h graphs for persistent load, thermal behaviour, and pressure over time.</div>
    </div>
  </div>

  <div class="trendcards">
    {''.join(cards) if cards else '<div class="muted">No trend data available.</div>'}
  </div>
</div>
"""


def _render_hidden_nodes(hidden_nodes: List[NodeView], hours: int) -> str:
    if not hidden_nodes:
        return ""

    next_url = f"/?hours={hours}"
    rows: List[str] = []

    for nv in hidden_nodes:
        display_name = _display_node_name(nv.node)
        rows.append(
            f"""
<div class="advrow">
  <div class="advleft">
    <div class="advnode">{_html_escape(display_name)} <span class="advsmall">{_html_escape(nv.model or nv.cpu or '')}</span></div>
    <div class="advmsg">Hidden from Fleet, Inventory, and Diagnostics. Last seen {_html_escape(_ago(nv.ts))}.</div>
  </div>
  <div class="advright">
    {_action_form(_node_action_url(nv.node, "unhide", next_url), "Unhide")}
    {_action_form(_node_action_url(nv.node, "delete", next_url), "Delete", "Delete this node and all of its history permanently?")}
  </div>
</div>
"""
        )

    return f"""
<div class="section" id="hidden-nodes">
  <div class="sectionhead">
    <div>
      <div class="h2">Hidden nodes</div>
      <div class="h2sub">Excluded from the main interface until restored.</div>
    </div>
  </div>
  <div class="advwrap">
    {''.join(rows)}
  </div>
</div>
"""


def _render_node_card(nv: NodeView, hours: int, debug: bool) -> str:
    display_name = _display_node_name(nv.node)
    dot = _sev_dot(nv.worst)
    model = f" ({nv.model})" if nv.model else ""
    agent_state = _agent_version_state(nv.agent_version, AGENT_VERSION)

    pills: List[str] = []
    if nv.cpu_pressure_now is not None:
        pills.append(_pill("neutral", f"CPU pressure {nv.cpu_pressure_now:.1f}%"))
    elif nv.load1 is not None:
        pills.append(_pill("neutral", f"Load {nv.load1:.2f}"))
    pills.append(_pill("neutral", f"CPU {nv.cpu_pressure_band}"))
    if nv.temp_c is not None:
        pills.append(_pill("neutral", f"CPU {nv.temp_c:.1f}°C"))
    pills.append(_pill("neutral", f"Activity {nv.activity_score:.1f}"))
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
    if top_action and top_action[0] in ("bad", "warn", "stale", "info"):
        sev, msg = top_action
        pill_sev = "bad" if sev in ("bad", "stale") else ("warn" if sev == "warn" else "neutral")
        top_action_line = (
            f'<div style="margin-top:8px;">'
            f'{_pill(pill_sev, "Recommendation")} '
            f'<span class="muted" style="font-size:13px;">{_html_escape(msg)}</span>'
            f"</div>"
        )

    ram_pct = 0.0 if nv.ram_used_pct is None else _clamp(nv.ram_used_pct, 0, 100)
    used_label = "—" if nv.ram_used_pct is None else f"{ram_pct:.2f}%"
    debug_html = _render_debug(nv) if debug else ""

    detail_trends: List[str] = [
        _trend_block("RAM trend", nv.trend_ram_svg),
        _trend_block("CPU pressure", nv.trend_cpu_svg),
        _trend_block("Temperature", nv.trend_temp_svg),
        _trend_block("Disk trend", nv.trend_disk_svg),
    ]
    if nv.gpus and nv.trend_gpu_svg:
        detail_trends.append(_trend_block("GPU trend", nv.trend_gpu_svg))

    cpu_detail = "—"
    if nv.cpu_pressure_now is not None:
        cpu_bits = [f"{nv.cpu_pressure_now:.1f}%", nv.cpu_pressure_band]
        if nv.logical_cores is not None:
            cpu_bits.append(f"{nv.logical_cores} threads")
        if nv.load1 is not None:
            cpu_bits.append(f"load {nv.load1:.2f}")
        cpu_detail = " · ".join(cpu_bits)

    hide_url = _node_action_url(nv.node, "hide", f"/?hours={hours}")

    return f"""
<section class="card" id="node-{nv.node_id}">
  <div class="cardtop">
    <div class="left">
      <div class="title">
        <span class="{dot}"></span>
        <a class="nodename" href="/node/{_html_escape(nv.node)}?hours={hours}">{_html_escape(display_name)}</a>
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
      <div class="muted" style="margin-top:6px; font-size:12px;">Pressure {_html_escape(cpu_detail)}</div>
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
        <div class="muted rightmuted">{_html_escape(nv.ram_total.splitlines()[1] if "\\n" in nv.ram_total else "")}</div>
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

    <div class="actions" style="margin-top:12px;">
      {_action_form(hide_url, "Hide node")}
    </div>

    <div class="trendrow">
      {''.join(detail_trends)}
    </div>
  </details>
</section>
"""


def build_nodeviews(hours: int = 72) -> List[NodeView]:
    with _db() as conn:
        from app.ui.db import _db_has_ingest, _fetch_latest_per_node

        if not _db_has_ingest(conn):
            return []

        latest = _fetch_latest_per_node(conn)
        nodeviews: List[NodeView] = []
        for node, rec in latest.items():
            nodeviews.append(build_node_view(conn, node, rec, hours=hours))

    def sort_key(nv: NodeView) -> Tuple[int, float, float, str]:
        if nv.stale:
            return (0, 0.0, 0.0, nv.node)
        if (nv.advice_sev or "ok") == "bad":
            return (1, -nv.activity_score, -(nv.cpu_pressure_avg_72h or 0.0), nv.node)
        if (nv.advice_sev or "ok") == "warn":
            return (2, -nv.activity_score, -(nv.cpu_pressure_avg_72h or 0.0), nv.node)
        return (3, -nv.activity_score, -(nv.cpu_pressure_avg_72h or 0.0), nv.node)

    nodeviews.sort(key=sort_key)
    return nodeviews


def build_hidden_nodeviews(hours: int = 72) -> List[NodeView]:
    with _db() as conn:
        from app.ui.db import _db_has_ingest

        if not _db_has_ingest(conn):
            return []

        latest = _fetch_latest_hidden_per_node(conn)
        nodeviews: List[NodeView] = []
        for node, rec in latest.items():
            nodeviews.append(build_node_view(conn, node, rec, hours=hours))

    nodeviews.sort(key=lambda nv: nv.node)
    return nodeviews


def render_fleet_live(hours: int, debug: bool) -> str:
    nodeviews = build_nodeviews(hours=hours)
    hidden_nodeviews = build_hidden_nodeviews(hours=hours)
    brain_name = (os.environ.get("HARRY_BRAIN_NODE") or "brain").strip()

    fleet_stats_html = _render_fleet_stats(nodeviews)
    trends_html = _render_fleet_trends(nodeviews, hours=hours)
    hidden_html = _render_hidden_nodes(hidden_nodeviews, hours=hours)

    fleet_map_html = f"""
<div class="section" id="fleet-overview">
  <div class="sectionhead">
    <div>
      <div class="h2">Overview</div>
      <div class="h2sub">Map, freshness, versions.</div>
    </div>
  </div>

  <div class="mapwrap">
    {_render_fleet_map(nodeviews, brain_name=brain_name)}
    <div class="legend">
      <span class="item"><span class="dot ok"></span> <span>fresh</span> <span class="mut">· within {int(STALE_SECONDS//60)}m</span></span>
      <span class="item"><span class="dot stale"></span> <span>stale</span> <span class="mut">· stopped reporting</span></span>
      <span class="item"><span class="dot warn"></span> <span>advice</span> <span class="mut">· warn / bad</span></span>
    </div>
  </div>
</div>
"""

    if nodeviews:
        table_html = f"""
<div class="section" id="fleet-table">
  <div class="sectionhead">
    <div>
      <div class="h2">Nodes</div>
      <div class="h2sub">Compact operational view.</div>
    </div>
  </div>
  <div class="invwrap">
    {_render_inventory_table(nodeviews, hours=hours)}
  </div>
</div>
"""
    else:
        table_html = """
<div class="section" id="fleet-table">
  <div class="sectionhead">
    <div>
      <div class="h2">Nodes</div>
      <div class="h2sub">Compact operational view.</div>
    </div>
  </div>
  <div class="card">
    <div class="subtitle">Waiting for the first node to check in...</div>
  </div>
</div>
"""

    return f"""
<div id="fleet-live" data-node-count="{len(nodeviews)}">
  {_render_top_banner(nodeviews)}
  {_fleet_outlier_pills(nodeviews)}
  {fleet_stats_html}
  {fleet_map_html}
  <div class="divider"></div>
  {table_html}
  <div class="divider"></div>
  {trends_html}
  {hidden_html}
</div>
"""


def _fleet_polling_script(hours: int, debug: bool) -> str:
    debug_q = "&debug=1" if debug else ""
    return f"""
<script>
(function () {{
  let attempts = 0;
  let timer = null;
  const maxAttempts = 24;
  const url = "/fleet/partial?hours={hours}{debug_q}";

  async function refreshFleet() {{
    const current = document.getElementById("fleet-live");
    if (!current) return;

    try {{
      const res = await fetch(url, {{ cache: "no-store" }});
      if (!res.ok) return;

      const html = await res.text();
      const wrapper = document.createElement("div");
      wrapper.innerHTML = html.trim();
      const updated = wrapper.firstElementChild;
      if (!updated) return;

      current.replaceWith(updated);

      const count = parseInt(updated.getAttribute("data-node-count") || "0", 10);
      if (count > 0 && timer) {{
        clearInterval(timer);
        timer = null;
      }}
    }} catch (err) {{
      console.warn("Fleet refresh failed", err);
    }}

    attempts += 1;
    if (attempts >= maxAttempts && timer) {{
      clearInterval(timer);
      timer = null;
    }}
  }}

  timer = setInterval(refreshFleet, 5000);
  setTimeout(refreshFleet, 1500);
}})();
</script>
"""


def render_fleet_page(hours: int, debug: bool) -> str:
    nodeviews = build_nodeviews(hours=hours)
    generated = _utcnow().isoformat().replace("+00:00", "Z")
    schema_current = _load_schema_current()

    stale_n = sum(1 for n in nodeviews if n.stale)
    bad_n = sum(1 for n in nodeviews if not n.stale and (n.advice_sev or "ok") == "bad")
    warn_n = sum(1 for n in nodeviews if not n.stale and (n.advice_sev or "ok") == "warn")
    healthy_n = max(0, len(nodeviews) - stale_n - bad_n - warn_n)

    sidebar_footer = (
        f"Brain {_html_escape(BRAIN_VERSION)}<br/>"
        f"Agent {_html_escape(AGENT_VERSION)}<br/>"
        f"Schema {_html_escape(schema_current)}"
    )

    page_subtitle = (
        f"<span>Generated {generated}</span>"
        f"<span>·</span><span>{len(nodeviews)} nodes</span>"
        f"<span>·</span><span>{healthy_n} healthy</span>"
        f"<span>·</span><span>{stale_n} stale</span>"
        f"<span>·</span><span>{bad_n} bad</span>"
        f"<span>·</span><span>{warn_n} warn</span>"
    )

    content = f"""
{render_fleet_live(hours=hours, debug=debug)}
{_fleet_polling_script(hours=hours, debug=debug)}
"""

    return render_shell(
        title="HARRY — Fleet",
        active_page="fleet",
        page_title="Fleet",
        page_subtitle=page_subtitle,
        sidebar_sections=_fleet_sidebar(hours=hours, debug=debug),
        actions=_global_actions(hours=hours, debug=debug),
        content=content,
        sidebar_footer=sidebar_footer,
    )


def render_node_cards_page(hours: int, debug: bool) -> str:
    nodeviews = build_nodeviews(hours=hours)
    return f"""
<div class="section" id="details">
  <div class="sectionhead">
    <div>
      <div class="h2">Node details</div>
      <div class="h2sub">Full cards.</div>
    </div>
  </div>

  <div class="nodes" id="node-details">
    {''.join(_render_node_card(nv, hours=hours, debug=debug) for nv in nodeviews)}
  </div>
</div>
"""
