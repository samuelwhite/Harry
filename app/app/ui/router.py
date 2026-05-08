from __future__ import annotations

import html
import ipaddress
import json
import os
import socket
import subprocess
import sys
from pathlib import Path
from urllib.parse import quote, urlsplit, urlunsplit

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import (
    FileResponse,
    HTMLResponse,
    JSONResponse,
    PlainTextResponse,
    RedirectResponse,
)

from app.ui.db import (
    DUMP_DEFAULT_HOURS,
    _clamp,
    _db,
    _db_has_ingest,
    _fetch_latest_per_node,
    _utcnow,
    delete_node,
    get_dump,
    hide_node,
    unhide_node,
)
from app.ui.diagnostics import render_diagnostics_page
from app.ui.fleet import render_fleet_page
from app.ui.inventory import _inventory_md, build_inventory_rows, render_inventory_page
from app.ui.node import render_node_detail
from app.ui.templates import render_shell

router = APIRouter()


def _is_usable_private_ipv4(ip: str) -> bool:
    ip = (ip or "").strip()
    if not ip:
        return False

    try:
        addr = ipaddress.ip_address(ip)
    except ValueError:
        return False

    if addr.version != 4:
        return False
    if addr.is_loopback:
        return False
    if addr.is_link_local:
        return False
    if addr.is_unspecified:
        return False
    if not addr.is_private:
        return False
    if addr in ipaddress.ip_network("172.16.0.0/12"):
        return False
    if addr in ipaddress.ip_network("192.168.240.0/20"):
        return False
    if addr in ipaddress.ip_network("169.254.0.0/16"):
        return False

    return True


def _score_lan_ip(ip: str) -> int:
    if not _is_usable_private_ipv4(ip):
        return -1000

    score = 100

    if ip.startswith("192.168."):
        score += 20
    elif ip.startswith("10."):
        score += 10
    elif ip.startswith("172."):
        score += 5

    # Common VirtualBox host-only subnet
    if ip.startswith("192.168.56."):
        score -= 100

    return score


def _udp_detect_lan_ip() -> str | None:
    test_targets = [
        ("8.8.8.8", 80),
        ("1.1.1.1", 80),
        ("192.0.2.1", 80),
    ]

    for host, port in test_targets:
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            try:
                sock.connect((host, port))
                ip = sock.getsockname()[0]
                if _is_usable_private_ipv4(ip):
                    return ip
            finally:
                sock.close()
        except Exception:
            continue

    return None


def _windows_ps_lan_candidates() -> list[str]:
    candidates: list[str] = []

    try:
        ps = r"""
$adapters = Get-CimInstance Win32_NetworkAdapterConfiguration |
    Where-Object {
        $_.IPEnabled -eq $true -and
        $_.IPAddress -ne $null
    }

$result = @()

foreach ($adapter in $adapters) {
    $desc = ""
    if ($adapter.Description) { $desc = [string]$adapter.Description }

    foreach ($ip in $adapter.IPAddress) {
        if (
            $ip -match '^\d+\.\d+\.\d+\.\d+$' -and
            $ip -notlike '127.*' -and
            $ip -notlike '169.254.*'
        ) {
            $result += [PSCustomObject]@{
                ip = $ip
                desc = $desc
            }
        }
    }
}

$result | ConvertTo-Json -Compress
"""
        result = subprocess.run(
            [
                "powershell",
                "-NoProfile",
                "-ExecutionPolicy",
                "Bypass",
                "-Command",
                ps,
            ],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )

        raw = (result.stdout or "").strip()
        if not raw:
            return candidates

        parsed = json.loads(raw)

        if isinstance(parsed, dict):
            parsed = [parsed]

        if isinstance(parsed, list):
            for item in parsed:
                if not isinstance(item, dict):
                    continue

                ip = str(item.get("ip") or "").strip()
                desc = str(item.get("desc") or "").strip().lower()

                if not _is_usable_private_ipv4(ip):
                    continue

                if any(
                    hint in desc
                    for hint in (
                        "virtualbox",
                        "vmware",
                        "hyper-v",
                        "hyperv",
                        "vEthernet".lower(),
                        "docker",
                        "wsl",
                        "loopback",
                        "host-only",
                        "host only",
                    )
                ):
                    continue

                candidates.append(ip)
    except Exception:
        pass

    return candidates


def _hostname_lan_candidates() -> list[str]:
    candidates: list[str] = []

    try:
        hostname = socket.gethostname()
        _name, _aliases, addrs = socket.gethostbyname_ex(hostname)
        candidates.extend(addrs)
    except Exception:
        pass

    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, family=socket.AF_INET):
            ip = info[4][0]
            if ip:
                candidates.append(ip)
    except Exception:
        pass

    return candidates


def _detect_lan_ip() -> str | None:
    # Strongly prefer the routed outbound address first.
    udp_ip = _udp_detect_lan_ip()
    if udp_ip:
        return udp_ip

    candidates: list[str] = []

    if sys.platform.startswith("win"):
        candidates.extend(_windows_ps_lan_candidates())

    candidates.extend(_hostname_lan_candidates())

    seen: set[str] = set()
    filtered: list[str] = []

    for ip in candidates:
        ip = (ip or "").strip()
        if not ip or ip in seen:
            continue
        seen.add(ip)

        if not _is_usable_private_ipv4(ip):
            continue

        filtered.append(ip)

    if not filtered:
        return None

    filtered.sort(key=_score_lan_ip, reverse=True)
    return filtered[0]


def _resolve_port(request: Request) -> int:
    configured = (os.environ.get("HARRY_PORT") or "").strip()
    if configured:
        try:
            return int(configured)
        except Exception:
            pass

    if request.url.port:
        return int(request.url.port)

    if request.url.scheme == "https":
        return 443

    return 80


def _host_is_loopback(host: str) -> bool:
    host = (host or "").strip().lower()
    if not host:
        return False
    if host in ("127.0.0.1", "localhost", "::1"):
        return True

    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def _is_placeholder_brain_address(url: str) -> bool:
    lowered = (url or "").strip().lower()
    if not lowered:
        return False
    return (
        "__harry_public_base_url__" in lowered
        or "<brain-ip>" in lowered
        or "brain-ip" in lowered
        or "<" in lowered
        or ">" in lowered
    )


def _host_is_container_bridge(host: str) -> bool:
    host = (host or "").strip()
    if not host:
        return False

    try:
        addr = ipaddress.ip_address(host)
    except ValueError:
        return False

    if addr.version != 4:
        return False

    try:
        return addr in ipaddress.ip_network("172.16.0.0/12")
    except ValueError:
        return False


def _host_is_publicly_usable(host: str) -> bool:
    host = (host or "").strip()
    if not host:
        return False

    lowered = host.lower()
    if lowered in ("localhost", "127.0.0.1", "::1", "testserver"):
        return False
    if "<" in lowered or ">" in lowered:
        return False
    if _host_is_loopback(host):
        return False

    try:
        addr = ipaddress.ip_address(host)
    except ValueError:
        return True

    if addr.version != 4:
        return False
    if addr.is_link_local or addr.is_unspecified or addr.is_loopback:
        return False
    if not addr.is_private:
        return False
    if addr in ipaddress.ip_network("172.16.0.0/12"):
        return False
    if addr in ipaddress.ip_network("192.168.240.0/20"):
        return False
    if addr in ipaddress.ip_network("169.254.0.0/16"):
        return False
    if _host_is_container_bridge(host):
        return False

    return True


def _safe_port(value: str | None) -> int | None:
    try:
        if value in (None, ""):
            return None
        port = int(str(value).strip())
        if 1 <= port <= 65535:
            return port
    except Exception:
        return None
    return None


def _parse_url_bits(url: str) -> tuple[str, str, int | None] | None:
    raw = (url or "").strip()
    if not raw:
        return None

    try:
        parsed = urlsplit(raw)
    except Exception:
        return None

    host = (parsed.hostname or "").strip()
    if not host:
        return None

    return (parsed.scheme or "http", host, parsed.port)


def _parse_authority(authority: str) -> tuple[str, int | None] | None:
    raw = (authority or "").strip()
    if not raw:
        return None

    try:
        parsed = urlsplit(f"//{raw}", scheme="http")
    except Exception:
        return None

    host = (parsed.hostname or "").strip()
    if not host:
        return None

    return host, parsed.port


def _request_public_candidate(request: Request) -> tuple[str, str, int | None, bool] | None:
    host_header = (request.headers.get("host") or "").strip()
    candidate = _parse_authority(host_header)
    scheme = (request.url.scheme or "http").strip().lower()

    if candidate:
        host, port = candidate
        try:
            ipaddress.ip_address(host)
        except ValueError:
            if scheme == "https" and not _host_is_loopback(host):
                return "https", host, None, True
        else:
            if _host_is_publicly_usable(host):
                return scheme or "http", host, port, False

    host = (request.url.hostname or "").strip()
    if host:
        try:
            ipaddress.ip_address(host)
        except ValueError:
            if scheme == "https" and not _host_is_loopback(host):
                return "https", host, None, True
        else:
            if _host_is_publicly_usable(host):
                return scheme or "http", host, request.url.port, False

    return None


def _resolve_public_port(request: Request, configured: str, request_port: int | None = None) -> int:
    parsed = _parse_url_bits(configured)
    if parsed and parsed[2] is not None and _host_is_publicly_usable(parsed[1]):
        return int(parsed[2])

    for env_name in ("HARRY_PUBLIC_PORT",):
        env_port = _safe_port(os.environ.get(env_name))
        if env_port is not None:
            return env_port

    if request_port is not None:
        return int(request_port)

    request_candidate = _request_public_candidate(request)
    if request_candidate and request_candidate[2] is not None:
        return int(request_candidate[2])

    return 8789


def _resolve_local_port(request: Request, configured: str, public_port: int) -> int:
    parsed = _parse_url_bits(configured)
    if parsed and parsed[2] is not None and _host_is_loopback(parsed[1]):
        return int(parsed[2])

    for env_name in ("HARRY_LOCAL_PORT", "HARRY_PUBLIC_PORT", "HARRY_PORT"):
        env_port = _safe_port(os.environ.get(env_name))
        if env_port is not None:
            return env_port

    request_candidate = _request_public_candidate(request)
    if request_candidate and request_candidate[2] is not None:
        return int(request_candidate[2])

    return public_port


def _build_url(scheme: str, host: str, port: int | None = None) -> str:
    netloc = host if port is None else f"{host}:{port}"
    return urlunsplit((scheme or "http", netloc, "", "", ""))


def _resolve_brain_urls(request: Request) -> tuple[str, str]:
    configured = (os.environ.get("HARRY_PUBLIC_BASE_URL") or "").strip()
    brain_lan_ip = (os.environ.get("HARRY_BRAIN_LAN_IP") or "").strip()
    request_candidate = _request_public_candidate(request)
    request_port = request_candidate[2] if request_candidate else None

    public_port = _resolve_public_port(request, configured, request_port=request_port)
    local_port = _resolve_local_port(request, configured, public_port)

    public_url = ""
    if configured and not _is_placeholder_brain_address(configured):
        parsed = _parse_url_bits(configured)
        if parsed and _host_is_publicly_usable(parsed[1]):
            scheme, host, port = parsed
            public_url = _build_url(scheme, host, int(port or public_port))

    if not public_url and brain_lan_ip and not _is_placeholder_brain_address(brain_lan_ip) and not _host_is_loopback(brain_lan_ip):
        public_url = _build_url("http", brain_lan_ip, public_port)

    if not public_url and request_candidate:
        scheme, host, port, https_domain = request_candidate
        if https_domain:
            public_url = _build_url("https", host, None)
        else:
            public_url = _build_url(scheme, host, int(port or public_port))

    if not public_url:
        lan_ip = _detect_lan_ip()
        if lan_ip:
            if _host_is_publicly_usable(lan_ip):
                public_url = _build_url("http", lan_ip, public_port)
        else:
            public_url = _build_url("http", "<brain-ip>", public_port)

    if not public_url:
        public_url = _build_url("http", "<brain-ip>", public_port)

    local_url = _build_url("http", "127.0.0.1", local_port)
    return public_url, local_url


def _downloads_dir() -> Path:
    configured = (os.environ.get("HARRY_DOWNLOADS_DIR") or "").strip()
    if configured:
        return Path(configured).expanduser()

    if getattr(sys, "frozen", False):
        exe_dir = Path(sys.executable).resolve().parent
        candidates = [
            exe_dir / "downloads",
            exe_dir.parent / "downloads",
        ]
        for candidate in candidates:
            if candidate.exists():
                return candidate
        return exe_dir / "downloads"

    here = Path(__file__).resolve()
    candidates = [
        here.parent / "downloads",
        here.parents[1] / "downloads",
        here.parents[2] / "downloads",
        here.parents[3] / "downloads",
    ]
    for candidate in candidates:
        if candidate.exists():
            return candidate

    return here.parents[3] / "downloads"


def _human_size(num_bytes: int) -> str:
    size = float(num_bytes)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if size < 1024.0 or unit == "TB":
            if unit == "B":
                return f"{int(size)} {unit}"
            return f"{size:.1f} {unit}"
        size /= 1024.0
    return f"{int(num_bytes)} B"


def _brain_url_warning(url: str) -> str | None:
    lowered = (url or "").strip().lower()

    if not lowered:
        return "No Brain address is configured."

    if "__harry_public_base_url__" in lowered or "__" in lowered:
        return "The Brain address has not been configured yet."

    if "127.0.0.1" in lowered or "localhost" in lowered:
        return (
            "This Brain address only works on the Brain machine itself. "
            "When installing Harry Agent on another machine, use this machine's LAN IP address instead."
        )

    if " " in lowered:
        return (
            "The current Brain address does not look valid. "
            "It should usually look like http://192.168.1.100:8789"
        )

    if not (lowered.startswith("http://") or lowered.startswith("https://")):
        return (
            "The current Brain address does not look valid. "
            "It should usually look like http://192.168.1.100:8789"
        )

    return None


@router.get("/ui/health")
def ui_health() -> PlainTextResponse:
    return PlainTextResponse("ok\n")


@router.get("/downloads", response_class=HTMLResponse)
def downloads_page(request: Request) -> HTMLResponse:
    brain_url, local_url = _resolve_brain_urls(request)
    warning = _brain_url_warning(brain_url)
    downloads_dir = _downloads_dir()

    files: list[dict[str, str]] = []
    if downloads_dir.exists() and downloads_dir.is_dir():
        for path in sorted(downloads_dir.iterdir(), key=lambda p: p.name.lower()):
            if not path.is_file():
                continue
            if path.name.startswith("."):
                continue
            if "Agent" not in path.name:
                continue

            if path.name == "HarryAgentSetup.exe":
                href = "/downloads/windows-agent"
                platform = "Windows"
            elif path.name == "HarryAgentInstall.sh":
                href = "/downloads/linux-agent"
                platform = "Linux"
            else:
                href = f"/downloads/file/{quote(path.name)}"
                platform = "Other"

            files.append(
                {
                    "name": path.name,
                    "href": href,
                    "size": _human_size(path.stat().st_size),
                    "platform": platform,
                }
            )

    if files:
        rows = []
        for f in files:
            rows.append(
                f"""
<tr>
  <td>{html.escape(f["name"])}</td>
  <td>{html.escape(f["platform"])}</td>
  <td>{html.escape(f["size"])}</td>
  <td><a class="btn" href="{html.escape(f["href"])}">Download</a></td>
</tr>
"""
            )

        downloads_html = f"""
<div class="invwrap">
  <table class="inv">
    <thead>
      <tr>
        <th>File</th>
        <th>Platform</th>
        <th>Size</th>
        <th>Action</th>
      </tr>
    </thead>
    <tbody>
      {''.join(rows)}
    </tbody>
  </table>
</div>
"""
    else:
        downloads_html = """
<div class="empty">
  No agent installers are currently available.
</div>
"""

    warning_html = ""
    if warning:
        warning_html = f"""
<section class="section" id="downloads-warning">
  <div class="card" style="border:1px solid rgba(245, 158, 11, 0.55);">
    <div class="k">Warning</div>
    <div class="v" style="margin-top:8px;">{html.escape(warning)}</div>
    <div class="subtitle" style="margin-top:10px;">
      On Windows, open <code>Command Prompt</code>, run <code>ipconfig</code>,
      find your active adapter's <code>IPv4 Address</code>, then use
      <code>HARRY_PUBLIC_BASE_URL=http://&lt;brain-ip&gt;:8789</code> or
      <code>HARRY_BRAIN_LAN_IP=&lt;brain-ip&gt;</code> with
      <code>HARRY_PUBLIC_PORT=8789</code> for the address your agents should reach.
    </div>
  </div>
</section>
"""

    content = f"""
    {warning_html}

<section class="section" id="downloads-overview">
  <div class="card">
    <div class="k">Brain address for other machines</div>
    <div style="display:flex; gap:10px; align-items:center; flex-wrap:wrap;">
      <div class="v big"><code id="brain-url">{html.escape(brain_url)}</code></div>
      <button class="btn" onclick="navigator.clipboard.writeText(document.getElementById('brain-url').innerText)">
        Copy
      </button>
    </div>
    <div class="subtitle">Copy this full Brain address into the installer when prompted on another machine on your network. If the automatic address is wrong, set <code>HARRY_PUBLIC_BASE_URL=http://&lt;brain-ip&gt;:8789</code> or <code>HARRY_BRAIN_LAN_IP=&lt;brain-ip&gt;</code> with <code>HARRY_PUBLIC_PORT=8789</code>.</div>
    <div class="subtitle" style="margin-top:10px;">Use the address that other machines on your network can reach. For Docker installs, set <code>HARRY_PUBLIC_BASE_URL</code> or <code>HARRY_BRAIN_LAN_IP</code> if this is wrong.</div>
  </div>
</section>

<section class="section" id="downloads-files">
  <div class="sectionhead">
    <div>
      <h2 class="h2">Agent Installers</h2>
      <div class="h2sub">Install Harry Agent on another machine.</div>
    </div>
  </div>
  {downloads_html}
</section>

<section class="section" id="downloads-notes">
  <div class="sectionhead">
    <div>
      <h2 class="h2">Add a Node to Harry</h2>
      <div class="h2sub">Install Harry Agent on another machine and connect it to this Brain.</div>
    </div>
  </div>

  <div class="card">
    <div class="advrow">
      <div class="advleft">
        <div class="advnode">1. Download the installer</div>
        <div class="advmsg">Choose the installer for the machine you want to add.</div>
      </div>
    </div>

    <div class="advrow">
      <div class="advleft">
        <div class="advnode">2. Run it on the target machine</div>
        <div class="advmsg">Start the installer on the machine you want Harry to monitor.</div>
      </div>
    </div>

    <div class="advrow">
      <div class="advleft">
        <div class="advnode">3. Enter the Brain address</div>
        <div class="advmsg">When prompted by the installer, use <code>{html.escape(brain_url)}</code>. Do not use <code>localhost</code> unless installing on the Brain machine itself.</div>
      </div>
    </div>

    <div class="advrow">
      <div class="advleft">
        <div class="advnode">4. Confirm the node in Fleet</div>
        <div class="advmsg">After installation, return to Fleet and check that the new machine appears.</div>
      </div>
    </div>

    <div class="advrow">
      <div class="advleft">
        <div class="advnode">5. Brain machine local agent</div>
        <div class="advmsg">Harry Brain and the local Harry Agent are separate. If this Brain machine does not appear in Overview, install or check the local Harry Agent service.</div>
      </div>
    </div>
  </div>

  <div class="footerline">
    <strong>Note for Windows users:</strong>
    Windows SmartScreen may show a warning when running the installer.<br>
    This is normal for newly built software that has not yet been digitally signed.<br>
    Choose <code>More info</code> → <code>Run anyway</code> to continue.
  </div>
</section>

<section class="section" id="downloads-help">
  <div class="sectionhead">
    <div>
      <h2 class="h2">If the Brain address is wrong</h2>
      <div class="h2sub">Find the correct LAN IP for this machine.</div>
    </div>
  </div>

  <div class="card">
    <div class="advrow">
      <div class="advleft">
        <div class="advnode">Future automatic discovery</div>
        <div class="advmsg">TODO: add mDNS / Bonjour discovery, consider a <code>harry.local</code> fallback, and keep manual IP entry available when discovery is unavailable.</div>
      </div>
    </div>

    <div class="advrow">
      <div class="advleft">
        <div class="advnode">1. Open Command Prompt</div>
        <div class="advmsg">Press Start, type <code>cmd</code>, and open Command Prompt.</div>
      </div>
    </div>

    <div class="advrow">
      <div class="advleft">
        <div class="advnode">2. Run ipconfig</div>
        <div class="advmsg">Type <code>ipconfig</code> and press Enter.</div>
      </div>
    </div>

    <div class="advrow">
      <div class="advleft">
        <div class="advnode">3. Find your active network adapter</div>
        <div class="advmsg">Look for the adapter currently connected to your network, such as Ethernet or Wi-Fi.</div>
      </div>
    </div>

    <div class="advrow">
      <div class="advleft">
        <div class="advnode">4. Find IPv4 Address</div>
        <div class="advmsg">Use the <code>IPv4 Address</code> value in the installer, in the format <code>http://192.168.1.100:8789</code>. Replace it with the real address your agents can reach.</div>
      </div>
    </div>
  </div>
</section>
"""

    sidebar_sections = [
        {
            "label": "Fleet",
            "items": [
                {"label": "Overview", "href": "/#overview", "page": "fleet", "sub": True},
                {"label": "Nodes", "href": "/#nodes", "page": "fleet", "sub": True},
                {"label": "Trends", "href": "/#trends", "page": "fleet", "sub": True},
                {"label": "Hidden Nodes", "href": "/#hidden-nodes", "page": "fleet", "sub": True},
            ],
        },
        {
            "label": "Inventory",
            "items": [
                {"label": "Summary", "href": "/inventory#summary", "page": "inventory", "sub": True},
                {"label": "Comparison Table", "href": "/inventory#comparison-table", "page": "inventory", "sub": True},
                {"label": "Details", "href": "/inventory#details", "page": "inventory", "sub": True},
            ],
        },
        {
            "label": "Diagnostics",
            "items": [
                {"label": "Summary", "href": "/diagnostics#summary", "page": "diagnostics", "sub": True},
                {"label": "Recommendations", "href": "/diagnostics#recommendations", "page": "diagnostics", "sub": True},
                {"label": "Statistics", "href": "/diagnostics#statistics", "page": "diagnostics", "sub": True},
            ],
        },
        {
            "label": "Downloads",
            "items": [
                {"label": "Agent Installers", "href": "/downloads#downloads-overview", "page": "downloads", "sub": True},
                {"label": "Available Downloads", "href": "/downloads#downloads-files", "sub": True},
                {"label": "Add a Node", "href": "/downloads#downloads-notes", "sub": True},
                {"label": "Fix Brain Address", "href": "/downloads#downloads-help", "sub": True},
            ],
        },
    ]

    return HTMLResponse(
        render_shell(
            title="Harry Downloads",
            active_page="downloads",
            page_title="Downloads",
            page_subtitle="Agent installers",
            sidebar_sections=sidebar_sections,
            actions=[],
            content=content,
        )
    )


@router.get("/downloads/file/{filename}")
def download_file(filename: str) -> FileResponse:
    base = _downloads_dir().resolve()
    path = (base / filename).resolve()

    if not path.is_relative_to(base):
        raise HTTPException(status_code=404, detail="File not found")

    if not path.exists() or not path.is_file():
        raise HTTPException(status_code=404, detail="File not found")

    return FileResponse(
        path=str(path),
        filename=path.name,
        media_type="application/octet-stream",
    )


@router.get("/fleet/partial", response_class=HTMLResponse)
def fleet_partial(request: Request) -> HTMLResponse:
    hours_q = request.query_params.get("hours", None)
    try:
        hours = int(hours_q) if hours_q is not None else DUMP_DEFAULT_HOURS
    except Exception:
        hours = DUMP_DEFAULT_HOURS
    hours = int(_clamp(hours, 1, 24 * 14))

    debug = (request.query_params.get("debug") or "").strip().lower() in ("1", "true", "yes", "y")

    from app.ui.fleet import render_fleet_live

    return HTMLResponse(render_fleet_live(hours=hours, debug=debug))


@router.get("/downloads/windows-agent")
def download_windows_agent() -> FileResponse:
    path = _downloads_dir() / "HarryAgentSetup.exe"
    if not path.exists() or not path.is_file():
        raise HTTPException(
            status_code=404,
            detail="Windows agent installer not found. Expected downloads/HarryAgentSetup.exe.",
        )

    return FileResponse(
        path=str(path),
        filename="HarryAgentSetup.exe",
        media_type="application/octet-stream",
    )


@router.get("/downloads/linux-agent")
def download_linux_agent() -> FileResponse:
    path = _downloads_dir() / "HarryAgentInstall.sh"
    if not path.exists() or not path.is_file():
        raise HTTPException(
            status_code=404,
            detail="Linux agent installer not found. Expected downloads/HarryAgentInstall.sh.",
        )

    return FileResponse(
        path=str(path),
        filename="HarryAgentInstall.sh",
        media_type="text/x-shellscript",
    )


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


@router.post("/node/{node}/hide")
def node_hide(request: Request, node: str) -> RedirectResponse:
    next_url = (request.query_params.get("next") or "/").strip() or "/"
    hide_node(node.strip())
    return RedirectResponse(url=next_url, status_code=303)


@router.post("/node/{node}/unhide")
def node_unhide(request: Request, node: str) -> RedirectResponse:
    next_url = (request.query_params.get("next") or "/").strip() or "/"
    unhide_node(node.strip())
    return RedirectResponse(url=next_url, status_code=303)


@router.post("/node/{node}/delete")
def node_delete(request: Request, node: str) -> RedirectResponse:
    next_url = (request.query_params.get("next") or "/").strip() or "/"
    delete_node(node.strip())
    return RedirectResponse(url=next_url, status_code=303)


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
