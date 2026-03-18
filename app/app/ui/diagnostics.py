from __future__ import annotations

from typing import Any, Dict, List

from app.versions import AGENT_VERSION, BRAIN_VERSION
from app.ui.db import _load_schema_current
from app.ui.fleet import build_nodeviews, _render_advice_queue
from app.ui.templates import _html_escape, render_shell


def _diagnostics_sidebar(hours: int, debug: bool) -> List[Dict[str, Any]]:
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
                {"label": "Comparison Table", "href": f"/inventory?hours={hours}{debug_q}#comparison-table", "sub": True},
                {"label": "Details", "href": f"/inventory?hours={hours}{debug_q}#node-details", "sub": True},
            ],
        },
        {
            "label": "Diagnostics",
            "items": [
                {"label": "Summary", "href": f"/diagnostics?hours={hours}{debug_q}", "sub": True},
                {"label": "Recommendations", "href": "#recommendations", "sub": True},
                {"label": "Statistics", "href": "#statistics", "sub": True},
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


def _diagnostics_actions(hours: int, debug: bool) -> List[Dict[str, str]]:
    debug_target = "0" if debug else "1"
    return [
        {"label": "Dump JSON", "href": f"/dump?hours={hours}"},
        {"label": "Debug toggle", "href": f"/diagnostics?hours={hours}&debug={debug_target}"},
    ]


def render_diagnostics_page(hours: int, debug: bool) -> str:
    nodeviews = build_nodeviews(hours=hours)

    stale_n = sum(1 for n in nodeviews if n.stale)
    bad_n = sum(1 for n in nodeviews if not n.stale and (n.advice_sev or "ok") == "bad")
    warn_n = sum(1 for n in nodeviews if not n.stale and (n.advice_sev or "ok") == "warn")
    info_n = sum(
        1
        for n in nodeviews
        if not n.stale and any(str(a.get("severity") or "").lower() == "info" for a in (n.advice or []))
    )
    healthy_n = max(0, len(nodeviews) - stale_n - bad_n - warn_n)

    behind = sum(
        1
        for n in nodeviews
        if n.agent_version not in ("", "unknown") and n.agent_version != AGENT_VERSION
    )

    delayed = sum(
        1
        for n in nodeviews
        if (not n.stale) and n.health_state == "warning" and (n.age_minutes is not None and n.age_minutes > 15)
    )

    advice_total = sum(len(n.advice or []) for n in nodeviews)

    schema_current = _load_schema_current()
    sidebar_footer = (
        f"<strong>Brain</strong> {_html_escape(BRAIN_VERSION)}<br/>"
        f"<strong>Agent</strong> {_html_escape(AGENT_VERSION)}<br/>"
        f"<strong>Schema</strong> {_html_escape(schema_current)}"
    )

    page_subtitle = (
        f"<span>{stale_n} stale</span>"
        f"<span>·</span><span>{bad_n} bad</span>"
        f"<span>·</span><span>{warn_n} warn</span>"
        f"<span>·</span><span>{info_n} info</span>"
    )

    content = f"""
<div class="section" id="diagnostic-summary">
  <div class="sectionhead">
    <div>
      <div class="h2">Summary</div>
      <div class="h2sub">Operational counts across the fleet.</div>
    </div>
  </div>

  <div class="stats">
    <div class="stat">
      <div class="statk">Nodes</div>
      <div class="statv">{len(nodeviews)}</div>
    </div>
    <div class="stat">
      <div class="statk">Healthy</div>
      <div class="statv">{healthy_n}</div>
    </div>
    <div class="stat">
      <div class="statk">Attention</div>
      <div class="statv">{bad_n + warn_n}</div>
    </div>
    <div class="stat">
      <div class="statk">Stale</div>
      <div class="statv">{stale_n}</div>
    </div>
  </div>
</div>

<div class="divider"></div>

<div class="section" id="recommendations">
  <div class="sectionhead">
    <div>
      <div class="h2">Recommendations</div>
      <div class="h2sub">Multiple findings, ordered by severity.</div>
    </div>
  </div>
  {_render_advice_queue(nodeviews)}
</div>

<div class="divider"></div>

<div class="section" id="statistics">
  <div class="sectionhead">
    <div>
      <div class="h2">Statistics</div>
      <div class="h2sub">Simple operational counts.</div>
    </div>
  </div>

  <div class="invwrap">
    <table class="inv">
      <tbody>
        <tr><td>Total nodes</td><td>{len(nodeviews)}</td></tr>
        <tr><td>Healthy nodes</td><td>{healthy_n}</td></tr>
        <tr><td>Stale nodes</td><td>{stale_n}</td></tr>
        <tr><td>Bad findings</td><td>{bad_n}</td></tr>
        <tr><td>Warn findings</td><td>{warn_n}</td></tr>
        <tr><td>Info findings</td><td>{info_n}</td></tr>
        <tr><td>Delayed reporters</td><td>{delayed}</td></tr>
        <tr><td>Total advice items</td><td>{advice_total}</td></tr>
        <tr><td>Agent version mismatch</td><td>{behind}</td></tr>
        <tr><td>Expected agent version</td><td>{AGENT_VERSION}</td></tr>
      </tbody>
    </table>
  </div>
</div>
"""

    return render_shell(
        title="HARRY — Diagnostics",
        active_page="diagnostics",
        page_title="Diagnostics",
        page_subtitle=page_subtitle,
        sidebar_sections=_diagnostics_sidebar(hours=hours, debug=debug),
        actions=_diagnostics_actions(hours=hours, debug=debug),
        content=content,
        sidebar_footer=sidebar_footer,
    )
