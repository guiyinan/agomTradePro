"""Resolve one fill's settlement dates from the public calendar reader.

This adapter requests exact published calendar evidence at an injected read
cutoff and delegates event-time session and lag arithmetic to the Domain proof.
It does not read a matcher, mutate a ledger, or establish fill-source truth.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

from apps.simulated_trading.application.execution_settlement_uow import (
    ExecutionCalendarUnavailable,
    PublishedExecutionCalendarReader,
    SimulatedTradeExecutionBlocked,
    SimulatedTradeExecutionClock,
    SimulatedTradeExecutionInputError,
)
from apps.simulated_trading.domain.execution_settlement_calendar import (
    ExecutionCalendarEvidence,
)
from apps.simulated_trading.domain.execution_settlement_primitives import (
    SimulatedSettlementContractError,
    _require_token,
)
from apps.simulated_trading.domain.order_reservation_fill_settlement import (
    OrderFillSettlementProof,
    build_order_fill_settlement_proof,
)


def _event_clock(value: object) -> tuple[datetime, datetime]:
    """Return the original exact aware event time and its UTC instant."""

    if type(value) is not datetime or value.tzinfo is None:
        raise SimulatedTradeExecutionInputError("成交时间必须是精确的带时区时间")
    try:
        if value.utcoffset() is None:
            raise SimulatedTradeExecutionInputError("成交时间必须是精确的带时区时间")
        utc_value = value.astimezone(UTC)
    except (OverflowError, TypeError, ValueError) as error:
        raise SimulatedTradeExecutionInputError("成交时间不能表示为 UTC 时刻") from error
    return value, utc_value


def _read_cutoff(value: object) -> datetime:
    """Require the injected current-read clock to meet the public UTC reader contract."""

    if type(value) is not datetime or value.tzinfo is None:
        raise SimulatedTradeExecutionInputError("日历读取截止时间必须为带时区 UTC 时间")
    try:
        offset = value.utcoffset()
    except (OverflowError, TypeError, ValueError) as error:
        raise SimulatedTradeExecutionInputError("日历读取截止时间必须为带时区 UTC 时间") from error
    if offset != timedelta(0):
        raise SimulatedTradeExecutionInputError("日历读取截止时间必须为带时区 UTC 时间")
    return value


def _calendar_coverage_start(event_utc: datetime) -> date:
    """Request one conservative UTC-date lower bound, never a session claim.

    Python timezone offsets have an absolute value below 24 hours, so the
    previous UTC date is no later than any valid exchange-local date for this
    instant. The returned date only scopes the reader's coverage request.
    """

    try:
        return event_utc.date() - timedelta(days=1)
    except OverflowError as error:
        raise SimulatedTradeExecutionInputError("成交时间无法形成保守的日历覆盖下界") from error


class OrderFillSettlementCalendarResolver:
    """Compose the existing public calendar reader with an injected clock."""

    def __init__(
        self,
        *,
        calendar_reader: PublishedExecutionCalendarReader,
        clock: SimulatedTradeExecutionClock,
    ) -> None:
        """Bind the public published-calendar port and the current read clock."""

        self._calendar_reader = calendar_reader
        self._clock = clock

    def resolve(
        self,
        *,
        event_occurred_at: datetime,
        settlement_exchange: str,
        settlement_lag_sessions: int,
        sealed_calendar_evidence: ExecutionCalendarEvidence | None = None,
    ) -> OrderFillSettlementProof:
        """Build a proof from sealed plan evidence or the legacy current reader.

        A sealed reservation calendar is evaluated at the fill event time. The
        injected clock remains an independent guard against future events.
        Existing callers without sealed evidence retain their current-reader path.
        """

        event_time, event_utc = _event_clock(event_occurred_at)
        try:
            _require_token(settlement_exchange, "settlement_exchange")
        except SimulatedSettlementContractError as error:
            raise SimulatedTradeExecutionInputError("结算交易所标识无效") from error
        if type(settlement_lag_sessions) is not int or settlement_lag_sessions < 0:
            raise SimulatedTradeExecutionInputError("结算交易日滞后必须是非负整数")

        coverage_start = (
            _calendar_coverage_start(event_utc) if sealed_calendar_evidence is None else None
        )
        cutoff = _read_cutoff(self._clock.now())
        if event_utc > cutoff:
            raise SimulatedTradeExecutionBlocked(
                "成交事件晚于正式日历读取截止时间",
                code="FILL_SETTLEMENT_EVENT_AFTER_READ_CUTOFF",
            )

        if sealed_calendar_evidence is None:
            evidence = self._calendar_reader.get_effective_execution_calendar(
                exchange=settlement_exchange,
                as_of=cutoff,
                coverage_start=coverage_start,
            )
            if evidence is None:
                raise ExecutionCalendarUnavailable("当前截止时间没有可验证的正式交易日历")
            if type(evidence) is not ExecutionCalendarEvidence:
                raise SimulatedTradeExecutionBlocked(
                    "日历读取器未返回精确的正式日历证据",
                    code="FILL_SETTLEMENT_CALENDAR_EVIDENCE_INVALID",
                )
            proof_cutoff = cutoff
        else:
            if type(sealed_calendar_evidence) is not ExecutionCalendarEvidence:
                raise SimulatedTradeExecutionBlocked(
                    "订单封存的正式日历证据不可验证",
                    code="FILL_SETTLEMENT_CALENDAR_EVIDENCE_INVALID",
                )
            evidence = sealed_calendar_evidence
            proof_cutoff = event_time

        try:
            return build_order_fill_settlement_proof(
                calendar_evidence=evidence,
                calendar_read_cutoff=proof_cutoff,
                fill_occurred_at=event_time,
                settlement_exchange=settlement_exchange,
                settlement_lag_sessions=settlement_lag_sessions,
            )
        except SimulatedSettlementContractError as error:
            raise SimulatedTradeExecutionBlocked(
                "成交时点或正式日历不能证明该笔结算交易日",
                code="FILL_SETTLEMENT_EVIDENCE_INVALID",
            ) from error


__all__: tuple[str, ...] = ("OrderFillSettlementCalendarResolver",)
