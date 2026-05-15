from __future__ import annotations

from typing import Any


def _coerce_float(value: Any) -> float | None:
    try:
        if value is None or value == "":
            return None
        return float(value)
    except Exception:
        return None


def _format_number(value: float) -> str:
    text = f"{value:.1f}"
    return text[:-2] if text.endswith(".0") else text


def format_bytes_human(value: Any) -> str:
    num = _coerce_float(value)
    if num is None:
        return "—"

    abs_num = abs(num)
    for unit in ("B", "KB", "MB", "GB", "TB", "PB"):
        if abs_num < 1000.0 or unit == "PB":
            return f"{_format_number(num)}{unit}"
        num /= 1000.0
        abs_num /= 1000.0

    return "—"


def format_capacity_gb(value: Any) -> str:
    num = _coerce_float(value)
    if num is None:
        return "—"

    abs_num = abs(num)
    if abs_num >= 1000.0:
        return f"{_format_number(num / 1000.0)}TB"
    if abs_num >= 1.0:
        return f"{_format_number(num)}GB"
    return f"{_format_number(num * 1000.0)}MB"
