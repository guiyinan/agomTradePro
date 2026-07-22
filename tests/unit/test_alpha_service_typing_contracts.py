"""Regression coverage for Alpha service boundary contracts."""

from types import SimpleNamespace

from apps.alpha.application import services


def test_runtime_qlib_config_delegates_to_the_integration_bridge(monkeypatch) -> None:
    expected = {"enabled": True, "provider_uri": "test-provider"}
    monkeypatch.setattr(
        services,
        "load_runtime_qlib_config",
        lambda: expected,
    )

    assert services._get_runtime_qlib_config() == expected


def test_fallback_alert_update_uses_an_aware_timestamp(monkeypatch) -> None:
    updates: list[dict[str, object]] = []
    repository = SimpleNamespace(
        get_open_alert=lambda **kwargs: SimpleNamespace(id=7),
        update_alert=lambda **kwargs: updates.append(kwargs),
    )
    monkeypatch.setattr(
        services,
        "get_alpha_alert_repository",
        lambda: repository,
    )

    services.AlphaProviderRegistry()._create_fallback_alert(
        "cache",
        ["qlib", "cache"],
        "Qlib unavailable",
    )

    assert len(updates) == 1
    metadata = updates[0]["metadata"]
    assert isinstance(metadata, dict)
    assert metadata["current_provider"] == "cache"
    assert "+" in str(metadata["alert_updated_at"])
