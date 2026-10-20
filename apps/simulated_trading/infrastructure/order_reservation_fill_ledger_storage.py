"""Locked account valuation and T+1 settlement helpers for local fill writes."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date, datetime
from decimal import Decimal, localcontext

from apps.simulated_trading.domain.execution_settlement_primitives import (
    validate_ledger_money,
    validate_ledger_price,
    validate_ledger_quantity,
)
from apps.simulated_trading.domain.order_reservation_fill_settlement import (
    OrderFillSettlementProof,
)
from apps.simulated_trading.infrastructure.execution_settlement_accounting_math import (
    _money_difference,
    _money_sum,
    _multiply_money,
    _quantity_difference,
    _require_known_simulated_cash,
)
from apps.simulated_trading.infrastructure.execution_settlement_plan_binding_repository import (
    pending_settlement_source_exchange as _pending_settlement_source_exchange,
)
from apps.simulated_trading.infrastructure.order_reservation_fill_chain_storage import (
    _blocked,
    _LockedFillChain,
    _trade_precision_values,
)
from apps.simulated_trading.infrastructure.order_reservation_guard import (
    active_order_reservation_holds,
)
from apps.simulated_trading.infrastructure.order_reservation_models import (
    SimulatedOrderReservationModel,
)
from apps.simulated_trading.infrastructure.order_reservation_sqlite_precision import (
    PrecisionValue,
    require_sqlite_values,
)
from apps.simulated_trading.infrastructure.simulated_account_trade_models import (
    PositionModel,
    SimulatedAccountModel,
    SimulatedTradeModel,
)

_ZERO_CASH = Decimal("0.00")
_ZERO_SHARES = Decimal("0.000000")


def _quantity_sum(left: Decimal, right: Decimal) -> Decimal:
    """Add ledger shares at six-place precision regardless of ambient Decimal context."""

    with localcontext() as context:
        context.prec = 80
        total = left + right
    return validate_ledger_quantity(total, "ledger.quantity_sum", allow_zero=True)


def _account_positions_snapshot(
    *,
    account: SimulatedAccountModel,
    positions: Sequence[PositionModel],
    asset_code: str,
    using: str,
) -> tuple[PositionModel, Decimal, Decimal]:
    """Validate the entire marked account aggregate and return its target position."""

    _require_known_simulated_cash(
        cash_known=account.cash_known,
        reconciliation_status=account.cash_reconciliation_status,
    )
    precision_values: list[PrecisionValue] = [
        ("account.current_cash", account.current_cash, "money"),
        ("account.current_market_value", account.current_market_value, "money"),
        ("account.total_value", account.total_value, "money"),
    ]
    for position in positions:
        prefix = "position"
        precision_values.extend(
            (
                (f"{prefix}.quantity", position.quantity, "quantity"),
                (f"{prefix}.current_price", position.current_price, "price"),
                (f"{prefix}.market_value", position.market_value, "money"),
            )
        )
        if position.asset_code == asset_code:
            if position.available_quantity_known is True:
                precision_values.append(
                    (f"{prefix}.available_quantity", position.available_quantity, "quantity")
                )
            precision_values.extend(
                (
                    (f"{prefix}.total_cost", position.total_cost, "money"),
                    (f"{prefix}.average_cost", position.avg_cost, "price"),
                    (
                        f"{prefix}.unrealized_pnl_magnitude",
                        position.unrealized_pnl.copy_abs(),
                        "money",
                    ),
                )
            )
    require_sqlite_values(
        values=tuple(precision_values),
        using=using,
        error_code="ORDER_RESERVATION_STATE_INVALID",
    )
    cash = validate_ledger_money(account.current_cash, "account.current_cash")
    aggregate = validate_ledger_money(account.current_market_value, "account.current_market_value")
    total_value = validate_ledger_money(account.total_value, "account.total_value")
    marked_values: list[Decimal] = []
    target: PositionModel | None = None
    for position in positions:
        if position.account_id != account.pk or position.valuation_known is not True:
            raise _blocked("POSITION_VALUATION_UNKNOWN", "账户持仓估值不完整，成交记账已阻止")
        quantity = validate_ledger_quantity(position.quantity, "position.quantity")
        mark = validate_ledger_price(position.current_price, "position.current_price")
        value = validate_ledger_money(position.market_value, "position.market_value")
        expected_value = _multiply_money(quantity, mark, "position.current_market_value")
        if value != expected_value:
            raise _blocked("POSITION_VALUATION_INCONSISTENT", "持仓市值与已知持仓标记不一致")
        marked_values.append(value)
        if position.asset_code == asset_code:
            if target is not None:
                raise _blocked("POSITION_IDENTITY_AMBIGUOUS", "账户证券持仓重复")
            target = position
    expected_aggregate = _money_sum(*marked_values)
    if aggregate != expected_aggregate or total_value != _money_sum(cash, aggregate):
        raise _blocked(
            "ACCOUNT_VALUATION_INCONSISTENT",
            "账户总资产与已知现金及持仓估值不一致，成交记账已阻止",
        )
    if target is None:
        raise _blocked("POSITION_REQUIRED", "成交写入需要已有的已知估值持仓")
    if target.available_quantity_known is not True:
        raise _blocked("SELLABLE_BALANCE_UNKNOWN", "持仓可卖数量未知，成交记账已阻止")
    if type(target.cost_basis_known) not in (bool, type(None)):
        raise _blocked("POSITION_COST_BASIS_UNKNOWN", "持仓成本知识状态不可验证")
    validate_ledger_quantity(
        target.available_quantity, "position.available_quantity", allow_zero=True
    )
    if target.available_quantity > target.quantity:
        raise _blocked("POSITION_QUANTITY_INVALID", "持仓可卖数量超过总数量")
    validate_ledger_money(target.total_cost, "position.total_cost", allow_zero=True)
    return target, cash, aggregate


def _locked_pending_buys(
    *,
    account_id: int,
    asset_code: str,
    using: str,
) -> list[SimulatedTradeModel]:
    """Lock pending BUY ledger rows after all account, reservation and Position locks."""

    rows = list(
        SimulatedTradeModel._base_manager.using(using)
        .select_for_update()
        .filter(
            account_id=account_id,
            asset_code=asset_code,
            action="buy",
            settlement_status="pending",
        )
        .order_by("settlement_market_session", "pk")
    )
    pending_values: list[PrecisionValue] = []
    for row in rows:
        pending_values.extend(
            _trade_precision_values(
                row,
                field_prefix="pending_trade",
            )
        )
    require_sqlite_values(
        values=tuple(pending_values),
        using=using,
        error_code="ORDER_RESERVATION_STATE_INVALID",
    )
    return rows


def _pending_release_plan(
    *,
    pending_rows: Sequence[SimulatedTradeModel],
    position: PositionModel,
    proof: OrderFillSettlementProof,
    now: datetime,
    security_id: str,
) -> tuple[date, tuple[SimulatedTradeModel, ...], Decimal]:
    """Select only legacy pending buys whose frozen lag elapsed in this proof."""

    try:
        current_session = proof.calendar_evidence.current_open_session(now)
    except (ArithmeticError, TypeError, ValueError) as error:
        raise _blocked("SIMULATED_FILL_CALENDAR_INVALID", "当前成交日历未覆盖锁内时钟") from error
    due_rows: list[SimulatedTradeModel] = []
    pending_quantities: list[Decimal] = []
    due_quantities: list[Decimal] = []
    for row in pending_rows:
        if type(row.settlement_market_session) is not date:
            raise _blocked("PENDING_SETTLEMENT_INVALID", "待结算交易缺少有效成交日")
        if type(row.settlement_lag_sessions) is not int or row.settlement_lag_sessions < 0:
            raise _blocked("PENDING_SETTLEMENT_INVALID", "待结算交易缺少有效结算周期")
        if type(row.settlement_release_date) is not date:
            raise _blocked("PENDING_SETTLEMENT_INVALID", "待结算交易缺少冻结释放日")
        if row.settlement_plan_binding_version not in (1, 2, 3, 4):
            raise _blocked("PENDING_SETTLEMENT_INVALID", "待结算交易绑定版本不可验证")
        if row.settlement_plan_binding_version == 4:
            row_exchange = row.settlement_exchange
        else:
            try:
                row_exchange = _pending_settlement_source_exchange(row)
            except (ArithmeticError, AttributeError, TypeError, ValueError) as error:
                raise _blocked(
                    "PENDING_SETTLEMENT_INVALID", "待结算交易来源绑定不可验证"
                ) from error
        if row_exchange != proof.settlement_exchange:
            raise _blocked("PENDING_SETTLEMENT_SCOPE_MISMATCH", "待结算交易与当前日历来源不一致")
        if row.settlement_security_id is not None and row.settlement_security_id != security_id:
            raise _blocked("PENDING_SETTLEMENT_SCOPE_MISMATCH", "待结算交易证券身份不一致")
        quantity = validate_ledger_quantity(row.quantity, "pending_buy.quantity")
        pending_quantities.append(quantity)
        try:
            expected_release = proof.calendar_evidence.release_session(
                row.settlement_market_session,
                row.settlement_lag_sessions,
            )
            elapsed = proof.calendar_evidence.elapsed_open_sessions(
                row.settlement_market_session,
                current_session,
            )
        except (ArithmeticError, TypeError, ValueError) as error:
            raise _blocked(
                "PENDING_SETTLEMENT_CALENDAR_INVALID",
                "当前日历不能证明待结算交易的完整释放区间",
            ) from error
        if expected_release != row.settlement_release_date:
            raise _blocked("PENDING_SETTLEMENT_INVALID", "待结算交易释放日与冻结结算周期不符")
        if elapsed < row.settlement_lag_sessions:
            continue
        # V4 pending rows need a dedicated historical-receipt release validator.
        # Until that read path is installed, leave those shares unavailable.
        if row.settlement_plan_binding_version == 4:
            continue
        due_rows.append(row)
        due_quantities.append(quantity)
    current_available = validate_ledger_quantity(
        position.available_quantity,
        "position.available_quantity",
        allow_zero=True,
    )
    all_pending = _moneyless_quantity_sum(pending_quantities)
    if _quantity_sum(current_available, all_pending) > position.quantity:
        raise _blocked("PENDING_SETTLEMENT_INVALID", "可卖与待结算数量超过总持仓")
    due_quantity = _moneyless_quantity_sum(due_quantities)
    with localcontext() as context:
        context.prec = 80
        next_available = current_available + due_quantity
    next_available = validate_ledger_quantity(
        next_available,
        "position.available_quantity_after_pending_release",
        allow_zero=True,
    )
    if next_available > position.quantity:
        raise _blocked("PENDING_SETTLEMENT_INVALID", "释放待结算数量会超过总持仓")
    return current_session, tuple(due_rows), next_available


def _moneyless_quantity_sum(values: Sequence[Decimal]) -> Decimal:
    """Add exact six-place quantities without using the ambient Decimal context."""

    with localcontext() as context:
        context.prec = 80
        total = sum(values, _ZERO_SHARES)
    return validate_ledger_quantity(total, "pending_quantity_total", allow_zero=True)


def _set_release_calendar_fields(
    trade: SimulatedTradeModel,
    *,
    proof: OrderFillSettlementProof,
    released_at: datetime,
    release_session: date,
) -> None:
    """Attach the exact current calendar evidence to one newly released BUY row."""

    evidence = proof.calendar_evidence
    publication = evidence.publication
    if publication is None:
        raise _blocked("PENDING_SETTLEMENT_INVALID", "结算释放缺少正式日历发布")
    trade.settlement_status = "released"
    trade.settlement_released_at = released_at
    trade.settlement_release_session = release_session
    trade.settlement_release_calendar_snapshot_id = evidence.snapshot.snapshot_id
    trade.settlement_release_calendar_content_hash = evidence.snapshot.content_hash
    trade.settlement_release_calendar_record_digest = evidence.snapshot.record_digest
    trade.settlement_release_calendar_publication_id = publication.publication_id
    trade.settlement_release_calendar_publication_hash = publication.publication_hash
    trade.settlement_release_calendar_policy_hash = publication.policy_hash
    trade.settlement_release_calendar_evidence_hash = evidence.evidence_hash
    trade.settlement_release_calendar_timezone = publication.timezone_name


def _persist_pending_releases(
    *,
    rows: Sequence[SimulatedTradeModel],
    proof: OrderFillSettlementProof,
    now: datetime,
    current_session: date,
    using: str,
) -> None:
    """Record releases after every new-fill validation has succeeded."""

    for row in rows:
        _set_release_calendar_fields(
            row,
            proof=proof,
            released_at=now,
            release_session=current_session,
        )
        row.save(
            using=using,
            update_fields=[
                "settlement_status",
                "settlement_released_at",
                "settlement_release_session",
                "settlement_release_calendar_snapshot_id",
                "settlement_release_calendar_content_hash",
                "settlement_release_calendar_record_digest",
                "settlement_release_calendar_publication_id",
                "settlement_release_calendar_publication_hash",
                "settlement_release_calendar_policy_hash",
                "settlement_release_calendar_evidence_hash",
                "settlement_release_calendar_timezone",
            ],
        )


def _active_hold_totals(
    *,
    active_rows: list[SimulatedOrderReservationModel],
    reservation_row: SimulatedOrderReservationModel,
    chain: _LockedFillChain,
    using: str,
) -> tuple[Decimal, Decimal, Decimal, Decimal]:
    """Validate all locked account holds and isolate this order's remaining bucket."""

    active_values: list[PrecisionValue] = []
    for row in active_rows:
        prefix = "active_reservation"
        active_values.extend(
            (
                (f"{prefix}.quantity", row.quantity, "quantity"),
                (f"{prefix}.filled_quantity", row.filled_quantity, "quantity"),
                (f"{prefix}.shares_reserved", row.shares_reserved, "quantity"),
                (f"{prefix}.shares_consumed", row.shares_consumed, "quantity"),
                (f"{prefix}.shares_released", row.shares_released, "quantity"),
                (f"{prefix}.cash_reserved", row.cash_reserved, "money"),
                (f"{prefix}.cash_consumed", row.cash_consumed, "money"),
                (f"{prefix}.cash_released", row.cash_released, "money"),
            )
        )
        if row.fee_budget is not None:
            active_values.append((f"{prefix}.fee_budget", row.fee_budget, "money"))
    require_sqlite_values(
        values=tuple(active_values),
        using=using,
        error_code="ORDER_RESERVATION_STATE_INVALID",
    )
    total_cash, total_shares = active_order_reservation_holds(
        active_rows,
        account_id=reservation_row.account_id,
        owner_user_id=reservation_row.owner_user_id,
        security_id=reservation_row.security_id,
        asset_code=reservation_row.asset_code,
    )
    own_cash = chain.reservation.remaining_cash
    own_shares = chain.reservation.remaining_shares
    other_cash = _money_difference(total_cash, own_cash, "other_order_held_cash")
    other_shares = _quantity_difference(total_shares, own_shares, "other_order_held_shares")
    require_sqlite_values(
        values=(
            ("active_order_holds.cash", total_cash, "money"),
            ("active_order_holds.shares", total_shares, "quantity"),
            ("other_order_holds.cash", other_cash, "money"),
            ("other_order_holds.shares", other_shares, "quantity"),
        ),
        using=using,
        error_code="ORDER_RESERVATION_STATE_INVALID",
    )
    return total_cash, total_shares, other_cash, other_shares
