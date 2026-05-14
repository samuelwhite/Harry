from __future__ import annotations

import json
from typing import Any, Dict, List

from fastapi import HTTPException

from app.machine_summary import get_machine_summary
from app.node_metadata import node_display_name, node_meta_summary, node_route_id, prime_privacy_aliases
from app.node_metadata import privacy_mode_enabled
from app.versions import AGENT_VERSION, BRAIN_VERSION
from app.ui.fleet import _advice_normalised_snapshot, _render_advice_summary

from .db import get_latest_node_record, get_latest_node_records, _load_schema_current, _raw_payload
from .templates import _html_escape, render_shell


def _node_sidebar(node: str, hours: int) -> List[Dict[str, Any]]:
    node_esc = _html_escape(node)
    return [
        {
            "label": "Fleet",
            "items": [
                {"label": "Overview", "href": f"/?hours={hours}#fleet-overview", "sub": True},
                {"label": "Nodes", "href": f"/?hours={hours}#fleet-table", "sub": True},
                {"label": "Trends", "href": f"/?hours={hours}#fleet-trends", "sub": True},
                {"label": "Hidden Nodes", "href": f"/?hours={hours}#hidden-nodes", "sub": True},
            ],
        },
        {
            "label": "Inventory",
            "items": [
                {"label": "Comparison Table", "href": f"/inventory?hours={hours}#comparison-table", "sub": True},
                {"label": "Details", "href": f"/inventory?hours={hours}#node-details", "sub": True},
            ],
        },
        {
            "label": "Diagnostics",
            "items": [
                {"label": "Summary", "href": f"/diagnostics?hours={hours}#diagnostic-summary", "sub": True},
                {"label": "Recommendations", "href": f"/diagnostics?hours={hours}#recommendations", "sub": True},
                {"label": "Statistics", "href": f"/diagnostics?hours={hours}#statistics", "sub": True},
            ],
        },
        {
            "label": "Node",
            "items": [
                {"label": "Normalised payload", "href": "#normalised-payload", "sub": True},
                {"label": "Raw payload", "href": "#raw-payload", "sub": True},
            ],
        },
	{
	    "label": "Downloads",
	    "items": [
	        {"label": "Agent Installers", "href": "/downloads#downloads-overview", "page": "downloads", "sub": True},
	        {"label": "Available Downloads", "href": "/downloads#downloads-files", "page": "downloads", "sub": True},
	        {"label": "Instructions", "href": "/downloads#downloads-instructions", "page": "downloads", "sub": True},
	    ],
	},
    ]


def _node_actions(node: str, hours: int) -> List[Dict[str, str]]:
    node_esc = _html_escape(node)
    return [
        {"label": "debug/latest", "href": f"/debug/latest/{node_esc}"},
        {"label": "Dump JSON", "href": f"/dump?hours={hours}"},
    ]


def render_node_detail(node: str, hours: int) -> str:
    node = node.strip()
    prime_privacy_aliases(list(get_latest_node_records().keys()))
    display_name = node_display_name(node)
    meta = node_meta_summary(node)
    row = get_latest_node_record(node)
    if not row:
        raise HTTPException(status_code=404, detail="not_found")

    try:
        payload = json.loads(row["payload"])
    except Exception:
        payload = {"bad_payload": True, "raw": row["payload"]}

    raw = _raw_payload(payload)
    summary = get_machine_summary(payload)
    advice = _advice_normalised_snapshot(payload)

    pretty_payload_text = json.dumps(payload, indent=2, ensure_ascii=False)
    pretty_raw_text = json.dumps(raw, indent=2, ensure_ascii=False) if raw else ""
    if privacy_mode_enabled():
        pretty_payload_text = pretty_payload_text.replace(node, display_name)
        pretty_raw_text = pretty_raw_text.replace(node, display_name)

    pretty_payload = _html_escape(pretty_payload_text)
    pretty_raw = _html_escape(pretty_raw_text) if raw else "—"
    summary_html = ""
    if summary and summary.get("summary"):
        summary_html = f"""
<div class="section" id="machine-summary">
  <div class="sectionhead">
    <div>
      <div class="h2">Machine summary</div>
      <div class="h2sub">Optional local summary, cached for quick viewing.</div>
    </div>
    <div class="pill">{_html_escape(str(summary.get("source") or "local"))}</div>
  </div>

  <div class="panel">
    <div class="subtitle" style="margin:0;">{_html_escape(str(summary.get("summary") or ""))}</div>
  </div>
</div>
"""

    advice_html = ""
    if advice:
        advice_html = f"""
<div class="section" id="node-recommendations">
  <div class="sectionhead">
    <div>
      <div class="h2">Recommendations</div>
      <div class="h2sub">User-actionable guidance for this node.</div>
    </div>
  </div>

  <div class="panel">
    {_render_advice_summary(advice)}
  </div>
</div>
"""

    schema_current = _load_schema_current()
    sidebar_footer = (
        f"<strong>Brain</strong> {_html_escape(BRAIN_VERSION)}<br/>"
        f"<strong>Agent</strong> {_html_escape(AGENT_VERSION)}<br/>"
        f"<strong>Schema</strong> {_html_escape(schema_current)}"
    )

    subtitle_bits = [
        f"<span>{_html_escape(row['ts'])}</span>",
        "<span>·</span><span>Inspect stored payload and captured raw data</span>",
    ]
    if meta:
        subtitle_bits.extend([f"<span>·</span><span>{_html_escape(meta)}</span>"])
    page_subtitle = "".join(subtitle_bits)

    content = f"""
{summary_html}

{advice_html}

<div class="section" id="normalised-payload">
  <div class="sectionhead">
    <div>
      <div class="h2">Normalised payload</div>
      <div class="h2sub">Stored in the database.</div>
    </div>
  </div>

  <div class="panel">
    <pre style="margin:0; padding:12px; border-radius:12px; overflow:auto; background:rgba(0,0,0,0.35); border:1px solid rgba(255,255,255,0.08); font-size:12px; line-height:1.35;">{pretty_payload}</pre>
  </div>
</div>

<div class="section" id="raw-payload">
  <div class="sectionhead">
    <div>
      <div class="h2">Raw payload</div>
      <div class="h2sub">Captured extension/raw payload if available.</div>
    </div>
  </div>

  <div class="panel">
    <pre style="margin:0; padding:12px; border-radius:12px; overflow:auto; background:rgba(0,0,0,0.35); border:1px solid rgba(255,255,255,0.08); font-size:12px; line-height:1.35;">{pretty_raw}</pre>
  </div>
</div>
"""

    return render_shell(
        title=f"HARRY • {display_name}",
        active_page="node",
        page_title=display_name,
        page_subtitle=page_subtitle,
        sidebar_sections=_node_sidebar(node=node_route_id(node), hours=hours),
        actions=_node_actions(node=node_route_id(node), hours=hours),
        content=content,
        sidebar_footer=sidebar_footer,
    )
