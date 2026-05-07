from __future__ import annotations

from types import SimpleNamespace

import app.ui.fleet as fleet


def test_render_fleet_live_uses_single_node_mode(monkeypatch):
    nodeview = SimpleNamespace(
        node="brain",
        node_id="brain",
        worst="ok",
        ts=None,
        model="Harry Brain",
        cpu="Ryzen",
        headline="Everything looks calm.",
        health_state="healthy",
        stale=False,
        cpu_pressure_avg_72h=None,
        temp_c=None,
        ram_used_pct=None,
        gpus=[],
        trend_gpu_wide_svg="",
        trend_ram_svg="",
        trend_cpu_svg="",
        trend_temp_svg="",
        trend_disk_svg="",
        advice=[],
        advice_sev="ok",
        advice_counts={"warn": 0, "bad": 0},
        cpu_pressure_now=None,
        load1=None,
        cpu_pressure_band="low",
        activity_score=0.0,
        ram_total="—",
        disk_used_pct=None,
        gpu_used_pct=None,
        logical_cores=None,
        bios="—",
        cpu_pressure_peak_72h=None,
        age_minutes=None,
        capabilities={"gpu": True},
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
    assert "<node-card />" in html
    assert "<trend-block />" in html
    assert "Map, freshness, versions." not in html
