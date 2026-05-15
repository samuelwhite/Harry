from __future__ import annotations

import ipaddress
import json
import os
import re
import socket
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, Optional
from urllib.parse import urlsplit, urlunsplit

DEFAULT_PUBLIC_PORT = 8789
BRIDGE_NETWORKS = (
    ipaddress.ip_network("172.16.0.0/12"),
    ipaddress.ip_network("192.168.240.0/20"),
    ipaddress.ip_network("169.254.0.0/16"),
)


def runtime_is_container() -> bool:
    hints = (
        os.environ.get("container"),
        os.environ.get("KUBERNETES_SERVICE_HOST"),
        os.environ.get("DOCKER_CONTAINER"),
    )
    if any(str(h or "").strip() for h in hints):
        return True

    try:
        if Path("/.dockerenv").exists() or Path("/run/.containerenv").exists():
            return True
    except Exception:
        pass

    try:
        cgroup = Path("/proc/1/cgroup")
        if cgroup.exists():
            raw = cgroup.read_text(encoding="utf-8", errors="replace").lower()
            if any(token in raw for token in ("docker", "kubepods", "containerd", "podman")):
                return True
    except Exception:
        pass

    return False


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
    if not re.match(r"^[a-zA-Z][a-zA-Z0-9+\-.]*://", raw):
        raw = f"http://{raw}"

    try:
        parsed = urlsplit(raw)
    except Exception:
        return None

    host = (parsed.hostname or "").strip()
    if not host:
        return None

    return (parsed.scheme or "http", host, parsed.port)


def _is_placeholder_brain_address(url: str) -> bool:
    lowered = (url or "").strip().lower()
    if not lowered:
        return False
    return (
        "__harry_public_base_url__" in lowered
        or "<brain-ip>" in lowered
        or "brain-ip" in lowered
        or "<your-brain-ip>" in lowered
        or "<" in lowered
        or ">" in lowered
    )


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

    return any(addr in net for net in BRIDGE_NETWORKS)


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
    if _host_is_container_bridge(host):
        return False

    try:
        addr = ipaddress.ip_address(host)
    except ValueError:
        return True

    if addr.version != 4:
        return False
    if addr.is_unspecified or addr.is_loopback or addr.is_link_local:
        return False
    if any(addr in net for net in BRIDGE_NETWORKS):
        return False

    return True


def _reject_lan_candidate(ip: str, *, container_runtime: bool = False) -> str | None:
    ip = (ip or "").strip()
    if not ip:
        return None

    if container_runtime:
        return "container runtime"

    try:
        addr = ipaddress.ip_address(ip)
    except ValueError:
        return "not an IP address"

    if addr.version != 4:
        return "not IPv4"
    if addr.is_loopback:
        return "loopback"
    if addr.is_link_local:
        return "link-local"
    if addr.is_unspecified:
        return "unspecified"
    if any(addr in net for net in BRIDGE_NETWORKS):
        return "bridge network"
    if not addr.is_private:
        return "not RFC1918"

    return None


def _split_header_values(raw: str | None) -> list[str]:
    if not raw:
        return []
    return [part.strip() for part in str(raw).split(",") if part.strip()]


def _host_looks_like_ip(host: str) -> bool:
    try:
        return ipaddress.ip_address((host or "").strip()).version == 4
    except ValueError:
        return False


def _candidate_from_host(host: str, scheme: str = "http", port: int | None = None) -> str | None:
    raw = (host or "").strip()
    if not raw or _is_placeholder_brain_address(raw):
        return None

    try:
        parsed = urlsplit(f"//{raw}", scheme="http")
    except Exception:
        return None

    host_only = (parsed.hostname or "").strip()
    if not host_only or _is_placeholder_brain_address(host_only):
        return None

    scheme = (scheme or "http").strip().lower() or "http"
    parsed_port = parsed.port if parsed.port is not None else port

    if _host_looks_like_ip(host_only):
        if not _host_is_publicly_usable(host_only):
            return None
        return f"{scheme}://{host_only}:{parsed_port or public_port()}"

    if not _host_is_publicly_usable(host_only):
        return None

    if parsed_port is not None:
        return f"{scheme}://{host_only}:{parsed_port}"
    return f"{scheme}://{host_only}"


def _request_forwarded_candidate(request: Any | None) -> str | None:
    if request is None:
        return None

    try:
        headers = request.headers
    except Exception:
        headers = None

    try:
        request_scheme = (request.url.scheme or "http").strip().lower()
    except Exception:
        request_scheme = "http"

    forwarded = ""
    forwarded_proto = ""
    try:
        forwarded = (headers.get("forwarded") or "").strip() if headers else ""
    except Exception:
        forwarded = ""
    try:
        forwarded_proto = (headers.get("x-forwarded-proto") or "").strip() if headers else ""
    except Exception:
        forwarded_proto = ""

    if forwarded:
        first_segment = forwarded.split(",", 1)[0]
        host_match = re.search(r"\bhost=([^;,\s]+)", first_segment, flags=re.IGNORECASE)
        proto_match = re.search(r"\bproto=([^;,\s]+)", first_segment, flags=re.IGNORECASE)
        candidate = _candidate_from_host(
            host_match.group(1) if host_match else "",
            proto_match.group(1) if proto_match else (forwarded_proto or request_scheme),
        )
        if candidate:
            return candidate

    x_forwarded_host = ""
    try:
        x_forwarded_host = (headers.get("x-forwarded-host") or "").strip() if headers else ""
    except Exception:
        x_forwarded_host = ""

    if x_forwarded_host:
        scheme = forwarded_proto.split(",", 1)[0].strip().lower() if forwarded_proto else request_scheme
        for host in _split_header_values(x_forwarded_host):
            candidate = _candidate_from_host(host, scheme=scheme)
            if candidate:
                return candidate

    return None


def _request_host_candidate(request: Any | None) -> str | None:
    if request is None:
        return None

    try:
        host_header = (request.headers.get("host") or "").strip()
    except Exception:
        host_header = ""

    try:
        scheme = (request.url.scheme or "http").strip().lower()
    except Exception:
        scheme = "http"

    if host_header:
        candidate = _candidate_from_host(host_header, scheme=scheme)
        if candidate:
            return candidate

    try:
        host = (request.url.hostname or "").strip()
    except Exception:
        host = ""

    if not host:
        return None

    if _is_placeholder_brain_address(host):
        return None

    try:
        port = request.url.port
    except Exception:
        port = None

    return _candidate_from_host(host, scheme=scheme, port=port)


def _score_lan_ip(ip: str) -> int:
    try:
        addr = ipaddress.ip_address(ip)
    except ValueError:
        return -1000

    if addr.version != 4:
        return -1000
    if addr.is_loopback or addr.is_link_local or addr.is_unspecified:
        return -1000
    if any(addr in net for net in BRIDGE_NETWORKS):
        return -1000
    if not addr.is_private:
        return -1000

    score = 100
    if ip.startswith("192.168."):
        score += 20
    elif ip.startswith("10."):
        score += 10

    if ip.startswith("192.168.56."):
        score -= 100

    return score


def _gather_lan_candidates() -> list[str]:
    candidates: list[str] = []

    udp_ip = _udp_detect_lan_ip()
    if udp_ip:
        candidates.append(udp_ip)

    if sys.platform.startswith("win"):
        candidates.extend(_windows_lan_candidates())
    else:
        candidates.extend(_posix_lan_candidates())

    seen: set[str] = set()
    out: list[str] = []
    for ip in candidates:
        ip = (ip or "").strip()
        if not ip or ip in seen:
            continue
        seen.add(ip)
        out.append(ip)

    return out


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
                if _score_lan_ip(ip) > 0:
                    return ip
            finally:
                sock.close()
        except Exception:
            continue

    return None


def _posix_lan_candidates() -> list[str]:
    candidates: list[str] = []

    try:
        _name, _aliases, addrs = socket.gethostbyname_ex(socket.gethostname())
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

    try:
        result = subprocess.run(
            ["hostname", "-I"],
            capture_output=True,
            text=True,
            check=False,
            timeout=3,
        )
        if result.returncode == 0 and result.stdout:
            candidates.extend(result.stdout.split())
    except Exception:
        pass

    try:
        result = subprocess.run(
            ["ip", "route", "get", "1.1.1.1"],
            capture_output=True,
            text=True,
            check=False,
            timeout=3,
        )
        if result.returncode == 0 and result.stdout:
            for match in re.findall(r"\bsrc\s+(\d+\.\d+\.\d+\.\d+)", result.stdout):
                candidates.append(match)
    except Exception:
        pass

    try:
        result = subprocess.run(
            ["ip", "route", "show", "default"],
            capture_output=True,
            text=True,
            check=False,
            timeout=3,
        )
        if result.returncode == 0 and result.stdout:
            for match in re.findall(r"\bsrc\s+(\d+\.\d+\.\d+\.\d+)", result.stdout):
                candidates.append(match)
    except Exception:
        pass

    return candidates


def _windows_lan_candidates() -> list[str]:
    candidates: list[str] = []

    try:
        ps = r"""
$routes = Get-NetRoute -DestinationPrefix '0.0.0.0/0' -ErrorAction SilentlyContinue |
    Where-Object { $_.NextHop -match '^\d+\.\d+\.\d+\.\d+$' }

$routeIndexes = @{}
foreach ($route in $routes) {
    if ($route.InterfaceIndex -ne $null) {
        $routeIndexes[[int]$route.InterfaceIndex] = $true
    }
}

$adapters = Get-NetIPAddress -AddressFamily IPv4 -ErrorAction SilentlyContinue |
    Where-Object {
        $_.IPAddress -match '^\d+\.\d+\.\d+\.\d+$' -and
        $_.InterfaceIndex -ne $null -and
        $routeIndexes.ContainsKey([int]$_.InterfaceIndex) -and
        $_.IPAddress -notlike '127.*' -and
        $_.IPAddress -notlike '169.254.*' -and
        $_.PrefixOrigin -ne 'WellKnown' -and
        $_.AddressState -ne 'Deprecated'
    }

$adapters |
    Select-Object -ExpandProperty IPAddress |
    ConvertTo-Json -Compress
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

        parsed = None
        try:
            parsed = json.loads(raw)
        except Exception:
            parsed = None

        if isinstance(parsed, str):
            parsed = [parsed]
        elif isinstance(parsed, dict):
            parsed = [parsed]

        if isinstance(parsed, list):
            for item in parsed:
                ip = str(item).strip()
                if _score_lan_ip(ip) > 0:
                    candidates.append(ip)
    except Exception:
        pass

    return candidates


def detect_lan_ip() -> str | None:
    candidates = _gather_lan_candidates()

    seen: set[str] = set()
    filtered: list[str] = []
    for ip in candidates:
        ip = (ip or "").strip()
        if not ip or ip in seen:
            continue
        seen.add(ip)
        if _score_lan_ip(ip) > 0:
            filtered.append(ip)

    if not filtered:
        return None

    filtered.sort(key=_score_lan_ip, reverse=True)
    return filtered[0]


def canonical_public_base_url() -> str | None:
    raw = (os.environ.get("HARRY_PUBLIC_BASE_URL") or "").strip()
    if not raw or _is_placeholder_brain_address(raw):
        return None

    parsed = _parse_url_bits(raw)
    if not parsed:
        return None

    scheme, host, port = parsed
    if scheme.lower() not in ("http", "https"):
        return None
    if not _host_is_publicly_usable(host):
        return None

    netloc = host if port is None else f"{host}:{port}"
    return urlunsplit((scheme, netloc, "", "", "")).rstrip("/")


def public_port() -> int:
    env_port = _safe_port(os.environ.get("HARRY_PUBLIC_PORT"))
    if env_port is not None:
        return env_port

    canonical = canonical_public_base_url()
    if canonical:
        parsed = _parse_url_bits(canonical)
        if parsed and parsed[2] is not None:
            return int(parsed[2])

    return DEFAULT_PUBLIC_PORT


def recommended_lan_ip() -> str | None:
    raw = (os.environ.get("HARRY_BRAIN_LAN_IP") or "").strip()
    if raw and _host_is_publicly_usable(raw):
        try:
            addr = ipaddress.ip_address(raw)
        except ValueError:
            return None
        if addr.version == 4:
            return raw
    if runtime_is_container():
        return None
    return detect_lan_ip()


def recommended_lan_url() -> str | None:
    lan_ip = recommended_lan_ip()
    if not lan_ip:
        return None
    return f"http://{lan_ip}:{public_port()}"


def resolve_brain_address(request: Any | None = None) -> Dict[str, Any]:
    canonical = canonical_public_base_url()
    recommended = recommended_lan_url()
    request_forwarded_candidate = _request_forwarded_candidate(request)
    request_host_candidate = _request_host_candidate(request)
    container_runtime = runtime_is_container()
    if canonical:
        source = "canonical"
        display_url = canonical
        warning = None
    elif (os.environ.get("HARRY_BRAIN_LAN_IP") or "").strip():
        source = "lan-config"
        display_url = recommended
        warning = (
            "Harry could not determine a reliable external Brain address automatically. "
            "Set HARRY_PUBLIC_BASE_URL for the canonical address that other machines should use."
        )
    elif not container_runtime and request_forwarded_candidate:
        source = "request-forwarded"
        display_url = request_forwarded_candidate.rstrip("/")
        warning = (
            "Harry is using the reverse-proxy address from the current request for now. "
            "Set HARRY_PUBLIC_BASE_URL to make the Brain address canonical for other machines."
        )
    elif not container_runtime and request_host_candidate:
        source = "request-host"
        display_url = request_host_candidate.rstrip("/")
        warning = (
            "Harry is using the current request address for now. "
            "Set HARRY_PUBLIC_BASE_URL to make the Brain address canonical for other machines."
        )
    elif not container_runtime and recommended:
        source = "lan-detected"
        display_url = recommended
        warning = (
            "Harry is using a detected LAN address for now. "
            "Set HARRY_PUBLIC_BASE_URL to make the Brain address canonical for other machines."
        )
    else:
        source = "unresolved"
        display_url = None
        warning = (
            "Harry could not determine a reliable LAN address automatically. "
            "Set HARRY_PUBLIC_BASE_URL or HARRY_BRAIN_LAN_IP to make the Brain address canonical for other machines."
        )

    try:
        request_port = int(request.url.port) if request and request.url.port else None
    except Exception:
        request_port = None

    return {
        "canonical_base_url": canonical,
        "recommended_lan_url": recommended,
        "display_url": display_url,
        "warning": warning,
        "source": source,
        "public_port": public_port(),
        "local_url": f"http://127.0.0.1:{request_port or public_port()}",
        "container_runtime": container_runtime,
        "detected_lan_ip": detect_lan_ip(),
        "request_forwarded_candidate": request_forwarded_candidate,
        "request_host_candidate": request_host_candidate,
        "rejected_lan_candidates": [
            ip
            for ip in _gather_lan_candidates()
            if _reject_lan_candidate(ip, container_runtime=container_runtime) is not None
        ],
    }


def discovery_payload_base_url() -> str | None:
    info = resolve_brain_address()
    return info["canonical_base_url"] or info["recommended_lan_url"]


def discovery_methods_enabled() -> list[str]:
    methods = ["HARRY_PUBLIC_BASE_URL", "HARRY_BRAIN_LAN_IP"]
    if runtime_is_container():
        methods.append("manual address entry")
    else:
        methods.extend(["reverse proxy headers", "request host", "LAN detection", "installer subnet discovery"])
    return methods
