"""Persist and replay source-qualified local daily-order match decisions."""

from __future__ import annotations

from collections.abc import Iterable
from datetime import UTC, date, datetime

from django.core.exceptions import ObjectDoesNotExist
from django.db import DEFAULT_DB_ALIAS, IntegrityError, connections, transaction
from django.db.models import Q

from apps.simulated_trading.application.execution_settlement_uow import (
    SimulatedTradeAccountScopeUnavailable,
    SimulatedTradeExecutionBlocked,
    SimulatedTradeExecutionClock,
    SimulatedTradeIdempotencyConflict,
)
from apps.simulated_trading.application.local_daily_match import (
    LOCAL_DAILY_MATCH_SOURCE_NAMESPACE,
    LocalDailyMatchCommand,
    LocalDailyMatchDecision,
    LocalDailyMatchQualificationReader,
    LocalDailyMatchRepository,
    QualifiedLocalDailyMatchInput,
    local_daily_match_request_hash,
    validate_local_daily_match_input,
)
from apps.simulated_trading.application.order_reservation_fill import (
    LOCAL_DAILY_INTERVAL_SOURCE_VERSION,
    ExistingOrderFill,
    LocalSimulatedFillEventV1,
    OrderFillContext,
)
from apps.simulated_trading.domain.local_order_matching import (
    LocalMatchOutcome,
    LocalMatchPolicy,
    LocalOrderMatchResult,
    PriorLocalMatchEvent,
    calculate_local_order_match,
)
from apps.simulated_trading.domain.order_reservation import OrderReservationStatus
from apps.simulated_trading.infrastructure.local_daily_match_codec import (
    decision_from_parts,
    decode_decision_result,
    decode_event,
    decode_qualified_input,
    encode_decision_result,
    encode_event,
    encode_qualified_input,
    event_payload_hash,
    make_daily_fill_event,
    observation_source_hash,
    qualified_input_hash,
    record_digest_values,
)
from apps.simulated_trading.infrastructure.local_daily_match_models import (
    LocalDailyMatchModel,
)
from apps.simulated_trading.infrastructure.order_reservation_codec import (
    decode_order_reservation,
)
from apps.simulated_trading.infrastructure.order_reservation_fill_chain_storage import (
    _locked_fill_chain,
    _LockedFillChain,
    _trade_settlement_bindings,
)
from apps.simulated_trading.infrastructure.order_reservation_fill_request_reader import (
    DjangoSimulatedOrderFillRequestReader,
)
from apps.simulated_trading.infrastructure.order_reservation_guard import (
    lock_active_order_reservations,
    lock_order_reservation_key,
)
from apps.simulated_trading.infrastructure.order_reservation_models import (
    SimulatedOrderReservationModel,
)
from apps.simulated_trading.infrastructure.simulated_account_trade_models import (
    SimulatedAccountModel,
)


def _blocked(code: str, message: str) -> SimulatedTradeExecutionBlocked:
    """Return a stable error for inconsistent or incomplete match history."""

    return SimulatedTradeExecutionBlocked(message, code=code)


def _is_aware(value: object) -> bool:
    """Return whether a value is an exact timezone-aware datetime."""

    if type(value) is not datetime or value.tzinfo is None:
        return False
    try:
        return value.utcoffset() is not None
    except (OverflowError, TypeError, ValueError):
        return False


def _record_values(row: LocalDailyMatchModel) -> dict[str, object]:
    """Return every sealed database field except the auto-generated primary key."""

    return {
        "account_id": row.account_id,
        "reservation_id": row.reservation_id,
        "operation_key": row.operation_key,
        "request_hash": row.request_hash,
        "qmt_binding_id": row.qmt_binding_id,
        "session_date": row.session_date.isoformat(),
        "security_id": row.security_id,
        "asset_code": row.asset_code,
        "observation_id": row.observation_id,
        "outcome": row.outcome,
        "reason_code": row.reason_code,
        "source_namespace": row.source_namespace,
        "source_version": row.source_version,
        "event_id": row.event_id,
        "qualified_input_payload": row.qualified_input_payload,
        "qualified_input_hash": row.qualified_input_hash,
        "observation_source_hash": row.observation_source_hash,
        "decision_payload": row.decision_payload,
        "event_payload": row.event_payload,
        "recorded_at": row.recorded_at.astimezone(UTC)
        .isoformat(timespec="microseconds")
        .replace("+00:00", "Z"),
    }


def _decode_row(
    row: LocalDailyMatchModel,
    *,
    replayed: bool,
) -> LocalDailyMatchDecision:
    """Rebuild one application result while verifying all row seals and bindings."""

    if type(row) is not LocalDailyMatchModel:
        raise _blocked("LOCAL_DAILY_MATCH_RECORD_INVALID", "日线撮合记录类型不可验证")
    try:
        if (
            type(row.pk) is not int
            or row.pk <= 0
            or type(row.account_id) is not int
            or row.account_id <= 0
            or type(row.reservation_id) is not int
            or row.reservation_id <= 0
            or type(row.session_date) is not date
            or not _is_aware(row.recorded_at)
        ):
            raise ValueError("stored match identity or recording clock is invalid")
        if record_digest_values(_record_values(row)) != row.record_digest:
            raise ValueError("stored match record digest differs from its contents")

        reservation_row = row.reservation
        account_row = row.account
        if (
            type(reservation_row) is not SimulatedOrderReservationModel
            or type(account_row) is not SimulatedAccountModel
            or reservation_row.account_id != row.account_id
            or account_row.pk != row.account_id
            or type(reservation_row.owner_user_id) is not int
            or account_row.user_id != reservation_row.owner_user_id
            or account_row.account_type != "simulated"
        ):
            raise ValueError("stored match foreign keys differ from their owner scope")
        reservation = decode_order_reservation(reservation_row)

        command = LocalDailyMatchCommand(
            account_id=row.account_id,
            user_id=reservation_row.owner_user_id,
            order_idempotency_key=reservation_row.idempotency_key,
            operation_key=row.operation_key,
            session_date=row.session_date,
            qmt_binding_id=row.qmt_binding_id,
        )
        request_hash = local_daily_match_request_hash(command)
        if request_hash != row.request_hash:
            raise ValueError("stored local match request hash is invalid")
        qualified_input = decode_qualified_input(row.qualified_input_payload)
        expected_input_hash = qualified_input_hash(qualified_input)
        expected_observation_hash = observation_source_hash(qualified_input)
        if (
            expected_input_hash != row.qualified_input_hash
            or expected_observation_hash != row.observation_source_hash
            or qualified_input.as_of > row.recorded_at
            or qualified_input.observation.session_date != row.session_date
            or qualified_input.observation.security_id != row.security_id
            or qualified_input.observation.observation_id != row.observation_id
            or reservation_row.security_id != row.security_id
            or reservation_row.asset_code != row.asset_code
            or row.source_namespace != LOCAL_DAILY_MATCH_SOURCE_NAMESPACE
            or row.source_version != LOCAL_DAILY_INTERVAL_SOURCE_VERSION
            or row.event_id != row.operation_key
        ):
            raise ValueError("stored match source or order identity differs from its seal")

        result = decode_decision_result(row.decision_payload)
        if result.reason_code != row.reason_code or result.outcome.value != row.outcome:
            raise ValueError("stored match columns differ from the result payload")
        if encode_decision_result(result) != row.decision_payload:
            raise ValueError("stored match result is not canonical")

        event: LocalSimulatedFillEventV1 | None = None
        if result.outcome is LocalMatchOutcome.MATCHED:
            event = decode_event(row.event_payload)
            expected_event_hash = event_payload_hash(event)
            if (
                expected_event_hash != event.event_payload_hash
                or encode_event(event) != row.event_payload
                or event.source_namespace != row.source_namespace
                or event.source_version != row.source_version
                or event.source_event_id != row.event_id
                or event.reservation_id != row.reservation_id
                or event.account_id != row.account_id
                or event.user_id != command.user_id
                or event.order_idempotency_key != command.order_idempotency_key
                or event.intent_payload_hash != reservation_row.intent_payload_hash
                or event.reservation_request_hash != reservation_row.reservation_request_hash
                or event.plan_snapshot_hash != reservation_row.plan_snapshot_hash
                or event.security_id != row.security_id
                or event.asset_code != row.asset_code
                or event.side is not reservation.side
                or event.quantity != result.matched_quantity
                or event.price != result.matched_price
                or event.source_snapshot_id != qualified_input.observation.observation_id
                or event.source_snapshot_hash != expected_observation_hash
                or event.recorded_at != row.recorded_at
                or event.interval_end_at != qualified_input.observation.observed_at
                or event.local_known_at != qualified_input.observation.available_at
            ):
                raise ValueError("stored matched event differs from its decision and source")
        elif row.event_payload is not None:
            raise ValueError("stored no-match decision contains an event")

        decision = decision_from_parts(
            command=command,
            request_hash=request_hash,
            result=result,
            event=event,
            replayed=replayed,
        )
        return decision
    except SimulatedTradeExecutionBlocked:
        raise
    except (
        ArithmeticError,
        AttributeError,
        KeyError,
        ObjectDoesNotExist,
        TypeError,
        ValueError,
    ) as error:
        raise _blocked(
            "LOCAL_DAILY_MATCH_RECORD_INVALID",
            "已保存的日线撮合决定或来源摘要无法精确验证",
        ) from error


class DjangoLocalDailyMatchRepository(LocalDailyMatchRepository):
    """Serialize local match decisions by account and retain exact source evidence."""

    def __init__(self, *, using: str = DEFAULT_DB_ALIAS) -> None:
        """Select the database alias for all owner-scoped matcher operations."""

        if type(using) is not str or not using:
            raise ValueError("database alias must be non-empty text")
        self._using = using
        self._fill_request_reader = DjangoSimulatedOrderFillRequestReader(using=using)

    def find_operation(
        self,
        *,
        command: LocalDailyMatchCommand,
        request_hash: str,
    ) -> LocalDailyMatchDecision | None:
        """Replay an exact committed operation before reading current mutable sources."""

        command.__post_init__()
        with transaction.atomic(using=self._using):
            account = self._lock_account(command=command)
            if account is None:
                return None
            row = self._find_operation_row(command=command)
            if row is None:
                return None
            decision = _decode_row(row, replayed=True)
            if decision.request_hash != request_hash or decision.command != command:
                raise SimulatedTradeIdempotencyConflict(
                    "日线撮合操作键已绑定到不同的账户、订单或请求"
                )
            return decision

    def resolve_order_context(
        self,
        *,
        command: LocalDailyMatchCommand,
    ) -> OrderFillContext | None:
        """Resolve one current active-owner order before qualification reads."""

        command.__post_init__()
        active_owner = (
            SimulatedAccountModel._base_manager.using(self._using)
            .filter(
                pk=command.account_id,
                user_id=command.user_id,
                user__is_active=True,
                account_type="simulated",
                is_active=True,
            )
            .exists()
        )
        if not active_owner:
            return None
        disposition = self._fill_request_reader.resolve_fill_request(
            account_id=command.account_id,
            user_id=command.user_id,
            order_idempotency_key=command.order_idempotency_key,
            source_namespace=LOCAL_DAILY_MATCH_SOURCE_NAMESPACE,
            fill_event_id=command.operation_key,
        )
        if disposition is None:
            return None
        if type(disposition) is ExistingOrderFill:
            raise _blocked(
                "LOCAL_DAILY_MATCH_HISTORY_MISSING",
                "已存在日线撮合成交回执但找不到对应的持久撮合决定",
            )
        if type(disposition) is not OrderFillContext:
            raise _blocked("LOCAL_DAILY_MATCH_CONTEXT_INVALID", "订单范围读取结果不可验证")
        return disposition

    def record_decision(
        self,
        *,
        command: LocalDailyMatchCommand,
        request_hash: str,
        context: OrderFillContext,
        qualified_input: QualifiedLocalDailyMatchInput,
        as_of: datetime,
        qualification_reader: LocalDailyMatchQualificationReader,
        clock: SimulatedTradeExecutionClock,
    ) -> LocalDailyMatchDecision:
        """Requalify and append one matcher result before any fill-ledger write."""

        command.__post_init__()
        if request_hash != local_daily_match_request_hash(command):
            raise SimulatedTradeIdempotencyConflict("日线撮合请求摘要与稳定操作键不一致")
        validate_local_daily_match_input(
            command=command,
            context=context,
            qualified_input=qualified_input,
            as_of=as_of,
        )
        if connections[self._using].in_atomic_block:
            raise _blocked(
                "LOCAL_DAILY_MATCH_DURABLE_TRANSACTION_REQUIRED",
                "日线撮合必须在可独立提交的事务中完成",
            )
        try:
            with transaction.atomic(using=self._using, durable=True):
                account = self._lock_account(command=command)
                if account is None:
                    raise SimulatedTradeAccountScopeUnavailable(
                        "模拟账户不存在、已停用或不属于当前所有者"
                    )
                replay = self._find_operation_row(command=command)
                if replay is not None:
                    decision = _decode_row(replay, replayed=True)
                    if decision.request_hash != request_hash or decision.command != command:
                        raise SimulatedTradeIdempotencyConflict("日线撮合操作键已绑定到不同请求")
                    return decision
                if account.is_active is not True:
                    raise SimulatedTradeAccountScopeUnavailable(
                        "模拟账户不存在、已停用或不属于当前所有者"
                    )

                lock_active_order_reservations(
                    account_id=command.account_id,
                    using=self._using,
                )
                target = lock_order_reservation_key(
                    account_id=command.account_id,
                    idempotency_key=command.order_idempotency_key,
                    using=self._using,
                )
                if target is None:
                    raise SimulatedTradeAccountScopeUnavailable("指定账户下未找到该订单")

                current_context = self._resolve_locked_context(command=command)
                if current_context.reservation_id != target.pk:
                    raise _blocked("LOCAL_DAILY_MATCH_CONTEXT_INVALID", "锁定订单范围发生变化")
                self._require_same_order_identity(before=context, current=current_context)
                if current_context.reservation.status is not OrderReservationStatus.ACTIVE:
                    raise _blocked(
                        "ORDER_RESERVATION_TERMINAL",
                        "终态订单不接受新的日线撮合",
                    )

                checked_input = qualification_reader.read(
                    command=command,
                    context=current_context,
                    as_of=as_of,
                )
                if checked_input is None:
                    raise _blocked(
                        "LOCAL_DAILY_MATCH_QUALIFICATION_UNAVAILABLE",
                        "锁内无法重新验证日线撮合来源",
                    )
                validate_local_daily_match_input(
                    command=command,
                    context=current_context,
                    qualified_input=checked_input,
                    as_of=as_of,
                )
                if qualified_input_hash(checked_input) != qualified_input_hash(qualified_input):
                    raise _blocked(
                        "LOCAL_DAILY_MATCH_QUALIFICATION_CHANGED",
                        "锁内读取的政策或来源与本次撮合预览不同",
                    )

                prior_events, current_chain = self._read_capacity_and_pending_history(
                    command=command,
                    context=current_context,
                    observation_id=checked_input.observation.observation_id,
                )
                policy = LocalMatchPolicy(
                    participation_rate=checked_input.policy_binding.policy.participation_rate,
                    share_step=checked_input.policy_binding.policy.share_step,
                )
                result = calculate_local_order_match(
                    order=current_context.reservation,
                    observation=checked_input.observation,
                    policy=policy,
                    prior_events=prior_events,
                    as_of=as_of,
                )
                if result.outcome is LocalMatchOutcome.BLOCKED:
                    raise _blocked(
                        f"LOCAL_DAILY_MATCH_{result.reason_code}",
                        "日线撮合输入或账户容量未通过既有撮合规则",
                    )

                recorded_at = clock.now()
                if not _is_aware(recorded_at) or recorded_at < as_of:
                    raise _blocked(
                        "LOCAL_DAILY_MATCH_CLOCK_INVALID",
                        "日线撮合持久化时钟无效或早于资格读取时点",
                    )
                if result.outcome is LocalMatchOutcome.MATCHED:
                    _trade_settlement_bindings(
                        reservation_row=target,
                        intent=current_chain.intent,
                        as_of=recorded_at,
                    )
                event = (
                    make_daily_fill_event(
                        command=command,
                        context=current_context,
                        qualified_input=checked_input,
                        result=result,
                        recorded_at=recorded_at,
                    )
                    if result.outcome is LocalMatchOutcome.MATCHED
                    else None
                )
                decision = self._insert_decision(
                    command=command,
                    request_hash=request_hash,
                    context=current_context,
                    qualified_input=checked_input,
                    result=result,
                    event=event,
                    recorded_at=recorded_at,
                )
                return decision
        except IntegrityError as error:
            committed = self.find_operation(command=command, request_hash=request_hash)
            if committed is not None:
                return committed
            raise SimulatedTradeIdempotencyConflict(
                "账户、订单或观察已存在冲突的日线撮合决定"
            ) from error

    def _lock_account(self, *, command: LocalDailyMatchCommand) -> SimulatedAccountModel | None:
        """Lock the owner-scoped simulated account as the first writer row."""

        account = (
            SimulatedAccountModel._base_manager.using(self._using)
            .select_for_update()
            .filter(
                pk=command.account_id,
                user_id=command.user_id,
                user__is_active=True,
                account_type="simulated",
            )
            .first()
        )
        if account is not None and (
            type(account.pk) is not int
            or type(account.user_id) is not int
            or type(account.is_active) is not bool
        ):
            raise _blocked("SIMULATED_ACCOUNT_SCOPE_INVALID", "模拟账户状态不可验证")
        return account

    def _find_operation_row(
        self,
        *,
        command: LocalDailyMatchCommand,
    ) -> LocalDailyMatchModel | None:
        """Read at most one account operation after its parent row is locked."""

        rows = list(
            LocalDailyMatchModel._base_manager.using(self._using)
            .select_related("account", "reservation")
            .filter(account_id=command.account_id, operation_key=command.operation_key)
            .order_by("pk")[:2]
        )
        if len(rows) > 1:
            raise _blocked("LOCAL_DAILY_MATCH_RECORD_INVALID", "账户操作键对应多条撮合记录")
        return rows[0] if rows else None

    def _resolve_locked_context(self, *, command: LocalDailyMatchCommand) -> OrderFillContext:
        """Reuse the existing strict reservation/receipt reader under account locks."""

        disposition = self._fill_request_reader.resolve_fill_request(
            account_id=command.account_id,
            user_id=command.user_id,
            order_idempotency_key=command.order_idempotency_key,
            source_namespace=LOCAL_DAILY_MATCH_SOURCE_NAMESPACE,
            fill_event_id=command.operation_key,
        )
        if type(disposition) is ExistingOrderFill:
            raise _blocked(
                "LOCAL_DAILY_MATCH_HISTORY_MISSING",
                "已存在日线撮合成交回执但找不到对应的持久撮合决定",
            )
        if type(disposition) is not OrderFillContext:
            raise SimulatedTradeAccountScopeUnavailable("指定账户下未找到可撮合的订单")
        return disposition

    def _require_same_order_identity(
        self,
        *,
        before: OrderFillContext,
        current: OrderFillContext,
    ) -> None:
        """Allow fill progress but reject changes to the sealed order identity."""

        if (
            before.reservation_id != current.reservation_id
            or before.account_id != current.account_id
            or before.owner_user_id != current.owner_user_id
            or before.order_idempotency_key != current.order_idempotency_key
            or before.reservation.identity != current.reservation.identity
            or before.intent_payload_hash != current.intent_payload_hash
            or before.plan_snapshot_hash != current.plan_snapshot_hash
            or before.asset_code != current.asset_code
            or before.settlement_exchange != current.settlement_exchange
            or before.settlement_lag_sessions != current.settlement_lag_sessions
        ):
            raise _blocked(
                "LOCAL_DAILY_MATCH_ORDER_CHANGED",
                "撮合预览后订单封存身份或结算范围发生变化",
            )

    def _read_capacity_and_pending_history(
        self,
        *,
        command: LocalDailyMatchCommand,
        context: OrderFillContext,
        observation_id: str,
    ) -> tuple[tuple[PriorLocalMatchEvent, ...], _LockedFillChain]:
        """Validate history and return the locked chain for the current order."""

        account_rows = list(
            LocalDailyMatchModel._base_manager.using(self._using)
            .select_related("account", "reservation")
            .filter(
                Q(account_id=command.account_id) | Q(reservation__account_id=command.account_id)
            )
            .order_by("pk")
        )
        rows_by_id: dict[int, LocalDailyMatchModel] = {}
        for row in account_rows:
            if type(row.pk) is not int:
                raise _blocked("LOCAL_DAILY_MATCH_RECORD_INVALID", "撮合记录主键无效")
            rows_by_id[row.pk] = row
        decoded_by_id: dict[int, LocalDailyMatchDecision] = {}
        for pk, row in rows_by_id.items():
            decoded_by_id[pk] = _decode_row(row, replayed=False)
        capacity_rows: list[LocalDailyMatchModel] = []
        order_rows: list[LocalDailyMatchModel] = []
        for row in rows_by_id.values():
            decoded = decoded_by_id[row.pk]
            reservation = row.reservation
            if type(reservation) is not SimulatedOrderReservationModel:
                raise _blocked("LOCAL_DAILY_MATCH_RECORD_INVALID", "撮合订单历史缺失")
            row_security_id = (
                decoded.event.security_id if decoded.event is not None else reservation.security_id
            )
            if (
                decoded.command.session_date == command.session_date
                and row_security_id == context.reservation.identity.security_id
            ):
                capacity_rows.append(row)
            if decoded.command.order_idempotency_key == command.order_idempotency_key:
                order_rows.append(row)
        for row in order_rows:
            decoded = decoded_by_id[row.pk]
            if (
                decoded.event is not None and decoded.event.source_snapshot_id == observation_id
            ) or row.observation_id == observation_id:
                raise SimulatedTradeIdempotencyConflict(
                    "同一订单和日线观察已存在撮合决定，不能以新来源重复计算"
                )

        matched_rows = tuple(
            row
            for row in dict.fromkeys((*capacity_rows, *order_rows))
            if decoded_by_id[row.pk].result.outcome is LocalMatchOutcome.MATCHED
        )
        reservation_ids = {row.reservation_id for row in matched_rows}
        reservation_ids.add(context.reservation_id)
        history_by_reservation: dict[int, list[LocalDailyMatchModel]] = {}
        for row in rows_by_id.values():
            if row.reservation_id in reservation_ids:
                history_by_reservation.setdefault(row.reservation_id, []).append(row)

        pending_by_reservation: dict[int, int] = {}
        prior_events: list[PriorLocalMatchEvent] = []
        current_history = history_by_reservation.get(context.reservation_id, [])
        current_reservation = (
            SimulatedOrderReservationModel._base_manager.using(self._using)
            .select_related("account")
            .filter(
                pk=context.reservation_id,
                account_id=command.account_id,
                owner_user_id=command.user_id,
            )
            .first()
        )
        if current_reservation is None:
            raise _blocked("LOCAL_DAILY_MATCH_ORDER_CHANGED", "锁定订单历史已不存在")
        current_chain = _locked_fill_chain(
            reservation_row=current_reservation,
            using=self._using,
        )
        chains: dict[int, _LockedFillChain] = {}
        chains[context.reservation_id] = current_chain
        self._require_local_namespace_receipts(
            reservation_id=context.reservation_id,
            decision_rows=current_history,
            chain=current_chain,
        )
        for row in matched_rows:
            reservation_id = row.reservation_id
            chain = chains.get(reservation_id)
            if chain is None:
                reservation_row = row.reservation
                if type(reservation_row) is not SimulatedOrderReservationModel:
                    raise _blocked("LOCAL_DAILY_MATCH_RECORD_INVALID", "撮合订单历史缺失")
                chain = _locked_fill_chain(
                    reservation_row=reservation_row,
                    using=self._using,
                )
                chains[reservation_id] = chain
                self._require_local_namespace_receipts(
                    reservation_id=reservation_id,
                    decision_rows=history_by_reservation.get(reservation_id, []),
                    chain=chain,
                )

            decision = decoded_by_id[row.pk]
            event = decision.event
            if event is None:
                raise _blocked("LOCAL_DAILY_MATCH_RECORD_INVALID", "已匹配历史缺少事件")
            receipts = tuple(
                decoded
                for receipt, decoded in chain.rows
                if receipt.source_namespace == event.source_namespace
                and receipt.source_event_id == event.source_event_id
            )
            if len(receipts) > 1:
                raise _blocked("LOCAL_DAILY_MATCH_HISTORY_INVALID", "撮合事件有多条入账回执")
            if receipts and receipts[0].event.event_payload_hash != event.event_payload_hash:
                raise _blocked("LOCAL_DAILY_MATCH_HISTORY_INVALID", "撮合事件与入账回执摘要冲突")
            if not receipts:
                pending_by_reservation[reservation_id] = (
                    pending_by_reservation.get(reservation_id, 0) + 1
                )
            decision = decoded_by_id[row.pk]
            if event.account_id == command.account_id and (
                event.security_id == context.reservation.identity.security_id
                and decision.command.session_date == command.session_date
            ):
                prior_events.append(
                    PriorLocalMatchEvent(
                        account_id=event.account_id,
                        security_id=event.security_id,
                        session_date=decision.command.session_date,
                        observation_id=event.source_snapshot_id,
                        event_id=event.source_event_id,
                        quantity=event.quantity,
                    )
                )

        if any(count > 1 for count in pending_by_reservation.values()):
            raise _blocked(
                "LOCAL_DAILY_MATCH_PENDING_HISTORY_INVALID",
                "同一订单存在多条未消费日线撮合事件",
            )
        if pending_by_reservation.get(context.reservation_id, 0):
            raise _blocked(
                "LOCAL_DAILY_MATCH_PENDING_FILL",
                "订单已有未消费的日线撮合事件，必须先处理该事件",
            )
        return tuple(prior_events), current_chain

    def _require_local_namespace_receipts(
        self,
        *,
        reservation_id: int,
        decision_rows: Iterable[LocalDailyMatchModel],
        chain: _LockedFillChain,
    ) -> None:
        """Require each local matcher receipt to remain bound to its matched row."""

        by_event: dict[str, LocalDailyMatchDecision] = {}
        for row in decision_rows:
            decision = _decode_row(row, replayed=False)
            if decision.command.operation_key in by_event:
                raise _blocked(
                    "LOCAL_DAILY_MATCH_HISTORY_INVALID",
                    "同一订单操作键对应多条日线撮合决定",
                )
            by_event[decision.command.operation_key] = decision
        for receipt, decoded in chain.rows:
            if receipt.source_namespace != LOCAL_DAILY_MATCH_SOURCE_NAMESPACE:
                continue
            matched_decision = by_event.get(receipt.source_event_id)
            if (
                matched_decision is None
                or matched_decision.event is None
                or matched_decision.event.reservation_id != reservation_id
                or matched_decision.command.account_id != decoded.event.account_id
                or matched_decision.command.user_id != decoded.event.user_id
                or matched_decision.command.order_idempotency_key
                != decoded.event.order_idempotency_key
                or matched_decision.event.event_payload_hash != decoded.event.event_payload_hash
            ):
                raise _blocked(
                    "LOCAL_DAILY_MATCH_HISTORY_INVALID",
                    "日线撮合成交回执缺少精确的不可变决定记录",
                )

    def _insert_decision(
        self,
        *,
        command: LocalDailyMatchCommand,
        request_hash: str,
        context: OrderFillContext,
        qualified_input: QualifiedLocalDailyMatchInput,
        result: LocalOrderMatchResult,
        event: LocalSimulatedFillEventV1 | None,
        recorded_at: datetime,
    ) -> LocalDailyMatchDecision:
        """Insert one sealed decision and verify it through the same reader codec."""

        input_payload = encode_qualified_input(qualified_input)
        input_hash = qualified_input_hash(qualified_input)
        source_hash = observation_source_hash(qualified_input)
        event_text = encode_event(event) if event is not None else None
        kwargs: dict[str, object] = {
            "account_id": context.account_id,
            "reservation_id": context.reservation_id,
            "operation_key": command.operation_key,
            "request_hash": request_hash,
            "qmt_binding_id": command.qmt_binding_id,
            "session_date": command.session_date,
            "security_id": context.reservation.identity.security_id,
            "asset_code": context.asset_code,
            "observation_id": qualified_input.observation.observation_id,
            "outcome": result.outcome.value,
            "reason_code": result.reason_code,
            "source_namespace": LOCAL_DAILY_MATCH_SOURCE_NAMESPACE,
            "source_version": LOCAL_DAILY_INTERVAL_SOURCE_VERSION,
            "event_id": command.operation_key,
            "qualified_input_payload": input_payload,
            "qualified_input_hash": input_hash,
            "observation_source_hash": source_hash,
            "decision_payload": encode_decision_result(result),
            "event_payload": event_text,
            "recorded_at": recorded_at,
            "record_digest": "0" * 64,
        }
        row = LocalDailyMatchModel(**kwargs)
        row.record_digest = record_digest_values(_record_values(row))
        row.save(using=self._using, force_insert=True)
        saved = (
            LocalDailyMatchModel._base_manager.using(self._using)
            .select_related("account", "reservation")
            .get(pk=row.pk)
        )
        return _decode_row(saved, replayed=False)


def require_no_pending_local_daily_match(
    *,
    reservation_row: SimulatedOrderReservationModel,
    chain: _LockedFillChain,
    using: str,
) -> None:
    """Block cancellation unless each matched event is already in its receipt chain."""

    rows = list(
        LocalDailyMatchModel._base_manager.using(using)
        .select_related("account", "reservation")
        .filter(reservation_id=reservation_row.pk)
        .order_by("pk")
    )
    decisions: dict[str, LocalDailyMatchDecision] = {}
    for row in rows:
        decision = _decode_row(row, replayed=False)
        operation_key = decision.command.operation_key
        if operation_key in decisions:
            raise _blocked(
                "LOCAL_DAILY_MATCH_HISTORY_INVALID",
                "同一订单操作键对应多条不可变决定",
            )
        decisions[operation_key] = decision

    receipt_events: dict[str, LocalSimulatedFillEventV1] = {}
    for receipt, decoded in chain.rows:
        if receipt.source_namespace != LOCAL_DAILY_MATCH_SOURCE_NAMESPACE:
            continue
        event_id = receipt.source_event_id
        if event_id in receipt_events:
            raise _blocked(
                "LOCAL_DAILY_MATCH_HISTORY_INVALID",
                "同一日线撮合事件存在重复账本回执",
            )
        matched_decision = decisions.get(event_id)
        if (
            matched_decision is None
            or matched_decision.event is None
            or matched_decision.event.reservation_id != reservation_row.pk
            or matched_decision.event.event_payload_hash != decoded.event.event_payload_hash
        ):
            raise _blocked(
                "LOCAL_DAILY_MATCH_HISTORY_INVALID",
                "日线撮合账本回执缺少精确的不可变决定记录",
            )
        receipt_events[event_id] = decoded.event

    pending = 0
    for decision in decisions.values():
        event = decision.event
        if event is None:
            continue
        receipt_event = receipt_events.get(event.source_event_id)
        if receipt_event is None:
            pending += 1
        elif receipt_event.event_payload_hash != event.event_payload_hash:
            raise _blocked(
                "LOCAL_DAILY_MATCH_HISTORY_INVALID",
                "日线撮合决定与账本回执的事件摘要冲突",
            )
    if pending > 1:
        raise _blocked(
            "LOCAL_DAILY_MATCH_PENDING_HISTORY_INVALID",
            "同一订单存在多条未消费日线撮合事件",
        )
    if pending:
        raise _blocked(
            "LOCAL_DAILY_MATCH_PENDING_FILL",
            "订单已有未消费的日线撮合事件，不能取消订单",
        )


__all__ = ("DjangoLocalDailyMatchRepository",)
