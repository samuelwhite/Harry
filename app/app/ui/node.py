from __future__ import annotations

import json
from typing import Any, Dict, List

from fastapi import HTTPException

from app.versions import AGENT_VERSION, BRAIN_VERSION

from .db import get_latest_node_record, _load_schema_current, _raw_payload
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
    row = get_latest_node_record(node.strip())
    if not row:
        raise HTTPException(status_code=404, detail="not_found")

    try:
        payload = json.loads(row["payload"])
    except Exception:
        payload = {"bad_payload": True, "raw": row["payload"]}

    raw = _raw_payload(payload)

    pretty_payload = _html_escape(json.dumps(payload, indent=2, ensure_ascii=False))
    pretty_raw = _html_escape(json.dumps(raw, indent=2, ensure_ascii=False)) if raw else "—"

    schema_current = _load_schema_current()
    sidebar_footer = (
        f"<strong>Brain</strong> {_html_escape(BRAIN_VERSION)}<br/>"
        f"<strong>Agent</strong> {_html_escape(AGENT_VERSION)}<br/>"
        f"<strong>Schema</strong> {_html_escape(schema_current)}"
    )

    page_subtitle = (
        f"<span>{_html_escape(row['ts'])}</span>"
        f"<span>·</span><span>Inspect stored payload and captured raw data</span>"
    )

    content = f"""
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
        title=f"HARRY • {node}",
        active_page="node",
        page_title=node,
        page_subtitle=page_subtitle,
        sidebar_sections=_node_sidebar(node=node, hours=hours),
        actions=_node_actions(node=node, hours=hours),
        content=content,
        sidebar_footer=sidebar_footer,
    )
