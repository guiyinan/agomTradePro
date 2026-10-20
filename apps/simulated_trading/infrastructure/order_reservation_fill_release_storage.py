"""Lock and validate complete V4 fill chains before settling their BUY shares."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal, localcontext
from typing import cast

from django.db.models import QuerySet

from apps.simulated_trading.application.execution_settlement_uow import (
    SimulatedTradeExecutionBlocked,
)
from apps.simulated_trading.domain.execution_settlement_calendar import (
    ExecutionCalendarEvidence,
)
from apps.simulated_trading.domain.execution_settlement_identity import (
    PendingSettlementScopeV1,
)
from apps.simulated_trading.domain.execution_settlement_primitives import (
    SimulatedSettlementContractError,
)
from apps.simulated_trading.domain.execution_settlement_uow import (
    validate_ledger_quantity,
)
from apps.simulated_trading.domain.order_reservation_fill_release import (
    OrderFillSettlementReleaseProof,
)
from apps.simulated_trading.infrastructure.execution_settlement_plan_binding_repository import (
    pending_settlement_source_exchange as _pending_settlement_source_exchange,
)
from apps.simulated_trading.infrastructure.order_fill_receipt_models import (
    SimulatedOrderFillReceiptModel,
)
from apps.simulated_trading.infrastructure.order_reservation_fill_chain_storage import (
    _blocked,
    _locked_fill_chain,
)
from apps.simulated_trading.infrastructure.order_reservation_fill_release_codec import (
    EncodedOrderFillSettlementReleaseProof,
    encode_order_fill_settlement_release_proof,
)
from apps.simulated_trading.infrastructure.order_reservation_fill_row_reader import (
    DecodedOrderReservationFillRow,
)
from apps.simulated_trading.infrastructure.order_reservation_models import (
    SimulatedOrderReservationModel,
)
from apps.simulated_trading.infrastructure.simulated_account_trade_models import (
    PositionModel,
    SimulatedAccountModel,
    SimulatedTradeModel,
)


@dataclass(frozen=True, slots=True)
class LockedV4PendingFill:
    """Carry one scoped V4 pending Trade and its fully validated source chain."""

    trade: SimulatedTradeModel
    receipt: SimulatedOrderFillReceiptModel
    reservation: SimulatedOrderReservationModel
    decoded: DecodedOrderReservationFillRow


def lock_v4_pending_fill_chains(
    *,
    account: SimulatedAccountModel,
    asset_code: str,
    pending_candidates: Sequence[SimulatedTradeModel],
    using: str,
) -> tuple[LockedV4PendingFill, ...]:
    """Lock owner-scoped parents and validate every pending V4 receipt prefix.

    The caller must already hold the account parent lock and active-reservation
    locks. Candidate rows are locator data only; reservation ownership and the
    complete immutable receipt/Trade/FeeV2 chain are re-read under row locks.
    """

    if type(account) is not SimulatedAccountModel:
        raise _blocked("SIMULATED_FILL_RECEIPT_CHAIN_INVALID", "模拟账户锁类型不可验证")
    if type(account.pk) is not int or type(account.user_id) is not int:
        raise _blocked("SIMULATED_FILL_RECEIPT_CHAIN_INVALID", "模拟账户所有权不可验证")
    if type(asset_code) is not str or not asset_code or type(using) is not str or not using:
        raise _blocked("SIMULATED_FILL_RECEIPT_CHAIN_INVALID", "待结算范围不可验证")

    v4_candidates: dict[int, SimulatedTradeModel] = {}
    for candidate in pending_candidates:
        if type(candidate) is not SimulatedTradeModel or type(candidate.pk) is not int:
            raise _blocked("SIMULATED_FILL_RECEIPT_CHAIN_INVALID", "待结算行类型不可验证")
        version = candidate.settlement_plan_binding_version
        if type(version) is not int:
            raise _blocked("SIMULATED_FILL_RECEIPT_CHAIN_INVALID", "待结算版本不可验证")
        if version != 4:
            continue
        if (
            candidate.account_id != account.pk
            or candidate.asset_code != asset_code
            or candidate.action != "buy"
            or candidate.settlement_status != "pending"
            or candidate.pk in v4_candidates
        ):
            raise _blocked("SIMULATED_FILL_RECEIPT_CHAIN_INVALID", "V4待结算定位身份冲突")
        v4_candidates[candidate.pk] = candidate
    if not v4_candidates:
        return ()

    locator_rows = cast(
        list[tuple[int, int]],
        list(
            SimulatedOrderFillReceiptModel._base_manager.using(using)
            .filter(trade_id__in=tuple(sorted(v4_candidates)))
            .order_by("trade_id", "pk")
            .values_list("trade_id", "reservation_id")
        ),
    )
    reservation_by_trade: dict[int, int] = {}
    for trade_id, reservation_id in locator_rows:
        if type(trade_id) is not int or type(reservation_id) is not int:
            raise _blocked("SIMULATED_FILL_RECEIPT_CHAIN_INVALID", "V4回执定位字段不可验证")
        if trade_id in reservation_by_trade:
            raise _blocked("SIMULATED_FILL_RECEIPT_CHAIN_INVALID", "V4交易存在重复回执")
        reservation_by_trade[trade_id] = reservation_id
    if set(reservation_by_trade) != set(v4_candidates):
        raise _blocked("SIMULATED_FILL_RECEIPT_CHAIN_INVALID", "V4待结算交易缺少唯一回执")

    reservation_ids = tuple(sorted(set(reservation_by_trade.values())))
    reservations = list(
        SimulatedOrderReservationModel._base_manager.using(using)
        .select_for_update()
        .filter(
            pk__in=reservation_ids,
            account_id=account.pk,
            owner_user_id=account.user_id,
        )
        .order_by("pk")
    )
    reservations_by_id = {row.pk: row for row in reservations}
    if set(reservations_by_id) != set(reservation_ids):
        raise _blocked("SIMULATED_FILL_RECEIPT_CHAIN_INVALID", "V4回执订单不属于当前账户")

    entries_by_trade: dict[int, LockedV4PendingFill] = {}
    for reservation_id in reservation_ids:
        reservation_row = reservations_by_id[reservation_id]
        chain = _locked_fill_chain(reservation_row=reservation_row, using=using)
        for receipt_row, decoded in chain.rows:
            trade_id = decoded.trade_id
            if trade_id not in v4_candidates:
                continue
            trade = receipt_row.trade
            candidate = v4_candidates[trade_id]
            if (
                receipt_row.reservation_id != reservation_id
                or trade.pk != candidate.pk
                or trade.account_id != account.pk
                or trade.asset_code != asset_code
                or trade.action != "buy"
                or trade.settlement_status != "pending"
                or trade.settlement_plan_binding_version != 4
                or reservation_by_trade[trade_id] != reservation_id
            ):
                raise _blocked("SIMULATED_FILL_RECEIPT_CHAIN_INVALID", "V4完整链与待结算行不一致")
            entries_by_trade[trade_id] = LockedV4PendingFill(
                trade=trade,
                receipt=receipt_row,
                reservation=reservation_row,
                decoded=decoded,
            )
    if set(entries_by_trade) != set(v4_candidates):
        raise _blocked("SIMULATED_FILL_RECEIPT_CHAIN_INVALID", "V4完整链未包含待结算交易")
    return tuple(entries_by_trade[key] for key in sorted(entries_by_trade))


def encode_due_v4_release_proofs(
    *,
    entries: Sequence[LockedV4PendingFill],
    evidence: ExecutionCalendarEvidence,
    released_at: datetime,
    release_session: date,
) -> dict[int, EncodedOrderFillSettlementReleaseProof]:
    """Seal proofs only for due rows after validating the entire candidate batch."""

    if type(evidence) is not ExecutionCalendarEvidence:
        raise _blocked("SIMULATED_FILL_CALENDAR_INVALID", "结算释放日历类型无效")
    try:
        evidence.validate_for(released_at)
        if evidence.current_open_session(released_at) != release_session:
            raise ValueError("release session differs from the locked release clock")
        encoded: dict[int, EncodedOrderFillSettlementReleaseProof] = {}
        for entry in entries:
            trade = entry.trade
            decoded = entry.decoded
            if (
                type(trade.pk) is not int
                or type(trade.settlement_market_session) is not date
                or type(trade.settlement_lag_sessions) is not int
                or trade.settlement_lag_sessions < 0
                or type(trade.settlement_exchange) is not str
                or type(trade.settlement_security_id) is not str
            ):
                raise ValueError("pending V4 trade settlement identity is invalid")
            elapsed = evidence.elapsed_open_sessions(
                trade.settlement_market_session,
                release_session,
            )
            if elapsed < trade.settlement_lag_sessions:
                continue
            event = decoded.event
            original_proof = decoded.proof
            if (
                released_at < event.occurred_at
                or released_at < event.recorded_at
                or released_at < trade.execution_time
                or released_at < original_proof.calendar_read_cutoff
            ):
                raise ValueError("release clock precedes a durable fill event or its evidence")
            proof = OrderFillSettlementReleaseProof(
                trade_id=trade.pk,
                reservation_id=entry.reservation.pk,
                account_id=trade.account_id,
                user_id=entry.reservation.owner_user_id,
                receipt_hash=entry.receipt.receipt_hash,
                security_id=trade.settlement_security_id,
                settlement_exchange=trade.settlement_exchange,
                fill_market_session=trade.settlement_market_session,
                settlement_lag_sessions=trade.settlement_lag_sessions,
                released_at=released_at,
                release_session=release_session,
                calendar_evidence=evidence,
            )
            encoded[trade.pk] = encode_order_fill_settlement_release_proof(proof)
        return encoded
    except SimulatedTradeExecutionBlocked:
        raise
    except (
        ArithmeticError,
        AttributeError,
        SimulatedSettlementContractError,
        TypeError,
        ValueError,
    ) as error:
        raise _blocked("SIMULATED_FILL_CALENDAR_INVALID", "V4结算释放证明无法验证") from error


def require_v4_pending_chain_match(
    *,
    pending_rows: Sequence[SimulatedTradeModel],
    entries: Sequence[LockedV4PendingFill],
) -> None:
    """Reject any change between the locked chain locator and pending-row lock."""

    pending_ids: set[int] = set()
    for row in pending_rows:
        if type(row) is not SimulatedTradeModel or type(row.pk) is not int:
            raise _blocked("SIMULATED_FILL_RECEIPT_CHAIN_INVALID", "待结算交易行类型不可验证")
        version = row.settlement_plan_binding_version
        if type(version) is not int:
            raise _blocked("SIMULATED_FILL_RECEIPT_CHAIN_INVALID", "待结算版本不可验证")
        if version == 4:
            if row.pk in pending_ids:
                raise _blocked("SIMULATED_FILL_RECEIPT_CHAIN_INVALID", "V4待结算交易重复")
            pending_ids.add(row.pk)
    chain_ids = {entry.trade.pk for entry in entries}
    if chain_ids != pending_ids:
        raise _blocked("SIMULATED_FILL_RECEIPT_CHAIN_INVALID", "V4待结算交易与完整链集合不一致")


def set_release_proof_fields(
    *,
    trade: SimulatedTradeModel,
    encoded: EncodedOrderFillSettlementReleaseProof,
) -> None:
    """Attach one exact already-validated proof pair to its matching Trade row."""

    proof = encoded.proof
    if (
        type(trade) is not SimulatedTradeModel
        or type(trade.pk) is not int
        or proof.trade_id != trade.pk
        or proof.account_id != trade.account_id
        or proof.security_id != trade.settlement_security_id
        or proof.settlement_exchange != trade.settlement_exchange
        or proof.fill_market_session != trade.settlement_market_session
        or proof.settlement_lag_sessions != trade.settlement_lag_sessions
    ):
        raise _blocked("SIMULATED_FILL_RECEIPT_CHAIN_INVALID", "V4释放证明与交易行不匹配")
    trade.settlement_release_proof_payload = encoded.to_payload()
    trade.settlement_release_proof_hash = encoded.proof_hash


def _get_pending_settlement_scope(
    *,
    using: str,
    account_id: int,
    user_id: int,
    asset_code: str,
) -> PendingSettlementScopeV1 | None:
    """Return the validated earliest session and original source exchange."""

    rows = list(
        SimulatedTradeModel._default_manager.using(using)
        .select_related("account")
        .filter(
            account_id=account_id,
            account__user_id=user_id,
            asset_code=asset_code,
            action="buy",
            settlement_status="pending",
        )
        .order_by("settlement_market_session", "pk")
    )
    return _pending_scope_for_rows(rows)


def _locked_pending_rows(
    *, using: str, account_id: int, asset_code: str
) -> list[SimulatedTradeModel]:
    """Acquire third-order pending-fill locks in deterministic date/PK order."""

    rows: QuerySet[SimulatedTradeModel] = (
        SimulatedTradeModel._default_manager.using(using)
        .select_for_update()
        .filter(
            account_id=account_id,
            asset_code=asset_code,
            action="buy",
            settlement_status="pending",
        )
        .order_by("settlement_market_session", "pk")
    )
    return list(rows)


def _pending_candidates(
    *, using: str, account_id: int, asset_code: str
) -> list[SimulatedTradeModel]:
    """Read account/security pending BUY locators before locking their fill chains."""

    rows: QuerySet[SimulatedTradeModel] = (
        SimulatedTradeModel._default_manager.using(using)
        .filter(
            account_id=account_id,
            asset_code=asset_code,
            action="buy",
            settlement_status="pending",
        )
        .order_by("settlement_market_session", "pk")
    )
    return list(rows)


def _pending_scope_for_rows(
    rows: list[SimulatedTradeModel],
) -> PendingSettlementScopeV1 | None:
    """Validate every pending receipt and derive one unambiguous source scope."""

    if not rows:
        return None
    sessions: list[date] = []
    exchanges: set[str] = set()
    for row in rows:
        session = row.settlement_market_session
        if type(session) is not date:
            raise SimulatedTradeExecutionBlocked(
                "pending settlement is missing its original market session"
            )
        sessions.append(session)
        exchanges.add(_pending_settlement_source_exchange(row))
    if len(exchanges) != 1:
        raise SimulatedTradeExecutionBlocked(
            "pending settlements contain multiple original source exchanges"
        )
    exchange = next(iter(exchanges))
    try:
        return PendingSettlementScopeV1(min(sessions), exchange)
    except (ArithmeticError, TypeError, ValueError) as error:
        raise SimulatedTradeExecutionBlocked(
            "pending settlement scope failed exact validation"
        ) from error


def _release_pending_rows(
    *,
    using: str,
    position: PositionModel | None,
    pending_rows: list[SimulatedTradeModel],
    active_held_shares: Decimal,
    evidence: ExecutionCalendarEvidence,
    through_session: date,
    released_at: datetime,
    v4_release_proofs: Mapping[int, EncodedOrderFillSettlementReleaseProof],
) -> tuple[PositionModel | None, int]:
    """Release only rows whose stored lag elapsed under this complete current snapshot."""

    # Validate the complete locked batch before changing any available-share
    # value. Version 0 is the explicit pre-binding/legacy state and cannot
    # prove which original plan authorized a pending release.
    for row in pending_rows:
        if _pending_settlement_source_exchange(row) != evidence.snapshot.exchange:
            raise SimulatedTradeExecutionBlocked(
                "current calendar exchange differs from the frozen trade source exchange"
            )

    if pending_rows and position is None:
        raise SimulatedTradeExecutionBlocked(
            "pending settlement exists without its account/security position"
        )
    if position is not None:
        if position.valuation_known is not True:
            raise SimulatedTradeExecutionBlocked(
                "position valuation is unknown", code="POSITION_VALUATION_UNKNOWN"
            )
        if position.available_quantity_known is not True:
            raise SimulatedTradeExecutionBlocked(
                "position sellable quantity is unknown",
                code="SELLABLE_BALANCE_UNKNOWN",
            )
        quantity = validate_ledger_quantity(position.quantity, "position.quantity")
        available = validate_ledger_quantity(
            position.available_quantity,
            "position.available_quantity",
        )
        held_shares = validate_ledger_quantity(
            active_held_shares,
            "active_order_holds.shares",
            allow_zero=True,
        )
        if available > quantity:
            raise SimulatedTradeExecutionBlocked(
                "available position quantity exceeds the recorded total quantity"
            )
        if held_shares > available:
            raise SimulatedTradeExecutionBlocked(
                "active sell reservations exceed the locked sellable balance",
                code="ORDER_RESERVATION_STATE_INVALID",
            )
        pending_quantity = Decimal("0.000000")
        with localcontext() as context:
            context.prec = 80
            for pending_row in pending_rows:
                pending_quantity += validate_ledger_quantity(
                    pending_row.quantity,
                    "pending_trade.quantity",
                )
            available_and_pending = validate_ledger_quantity(
                available + pending_quantity,
                "position.available_plus_pending_quantity",
                allow_zero=True,
            )
        if available_and_pending > quantity:
            raise SimulatedTradeExecutionBlocked(
                "available and pending position quantities exceed the recorded total",
                code="PENDING_SETTLEMENT_INVALID",
            )
    released_rows: list[SimulatedTradeModel] = []
    next_available = (
        validate_ledger_quantity(position.available_quantity, "position.available_quantity")
        if position is not None
        else Decimal("0.000000")
    )
    publication = evidence.publication
    if publication is None:
        raise SimulatedTradeExecutionBlocked(
            "settlement release requires a formal calendar publication binding"
        )
    for row in pending_rows:
        trade_session = row.settlement_market_session
        lag = row.settlement_lag_sessions
        if type(trade_session) is not date or type(lag) is not int or lag < 0:
            raise SimulatedTradeExecutionBlocked(
                "pending trade lacks its immutable original settlement lag/session"
            )
        expected_exchange = (
            row.settlement_market
            if row.settlement_plan_binding_version == 1
            else row.settlement_exchange
        )
        if expected_exchange != evidence.snapshot.exchange:
            raise SimulatedTradeExecutionBlocked(
                "current calendar exchange differs from the frozen trade source exchange"
            )
        try:
            elapsed = evidence.elapsed_open_sessions(trade_session, through_session)
        except (ArithmeticError, TypeError, ValueError) as error:
            raise SimulatedTradeExecutionBlocked(
                "current calendar does not prove the original settlement interval"
            ) from error
        if elapsed < lag:
            continue
        assert position is not None
        trade_quantity = validate_ledger_quantity(row.quantity, "pending_trade.quantity")
        total_quantity = validate_ledger_quantity(position.quantity, "position.quantity")
        next_available = validate_ledger_quantity(
            next_available + trade_quantity,
            "position.available_quantity_after_release",
        )
        if next_available > total_quantity:
            raise SimulatedTradeExecutionBlocked(
                "releasing a pending trade would exceed the total recorded quantity"
            )
        if row.settlement_plan_binding_version == 4:
            encoded = v4_release_proofs.get(row.pk)
            if encoded is None:
                raise SimulatedTradeExecutionBlocked(
                    "due V4 fill is missing its validated release proof",
                    code="SIMULATED_FILL_RECEIPT_CHAIN_INVALID",
                )
            set_release_proof_fields(trade=row, encoded=encoded)
        elif row.pk in v4_release_proofs:
            raise SimulatedTradeExecutionBlocked(
                "legacy pending trade received a V4 release proof",
                code="SIMULATED_FILL_RECEIPT_CHAIN_INVALID",
            )
        row.settlement_status = "released"
        row.settlement_released_at = released_at
        row.settlement_release_session = through_session
        _set_release_evidence(row, evidence)
        released_rows.append(row)
    expected_v4_proof_ids = {
        row.pk for row in released_rows if row.settlement_plan_binding_version == 4
    }
    if expected_v4_proof_ids != set(v4_release_proofs):
        raise SimulatedTradeExecutionBlocked(
            "V4 release proof set differs from the due pending rows",
            code="SIMULATED_FILL_RECEIPT_CHAIN_INVALID",
        )
    if not released_rows:
        return position, 0

    assert position is not None
    position.available_quantity = next_available
    position.save(using=using, update_fields=["available_quantity", "last_update_date"])
    update_fields = [
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
    ]
    for row in released_rows:
        row_update_fields = list(update_fields)
        if row.settlement_plan_binding_version == 4:
            row_update_fields.extend(
                ["settlement_release_proof_payload", "settlement_release_proof_hash"]
            )
        row.save(using=using, update_fields=row_update_fields)
    return position, len(released_rows)


def _set_release_evidence(row: SimulatedTradeModel, evidence: ExecutionCalendarEvidence) -> None:
    """Save the actual release proof separately from the buy-time forecast."""

    publication = evidence.publication
    if publication is None:
        raise SimulatedTradeExecutionBlocked("calendar release proof has no publication")
    row.settlement_release_calendar_snapshot_id = evidence.snapshot.snapshot_id
    row.settlement_release_calendar_content_hash = evidence.snapshot.content_hash
    row.settlement_release_calendar_record_digest = evidence.snapshot.record_digest
    row.settlement_release_calendar_publication_id = publication.publication_id
    row.settlement_release_calendar_publication_hash = publication.publication_hash
    row.settlement_release_calendar_policy_hash = publication.policy_hash
    row.settlement_release_calendar_evidence_hash = evidence.evidence_hash
    row.settlement_release_calendar_timezone = publication.timezone_name


__all__: tuple[str, ...] = (
    "LockedV4PendingFill",
    "encode_due_v4_release_proofs",
    "lock_v4_pending_fill_chains",
    "require_v4_pending_chain_match",
    "set_release_proof_fields",
)
