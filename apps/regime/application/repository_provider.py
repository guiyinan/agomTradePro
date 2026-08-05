"""Regime application repository providers."""

from __future__ import annotations

from datetime import date
from typing import Any, Protocol, cast

from apps.regime.domain.protocols import (
    MacroDataProviderProtocol,
    MacroIndicator,
    MacroSourceConfigGatewayProtocol,
    MacroSyncTaskGatewayProtocol,
)
from apps.regime.infrastructure.providers import (
    DjangoNavigatorRepository,
    RegimeDiagnosticRepository,
)
from apps.regime.infrastructure.providers import (
    DjangoRegimeRepository as DjangoRegimeRepository,
)
from apps.regime.infrastructure.providers import (
    get_navigator_repository as _get_navigator_repository,
)
from apps.regime.infrastructure.providers import get_regime_repository as _get_regime_repository


class MacroRepositoryAdapterProtocol(Protocol):
    """Macro repository surface consumed by Regime application workflows."""

    GROWTH_INDICATORS: dict[str, str]
    INFLATION_INDICATORS: dict[str, str]

    def get_observations_for_period(
        self,
        indicator_code: str,
        start_date: date,
        end_date: date,
    ) -> list[MacroIndicator]:
        """Return observations within a reporting period."""

    def get_latest_observation(
        self,
        code: str,
        before_date: date | None = None,
    ) -> MacroIndicator | None:
        """Return the latest observation before an optional date."""

    def get_recent_observations(
        self,
        indicator_code: str,
        limit: int = 24,
    ) -> list[MacroIndicator]:
        """Return recent observations."""

    def get_latest_observation_date(
        self,
        indicator_code: str,
        as_of_date: date | None = None,
    ) -> date | None:
        """Return the latest observation date."""

    def get_by_code_and_date(
        self,
        code: str,
        observed_at: date,
    ) -> MacroIndicator | None:
        """Return an observation on an exact date."""

    def get_growth_series(
        self,
        indicator_code: str = "PMI",
        end_date: date | None = None,
        use_pit: bool = False,
        source: str | None = None,
        published_only: bool = False,
    ) -> list[float]:
        """Return growth values, optionally restricted to current publication members."""

    def get_growth_series_full(
        self,
        indicator_code: str = "PMI",
        end_date: date | None = None,
        use_pit: bool = False,
        source: str | None = None,
        published_only: bool = False,
    ) -> list[MacroIndicator]:
        """Return growth observations, optionally restricted to current publication members."""

    def get_inflation_series(
        self,
        indicator_code: str = "CPI",
        end_date: date | None = None,
        use_pit: bool = False,
        source: str | None = None,
        published_only: bool = False,
    ) -> list[float]:
        """Return inflation values, optionally restricted to current publication members."""

    def get_inflation_series_full(
        self,
        indicator_code: str = "CPI",
        end_date: date | None = None,
        use_pit: bool = False,
        source: str | None = None,
        published_only: bool = False,
    ) -> list[MacroIndicator]:
        """Return inflation observations, optionally restricted to current publication members."""

    def get_available_dates(
        self,
        codes: list[str] | None = None,
        start_date: date | None = None,
        end_date: date | None = None,
    ) -> list[date]:
        """Return dates available for the requested indicators."""


def get_default_macro_repository() -> MacroRepositoryAdapterProtocol:
    """返回默认宏观数据 repository 适配器。"""
    from apps.regime.infrastructure.macro_data_provider import MacroRepositoryAdapter

    return cast(MacroRepositoryAdapterProtocol, MacroRepositoryAdapter())


def get_default_macro_data_provider() -> MacroDataProviderProtocol:
    """Return the default macro data provider."""

    from apps.regime.infrastructure.macro_data_provider import (
        get_default_macro_data_provider as _impl,
    )

    return cast(MacroDataProviderProtocol, _impl())


def build_macro_data_provider() -> MacroDataProviderProtocol:
    """Build the default Django macro data provider."""

    from apps.regime.infrastructure.macro_data_provider import DjangoMacroDataProvider

    return cast(MacroDataProviderProtocol, DjangoMacroDataProvider())


def build_macro_repository_adapter(
    provider: MacroDataProviderProtocol | None = None,
) -> MacroRepositoryAdapterProtocol:
    """Build a macro repository adapter, optionally wrapping a provider."""

    from apps.regime.infrastructure.macro_data_provider import MacroRepositoryAdapter

    if provider is None:
        return cast(MacroRepositoryAdapterProtocol, MacroRepositoryAdapter())
    return cast(MacroRepositoryAdapterProtocol, MacroRepositoryAdapter(provider))


def get_regime_repository() -> DjangoRegimeRepository:
    """返回 Regime snapshot/history repository。"""

    return _get_regime_repository()


def get_regime_diagnostic_repository() -> RegimeDiagnosticRepository:
    """Return the regime diagnostic query repository."""

    return RegimeDiagnosticRepository()


def get_navigator_repository() -> DjangoNavigatorRepository:
    """返回导航仪相关 repository。"""
    return _get_navigator_repository()


def get_regime_config_repository() -> Any:
    """Return the configured regime config repository."""

    from apps.regime.infrastructure.providers import RegimeConfigRepository

    return RegimeConfigRepository()


def get_macro_source_config_gateway() -> MacroSourceConfigGatewayProtocol:
    """Return the configured macro source gateway for regime views."""

    from apps.regime.infrastructure.macro_source_config_gateway import (
        DjangoMacroSourceConfigGateway,
    )

    return DjangoMacroSourceConfigGateway()


def build_macro_sync_task_gateway() -> MacroSyncTaskGatewayProtocol:
    """Build the default macro sync task gateway."""

    from apps.regime.infrastructure.macro_sync_gateway import DjangoMacroSyncTaskGateway

    return cast(MacroSyncTaskGatewayProtocol, DjangoMacroSyncTaskGateway())
