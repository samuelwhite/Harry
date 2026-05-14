from __future__ import annotations

import json
import ipaddress
import os
from pathlib import Path
from typing import Any, Dict, List

from fastapi import Request

from app.brain_address import discovery_methods_enabled, resolve_brain_address
from app.versions import AGENT_VERSION, BRAIN_VERSION, display_agent_version
from app.service_awareness import build_service_rows
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


def _downloads_dir() -> Path:
    configured = (os.environ.get("HARRY_DOWNLOADS_DIR") or "").strip()
    if configured:
        return Path(configured).expanduser()

    here = Path(__file__).resolve()
    candidates = [
        here.parents[1] / "downloads",
        here.parents[2] / "downloads",
        here.parents[3] / "downloads",
    ]
    for candidate in candidates:
        if candidate.exists():
            return candidate

    return here.parents[3] / "downloads"


def _windows_installer_manifest_path(installer_name: str) -> Path:
    return (_downloads_dir() / installer_name).with_suffix(".manifest.json")


def _load_windows_installer_manifest(installer_name: str) -> dict[str, object] | None:
    path = _windows_installer_manifest_path(installer_name)
    if not path.exists() or not path.is_file():
        return None

    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None

    return data if isinstance(data, dict) else None


def _windows_installer_is_current(installer_name: str, manifest: dict[str, object] | None) -> bool:
    if not manifest:
        return False

    schema_current = _load_schema_current()
    return (
        str(manifest.get("installer_name") or "") == installer_name
        and str(manifest.get("brain_version") or "") == BRAIN_VERSION
        and str(manifest.get("agent_version") or "") == AGENT_VERSION
        and str(manifest.get("schema_current") or "") == schema_current
    )


def _advanced_discovery_rows(request: Request) -> List[tuple[str, str, str]]:
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


def _summary_status(label: str, body: str, status: str, badge: str | None = None) -> tuple[str, str, str, str | None]:
    return (label, body, status, badge)


def _agent_summary(nodeviews) -> tuple[str, str, str, str | None]:
    total = len(nodeviews)
    stale_n = sum(1 for n in nodeviews if n.stale)
    current_n = sum(
        1
        for n in nodeviews
        if display_agent_version(n.agent_version) not in ("", "unknown") and display_agent_version(n.agent_version) == AGENT_VERSION
    )
    behind_n = sum(
        1
        for n in nodeviews
        if display_agent_version(n.agent_version) not in ("", "unknown") and display_agent_version(n.agent_version) != AGENT_VERSION
    )
    unknown_n = max(0, total - current_n - behind_n)

    if total == 0:
        return _summary_status("Agents reporting?", "No agents reporting yet.", "info", "Not set up yet")
    if stale_n or behind_n or unknown_n:
        body = f"{current_n} current, {behind_n} behind, {unknown_n} unknown"
        if stale_n:
            body += f", {stale_n} stale"
        return _summary_status("Agents reporting?", body, "warn", "Needs attention")
    if current_n == 1:
        return _summary_status("Agents reporting?", "1 current agent reporting.", "ok", "Healthy")
    return _summary_status("Agents reporting?", f"{current_n} current agents reporting.", "ok", "Healthy")


def _service_summary() -> tuple[str, str, str, str | None] | None:
    rows = build_service_rows()
    watched = [row for row in rows if "brain" not in [str(tag).strip().lower() for tag in (row.get("tags") or [])]]
    if not watched:
        return None

    healthy = sum(1 for row in watched if str(row.get("status") or "").lower() in ("online", "healthy"))
    degraded = sum(1 for row in watched if str(row.get("status") or "").lower() in ("degraded", "warning"))
    offline = sum(1 for row in watched if str(row.get("status") or "").lower() in ("offline", "critical"))

    if degraded or offline:
        body = f"{healthy} healthy, {degraded} degraded, {offline} offline"
        return _summary_status("Service Health", body, "warn" if not offline else "bad", "Needs attention")

    return _summary_status("Service Health", f"{healthy} watched services healthy.", "ok", "Healthy")


def _installer_download_issues() -> List[str]:
    issues: List[str] = []
    for installer_name, label in (("HarryAgentSetup.exe", "Windows agent installer"), ("HarryBrainSetup.exe", "Windows Brain installer")):
        manifest = _load_windows_installer_manifest(installer_name)
        if not _windows_installer_is_current(installer_name, manifest):
            issues.append(label)
    return issues


def _installer_artifact_row(installer_name: str, label: str) -> tuple[str, str, str]:
    manifest = _load_windows_installer_manifest(installer_name)
    if _windows_installer_is_current(installer_name, manifest):
        return (
            label,
            "online",
            f"Committed {label.lower()} EXE and manifest are current.",
        )

    if not manifest:
        return (
            label,
            "warning",
            f"{label} EXE or manifest is missing. Rebuild and commit the latest stable artifact.",
        )

    return (
        label,
        "warning",
        f"{label} EXE is stale. Rebuild and commit the latest stable artifact.",
    )


def _render_action_card(title: str, body: str, status: str = "info", badge_label: str | None = None) -> str:
    badge = badge_label or _service_status_label(status)
    return f"""
<div class="card compactcard">
  <div class="advrow" style="align-items:flex-start;">
    <div class="advleft">
      <div class="advnode">{_html_escape(title)}</div>
      <div class="advmsg">{_html_escape(body)}</div>
    </div>
    <span class="badgetxt {_service_status_class(status)}">{_html_escape(badge)}</span>
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
    current_n = sum(
        1
        for n in nodeviews
        if display_agent_version(n.agent_version) not in ("", "unknown") and display_agent_version(n.agent_version) == AGENT_VERSION
    )
    unknown_n = max(0, len(nodeviews) - current_n - behind)

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

    brain_rows = _advanced_discovery_rows(request)
    advanced_rows = brain_rows + [
        _installer_artifact_row("HarryAgentSetup.exe", "Agent installer artifact"),
        _installer_artifact_row("HarryBrainSetup.exe", "Brain installer artifact"),
    ]
    agent_title, agent_body, agent_status, agent_badge = _agent_summary(nodeviews)
    service_summary = _service_summary()

    recommendation_lines: List[str] = []
    if not nodeviews:
        recommendation_lines.append("Install the Harry agent on at least one machine so it can start reporting.")
    elif stale_n or behind:
        recommendation_lines.append("Restart or update the agents that are stale or behind.")
    if service_summary is not None:
        service_title, service_body, service_status, service_badge = service_summary
        if "healthy" not in service_body.lower():
            recommendation_lines.append("Check the monitored service on the machine that runs it.")
    if _installer_download_issues():
        recommendation_lines.append("Refresh the Windows installer downloads before onboarding new machines.")

    recommendations_html = ""
    if recommendation_lines:
        recommendations_html = f"""
<div class="divider"></div>

<div class="section" id="recommendations">
  <div class="sectionhead">
    <div>
      <div class="h2">Recommendations</div>
      <div class="h2sub">Only shown when something needs attention.</div>
    </div>
  </div>
  {_render_advice_queue(nodeviews)}
</div>
"""

    content = f"""
<div class="section" id="diagnostic-summary">
  <div class="sectionhead">
    <div>
      <div class="h2">Summary</div>
      <div class="h2sub">Actionable status at a glance. Healthy systems should feel calm and minimal.</div>
    </div>
  </div>

  <div class="cardgrid">
    {_render_action_card(agent_title, agent_body, agent_status, agent_badge)}
    {'' if service_summary is None else _render_action_card(service_summary[0], service_summary[1], service_summary[2], service_summary[3])}
    {'' if not recommendation_lines else _render_action_card("Recommendations", " · ".join(recommendation_lines), "warn", "Next steps")}
  </div>
</div>

{recommendations_html}

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
      for label, status, text in advanced_rows
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
        <tr><td>Current agents</td><td>{current_n}</td></tr>
        <tr><td>Behind agents</td><td>{behind}</td></tr>
        <tr><td>Unknown agents</td><td>{unknown_n}</td></tr>
        <tr><td>Bad findings</td><td>{bad_n}</td></tr>
        <tr><td>Warn findings</td><td>{warn_n}</td></tr>
        <tr><td>Info findings</td><td>{info_n}</td></tr>
        <tr><td>Delayed reporters</td><td>{delayed}</td></tr>
        <tr><td>Total advice items</td><td>{advice_total}</td></tr>
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
