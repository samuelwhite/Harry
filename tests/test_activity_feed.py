from __future__ import annotations

from datetime import datetime, timedelta, timezone

from app.activity_feed import format_duration, format_relative_ago, prepare_activity_items


def test_relative_time_formatting_uses_human_readable_ranges():
    now = datetime(2026, 5, 7, 12, 0, tzinfo=timezone.utc)

    assert format_relative_ago(now - timedelta(seconds=12), now=now) == "just now"
    assert format_relative_ago(now - timedelta(minutes=12), now=now) == "12 minutes ago"
    assert format_relative_ago(now - timedelta(hours=9, minutes=33), now=now) == "9h 33m ago"
    assert format_relative_ago(now - timedelta(days=1), now=now) == "yesterday"
    assert format_relative_ago(now - timedelta(days=1, hours=4), now=now) == "1d 4h ago"


def test_duration_formatting_avoids_raw_minute_counts():
    assert format_duration(0) == "just now"
    assert format_duration(9) == "about 9 minutes"
    assert format_duration(60) == "about 1 hour"
    assert format_duration(72) == "1h 12m"
    assert format_duration(573) == "9h 33m"


def test_activity_feed_groups_heartbeat_recovery_pairs():
    now = datetime(2026, 5, 7, 12, 0, tzinfo=timezone.utc)
    events = [
        {
            "id": 1,
            "type": "agent.heartbeat_missed",
            "created_at": "2026-05-07T11:51:00Z",
            "node_id": "desktop-sam",
            "metadata": {"gap_seconds": 540},
        },
        {
            "id": 2,
            "type": "agent.heartbeat_restored",
            "created_at": "2026-05-07T12:00:00Z",
            "node_id": "desktop-sam",
            "metadata": {"gap_seconds": 540},
        },
    ]

    items = prepare_activity_items(events, now=now)

    assert len(items) == 1
    assert items[0]["type"] == "agent.heartbeat_pair"
    assert "briefly dropped offline, then recovered" in items[0]["title"]
    assert items[0]["detail"] == "Recovered after about 9 minutes"
