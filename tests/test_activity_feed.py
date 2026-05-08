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
            "node_id": "workstation-1",
            "metadata": {"gap_seconds": 540},
        },
        {
            "id": 2,
            "type": "agent.heartbeat_restored",
            "created_at": "2026-05-07T12:00:00Z",
            "node_id": "workstation-1",
            "metadata": {"gap_seconds": 540},
        },
    ]

    items = prepare_activity_items(events, now=now)

    assert len(items) == 1
    assert items[0]["type"] == "agent.heartbeat_pair"
    assert "briefly dropped offline, then recovered" in items[0]["title"]
    assert items[0]["detail"] == "Recovered after about 9 minutes"


def test_activity_feed_uses_present_tense_only_while_node_is_stale():
    now = datetime(2026, 5, 7, 12, 0, tzinfo=timezone.utc)
    events = [
        {
            "id": 1,
            "type": "agent.heartbeat_missed",
            "created_at": "2026-05-07T11:30:00Z",
            "node_id": "compute-node-1",
            "metadata": {"age_seconds": 3600},
        }
    ]
    current_nodes = {
        "compute-node-1": {
            "ts": "2026-05-07T10:45:00Z",
            "payload": {"agent_status": {"state": "healthy", "ok": True}},
        }
    }

    items = prepare_activity_items(events, now=now, current_nodes=current_nodes)

    assert items[0]["title"] == "compute-node-1 is not checking in right now"
    assert items[0]["detail"] == "No response for about 1 hour"


def test_activity_feed_rewrites_recovered_offline_copy_as_historical():
    now = datetime(2026, 5, 7, 12, 0, tzinfo=timezone.utc)
    events = [
        {
            "id": 1,
            "type": "agent.offline",
            "created_at": "2026-05-07T11:40:00Z",
            "node_id": "media-server-1",
            "message": "media-server-1 reported state error.",
            "metadata": {"state": "error"},
        }
    ]
    current_nodes = {
        "media-server-1": {
            "ts": "2026-05-07T11:59:00Z",
            "payload": {"agent_status": {"state": "healthy", "ok": True}},
        }
    }

    items = prepare_activity_items(events, now=now, current_nodes=current_nodes)

    assert items[0]["title"] == "media-server-1 reported trouble earlier"
    assert items[0]["detail"] == "media-server-1 reported state error."


def test_activity_feed_suppresses_old_missed_event_after_recovery():
    now = datetime(2026, 5, 7, 12, 0, tzinfo=timezone.utc)
    events = [
        {
            "id": 1,
            "type": "agent.heartbeat_restored",
            "created_at": "2026-05-07T11:55:00Z",
            "node_id": "compute-node-1",
            "metadata": {"gap_seconds": 900},
        },
        {
            "id": 2,
            "type": "agent.heartbeat_missed",
            "created_at": "2026-05-07T10:30:00Z",
            "node_id": "compute-node-1",
            "metadata": {"age_seconds": 900},
        },
    ]
    current_nodes = {
        "compute-node-1": {
            "ts": "2026-05-07T11:59:00Z",
            "payload": {"agent_status": {"state": "healthy", "ok": True}},
        }
    }

    items = prepare_activity_items(events, now=now, current_nodes=current_nodes)

    assert len(items) == 1
    assert items[0]["type"] == "agent.heartbeat_restored"


def test_activity_feed_uses_unknown_recovery_copy_when_duration_missing():
    now = datetime(2026, 5, 7, 12, 0, tzinfo=timezone.utc)
    events = [
        {
            "id": 1,
            "type": "agent.heartbeat_restored",
            "created_at": "2026-05-07T11:59:00Z",
            "node_id": "compute-node-1",
            "metadata": {},
        }
    ]

    items = prepare_activity_items(events, now=now)

    assert items[0]["detail"] == "Recovered; duration unknown."


def test_activity_feed_never_says_recovered_after_just_now():
    now = datetime(2026, 5, 7, 12, 0, tzinfo=timezone.utc)
    events = [
        {
            "id": 1,
            "type": "agent.heartbeat_restored",
            "created_at": "2026-05-07T12:00:00Z",
            "node_id": "compute-node-1",
            "metadata": {"gap_seconds": 10},
        }
    ]

    items = prepare_activity_items(events, now=now)

    assert items[0]["detail"] == "Recovered after a short gap"
    assert "just now" not in items[0]["detail"]
