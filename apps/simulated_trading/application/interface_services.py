"""Application-facing helpers for simulated trading interface views."""

from __future__ import annotations

import logging
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Any, cast
from uuid import UUID

from django.db import DEFAULT_DB_ALIAS
from django.utils import timezone

from apps.account.application.portfolio_api_contracts import (
    PortfolioApiRepository as PortfolioApiRepositoryProtocol,
)
from apps.asset_analysis.application.repository_provider import get_asset_pool_query_repository
from apps.share.application.query_services import list_share_links_for_account_owner
from apps.signal.application.repository_provider import get_signal_repository
from apps.simulated_trading.application.asset_pool_query_service import AssetPoolQueryService
from apps.simulated_trading.application.auto_trading_engine import AutoTradingEngine
from apps.simulated_trading.application.automatic_invocation import (
    AutoTradingInvocationRequest,
    AutoTradingInvocationResult,
    AutoTradingRequestActor,
    ExecuteAutomaticInvocation,
    FrozenAutoTradingScope,
    get_auto_invocation_repository,
    validate_auto_invocation_key,
)
from apps.simulated_trading.application.automatic_trade_execution import (
    get_automatic_trade_execution_bridge,
)
from apps.simulated_trading.application.daily_inspection_service import DailyInspectionService
from apps.simulated_trading.application.decision_rhythm_exit_gateway import (
    build_decision_rhythm_exit_advisor,
)
from apps.simulated_trading.application.facade import get_simulated_trading_facade
from apps.simulated_trading.application.performance_calculator import PerformanceCalculator
from apps.simulated_trading.application.ports import (
    AdminDashboardTradeStatisticsRepositoryProtocol,
    DailyNetValueRepositoryProtocol,
)
from apps.simulated_trading.application.rebalance_plan_preview import (
    ReadOnlyRebalancePlanPreviewBuilder,
)
from apps.simulated_trading.application.repository_provider import (
    get_simulated_account_repository,
    get_simulated_daily_net_value_repository,
    get_simulated_fee_config_repository,
    get_simulated_inspection_repository,
    get_simulated_position_repository,
    get_simulated_trade_repository,
)
from apps.simulated_trading.application.temporary_target_access import (
    require_temporary_target_account_owner,
)
from apps.simulated_trading.application.temporary_target_entry import (
    parse_temporary_security_targets,
)
from apps.simulated_trading.application.unified_position_service import UnifiedPositionService
from apps.simulated_trading.application.use_cases import (
    GetAccountPerformanceUseCase,
)
from apps.simulated_trading.domain.auto_trading_outcomes import (
    AutoTradingBatchOutcome,
)
from apps.simulated_trading.domain.temporary_rebalance_targets import (
    TemporarySecurityTargets,
    TemporaryTargetValidationError,
)
from apps.strategy.application.execution_gateway import StrategySelectionState
from core.exceptions import AgomTradeProException
from core.integration.decision_execution_links import build_decision_execution_link_recorder
from core.integration.portfolio_account_access import PortfolioAccountAccessResult

MAX_AUTO_TRADING_ACCOUNT_SCOPE_SIZE = 10_000
logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class AccountAccessResult(PortfolioAccountAccessResult):
    """Result for account ownership checks used by DRF views."""

    account: Any | None = None
    error: str | None = None
    status_code: int | None = None

    @property
    def allowed(self) -> bool:
        """Whether access was granted."""

        return self.account is not None and self.error is None


@dataclass(frozen=True)
class AutoTradingAccountScopeResult:
    """Authorized simulated account ids for one manual auto-trading request."""

    account_ids: tuple[int, ...] | None = None
    error: str | None = None
    status_code: int | None = None

    @property
    def allowed(self) -> bool:
        """Whether a complete account scope was resolved."""

        return self.account_ids is not None and self.error is None and self.status_code is None


def get_manual_trade_portfolio_id_for_account(account_id: int) -> int | None:
    """Return the legacy portfolio id used by manual trade import for one account."""

    from apps.account.application.repository_provider import get_portfolio_api_repository

    portfolio_repo = cast(
        PortfolioApiRepositoryProtocol,
        get_portfolio_api_repository(),
    )
    portfolio = portfolio_repo.get_portfolio_for_account(account_id)
    if portfolio is None:
        return None
    return int(portfolio.id)


def get_account_repository() -> Any:
    """Return the default account repository."""

    return get_simulated_account_repository()


def get_position_repository() -> Any:
    """Return the default position repository."""

    return get_simulated_position_repository()


def get_trade_repository() -> Any:
    """Return the default trade repository."""

    return get_simulated_trade_repository()


def get_daily_net_value_repository() -> DailyNetValueRepositoryProtocol:
    """Return the daily snapshot repository used for corrected performance reads."""

    return get_simulated_daily_net_value_repository()


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


def resolve_auto_trading_account_scope(
    user: Any,
    account_ids: list[int] | None,
) -> AutoTradingAccountScopeResult:
    """Resolve a user's eligible simulated account scope before engine construction.

    An omitted list selects only the authenticated user's active, auto-enabled
    simulated accounts. An explicit list is checked account by account through
    the existing ownership policy. An empty list remains an explicit empty scope.
    """

    if not user or getattr(user, "is_authenticated", False) is not True:
        return AutoTradingAccountScopeResult(
            error="请先登录后再执行自动交易",
            status_code=401,
        )
    user_id = getattr(user, "id", None)
    if type(user_id) is not int or user_id <= 0:
        return AutoTradingAccountScopeResult(
            error="当前用户身份无效",
            status_code=401,
        )

    if account_ids is not None:
        if type(account_ids) is not list:
            return AutoTradingAccountScopeResult(
                error="account_ids 必须是列表",
                status_code=400,
            )
        if len(account_ids) > MAX_AUTO_TRADING_ACCOUNT_SCOPE_SIZE:
            return AutoTradingAccountScopeResult(
                error="account_ids 超出允许的账户数量",
                status_code=400,
            )
        if any(type(account_id) is not int or account_id <= 0 for account_id in account_ids):
            return AutoTradingAccountScopeResult(
                error="account_ids 必须是正整数列表",
                status_code=400,
            )
        if len(set(account_ids)) != len(account_ids):
            return AutoTradingAccountScopeResult(
                error="account_ids 不能包含重复账户",
                status_code=400,
            )
        if not account_ids:
            return AutoTradingAccountScopeResult(account_ids=())

        authorized_ids: list[int] = []
        for account_id in account_ids:
            access = get_account_access(user, account_id, action="执行自动交易")
            if not access.allowed:
                return AutoTradingAccountScopeResult(
                    error=access.error or "无权执行自动交易",
                    status_code=access.status_code or 403,
                )
            account = access.account
            row_account_id = getattr(account, "id", None)
            if type(row_account_id) is not int or row_account_id != account_id:
                return AutoTradingAccountScopeResult(
                    error="所选账户记录无效",
                    status_code=404,
                )
            owner_id = getattr(account, "user_id", None)
            if owner_id is not None and type(owner_id) is not int:
                return AutoTradingAccountScopeResult(
                    error="所选账户记录无效",
                    status_code=404,
                )
            if owner_id != user_id and getattr(user, "is_superuser", False) is not True:
                return AutoTradingAccountScopeResult(
                    error="无权执行自动交易该账户",
                    status_code=403,
                )
            if getattr(account, "account_type", None) != "simulated":
                return AutoTradingAccountScopeResult(
                    error="自动交易仅支持模拟账户",
                    status_code=400,
                )
            if getattr(account, "is_active", False) is not True:
                return AutoTradingAccountScopeResult(
                    error="所选账户未启用",
                    status_code=400,
                )
            if getattr(account, "auto_trading_enabled", False) is not True:
                return AutoTradingAccountScopeResult(
                    error="所选账户未启用自动交易",
                    status_code=400,
                )
            authorized_ids.append(account_id)
        return AutoTradingAccountScopeResult(account_ids=tuple(authorized_ids))

    account_repo = get_simulated_account_repository()
    account_models = account_repo.get_active_account_models_for_user(user_id)
    selected_ids: list[int] = []
    seen_ids: set[int] = set()
    for account in account_models:
        row_user_id = getattr(account, "user_id", None)
        if type(row_user_id) is not int or row_user_id != user_id:
            return AutoTradingAccountScopeResult(
                error="账户范围包含其他用户或无效记录",
                status_code=500,
            )
        row_account_id = getattr(account, "id", None)
        if type(row_account_id) is not int or row_account_id <= 0 or row_account_id in seen_ids:
            return AutoTradingAccountScopeResult(
                error="账户范围包含重复或无效记录",
                status_code=500,
            )
        seen_ids.add(row_account_id)
        if getattr(account, "is_active", False) is not True:
            return AutoTradingAccountScopeResult(
                error="账户范围包含非活动记录",
                status_code=500,
            )
        account_type = getattr(account, "account_type", None)
        if account_type == "real":
            continue
        if account_type != "simulated":
            return AutoTradingAccountScopeResult(
                error="账户范围包含未知账户类型",
                status_code=500,
            )
        if type(getattr(account, "auto_trading_enabled", None)) is not bool:
            return AutoTradingAccountScopeResult(
                error="账户范围包含无效自动交易状态",
                status_code=500,
            )
        if getattr(account, "auto_trading_enabled", False) is not True:
            continue
        selected_ids.append(row_account_id)
        if len(selected_ids) > MAX_AUTO_TRADING_ACCOUNT_SCOPE_SIZE:
            return AutoTradingAccountScopeResult(
                error="默认账户范围超出允许的账户数量",
                status_code=400,
            )
    return AutoTradingAccountScopeResult(account_ids=tuple(selected_ids))


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
    total_assets: Decimal | None = Decimal("0")

    for account in accounts:
        account.active_strategy = facade.get_active_strategy_summary(account.id)
        account.manual_trade_portfolio_id = _manual_trade_portfolio_id(account)
        if account.cash_known is not True:
            total_assets = None
        elif total_assets is not None:
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
        "manual_trade_portfolio_id": _manual_trade_portfolio_id(account),
        "positions": get_simulated_position_repository().list_position_models_for_account(
            account.id,
            limit=10,
        ),
        "trades": get_simulated_trade_repository().list_trade_models_for_account(
            account.id,
            limit=20,
        ),
        "share_links": list_share_links_for_account_owner(
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

    positions = get_simulated_position_repository().list_position_models_for_account(account.id)
    return {
        "account": account,
        "account_type": _account_type_label(account.account_type),
        "account_type_code": account.account_type,
        "manual_trade_portfolio_id": _manual_trade_portfolio_id(account),
        "positions": positions,
        "position_valuation_known": all(position.valuation_known is True for position in positions),
        "user": user,
    }


def has_complete_closed_trade_costs(account_id: int, *, using: str = DEFAULT_DB_ALIAS) -> bool:
    """Check executed sell evidence in the account's trusted database."""

    repository = get_simulated_trade_repository()
    return not (
        repository.has_incomplete_closed_trade_costs(account_id)
        if using == DEFAULT_DB_ALIAS
        else repository.has_incomplete_closed_trade_costs(account_id, using=using)
    )


def has_current_position_valuation(account_id: int, *, using: str = DEFAULT_DB_ALIAS) -> bool:
    """Check current position valuation in the account's trusted database."""

    repository = get_simulated_position_repository()
    positions = (
        repository.get_by_account(account_id)
        if using == DEFAULT_DB_ALIAS
        else repository.get_by_account(account_id, using=using)
    )
    return all(position.valuation_known is True for position in positions)


def build_my_trades_context(user: Any, account_id: int) -> dict[str, Any] | None:
    """Build context for one account trades page."""

    account = get_simulated_account_repository().get_account_model_for_user(account_id, user.id)
    if not account:
        return None

    summary = get_simulated_trade_repository().get_trade_model_summary_for_account(account.id)
    trades = summary["trades"]
    for trade in trades:
        is_sell = trade.action.value == "sell"
        current_realized_pnl = trade.current_realized_pnl
        current_realized_pnl_pct = trade.current_realized_pnl_pct
        original_realized_pnl_known = (
            is_sell
            and trade.cost_basis_known is True
            and trade.fee_amounts_known is True
            and trade.realized_pnl is not None
        )
        realized_pnl_known = (
            is_sell
            and trade.cost_basis_known is True
            and trade.fee_amounts_known is True
            and current_realized_pnl is not None
        )
        original_realized_pnl_pct_known = (
            original_realized_pnl_known and trade.realized_pnl_pct is not None
        )
        realized_pnl_pct_known = realized_pnl_known and current_realized_pnl_pct is not None
        trade.original_realized_pnl_known = original_realized_pnl_known
        trade.original_realized_pnl_pct_known = original_realized_pnl_pct_known
        trade.realized_pnl_known = realized_pnl_known
        trade.effective_realized_pnl_known = realized_pnl_known
        trade.effective_realized_pnl_pct_known = realized_pnl_pct_known
        trade.realized_pnl_pct_known = realized_pnl_pct_known
        trade.original_realized_pnl_status = (
            "已知"
            if original_realized_pnl_known
            else "成本基数或卖出费用完整性未知" if is_sell else "不适用"
        )
        trade.realized_pnl_status = (
            "已知"
            if realized_pnl_known
            else "成本基数或卖出费用完整性未知" if is_sell else "不适用"
        )
        trade.realized_pnl_pct_status = (
            "已知"
            if realized_pnl_pct_known
            else (
                "成本基数或卖出费用完整性未知"
                if is_sell and not realized_pnl_known
                else "不可计算" if is_sell else "不适用"
            )
        )
        trade.original_realized_pnl_pct_status = (
            "已知"
            if original_realized_pnl_pct_known
            else (
                "成本基数或卖出费用完整性未知"
                if is_sell and not original_realized_pnl_known
                else "不可计算" if is_sell else "不适用"
            )
        )
        trade.effective_realized_pnl_pct_status = trade.realized_pnl_pct_status
    return {
        "account": account,
        "account_type": _account_type_label(account.account_type),
        "account_type_code": account.account_type,
        "trades": trades,
        "total_trade_count": summary["total_trade_count"],
        "buy_count": summary["buy_count"],
        "sell_count": summary["sell_count"],
        "total_realized_pnl": summary["total_realized_pnl"],
        "total_realized_pnl_known": summary["total_realized_pnl_known"],
        "effective_total_realized_pnl": summary["effective_total_realized_pnl"],
        "effective_total_realized_pnl_known": summary["effective_total_realized_pnl_known"],
        "user": user,
    }


def build_inspection_notify_context(user: Any, account_id: int) -> dict[str, Any] | None:
    """Build context for daily inspection notification settings."""

    account = get_simulated_account_repository().get_account_model_for_user(account_id, user.id)
    if not account:
        return None

    context = get_simulated_inspection_repository().get_or_create_notification_config_model(
        account.id
    )
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


def delete_account_with_summary(account_id: int) -> dict[str, Any] | None:
    """Delete one account and return cascade summary details."""

    return get_simulated_account_repository().delete_account_with_summary(account_id)


def close_account_position(
    *,
    account_id: int,
    asset_code: str,
    close_shares: Decimal | None = None,
    close_price: Decimal | None = None,
    reason: str = "平仓",
) -> dict[str, Any]:
    """Close all or part of an account position through the unified ledger service."""

    remaining = UnifiedPositionService.default().close_position(
        account_id=account_id,
        asset_code=asset_code,
        close_shares=close_shares,
        close_price=close_price,
        reason=reason,
    )
    return {
        "account_id": account_id,
        "asset_code": asset_code,
        "closed": remaining is None,
        "remaining_quantity": str(remaining.quantity) if remaining is not None else "0",
    }


def reset_account_with_summary(
    *,
    account_id: int,
    new_initial_capital: Decimal | None = None,
) -> dict[str, Any] | None:
    """Reset one account through its infrastructure repository boundary."""

    return get_simulated_account_repository().reset_account_with_summary(
        account_id,
        new_initial_capital,
    )


def build_auto_trading_engine(
    *, invocation_id: UUID, expected_owner_id: int | None = None
) -> AutoTradingEngine:
    """Build one guarded automatic engine using the settlement-bound ledger adapters."""

    account_repo = get_simulated_account_repository()
    position_repo = get_simulated_position_repository()
    trade_repo = get_simulated_trade_repository()
    signal_repo = get_signal_repository()
    execution_bridge = (
        get_automatic_trade_execution_bridge(invocation_id)
        if expected_owner_id is None
        else get_automatic_trade_execution_bridge(
            invocation_id, expected_owner_id=expected_owner_id
        )
    )
    performance_use_case = GetAccountPerformanceUseCase(
        account_repo,
        position_repo,
        trade_repo,
        get_simulated_daily_net_value_repository(),
    )
    asset_pool_service = AssetPoolQueryService(
        asset_pool_repo=get_asset_pool_query_repository(),
        signal_repo=signal_repo,
    )
    return AutoTradingEngine(
        account_repo=account_repo,
        position_repo=position_repo,
        trade_repo=trade_repo,
        buy_use_case=execution_bridge.buy_use_case,
        sell_use_case=execution_bridge.sell_use_case,
        performance_use_case=performance_use_case,
        asset_pool_service=asset_pool_service,
        price_provider=execution_bridge.price_provider,
        signal_service=signal_repo,
        exit_advisor=build_decision_rhythm_exit_advisor(),
        execution_link_recorder=build_decision_execution_link_recorder(),
    )


def run_auto_trading_for_scope(
    *,
    trade_date: date,
    account_ids: tuple[int, ...],
    invocation_key: str | None = None,
) -> AutoTradingBatchOutcome:
    """Execute one trusted internal explicit scope and preserve its typed result.

    Engine construction happens before execution and may fail without writes. Once
    ``run_daily_trading`` begins, exceptions are reported as indeterminate rather
    than inviting a whole-batch retry.
    """
    if type(trade_date) is not date:
        raise ValueError("trade_date must be an exact date")
    if (
        type(account_ids) is not tuple
        or len(account_ids) > MAX_AUTO_TRADING_ACCOUNT_SCOPE_SIZE
        or any(type(account_id) is not int or account_id <= 0 for account_id in account_ids)
    ):
        raise ValueError("account_ids must be a bounded tuple of positive exact integers")
    if len(set(account_ids)) != len(account_ids):
        raise ValueError("account_ids must not contain duplicates")
    request = AutoTradingInvocationRequest(
        namespace="internal:simulated-auto",
        invocation_key=validate_auto_invocation_key(invocation_key),
        trade_date=trade_date,
        requested_account_ids=account_ids,
    )

    def resolve_scope() -> FrozenAutoTradingScope:
        return FrozenAutoTradingScope(trade_date, account_ids)

    def authorize_scope(scope: FrozenAutoTradingScope) -> None:
        # This internal entry receives an already-authorized explicit scope.
        if scope.account_ids != account_ids:
            raise AgomTradeProException("自动交易账户范围不匹配", status_code=403)

    def build_engine(invocation_id: UUID) -> AutoTradingEngine:
        return build_auto_trading_engine(invocation_id=invocation_id)

    result = ExecuteAutomaticInvocation(get_auto_invocation_repository()).execute(
        request,
        resolve_scope=resolve_scope,
        authorize_scope=authorize_scope,
        build_engine=build_engine,
    )
    return result.outcome


def run_auto_trading_request(
    *,
    actor: AutoTradingRequestActor,
    invocation_key: str,
    trade_date: date | None,
    account_ids: list[int] | None,
) -> AutoTradingInvocationResult:
    """Freeze an owner's first effective scope and reauthorize it on every replay."""
    request = AutoTradingInvocationRequest(
        namespace=f"http:user:{actor.id}",
        invocation_key=invocation_key,
        trade_date=trade_date,
        requested_account_ids=tuple(account_ids) if account_ids is not None else None,
    )

    def checked_scope(selected_ids: list[int] | None) -> tuple[int, ...]:
        scope = resolve_auto_trading_account_scope(actor, selected_ids)
        if not scope.allowed or scope.account_ids is None:
            raise AgomTradeProException(
                scope.error or "无法确定自动交易账户范围",
                code="AUTO_TRADING_SCOPE_REJECTED",
                status_code=scope.status_code or 403,
            )
        return scope.account_ids

    def resolve_scope() -> FrozenAutoTradingScope:
        return FrozenAutoTradingScope(
            trade_date=trade_date if trade_date is not None else timezone.localdate(),
            account_ids=checked_scope(account_ids),
        )

    def authorize_scope(scope: FrozenAutoTradingScope) -> None:
        checked_scope(list(scope.account_ids))

    def build_engine(invocation_id: UUID) -> AutoTradingEngine:
        return build_auto_trading_engine(
            invocation_id=invocation_id,
            expected_owner_id=None if actor.is_superuser else actor.id,
        )

    return ExecuteAutomaticInvocation(get_auto_invocation_repository()).execute(
        request,
        resolve_scope=resolve_scope,
        authorize_scope=authorize_scope,
        build_engine=build_engine,
    )


def run_daily_inspection(
    *,
    account_id: int,
    inspection_date: date | None,
    strategy_id: int | None,
    auto_create_proposal: bool = False,
    user_id: int | None = None,
    preview_builder: ReadOnlyRebalancePlanPreviewBuilder | None = None,
    temporary_target_weights: str | None = None,
) -> dict[str, Any]:
    """Run daily inspection and optionally attach a temporary-target preview.

    Temporary targets are parsed as exact decimal fractions and remain separate
    from the account-bound strategy and position-rule context.
    """

    temporary_targets: TemporarySecurityTargets | None = None
    target_text: str | None = None
    if temporary_target_weights is not None:
        if type(temporary_target_weights) is not str:
            raise TemporaryTargetValidationError(
                "TARGET_TEXT_INVALID", "请按每行一只证券的格式填写目标比例。"
            )
        target_text = temporary_target_weights

    if target_text is not None and target_text.strip():
        if strategy_id is not None:
            raise TemporaryTargetValidationError(
                "TARGET_STRATEGY_ID_FORBIDDEN", "临时目标预览不能指定策略编号。"
            )
        if auto_create_proposal:
            raise TemporaryTargetValidationError(
                "TARGET_PROPOSAL_FORBIDDEN", "临时目标只支持只读预览，不能生成调仓方案。"
            )
        if preview_builder is None:
            raise TemporaryTargetValidationError(
                "TARGET_PREVIEW_BUILDER_REQUIRED", "当前无法生成临时目标预览，请稍后重试。"
            )
        require_temporary_target_account_owner(account_id=account_id, user_id=user_id)
        temporary_targets = parse_temporary_security_targets(target_text)

    if auto_create_proposal:
        result = DailyInspectionService.run_and_create_proposal(
            account_id=account_id,
            inspection_date=inspection_date,
            strategy_id=strategy_id,
            auto_create_proposal=True,
            user_id=user_id,
        )
    else:
        result = DailyInspectionService.run(
            account_id=account_id,
            inspection_date=inspection_date,
            strategy_id=strategy_id,
            temporary_targets=temporary_targets,
            user_id=user_id,
        )

    if preview_builder is None:
        return result
    account = get_simulated_account_repository().get_by_id(account_id)
    if account is None:
        raise ValueError(f"模拟账户不存在: {account_id}")
    result_date = date.fromisoformat(str(result.get("inspection_date") or ""))
    summary = _inspection_mapping(result.get("summary"))
    checks = _inspection_mappings(result.get("checks"))
    preview = preview_builder.build(
        account=account,
        user_id=user_id if user_id is not None else 0,
        positions=tuple(get_simulated_position_repository().get_by_account(account_id)),
        checks=checks,
        summary=summary,
        strategy_id=_optional_int(result.get("strategy_id")),
        position_rule_id=_optional_int(result.get("position_rule_id")),
        strategy_name=_optional_text(result.get("strategy_name")),
        strategy_type=_optional_text(result.get("strategy_type")),
        strategy_version=_optional_int(result.get("strategy_version")),
        strategy_selection_state=_strategy_selection_state(result),
        rule_name=_optional_text(result.get("rule_name")),
        max_position_pct=_inspection_decimal(result.get("max_position_pct")),
        max_total_position_pct=_inspection_decimal(result.get("max_total_position_pct")),
        stop_loss_pct=_inspection_decimal(result.get("stop_loss_pct")),
        macro_regime=str(result.get("macro_regime") or ""),
        policy_gear=str(result.get("policy_gear") or ""),
        as_of=timezone.now(),
        inspection_date=result_date,
        current_local_date=timezone.localdate(),
        temporary_targets=temporary_targets,
    )
    result["plan"] = preview.to_payload()
    return result


def _inspection_mapping(value: object) -> Mapping[str, object]:
    """Narrow one persisted JSON object before passing it into the preview builder."""

    if not isinstance(value, dict) or any(type(key) is not str for key in value):
        return {}
    return cast(Mapping[str, object], value)


def _inspection_mappings(value: object) -> tuple[Mapping[str, object], ...]:
    """Narrow persisted inspection rows into read-only mapping contracts."""

    if not isinstance(value, list):
        return ()
    return tuple(_inspection_mapping(item) for item in value if isinstance(item, dict))


def _optional_int(value: object) -> int | None:
    """Preserve only actual integer identifiers from the inspection result."""

    return value if type(value) is int else None


def _optional_text(value: object) -> str | None:
    """Preserve only nonempty text labels from the inspection result."""

    return value if type(value) is str and value else None


def _strategy_selection_state(value: Mapping[str, object]) -> StrategySelectionState:
    """Accept only a consistent explicit selection state from the service result."""

    raw_state = value.get("strategy_selection_state")
    strategy_id = value.get("strategy_id")
    if (
        type(raw_state) is str
        and raw_state == "configured"
        and type(strategy_id) is int
        and strategy_id > 0
    ):
        return "configured"
    if (
        type(raw_state) is str
        and raw_state == "confirmed_unconfigured"
        and all(
            key in value and value.get(key) is None
            for key in (
                "strategy_id",
                "position_rule_id",
                "strategy_name",
                "strategy_type",
                "strategy_version",
                "rule_name",
                "max_position_pct",
                "max_total_position_pct",
                "stop_loss_pct",
            )
        )
    ):
        return "confirmed_unconfigured"
    return "unavailable"


def _inspection_decimal(value: object) -> Decimal | None:
    """Convert one finite strategy risk percentage without rounding it through float."""

    if isinstance(value, bool) or value is None:
        return None
    try:
        result = value if type(value) is Decimal else Decimal(str(value))
    except (ArithmeticError, TypeError, ValueError):
        return None
    return result if result.is_finite() else None


def list_daily_inspection_report_payloads(
    *,
    account_id: int,
    limit: int,
    inspection_date: date | None,
) -> list[dict[str, Any]]:
    """Return daily inspection reports serialized for API output."""

    return get_simulated_inspection_repository().list_report_payloads(
        account_id=account_id,
        limit=limit,
        inspection_date=inspection_date,
    )


def list_account_trade_payloads(
    *,
    account_id: int,
    start_date: date | None = None,
    end_date: date | None = None,
    limit: int = 100,
) -> list[dict[str, Any]]:
    """Return JSON-safe account trades for cross-app application queries."""

    trades = get_simulated_trade_repository().get_by_account(account_id)
    payloads: list[dict[str, Any]] = []
    for trade in trades:
        if start_date and trade.execution_date < start_date:
            continue
        if end_date and trade.execution_date > end_date:
            continue
        sell_executed = trade.action.value == "sell" and trade.status.value == "executed"
        realized_pnl_known = (
            sell_executed
            and trade.cost_basis_known is True
            and trade.fee_amounts_known is True
            and trade.realized_pnl is not None
        )
        effective_realized_pnl_known = (
            sell_executed
            and trade.cost_basis_known is True
            and trade.fee_amounts_known is True
            and trade.current_realized_pnl is not None
        )
        payloads.append(
            {
                "trade_id": trade.trade_id,
                "account_id": trade.account_id,
                "asset_code": trade.asset_code,
                "asset_name": trade.asset_name,
                "asset_type": trade.asset_type,
                "action": trade.action.value,
                "quantity": str(trade.quantity),
                "price": str(trade.price),
                "amount": str(trade.amount),
                "commission": str(trade.commission),
                "slippage": str(trade.slippage),
                "total_cost": str(trade.total_cost),
                "effective_commission": (
                    str(trade.current_commission) if trade.fee_amounts_known is True else None
                ),
                "effective_transfer_fee": (
                    str(trade.current_transfer_fee)
                    if trade.fee_amounts_known is True and trade.current_transfer_fee is not None
                    else None
                ),
                "effective_stamp_duty": (
                    str(trade.current_stamp_duty)
                    if trade.fee_amounts_known is True and trade.current_stamp_duty is not None
                    else None
                ),
                "effective_total_cost": (
                    str(trade.current_total_cost) if trade.fee_amounts_known is True else None
                ),
                "fee_amounts_known": trade.fee_amounts_known,
                "fee_amounts_status": trade.fee_amounts_status,
                "cost_basis_known": trade.cost_basis_known,
                "cost_basis_status": trade.cost_basis_status,
                "realized_pnl": (str(trade.realized_pnl) if realized_pnl_known else None),
                "original_realized_pnl": (
                    str(trade.realized_pnl) if trade.realized_pnl is not None else None
                ),
                "effective_realized_pnl": (
                    str(trade.current_realized_pnl) if effective_realized_pnl_known else None
                ),
                "realized_pnl_pct": (trade.realized_pnl_pct if realized_pnl_known else None),
                "original_realized_pnl_pct": trade.realized_pnl_pct,
                "effective_realized_pnl_pct": (
                    trade.current_realized_pnl_pct if effective_realized_pnl_known else None
                ),
                "effective_realized_pnl_known": effective_realized_pnl_known,
                "fee_correction_revision": trade.fee_correction_revision,
                "fee_correction_overlay_applied": trade.fee_correction_overlay_applied,
                "realized_pnl_known": realized_pnl_known if trade.action.value == "sell" else None,
                "reason": trade.reason,
                "signal_id": trade.signal_id,
                "order_date": trade.order_date.isoformat(),
                "execution_date": trade.execution_date.isoformat(),
                "execution_time": trade.execution_time.isoformat(),
                "status": trade.status.value,
            }
        )
        if len(payloads) >= limit:
            break
    return payloads


def build_admin_dashboard_context() -> dict[str, Any]:
    """Build summary stats for the simulated-trading admin dashboard."""

    account_repo = get_simulated_account_repository()
    position_repo = get_simulated_position_repository()
    trade_repo: AdminDashboardTradeStatisticsRepositoryProtocol = get_simulated_trade_repository()
    today = timezone.now().date()
    today_summary = trade_repo.summarize_trade_models_for_date(today)
    active_accounts = account_repo.get_active_accounts()
    total_capital: Decimal | None = Decimal("0")
    for account in active_accounts:
        account_positions = position_repo.get_by_account(account.account_id)
        if account.cash_known is not True or any(
            position.valuation_known is not True for position in account_positions
        ):
            total_capital = None
            break
        if total_capital is not None:
            total_capital += Decimal(str(account.total_value))

    realized_pnl_summary = trade_repo.sum_realized_pnl_for_closed_trades()

    return {
        "total_accounts": account_repo.count_active_account_models(),
        "total_positions": position_repo.count_position_models(),
        "total_trades": trade_repo.count_trade_models(),
        "today_buy_count": today_summary["buy_count"],
        "today_sell_count": today_summary["sell_count"],
        "total_capital": total_capital,
        "total_pnl": realized_pnl_summary["realized_pnl"],
        "total_pnl_known": realized_pnl_summary["known"],
        "effective_total_pnl": realized_pnl_summary["effective_realized_pnl"],
        "effective_total_pnl_known": realized_pnl_summary["effective_known"],
        "total_pnl_covered_sell_count": realized_pnl_summary["covered_executed_sell_count"],
        "total_pnl_executed_sell_count": realized_pnl_summary["executed_sell_count"],
    }


def _account_type_label(account_type: str) -> str:
    """Return display label for account type."""

    return "真实账户" if account_type == "real" else "模拟账户"


def _manual_trade_portfolio_id(account: Any) -> int | None:
    """Return the manual-trade import portfolio id for mapped real accounts."""

    if getattr(account, "account_type", None) != "real":
        return None
    return get_manual_trade_portfolio_id_for_account(int(account.id))
