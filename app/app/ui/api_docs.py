from __future__ import annotations

from typing import Any, Dict, List

from app.versions import AGENT_VERSION, BRAIN_VERSION

from .db import _load_schema_current

from .templates import _html_escape, render_shell


def _section_nav(hours: int = 72) -> List[Dict[str, Any]]:
    return [
        {
            "label": "API",
            "page": "api",
            "items": [
                {"label": "Overview", "href": "#api-overview", "sub": True},
                {"label": "Endpoints", "href": "#api-endpoints", "sub": True},
                {"label": "Examples", "href": "#api-examples", "sub": True},
                {"label": "Discovery", "href": "#api-discovery", "sub": True},
            ],
        },
        {
            "label": "Downloads",
            "items": [
                {"label": "Agent Installers", "href": "/downloads#downloads-overview", "page": "downloads", "sub": True},
                {"label": "Available Downloads", "href": "/downloads#downloads-files", "page": "downloads", "sub": True},
                {"label": "Setup help", "href": "/downloads#downloads-warning", "page": "downloads", "sub": True},
            ],
        },
    ]


def _endpoint_row(method: str, path: str, purpose: str) -> str:
    return f"""
<tr>
  <td><span class="badgetxt info">{_html_escape(method)}</span></td>
  <td class="mono">{_html_escape(path)}</td>
  <td>{_html_escape(purpose)}</td>
</tr>
"""


def render_api_docs_page() -> str:
    schema_current = _load_schema_current()
    endpoints = [
        ("GET", "/health", "Brain status, versions, and dist health."),
        ("GET", "/discover", "Discovery payload for installers and local tooling."),
        ("POST", "/ingest", "Agent telemetry ingest endpoint."),
        ("GET", "/inventory.json", "Inventory data for the UI and automation."),
        ("GET", "/api/services", "Service-awareness rows for the dashboard."),
        ("GET", "/downloads/windows-agent-exe", "Windows agent binary download."),
        ("GET", "/downloads/windows-update-script", "Windows updater helper script."),
    ]

    discover_json = """
{
  "ok": true,
  "service": "harry-brain",
  "display_name": "Harry Brain",
  "brain_version": "2026.05.09",
  "agent_version": "0.2.5",
  "schema_current": "0.2.3",
  "base_url": "http://brain-ip:8789",
  "ingest_url": "http://brain-ip:8789/ingest"
}
""".strip()

    content = f"""
<div class="section" id="api-overview">
  <div class="sectionhead">
    <div>
      <div class="h2">API overview</div>
      <div class="h2sub">Use Harry as a dashboard, ingest target, or automation endpoint.</div>
    </div>
    <div class="pill neutral">Brain {_html_escape(BRAIN_VERSION)} · Agent {_html_escape(AGENT_VERSION)} · Schema {_html_escape(schema_current)}</div>
  </div>

  <div class="card">
    <div class="subtitle" style="margin:0;">
      Harry’s endpoints are designed for self-hosted use on a local network or behind a reverse proxy.
      Installers will try to discover Harry Brain automatically and fall back to a manual URL when needed.
    </div>
  </div>
</div>

<div class="section" id="api-endpoints">
  <div class="sectionhead">
    <div>
      <div class="h2">Endpoints</div>
      <div class="h2sub">High-level purpose for the most useful routes.</div>
    </div>
  </div>

  <div class="invwrap">
    <table class="inv">
      <thead>
        <tr>
          <th>Method</th>
          <th>Path</th>
          <th>Purpose</th>
        </tr>
      </thead>
      <tbody>
        {''.join(_endpoint_row(*row) for row in endpoints)}
      </tbody>
    </table>
  </div>
</div>

<div class="section" id="api-examples">
  <div class="sectionhead">
    <div>
      <div class="h2">Examples</div>
      <div class="h2sub">Copy-paste snippets for common integrations.</div>
    </div>
  </div>

  <div class="cardgrid">
    <div class="card">
      <div class="subcardtitle">curl</div>
      <pre style="margin:0; white-space:pre-wrap; font-size:12.5px; line-height:1.5; color:rgba(255,255,255,0.88);">{_html_escape("curl http://<brain-ip>:8789/health")}</pre>
    </div>
    <div class="card">
      <div class="subcardtitle">PowerShell</div>
      <pre style="margin:0; white-space:pre-wrap; font-size:12.5px; line-height:1.5; color:rgba(255,255,255,0.88);">{_html_escape("Invoke-WebRequest http://<brain-ip>:8789/discover | Select-Object -Expand Content")}</pre>
    </div>
    <div class="card">
      <div class="subcardtitle">Python requests</div>
      <pre style="margin:0; white-space:pre-wrap; font-size:12.5px; line-height:1.5; color:rgba(255,255,255,0.88);">{_html_escape("import requests\nr = requests.get(\"http://<brain-ip>:8789/health\", timeout=5)\nprint(r.json())")}</pre>
    </div>
    <div class="card">
      <div class="subcardtitle">Discovery payload</div>
      <pre style="margin:0; white-space:pre-wrap; font-size:12.5px; line-height:1.5; color:rgba(255,255,255,0.88);">{_html_escape(discover_json)}</pre>
    </div>
  </div>
</div>

<div class="section" id="api-discovery">
  <div class="sectionhead">
    <div>
      <div class="h2">Discovery and deployment</div>
      <div class="h2sub">Designed for local-network installs and reverse-proxy deployments.</div>
    </div>
  </div>

  <div class="cardgrid">
    <div class="card">
      <div class="subcardtitle">Automatic discovery</div>
      <div class="subtitle" style="margin:0;">Installers try to find Harry Brain automatically first.</div>
    </div>
    <div class="card">
      <div class="subcardtitle">Manual fallback</div>
      <div class="subtitle" style="margin:0;">If discovery fails, paste the LAN-reachable Brain URL.</div>
    </div>
    <div class="card">
      <div class="subcardtitle">HTTPS</div>
      <div class="subtitle" style="margin:0;">Prefer HTTPS when exposing Harry through a reverse proxy.</div>
    </div>
    <div class="card">
      <div class="subcardtitle">Configuration</div>
      <div class="subtitle" style="margin:0;"><code>HARRY_PUBLIC_BASE_URL</code> or <code>HARRY_BRAIN_LAN_IP</code> + <code>HARRY_PUBLIC_PORT</code>.</div>
    </div>
  </div>
</div>
"""

    return render_shell(
        title="Harry API",
        active_page="api",
        page_title="API",
        page_subtitle="Integration endpoints and examples",
        sidebar_sections=_section_nav(),
        actions=[],
        content=content,
        sidebar_footer=f"Brain {BRAIN_VERSION}<br/>Agent {AGENT_VERSION}<br/>Schema {schema_current}",
    )
