"""Regime application repository providers."""

from apps.regime.domain.protocols import MacroSourceConfigGatewayProtocol
from apps.regime.infrastructure.providers import (
    DjangoNavigatorRepository,
    DjangoRegimeRepository,
    get_navigator_repository as _get_navigator_repository,
)


def get_default_macro_repository() -> object:
    """返回默认宏观数据 repository 适配器。"""
    from apps.regime.infrastructure.macro_data_provider import MacroRepositoryAdapter

    return MacroRepositoryAdapter()


def get_regime_repository() -> DjangoRegimeRepository:
    """返回 Regime snapshot/history repository。"""

    return DjangoRegimeRepository()


def get_navigator_repository() -> DjangoNavigatorRepository:
    """返回导航仪相关 repository。"""
    return _get_navigator_repository()


def get_macro_source_config_gateway() -> MacroSourceConfigGatewayProtocol:
    """Return the configured macro source gateway for regime views."""

    from apps.regime.infrastructure.macro_source_config_gateway import DjangoMacroSourceConfigGateway

    return DjangoMacroSourceConfigGateway()
