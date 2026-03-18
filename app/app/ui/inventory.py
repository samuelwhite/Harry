from __future__ import annotations

from typing import Any, Dict, List, Tuple

from app.versions import AGENT_VERSION, BRAIN_VERSION

from .db import (
    _db,
    _db_has_ingest,
    _fetch_latest_per_node,
    _get_facts,
    _get_metrics,
    _load_schema_current,
    _raw_payload,
)
from .templates import _html_escape, render_shell


def _inventory_sidebar(hours: int, debug: bool) -> List[Dict[str, Any]]:
    debug_q = "&debug=1" if debug else ""
    return [
        {
            "label": "Fleet",
            "items": [
                {"label": "Overview", "href": f"/?hours={hours}{debug_q}", "sub": True},
                {"label": "Nodes", "href": f"/?hours={hours}{debug_q}#fleet-table", "sub": True},
                {"label": "Trends", "href": f"/?hours={hours}{debug_q}#fleet-trends", "sub": True},
                {"label": "Hidden Nodes", "href": f"/?hours={hours}{debug_q}#hidden-nodes", "sub": True},
            ],
        },
        {
            "label": "Inventory",
            "items": [
                {"label": "Summary", "href": f"/inventory?hours={hours}{debug_q}", "sub": True},
                {"label": "Comparison Table", "href": "#comparison-table", "sub": True},
                {"label": "Details", "href": "#node-details", "sub": True},
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


def _inventory_actions(hours: int, debug: bool) -> List[Dict[str, str]]:
    return [
        {"label": "Inventory JSON", "href": f"/inventory.json?hours={hours}"},
        {"label": "Inventory Markdown", "href": f"/inventory?hours={hours}&format=md"},
    ]


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


def build_inventory_rows(latest: Dict[str, Dict[str, Any]]) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    for node, rec in latest.items():
        payload = rec.get("payload") if isinstance(rec.get("payload"), dict) else {}
        rows.append(_inventory_row(node, payload, rec.get("ts") or ""))
    rows.sort(key=lambda r: str(r.get("node") or ""))
    return rows


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
        lines.append(f"- RAM: `{' · '.join(ram_bits) if ram_bits else '—'}`")
        lines.append(f"- BIOS: `{r.get('bios_version') or '—'}` ({r.get('bios_release_date') or '—'})")

        disks = r.get("disks") or []
        if disks:
            lines.append("- Disks:")
            for d in disks:
                name = d.get("name") or d.get("model") or "disk"
                size = d.get("size_gb")
                dtype = d.get("type") or "—"
                size_txt = f"{size}GB" if size is not None else "—"
                lines.append(f"  - `{name}` · `{dtype}` · `{size_txt}`")

        gpus = r.get("gpus") or []
        if gpus:
            lines.append("- GPUs:")
            for g in gpus:
                name = g.get("name") or "gpu"
                mem = g.get("mem_total_mb")
                mem_txt = f"{mem}MB" if mem is not None else "—"
                lines.append(f"  - `{name}` · `{mem_txt}`")

        lines.append("")

    return "\n".join(lines).strip() + "\n"


def _fmt_ram(r: Dict[str, Any]) -> str:
    rt = r.get("ram_total_gb")
    rm = r.get("ram_max_gb")
    rs = r.get("ram_slots_total")
    ru = r.get("ram_slots_used")
    rtype = r.get("ram_type")

    parts: List[str] = []
    if rt is not None:
        parts.append(f"{rt}GB")
    if rm is not None and rm != rt:
        parts.append(f"max {rm}GB")
    if rs is not None:
        parts.append(f"slots {ru or '—'}/{rs}")
    if rtype:
        parts.append(str(rtype))

    return " · ".join(parts) if parts else "—"


def _fmt_disk_brief(disks: List[Dict[str, Any]]) -> str:
    if not disks:
        return "—"

    bits: List[str] = []
    for d in disks[:3]:
        name = d.get("name") or d.get("model") or "disk"
        dtype = d.get("type") or "—"
        size = d.get("size_gb")
        size_txt = f"{size}GB" if size is not None else "—"
        bits.append(f"{name} · {dtype} · {size_txt}")

    extra = len(disks) - 3
    if extra > 0:
        bits.append(f"+{extra} more")

    return "<br>".join(bits)


def _fmt_gpu_brief(gpus: List[Dict[str, Any]]) -> str:
    if not gpus:
        return "—"

    bits: List[str] = []
    for g in gpus[:2]:
        name = g.get("name") or "gpu"
        mem = g.get("mem_total_mb")
        mem_txt = f"{mem}MB" if mem is not None else "—"
        bits.append(f"{name} · {mem_txt}")

    extra = len(gpus) - 2
    if extra > 0:
        bits.append(f"+{extra} more")

    return "<br>".join(bits)


def render_inventory_page(hours: int, debug: bool) -> str:
    with _db() as conn:
        if not _db_has_ingest(conn):
            rows = []
        else:
            latest = _fetch_latest_per_node(conn)
            rows = build_inventory_rows(latest)

    node_count = len(rows)
    disk_count = sum(len(r.get("disks") or []) for r in rows)
    gpu_count = sum(len(r.get("gpus") or []) for r in rows)
    with_bios_date = sum(1 for r in rows if r.get("bios_release_date"))

    table_rows: List[str] = []
    detail_cards: List[str] = []

    for r in rows:
        node = r.get("node") or "—"
        model = r.get("model") or "—"
        cpu = r.get("cpu") or "—"
        ram = _fmt_ram(r)
        bios = r.get("bios_version") or "—"
        last_seen = r.get("last_seen") or "—"
        agent = r.get("agent_version") or "unknown"
        disks = r.get("disks") or []
        gpus = r.get("gpus") or []

        table_rows.append(
            f"""
<tr>
  <td><a href="/node/{node}?hours={hours}">{node}</a></td>
  <td>{model}</td>
  <td>{cpu}</td>
  <td>{ram}</td>
  <td>{bios}</td>
  <td>{len(disks)}</td>
  <td>{len(gpus)}</td>
</tr>
"""
        )

        detail_cards.append(
            f"""
<div class="card">
  <div class="sectionhead">
    <div>
      <div class="h2"><a href="/node/{node}?hours={hours}">{node}</a></div>
      <div class="h2sub">{model}</div>
    </div>
    <div class="pill">{last_seen}</div>
  </div>

  <div class="kvgrid">
    <div class="kv"><div class="k">CPU</div><div class="v">{cpu}</div></div>
    <div class="kv"><div class="k">RAM</div><div class="v">{ram}</div></div>
    <div class="kv"><div class="k">BIOS</div><div class="v">{bios}</div></div>
    <div class="kv"><div class="k">BIOS Date</div><div class="v">{r.get('bios_release_date') or '—'}</div></div>
    <div class="kv"><div class="k">Agent</div><div class="v">{agent}</div></div>
    <div class="kv"><div class="k">Last Seen</div><div class="v">{last_seen}</div></div>
  </div>

  <div class="splitcols">
    <div class="subcard">
      <div class="subcardtitle">Storage</div>
      <div class="subcardbody">{_fmt_disk_brief(disks)}</div>
    </div>
    <div class="subcard">
      <div class="subcardtitle">Graphics</div>
      <div class="subcardbody">{_fmt_gpu_brief(gpus)}</div>
    </div>
  </div>
</div>
"""
        )

    schema_current = _load_schema_current()
    sidebar_footer = (
        f"<strong>Brain</strong> {_html_escape(BRAIN_VERSION)}<br/>"
        f"<strong>Agent</strong> {_html_escape(AGENT_VERSION)}<br/>"
        f"<strong>Schema</strong> {_html_escape(schema_current)}"
    )

    page_subtitle = "<span>Hardware comparison view</span>"

    content = f"""
<div class="section" id="inventory-overview">
  <div class="sectionhead">
    <div>
      <div class="h2">Summary</div>
      <div class="h2sub">Hardware-aware comparison across the fleet.</div>
    </div>
  </div>

  <div class="stats">
    <div class="stat">
      <div class="statk">Nodes</div>
      <div class="statv">{node_count}</div>
    </div>
    <div class="stat">
      <div class="statk">Disks</div>
      <div class="statv">{disk_count}</div>
    </div>
    <div class="stat">
      <div class="statk">GPUs</div>
      <div class="statv">{gpu_count}</div>
    </div>
    <div class="stat">
      <div class="statk">BIOS Dates</div>
      <div class="statv">{with_bios_date}</div>
    </div>
  </div>
</div>

<div class="section" id="comparison-table">
  <div class="sectionhead">
    <div>
      <div class="h2">Comparison Table</div>
      <div class="h2sub">Quick side-by-side fleet view.</div>
    </div>
  </div>

  <div class="invwrap">
    <table class="inv">
      <thead>
        <tr>
          <th>Node</th>
          <th>Model</th>
          <th>CPU</th>
          <th>RAM</th>
          <th>BIOS</th>
          <th>Disks</th>
          <th>GPUs</th>
        </tr>
      </thead>
      <tbody>
        {''.join(table_rows) if table_rows else '<tr><td colspan="7">No inventory data available.</td></tr>'}
      </tbody>
    </table>
  </div>
</div>

<div class="section" id="node-details">
  <div class="sectionhead">
    <div>
      <div class="h2">Details</div>
      <div class="h2sub">Per-node hardware cards.</div>
    </div>
  </div>

  <div class="cardgrid">
    {''.join(detail_cards) if detail_cards else '<div class="empty">No inventory records found.</div>'}
  </div>
</div>
"""

    return render_shell(
        title="HARRY — Inventory",
        active_page="inventory",
        page_title="Inventory",
        page_subtitle=page_subtitle,
        sidebar_sections=_inventory_sidebar(hours=hours, debug=debug),
        actions=_inventory_actions(hours=hours, debug=debug),
        content=content,
        sidebar_footer=sidebar_footer,
    )
