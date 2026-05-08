from __future__ import annotations

import json
from pathlib import Path

from app import machine_summary as ms


def _payload():
    return {
        "schema_version": "0.2.3",
        "node": "node-1",
        "ts": "2026-05-07T12:00:00Z",
        "capabilities": {"gpu": True},
        "facts": {"model": "ThinkStation", "cpu": "Ryzen", "gpus": [{"name": "GPU0"}]},
        "metrics": {
            "cpu_load_1m": 0.2,
            "mem_used_pct": 42.0,
            "disk_used": [{"mount": "C:\\", "used_pct": 61.0}],
            "temps_c": {},
            "gpu": [{"name": "GPU0"}],
            "extensions": {},
        },
        "derived": {"health": {"state": "healthy", "worst_severity": "unknown", "reasons": []}, "extensions": {}},
        "advice": [],
    }


def test_machine_summary_disabled_by_default(monkeypatch):
    payload = _payload()
    monkeypatch.delenv("HARRY_ENABLE_LLM_SUMMARIES", raising=False)
    monkeypatch.setattr(ms, "_call_local_llm", lambda prompt: (_ for _ in ()).throw(AssertionError("should not call LLM")))

    assert ms.get_machine_summary(payload) is None


def test_machine_summary_returns_cached_summary(monkeypatch, tmp_path):
    payload = _payload()
    monkeypatch.setenv("HARRY_ENABLE_LLM_SUMMARIES", "1")
    monkeypatch.setattr(ms, "DATA_DIR", tmp_path)
    monkeypatch.setattr(ms, "SUMMARY_CACHE_DIR", tmp_path / "machine_summaries")
    cache = {
        "node": "node-1",
        "fingerprint": ms._summary_fingerprint(payload),
        "generated_at": ms._iso_now(),
        "source": "cache",
        "summary": "Cached summary.",
    }
    Path(ms._cache_path("node-1")).parent.mkdir(parents=True, exist_ok=True)
    Path(ms._cache_path("node-1")).write_text(json.dumps(cache), encoding="utf-8")

    result = ms.get_machine_summary(payload)

    assert result["summary"] == "Cached summary."
    assert result["source"] == "cache"


def test_machine_summary_falls_back_when_llm_fails(monkeypatch, tmp_path):
    payload = _payload()
    monkeypatch.setenv("HARRY_ENABLE_LLM_SUMMARIES", "1")
    monkeypatch.setenv("HARRY_LLM_BASE_URL", "http://127.0.0.1:11434")
    monkeypatch.setattr(ms, "DATA_DIR", tmp_path)
    monkeypatch.setattr(ms, "SUMMARY_CACHE_DIR", tmp_path / "machine_summaries")
    monkeypatch.setattr(ms, "_call_local_llm", lambda prompt: (_ for _ in ()).throw(RuntimeError("boom")))

    result = ms.build_machine_summary(payload)

    assert result["source"] == "local"
    assert "Everything looks calm." in result["summary"]
    assert Path(ms._cache_path("node-1")).exists()
