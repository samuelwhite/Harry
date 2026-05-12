from __future__ import annotations


def _first_telemetry_result(lines: list[str], session_id: str) -> str:
    marker = f"install_validation_start session={session_id}"
    seen_marker = False
    for line in lines:
        if not seen_marker:
            if marker in line:
                seen_marker = True
            continue
        if "ingest_success" in line:
            return "success"
        if "ingest_failure" in line:
            return "failure"
    return "timeout"


def test_stale_old_failure_is_ignored_after_install_marker():
    lines = [
        "[2026-05-12T08:00:00Z] ingest_failure status=500 endpoint=http://brain/ingest",
        "[2026-05-12T08:01:00Z] install_validation_start session=abc brain=http://brain:8789",
        "[2026-05-12T08:01:30Z] ingest_success status=200 endpoint=http://brain/ingest",
    ]

    assert _first_telemetry_result(lines, "abc") == "success"


def test_fresh_success_is_accepted():
    lines = [
        "[2026-05-12T08:01:00Z] install_validation_start session=abc brain=http://brain:8789",
        "[2026-05-12T08:01:30Z] ingest_success status=200 endpoint=http://brain/ingest",
    ]

    assert _first_telemetry_result(lines, "abc") == "success"


def test_fresh_failure_is_reported():
    lines = [
        "[2026-05-12T08:01:00Z] install_validation_start session=abc brain=http://brain:8789",
        "[2026-05-12T08:01:30Z] ingest_failure status=500 endpoint=http://brain/ingest error=boom",
    ]

    assert _first_telemetry_result(lines, "abc") == "failure"


def test_timeout_occurs_when_no_fresh_result_appears():
    lines = [
        "[2026-05-12T08:01:00Z] install_validation_start session=abc brain=http://brain:8789",
        "[2026-05-12T08:02:30Z] service_started",
    ]

    assert _first_telemetry_result(lines, "abc") == "timeout"
