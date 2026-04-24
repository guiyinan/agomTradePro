"""Application-facing helpers for equity interface views."""

from __future__ import annotations

from typing import Any

from django.db.utils import OperationalError, ProgrammingError

from apps.equity.application.config import clear_config_cache, get_valuation_repair_config
from apps.equity.application.repository_provider import (
    get_equity_bootstrap_config_repository,
    get_equity_valuation_repair_config_repository,
)
from apps.equity.domain.entities_valuation_repair import DEFAULT_VALUATION_REPAIR_CONFIG


def list_valuation_repair_configs() -> list[Any]:
    """Return all persisted valuation repair configs."""

    return get_equity_valuation_repair_config_repository().list_models()


def get_valuation_repair_config_by_id(*, config_id: int) -> Any | None:
    """Return one valuation repair config model by id."""

    return get_equity_valuation_repair_config_repository().get_by_id(config_id)


def create_valuation_repair_config(*, data: dict[str, Any], created_by: str) -> Any:
    """Create one valuation repair config and clear runtime cache."""

    config = get_equity_valuation_repair_config_repository().create(
        data=data,
        created_by=created_by,
    )
    clear_config_cache()
    return config


def update_valuation_repair_config(*, config_id: int, data: dict[str, Any]) -> Any | None:
    """Update one valuation repair config and clear runtime cache."""

    config = get_equity_valuation_repair_config_repository().update(
        config_id=config_id,
        data=data,
    )
    if config is not None:
        clear_config_cache()
    return config


def activate_valuation_repair_config(*, config_id: int) -> Any | None:
    """Activate one valuation repair config and clear runtime cache."""

    config = get_equity_valuation_repair_config_repository().activate(config_id=config_id)
    if config is not None:
        clear_config_cache()
    return config


def delete_valuation_repair_config(*, config_id: int) -> bool:
    """Delete one valuation repair config and clear runtime cache."""

    deleted = get_equity_valuation_repair_config_repository().delete(config_id=config_id)
    if deleted:
        clear_config_cache()
    return deleted


def get_active_valuation_repair_config_payload() -> dict[str, Any]:
    """Return the payload used by the active-config endpoint."""

    runtime_config = get_valuation_repair_config(use_cache=False)
    try:
        active_config = get_equity_valuation_repair_config_repository().get_active_model()
    except (OperationalError, ProgrammingError):
        active_config = None
    if active_config is not None:
        return {
            "success": True,
            "source": "database",
            "data": active_config,
        }

    source = "settings"
    if runtime_config == DEFAULT_VALUATION_REPAIR_CONFIG:
        source = "default"
    return {
        "success": True,
        "source": source,
        "data": {
            "version": 0,
            "is_active": False,
            "min_history_points": runtime_config.min_history_points,
            "default_lookback_days": runtime_config.default_lookback_days,
            "confirm_window": runtime_config.confirm_window,
            "min_rebound": runtime_config.min_rebound,
            "stall_window": runtime_config.stall_window,
            "stall_min_progress": runtime_config.stall_min_progress,
            "target_percentile": runtime_config.target_percentile,
            "undervalued_threshold": runtime_config.undervalued_threshold,
            "near_target_threshold": runtime_config.near_target_threshold,
            "overvalued_threshold": runtime_config.overvalued_threshold,
            "pe_weight": runtime_config.pe_weight,
            "pb_weight": runtime_config.pb_weight,
            "confidence_base": runtime_config.confidence_base,
            "confidence_sample_threshold": runtime_config.confidence_sample_threshold,
            "confidence_sample_bonus": runtime_config.confidence_sample_bonus,
            "confidence_blend_bonus": runtime_config.confidence_blend_bonus,
            "confidence_repair_start_bonus": runtime_config.confidence_repair_start_bonus,
            "confidence_not_stalled_bonus": runtime_config.confidence_not_stalled_bonus,
            "repairing_threshold": runtime_config.repairing_threshold,
            "eta_max_days": runtime_config.eta_max_days,
        },
    }


def clear_valuation_repair_config_cache_payload() -> dict[str, Any]:
    """Clear runtime cache for valuation repair config."""

    clear_config_cache()
    return {"success": True, "message": "配置缓存已清除"}


def init_stock_screening_rules(*, rules: list[dict[str, Any]]) -> None:
    """Persist stock screening rules used by the bootstrap command."""

    for rule_data in rules:
        get_equity_bootstrap_config_repository().upsert_stock_screening_rule(rule_data)


def init_sector_preferences(*, preferences: list[dict[str, Any]]) -> None:
    """Persist sector preference rows used by the bootstrap command."""

    for preference in preferences:
        get_equity_bootstrap_config_repository().upsert_sector_preference(preference)


def init_fund_type_preferences(*, preferences: list[dict[str, Any]]) -> None:
    """Persist fund type preference rows used by the bootstrap command."""

    for preference in preferences:
        get_equity_bootstrap_config_repository().upsert_fund_type_preference(preference)
