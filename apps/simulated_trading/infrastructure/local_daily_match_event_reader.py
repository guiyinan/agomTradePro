"""Read an exact stored local daily-match event for the existing fill use case."""

from __future__ import annotations

from datetime import datetime

from django.core.exceptions import ObjectDoesNotExist
from django.db import DEFAULT_DB_ALIAS

from apps.simulated_trading.application.execution_settlement_uow import (
    SimulatedTradeExecutionBlocked,
    SimulatedTradeExecutionInputError,
)
from apps.simulated_trading.application.local_daily_match import (
    LOCAL_DAILY_MATCH_SOURCE_NAMESPACE,
    LocalDailyMatchDecisionDiscovery,
    LocalDailyMatchDecisionPage,
)
from apps.simulated_trading.application.order_reservation_fill import (
    LocalSimulatedFillEventV1,
)
from apps.simulated_trading.domain.execution_settlement_primitives import (
    _require_token,
)
from apps.simulated_trading.infrastructure.local_daily_match_models import (
    LocalDailyMatchModel,
)
from apps.simulated_trading.infrastructure.local_daily_match_repository import (
    _decode_row,
)


class DjangoLocalDailyMatchEventReader(
    LocalDailyMatchDecisionDiscovery,
):
    """Expose only exact persisted MATCHED events under their full owner locator."""

    def __init__(self, *, using: str = DEFAULT_DB_ALIAS) -> None:
        """Select the database alias for read-only event lookup."""

        if type(using) is not str or not using:
            raise SimulatedTradeExecutionInputError("撮合事件读取数据库别名无效")
        self._using = using

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
        """Return one sealed event only when it was recorded by the requested cutoff."""

        if (
            type(account_id) is not int
            or account_id <= 0
            or type(user_id) is not int
            or user_id <= 0
            or type(as_of) is not datetime
            or as_of.tzinfo is None
        ):
            raise SimulatedTradeExecutionInputError("日线成交事件读取范围或时点无效")
        try:
            if as_of.utcoffset() is None:
                raise ValueError("naive read cutoff")
            _require_token(order_idempotency_key, "order_idempotency_key", max_length=128)
            _require_token(source_namespace, "source_namespace", max_length=128)
            _require_token(fill_event_id, "fill_event_id", max_length=128)
        except (ArithmeticError, TypeError, ValueError) as error:
            raise SimulatedTradeExecutionInputError("日线成交事件定位无效") from error
        if source_namespace != LOCAL_DAILY_MATCH_SOURCE_NAMESPACE:
            raise SimulatedTradeExecutionInputError("日线成交事件命名空间不受支持")

        rows = list(
            LocalDailyMatchModel._base_manager.using(self._using)
            .select_related("account", "reservation")
            .filter(
                account_id=account_id,
                account__user_id=user_id,
                account__account_type="simulated",
                account__user__is_active=True,
                reservation__owner_user_id=user_id,
                reservation__idempotency_key=order_idempotency_key,
                source_namespace=source_namespace,
                event_id=fill_event_id,
            )
            .order_by("pk")[:2]
        )
        if len(rows) > 1:
            raise _blocked("LOCAL_DAILY_MATCH_RECORD_INVALID", "成交事件定位对应多条日线撮合记录")
        if not rows:
            return None
        try:
            decision = _decode_row(rows[0], replayed=False)
            if decision.result.outcome.value != LocalDailyMatchModel.OUTCOME_MATCHED:
                return None
            if decision.event is None:
                raise ValueError("matched decision has no fill event")
            if decision.event.recorded_at > as_of:
                return None
            return decision.event
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
                "LOCAL_DAILY_MATCH_RECORD_INVALID",
                "日线成交事件与持久撮合决定无法精确核对",
            ) from error

    def discover(
        self,
        *,
        account_id: int,
        user_id: int,
        order_idempotency_key: str,
        limit: int = 50,
        cursor: int | None,
        as_of: datetime,
    ) -> LocalDailyMatchDecisionPage:
        """Page decisions recorded by the cutoff without source reads or absence claims."""

        if (
            type(account_id) is not int
            or account_id <= 0
            or type(user_id) is not int
            or user_id <= 0
            or type(limit) is not int
            or not 1 <= limit <= 100
            or (cursor is not None and (type(cursor) is not int or cursor <= 0))
            or type(as_of) is not datetime
            or as_of.tzinfo is None
        ):
            raise SimulatedTradeExecutionInputError("日线撮合历史分页范围无效")
        try:
            if as_of.utcoffset() is None:
                raise ValueError("naive read cutoff")
            _require_token(order_idempotency_key, "order_idempotency_key", max_length=128)
        except (ArithmeticError, TypeError, ValueError) as error:
            raise SimulatedTradeExecutionInputError("日线撮合历史订单定位无效") from error

        queryset = (
            LocalDailyMatchModel._base_manager.using(self._using)
            .select_related("account", "reservation")
            .filter(
                account_id=account_id,
                account__user_id=user_id,
                account__account_type="simulated",
                account__user__is_active=True,
                reservation__owner_user_id=user_id,
                reservation__idempotency_key=order_idempotency_key,
                recorded_at__lte=as_of,
            )
            .order_by("pk")
        )
        if cursor is not None:
            queryset = queryset.filter(pk__gt=cursor)
        rows = list(queryset[: limit + 1])
        has_more = len(rows) > limit
        visible_rows = rows[:limit]
        decisions = tuple(_decode_row(row, replayed=False) for row in visible_rows)
        next_cursor = visible_rows[-1].pk if has_more and visible_rows else None
        return LocalDailyMatchDecisionPage(
            items=decisions,
            has_more=has_more,
            next_cursor=next_cursor,
        )


def _blocked(code: str, message: str) -> SimulatedTradeExecutionBlocked:
    """Return the existing business exception for damaged event storage."""

    return SimulatedTradeExecutionBlocked(message, code=code)


__all__ = ("DjangoLocalDailyMatchEventReader",)
