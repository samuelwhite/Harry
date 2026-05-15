from __future__ import annotations

from types import SimpleNamespace

import app.brain_address as brain_address


def test_recommended_lan_ip_is_disabled_in_container_without_explicit_config(monkeypatch):
    monkeypatch.delenv("HARRY_BRAIN_LAN_IP", raising=False)
    monkeypatch.delenv("HARRY_PUBLIC_BASE_URL", raising=False)
    monkeypatch.setattr(brain_address, "runtime_is_container", lambda: True)
    monkeypatch.setattr(brain_address, "detect_lan_ip", lambda: "192.168.1.55")

    assert brain_address.recommended_lan_ip() is None
    assert brain_address.recommended_lan_url() is None


def test_detect_lan_ip_rejects_docker_bridge_candidates(monkeypatch):
    monkeypatch.setattr(
        brain_address,
        "_gather_lan_candidates",
        lambda: ["192.168.240.2", "172.17.0.2", "169.254.1.5"],
    )

    assert brain_address.detect_lan_ip() is None


def test_resolve_brain_address_refuses_container_guessing(monkeypatch):
    monkeypatch.delenv("HARRY_PUBLIC_BASE_URL", raising=False)
    monkeypatch.delenv("HARRY_BRAIN_LAN_IP", raising=False)
    monkeypatch.setattr(brain_address, "runtime_is_container", lambda: True)
    monkeypatch.setattr(brain_address, "detect_lan_ip", lambda: "192.168.1.55")
    monkeypatch.setattr(brain_address, "_gather_lan_candidates", lambda: ["192.168.1.55", "192.168.240.2"])

    info = brain_address.resolve_brain_address(None)

    assert info["canonical_base_url"] is None
    assert info["recommended_lan_url"] is None
    assert info["display_url"] is None
    assert info["container_runtime"] is True
    assert info["warning"] == (
        "Harry could not determine a reliable LAN address automatically. "
        "Set HARRY_PUBLIC_BASE_URL or HARRY_BRAIN_LAN_IP to make the Brain address canonical for other machines."
    )


def test_resolve_brain_address_reports_rejected_candidates(monkeypatch):
    monkeypatch.delenv("HARRY_PUBLIC_BASE_URL", raising=False)
    monkeypatch.delenv("HARRY_BRAIN_LAN_IP", raising=False)
    monkeypatch.setattr(brain_address, "runtime_is_container", lambda: False)
    monkeypatch.setattr(brain_address, "_gather_lan_candidates", lambda: ["192.168.240.2", "192.168.1.55"])
    monkeypatch.setattr(brain_address, "detect_lan_ip", lambda: "192.168.1.55")

    info = brain_address.resolve_brain_address(None)

    assert info["display_url"] == "http://192.168.1.55:8789"
    assert info["rejected_lan_candidates"] == ["192.168.240.2"]


def test_resolve_brain_address_prefers_forwarded_proxy_headers(monkeypatch):
    monkeypatch.delenv("HARRY_PUBLIC_BASE_URL", raising=False)
    monkeypatch.delenv("HARRY_BRAIN_LAN_IP", raising=False)
    monkeypatch.setattr(brain_address, "runtime_is_container", lambda: False)
    monkeypatch.setattr(brain_address, "detect_lan_ip", lambda: "192.168.1.55")

    request = SimpleNamespace(
        headers={
            "host": "127.0.0.1:8789",
            "x-forwarded-host": "brain.example",
            "x-forwarded-proto": "https",
        },
        url=SimpleNamespace(hostname="127.0.0.1", port=8789, scheme="http"),
    )

    info = brain_address.resolve_brain_address(request)

    assert info["display_url"] == "https://brain.example"
    assert info["source"] == "request-forwarded"
    assert info["request_forwarded_candidate"] == "https://brain.example"


def test_resolve_brain_address_accepts_lan_ip_candidate(monkeypatch):
    monkeypatch.delenv("HARRY_PUBLIC_BASE_URL", raising=False)
    monkeypatch.delenv("HARRY_BRAIN_LAN_IP", raising=False)
    monkeypatch.setattr(brain_address, "runtime_is_container", lambda: False)
    monkeypatch.setattr(brain_address, "detect_lan_ip", lambda: "192.168.1.55")

    request = SimpleNamespace(
        headers={"host": "127.0.0.1:8789"},
        url=SimpleNamespace(hostname="127.0.0.1", port=8789, scheme="http"),
    )

    info = brain_address.resolve_brain_address(request)

    assert info["display_url"] == "http://192.168.1.55:8789"
    assert info["source"] == "lan-detected"


def test_discovery_methods_enabled_reflects_container_mode(monkeypatch):
    monkeypatch.setattr(brain_address, "runtime_is_container", lambda: True)
    assert brain_address.discovery_methods_enabled() == [
        "HARRY_PUBLIC_BASE_URL",
        "HARRY_BRAIN_LAN_IP",
        "manual address entry",
    ]
