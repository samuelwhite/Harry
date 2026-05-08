from __future__ import annotations

import argparse
import concurrent.futures
import ipaddress
import json
import re
import socket
import subprocess
import sys
import urllib.error
import urllib.request
from urllib.parse import urlsplit, urlunsplit
from typing import Callable

DISCOVERY_PATHS = ("/discover", "/.well-known/harry-brain")
BRIDGE_NETWORKS = (
    ipaddress.ip_network("172.16.0.0/12"),
    ipaddress.ip_network("192.168.240.0/20"),
    ipaddress.ip_network("169.254.0.0/16"),
)


def _is_safe_private_ipv4(ip: str) -> bool:
    ip = (ip or "").strip()
    if not ip:
        return False

    try:
        addr = ipaddress.ip_address(ip)
    except ValueError:
        return False

    if addr.version != 4:
        return False
    if addr.is_loopback or addr.is_link_local or addr.is_unspecified:
        return False
    if not addr.is_private:
        return False
    if any(addr in net for net in BRIDGE_NETWORKS):
        return False

    return True


def normalize_brain_url(value: str | None, default_port: int = 8789) -> str | None:
    raw = (value or "").strip()
    if not raw:
        return None

    if not re.match(r"^[a-zA-Z][a-zA-Z0-9+\-.]*://", raw):
        if re.match(r"^\d+\.\d+\.\d+\.\d+$", raw):
            raw = f"http://{raw}:{default_port}"
        elif re.match(r"^\d+\.\d+\.\d+\.\d+:\d+$", raw):
            raw = f"http://{raw}"
        else:
            raw = f"http://{raw}"

    try:
        parsed = urlsplit(raw)
    except Exception:
        return None

    host = (parsed.hostname or "").strip()
    if not host:
        return None

    port = parsed.port
    if re.match(r"^\d+\.\d+\.\d+\.\d+$", host) and port is None:
        port = default_port

    netloc = host if port is None else f"{host}:{port}"
    return urlunsplit((parsed.scheme or "http", netloc, "", "", ""))


def _private_ipv4_sources() -> list[str]:
    sources: list[str] = []

    try:
        _hostname, _aliases, addrs = socket.gethostbyname_ex(socket.gethostname())
        sources.extend(addrs)
    except Exception:
        pass

    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, family=socket.AF_INET):
            ip = info[4][0]
            if ip:
                sources.append(ip)
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
            sources.extend(result.stdout.split())
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
            for match in re.findall(r"via\s+(\d+\.\d+\.\d+\.\d+)", result.stdout):
                sources.append(match)
    except Exception:
        pass

    seen: set[str] = set()
    out: list[str] = []
    for ip in sources:
        ip = (ip or "").strip()
        if ip and ip not in seen and _is_safe_private_ipv4(ip):
            seen.add(ip)
            out.append(ip)

    return out


def build_candidate_urls(port: int = 8789) -> list[str]:
    urls: list[str] = [
        f"http://harry.local:{port}",
        f"http://harry-brain.local:{port}",
    ]

    subnets: list[ipaddress.IPv4Network] = []
    seen_subnets: set[str] = set()

    for ip in _private_ipv4_sources():
        try:
            subnet = ipaddress.ip_network(f"{ip}/24", strict=False)
        except Exception:
            continue

        subnet_s = str(subnet)
        if subnet_s in seen_subnets:
            continue
        seen_subnets.add(subnet_s)
        subnets.append(subnet)

    # Keep the scan small and predictable.
    for subnet in subnets[:2]:
        for host in subnet.hosts():
            urls.append(f"http://{host}:{port}")

    seen_urls: set[str] = set()
    ordered: list[str] = []
    for url in urls:
        if url not in seen_urls:
            seen_urls.add(url)
            ordered.append(url)
    return ordered


def probe_candidate(base_url: str, timeout: float = 1.2) -> str | None:
    base = base_url.rstrip("/")
    for path in DISCOVERY_PATHS:
        try:
            req = urllib.request.Request(
                f"{base}{path}",
                headers={"User-Agent": "HarryAgentInstall/1.0"},
            )
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                body = resp.read()
            payload = json.loads(body.decode("utf-8", errors="replace"))
            if not isinstance(payload, dict):
                continue
            if payload.get("service") != "harry-brain" or payload.get("ok") is not True:
                continue
            discovered = str(payload.get("base_url") or base).rstrip("/")
            return discovered
        except Exception:
            continue

    return None


def discover_brain_urls(
    *,
    port: int = 8789,
    timeout: float = 1.2,
    workers: int = 32,
    probe_fn: Callable[[str, float], str | None] | None = None,
) -> list[str]:
    probe = probe_fn or probe_candidate
    candidates = build_candidate_urls(port=port)
    discovered: list[str] = []

    with concurrent.futures.ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
        for result in pool.map(lambda url: probe(url, timeout), candidates):
            if result:
                discovered.append(result)

    seen: set[str] = set()
    ordered: list[str] = []
    for url in discovered:
        if url not in seen:
            seen.add(url)
            ordered.append(url)
    return ordered


def _cli(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description="Harry Brain discovery helper")
    sub = parser.add_subparsers(dest="cmd", required=True)

    discover = sub.add_parser("discover", help="Discover Harry Brain endpoints")
    discover.add_argument("--port", type=int, default=8789)
    discover.add_argument("--timeout", type=float, default=1.2)
    discover.add_argument("--workers", type=int, default=32)

    normalize = sub.add_parser("normalize", help="Normalize a Brain URL or IP")
    normalize.add_argument("value")
    normalize.add_argument("--default-port", type=int, default=8789)

    probe = sub.add_parser("probe", help="Probe a Brain URL for discovery metadata")
    probe.add_argument("value")
    probe.add_argument("--timeout", type=float, default=1.2)

    args = parser.parse_args(argv)

    if args.cmd == "discover":
        for url in discover_brain_urls(port=args.port, timeout=args.timeout, workers=args.workers):
            print(url)
        return 0

    if args.cmd == "normalize":
        normalized = normalize_brain_url(args.value, default_port=args.default_port)
        if not normalized:
            return 1
        print(normalized)
        return 0

    if args.cmd == "probe":
        discovered = probe_candidate(args.value, timeout=args.timeout)
        if not discovered:
            return 1
        print(discovered)
        return 0

    return 2


if __name__ == "__main__":
    raise SystemExit(_cli(sys.argv[1:]))
