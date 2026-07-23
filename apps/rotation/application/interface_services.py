"""Application-facing orchestration helpers for rotation interface views."""

from __future__ import annotations

from datetime import date
from typing import Any, Protocol, cast

from apps.rotation.application.dtos import (
    AssetsViewRequest,
    RotationConfigsViewRequest,
    RotationSignalsViewRequest,
)
from apps.rotation.application.repository_provider import (
    RotationIntegrationService as _RotationIntegrationService,
)
from apps.rotation.application.repository_provider import (
    get_rotation_integration_service,
    get_rotation_interface_repository,
)
from apps.rotation.application.use_cases import (
    GetAssetsForViewUseCase,
    GetRotationConfigsForViewUseCase,
    GetRotationSignalsForViewUseCase,
    RotationViewRepository,
    RotationViewService,
)
from core.integration.trading_account_registry import (
    list_active_accounts_for_user as list_active_account_models_for_user,
)

# Backward-compatible patch/import surface used by API tests and external callers.
RotationIntegrationService = _RotationIntegrationService


class RotationInterfaceBoundary(RotationViewRepository, Protocol):
    """Repository operations exposed to rotation interfaces."""

    def asset_queryset(self) -> Any: ...

    def active_asset_queryset(self) -> Any: ...

    def config_queryset(self) -> Any: ...

    def signal_queryset(self) -> Any: ...

    def active_template_queryset(self) -> Any: ...

    def portfolio_config_queryset_for_user(self, user: Any) -> Any: ...

    def get_portfolio_config_for_account(
        self,
        account_id: int | str,
        user: Any,
    ) -> Any | None: ...

    def apply_template_to_portfolio_config(
        self,
        config: Any,
        template_key: str,
    ) -> Any | None: ...

    def import_default_assets(self) -> dict[str, int]: ...

    def preview_default_asset_import(self) -> dict[str, Any]: ...

    def export_asset_rows(
        self,
    ) -> tuple[list[str], list[dict[str, Any]]]: ...

    def get_latest_signal_models_for_active_configs(self) -> list[Any]: ...

    def get_asset_category_choices(self) -> list[tuple[str, str]]: ...

    def get_risk_tolerance_choices(self) -> list[tuple[str, str]]: ...


class RotationIntegrationBoundary(RotationViewService, Protocol):
    """Integration operations exposed to rotation interfaces."""

    def get_all_assets(self) -> list[dict[str, Any]]: ...

    def get_asset_info(self, asset_code: str) -> dict[str, Any] | None: ...

    def generate_rotation_signal(
        self,
        config_name: str,
        signal_date: date | None = None,
    ) -> dict[str, Any] | None: ...

    def get_rotation_recommendation(
        self,
        strategy_type: str = "momentum",
    ) -> dict[str, Any]: ...

    def compare_assets(
        self,
        asset_codes: list[str],
        lookback_days: int = 60,
    ) -> dict[str, Any]: ...

    def get_correlation_matrix(
        self,
        asset_codes: list[str],
        window_days: int = 60,
    ) -> dict[str, Any]: ...

    def clear_price_cache(self) -> None: ...


def _query_repo() -> RotationInterfaceBoundary:
    """Return the default query repository for interface services."""
    return cast(RotationInterfaceBoundary, get_rotation_interface_repository())


def _integration_service() -> RotationIntegrationBoundary:
    """Return the default rotation integration service."""
    return cast(RotationIntegrationBoundary, get_rotation_integration_service())


def get_asset_queryset() -> Any:
    """Return the asset queryset used by DRF viewsets."""
    return _query_repo().asset_queryset()


def get_rotation_config_queryset() -> Any:
    """Return the rotation config queryset used by DRF viewsets."""
    return _query_repo().config_queryset()


def get_rotation_signal_queryset() -> Any:
    """Return the rotation signal queryset used by DRF viewsets."""
    return _query_repo().signal_queryset()


def get_active_template_queryset() -> Any:
    """Return active rotation template presets."""
    return _query_repo().active_template_queryset()


def get_portfolio_rotation_config_queryset(user: Any) -> Any:
    """Return account-level rotation configs visible to a user."""
    return _query_repo().portfolio_config_queryset_for_user(user)


def get_portfolio_rotation_config_by_account(
    account_id: int | str | None,
    user: Any,
) -> Any | None:
    """Return one account-level rotation config visible to a user."""
    if account_id is None:
        return None
    return _query_repo().get_portfolio_config_for_account(account_id, user)


def apply_template_to_portfolio_config(config: Any, template_key: str) -> Any:
    """Apply an active template preset to a portfolio rotation config."""
    return _query_repo().apply_template_to_portfolio_config(config, template_key)


def import_default_assets() -> dict[str, int]:
    """Import or reactivate default rotation assets."""
    return _query_repo().import_default_assets()


def preview_default_asset_import() -> dict[str, Any]:
    """Return a read-only plan for importing default rotation assets."""
    return _query_repo().preview_default_asset_import()


def export_asset_rows() -> tuple[list[str], list[dict[str, Any]]]:
    """Return exportable asset fields and rows."""
    return _query_repo().export_asset_rows()


def get_all_assets_with_prices() -> list[dict[str, Any]]:
    """Return active assets with price metadata."""
    return _integration_service().get_all_assets()


def get_asset_info(asset_code: str) -> dict[str, Any] | None:
    """Return one asset detail payload."""
    return _integration_service().get_asset_info(asset_code)


def generate_rotation_signal(
    config_name: str,
    signal_date: date | None = None,
) -> dict[str, Any] | None:
    """Generate a rotation signal for the named config."""
    return _integration_service().generate_rotation_signal(config_name, signal_date)


def get_rotation_recommendation(strategy_type: str = "momentum") -> dict[str, Any]:
    """Return a rotation recommendation payload."""
    return _integration_service().get_rotation_recommendation(strategy_type)


def compare_assets(
    asset_codes: list[str],
    lookback_days: int = 60,
) -> dict[str, Any]:
    """Compare multiple rotation assets."""
    return _integration_service().compare_assets(asset_codes, lookback_days)


def get_correlation_matrix(
    asset_codes: list[str],
    window_days: int = 60,
) -> dict[str, Any]:
    """Return the correlation matrix for selected assets."""
    return _integration_service().get_correlation_matrix(asset_codes, window_days)


def clear_price_cache() -> None:
    """Clear cached rotation price data."""
    _integration_service().clear_price_cache()


def get_latest_signal_models_for_active_configs() -> list[Any]:
    """Return latest signal models for active configs."""
    return _query_repo().get_latest_signal_models_for_active_configs()


def _user_accounts_for_context(user: Any) -> list[Any]:
    """Return active account rows for authenticated users."""
    if not getattr(user, "is_authenticated", False):
        return []
    if user.id is None:
        return []
    return list(list_active_account_models_for_user(user.id))


def build_rotation_assets_context() -> dict[str, Any]:
    """Build the rotation assets HTML context."""
    repo = _query_repo()
    service = _integration_service()
    response = GetAssetsForViewUseCase(service, view_repo=repo).execute(AssetsViewRequest())

    momentum_scores = {
        asset_code: {
            "composite_score": score.composite_score,
            "rank": score.rank,
            "momentum_1m": score.momentum_1m,
            "momentum_3m": score.momentum_3m,
            "momentum_6m": score.momentum_6m,
            "trend_strength": score.trend_strength,
            "calc_date": score.calc_date,
        }
        for asset_code, score in response.momentum_scores.items()
    }

    return {
        "assets": response.assets,
        "categories": response.categories,
        "momentum_scores": momentum_scores,
        "latest_calc_date": response.latest_calc_date,
        "maintenance_notice": response.maintenance_notice,
        "current_date": date.today(),
        "asset_category_choices": repo.get_asset_category_choices(),
    }


def build_rotation_configs_context(user: Any) -> dict[str, Any]:
    """Build the rotation configs HTML context."""
    repo = _query_repo()
    service = _integration_service()
    response = GetRotationConfigsForViewUseCase(
        service,
        view_repo=repo,
    ).execute(RotationConfigsViewRequest())

    latest_signals = {
        config_id: {
            "signal_date": signal.signal_date,
            "current_regime": signal.current_regime,
            "action_required": signal.action_required,
            "target_allocation": signal.target_allocation,
        }
        for config_id, signal in response.latest_signals.items()
    }

    for config in response.configs:
        config["latest_signal"] = latest_signals.get(config["id"])

    return {
        "configs": response.configs,
        "latest_signals": latest_signals,
        "strategy_types": response.strategy_types,
        "frequencies": response.frequencies,
        "current_date": date.today(),
        "user_accounts": _user_accounts_for_context(user),
        "assets": repo.active_asset_queryset(),
    }


def build_rotation_signals_context(filters: dict[str, str]) -> dict[str, Any]:
    """Build the rotation signals HTML context."""
    repo = _query_repo()
    service = _integration_service()
    request = RotationSignalsViewRequest(
        config_filter=filters.get("config", ""),
        regime_filter=filters.get("regime", ""),
        action_filter=filters.get("action", ""),
    )
    response = GetRotationSignalsForViewUseCase(
        service,
        view_repo=repo,
    ).execute(request)

    return {
        "signals": response.signals,
        "configs": response.configs,
        "latest_by_config": response.latest_by_config,
        "current_regime": response.current_regime,
        "filter_config": response.filter_config,
        "filter_regime": response.filter_regime,
        "filter_action": response.filter_action,
        "regime_choices": response.regime_choices,
        "action_choices": response.action_choices,
        "current_date": date.today(),
    }


def build_rotation_account_config_context(user: Any) -> dict[str, Any]:
    """Build the account rotation config HTML context."""
    repo = _query_repo()
    return {
        "user_accounts": _user_accounts_for_context(user),
        "assets": repo.active_asset_queryset(),
        "templates": repo.active_template_queryset(),
        "current_date": date.today(),
        "risk_tolerance_choices": repo.get_risk_tolerance_choices(),
    }
