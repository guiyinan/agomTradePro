"""Locked account valuation, first-position, and T+0/T+1 settlement helpers."""

from __future__ import annotations

import logging
from collections.abc import Sequence
from datetime import date, datetime
from decimal import Decimal, localcontext

from django.db import DatabaseError

from apps.simulated_trading.application.execution_settlement_uow import (
    SimulatedTradeAccountScopeUnavailable,
    SimulatedTradeIdempotencyConflict,
)
from apps.simulated_trading.application.initial_position_mark import InitialPositionMarkReader
from apps.simulated_trading.application.order_reservation_fill import (
    LocalSimulatedFillEventKind,
    LocalSimulatedFillEventV1,
)
from apps.simulated_trading.domain.execution_settlement_primitives import (
    SimulatedSettlementContractError,
    _require_aware,
    _require_hash,
    _require_token,
    validate_ledger_money,
    validate_ledger_price,
    validate_ledger_quantity,
)
from apps.simulated_trading.domain.execution_settlement_uow import SimulatedTradeIntent
from apps.simulated_trading.domain.initial_position_mark import InitialPositionMarkProof
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
    _trade_settlement_bindings,
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
_logger = logging.getLogger(__name__)


def _validate_new_event(
    event: LocalSimulatedFillEventV1,
    *,
    using: str,
    reservation_row: SimulatedOrderReservationModel,
    chain: _LockedFillChain,
    proof: OrderFillSettlementProof,
    now: datetime,
    expected_event_payload_hash: str | None,
) -> None:
    """Bind a fresh event, its proof, and every owner/order identity to locks."""

    if event.event_kind is LocalSimulatedFillEventKind.UNKNOWN:
        _logger.warning(
            "Unknown local simulated fill kind blocked",
            extra={"code": "SIMULATED_FILL_EVENT_KIND_UNKNOWN"},
        )
        raise _blocked("SIMULATED_FILL_EVENT_KIND_UNKNOWN", "未知成交事件类型已阻止记账")
    if event.event_kind not in (
        LocalSimulatedFillEventKind.FILL,
        LocalSimulatedFillEventKind.FINAL_FILL,
    ):
        _logger.warning(
            "Unsupported local simulated fill kind blocked",
            extra={"code": "SIMULATED_FILL_EVENT_KIND_UNKNOWN"},
        )
        raise _blocked("SIMULATED_FILL_EVENT_KIND_UNKNOWN", "不支持的成交事件类型已阻止记账")
    if type(proof) is not OrderFillSettlementProof:
        raise _blocked("SIMULATED_FILL_CALENDAR_INVALID", "成交日历证明类型不受支持")
    try:
        proof.validate()
        proof.calendar_evidence.validate_for(now)
        if proof.calendar_read_cutoff > now:
            raise ValueError("calendar cutoff is later than the locked writer clock")
        _require_token(event.source_version, "source_version", max_length=128)
        _require_token(event.source_snapshot_id, "source_snapshot_id")
        _require_token(event.security_id, "security_id")
        _require_token(event.asset_code, "asset_code")
        for field_name, digest in (
            ("source_snapshot_hash", event.source_snapshot_hash),
            ("intent_payload_hash", event.intent_payload_hash),
            ("reservation_request_hash", event.reservation_request_hash),
            ("plan_snapshot_hash", event.plan_snapshot_hash),
        ):
            _require_hash(digest, field_name)
        for field_name, value in (
            ("occurred_at", event.occurred_at),
            ("source_observed_at", event.source_observed_at),
            ("source_available_at", event.source_available_at),
            ("recorded_at", event.recorded_at),
        ):
            _require_aware(value, field_name)
        validate_ledger_quantity(event.quantity, "fill_quantity", allow_zero=False)
        validate_ledger_price(event.price, "fill_price", allow_zero=False)
        require_sqlite_values(
            values=(
                ("fill_quantity", event.quantity, "quantity"),
                ("fill_price", event.price, "price"),
            ),
            using=using,
        )
    except (ArithmeticError, SimulatedSettlementContractError, TypeError, ValueError) as error:
        raise _blocked("SIMULATED_FILL_SOURCE_INVALID", "成交事件或日历证据不可验证") from error

    reservation = chain.reservation
    intent = chain.intent
    if (
        event.reservation_id != reservation_row.pk
        or event.account_id != reservation_row.account_id
        or event.user_id != reservation_row.owner_user_id
        or event.order_idempotency_key != reservation_row.idempotency_key
        or event.intent_payload_hash != reservation_row.intent_payload_hash
        or event.reservation_request_hash != reservation_row.reservation_request_hash
        or event.plan_snapshot_hash != reservation_row.plan_snapshot_hash
        or event.security_id != reservation_row.security_id
        or event.asset_code != reservation_row.asset_code
        or event.side is not reservation.side
        or intent.request_payload_hash != reservation_row.intent_payload_hash
        or intent.user_id != reservation_row.owner_user_id
        or intent.account_id != reservation_row.account_id
        or intent.idempotency_key != reservation_row.idempotency_key
        or intent.security_id != reservation_row.security_id
        or intent.asset_code != reservation_row.asset_code
    ):
        raise _blocked("SIMULATED_FILL_SOURCE_SCOPE_MISMATCH", "成交事件与锁定订单封存身份不符")
    if expected_event_payload_hash is not None:
        try:
            _require_hash(expected_event_payload_hash, "expected_event_payload_hash")
        except (ArithmeticError, SimulatedSettlementContractError, TypeError, ValueError) as error:
            raise _blocked("SIMULATED_FILL_SOURCE_INVALID", "调用方成交摘要格式无效") from error
        if event.event_payload_hash != expected_event_payload_hash:
            raise SimulatedTradeIdempotencyConflict("成交事件摘要与调用方已观察摘要不一致")
    settlement_bindings = _trade_settlement_bindings(
        reservation_row=reservation_row,
        intent=intent,
        as_of=now,
    )
    settlement_exchange = settlement_bindings.exchange
    settlement_lag_sessions = settlement_bindings.lag_sessions
    if (
        proof.fill_occurred_at != event.occurred_at
        or proof.settlement_exchange != settlement_exchange
        or proof.settlement_lag_sessions != settlement_lag_sessions
        or proof.calendar_evidence.snapshot.exchange != settlement_exchange
        or proof.fill_occurred_at < reservation.reserved_at
    ):
        raise _blocked("SIMULATED_FILL_CALENDAR_SCOPE_MISMATCH", "成交日历证明与订单封存范围不符")


def _lock_simulated_fill_account(
    *,
    account_id: int,
    user_id: int,
    using: str,
) -> SimulatedAccountModel:
    """Lock the owner-scoped simulated account parent before every child row."""

    account = (
        SimulatedAccountModel._base_manager.using(using)
        .select_for_update()
        .filter(pk=account_id, user_id=user_id, account_type="simulated")
        .first()
    )
    if account is None:
        raise SimulatedTradeAccountScopeUnavailable()
    return account


def _validate_locked_fill_owner(
    *,
    account: SimulatedAccountModel,
    reservation_row: SimulatedOrderReservationModel,
    event: LocalSimulatedFillEventV1,
) -> None:
    """Reject any account, owner or order-key mismatch before receipt decoding."""

    if (
        account.pk != event.account_id
        or account.user_id != event.user_id
        or account.account_type != "simulated"
        or reservation_row.account_id != event.account_id
        or reservation_row.owner_user_id != event.user_id
        or reservation_row.idempotency_key != event.order_idempotency_key
        or reservation_row.pk != event.reservation_id
    ):
        raise SimulatedTradeAccountScopeUnavailable()


def _read_initial_position_mark(
    *,
    reader: InitialPositionMarkReader | None,
    using: str,
    event: LocalSimulatedFillEventV1,
    intent: SimulatedTradeIntent,
    now: datetime,
) -> InitialPositionMarkProof:
    """Read an independently sourced mark for one missing BUY Position."""

    if reader is None:
        raise _blocked(
            "INITIAL_POSITION_MARK_UNAVAILABLE",
            "首次建立持仓没有配置独立估值来源，未记账",
        )
    try:
        proof = reader.read_initial_position_mark(
            security_id=intent.security_id,
            asset_code=intent.asset_code,
            asset_type=intent.asset_type,
            market=intent.market,
            board=intent.board,
            read_at=now,
        )
    except DatabaseError as error:
        raise _blocked(
            "INITIAL_POSITION_MARK_UNAVAILABLE",
            "首次建立持仓时无法读取独立估值来源，未记账",
        ) from error
    if type(proof) is not InitialPositionMarkProof:
        raise _blocked(
            "INITIAL_POSITION_MARK_UNAVAILABLE",
            "首次建立持仓没有返回可验证的估值证明，未记账",
        )
    try:
        proof.validate_for(intent=intent, read_at=now)
        _require_aware(event.recorded_at, "fill_event.recorded_at")
    except (
        ArithmeticError,
        SimulatedSettlementContractError,
        TypeError,
        ValueError,
    ) as error:
        raise _blocked(
            "INITIAL_POSITION_MARK_INVALID",
            "首次持仓估值证明与成交身份或读取时点不一致",
        ) from error
    if event.recorded_at > proof.read_at:
        raise _blocked(
            "INITIAL_POSITION_MARK_INVALID",
            "首次持仓估值读取早于成交事件记入时间",
        )
    require_sqlite_values(
        values=(("initial_position_mark.price", proof.price, "price"),),
        using=using,
    )
    return proof


def _signed_difference(left: Decimal, right: Decimal) -> Decimal:
    """Subtract nonnegative ledger values under a wide context for PnL output."""

    with localcontext() as context:
        context.prec = 80
        return left - right


def _quantity_sum(left: Decimal, right: Decimal) -> Decimal:
    """Add ledger shares at six-place precision regardless of ambient Decimal context."""

    with localcontext() as context:
        context.prec = 80
        total = left + right
    return validate_ledger_quantity(total, "ledger.quantity_sum", allow_zero=True)


def _insert_initial_position(
    *,
    account: SimulatedAccountModel,
    asset_code: str,
    asset_name: str,
    asset_type: str,
    quantity: Decimal,
    available_quantity: Decimal,
    average_cost: Decimal,
    total_cost: Decimal,
    mark_price: Decimal,
    market_value: Decimal,
    unrealized_pnl: Decimal,
    unrealized_pnl_pct: float,
    first_buy_date: date,
    signal_id: int | None,
    entry_reason: str,
    using: str,
) -> PositionModel:
    """Insert a newly established, independently marked position exactly once."""

    return PositionModel._base_manager.using(using).create(
        account=account,
        asset_code=asset_code,
        asset_name=asset_name,
        asset_type=asset_type,
        quantity=quantity,
        available_quantity=available_quantity,
        available_quantity_known=True,
        avg_cost=average_cost,
        total_cost=total_cost,
        cost_basis_known=True,
        current_price=mark_price,
        market_value=market_value,
        valuation_known=True,
        unrealized_pnl=unrealized_pnl,
        unrealized_pnl_pct=unrealized_pnl_pct,
        first_buy_date=first_buy_date,
        first_buy_date_known=True,
        signal_id=signal_id,
        entry_reason=entry_reason,
    )


def _account_positions_snapshot(
    *,
    account: SimulatedAccountModel,
    positions: Sequence[PositionModel],
    asset_code: str,
    using: str,
    allow_missing_target: bool = False,
) -> tuple[PositionModel | None, Decimal, Decimal]:
    """Validate the marked account aggregate and return its optional target row."""

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
    if target is None and not allow_missing_target:
        raise _blocked("POSITION_REQUIRED", "成交写入需要已有的已知估值持仓")
    if target is None:
        return None, cash, aggregate
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
