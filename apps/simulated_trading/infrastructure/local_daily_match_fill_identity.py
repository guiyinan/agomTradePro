"""Verify a durable local match before using its historical identity time."""

from __future__ import annotations

from datetime import datetime

from django.core.exceptions import ObjectDoesNotExist
from django.db import DEFAULT_DB_ALIAS, DatabaseError, connections

from apps.simulated_trading.application.execution_settlement_uow import (
    SimulatedTradeExecutionBlocked,
)
from apps.simulated_trading.application.local_daily_match import (
    LOCAL_DAILY_MATCH_SOURCE_NAMESPACE,
)
from apps.simulated_trading.application.order_reservation_fill import (
    LOCAL_DAILY_INTERVAL_SOURCE_VERSION,
    LocalSimulatedFillEventV1,
    validate_local_simulated_fill_event,
)
from apps.simulated_trading.domain.execution_settlement_primitives import (
    SimulatedSettlementContractError,
    _require_aware,
)
from apps.simulated_trading.domain.local_order_matching import LocalMatchOutcome
from apps.simulated_trading.infrastructure.local_daily_match_models import (
    LocalDailyMatchModel,
)
from apps.simulated_trading.infrastructure.local_daily_match_repository import _decode_row
from apps.simulated_trading.infrastructure.order_reservation_models import (
    SimulatedOrderReservationModel,
)
from apps.simulated_trading.infrastructure.simulated_account_trade_models import (
    SimulatedAccountModel,
)


def _blocked(code: str, message: str) -> SimulatedTradeExecutionBlocked:
    """Return a stable fill-path block for unverified local match history."""

    return SimulatedTradeExecutionBlocked(message, code=code)


def local_daily_match_fill_identity_as_of(
    *,
    using: str = DEFAULT_DB_ALIAS,
    account: SimulatedAccountModel,
    reservation_row: SimulatedOrderReservationModel,
    event: LocalSimulatedFillEventV1,
    now: datetime,
) -> datetime | None:
    """Return the verified local match recording time for the exact producer namespace.

    Other injected event namespaces retain the fill path's current-time identity
    checks. The local namespace is a claim that must resolve to one locked,
    fully decoded MATCHED decision whose event is exactly the supplied event;
    malformed, absent, ambiguous, future, or cross-scope records are blocked.
    The returned timestamp is an identity-validation cutoff only. Current owner,
    ledger, settlement, calendar, and valuation checks still use the current
    fill writer time.
    """

    if type(event) is not LocalSimulatedFillEventV1:
        raise _blocked("SIMULATED_FILL_SOURCE_INVALID", "成交事件必须为精确类型")
    if event.source_namespace != LOCAL_DAILY_MATCH_SOURCE_NAMESPACE:
        return None
    try:
        if (
            type(using) is not str
            or not using
            or type(account) is not SimulatedAccountModel
            or type(reservation_row) is not SimulatedOrderReservationModel
            or event.source_version != LOCAL_DAILY_INTERVAL_SOURCE_VERSION
            or event.observation_basis != "daily_interval_end"
        ):
            raise ValueError("local daily match event or lock scope is invalid")
        _require_aware(now, "fill_writer_now")
        validate_local_simulated_fill_event(event)
        if (
            account.pk != event.account_id
            or account.user_id != event.user_id
            or account.account_type != "simulated"
            or reservation_row.pk != event.reservation_id
            or reservation_row.account_id != event.account_id
            or reservation_row.owner_user_id != event.user_id
            or reservation_row.idempotency_key != event.order_idempotency_key
        ):
            raise ValueError("local daily match event differs from locked owner scope")
        if connections[using].in_atomic_block is not True:
            raise ValueError("local daily match lookup requires the locked fill transaction")

        rows = tuple(
            LocalDailyMatchModel._base_manager.using(using)
            .select_for_update()
            .filter(account_id=account.pk, operation_key=event.source_event_id)
            .order_by("pk")[:2]
        )
        if len(rows) != 1:
            raise ValueError("local daily match operation is missing or ambiguous")
        row = rows[0]
        decision = _decode_row(row, replayed=True)
        if (
            type(decision.event) is not LocalSimulatedFillEventV1
            or decision.event != event
            or decision.result.outcome is not LocalMatchOutcome.MATCHED
            or row.account_id != account.pk
            or row.reservation_id != reservation_row.pk
            or row.operation_key != event.source_event_id
            or row.event_id != event.source_event_id
            or row.source_namespace != LOCAL_DAILY_MATCH_SOURCE_NAMESPACE
            or row.source_version != LOCAL_DAILY_INTERVAL_SOURCE_VERSION
            or row.recorded_at > now
        ):
            raise ValueError("local daily match decision differs from the claimed event")
        return row.recorded_at
    except SimulatedTradeExecutionBlocked as error:
        raise _blocked("SIMULATED_FILL_SOURCE_INVALID", "本地日线撮合记录无法精确验证") from error
    except DatabaseError as error:
        raise _blocked("SIMULATED_FILL_SOURCE_UNAVAILABLE", "本地日线撮合记录暂不可读取") from error
    except (
        ArithmeticError,
        AttributeError,
        ObjectDoesNotExist,
        SimulatedSettlementContractError,
        TypeError,
        ValueError,
    ) as error:
        raise _blocked("SIMULATED_FILL_SOURCE_INVALID", "本地日线撮合记录无法精确验证") from error
