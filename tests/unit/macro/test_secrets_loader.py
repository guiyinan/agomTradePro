"""Tests for database-backed data-source secret loading."""

from types import SimpleNamespace
from typing import Any

from apps.macro.infrastructure import secrets_loader


def test_load_tushare_unified_relay_mode(monkeypatch: Any) -> None:
    """Tushare transport mode must flow from provider extras to shared secrets."""

    providers = [
        SimpleNamespace(
            source_type="tushare",
            api_key="relay-secret",
            http_url="https://relay.example.test/tushare/pro",
            extra_config={"tushare_request_mode": "unified_relay"},
        )
    ]
    monkeypatch.setattr(
        secrets_loader,
        "list_active_provider_configs",
        lambda: providers,
    )

    result = secrets_loader.load_secrets_from_database()

    assert result is not None
    assert result.tushare_token == "relay-secret"
    assert result.tushare_http_url == "https://relay.example.test/tushare/pro"
    assert result.tushare_request_mode == "unified_relay"
