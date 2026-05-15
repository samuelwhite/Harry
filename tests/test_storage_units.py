from __future__ import annotations

from app.units import format_bytes_human, format_capacity_gb


def test_capacity_formatting_uses_friendly_units():
    assert format_capacity_gb(1900) == "1.9TB"
    assert format_capacity_gb(11000) == "11TB"
    assert format_capacity_gb(750) == "750GB"
    assert format_capacity_gb(0.5) == "500MB"


def test_byte_formatting_uses_friendly_units():
    assert format_bytes_human(1900 * 1_000_000_000) == "1.9TB"
    assert format_bytes_human(11 * 1_000_000_000_000) == "11TB"
    assert format_bytes_human(750 * 1_000_000_000) == "750GB"
    assert format_bytes_human(512 * 1_000_000) == "512MB"
