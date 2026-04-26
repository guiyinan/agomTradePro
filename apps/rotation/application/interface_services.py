"""Application-facing orchestration helpers for rotation interface views."""

from __future__ import annotations

from datetime import date
from typing import Any

from apps.rotation.application.dtos import (
    AssetsViewRequest,
    RotationConfigsViewRequest,
    RotationSignalsViewRequest,
)
from apps.rotation.application.repository_provider import (
    RotationIntegrationService,
    RotationInterfaceRepository,
    get_rotation_integration_service,
    get_rotation_interface_repository,
)
from apps.rotation.application.use_cases import (
    GetAssetsForViewUseCase,
    GetRotationConfigsForViewUseCase,
    GetRotationSignalsForViewUseCase,
)
from core.integration.rotation_accounts import list_rotation_user_accounts


def _query_repo() -> RotationInterfaceRepository:
    """Return the default query repository for interface services."""
    return get_rotation_interface_repository()


def _integration_service() -> RotationIntegrationService:
    """Return the default rotation integration service."""
    return get_rotation_integration_service()


def get_asset_queryset():
    """Return the asset queryset used by DRF viewsets."""
    return _query_repo().asset_queryset()


def get_rotation_config_queryset():
    """Return the rotation config queryset used by DRF viewsets."""
    return _query_repo().config_queryset()


def get_rotation_signal_queryset():
    """Return the rotation signal queryset used by DRF viewsets."""
    return _query_repo().signal_queryset()


def get_active_template_queryset():
    """Return active rotation template presets."""
    return _query_repo().active_template_queryset()


def get_portfolio_rotation_config_queryset(user):
    """Return account-level rotation configs visible to a user."""
    return _query_repo().portfolio_config_queryset_for_user(user)


def get_portfolio_rotation_config_by_account(account_id: int | str, user):
    """Return one account-level rotation config visible to a user."""
    return _query_repo().get_portfolio_config_for_account(account_id, user)


def apply_template_to_portfolio_config(config, template_key: str):
    """Apply an active template preset to a portfolio rotation config."""
    return _query_repo().apply_template_to_portfolio_config(config, template_key)


def import_default_assets() -> dict[str, int]:
    """Import or reactivate default rotation assets."""
    return _query_repo().import_default_assets()


def export_asset_rows() -> tuple[list[str], list[dict]]:
    """Return exportable asset fields and rows."""
    return _query_repo().export_asset_rows()


def get_all_assets_with_prices() -> list[dict]:
    """Return active assets with price metadata."""
    return _integration_service().get_all_assets()


def get_asset_info(asset_code: str) -> dict | None:
    """Return one asset detail payload."""
    return _integration_service().get_asset_info(asset_code)


def generate_rotation_signal(config_name: str, signal_date=None) -> dict | None:
    """Generate a rotation signal for the named config."""
    return _integration_service().generate_rotation_signal(config_name, signal_date)


def get_rotation_recommendation(strategy_type: str = "momentum") -> dict:
    """Return a rotation recommendation payload."""
    return _integration_service().get_rotation_recommendation(strategy_type)


def compare_assets(asset_codes: list[str], lookback_days: int = 60) -> dict:
    """Compare multiple rotation assets."""
    return _integration_service().compare_assets(asset_codes, lookback_days)


def get_correlation_matrix(asset_codes: list[str], window_days: int = 60) -> dict:
    """Return the correlation matrix for selected assets."""
    return _integration_service().get_correlation_matrix(asset_codes, window_days)


def clear_price_cache() -> None:
    """Clear cached rotation price data."""
    _integration_service().clear_price_cache()


def get_latest_signal_models_for_active_configs() -> list:
    """Return latest signal models for active configs."""
    return _query_repo().get_latest_signal_models_for_active_configs()


def _user_accounts_for_context(user) -> list:
    """Return active account rows for authenticated users."""
    if not getattr(user, "is_authenticated", False):
        return []
    return list_rotation_user_accounts(user.id)


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


def build_rotation_configs_context(user) -> dict[str, Any]:
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


def build_rotation_account_config_context(user) -> dict[str, Any]:
    """Build the account rotation config HTML context."""
    repo = _query_repo()
    return {
        "user_accounts": _user_accounts_for_context(user),
        "assets": repo.active_asset_queryset(),
        "templates": repo.active_template_queryset(),
        "current_date": date.today(),
        "risk_tolerance_choices": repo.get_risk_tolerance_choices(),
    }
