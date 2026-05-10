from __future__ import annotations

import importlib.util
from pathlib import Path


def _load_helper():
    path = Path(__file__).resolve().parents[1] / "scripts" / "brain_discovery.py"
    spec = importlib.util.spec_from_file_location("harry_brain_discovery", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_normalize_brain_url_promotes_bare_ip_to_public_port():
    helper = _load_helper()

    assert helper.normalize_brain_url("192.168.1.100") == "http://192.168.1.100:8789"


def test_normalize_brain_url_preserves_https_domain():
    helper = _load_helper()

    assert helper.normalize_brain_url("https://brain.example") == "https://brain.example"


def test_discover_brain_urls_returns_unique_matches_from_probe_results(monkeypatch):
    helper = _load_helper()
    monkeypatch.setattr(
        helper,
        "build_candidate_urls",
        lambda port=8789: [
            "http://harry.local:8789",
            "http://harry-brain.local:8789",
            "http://192.168.1.10:8789",
            "http://192.168.1.20:8789",
        ],
    )

    def fake_probe(url, timeout=1.2):
        mapping = {
            "http://harry.local:8789": None,
            "http://harry-brain.local:8789": "http://192.168.1.20:8789",
            "http://192.168.1.10:8789": "http://192.168.1.10:8789",
            "http://192.168.1.20:8789": "http://192.168.1.20:8789",
        }
        return mapping[url]

    found = helper.discover_brain_urls(probe_fn=fake_probe, workers=2)

    assert found == ["http://192.168.1.20:8789", "http://192.168.1.10:8789"]


def test_probe_candidate_prefers_canonical_and_recommended_addresses(monkeypatch):
    helper = _load_helper()

    class FakeResponse:
        def __init__(self, payload: dict):
            self._payload = payload

        def read(self):
            import json

            return json.dumps(self._payload).encode("utf-8")

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

    def fake_urlopen(req, timeout=1.2):
        return FakeResponse(
            {
                "service": "harry-brain",
                "ok": True,
                "canonical_base_url": "https://brain.example",
                "recommended_lan_url": "http://192.168.1.20:8789",
                "base_url": "http://192.168.1.20:8789",
            }
        )

    monkeypatch.setattr(helper.urllib.request, "urlopen", fake_urlopen)

    assert helper.probe_candidate("http://192.168.1.20:8789") == "https://brain.example"
