from __future__ import annotations

from app.ui.copy import status_copy


def test_status_copy_uses_plain_friendly_lines():
    assert status_copy() == "Everything looks calm."
    assert status_copy(stale=True) == "Harry has not heard from this machine recently."
    assert status_copy(delayed=True) == "Harry is hearing from this machine a little late."
    assert status_copy(cpu_pressure_now=82.0) == "This machine is working hard right now."
    assert status_copy(disk_used_pct=91.0) == "Storage is the thing to watch here."
    assert status_copy(health_state="warning") == "A few things deserve a closer look."
    assert status_copy(health_state="critical") == "This machine needs attention."
    assert status_copy(gpus=[{"name": "RTX"}], capabilities={"gpu": True}) == "AI-capable hardware is available on this node."
