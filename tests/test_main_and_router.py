from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

import app.config as config
import app.main as main
import importlib
from app.ui import db as dbmod
from app.ui.templates import render_shell

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


def test_render_shell_includes_page_eyebrow():
    html = render_shell(
        title="HARRY Fleet",
        active_page="fleet",
        page_title="Fleet",
        page_subtitle="Live status",
        sidebar_sections=[
            {"label": "Fleet", "items": [{"label": "Overview", "href": "/"}]},
            {"label": "Inventory", "items": [{"label": "Summary", "href": "/inventory"}]},
        ],
        actions=[],
        content="",
    )

    assert "Fleet overview" in html
    assert '<div class="eyebrow">Fleet overview</div>' in html
    assert 'class="topnav-link active"' in html
    assert ">Overview</a>" in html


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
    assert data["base_url"] == "http://brain.example:8789"
    assert data["ingest_url"] == "http://brain.example:8789/ingest"

    assert well_known.status_code == 200
    assert well_known.json() == data


def test_downloads_prefers_non_local_public_base_url(monkeypatch, tmp_path):
    monkeypatch.setenv("HARRY_PUBLIC_BASE_URL", "http://brain.example:8789")
    html = _render_downloads(monkeypatch, tmp_path)

    assert 'id="brain-url">http://brain.example:8789<' in html
    assert "On this machine only" not in html
    assert "127.0.0.1" not in html


def test_downloads_uses_placeholder_env_only_as_fallback(monkeypatch, tmp_path):
    monkeypatch.setenv("HARRY_PUBLIC_BASE_URL", "http://<brain-ip>:8789")
    monkeypatch.setattr(router, "_detect_lan_ip", lambda: "192.168.1.44")
    html = _render_downloads(monkeypatch, tmp_path)

    assert 'id="brain-url">http://192.168.1.44:8789<' in html
    assert "127.0.0.1" not in html


def test_downloads_ignores_container_bridge_public_base_url(monkeypatch, tmp_path):
    monkeypatch.setenv("HARRY_PUBLIC_BASE_URL", "http://172.17.0.2:8789")
    monkeypatch.setattr(router, "_detect_lan_ip", lambda: "192.168.1.44")
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
    monkeypatch.delenv("HARRY_PUBLIC_BASE_URL", raising=False)
    monkeypatch.delenv("HARRY_PUBLIC_PORT", raising=False)
    monkeypatch.delenv("HARRY_PORT", raising=False)
    monkeypatch.delenv("HARRY_BRAIN_LAN_IP", raising=False)
    monkeypatch.setattr(router, "_detect_lan_ip", lambda: "172.17.0.2")
    html = _render_downloads(monkeypatch, tmp_path)

    assert 'id="brain-url">http://&lt;brain-ip&gt;:8789<' in html


def test_downloads_rejects_detected_private_bridge_ip(monkeypatch, tmp_path):
    monkeypatch.delenv("HARRY_PUBLIC_BASE_URL", raising=False)
    monkeypatch.delenv("HARRY_PUBLIC_PORT", raising=False)
    monkeypatch.delenv("HARRY_PORT", raising=False)
    monkeypatch.delenv("HARRY_BRAIN_LAN_IP", raising=False)
    monkeypatch.setattr(router, "_detect_lan_ip", lambda: "192.168.240.2")
    html = _render_downloads(monkeypatch, tmp_path)

    assert 'id="brain-url">http://&lt;brain-ip&gt;:8789<' in html


def test_downloads_rejects_detected_link_local_ip(monkeypatch, tmp_path):
    monkeypatch.delenv("HARRY_PUBLIC_BASE_URL", raising=False)
    monkeypatch.delenv("HARRY_PUBLIC_PORT", raising=False)
    monkeypatch.delenv("HARRY_PORT", raising=False)
    monkeypatch.delenv("HARRY_BRAIN_LAN_IP", raising=False)
    monkeypatch.setattr(router, "_detect_lan_ip", lambda: "169.254.10.4")
    html = _render_downloads(monkeypatch, tmp_path)

    assert 'id="brain-url">http://&lt;brain-ip&gt;:8789<' in html


def test_downloads_removes_local_only_block(monkeypatch, tmp_path):
    monkeypatch.setenv("HARRY_PUBLIC_BASE_URL", "http://brain.example:8789")
    html = _render_downloads(monkeypatch, tmp_path)

    assert "The installer will try to find Harry Brain automatically." in html
    assert "On this machine only" not in html
    assert "Only works from this Brain machine." not in html
    assert "http://127.0.0.1:8789" not in html


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
    monkeypatch.setattr(router, "_detect_lan_ip", lambda: None)
    request = _make_request("172.17.0.2:8787", scheme="http")

    public_url, local_url = router._resolve_brain_urls(request)

    assert public_url == "http://<brain-ip>:8789"
    assert local_url == "http://127.0.0.1:8789"


def test_downloads_uses_detected_lan_ip_with_default_public_port(monkeypatch, tmp_path):
    monkeypatch.delenv("HARRY_PUBLIC_BASE_URL", raising=False)
    monkeypatch.delenv("HARRY_PUBLIC_PORT", raising=False)
    monkeypatch.delenv("HARRY_PORT", raising=False)
    monkeypatch.setattr(router, "_detect_lan_ip", lambda: "192.168.1.77")
    html = _render_downloads(monkeypatch, tmp_path)

    assert 'id="brain-url">http://192.168.1.77:8789<' in html
    assert "127.0.0.1" not in html


def test_downloads_domain_http_request_does_not_become_domain_port(monkeypatch):
    monkeypatch.delenv("HARRY_PUBLIC_BASE_URL", raising=False)
    monkeypatch.delenv("HARRY_PUBLIC_PORT", raising=False)
    monkeypatch.delenv("HARRY_PORT", raising=False)
    monkeypatch.setattr(router, "_detect_lan_ip", lambda: None)
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
    monkeypatch.delenv("HARRY_PUBLIC_BASE_URL", raising=False)
    monkeypatch.delenv("HARRY_PUBLIC_PORT", raising=False)
    monkeypatch.delenv("HARRY_PORT", raising=False)
    monkeypatch.setattr(router, "_detect_lan_ip", lambda: None)
    html = _render_downloads(monkeypatch, tmp_path)

    assert 'id="brain-url">http://&lt;brain-ip&gt;:8789<' in html
    assert "HARRY_PUBLIC_BASE_URL=http://&lt;brain-ip&gt;:8789" in html
    assert "127.0.0.1" not in html
