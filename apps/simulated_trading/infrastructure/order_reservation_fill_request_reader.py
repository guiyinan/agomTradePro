"""Read exact persisted fill receipts before resolving a new order context.

This adapter is deliberately read-only. It neither reads a fill source nor
consults a clock/calendar, and it does not lock rows. The atomic writer must
repeat the event lookup and all mutable-state checks under its account lock.
"""

from __future__ import annotations

from django.core.exceptions import ObjectDoesNotExist
from django.db import DEFAULT_DB_ALIAS

from apps.simulated_trading.application.execution_settlement_uow import (
    SimulatedTradeExecutionBlocked,
    SimulatedTradeExecutionInputError,
)
from apps.simulated_trading.application.order_reservation_fill import (
    ExistingOrderFill,
    FillRequestDisposition,
    OrderFillContext,
    SimulatedOrderFillResult,
)
from apps.simulated_trading.domain.execution_settlement_primitives import (
    SimulatedSettlementContractError,
    _hash_payload,
    _require_hash,
    _require_token,
)
from apps.simulated_trading.infrastructure.order_fill_receipt_models import (
    SimulatedOrderFillReceiptModel,
)
from apps.simulated_trading.infrastructure.order_reservation_codec import (
    decode_order_reservation,
    json_object,
    validated_plan_snapshot,
)
from apps.simulated_trading.infrastructure.order_reservation_fill_row_reader import (
    DecodedOrderReservationFillRow,
    read_order_reservation_fill_row,
)
from apps.simulated_trading.infrastructure.order_reservation_models import (
    SimulatedOrderReservationModel,
)
from apps.simulated_trading.infrastructure.simulated_account_trade_models import (
    SimulatedAccountModel,
)

_ORDER_KEY_MAX_LENGTH = 128
_SOURCE_NAMESPACE_MAX_LENGTH = 128
_FILL_EVENT_ID_MAX_LENGTH = 128
_PLAN_CALENDAR_FIELDS = frozenset({"snapshot", "publication", "evidence_hash"})


def _blocked(code: str, message: str) -> SimulatedTradeExecutionBlocked:
    """Build a stable business error for unreadable or inconsistent stored rows."""

    return SimulatedTradeExecutionBlocked(message, code=code)


def _validate_locator(
    *,
    account_id: int,
    user_id: int,
    order_idempotency_key: str,
    source_namespace: str,
    fill_event_id: str,
) -> None:
    """Reject malformed locator values before any owner-scoped ORM query."""

    if type(account_id) is not int or account_id <= 0 or type(user_id) is not int or user_id <= 0:
        raise SimulatedTradeExecutionInputError("账户及所有者必须为有效标识")
    try:
        _require_token(
            order_idempotency_key,
            "order_idempotency_key",
            max_length=_ORDER_KEY_MAX_LENGTH,
        )
        _require_token(
            source_namespace,
            "source_namespace",
            max_length=_SOURCE_NAMESPACE_MAX_LENGTH,
        )
        _require_token(
            fill_event_id,
            "fill_event_id",
            max_length=_FILL_EVENT_ID_MAX_LENGTH,
        )
    except (ArithmeticError, TypeError, ValueError) as error:
        raise SimulatedTradeExecutionInputError("成交事件定位无效") from error


def _settlement_scope(
    row: SimulatedOrderReservationModel,
) -> tuple[str, int]:
    """Return exchange and lag only from the revalidated, sealed plan evidence."""

    snapshot = validated_plan_snapshot(row)
    try:
        raw_calendar = json_object(snapshot.get("calendar_evidence"), "calendar evidence")
        if set(raw_calendar) != _PLAN_CALENDAR_FIELDS:
            raise ValueError("sealed calendar evidence fields are incomplete or unknown")
        raw_snapshot = json_object(raw_calendar.get("snapshot"), "calendar snapshot")
        publication = json_object(raw_calendar.get("publication"), "calendar publication")
        snapshot_id = raw_snapshot.get("snapshot_id")
        exchange = raw_snapshot.get("exchange")
        member_id = publication.get("member_id")
        evidence_hash = raw_calendar.get("evidence_hash")
        if type(snapshot_id) is not str or not snapshot_id:
            raise ValueError("calendar snapshot identity is invalid")
        if type(exchange) is not str or not exchange:
            raise ValueError("calendar exchange is invalid")
        if type(member_id) is not str or member_id != snapshot_id:
            raise ValueError("calendar publication is not bound to its snapshot")
        _require_token(exchange, "settlement_exchange")
        _require_hash(evidence_hash, "calendar_evidence_hash")
        expected_evidence_hash = _hash_payload(
            {"snapshot": raw_snapshot, "publication": publication}
        )
        if evidence_hash != expected_evidence_hash:
            raise ValueError("calendar evidence seal differs from its stored members")
        lag = snapshot.get("settlement_lag_sessions")
        if type(lag) is not int or lag < 0:
            raise ValueError("settlement lag is not an exact nonnegative integer")
        if type(row.settlement_lag_sessions) is not int or row.settlement_lag_sessions != lag:
            raise ValueError("settlement lag differs from the reservation column")
    except SimulatedTradeExecutionBlocked:
        raise
    except (ArithmeticError, AttributeError, TypeError, ValueError) as error:
        raise _blocked(
            "ORDER_RESERVATION_SNAPSHOT_INVALID",
            "订单封存的交易所或结算规则不可验证",
        ) from error
    return exchange, lag


class DjangoSimulatedOrderFillRequestReader:
    """Resolve persisted receipts and active account contexts without writes."""

    def __init__(self, *, using: str = DEFAULT_DB_ALIAS) -> None:
        """Select the Django database alias used for owner-scoped reads."""

        if type(using) is not str or not using:
            raise SimulatedTradeExecutionInputError("模拟订单回执读取数据库别名无效")
        self._using = using

    def resolve_fill_request(
        self,
        *,
        account_id: int,
        user_id: int,
        order_idempotency_key: str,
        source_namespace: str,
        fill_event_id: str,
    ) -> FillRequestDisposition:
        """Return an exact saved event first, or a validated context for a new event.

        Receipt replay remains available for an inactive simulated account and a
        terminal order. A miss needs an active account; terminal reservation
        state is returned unchanged so the Application can block before source
        or calendar access. The eventual writer must re-read under its lock.
        """

        _validate_locator(
            account_id=account_id,
            user_id=user_id,
            order_idempotency_key=order_idempotency_key,
            source_namespace=source_namespace,
            fill_event_id=fill_event_id,
        )
        reservation_rows = list(
            SimulatedOrderReservationModel.objects.using(self._using)
            .select_related("account")
            .filter(
                account_id=account_id,
                owner_user_id=user_id,
                idempotency_key=order_idempotency_key,
                account__user_id=user_id,
                account__account_type="simulated",
            )
            .order_by("pk")
        )
        if not reservation_rows:
            return None
        if len(reservation_rows) != 1:
            raise _blocked(
                "ORDER_RESERVATION_STATE_INVALID",
                "账户中的订单幂等身份不唯一",
            )
        reservation_row = reservation_rows[0]
        account = reservation_row.account
        if type(account) is not SimulatedAccountModel:
            raise _blocked("SIMULATED_ACCOUNT_SCOPE_INVALID", "订单账户类型不可验证")
        if (
            account.pk != account_id
            or account.user_id != user_id
            or account.account_type != "simulated"
            or reservation_row.owner_user_id != user_id
        ):
            return None
        if type(account.is_active) is not bool:
            raise _blocked("SIMULATED_ACCOUNT_SCOPE_INVALID", "模拟账户状态不可验证")

        receipt_rows = list(
            SimulatedOrderFillReceiptModel.objects.using(self._using)
            .select_related("trade")
            .filter(
                reservation_id=reservation_row.pk,
                source_namespace=source_namespace,
                source_event_id=fill_event_id,
            )
            .order_by("pk")
        )
        if len(receipt_rows) > 1:
            raise _blocked(
                "SIMULATED_FILL_RECEIPT_INVALID",
                "同一订单成交定位对应多条持久回执",
            )
        if receipt_rows:
            return self._read_existing_receipt(reservation_row, receipt_rows[0])
        if account.is_active is not True:
            return None
        return self._new_order_context(reservation_row)

    def _read_existing_receipt(
        self,
        reservation_row: SimulatedOrderReservationModel,
        receipt_row: SimulatedOrderFillReceiptModel,
    ) -> ExistingOrderFill:
        """Strictly decode one exact receipt and return its immutable replay result."""

        current_reservation = decode_order_reservation(reservation_row)
        try:
            decoded = read_order_reservation_fill_row(
                reservation_row=reservation_row,
                receipt_row=receipt_row,
                trade_row=receipt_row.trade,
            )
            if type(decoded) is not DecodedOrderReservationFillRow:
                raise SimulatedSettlementContractError("fill row reader returned an unknown type")
            if (
                type(receipt_row.pk) is not int
                or type(receipt_row.trade_id) is not int
                or decoded.reservation_id != reservation_row.pk
                or decoded.receipt_id != receipt_row.pk
                or decoded.trade_id != receipt_row.trade_id
                or decoded.event.source_namespace != receipt_row.source_namespace
                or decoded.event.source_event_id != receipt_row.source_event_id
                or decoded.event.source_version != receipt_row.source_version
                or decoded.event.account_id != reservation_row.account_id
                or decoded.event.user_id != reservation_row.owner_user_id
                or decoded.event.order_idempotency_key != reservation_row.idempotency_key
                or decoded.economics.reservation_identity.account_id != reservation_row.account_id
            ):
                raise SimulatedSettlementContractError(
                    "decoded fill receipt differs from its exact persisted locator"
                )
            result = SimulatedOrderFillResult(
                reservation_id=decoded.reservation_id,
                source_namespace=decoded.event.source_namespace,
                source_version=decoded.event.source_version,
                event_payload_hash=decoded.event.event_payload_hash,
                economics=decoded.economics,
                reservation=current_reservation,
                trade_id=decoded.trade_id,
                replayed=True,
            )
            return ExistingOrderFill(result=result)
        except SimulatedTradeExecutionBlocked:
            raise
        except (
            ArithmeticError,
            AttributeError,
            ObjectDoesNotExist,
            TypeError,
            ValueError,
        ) as error:
            raise _blocked(
                "SIMULATED_FILL_RECEIPT_INVALID",
                "已存成交回执无法与原交易及订单封存数据精确核对",
            ) from error

    def _new_order_context(
        self,
        reservation_row: SimulatedOrderReservationModel,
    ) -> OrderFillContext:
        """Return a current active-owner snapshot after strict parent validation."""

        reservation = decode_order_reservation(reservation_row)
        settlement_exchange, settlement_lag = _settlement_scope(reservation_row)
        reservation_id = reservation_row.pk
        if (
            type(reservation_id) is not int
            or type(reservation_row.account_id) is not int
            or type(reservation_row.owner_user_id) is not int
            or type(reservation_row.asset_code) is not str
            or type(reservation_row.intent_payload_hash) is not str
            or type(reservation_row.plan_snapshot_hash) is not str
        ):
            raise _blocked("ORDER_RESERVATION_STATE_INVALID", "订单封存身份不完整")
        return OrderFillContext(
            reservation_id=reservation_id,
            account_id=reservation_row.account_id,
            owner_user_id=reservation_row.owner_user_id,
            order_idempotency_key=reservation_row.idempotency_key,
            reservation=reservation,
            asset_code=reservation_row.asset_code,
            intent_payload_hash=reservation_row.intent_payload_hash,
            plan_snapshot_hash=reservation_row.plan_snapshot_hash,
            settlement_exchange=settlement_exchange,
            settlement_lag_sessions=settlement_lag,
        )


__all__: tuple[str, ...] = ("DjangoSimulatedOrderFillRequestReader",)
