from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace

import app.ui.fleet as fleet


def test_render_fleet_live_uses_single_node_mode(monkeypatch):
    nodeview = SimpleNamespace(
        node="brain",
        node_id="brain",
        worst="ok",
        ts=datetime(2026, 5, 7, 12, 0, tzinfo=timezone.utc),
        model="Harry Brain",
        cpu="Ryzen",
        headline="Everything looks calm.",
        health_state="healthy",
        stale=False,
        agent_version="0.2.5",
        cpu_pressure_avg_72h=None,
        temp_c=None,
        ram_used_pct=48.5,
        trend_gpu_wide_svg="",
        trend_ram_svg="",
        trend_cpu_svg="",
        trend_temp_svg="",
        trend_disk_svg="",
        advice=[],
        advice_sev="ok",
        advice_counts={"warn": 0, "bad": 0},
        cpu_pressure_now=24.0,
        load1=0.42,
        cpu_pressure_band="low",
        activity_score=0.0,
        ram_total="32GB",
        disk_used_pct=91.2,
        gpu_used_pct=12.0,
        logical_cores=None,
        bios="—",
        cpu_pressure_peak_72h=None,
        age_minutes=None,
        gpus=[{"name": "RTX 4000"}],
        capabilities={"gpu": True, "docker": True, "systemd": True, "temperature": True, "smart": False},
    )

    monkeypatch.setattr(fleet, "build_nodeviews", lambda hours=72: [nodeview])
    monkeypatch.setattr(fleet, "build_hidden_nodeviews", lambda hours=72: [])
    monkeypatch.setattr(fleet, "_render_top_banner", lambda nodes: "<top-banner />")
    monkeypatch.setattr(fleet, "_fleet_outlier_pills", lambda nodes: "<outlier-pills />")
    monkeypatch.setattr(fleet, "_render_node_card", lambda nv, hours, debug: "<node-card />")
    monkeypatch.setattr(fleet, "_render_fleet_trends", lambda nodes, hours: "<trend-block />")

    html = fleet.render_fleet_live(hours=24, debug=False)

    assert "Harry is watching this machine." in html
    assert "This is the Brain node." in html
    assert "Brain service is healthy." in html
    assert "Why Harry says this" in html
    assert "CPU" in html
    assert "Memory" in html
    assert "Disk" in html
    assert "GPU" in html
    assert "Last heartbeat" in html
    assert "Capabilities" in html
    assert "<node-card />" in html
    assert "<trend-block />" in html
    assert "Map, freshness, versions." not in html
