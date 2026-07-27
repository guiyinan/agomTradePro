"""Infrastructure registration for Account-owned trading gateways."""

from __future__ import annotations

from decimal import Decimal
from typing import Any, cast

from django.db import transaction

from apps.account.application.market_price_contracts import MarketPriceProvider
from apps.account.application.portfolio_api_contracts import (
    PortfolioApiRepository as PortfolioApiRepositoryProtocol,
)
from apps.account.application.portfolio_api_contracts import (
    UnifiedPositionService as UnifiedPositionServiceProtocol,
)


def _build_portfolio_api_repository() -> PortfolioApiRepositoryProtocol:
    from apps.simulated_trading.infrastructure.account_portfolio_repository import (
        PortfolioApiRepository,
    )

    return cast(PortfolioApiRepositoryProtocol, PortfolioApiRepository())


def _get_unified_position_service() -> UnifiedPositionServiceProtocol:
    from apps.simulated_trading.application.unified_position_service import (
        UnifiedPositionService,
    )

    return cast(UnifiedPositionServiceProtocol, UnifiedPositionService.default())


def _build_price_provider(cache_ttl_minutes: int) -> MarketPriceProvider:
    from apps.simulated_trading.infrastructure.price_provider import DataCenterPriceProvider

    return DataCenterPriceProvider(cache_ttl_minutes=cache_ttl_minutes)


def _provision_default_accounts(user: Any, initial_capital: Decimal) -> None:
    from apps.simulated_trading.infrastructure.models import SimulatedAccountModel

    with transaction.atomic():
        if not SimulatedAccountModel._default_manager.filter(
            user=user, account_type="real"
        ).exists():
            SimulatedAccountModel._default_manager.create(
                user=user,
                account_name=f"{user.username}_实仓",
                account_type="real",
                initial_capital=Decimal("0"),
                current_cash=Decimal("0"),
                current_market_value=Decimal("0"),
                total_value=Decimal("0"),
                auto_trading_enabled=False,
            )

        if not SimulatedAccountModel._default_manager.filter(
            user=user, account_type="simulated"
        ).exists():
            SimulatedAccountModel._default_manager.create(
                user=user,
                account_name=f"{user.username}_模拟仓",
                account_type="simulated",
                initial_capital=initial_capital,
                current_cash=initial_capital,
                current_market_value=Decimal("0"),
                total_value=initial_capital,
                auto_trading_enabled=True,
            )


def _list_investment_accounts(user_id: int) -> list[dict[str, Any]]:
    from apps.simulated_trading.infrastructure.models import SimulatedAccountModel

    accounts = (
        SimulatedAccountModel._default_manager.filter(user_id=user_id)
        .only("id", "account_name", "account_type", "total_value", "total_return")
        .order_by("account_type", "-created_at")
    )
    return [
        {
            "id": account.id,
            "account_name": account.account_name,
            "account_type": account.account_type,
            "total_value": float(account.total_value or 0),
            "total_return": float(account.total_return or 0),
        }
        for account in accounts
    ]


def _get_unified_account_id_for_portfolio(portfolio_id: int) -> int | None:
    from apps.simulated_trading.infrastructure.models import LedgerMigrationMapModel

    return (
        LedgerMigrationMapModel._default_manager.filter(
            source_table="portfolio",
            source_id=portfolio_id,
            target_table="simulated_account",
        )
        .values_list("target_id", flat=True)
        .first()
    )


def _resolve_view(view_key: str) -> type[Any]:
    from apps.simulated_trading.interface import performance_views, views

    view_map = {
        "account-list": views.AccountListAPIView,
        "account-batch-delete": views.AccountBatchDeleteAPIView,
        "account-detail": views.AccountDetailAPIView,
        "account-position-list": views.PositionListAPIView,
        "account-trade-list": views.TradeListAPIView,
        "account-performance": views.PerformanceAPIView,
        "account-equity-curve": views.EquityCurveAPIView,
        "account-inspection-run": views.DailyInspectionRunAPIView,
        "account-inspection-list": views.DailyInspectionReportListAPIView,
        "account-performance-report": performance_views.AccountPerformanceReportAPIView,
        "account-valuation-snapshot": performance_views.AccountValuationSnapshotAPIView,
        "account-valuation-timeline": performance_views.AccountValuationTimelineAPIView,
        "account-benchmarks": performance_views.AccountBenchmarksAPIView,
        "account-backfill": performance_views.AccountBackfillAPIView,
    }
    return cast(type[Any], view_map[view_key])


def register_account_gateway() -> None:
    """Register all Account-facing trading providers."""

    from apps.account.application.simulated_trading_gateway import (
        configure_simulated_trading_gateway,
    )
    from apps.simulated_trading.application.query_services import (
        list_active_account_models_for_user,
    )
    from core.integration.trading_account_registry import (
        register_active_accounts_reader,
    )

    configure_simulated_trading_gateway(
        portfolio_repository_factory=_build_portfolio_api_repository,
        position_service_factory=_get_unified_position_service,
        price_provider_factory=_build_price_provider,
        default_accounts_provisioner=_provision_default_accounts,
        investment_accounts_reader=_list_investment_accounts,
        portfolio_account_resolver=_get_unified_account_id_for_portfolio,
        view_resolver=_resolve_view,
    )
    register_active_accounts_reader(list_active_account_models_for_user)


__all__ = ["register_account_gateway"]
