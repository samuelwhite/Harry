from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from types import SimpleNamespace
from datetime import datetime, timezone

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from starlette.requests import Request

import app.config as config
import app.brain_address as brain_address
import app.main as main
import importlib
from app.ui import db as dbmod
import app.ui.diagnostics as diagnostics

router = importlib.import_module("app.ui.router")


def _setup_temp_db(monkeypatch, tmp_path):
    db_path = tmp_path / "harry.db"
    monkeypatch.setattr(config, "DB_PATH", db_path, raising=False)
    monkeypatch.setattr(main, "DB_PATH", db_path, raising=False)
    monkeypatch.setattr(dbmod, "DB_PATH", str(db_path), raising=False)
    main._init_db()
    return db_path


def _insert_snapshot(db_path, payload):
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            "INSERT INTO ingest(ts, node, payload) VALUES(?, ?, ?)",
            (payload["ts"], payload["node"], json.dumps(payload)),
        )
        conn.commit()


def _render_downloads(monkeypatch, tmp_path, *, base_url=None, headers=None):
    _setup_temp_db(monkeypatch, tmp_path)
    monkeypatch.setattr(router, "_downloads_dir", lambda: tmp_path)

    client_kwargs = {}
    if base_url is not None:
        client_kwargs["base_url"] = base_url

    with TestClient(main.app, **client_kwargs) as client:
        return client.get("/downloads", headers=headers or {}).text


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


def _sample_snapshot(*, node: str = "nas-1") -> dict:
    now = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    return {
        "schema_version": "0.2.3",
        "node": node,
        "ts": now,
        "facts": {"cpu_cores": 4},
        "metrics": {
            "cpu_load_1m": 0.6,
            "mem_used_pct": 25.0,
            "disk_used": [
                {
                    "mount": "/volume1",
                    "fs": "/dev/vg1/volume_1",
                    "device": "/dev/vg1/volume_1",
                    "total_b": 1000000000,
                    "used_b": 880000000,
                    "free_b": 120000000,
                    "used_pct": 88.0,
                }
            ],
            "temps_c": {},
            "gpu": [],
            "extensions": {},
        },
        "derived": {"health": {"state": "healthy", "worst_severity": "ok", "reasons": []}, "extensions": {}},
        "advice": [
            {
                "id": "disk_warn_now",
                "category": "storage",
                "severity": "warn",
                "message": "Storage is getting tight (88%).",
                "recommendation": "Plan a cleanup or storage upgrade soon.",
            }
        ],
    }


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


def test_node_summary_includes_agent_update_mode():
    payload = {
        "node": "nas-1",
        "ts": "2026-05-07T12:00:00Z",
        "agent_version": "0.2.4",
        "capabilities": {
            "synology_dsm": True,
            "self_update_enabled": False,
            "update_mode": "manual",
        },
        "facts": {},
        "metrics": {"disk_used": [], "temps_c": {}, "gpu": [], "extensions": {}},
        "derived": {"health": {"state": "healthy", "worst_severity": "ok", "reasons": []}, "extensions": {}},
        "advice": [],
    }

    summary = main._node_summary(payload, ctx={})

    assert summary["update_mode"] == "manual"
    assert summary["self_update_enabled"] is False
    assert summary["update_display"] == "Manual update available"


def test_fleet_page_does_not_inject_full_page_refresh_script(monkeypatch):
    fleet = importlib.import_module("app.ui.fleet")
    monkeypatch.setattr(fleet, "render_fleet_live", lambda hours, debug: "<div id='fleet-live'></div>")
    fleet_html = fleet.render_fleet_page(hours=72, debug=False)

    assert "/fleet/partial" not in fleet_html
    assert "refreshFleet" not in fleet_html


def test_overview_shows_manual_update_available_without_making_node_unhealthy(monkeypatch, tmp_path):
    db_path = _setup_temp_db(monkeypatch, tmp_path)
    payload = _sample_snapshot(node="nas-1")
    payload["agent_version"] = "0.2.4"
    payload["capabilities"] = {
        "synology_dsm": True,
        "self_update_enabled": False,
        "update_mode": "manual",
    }
    _insert_snapshot(db_path, payload)

    with TestClient(main.app) as client:
        html = client.get("/").text

    assert "Manual update available" in html
    assert 'class="dot bad"' not in html
    assert "ADVICE · BAD" not in html


def test_overview_shows_awaiting_automatic_update_for_auto_nodes(monkeypatch, tmp_path):
    db_path = _setup_temp_db(monkeypatch, tmp_path)
    payload = _sample_snapshot(node="node-1")
    payload["agent_version"] = "0.2.4"
    payload["capabilities"] = {
        "self_update_enabled": True,
        "update_mode": "auto",
    }
    _insert_snapshot(db_path, payload)

    with TestClient(main.app) as client:
        html = client.get("/").text

    assert "Awaiting automatic update" in html


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
    assert data["brain_version"] == "2026.05.15"
    assert data["agent_version"] == "0.2.5"
    assert data["schema_current"] == "0.2.3"
    assert data["canonical_base_url"] == "http://brain.example:8789"
    assert data["address_warning"] is None
    assert data["address_source"] == "canonical"
    assert data["base_url"] == "http://brain.example:8789"
    assert data["ingest_url"] == "http://brain.example:8789/ingest"
    assert data["brain_installer_download_url"] == "http://brain.example:8789/downloads/windows-brain"
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
                "brain_version": "2026.05.15",
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


def test_downloads_exposes_windows_brain_setup(monkeypatch, tmp_path):
    _setup_temp_db(monkeypatch, tmp_path)
    monkeypatch.setenv("HARRY_DOWNLOADS_DIR", str(tmp_path))
    (tmp_path / "HarryBrainSetup.exe").write_bytes(b"MZ")
    (tmp_path / "HarryBrainSetup.manifest.json").write_text(
        json.dumps(
            {
                "installer_name": "HarryBrainSetup.exe",
                "brain_version": "2026.05.15",
                "agent_version": "0.2.5",
                "schema_current": "0.2.3",
            }
        ),
        encoding="utf-8",
    )

    with TestClient(main.app) as client:
        resp = client.get("/downloads/windows-brain")

    assert resp.status_code == 200
    assert "HarryBrainSetup.exe" in resp.headers["content-disposition"]


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


def test_downloads_rejects_stale_windows_brain_setup(monkeypatch, tmp_path):
    _setup_temp_db(monkeypatch, tmp_path)
    monkeypatch.setenv("HARRY_DOWNLOADS_DIR", str(tmp_path))
    (tmp_path / "HarryBrainSetup.exe").write_bytes(b"MZ")
    (tmp_path / "HarryBrainSetup.manifest.json").write_text(
        json.dumps(
            {
                "installer_name": "HarryBrainSetup.exe",
                "brain_version": "2026.03.18",
                "agent_version": "0.2.3",
                "schema_current": "0.2.3",
            }
        ),
        encoding="utf-8",
    )

    with TestClient(main.app) as client:
        resp = client.get("/downloads/windows-brain")

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


def test_downloads_prefers_forwarded_proxy_headers(monkeypatch, tmp_path):
    html = _render_downloads(
        monkeypatch,
        tmp_path,
        headers={
            "host": "127.0.0.1:8789",
            "x-forwarded-host": "brain.example",
            "x-forwarded-proto": "https",
        },
    )

    assert 'id="brain-url">https://brain.example<' in html
    assert "Could not determine automatically" not in html


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
    (tmp_path / "HarryAgentSetup.exe").write_bytes(b"MZ")
    (tmp_path / "HarryBrainSetup.exe").write_bytes(b"MZ")
    html = _render_downloads(monkeypatch, tmp_path)

    assert "Recommended Windows installer" not in html
    assert "Windows installer" not in html
    assert "HarryAgentSetup.exe" in html
    assert "HarryBrainSetup.exe" in html
    assert html.count("HarryAgentSetup.exe") == 1
    assert html.count("HarryBrainSetup.exe") == 1
    assert "/downloads/windows-agent" in html
    assert "/downloads/windows-brain" in html
    assert "/downloads/windows-agent-exe" not in html
    assert "Download Windows installer" not in html
    assert "Other machines should use this address." in html
    assert "Advanced configuration" in html
    assert "http://127.0.0.1:8789" not in html
    assert "Docker/container networking" not in html
    assert "reverse proxy" not in html
    assert "mDNS" not in html


def test_downloads_includes_synology_guidance(monkeypatch, tmp_path):
    html = _render_downloads(monkeypatch, tmp_path)

    assert "Synology NAS" in html
    assert "Task Scheduler" in html
    assert "Enable SSH" in html
    assert 'sudo HARRY_PLATFORM="synology-dsm" curl -fsSL http://&lt;brain-ip&gt;:8789/downloads/linux-agent | bash' in html
    assert "./run-harry-agent.sh" in html
    assert "PATH" in html
    assert "install owner" in html
    assert "usually root when installed with sudo" in html
    assert "self-update is disabled by default" in html


def test_downloads_linux_agent_prefers_live_installer_source(monkeypatch, tmp_path):
    _setup_temp_db(monkeypatch, tmp_path)
    monkeypatch.setattr(router, "_downloads_dir", lambda: tmp_path)

    response = router.download_linux_agent()

    assert Path(response.path) == Path("scripts/install-agent.sh").resolve()


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


def test_downloads_domain_http_request_uses_domain_host(monkeypatch):
    monkeypatch.delenv("HARRY_PUBLIC_BASE_URL", raising=False)
    monkeypatch.delenv("HARRY_PUBLIC_PORT", raising=False)
    monkeypatch.delenv("HARRY_PORT", raising=False)
    monkeypatch.setattr(brain_address, "detect_lan_ip", lambda: None)
    request = _make_request("brain.example", scheme="http")

    public_url, _ = router._resolve_brain_urls(request)

    assert public_url == "http://brain.example"


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

    monkeypatch.setattr(
        diagnostics,
        "build_nodeviews",
        lambda hours=72: [SimpleNamespace(stale=False, agent_version="0.2.5", health_state="healthy", advice_sev=None, age_minutes=2, advice=[])],
    )
    monkeypatch.setattr(diagnostics, "_service_summary", lambda: None)
    monkeypatch.setattr(diagnostics, "_installer_download_issues", lambda: [])

    html = diagnostics.render_diagnostics_page(_make_starlette_request(), hours=72, debug=False)
    assert "Agents reporting?" in html
    assert "Advanced diagnostics" in html
    assert "Brain Address" in html
    assert "Canonical address" in html
    assert "Recommended LAN" in html
    assert "Container networking" in html
    assert "Discovery methods" in html
    assert "Agent installer artifact" in html[html.index("Advanced diagnostics") :]
    assert "Brain installer artifact" in html[html.index("Advanced diagnostics") :]
    assert "Brain reachable?" not in html
    assert "Agent installer artifact" not in html[:html.index("Advanced diagnostics")]
    assert "Brain installer artifact" not in html[:html.index("Advanced diagnostics")]
    assert "Healthy" in html
    assert "Unknown" not in html[:html.index("Advanced diagnostics")]
    assert "Service Health" not in html
    assert 'id="recommendations"' not in html
    assert "commit installer artifact" not in html.lower()
    assert "HARRY_PUBLIC_BASE_URL" not in html[:html.index("Advanced diagnostics")]


def test_diagnostics_service_health_is_positive_for_healthy_services(monkeypatch, tmp_path):
    _setup_temp_db(monkeypatch, tmp_path)

    monkeypatch.setattr(
        diagnostics,
        "build_nodeviews",
        lambda hours=72: [SimpleNamespace(stale=False, agent_version="0.2.5", health_state="healthy", advice_sev=None, age_minutes=2, advice=[])],
    )
    monkeypatch.setattr(
        diagnostics,
        "_service_summary",
        lambda: ("Service Health", "2 watched services healthy.", "ok", "Healthy"),
    )
    monkeypatch.setattr(diagnostics, "_installer_download_issues", lambda: [])

    html = diagnostics.render_diagnostics_page(_make_starlette_request(), hours=72, debug=False)
    summary_html = html.split('<details class="card compactcard" id="advanced-diagnostics">', 1)[0]
    assert 'id="diagnostic-summary"' in html
    assert "Service Health" in summary_html
    assert "Healthy" in html
    assert "Unknown" not in summary_html


def test_diagnostics_hides_recommendations_when_healthy(monkeypatch, tmp_path):
    _setup_temp_db(monkeypatch, tmp_path)

    monkeypatch.setattr(
        diagnostics,
        "build_nodeviews",
        lambda hours=72: [SimpleNamespace(stale=False, agent_version="0.2.5", health_state="healthy", advice_sev=None, age_minutes=2, advice=[])],
    )
    monkeypatch.setattr(diagnostics, "_service_summary", lambda: None)
    monkeypatch.setattr(diagnostics, "_installer_download_issues", lambda: [])

    html = diagnostics.render_diagnostics_page(_make_starlette_request(), hours=72, debug=False)
    assert 'id="recommendations"' not in html
    assert "Service Health" not in html
    assert "Healthy systems should feel calm and minimal." in html


def test_diagnostics_filters_info_only_advice_from_recommendations(monkeypatch, tmp_path):
    _setup_temp_db(monkeypatch, tmp_path)

    monkeypatch.setattr(
        diagnostics,
        "build_nodeviews",
        lambda hours=72: [
            SimpleNamespace(
                stale=False,
                agent_version="0.2.4",
                health_state="healthy",
                advice_sev=None,
                age_minutes=2,
                advice=[
                    {
                        "severity": "info",
                        "message": "Memory baseline is elevated (median 62% over ~6h).",
                        "recommendation": "Not urgent, but it reduces headroom for spikes.",
                    }
                ],
            )
        ],
    )
    monkeypatch.setattr(diagnostics, "_service_summary", lambda: None)
    monkeypatch.setattr(diagnostics, "_installer_download_issues", lambda: [])

    html = diagnostics.render_diagnostics_page(_make_starlette_request(), hours=72, debug=False)

    assert 'id="recommendations"' in html
    assert "Restart or update the agents that are stale or behind." in html
    assert "Memory baseline is elevated" not in html


def test_api_page_lists_core_endpoints_and_examples():
    with TestClient(main.app) as client:
        resp = client.get("/api")

    assert resp.status_code == 200
    html = resp.text
    assert "/health" in html
    assert "/discover" in html
    assert "/ingest" in html
    assert "/inventory.json" in html
    assert "Overview" in html
    assert "Inventory" in html
    assert "Diagnostics" in html
    assert "Downloads" in html
    assert ">API<" in html or "API</a>" in html
    assert 'href="/#overview"' in html
    assert 'href="/inventory' in html
    assert 'href="/diagnostics' in html
    assert 'href="/downloads' in html
    assert 'href="/api"' in html
    assert "curl http://&lt;brain-ip&gt;:8789/health" in html
    assert "Invoke-WebRequest http://&lt;brain-ip&gt;:8789/downloads/windows-brain" in html
    assert "import requests" in html
    assert "Privacy Mode Enabled" not in html
