from __future__ import annotations

from datetime import datetime, timezone

from app import node_metadata as nm
from app.ui import inventory as inventory_ui
from app.ui import node as node_ui


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
                    "agent_version": "0.2.3",
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
