"""Canonical-only Alpha, market, and account summary contracts."""

from __future__ import annotations

import inspect

from apps.config_center.infrastructure import config_summary_repository as summary_module
from apps.config_center.infrastructure.config_summary_repository import (
    DjangoConfigCenterSummaryRepository,
)


def test_config_summary_has_no_legacy_system_settings_dependency() -> None:
    """Summary reads must remain valid after the legacy singleton is deleted."""

    assert "SystemSettingsModel" not in inspect.getsource(summary_module)


def test_config_summary_missing_canonical_groups_returns_safe_empty_values(monkeypatch) -> None:
    """Missing canonical groups never reheat persisted legacy configuration."""

    monkeypatch.setattr(summary_module, "get_active_alpha_runtime_config", lambda _env: None)
    monkeypatch.setattr(summary_module, "get_active_market_runtime_config", lambda _env: None)
    monkeypatch.setattr(summary_module, "get_active_account_runtime_config", lambda _env: None)
    repository = DjangoConfigCenterSummaryRepository()
    monkeypatch.setattr(
        repository,
        "get_runtime_qlib_config",
        lambda: {"enabled": False, "is_configured": False},
    )

    assert repository.get_runtime_alpha_fixed_provider() == ""
    assert repository.get_runtime_alpha_pool_mode("strict_valuation") == "strict_valuation"
    assert repository.get_runtime_benchmark_code("equity", "fallback") == "fallback"
    assert repository.get_runtime_asset_proxy_map() == {}
    assert repository.get_system_settings_summary()["status"] == "blocked"


def test_config_summary_reads_alpha_and_market_groups_independently(monkeypatch) -> None:
    """One incomplete group must not hide a complete canonical sibling group."""

    monkeypatch.setattr(
        summary_module,
        "get_active_alpha_runtime_config",
        lambda _env: {
            "alpha_fixed_provider": "qlib",
            "alpha_pool_mode": "market",
        },
    )
    monkeypatch.setattr(summary_module, "get_active_market_runtime_config", lambda _env: None)
    repository = DjangoConfigCenterSummaryRepository()

    assert repository.get_runtime_alpha_fixed_provider() == "qlib"
    assert repository.get_runtime_alpha_pool_mode("strict_valuation") == "market"
    assert repository.get_runtime_benchmark_code("equity", "fallback") == "fallback"
