"""Regime application repository providers."""

from apps.regime.domain.protocols import MacroSourceConfigGatewayProtocol
from apps.regime.infrastructure.providers import (
    DjangoNavigatorRepository,
    get_navigator_repository as _get_navigator_repository,
    get_regime_repository as _get_regime_repository,
)


def get_default_macro_repository() -> object:
    """返回默认宏观数据 repository 适配器。"""
    from apps.regime.infrastructure.macro_data_provider import MacroRepositoryAdapter

    return MacroRepositoryAdapter()


def get_default_macro_data_provider():
    """Return the default macro data provider."""

    from apps.regime.infrastructure.macro_data_provider import (
        get_default_macro_data_provider as _impl,
    )

    return _impl()


def build_macro_data_provider():
    """Build the default Django macro data provider."""

    from apps.regime.infrastructure.macro_data_provider import DjangoMacroDataProvider

    return DjangoMacroDataProvider()


def build_macro_repository_adapter(provider=None):
    """Build a macro repository adapter, optionally wrapping a provider."""

    from apps.regime.infrastructure.macro_data_provider import MacroRepositoryAdapter

    if provider is None:
        return MacroRepositoryAdapter()
    return MacroRepositoryAdapter(provider)


def get_regime_repository():
    """返回 Regime snapshot/history repository。"""

    return _get_regime_repository()


def get_navigator_repository() -> DjangoNavigatorRepository:
    """返回导航仪相关 repository。"""
    return _get_navigator_repository()


def get_macro_source_config_gateway() -> MacroSourceConfigGatewayProtocol:
    """Return the configured macro source gateway for regime views."""

    from apps.regime.infrastructure.macro_source_config_gateway import DjangoMacroSourceConfigGateway

    return DjangoMacroSourceConfigGateway()


def build_macro_sync_task_gateway():
    """Build the default macro sync task gateway."""

    from apps.regime.infrastructure.macro_sync_gateway import DjangoMacroSyncTaskGateway

    return DjangoMacroSyncTaskGateway()
