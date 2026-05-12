from __future__ import annotations

import ipaddress
from typing import Any, Dict, List

from fastapi import Request

from app.brain_address import discovery_methods_enabled, resolve_brain_address
from app.versions import AGENT_VERSION, BRAIN_VERSION, display_agent_version
from app.ui.db import _load_schema_current
from app.ui.fleet import build_nodeviews, _render_advice_queue, _service_status_class, _service_status_label
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


def _discovery_rows(request: Request) -> List[tuple[str, str, str]]:
    info = resolve_brain_address(request)
    host = (request.headers.get("host") or request.url.hostname or "").strip()
    scheme = (request.url.scheme or "http").strip().lower()
    reverse_proxy = "No"
    if host:
        try:
            addr = ipaddress.ip_address(host.split(":", 1)[0])
        except ValueError:
            if scheme == "https":
                reverse_proxy = "Likely"
        else:
            if addr.version == 4 and not addr.is_loopback and not addr.is_link_local and not addr.is_unspecified:
                reverse_proxy = "No"

    canonical = info.get("canonical_base_url") or "Not set"
    recommended = info.get("recommended_lan_url") or "Not detected"
    display = info.get("display_url") or "Could not determine"
    warning = info.get("warning") or "None"
    installer = "Ready" if info.get("display_url") else "Manual input required"
    container_runtime = "Yes" if info.get("container_runtime") else "No"
    detected_lan = info.get("detected_lan_ip") or "Not detected"
    rejected = info.get("rejected_lan_candidates") or []
    rejected_txt = ", ".join(str(x) for x in rejected[:8]) if rejected else "None"
    methods = ", ".join(discovery_methods_enabled())

    return [
        ("Brain Address", "online", f"Other machines should use: {display}"),
        ("Canonical address", "online" if info.get("canonical_base_url") else "warning", str(canonical)),
        ("Recommended LAN", "online" if info.get("recommended_lan_url") else "warning", str(recommended)),
        ("Discovery endpoint", "online", "Installers can query /discover or /.well-known/harry-brain."),
        ("Reverse proxy", "info" if reverse_proxy == "Likely" else "online", reverse_proxy),
        ("Container networking", "warn" if info.get("container_runtime") else "online", container_runtime),
        ("Detected LAN address", "online" if info.get("detected_lan_ip") else "warning", str(detected_lan)),
        ("Rejected addresses", "warning" if rejected else "online", rejected_txt),
        ("Discovery methods", "online", methods),
        ("Installer discovery", "online" if info.get("display_url") else "warning", installer),
        ("Warning", "warning" if info.get("warning") else "online", warning),
    ]


def _render_action_card(title: str, body: str, status: str = "info") -> str:
    return f"""
<div class="card compactcard">
  <div class="advrow" style="align-items:flex-start;">
    <div class="advleft">
      <div class="advnode">{_html_escape(title)}</div>
      <div class="advmsg">{_html_escape(body)}</div>
    </div>
    <span class="badgetxt {_service_status_class(status)}">{_html_escape(_service_status_label(status))}</span>
  </div>
</div>
"""


def render_diagnostics_page(request: Request, hours: int, debug: bool) -> str:
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
        if display_agent_version(n.agent_version) not in ("", "unknown") and display_agent_version(n.agent_version) != AGENT_VERSION
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

    brain_rows = _discovery_rows(request)
    brain_status = next((status for label, status, _ in brain_rows if label == "Brain Address"), "info")
    config_status = next((status for label, status, _ in brain_rows if label == "Canonical address"), "info")
    brain_display = next((text for label, _, text in brain_rows if label == "Brain Address"), "Other machines should use the Brain address shown below.")
    canonical_display = next((text for label, _, text in brain_rows if label == "Canonical address"), "Set HARRY_PUBLIC_BASE_URL to define the canonical Brain address.")
    recommendation_lines = [
        "Set HARRY_PUBLIC_BASE_URL if installers cannot find the Brain.",
        "Install or restart the local agent if this machine is stale.",
        "Use the Downloads page to verify the installer link and Brain address.",
    ]

    content = f"""
<div class="section" id="diagnostic-summary">
  <div class="sectionhead">
    <div>
      <div class="h2">Summary</div>
      <div class="h2sub">Actionable status at a glance.</div>
    </div>
  </div>

  <div class="cardgrid">
    {_render_action_card("Brain reachable?", brain_display, brain_status)}
    {_render_action_card("Agents reporting?", f"{healthy_n} healthy, {stale_n} stale, {behind} behind", "warn" if stale_n or behind else "ok")}
    {_render_action_card("Installer address configured?", canonical_display, config_status)}
    {_render_action_card("Recommended actions", " · ".join(recommendation_lines), "info")}
  </div>
</div>

<div class="divider"></div>

<div class="section" id="recommendations">
  <div class="sectionhead">
    <div>
      <div class="h2">Recommendations</div>
      <div class="h2sub">What to do next if something needs attention.</div>
    </div>
  </div>
  {_render_advice_queue(nodeviews)}
</div>

<div class="divider"></div>

<details class="card compactcard" id="advanced-diagnostics">
  <summary style="cursor:pointer; list-style:none; display:flex; align-items:center; justify-content:space-between; gap:12px;">
    <div>
      <div class="h2" style="margin:0;">Advanced diagnostics</div>
      <div class="h2sub">Low-level address and discovery details for troubleshooting.</div>
    </div>
  </summary>
  <div class="advwrap" style="margin-top:16px;">
    {''.join(
      f'<div class="advrow"><div class="advleft"><div class="advnode">{_html_escape(label)}</div><div class="advmsg">{_html_escape(text)}</div></div><span class="badgetxt {_service_status_class(status)}">{_html_escape(_service_status_label(status))}</span></div>'
      for label, status, text in brain_rows
    )}
  </div>
</details>

<div class="divider"></div>

<div class="section" id="fleet-status">
  <div class="sectionhead">
    <div>
      <div class="h2">Fleet status</div>
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
