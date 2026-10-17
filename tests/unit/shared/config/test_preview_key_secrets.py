"""Tests for reading the existing encryption key without provider credentials."""

from __future__ import annotations

import dataclasses
from typing import Any

import pytest


@pytest.fixture(autouse=True)
def isolated_secret_state(monkeypatch: Any) -> None:
    """Keep the shared secret loader and its cache local to each test."""

    import shared.config.secrets as secrets_module

    secrets_module.clear_secrets_cache()
    previous_loader = secrets_module._database_secrets_loader
    monkeypatch.setattr(secrets_module, "_database_secrets_loader", None)
    yield
    secrets_module.clear_secrets_cache()
    secrets_module._database_secrets_loader = previous_loader


def test_optional_mode_reads_encryption_key_without_provider_loader(
    monkeypatch: Any,
) -> None:
    """Preview key reads must work without Tushare or a DB secret lookup."""

    from shared.config.secrets import get_secrets, register_database_secrets_loader

    def unexpected_database_read() -> None:
        raise AssertionError("optional preview-key mode must not call the provider loader")

    register_database_secrets_loader(unexpected_database_read)
    monkeypatch.delenv("TUSHARE_TOKEN", raising=False)
    monkeypatch.setenv("AGOMTRADEPRO_ENCRYPTION_KEY", "test-preview-key")

    secrets = get_secrets(require_tushare_token=False)

    assert secrets.data_sources.tushare_token == ""
    assert secrets.field_encryption_key == "test-preview-key"


def test_database_provider_secrets_keep_existing_precedence_and_merge_key(
    monkeypatch: Any,
) -> None:
    """Default reads still prefer database data sources and retain the env key."""

    from shared.config.secrets import get_secrets, register_database_secrets_loader
    from shared.domain.interfaces import DataSourceSecretsDTO

    register_database_secrets_loader(
        lambda: DataSourceSecretsDTO(
            tushare_token="database-provider-token",
            fred_api_key="database-fred-key",
        )
    )
    monkeypatch.setenv("TUSHARE_TOKEN", "environment-provider-token")
    monkeypatch.setenv("AGOMTRADEPRO_ENCRYPTION_KEY", "test-preview-key")

    secrets = get_secrets()

    assert secrets.data_sources.tushare_token == "database-provider-token"
    assert secrets.data_sources.fred_api_key == "database-fred-key"
    assert secrets.field_encryption_key == "test-preview-key"


def test_default_mode_retains_missing_tushare_error(monkeypatch: Any) -> None:
    """Existing callers still receive the historical missing-provider error."""

    from shared.config.secrets import get_secrets

    monkeypatch.delenv("TUSHARE_TOKEN", raising=False)
    monkeypatch.setenv("AGOMTRADEPRO_ENCRYPTION_KEY", "test-preview-key")

    with pytest.raises(OSError, match="Tushare Token"):
        get_secrets()


def test_optional_app_secret_is_compatible_immutable_and_hidden_from_repr() -> None:
    """The optional key must not change dataclass equality or expose its value."""

    from shared.config.secrets import AppSecrets, DataSourceSecrets

    data_sources = DataSourceSecrets(tushare_token="provider-token", fred_api_key="")
    with_key = AppSecrets(data_sources=data_sources, field_encryption_key="do-not-print")
    without_key = AppSecrets(data_sources=data_sources)

    assert with_key == without_key
    assert "do-not-print" not in repr(with_key)
    with pytest.raises(dataclasses.FrozenInstanceError):
        with_key.field_encryption_key = "changed"


@pytest.mark.parametrize("invalid_flag", [0, 1, None, "false"])
def test_require_tushare_flag_must_be_exact_bool(invalid_flag: object) -> None:
    """The optional loader mode must reject values that merely coerce to bool."""

    from shared.config.secrets import get_secrets

    with pytest.raises(TypeError, match="require_tushare_token"):
        get_secrets(require_tushare_token=invalid_flag)  # type: ignore[arg-type]


@pytest.mark.parametrize(("warm_flag", "invalid_flag"), [(False, 0), (True, 1)])
def test_exact_bool_validation_survives_warm_cache_keys(
    monkeypatch: Any,
    warm_flag: bool,
    invalid_flag: object,
) -> None:
    """Warm bool cache entries must not make equal-valued integers valid flags."""

    from shared.config.secrets import get_secrets

    monkeypatch.setenv("TUSHARE_TOKEN", "synthetic-provider-token")
    warmed = get_secrets(require_tushare_token=warm_flag)
    assert warmed.data_sources.tushare_token == "synthetic-provider-token"

    with pytest.raises(TypeError, match="require_tushare_token"):
        get_secrets(require_tushare_token=invalid_flag)  # type: ignore[arg-type]


def test_cache_holds_both_modes_and_clear_refreshes_optional_key(
    monkeypatch: Any,
) -> None:
    """Both modes cache independently, and the public clear resets all entries."""

    from shared.config.secrets import clear_secrets_cache, get_secrets

    monkeypatch.setenv("TUSHARE_TOKEN", "environment-provider-token")
    monkeypatch.setenv("AGOMTRADEPRO_ENCRYPTION_KEY", "preview-key-one")

    optional = get_secrets(require_tushare_token=False)
    default = get_secrets()

    assert optional.field_encryption_key == "preview-key-one"
    assert default.field_encryption_key == "preview-key-one"
    assert get_secrets.cache_info().currsize == 2

    monkeypatch.setenv("AGOMTRADEPRO_ENCRYPTION_KEY", "preview-key-two")
    assert get_secrets(require_tushare_token=False).field_encryption_key == "preview-key-one"

    clear_secrets_cache()
    assert get_secrets.cache_info().currsize == 0
    assert get_secrets(require_tushare_token=False).field_encryption_key == "preview-key-two"
