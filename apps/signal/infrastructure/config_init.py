"""
Configuration Initialization for Domain Layer

在应用启动时将数据库配置注入到 Domain 层。
"""

from __future__ import annotations

from typing import Any, cast

from django.apps import apps as django_apps

from apps.regime.domain.asset_eligibility import (
    Eligibility,
    set_eligibility_matrix_provider,
)
from apps.regime.domain.services_v2 import RegimeType


def _load_eligibility_matrix_from_db() -> dict[str, dict[str, Eligibility]]:
    """Load and validate the active eligibility matrix from the database."""

    regime_eligibility_model = django_apps.get_model("regime", "RegimeEligibilityConfigModel")
    if regime_eligibility_model is None:
        raise RuntimeError("RegimeEligibilityConfigModel is unavailable")
    configs = regime_eligibility_model._default_manager.filter(is_active=True)
    matrix: dict[str, dict[str, Eligibility]] = {}
    valid_regimes = {regime.value for regime in RegimeType}

    for raw_config in configs:
        config = cast(Any, raw_config)
        asset_class = str(config.asset_class).strip()
        regime = str(config.regime).strip()
        raw_eligibility = str(config.eligibility).strip()
        if not asset_class or len(asset_class) > 50:
            raise ValueError("eligibility configuration has an invalid asset class")
        if regime not in valid_regimes:
            raise ValueError(f"eligibility configuration has an invalid regime: {regime}")
        try:
            eligibility = Eligibility(raw_eligibility)
        except ValueError as exc:
            raise ValueError(
                f"eligibility configuration has an invalid value: {raw_eligibility}"
            ) from exc
        asset_matrix = matrix.setdefault(asset_class, {})
        if regime in asset_matrix:
            raise ValueError(f"duplicate eligibility configuration: {asset_class}/{regime}")
        asset_matrix[regime] = eligibility

    if not matrix:
        raise ValueError("no active eligibility configuration is available")

    return matrix


def initialize_domain_config() -> None:
    """
    初始化 Domain 层配置

    从数据库加载配置并注入到 Domain 层。
    应在 Django 应用启动时调用（例如 apps.py 的 ready() 方法）。
    """
    set_eligibility_matrix_provider(_load_eligibility_matrix_from_db)


def refresh_domain_config() -> None:
    """
    刷新 Domain 层配置

    当配置表更新后调用，强制重新加载配置。
    """
    initialize_domain_config()
