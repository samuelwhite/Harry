from __future__ import annotations

from datetime import datetime, timezone


def parse_iso_utc(ts_iso: str) -> datetime:
    s = (ts_iso or "").strip()
    if not s:
        return datetime.now(timezone.utc)

    # Accept Z or +00:00 style
    try:
        if s.endswith("Z"):
            return datetime.strptime(s, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    except Exception:
        pass

    try:
        s2 = s.replace("Z", "+00:00")
        dt = datetime.fromisoformat(s2)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except Exception:
        return datetime.now(timezone.utc)


def human(ts_iso: str) -> str:
    dt = parse_iso_utc(ts_iso)
    return dt.strftime("%a %d %b %Y %H:%M")


def relative(ts_iso: str, now: datetime | None = None) -> str:
    dt = parse_iso_utc(ts_iso)
    now = now or datetime.now(timezone.utc)
    sec = int((now - dt).total_seconds())

    if sec < 0:
        return "in the future (clock?)"
    if sec < 10:
        return "just now"
    if sec < 60:
        return f"{sec}s ago"
    mins = sec // 60
    if mins < 60:
        return f"{mins}m ago"
    hrs = mins // 60
    if hrs < 24:
        return f"{hrs}h ago"
    days = hrs // 24
    return f"{days}d ago"
