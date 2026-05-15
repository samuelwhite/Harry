from __future__ import annotations

from datetime import datetime, timezone

from app import node_metadata as nm
from app.ui import inventory as inventory_ui
from app.ui import node as node_ui
from app import activity_feed as activity_feed_ui


def test_node_metadata_loads_from_json_and_formats_summary(monkeypatch, tmp_path):
    monkeypatch.setenv(
        "HARRY_NODE_METADATA_JSON",
        """
        {
          "nodes": [
            {
              "node": "node-1",
              "display_name": "Example Node",
              "role": "Media Server",
              "character": "NAS",
              "location": "Rack Shelf",
              "tags": ["gpu", "llm", "automation"]
            }
          ]
        }
        """,
    )

    meta = nm.load_node_metadata()

    assert meta["node-1"]["display_name"] == "Example Node"
    assert meta["node-1"]["role"] == "Media Server"
    assert nm.node_display_name("node-1") == "Example Node"
    assert nm.node_meta_summary("node-1") == "Media Server · NAS · Rack Shelf · gpu, llm, automation"
    assert nm.node_display_name("missing") == "missing"


def test_privacy_mode_off_shows_real_names(monkeypatch):
    monkeypatch.delenv("HARRY_PRIVACY_MODE", raising=False)
    monkeypatch.delenv("HARRY_ANONYMIZE_UI", raising=False)
    monkeypatch.setenv(
        "HARRY_NODE_METADATA_JSON",
        """
        {
          "nodes": [
            {
              "node": "node-1",
              "display_name": "Example Node"
            }
          ]
        }
        """,
    )
    nm.reset_privacy_aliases()

    assert nm.privacy_mode_enabled() is False
    assert nm.node_display_name("node-1") == "Example Node"


def test_privacy_mode_on_uses_aliases_and_hides_real_names(monkeypatch):
    monkeypatch.setenv("HARRY_PRIVACY_MODE", "1")
    monkeypatch.setenv(
        "HARRY_NODE_METADATA_JSON",
        """
        {
          "nodes": [
            {
              "node": "samuel-laptop",
              "display_name": "Samuel Laptop",
              "role": "Windows workstation"
            }
          ]
        }
        """,
    )
    nm.reset_privacy_aliases()
    nm.prime_privacy_aliases(["samuel-laptop"])

    assert nm.privacy_mode_enabled() is True
    assert nm.node_display_name("samuel-laptop") == "Windows Workstation"
    assert nm.node_meta_summary("samuel-laptop") == "Windows Workstation"
    assert nm.node_route_id("samuel-laptop") == "windows-workstation"


def test_custom_privacy_alias_override_wins(monkeypatch):
    monkeypatch.setenv("HARRY_PRIVACY_MODE", "1")
    monkeypatch.setenv("HARRY_PRIVACY_ALIASES_JSON", '{"samuel-laptop": "Media Server"}')
    monkeypatch.setenv(
        "HARRY_NODE_METADATA_JSON",
        """
        {
          "nodes": [
            {
              "node": "samuel-laptop",
              "display_name": "Samuel Laptop"
            }
          ]
        }
        """,
    )
    nm.reset_privacy_aliases()
    nm.prime_privacy_aliases(["samuel-laptop"])

    assert nm.node_display_name("samuel-laptop") == "Media Server"
    assert nm.node_route_id("samuel-laptop") == "media-server"


def test_privacy_aliases_are_stable_across_requests(monkeypatch):
    monkeypatch.setenv("HARRY_PRIVACY_MODE", "1")
    nm.reset_privacy_aliases()

    nm.prime_privacy_aliases(["alpha-node", "beta-node"])
    first = (nm.node_display_name("alpha-node"), nm.node_display_name("beta-node"))

    nm.prime_privacy_aliases(["beta-node", "alpha-node"])
    second = (nm.node_display_name("alpha-node"), nm.node_display_name("beta-node"))

    assert first == second


def test_fallback_alias_generation_works(monkeypatch):
    monkeypatch.setenv("HARRY_PRIVACY_MODE", "1")
    nm.reset_privacy_aliases()
    nm.prime_privacy_aliases(["alpha-node", "beta-node"])

    alpha = nm.node_display_name("alpha-node")
    beta = nm.node_display_name("beta-node")

    assert alpha.startswith("Node ")
    assert beta.startswith("Node ")
    assert alpha != beta


def test_inventory_rows_include_node_metadata(monkeypatch, tmp_path):
    monkeypatch.setenv(
        "HARRY_NODE_METADATA_FILE",
        str(tmp_path / "node_metadata.json"),
    )
    (tmp_path / "node_metadata.json").write_text(
        """
        {
          "node-1": {
            "display_name": "Example Node",
            "role": "Media Server",
            "character": "NAS",
            "location": "Rack Shelf",
            "tags": ["gpu", "llm", "automation"]
          }
        }
        """,
        encoding="utf-8",
    )

    rows = inventory_ui.build_inventory_rows(
        {
            "node-1": {
                "ts": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                "payload": {
                    "node": "node-1",
                    "agent_version": "0.2.5",
                    "facts": {},
                    "metrics": {"disk_used": [], "temps_c": {}, "gpu": [], "extensions": {}},
                    "derived": {"health": {"state": "healthy", "worst_severity": "ok", "reasons": []}, "extensions": {}},
                    "advice": [],
                },
            }
        }
    )

    row = rows[0]
    assert row["display_name"] == "Example Node"
    assert row["meta"] == "Media Server · NAS · Rack Shelf · gpu, llm, automation"
    assert "Example Node" in inventory_ui._inventory_md(rows)


def test_privacy_mode_hides_real_names_in_rendered_html(monkeypatch):
    monkeypatch.setenv("HARRY_PRIVACY_MODE", "1")
    monkeypatch.setenv(
        "HARRY_NODE_METADATA_JSON",
        """
        {
          "nodes": [
            {
              "node": "samuel-laptop",
              "display_name": "Samuel Laptop",
              "role": "Windows workstation"
            }
          ]
        }
        """,
    )
    nm.reset_privacy_aliases()

    monkeypatch.setattr(node_ui, "get_machine_summary", lambda payload: None)
    monkeypatch.setattr(
        node_ui,
        "get_latest_node_records",
        lambda: {
            "samuel-laptop": {
                "ts": "2026-05-07T12:00:00Z",
                "payload": {
                    "node": "samuel-laptop",
                    "ts": "2026-05-07T12:00:00Z",
                    "facts": {"hostname": "samuel-laptop"},
                },
            }
        },
    )
    monkeypatch.setattr(
        node_ui,
        "get_latest_node_record",
        lambda node: {
            "ts": "2026-05-07T12:00:00Z",
            "payload": "{\"node\":\"samuel-laptop\",\"ts\":\"2026-05-07T12:00:00Z\",\"facts\":{\"hostname\":\"samuel-laptop\"}}",
        },
    )

    html = node_ui.render_node_detail("samuel-laptop", hours=72)

    assert "Privacy Mode Enabled" in html
    assert "Samuel Laptop" not in html
    assert "samuel-laptop" not in html
    assert "Windows Workstation" in html


def test_privacy_mode_applies_to_recent_activity(monkeypatch):
    monkeypatch.setenv("HARRY_PRIVACY_MODE", "1")
    nm.reset_privacy_aliases()

    now = datetime.now(timezone.utc)
    items = activity_feed_ui.prepare_activity_items(
        [
            {
                "type": "agent.heartbeat_missed",
                "created_at": now.isoformat(),
                "node_id": "samuel-laptop",
                "metadata": {"gap_seconds": 120},
            }
        ],
        now=now,
        current_nodes={"samuel-laptop": {"ts": now.isoformat(), "payload": {}}},
    )

    assert items
    assert "samuel-laptop" not in items[0]["title"]


def test_node_detail_uses_display_name_and_metadata(monkeypatch):
    monkeypatch.setenv(
        "HARRY_NODE_METADATA_JSON",
        """
        {
          "nodes": [
            {
              "node": "node-1",
              "display_name": "Example Node",
              "role": "Media Server",
              "character": "NAS",
              "location": "Rack Shelf",
              "tags": ["gpu", "llm", "automation"]
            }
          ]
        }
        """,
    )
    monkeypatch.setattr(node_ui, "get_machine_summary", lambda payload: None)
    monkeypatch.setattr(
        node_ui,
        "get_latest_node_record",
        lambda node: {
            "ts": "2026-05-07T12:00:00Z",
            "payload": "{\"node\":\"node-1\",\"ts\":\"2026-05-07T12:00:00Z\"}",
        },
    )

    html = node_ui.render_node_detail("node-1", hours=72)

    assert "Example Node" in html
    assert "Media Server · NAS · Rack Shelf · gpu, llm, automation" in html


def test_node_detail_renders_recommendations_when_present(monkeypatch):
    monkeypatch.setattr(node_ui, "get_machine_summary", lambda payload: None)
    monkeypatch.setattr(node_ui, "get_latest_node_records", lambda: {"node-1": {"ts": "2026-05-07T12:00:00Z", "payload": {}}})
    monkeypatch.setattr(
        node_ui,
        "get_latest_node_record",
        lambda node: {
            "ts": "2026-05-07T12:00:00Z",
            "payload": """
            {
              "node": "node-1",
              "ts": "2026-05-07T12:00:00Z",
              "facts": {},
              "metrics": {"disk_used": [], "temps_c": {}, "gpu": [], "extensions": {}},
              "derived": {"health": {"state": "healthy", "worst_severity": "ok", "reasons": []}, "extensions": {}},
              "advice": [
                {
                  "severity": "warn",
                  "message": "Memory usage is high (86%).",
                  "recommendation": "Keep an eye on it; tune services or plan a RAM upgrade if this is typical."
                }
              ]
            }
            """,
        },
    )

    html = node_ui.render_node_detail("node-1", hours=72)

    assert 'id="node-recommendations"' in html
    assert "Memory usage is high (86%)." in html
    assert "RAM upgrade" in html


def test_node_detail_stays_calm_when_no_recommendations_exist(monkeypatch):
    monkeypatch.setattr(node_ui, "get_machine_summary", lambda payload: None)
    monkeypatch.setattr(node_ui, "get_latest_node_records", lambda: {"node-1": {"ts": "2026-05-07T12:00:00Z", "payload": {}}})
    monkeypatch.setattr(
        node_ui,
        "get_latest_node_record",
        lambda node: {
            "ts": "2026-05-07T12:00:00Z",
            "payload": "{\"node\":\"node-1\",\"ts\":\"2026-05-07T12:00:00Z\",\"facts\":{},\"metrics\":{\"disk_used\":[],\"temps_c\":{},\"gpu\":[],\"extensions\":{}},\"derived\":{\"health\":{\"state\":\"healthy\",\"worst_severity\":\"ok\",\"reasons\":[]},\"extensions\":{}},\"advice\":[]}",
        },
    )

    html = node_ui.render_node_detail("node-1", hours=72)

    assert 'id="node-recommendations"' not in html


def test_node_detail_renders_synology_manual_update_mode(monkeypatch):
    monkeypatch.setattr(node_ui, "get_machine_summary", lambda payload: None)
    monkeypatch.setattr(node_ui, "get_latest_node_records", lambda: {"nas-1": {"ts": "2026-05-07T12:00:00Z", "payload": {}}})
    monkeypatch.setattr(
        node_ui,
        "get_latest_node_record",
        lambda node: {
            "ts": "2026-05-07T12:00:00Z",
            "payload": """
            {
              "node": "nas-1",
              "ts": "2026-05-07T12:00:00Z",
              "agent_version": "0.2.4",
              "capabilities": {
                "synology_dsm": true,
                "self_update_enabled": false,
                "update_mode": "manual"
              },
              "facts": {},
              "metrics": {"disk_used": [], "temps_c": {}, "gpu": [], "extensions": {}},
              "derived": {"health": {"state": "healthy", "worst_severity": "ok", "reasons": []}, "extensions": {}},
              "advice": []
            }
            """,
        },
    )

    html = node_ui.render_node_detail("nas-1", hours=72)

    assert "Agent update mode" in html
    assert "Manual update available" in html
    assert "Mode: manual" in html
    assert "Self-update: disabled" in html


def test_node_detail_renders_linux_auto_update_mode(monkeypatch):
    monkeypatch.setattr(node_ui, "get_machine_summary", lambda payload: None)
    monkeypatch.setattr(node_ui, "get_latest_node_records", lambda: {"node-1": {"ts": "2026-05-07T12:00:00Z", "payload": {}}})
    monkeypatch.setattr(
        node_ui,
        "get_latest_node_record",
        lambda node: {
            "ts": "2026-05-07T12:00:00Z",
            "payload": """
            {
              "node": "node-1",
              "ts": "2026-05-07T12:00:00Z",
              "agent_version": "0.2.4",
              "capabilities": {
                "self_update_enabled": true,
                "update_mode": "auto"
              },
              "facts": {},
              "metrics": {"disk_used": [], "temps_c": {}, "gpu": [], "extensions": {}},
              "derived": {"health": {"state": "healthy", "worst_severity": "ok", "reasons": []}, "extensions": {}},
              "advice": []
            }
            """,
        },
    )

    html = node_ui.render_node_detail("node-1", hours=72)

    assert "Agent update mode" in html
    assert "Awaiting automatic update" in html
    assert "Mode: auto" in html
    assert "Self-update: enabled" in html
