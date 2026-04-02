"""Unit tests for environment-based configuration loading."""

from __future__ import annotations

from ..config import SystemConfig, get_config


def test_system_config_from_env(monkeypatch) -> None:
    monkeypatch.setenv("MAX_WORKERS", "9")
    monkeypatch.setenv("POLL_INTERVAL", "3")
    monkeypatch.setenv("HEALTH_ENABLED", "false")
    monkeypatch.setenv("HEALTH_PORT", "8899")
    monkeypatch.setenv("BACKEND_URL", "http://example.local")
    monkeypatch.setenv("INTERNAL_API_KEY", "ik")
    monkeypatch.setenv("AGENT_GENESIS_API_KEY", "uk")
    monkeypatch.setenv("REQUEST_TIMEOUT", "55")

    cfg = SystemConfig.from_env()
    assert cfg.max_workers == 9
    assert cfg.poll_interval == 3
    assert cfg.health_enabled is False
    assert cfg.health_port == 8899
    assert cfg.backend_url == "http://example.local"
    assert cfg.internal_api_key == "ik"
    assert cfg.user_api_key == "uk"
    assert cfg.request_timeout == 55


def test_singleton_reset_and_override() -> None:
    SystemConfig.reset()
    c1 = get_config()
    c2 = get_config()
    assert c1 is c2

    c3 = SystemConfig.override(max_workers=123)
    assert c3.max_workers == 123
    assert get_config().max_workers == 123

    SystemConfig.reset()
