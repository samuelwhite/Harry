from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from starlette.requests import Request

import app.config as config
import app.brain_address as brain_address
import app.main as main
import importlib
from app.ui import db as dbmod

router = importlib.import_module("app.ui.router")


def _setup_temp_db(monkeypatch, tmp_path):
    db_path = tmp_path / "harry.db"
    monkeypatch.setattr(config, "DB_PATH", db_path, raising=False)
    monkeypatch.setattr(main, "DB_PATH", db_path, raising=False)
    monkeypatch.setattr(dbmod, "DB_PATH", str(db_path), raising=False)
    main._init_db()
    return db_path


def _render_downloads(monkeypatch, tmp_path, *, base_url=None):
    _setup_temp_db(monkeypatch, tmp_path)
    monkeypatch.setattr(router, "_downloads_dir", lambda: tmp_path)

    client_kwargs = {}
    if base_url is not None:
        client_kwargs["base_url"] = base_url

    with TestClient(main.app, **client_kwargs) as client:
        return client.get("/downloads").text


def _make_request(host: str, scheme: str = "http"):
    hostname, _, port_s = host.partition(":")
    port = int(port_s) if port_s else None
    return SimpleNamespace(
        headers={"host": host},
        url=SimpleNamespace(hostname=hostname, port=port, scheme=scheme),
    )


def _make_starlette_request(host: str = "localhost", scheme: str = "http") -> Request:
    return Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/downloads",
            "raw_path": b"/downloads",
            "headers": [(b"host", host.encode("utf-8"))],
            "query_string": b"",
            "client": ("127.0.0.1", 12345),
            "server": (host, 80),
            "scheme": scheme,
            "root_path": "",
            "http_version": "1.1",
            "extensions": {},
        }
    )


def test_validate_dist_agent_rejects_tabs(tmp_path):
    script = tmp_path / "harry_agent.sh"
    script.write_text("#!/usr/bin/env bash\n\techo hi\n", encoding="utf-8")

    ok, error = main._validate_dist_agent(script)

    assert ok is False
    assert error == "contains_tab_characters"


def test_validate_dist_agent_skips_bash_on_windows(monkeypatch, tmp_path):
    script = tmp_path / "harry_agent.sh"
    script.write_text("#!/usr/bin/env bash\necho hi\n", encoding="utf-8")

    monkeypatch.setattr(main.sys, "platform", "win32", raising=False)
    monkeypatch.setattr(
        main.subprocess,
        "run",
        lambda *args, **kwargs: pytest.fail("bash validation should be skipped on Windows"),
    )

    ok, error = main._validate_dist_agent(script)

    assert ok is True
    assert error is None


def test_download_file_rejects_path_traversal(monkeypatch, tmp_path):
    downloads = tmp_path / "downloads"
    downloads.mkdir()
    (downloads / "harry.txt").write_text("ok", encoding="utf-8")

    monkeypatch.setattr(router, "_downloads_dir", lambda: downloads)

    response = router.download_file("harry.txt")
    assert Path(response.path) == downloads / "harry.txt"

    with pytest.raises(HTTPException) as excinfo:
        router.download_file("../outside.txt")

    assert excinfo.value.status_code == 404


def test_node_summary_strips_platform_suffix_from_agent_version():
    payload = {
        "node": "node-1",
        "ts": "2026-05-07T12:00:00Z",
        "agent_version": "0.2.5-windows-dev",
        "facts": {},
        "metrics": {"disk_used": [], "temps_c": {}, "gpu": [], "extensions": {}},
        "derived": {"health": {"state": "unknown", "worst_severity": "unknown", "reasons": []}, "extensions": {}},
        "advice": [],
    }

    summary = main._node_summary(payload, ctx={})

    assert summary["agent_version"] == "0.2.5"


def test_fleet_page_does_not_inject_full_page_refresh_script(monkeypatch):
    fleet = importlib.import_module("app.ui.fleet")
    monkeypatch.setattr(fleet, "render_fleet_live", lambda hours, debug: "<div id='fleet-live'></div>")
    fleet_html = fleet.render_fleet_page(hours=72, debug=False)

    assert "/fleet/partial" not in fleet_html
    assert "refreshFleet" not in fleet_html


def test_discover_endpoint_reports_brain_identity(monkeypatch, tmp_path):
    _setup_temp_db(monkeypatch, tmp_path)
    monkeypatch.setenv("HARRY_PUBLIC_BASE_URL", "http://brain.example:8789")

    with TestClient(main.app) as client:
        resp = client.get("/discover")
        well_known = client.get("/.well-known/harry-brain")

    assert resp.status_code == 200
    data = resp.json()
    assert data["ok"] is True
    assert data["service"] == "harry-brain"
    assert data["display_name"] == "Harry Brain"
    assert data["brain_version"] == "2026.05.09"
    assert data["agent_version"] == "0.2.5"
    assert data["schema_current"] == "0.2.3"
    assert data["canonical_base_url"] == "http://brain.example:8789"
    assert data["address_warning"] is None
    assert data["address_source"] == "canonical"
    assert data["base_url"] == "http://brain.example:8789"
    assert data["ingest_url"] == "http://brain.example:8789/ingest"
    assert data["installer_download_url"] == "http://brain.example:8789/downloads/windows-agent"
    assert data["agent_download_url"] == "http://brain.example:8789/downloads/windows-agent-exe"
    assert data["agent_update_script_url"] == "http://brain.example:8789/downloads/windows-update-script"

    assert well_known.status_code == 200
    assert well_known.json() == data


def test_downloads_exposes_windows_agent_binary(monkeypatch, tmp_path):
    _setup_temp_db(monkeypatch, tmp_path)

    with TestClient(main.app) as client:
        resp = client.get("/downloads/windows-agent-exe")

    assert resp.status_code == 200
    assert "harry_agent.exe" in resp.headers["content-disposition"]


def test_downloads_exposes_windows_agent_setup(monkeypatch, tmp_path):
    _setup_temp_db(monkeypatch, tmp_path)
    monkeypatch.setenv("HARRY_DOWNLOADS_DIR", str(tmp_path))
    (tmp_path / "HarryAgentSetup.exe").write_bytes(b"MZ")
    (tmp_path / "HarryAgentSetup.manifest.json").write_text(
        json.dumps(
            {
                "installer_name": "HarryAgentSetup.exe",
                "brain_version": "2026.05.09",
                "agent_version": "0.2.5",
                "schema_current": "0.2.3",
            }
        ),
        encoding="utf-8",
    )

    with TestClient(main.app) as client:
        resp = client.get("/downloads/windows-agent")

    assert resp.status_code == 200
    assert "HarryAgentSetup.exe" in resp.headers["content-disposition"]


def test_downloads_rejects_stale_windows_agent_setup(monkeypatch, tmp_path):
    _setup_temp_db(monkeypatch, tmp_path)
    monkeypatch.setenv("HARRY_DOWNLOADS_DIR", str(tmp_path))
    (tmp_path / "HarryAgentSetup.exe").write_bytes(b"MZ")
    (tmp_path / "HarryAgentSetup.manifest.json").write_text(
        json.dumps(
            {
                "installer_name": "HarryAgentSetup.exe",
                "brain_version": "2026.03.18",
                "agent_version": "0.2.3",
                "schema_current": "0.2.3",
            }
        ),
        encoding="utf-8",
    )

    with TestClient(main.app) as client:
        resp = client.get("/downloads/windows-agent")

    assert resp.status_code == 503
    assert "stale" in resp.text.lower()


def test_downloads_exposes_windows_agent_script(monkeypatch, tmp_path):
    _setup_temp_db(monkeypatch, tmp_path)

    with TestClient(main.app) as client:
        resp = client.get("/downloads/windows-agent-script")

    assert resp.status_code == 200
    assert "install_agent.ps1" in resp.headers["content-disposition"]
    assert "Discover-HarryBrain" in resp.text


def test_downloads_exposes_windows_update_script(monkeypatch, tmp_path):
    _setup_temp_db(monkeypatch, tmp_path)

    with TestClient(main.app) as client:
        resp = client.get("/downloads/windows-update-script")

    assert resp.status_code == 200
    assert "update_agent.ps1" in resp.headers["content-disposition"]


def test_downloads_prefers_non_local_public_base_url(monkeypatch, tmp_path):
    monkeypatch.setenv("HARRY_PUBLIC_BASE_URL", "http://brain.example:8789")
    html = _render_downloads(monkeypatch, tmp_path)

    assert 'id="brain-url">http://brain.example:8789<' in html
    assert "On this machine only" not in html
    assert "127.0.0.1" not in html


def test_downloads_uses_placeholder_env_only_as_fallback(monkeypatch, tmp_path):
    monkeypatch.setenv("HARRY_PUBLIC_BASE_URL", "http://<brain-ip>:8789")
    monkeypatch.setattr(brain_address, "detect_lan_ip", lambda: "192.168.1.44")
    html = _render_downloads(monkeypatch, tmp_path)

    assert 'id="brain-url">http://192.168.1.44:8789<' in html
    assert "127.0.0.1" not in html


def test_downloads_ignores_container_bridge_public_base_url(monkeypatch, tmp_path):
    monkeypatch.setenv("HARRY_PUBLIC_BASE_URL", "http://172.17.0.2:8789")
    monkeypatch.setattr(brain_address, "detect_lan_ip", lambda: "192.168.1.44")
    html = _render_downloads(monkeypatch, tmp_path)

    assert 'id="brain-url">http://192.168.1.44:8789<' in html


def test_downloads_uses_harry_brain_lan_ip(monkeypatch, tmp_path):
    monkeypatch.delenv("HARRY_PUBLIC_BASE_URL", raising=False)
    monkeypatch.setenv("HARRY_BRAIN_LAN_IP", "192.168.1.88")
    monkeypatch.setenv("HARRY_PUBLIC_PORT", "8799")
    html = _render_downloads(monkeypatch, tmp_path)

    assert 'id="brain-url">http://192.168.1.88:8799<' in html
    assert "127.0.0.1" not in html


def test_downloads_rejects_detected_docker_bridge_ip(monkeypatch, tmp_path):
    html = router._downloads_fallback_help_html() + router._downloads_advanced_help_html()

    assert "Need help finding the address?" in html
    assert "Advanced configuration" in html
    assert "hostname -I" in html
    assert "ipconfig" in html


def test_downloads_rejects_detected_private_bridge_ip(monkeypatch, tmp_path):
    html = router._downloads_fallback_help_html() + router._downloads_advanced_help_html()

    assert "Need help finding the address?" in html
    assert "Advanced configuration" in html
    assert "hostname -I" in html
    assert "ipconfig" in html


def test_downloads_rejects_detected_link_local_ip(monkeypatch, tmp_path):
    html = router._downloads_fallback_help_html() + router._downloads_advanced_help_html()

    assert "Need help finding the address?" in html
    assert "Advanced configuration" in html
    assert "hostname -I" in html
    assert "ipconfig" in html


def test_downloads_removes_local_only_block(monkeypatch, tmp_path):
    monkeypatch.setenv("HARRY_PUBLIC_BASE_URL", "http://brain.example:8789")
    html = _render_downloads(monkeypatch, tmp_path)

    assert "Recommended Windows installer" not in html
    assert "Windows installer" in html
    assert "HarryAgentSetup.exe" in html
    assert "Other machines should use this address." in html
    assert "Advanced configuration" in html
    assert "windows-agent-script" not in html
    assert "http://127.0.0.1:8789" not in html
    assert "Docker/container networking" not in html
    assert "reverse proxy" not in html
    assert "mDNS" not in html


def test_downloads_uses_request_host_lan_ip(monkeypatch):
    monkeypatch.delenv("HARRY_PUBLIC_BASE_URL", raising=False)
    monkeypatch.delenv("HARRY_PUBLIC_PORT", raising=False)
    monkeypatch.delenv("HARRY_PORT", raising=False)
    monkeypatch.setattr(router, "_detect_lan_ip", lambda: None)
    request = _make_request("192.168.1.55:8787", scheme="http")
    public_url, local_url = router._resolve_brain_urls(request)

    assert public_url == "http://192.168.1.55:8787"
    assert local_url == "http://127.0.0.1:8787"


def test_downloads_ignores_container_bridge_request_host(monkeypatch):
    monkeypatch.delenv("HARRY_PUBLIC_BASE_URL", raising=False)
    monkeypatch.delenv("HARRY_PUBLIC_PORT", raising=False)
    monkeypatch.delenv("HARRY_PORT", raising=False)
    monkeypatch.setattr(brain_address, "detect_lan_ip", lambda: None)
    request = _make_request("172.17.0.2:8787", scheme="http")

    public_url, local_url = router._resolve_brain_urls(request)

    assert public_url == "http://<brain-ip>:8789"
    assert local_url == "http://127.0.0.1:8787"


def test_downloads_uses_detected_lan_ip_with_default_public_port(monkeypatch, tmp_path):
    monkeypatch.delenv("HARRY_PUBLIC_BASE_URL", raising=False)
    monkeypatch.delenv("HARRY_PUBLIC_PORT", raising=False)
    monkeypatch.delenv("HARRY_PORT", raising=False)
    monkeypatch.setattr(brain_address, "detect_lan_ip", lambda: "192.168.1.77")
    html = _render_downloads(monkeypatch, tmp_path)

    assert 'id="brain-url">http://192.168.1.77:8789<' in html
    assert "127.0.0.1" not in html


def test_downloads_domain_http_request_does_not_become_domain_port(monkeypatch):
    monkeypatch.delenv("HARRY_PUBLIC_BASE_URL", raising=False)
    monkeypatch.delenv("HARRY_PUBLIC_PORT", raising=False)
    monkeypatch.delenv("HARRY_PORT", raising=False)
    monkeypatch.setattr(brain_address, "detect_lan_ip", lambda: None)
    request = _make_request("brain.example", scheme="http")

    public_url, _ = router._resolve_brain_urls(request)

    assert public_url == "http://<brain-ip>:8789"


def test_downloads_https_domain_request_renders_https_domain(monkeypatch):
    monkeypatch.delenv("HARRY_PUBLIC_BASE_URL", raising=False)
    monkeypatch.delenv("HARRY_PUBLIC_PORT", raising=False)
    monkeypatch.delenv("HARRY_PORT", raising=False)
    monkeypatch.setattr(router, "_detect_lan_ip", lambda: None)
    request = _make_request("brain.example", scheme="https")

    public_url, _ = router._resolve_brain_urls(request)

    assert public_url == "https://brain.example"


def test_downloads_uses_placeholder_when_lan_ip_is_unavailable(monkeypatch, tmp_path):
    html = router._downloads_fallback_help_html() + router._downloads_advanced_help_html()

    assert "Need help finding the address?" in html
    assert "hostname -I" in html
    assert "ipconfig" in html
    assert "http://&lt;your-brain-ip&gt;:8789" in html
    assert "YOUR-BRAIN-IP" in html
    assert "http://192.168.1.100:8789" not in html
    assert "http://nas.local:8789" not in html
    assert "HARRY_PUBLIC_BASE_URL=http://&lt;your-brain-ip&gt;:8789" in html
    assert "YOUR-BRAIN-IP" in html
    assert "HARRY_BRAIN_LAN_IP" in html
    assert "HARRY_PUBLIC_PORT" in html
    assert "http://<brain-ip>:8789" not in html
    assert "127.0.0.1" not in html
    assert "Advanced configuration" in html


def test_downloads_primary_guidance_is_short(monkeypatch, tmp_path):
    monkeypatch.setattr(
        router,
        "_resolve_brain_address_info",
        lambda request: {
            "display_url": None,
            "warning": "Could not determine automatically.",
            "public_port": 8789,
            "local_url": "http://127.0.0.1:8789",
        },
    )
    monkeypatch.setattr(router, "_downloads_dir", lambda: tmp_path)
    html = router.downloads_page(_make_starlette_request()).body.decode("utf-8")

    assert "Could not determine automatically" in html
    assert "Other machines should use this address." in html
    assert "Docker/container networking" not in html
    assert "reverse-proxy" not in html


def test_discovery_diagnostics_section_shows_address_context(monkeypatch, tmp_path):
    _setup_temp_db(monkeypatch, tmp_path)
    monkeypatch.setenv("HARRY_PUBLIC_BASE_URL", "http://brain.example:8789")

    with TestClient(main.app) as client:
        resp = client.get("/diagnostics")

    assert resp.status_code == 200
    html = resp.text
    assert "Discovery diagnostics" in html
    assert "Brain Address" in html
    assert "Canonical address" in html
    assert "Recommended LAN" in html
    assert "Container networking" in html
    assert "Discovery methods" in html


def test_api_page_lists_core_endpoints_and_examples():
    with TestClient(main.app) as client:
        resp = client.get("/api")

    assert resp.status_code == 200
    html = resp.text
    assert "/health" in html
    assert "/discover" in html
    assert "/ingest" in html
    assert "/inventory.json" in html
    assert "curl http://&lt;brain-ip&gt;:8789/health" in html
    assert "Invoke-WebRequest http://&lt;brain-ip&gt;:8789/downloads/windows-agent" in html
    assert "import requests" in html
    assert "Privacy Mode Enabled" not in html
