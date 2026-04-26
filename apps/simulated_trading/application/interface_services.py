"""Application-facing helpers for simulated trading interface views."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Any

from apps.asset_analysis.application.repository_provider import get_asset_pool_query_repository
from apps.data_center.application.price_service import UnifiedPriceService
from apps.signal.application.repository_provider import get_signal_repository
from apps.simulated_trading.application.asset_pool_query_service import AssetPoolQueryService
from apps.simulated_trading.application.auto_trading_engine import AutoTradingEngine
from apps.simulated_trading.application.daily_inspection_service import DailyInspectionService
from apps.simulated_trading.application.facade import get_simulated_trading_facade
from apps.simulated_trading.application.performance_calculator import PerformanceCalculator
from apps.simulated_trading.application.repository_provider import (
    get_simulated_account_repository,
    get_simulated_fee_config_repository,
    get_simulated_inspection_repository,
    get_simulated_position_repository,
    get_simulated_trade_repository,
)
from apps.simulated_trading.application.use_cases import (
    ExecuteBuyOrderUseCase,
    ExecuteSellOrderUseCase,
    GetAccountPerformanceUseCase,
)
from core.integration.share_context import get_account_owner_share_links


@dataclass(frozen=True)
class AccountAccessResult:
    """Result for account ownership checks used by DRF views."""

    account: Any | None = None
    error: str | None = None
    status_code: int | None = None

    @property
    def allowed(self) -> bool:
        """Whether access was granted."""

        return self.account is not None and self.error is None


def get_account_repository() -> Any:
    """Return the default account repository."""

    return get_simulated_account_repository()


def get_position_repository() -> Any:
    """Return the default position repository."""

    return get_simulated_position_repository()


def get_trade_repository() -> Any:
    """Return the default trade repository."""

    return get_simulated_trade_repository()


def get_fee_config_repository() -> Any:
    """Return the default fee config repository."""

    return get_simulated_fee_config_repository()


def get_performance_calculator() -> PerformanceCalculator:
    """Return the default account performance calculator."""

    return PerformanceCalculator()


def get_trading_signal_repository() -> Any:
    """Return the default signal repository used by trading use cases."""

    return get_signal_repository()


def can_manage_account(user: Any, account: Any) -> bool:
    """Whether the current user can mutate the account."""

    if not getattr(user, "is_authenticated", False):
        return False
    return bool(getattr(user, "is_superuser", False) or account.user_id == user.id)


def get_account_access(user: Any, account_id: int, action: str = "访问") -> AccountAccessResult:
    """Return an owned account row or a structured access error."""

    if not user or not getattr(user, "is_authenticated", False):
        return AccountAccessResult(
            error=f"请先登录后再{action}账户",
            status_code=401,
        )

    account = get_simulated_account_repository().get_account_model_by_id(account_id)
    if not account:
        return AccountAccessResult(
            error=f"账户不存在: {account_id}",
            status_code=404,
        )

    if not can_manage_account(user, account):
        return AccountAccessResult(
            error=f"无权{action}该账户",
            status_code=403,
        )

    return AccountAccessResult(account=account)


def create_account_for_user(
    *,
    user: Any,
    account_name: str,
    account_type: str,
    initial_capital: Decimal,
) -> Any:
    """Create one account for the user-facing account page."""

    return get_simulated_account_repository().create_account_model_for_user(
        user=user,
        account_name=account_name,
        account_type=account_type,
        initial_capital=initial_capital,
    )


def build_my_accounts_context(user: Any) -> dict[str, Any]:
    """Build context for the account management page."""

    facade = get_simulated_trading_facade()
    accounts = get_simulated_account_repository().list_account_models_for_user(user.id)
    total_assets = Decimal("0")

    for account in accounts:
        account.active_strategy = facade.get_active_strategy_summary(account.id)
        total_assets += Decimal(account.total_value or 0)

    return {
        "total_assets": total_assets,
        "user": user,
        "accounts": accounts,
    }


def build_my_account_detail_context(user: Any, account_id: int) -> dict[str, Any] | None:
    """Build context for one account detail page."""

    account = get_simulated_account_repository().get_account_model_for_user(account_id, user.id)
    if not account:
        return None

    return {
        "account": account,
        "account_type": _account_type_label(account.account_type),
        "account_type_code": account.account_type,
        "positions": get_simulated_position_repository().list_position_models_for_account(
            account.id,
            limit=10,
        ),
        "trades": get_simulated_trade_repository().list_trade_models_for_account(
            account.id,
            limit=20,
        ),
        "share_links": get_account_owner_share_links(
            owner_id=user.id,
            account_id=account.id,
        ),
        "user": user,
    }


def build_my_positions_context(user: Any, account_id: int) -> dict[str, Any] | None:
    """Build context for one account positions page."""

    account = get_simulated_account_repository().get_account_model_for_user(account_id, user.id)
    if not account:
        return None

    return {
        "account": account,
        "account_type": _account_type_label(account.account_type),
        "account_type_code": account.account_type,
        "positions": get_simulated_position_repository().list_position_models_for_account(account.id),
        "user": user,
    }


def build_my_trades_context(user: Any, account_id: int) -> dict[str, Any] | None:
    """Build context for one account trades page."""

    account = get_simulated_account_repository().get_account_model_for_user(account_id, user.id)
    if not account:
        return None

    summary = get_simulated_trade_repository().get_trade_model_summary_for_account(account.id)
    return {
        "account": account,
        "account_type": _account_type_label(account.account_type),
        "account_type_code": account.account_type,
        "trades": summary["trades"],
        "buy_count": summary["buy_count"],
        "sell_count": summary["sell_count"],
        "total_realized_pnl": summary["total_realized_pnl"],
        "user": user,
    }


def build_inspection_notify_context(user: Any, account_id: int) -> dict[str, Any] | None:
    """Build context for daily inspection notification settings."""

    account = get_simulated_account_repository().get_account_model_for_user(account_id, user.id)
    if not account:
        return None

    context = get_simulated_inspection_repository().get_or_create_notification_config_model(account.id)
    if context is None:
        return None
    _, config = context

    return {
        "account": account,
        "config": config,
        "recipient_emails_text": "\n".join(config.recipient_emails or []),
    }


def save_inspection_notification_config(
    *,
    account_id: int,
    is_enabled: bool,
    include_owner_email: bool,
    notify_on: str,
    recipient_emails: list[str],
) -> Any | None:
    """Persist daily inspection notification settings."""

    return get_simulated_inspection_repository().update_notification_config(
        account_id=account_id,
        is_enabled=is_enabled,
        include_owner_email=include_owner_email,
        notify_on=notify_on,
        recipient_emails=recipient_emails,
    )


def delete_account_with_summary(account_id: int) -> dict | None:
    """Delete one account and return cascade summary details."""

    return get_simulated_account_repository().delete_account_with_summary(account_id)


def build_auto_trading_engine() -> AutoTradingEngine:
    """Build the default auto trading engine used by the manual trigger API."""

    account_repo = get_simulated_account_repository()
    position_repo = get_simulated_position_repository()
    trade_repo = get_simulated_trade_repository()
    signal_repo = get_signal_repository()

    buy_use_case = ExecuteBuyOrderUseCase(
        account_repo,
        position_repo,
        trade_repo,
        signal_repo=signal_repo,
    )
    sell_use_case = ExecuteSellOrderUseCase(account_repo, position_repo, trade_repo)
    performance_use_case = GetAccountPerformanceUseCase(account_repo, position_repo, trade_repo)
    asset_pool_service = AssetPoolQueryService(
        asset_pool_repo=get_asset_pool_query_repository(),
        signal_repo=signal_repo,
    )

    return AutoTradingEngine(
        account_repo=account_repo,
        position_repo=position_repo,
        trade_repo=trade_repo,
        buy_use_case=buy_use_case,
        sell_use_case=sell_use_case,
        performance_use_case=performance_use_case,
        asset_pool_service=asset_pool_service,
        price_provider=UnifiedPriceService(),
        signal_service=signal_repo,
    )


def run_daily_inspection(
    *,
    account_id: int,
    inspection_date: date | None,
    strategy_id: int | None,
    auto_create_proposal: bool = False,
) -> dict[str, Any]:
    """Run daily inspection for one account."""

    if auto_create_proposal:
        return DailyInspectionService.run_and_create_proposal(
            account_id=account_id,
            inspection_date=inspection_date,
            strategy_id=strategy_id,
            auto_create_proposal=True,
        )

    return DailyInspectionService.run(
        account_id=account_id,
        inspection_date=inspection_date,
        strategy_id=strategy_id,
    )


def list_daily_inspection_report_payloads(
    *,
    account_id: int,
    limit: int,
    inspection_date: date | None,
) -> list[dict]:
    """Return daily inspection reports serialized for API output."""

    return get_simulated_inspection_repository().list_report_payloads(
        account_id=account_id,
        limit=limit,
        inspection_date=inspection_date,
    )


def _account_type_label(account_type: str) -> str:
    """Return display label for account type."""

    return "真实账户" if account_type == "real" else "模拟账户"
