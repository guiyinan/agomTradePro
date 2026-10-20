"""Orchestrate one owner-scoped fill from an injected durable local matcher.

This Application layer never creates or guesses a fill event. A source binding
must be installed by a future composition root for an actual durable matcher;
the event's own namespace, version, hashes, and timestamps do not establish
that qualification. The repository remains responsible for locking, sealed
plan revalidation, exact-event re-read, and atomic ledger persistence.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, replace
from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from typing import Protocol, TypeAlias

from apps.simulated_trading.application.execution_settlement_uow import (
    SimulatedTradeAccountScopeUnavailable,
    SimulatedTradeExecutionBlocked,
    SimulatedTradeExecutionClock,
    SimulatedTradeExecutionInputError,
    SimulatedTradeExecutionResultUnknown,
    SimulatedTradeIdempotencyConflict,
    _require_aware_clock,
)
from apps.simulated_trading.domain.execution_settlement_primitives import (
    SimulatedSettlementContractError,
    _require_aware,
    _require_hash,
    _require_token,
    validate_ledger_price,
    validate_ledger_quantity,
)
from apps.simulated_trading.domain.execution_settlement_uow import SimulatedTradeSide
from apps.simulated_trading.domain.order_reservation import (
    OrderReservation,
    OrderReservationStatus,
)
from apps.simulated_trading.domain.order_reservation_fill import OrderReservationFillEconomics
from apps.simulated_trading.domain.order_reservation_fill_settlement import (
    OrderFillSettlementProof,
)

_logger = logging.getLogger(__name__)
_FILL_EVENT_ID_MAX_LENGTH = 128
_FILL_SOURCE_NAMESPACE_MAX_LENGTH = 128


class LocalSimulatedFillEventKind(StrEnum):
    """Known local matcher event dispositions; unknown values must block."""

    FILL = "fill"
    FINAL_FILL = "final_fill"
    UNKNOWN = "unknown"


@dataclass(frozen=True, slots=True)
class ApplySimulatedOrderFillCommand:
    """Address one source-local event by its complete namespace/ID locator.

    source_namespace selects the event stream for lookup; it does not authorize
    that source. Source authorization remains the responsibility of the
    composition-root binding used for new events.
    """

    account_id: int
    user_id: int
    order_idempotency_key: str
    source_namespace: str
    fill_event_id: str
    expected_event_payload_hash: str | None = None


@dataclass(frozen=True, slots=True)
class LocalSimulatedFillEventV1:
    """Typed event returned by a configured durable local matcher reader.

    The independent event_payload_hash binds source identity and source
    evidence. Domain OrderReservationFillEconomics.payload_hash seals only
    the immutable economic request, so the two digests must remain separate.
    Source adapters own raw-byte hashing and the policy for event visibility,
    clock order, session membership, and source qualification.
    """

    source_namespace: str
    source_version: str
    source_event_id: str
    event_payload_hash: str
    source_snapshot_id: str
    source_snapshot_hash: str
    reservation_id: int
    account_id: int
    user_id: int
    order_idempotency_key: str
    intent_payload_hash: str
    reservation_request_hash: str
    plan_snapshot_hash: str
    security_id: str
    asset_code: str
    side: SimulatedTradeSide
    event_kind: LocalSimulatedFillEventKind
    quantity: Decimal
    price: Decimal
    occurred_at: datetime
    source_observed_at: datetime
    source_available_at: datetime
    recorded_at: datetime


class LocalSimulatedFillEventReader(Protocol):
    """Read one durable matcher event without writing a ledger or inventing IDs."""

    def read_event(
        self,
        *,
        account_id: int,
        user_id: int,
        order_idempotency_key: str,
        source_namespace: str,
        fill_event_id: str,
        as_of: datetime,
    ) -> LocalSimulatedFillEventV1 | None:
        """Return a typed source event visible under the reader's own contract."""


@dataclass(frozen=True, slots=True)
class LocalSimulatedFillSourceBinding:
    """Bind an actual reader to explicitly configured namespace and version."""

    reader: LocalSimulatedFillEventReader
    source_namespace: str
    source_version: str


class OrderFillSettlementResolver(Protocol):
    """Resolve published calendar evidence for one validated source-event instant."""

    def resolve(
        self,
        *,
        event_occurred_at: datetime,
        settlement_exchange: str,
        settlement_lag_sessions: int,
    ) -> OrderFillSettlementProof | None:
        """Return a Domain proof or no proof; never infer an exchange or lag."""


@dataclass(frozen=True, slots=True)
class OrderFillContext:
    """Owner-scoped lookup data for checking one newly read source event."""

    reservation_id: int
    account_id: int
    owner_user_id: int
    order_idempotency_key: str
    reservation: OrderReservation
    asset_code: str
    intent_payload_hash: str
    plan_snapshot_hash: str
    settlement_exchange: str
    settlement_lag_sessions: int


@dataclass(frozen=True, slots=True)
class SimulatedOrderFillResult:
    """Persisted fill economics, separate source digest, and current order state.

    reservation is the current owner-scoped reservation at repository readback
    time. It may include later fills than economics when an older event is
    replayed; callers must not require those cumulative states to be equal.
    source_version records the original event schema and is not part of the
    namespace/event-ID replay locator.
    """

    reservation_id: int
    source_namespace: str
    source_version: str
    event_payload_hash: str
    economics: OrderReservationFillEconomics
    reservation: OrderReservation
    trade_id: int
    replayed: bool

    def __post_init__(self) -> None:
        """Validate stable identities without comparing mutable accrual states."""

        if type(self.reservation_id) is not int or self.reservation_id <= 0:
            raise ValueError("reservation_id must be a positive integer")
        if type(self.trade_id) is not int or self.trade_id <= 0:
            raise ValueError("trade_id must be a positive integer")
        if type(self.replayed) is not bool:
            raise ValueError("replayed must be a literal boolean")
        _require_token(
            self.source_namespace,
            "source_namespace",
            max_length=_FILL_SOURCE_NAMESPACE_MAX_LENGTH,
        )
        _require_token(self.source_version, "source_version")
        _require_hash(self.event_payload_hash, "event_payload_hash")
        if type(self.economics) is not OrderReservationFillEconomics:
            raise ValueError("economics must be an exact fill Domain value")
        if type(self.reservation) is not OrderReservation:
            raise ValueError("reservation must be an exact Domain value")
        self.economics.__post_init__()
        self.reservation.__post_init__()
        if self.reservation.identity != self.economics.reservation_identity:
            raise ValueError("current reservation identity differs from fill economics")


@dataclass(frozen=True, slots=True)
class ExistingOrderFill:
    """An exact owner-scoped persisted event found before any source read."""

    result: SimulatedOrderFillResult


FillRequestDisposition: TypeAlias = ExistingOrderFill | OrderFillContext | None


class SimulatedOrderFillRepository(Protocol):
    """Resolve owner scope and atomically re-read and apply one event."""

    def resolve_fill_request(
        self,
        *,
        account_id: int,
        user_id: int,
        order_idempotency_key: str,
        source_namespace: str,
        fill_event_id: str,
    ) -> FillRequestDisposition:
        """Under the account parent lock, return exact fill first or current order context."""

    def apply_fill_event(
        self,
        *,
        event: LocalSimulatedFillEventV1,
        expected_event_payload_hash: str | None,
        settlement_proof: OrderFillSettlementProof,
        clock: SimulatedTradeExecutionClock,
    ) -> SimulatedOrderFillResult:
        """Re-read the exact event before terminal checks and commit effects atomically."""


def _blocked(code: str, message: str) -> SimulatedTradeExecutionBlocked:
    """Create a stable existing business exception for a fill block."""

    return SimulatedTradeExecutionBlocked(message, code=code)


def _validate_command(command: object) -> ApplySimulatedOrderFillCommand:
    """Validate the minimal user/owner/event locator before repository access."""

    if type(command) is not ApplySimulatedOrderFillCommand:
        raise SimulatedTradeExecutionInputError("必须提供精确的模拟订单成交事件命令")
    if (
        type(command.account_id) is not int
        or command.account_id <= 0
        or type(command.user_id) is not int
        or command.user_id <= 0
    ):
        raise SimulatedTradeExecutionInputError("账户及所有者必须为有效标识")
    try:
        _require_token(command.order_idempotency_key, "order_idempotency_key", max_length=128)
        _require_token(
            command.source_namespace,
            "source_namespace",
            max_length=_FILL_SOURCE_NAMESPACE_MAX_LENGTH,
        )
        _require_token(
            command.fill_event_id,
            "fill_event_id",
            max_length=_FILL_EVENT_ID_MAX_LENGTH,
        )
        if command.expected_event_payload_hash is not None:
            _require_hash(command.expected_event_payload_hash, "expected_event_payload_hash")
    except (ArithmeticError, TypeError, ValueError) as error:
        raise SimulatedTradeExecutionInputError("成交事件定位或摘要无效") from error
    return command


def _validate_context(context: object, command: ApplySimulatedOrderFillCommand) -> OrderFillContext:
    """Validate the repository lookup snapshot before using it to scope source I/O."""

    if type(context) is not OrderFillContext:
        raise _blocked("SIMULATED_FILL_CONTEXT_INVALID", "订单成交上下文不可验证")
    try:
        if (
            type(context.account_id) is not int
            or context.account_id <= 0
            or type(context.owner_user_id) is not int
            or context.owner_user_id <= 0
            or type(context.reservation_id) is not int
            or context.reservation_id <= 0
            or type(context.reservation) is not OrderReservation
        ):
            raise ValueError("invalid order fill context fields")
        context.reservation.__post_init__()
        _require_token(context.order_idempotency_key, "order_idempotency_key", max_length=128)
        _require_token(context.asset_code, "asset_code")
        _require_hash(context.intent_payload_hash, "intent_payload_hash")
        _require_hash(context.plan_snapshot_hash, "plan_snapshot_hash")
        _require_token(context.settlement_exchange, "settlement_exchange")
        if type(context.settlement_lag_sessions) is not int or context.settlement_lag_sessions < 0:
            raise ValueError("settlement_lag_sessions must be an exact nonnegative integer")
        identity = context.reservation.identity
        if (
            context.account_id != command.account_id
            or context.owner_user_id != command.user_id
            or context.order_idempotency_key != command.order_idempotency_key
            or identity.account_id != context.account_id
            or identity.idempotency_key != context.order_idempotency_key
        ):
            raise SimulatedTradeAccountScopeUnavailable("订单不属于指定账户与所有者")
    except SimulatedTradeAccountScopeUnavailable:
        raise
    except (AttributeError, ArithmeticError, TypeError, ValueError) as error:
        raise _blocked("SIMULATED_FILL_CONTEXT_INVALID", "订单成交上下文不可验证") from error
    return context


def _validate_event(
    event: object,
    *,
    context: OrderFillContext,
    command: ApplySimulatedOrderFillCommand,
    binding: LocalSimulatedFillSourceBinding,
) -> LocalSimulatedFillEventV1:
    """Check source labels, digest syntax, owner/order binding, and typed clocks.

    This checks structural bindings only. It does not assign a freshness TTL or
    invent an ordering relation between occurred, observed, available, and
    recorded times; the configured source adapter owns those rules.
    """

    if type(event) is not LocalSimulatedFillEventV1:
        raise _blocked("SIMULATED_FILL_SOURCE_INVALID", "本地成交读取器返回了未知事件类型")
    try:
        _require_token(binding.source_namespace, "source_namespace")
        _require_token(binding.source_version, "source_version")
        _require_token(event.source_namespace, "source_namespace")
        _require_token(event.source_version, "source_version")
        _require_token(
            event.source_event_id, "source_event_id", max_length=_FILL_EVENT_ID_MAX_LENGTH
        )
        _require_token(event.source_snapshot_id, "source_snapshot_id")
        _require_token(event.order_idempotency_key, "order_idempotency_key", max_length=128)
        _require_token(event.security_id, "security_id")
        _require_token(event.asset_code, "asset_code")
        for field_name, digest in (
            ("event_payload_hash", event.event_payload_hash),
            ("source_snapshot_hash", event.source_snapshot_hash),
            ("intent_payload_hash", event.intent_payload_hash),
            ("reservation_request_hash", event.reservation_request_hash),
            ("plan_snapshot_hash", event.plan_snapshot_hash),
        ):
            _require_hash(digest, field_name)
        if (
            type(event.reservation_id) is not int
            or event.reservation_id <= 0
            or type(event.account_id) is not int
            or event.account_id <= 0
            or type(event.user_id) is not int
            or event.user_id <= 0
            or type(event.side) is not SimulatedTradeSide
            or type(event.event_kind) is not LocalSimulatedFillEventKind
        ):
            raise ValueError("source event identity or kind is invalid")
        validate_ledger_quantity(event.quantity, "fill_quantity", allow_zero=False)
        validate_ledger_price(event.price, "fill_price", allow_zero=False)
        for field_name, value in (
            ("occurred_at", event.occurred_at),
            ("source_observed_at", event.source_observed_at),
            ("source_available_at", event.source_available_at),
            ("recorded_at", event.recorded_at),
        ):
            _require_aware(value, field_name)
    except (
        AttributeError,
        ArithmeticError,
        SimulatedSettlementContractError,
        TypeError,
        ValueError,
    ) as error:
        raise _blocked(
            "SIMULATED_FILL_SOURCE_INVALID",
            "本地成交事件字段或时间不可验证",
        ) from error

    if event.event_kind is LocalSimulatedFillEventKind.UNKNOWN:
        _logger.warning(
            "Unknown local simulated fill event kind blocked",
            extra={"code": "SIMULATED_FILL_EVENT_KIND_UNKNOWN"},
        )
        raise _blocked(
            "SIMULATED_FILL_EVENT_KIND_UNKNOWN",
            "本地成交事件类型未知，已阻止记账",
        )
    if event.event_kind not in (
        LocalSimulatedFillEventKind.FILL,
        LocalSimulatedFillEventKind.FINAL_FILL,
    ):
        _logger.warning(
            "Unsupported local simulated fill event kind blocked",
            extra={"code": "SIMULATED_FILL_EVENT_KIND_UNKNOWN"},
        )
        raise _blocked("SIMULATED_FILL_EVENT_KIND_UNKNOWN", "本地成交事件类型未受支持")
    if (
        event.source_namespace != command.source_namespace
        or event.source_namespace != binding.source_namespace
        or event.source_version != binding.source_version
    ):
        raise _blocked("SIMULATED_FILL_SOURCE_INVALID", "成交事件来源与注入的读取器绑定不符")
    identity = context.reservation.identity
    if (
        event.source_event_id != command.fill_event_id
        or event.reservation_id != context.reservation_id
        or event.account_id != context.account_id
        or event.user_id != context.owner_user_id
        or event.order_idempotency_key != context.order_idempotency_key
        or event.intent_payload_hash != context.intent_payload_hash
        or event.reservation_request_hash != identity.request_payload_hash
        or event.plan_snapshot_hash != context.plan_snapshot_hash
        or event.security_id != identity.security_id
        or event.asset_code != context.asset_code
        or event.side is not context.reservation.side
    ):
        raise _blocked("SIMULATED_FILL_SOURCE_SCOPE_MISMATCH", "成交事件与当前订单封存身份不符")
    if (
        command.expected_event_payload_hash is not None
        and event.event_payload_hash != command.expected_event_payload_hash
    ):
        raise SimulatedTradeIdempotencyConflict("成交事件摘要与调用方已观察摘要不一致")
    return event


def _validate_settlement_proof(
    proof: object,
    *,
    event: LocalSimulatedFillEventV1,
    context: OrderFillContext,
) -> OrderFillSettlementProof:
    """Revalidate exact calendar proof and bind it to the event and sealed plan."""

    if type(proof) is not OrderFillSettlementProof:
        raise _blocked(
            "SIMULATED_FILL_SETTLEMENT_PROOF_INVALID",
            "正式交易日历没有返回精确的成交结算证明",
        )
    try:
        proof.validate()
        if (
            proof.fill_occurred_at != event.occurred_at
            or proof.settlement_exchange != context.settlement_exchange
            or proof.settlement_lag_sessions != context.settlement_lag_sessions
        ):
            raise ValueError("calendar proof differs from the exact fill event or sealed plan")
    except (
        AttributeError,
        ArithmeticError,
        SimulatedSettlementContractError,
        TypeError,
        ValueError,
    ) as error:
        raise _blocked(
            "SIMULATED_FILL_SETTLEMENT_PROOF_INVALID",
            "正式交易日历证明与成交时点或封存结算规则不一致",
        ) from error
    return proof


def _validate_result(
    result: object,
    *,
    command: ApplySimulatedOrderFillCommand,
    context: OrderFillContext | None,
    event: LocalSimulatedFillEventV1 | None,
) -> SimulatedOrderFillResult:
    """Check a persisted result against the stable request and available evidence."""

    if type(result) is not SimulatedOrderFillResult:
        raise SimulatedTradeExecutionResultUnknown("成交仓储返回了不可验证的回执")
    try:
        result.__post_init__()
        economics = result.economics
        identity = economics.reservation_identity
        if (
            economics.fill_event_id != command.fill_event_id
            or result.source_namespace != command.source_namespace
            or economics.user_id != command.user_id
            or identity.account_id != command.account_id
            or identity.idempotency_key != command.order_idempotency_key
        ):
            raise ValueError("fill receipt differs from requested owner or event")
        if context is not None and (
            result.reservation_id != context.reservation_id
            or identity != context.reservation.identity
            or result.reservation.identity != context.reservation.identity
            or economics.intent_payload_hash != context.intent_payload_hash
            or economics.asset_code != context.asset_code
        ):
            raise ValueError("fill receipt differs from the owner-scoped order context")
        if event is not None and (
            result.source_namespace != event.source_namespace
            or result.source_version != event.source_version
            or economics.fill_event_id != event.source_event_id
            or result.event_payload_hash != event.event_payload_hash
            or economics.user_id != event.user_id
            or identity.account_id != event.account_id
            or identity.security_id != event.security_id
            or identity.idempotency_key != event.order_idempotency_key
            or identity.request_payload_hash != event.reservation_request_hash
            or economics.intent_payload_hash != event.intent_payload_hash
            or economics.asset_code != event.asset_code
            or economics.side is not event.side
            or economics.quantity != event.quantity
            or economics.price != event.price
            or economics.fill_occurred_at != event.occurred_at
            or economics.close_order
            is not (event.event_kind is LocalSimulatedFillEventKind.FINAL_FILL)
        ):
            raise ValueError("fill receipt differs from the exact source event")
    except (AttributeError, ArithmeticError, TypeError, ValueError) as error:
        raise SimulatedTradeExecutionResultUnknown("成交仓储回执与持久事实无法精确核对") from error
    if (
        event is None
        and command.expected_event_payload_hash is not None
        and result.event_payload_hash != command.expected_event_payload_hash
    ):
        raise SimulatedTradeIdempotencyConflict("已存事件摘要与调用方预期不一致")
    return result


class ApplySimulatedOrderFillUseCase:
    """Apply or replay one exact fill from an explicitly injected local reader.

    Existing event lookup runs before consulting the clock or source, so exact
    readback still works when a source is unavailable or the order is terminal.
    The repository's account lock and second event lookup remain authoritative
    for races between resolution and application.
    """

    def __init__(
        self,
        *,
        repository: SimulatedOrderFillRepository,
        clock: SimulatedTradeExecutionClock,
        source_binding: LocalSimulatedFillSourceBinding | None,
        settlement_resolver: OrderFillSettlementResolver | None = None,
    ) -> None:
        """Inject persistence, an aware clock, and optional new-event evidence readers."""

        self._repository = repository
        self._clock = clock
        self._source_binding = source_binding
        self._settlement_resolver = settlement_resolver

    def execute(self, command: ApplySimulatedOrderFillCommand) -> SimulatedOrderFillResult:
        """Replay an exact event or request one source-backed atomic fill application."""

        checked_command = _validate_command(command)
        disposition = self._repository.resolve_fill_request(
            account_id=checked_command.account_id,
            user_id=checked_command.user_id,
            order_idempotency_key=checked_command.order_idempotency_key,
            source_namespace=checked_command.source_namespace,
            fill_event_id=checked_command.fill_event_id,
        )
        if type(disposition) is ExistingOrderFill:
            result = _validate_result(
                disposition.result,
                command=checked_command,
                context=None,
                event=None,
            )
            return result if result.replayed else replace(result, replayed=True)
        if disposition is None:
            raise SimulatedTradeAccountScopeUnavailable("指定账户下未找到该订单")
        context = _validate_context(disposition, checked_command)
        if context.reservation.status is not OrderReservationStatus.ACTIVE:
            raise _blocked("ORDER_RESERVATION_TERMINAL", "订单已终止，不能登记新的成交事件")

        binding = self._source_binding
        if type(binding) is not LocalSimulatedFillSourceBinding:
            raise _blocked(
                "SIMULATED_FILL_SOURCE_UNAVAILABLE",
                "本地成交读取器尚未配置；订单保持原状态",
            )
        try:
            _require_token(binding.source_namespace, "source_namespace")
            _require_token(binding.source_version, "source_version")
            if binding.source_namespace != checked_command.source_namespace:
                raise ValueError("source namespace differs from the requested locator")
        except (ArithmeticError, TypeError, ValueError) as error:
            raise _blocked(
                "SIMULATED_FILL_SOURCE_UNAVAILABLE",
                "本地成交读取器的来源版本绑定无效",
            ) from error

        settlement_resolver = self._settlement_resolver
        if settlement_resolver is None:
            raise _blocked(
                "SIMULATED_FILL_SETTLEMENT_UNAVAILABLE",
                "正式交易日历读取器尚未配置；订单保持原状态",
            )

        as_of = _require_aware_clock(self._clock.now())
        try:
            source_event = binding.reader.read_event(
                account_id=checked_command.account_id,
                user_id=checked_command.user_id,
                order_idempotency_key=checked_command.order_idempotency_key,
                source_namespace=checked_command.source_namespace,
                fill_event_id=checked_command.fill_event_id,
                as_of=as_of,
            )
        except AttributeError as error:
            raise _blocked(
                "SIMULATED_FILL_SOURCE_UNAVAILABLE",
                "本地成交读取器没有可用的事件读取入口",
            ) from error
        if source_event is None:
            raise _blocked(
                "SIMULATED_FILL_SOURCE_UNAVAILABLE",
                "本地成交读取器当前无法确认该稳定事件",
            )
        event = _validate_event(
            source_event,
            context=context,
            command=checked_command,
            binding=binding,
        )
        resolved_proof = settlement_resolver.resolve(
            event_occurred_at=event.occurred_at,
            settlement_exchange=context.settlement_exchange,
            settlement_lag_sessions=context.settlement_lag_sessions,
        )
        if resolved_proof is None:
            raise _blocked(
                "SIMULATED_FILL_SETTLEMENT_UNAVAILABLE",
                "正式交易日历当前无法证明成交时点与结算日",
            )
        settlement_proof = _validate_settlement_proof(
            resolved_proof,
            event=event,
            context=context,
        )

        try:
            applied = self._repository.apply_fill_event(
                event=event,
                expected_event_payload_hash=checked_command.expected_event_payload_hash,
                settlement_proof=settlement_proof,
                clock=self._clock,
            )
        except SimulatedTradeExecutionResultUnknown as error:
            return self._recover_unknown(
                command=checked_command,
                context=context,
                event=event,
                original_error=error,
            )
        try:
            return _validate_result(
                applied,
                command=checked_command,
                context=context,
                event=event,
            )
        except SimulatedTradeExecutionResultUnknown as error:
            return self._recover_unknown(
                command=checked_command,
                context=context,
                event=event,
                original_error=error,
            )

    def _recover_unknown(
        self,
        *,
        command: ApplySimulatedOrderFillCommand,
        context: OrderFillContext,
        event: LocalSimulatedFillEventV1,
        original_error: SimulatedTradeExecutionResultUnknown,
    ) -> SimulatedOrderFillResult:
        """Recover only from an exact owner-scoped durable event readback."""

        try:
            disposition = self._repository.resolve_fill_request(
                account_id=command.account_id,
                user_id=command.user_id,
                order_idempotency_key=command.order_idempotency_key,
                source_namespace=command.source_namespace,
                fill_event_id=command.fill_event_id,
            )
        except SimulatedTradeExecutionBlocked:
            disposition = None
        if type(disposition) is not ExistingOrderFill:
            raise original_error
        if disposition.result.event_payload_hash != event.event_payload_hash:
            raise SimulatedTradeIdempotencyConflict("同一成交事件标识已绑定到不同来源摘要")
        result = _validate_result(
            disposition.result,
            command=command,
            context=context,
            event=event,
        )
        return result if result.replayed else replace(result, replayed=True)


__all__: tuple[str, ...] = (
    "ApplySimulatedOrderFillCommand",
    "ApplySimulatedOrderFillUseCase",
    "ExistingOrderFill",
    "FillRequestDisposition",
    "LocalSimulatedFillEventKind",
    "LocalSimulatedFillEventReader",
    "LocalSimulatedFillEventV1",
    "LocalSimulatedFillSourceBinding",
    "OrderFillContext",
    "OrderFillSettlementResolver",
    "SimulatedOrderFillRepository",
    "SimulatedOrderFillResult",
)
