"""Resolve locked owner order IDs to retained Apply or Cancel targets."""

from __future__ import annotations

from datetime import date, datetime
from typing import Protocol, TypedDict, cast
from uuid import UUID

from django.contrib.auth import get_user_model
from django.core.exceptions import ObjectDoesNotExist
from django.db import DEFAULT_DB_ALIAS, DatabaseError, transaction

from apps.simulated_trading.application.execution_settlement_uow import (
    SimulatedTradeAccountScopeUnavailable,
    SimulatedTradeExecutionBlocked,
    SimulatedTradeExecutionClock,
    SimulatedTradeExecutionInputError,
)
from apps.simulated_trading.application.local_daily_match import (
    LOCAL_DAILY_MATCH_SOURCE_NAMESPACE,
    LocalDailyMatchCommand,
    LocalDailyMatchDecision,
)
from apps.simulated_trading.application.order_reservation_fill import (
    LOCAL_DAILY_INTERVAL_SOURCE_VERSION,
)
from apps.simulated_trading.application.owner_order_matching import (
    owner_order_match_operation_key,
)
from apps.simulated_trading.application.owner_order_operations import (
    OwnerOrderCancelTarget,
    OwnerOrderFillTarget,
)
from apps.simulated_trading.domain.local_order_matching import LocalMatchOutcome
from apps.simulated_trading.domain.order_reservation import (
    OrderReservation,
    OrderReservationStatus,
)
from apps.simulated_trading.infrastructure.local_daily_match_models import (
    LocalDailyMatchModel,
)
from apps.simulated_trading.infrastructure.local_daily_match_repository import _decode_row
from apps.simulated_trading.infrastructure.order_reservation_codec import decode_order_reservation
from apps.simulated_trading.infrastructure.order_reservation_models import (
    SimulatedOrderReservationModel,
)
from apps.simulated_trading.infrastructure.simulated_account_trade_models import (
    SimulatedAccountModel,
)


class _ActorState(TypedDict):
    """Only the authenticated user's current activation column."""

    is_active: object


class OwnerQmtBindingListReader(Protocol):
    """Read the current owner's public QMT binding statuses without source authority."""

    def list_bindings(self, owner_id: int) -> list[dict[str, object]]:
        """Return the owner's current paired/enabled/revoked binding summaries."""


class DjangoOwnerOrderOperationTargetReader:
    """Lock current owner scope and decode the original retained order facts."""

    def __init__(
        self,
        *,
        using: str = DEFAULT_DB_ALIAS,
        clock: SimulatedTradeExecutionClock,
        read_bindings: OwnerQmtBindingListReader | None = None,
    ) -> None:
        """Bind order resolution to its DB, clock, and optional public binding list."""

        if type(using) is not str or not using or using.strip() != using:
            raise SimulatedTradeExecutionInputError("订单操作目标数据库别名无效")
        self._using = using
        self._clock = clock
        self._read_bindings = read_bindings

    def resolve_match_target(
        self,
        *,
        account_id: int,
        user_id: int,
        order_id: int,
        session_date: date,
    ) -> LocalDailyMatchCommand:
        """Return an exact prior command or construct one from the owner's QMT list.

        Existing decisions are decoded before account-activity and binding checks,
        so the original operation can replay without today's mutable source state.
        New decisions require an active account and reservation before one unique
        configured binding is selected. Qualification remains with the producer's
        existing source reader.
        """

        _validate_ids(account_id=account_id, user_id=user_id, order_id=order_id)
        if type(session_date) is not date:
            raise SimulatedTradeExecutionInputError("撮合交易日必须为精确日期")
        if self._using != DEFAULT_DB_ALIAS:
            raise SimulatedTradeExecutionInputError(
                "公开 QMT 绑定与模拟撮合必须使用同一默认数据库",
                code="LOCAL_DAILY_MATCH_ALIAS_MISMATCH",
            )
        with transaction.atomic(using=self._using):
            account = self._lock_owner(account_id=account_id, user_id=user_id)
            reservation_row, reservation = self._lock_reservation(
                account_id=account_id,
                user_id=user_id,
                order_id=order_id,
            )
            as_of = self._current_time()
            prior_command = self._read_existing_match_command(
                account_id=account_id,
                user_id=user_id,
                order_id=order_id,
                session_date=session_date,
                reservation_row=reservation_row,
                reservation=reservation,
                as_of=as_of,
            )
            if prior_command is not None:
                return prior_command
            if account.is_active is not True:
                raise SimulatedTradeAccountScopeUnavailable("新撮合只允许使用启用中的模拟账户")
            if reservation.status is not OrderReservationStatus.ACTIVE:
                raise SimulatedTradeExecutionBlocked(
                    "终态订单不能生成新的日线撮合决定",
                    code="OWNER_ORDER_MATCH_ORDER_NOT_ACTIVE",
                )
            binding_id = self._select_binding_id(
                owner_id=user_id,
                asset_code=reservation_row.asset_code,
            )
            try:
                return LocalDailyMatchCommand(
                    account_id=account_id,
                    user_id=user_id,
                    order_idempotency_key=reservation.identity.idempotency_key,
                    operation_key=owner_order_match_operation_key(order_id, session_date),
                    session_date=session_date,
                    qmt_binding_id=binding_id,
                )
            except (ArithmeticError, AttributeError, TypeError, ValueError) as error:
                raise _match_target_invalid() from error

    def _read_existing_match_command(
        self,
        *,
        account_id: int,
        user_id: int,
        order_id: int,
        session_date: date,
        reservation_row: SimulatedOrderReservationModel,
        reservation: OrderReservation,
        as_of: datetime,
    ) -> LocalDailyMatchCommand | None:
        """Decode a prior same-order/session row and preserve its original command."""

        rows = list(
            LocalDailyMatchModel._base_manager.using(self._using)
            .select_for_update()
            .select_related("account", "reservation")
            .filter(
                account_id=account_id,
                reservation_id=order_id,
                session_date=session_date,
            )
            .order_by("pk")[:2]
        )
        if len(rows) > 1:
            raise _match_history_invalid()
        if not rows:
            return None
        row = rows[0]
        try:
            decision = _decode_row(row, replayed=False)
            if type(decision) is not LocalDailyMatchDecision:
                raise ValueError("stored decision decoder returned an unknown value")
            decision.__post_init__()
            command = decision.command
            if (
                type(row.pk) is not int
                or row.account_id != account_id
                or row.reservation_id != reservation_row.pk
                or row.session_date != session_date
                or row.security_id != reservation.identity.security_id
                or row.asset_code != reservation_row.asset_code
                or row.source_namespace != LOCAL_DAILY_MATCH_SOURCE_NAMESPACE
                or row.source_version != LOCAL_DAILY_INTERVAL_SOURCE_VERSION
                or row.operation_key != command.operation_key
                or row.event_id != command.operation_key
                or row.qmt_binding_id != command.qmt_binding_id
                or command.account_id != account_id
                or command.user_id != user_id
                or command.order_idempotency_key != reservation.identity.idempotency_key
                or command.session_date != session_date
                or decision.result.outcome
                not in (LocalMatchOutcome.MATCHED, LocalMatchOutcome.NO_MATCH)
                or row.recorded_at > as_of
                or (decision.event is not None and decision.event.recorded_at > as_of)
            ):
                raise ValueError("stored match command differs from the locked owner order")
            return command
        except SimulatedTradeExecutionBlocked:
            raise
        except (
            ArithmeticError,
            AttributeError,
            ObjectDoesNotExist,
            TypeError,
            ValueError,
        ) as error:
            raise _match_history_invalid() from error

    def _select_binding_id(self, *, owner_id: int, asset_code: str) -> str:
        """Select one current owner binding while leaving qualification to QMT reads."""

        if self._read_bindings is None:
            raise _qmt_binding_unavailable()
        try:
            bindings = self._read_bindings.list_bindings(owner_id=owner_id)
        except (DatabaseError, ObjectDoesNotExist, OSError, TypeError, ValueError) as error:
            raise _qmt_binding_unavailable() from error
        return _select_qmt_binding_id(bindings, asset_code=asset_code)

    def resolve_fill_target(
        self,
        *,
        account_id: int,
        user_id: int,
        order_id: int,
        decision_id: int,
    ) -> OwnerOrderFillTarget:
        """Return the exact retained MATCHED event locator inside owner locks."""

        _validate_ids(
            account_id=account_id,
            user_id=user_id,
            order_id=order_id,
            decision_id=decision_id,
        )
        with transaction.atomic(using=self._using):
            self._lock_owner(account_id=account_id, user_id=user_id)
            reservation_row, reservation = self._lock_reservation(
                account_id=account_id,
                user_id=user_id,
                order_id=order_id,
            )
            current_time = self._current_time()
            decision = self._read_decision(
                account_id=account_id,
                user_id=user_id,
                order_id=order_id,
                decision_id=decision_id,
                reservation_row=reservation_row,
                reservation=reservation,
                as_of=current_time,
            )
            event = decision.event
            if event is None or decision.result.outcome is not LocalMatchOutcome.MATCHED:
                raise SimulatedTradeExecutionBlocked(
                    "该撮合决定没有可入账的匹配事件",
                    code="OWNER_ORDER_DECISION_NOT_MATCHED",
                )
            try:
                return OwnerOrderFillTarget(
                    account_id=account_id,
                    user_id=user_id,
                    order_id=order_id,
                    reservation_id=reservation_row.pk,
                    decision_id=decision_id,
                    order_idempotency_key=reservation.identity.idempotency_key,
                    source_namespace=event.source_namespace,
                    fill_event_id=event.source_event_id,
                    expected_event_payload_hash=event.event_payload_hash,
                )
            except (ArithmeticError, AttributeError, TypeError, ValueError) as error:
                raise _target_invalid() from error

    def resolve_cancel_target(
        self,
        *,
        account_id: int,
        user_id: int,
        order_id: int,
    ) -> OwnerOrderCancelTarget:
        """Return the exact current owner reservation key under account locks."""

        _validate_ids(account_id=account_id, user_id=user_id, order_id=order_id)
        with transaction.atomic(using=self._using):
            self._lock_owner(account_id=account_id, user_id=user_id)
            reservation_row, reservation = self._lock_reservation(
                account_id=account_id,
                user_id=user_id,
                order_id=order_id,
            )
            try:
                return OwnerOrderCancelTarget(
                    account_id=account_id,
                    user_id=user_id,
                    order_id=order_id,
                    reservation_id=reservation_row.pk,
                    order_idempotency_key=reservation.identity.idempotency_key,
                )
            except (ArithmeticError, AttributeError, TypeError, ValueError) as error:
                raise _target_invalid() from error

    def _lock_owner(self, *, account_id: int, user_id: int) -> SimulatedAccountModel:
        """Lock the simulated account then active actor and recheck current ownership."""

        account = (
            SimulatedAccountModel._base_manager.using(self._using)
            .select_for_update()
            .filter(pk=account_id, account_type="simulated", user_id=user_id)
            .first()
        )
        if type(account) is not SimulatedAccountModel:
            raise SimulatedTradeAccountScopeUnavailable("模拟账户不存在或不属于当前用户")
        actor_query = (
            get_user_model()
            ._base_manager.using(self._using)
            .select_for_update()
            .filter(pk=user_id)
            .values("is_active")
        )
        actor_state: _ActorState | None = cast(_ActorState | None, actor_query.first())
        if (
            type(actor_state) is not dict
            or set(actor_state) != {"is_active"}
            or type(actor_state["is_active"]) is not bool
            or actor_state["is_active"] is not True
        ):
            raise SimulatedTradeAccountScopeUnavailable("当前账户用户不可用")
        if type(account.user_id) is not int or account.user_id != user_id:
            raise SimulatedTradeAccountScopeUnavailable("模拟账户所有者已变化")
        return account

    def _lock_reservation(
        self,
        *,
        account_id: int,
        user_id: int,
        order_id: int,
    ) -> tuple[SimulatedOrderReservationModel, OrderReservation]:
        """Lock one public order ID and revalidate its complete sealed reservation."""

        row = (
            SimulatedOrderReservationModel._base_manager.using(self._using)
            .select_for_update()
            .filter(pk=order_id, account_id=account_id, owner_user_id=user_id)
            .first()
        )
        if type(row) is not SimulatedOrderReservationModel:
            raise SimulatedTradeAccountScopeUnavailable("订单不存在或不属于当前账户所有者")
        try:
            reservation = decode_order_reservation(row)
            if (
                type(row.pk) is not int
                or row.pk != order_id
                or type(row.account_id) is not int
                or row.account_id != account_id
                or type(row.owner_user_id) is not int
                or row.owner_user_id != user_id
                or reservation.identity.account_id != account_id
            ):
                raise ValueError("reservation does not match the requested owner order")
            return row, reservation
        except SimulatedTradeExecutionBlocked:
            raise
        except (
            ArithmeticError,
            AttributeError,
            ObjectDoesNotExist,
            TypeError,
            ValueError,
        ) as error:
            raise _target_invalid() from error

    def _read_decision(
        self,
        *,
        account_id: int,
        user_id: int,
        order_id: int,
        decision_id: int,
        reservation_row: SimulatedOrderReservationModel,
        reservation: OrderReservation,
        as_of: datetime,
    ) -> LocalDailyMatchDecision:
        """Decode the locked immutable decision and bind it to the exact order."""

        rows = list(
            LocalDailyMatchModel._base_manager.using(self._using)
            .select_for_update()
            .select_related("account", "reservation")
            .filter(pk=decision_id, account_id=account_id, reservation_id=order_id)[:2]
        )
        if not rows:
            raise SimulatedTradeAccountScopeUnavailable("撮合决定不存在或不属于当前订单")
        if len(rows) != 1:
            raise _target_invalid()
        row = rows[0]
        try:
            decision = _decode_row(row, replayed=False)
            if type(decision) is not LocalDailyMatchDecision:
                raise ValueError("decision reader returned an unknown contract type")
            decision.__post_init__()
            command = decision.command
            if (
                type(row.pk) is not int
                or row.pk != decision_id
                or row.reservation_id != reservation_row.pk
                or row.account_id != account_id
                or command.account_id != account_id
                or command.user_id != user_id
                or command.order_idempotency_key != reservation.identity.idempotency_key
                or decision.result.outcome
                not in (LocalMatchOutcome.MATCHED, LocalMatchOutcome.NO_MATCH)
            ):
                raise ValueError("decision does not match its owner order scope")
            if row.recorded_at > as_of or (
                decision.event is not None and decision.event.recorded_at > as_of
            ):
                raise SimulatedTradeExecutionBlocked(
                    "未来记录的撮合决定不能用于当前操作",
                    code="OWNER_ORDER_DECISION_FUTURE",
                )
            return decision
        except SimulatedTradeExecutionBlocked:
            raise
        except (
            ArithmeticError,
            AttributeError,
            ObjectDoesNotExist,
            TypeError,
            ValueError,
        ) as error:
            raise _target_invalid() from error

    def _current_time(self) -> datetime:
        """Read one exact aware cutoff from the injected execution clock."""

        current_time = self._clock.now()
        if type(current_time) is not datetime or current_time.tzinfo is None:
            raise SimulatedTradeExecutionInputError("订单操作读取时钟必须为带时区时间")
        try:
            if current_time.utcoffset() is None:
                raise ValueError("missing UTC offset")
        except (OverflowError, TypeError, ValueError) as error:
            raise SimulatedTradeExecutionInputError("订单操作读取时钟无效") from error
        return current_time


def _select_qmt_binding_id(bindings: object, *, asset_code: str) -> str:
    """Narrow the public dynamic binding list to one exact usable owner binding."""

    if (
        type(asset_code) is not str
        or not asset_code
        or asset_code.strip() != asset_code
        or type(bindings) is not list
    ):
        raise _qmt_binding_invalid()

    eligible: list[str] = []
    for value in cast(list[object], bindings):
        if type(value) is not dict:
            raise _qmt_binding_invalid()
        fields = cast(dict[str, object], value)
        binding_id = fields.get("binding_id")
        assets = fields.get("assets")
        paired = fields.get("paired")
        enabled = fields.get("enabled")
        revoked = fields.get("revoked")
        if (
            type(binding_id) is not str
            or type(assets) is not list
            or not assets
            or type(paired) is not bool
            or type(enabled) is not bool
            or type(revoked) is not bool
        ):
            raise _qmt_binding_invalid()
        try:
            if str(UUID(binding_id)) != binding_id:
                raise ValueError("QMT binding UUID is not canonical")
        except (AttributeError, TypeError, ValueError) as error:
            raise _qmt_binding_invalid() from error
        checked_assets = cast(list[object], assets)
        if any(
            type(asset) is not str or not asset or asset.strip() != asset
            for asset in checked_assets
        ) or len(set(cast(list[str], assets))) != len(checked_assets):
            raise _qmt_binding_invalid()
        if asset_code in cast(list[str], assets) and paired and enabled and not revoked:
            eligible.append(binding_id)

    if not eligible:
        raise _qmt_binding_unavailable()
    if len(eligible) != 1:
        raise SimulatedTradeExecutionBlocked(
            "当前证券存在多个已配对启用的 QMT 绑定",
            code="OWNER_ORDER_MATCH_QMT_BINDING_AMBIGUOUS",
        )
    return eligible[0]


def _validate_ids(
    *,
    account_id: int,
    user_id: int,
    order_id: int,
    decision_id: int | None = None,
) -> None:
    """Validate public IDs before querying any account or order rows."""

    if (
        type(account_id) is not int
        or account_id <= 0
        or type(user_id) is not int
        or user_id <= 0
        or type(order_id) is not int
        or order_id <= 0
        or (decision_id is not None and (type(decision_id) is not int or decision_id <= 0))
    ):
        raise SimulatedTradeExecutionInputError("订单操作标识必须为正整数")


def _target_invalid() -> SimulatedTradeExecutionBlocked:
    """Return one stable block for corrupted retained order or decision facts."""

    return SimulatedTradeExecutionBlocked(
        "订单操作目标无法与持久封存数据精确核对",
        code="OWNER_ORDER_OPERATION_TARGET_INVALID",
    )


def _match_target_invalid() -> SimulatedTradeExecutionBlocked:
    """Return a stable block for corrupt match history or internal command values."""

    return SimulatedTradeExecutionBlocked(
        "订单日线撮合目标无法与持久原件精确核对",
        code="OWNER_ORDER_MATCH_TARGET_INVALID",
    )


def _match_history_invalid() -> SimulatedTradeExecutionBlocked:
    """Return a stable block for duplicate, corrupt, or future prior decisions."""

    return SimulatedTradeExecutionBlocked(
        "原订单的既有日线撮合决定无法精确验证",
        code="OWNER_ORDER_MATCH_HISTORY_INVALID",
    )


def _qmt_binding_invalid() -> SimulatedTradeExecutionBlocked:
    """Return a stable block for malformed public QMT binding-list contents."""

    return SimulatedTradeExecutionBlocked(
        "QMT 绑定清单包含无法验证的字段",
        code="OWNER_ORDER_MATCH_QMT_BINDING_INVALID",
    )


def _qmt_binding_unavailable() -> SimulatedTradeExecutionBlocked:
    """Return a stable block when no unique eligible QMT binding is available."""

    return SimulatedTradeExecutionBlocked(
        "当前所有者没有覆盖该证券的已配对启用 QMT 绑定",
        code="OWNER_ORDER_MATCH_QMT_BINDING_UNAVAILABLE",
    )


__all__ = ("DjangoOwnerOrderOperationTargetReader", "OwnerQmtBindingListReader")
