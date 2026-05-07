from __future__ import annotations

from pathlib import Path

import pytest
from fastapi import HTTPException

import app.main as main
import importlib

router = importlib.import_module("app.ui.router")


def test_validate_dist_agent_rejects_tabs(tmp_path):
    script = tmp_path / "harry_agent.sh"
    script.write_text("#!/usr/bin/env bash\n\techo hi\n", encoding="utf-8")

    ok, error = main._validate_dist_agent(script)

    assert ok is False
    assert error == "contains_tab_characters"


def test_validate_dist_agent_skips_bash_on_windows(monkeypatch, tmp_path):
    script = tmp_path / "harry_agent.sh"
    script.write_text("#!/usr/bin/env bash\necho hi\n", encoding="utf-8")

    monkeypatch.setattr(main.sys, "platform", "win32", raising=False)
    monkeypatch.setattr(
        main.subprocess,
        "run",
        lambda *args, **kwargs: pytest.fail("bash validation should be skipped on Windows"),
    )

    ok, error = main._validate_dist_agent(script)

    assert ok is True
    assert error is None


def test_download_file_rejects_path_traversal(monkeypatch, tmp_path):
    downloads = tmp_path / "downloads"
    downloads.mkdir()
    (downloads / "harry.txt").write_text("ok", encoding="utf-8")

    monkeypatch.setattr(router, "_downloads_dir", lambda: downloads)

    response = router.download_file("harry.txt")
    assert Path(response.path) == downloads / "harry.txt"

    with pytest.raises(HTTPException) as excinfo:
        router.download_file("../outside.txt")

    assert excinfo.value.status_code == 404


def test_node_summary_strips_platform_suffix_from_agent_version():
    payload = {
        "node": "node-1",
        "ts": "2026-05-07T12:00:00Z",
        "agent_version": "0.2.3-windows-dev",
        "facts": {},
        "metrics": {"disk_used": [], "temps_c": {}, "gpu": [], "extensions": {}},
        "derived": {"health": {"state": "unknown", "worst_severity": "unknown", "reasons": []}, "extensions": {}},
        "advice": [],
    }

    summary = main._node_summary(payload, ctx={})

    assert summary["agent_version"] == "0.2.3"
