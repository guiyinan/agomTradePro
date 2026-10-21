"""Owner-scoped historical performance shared by the TUI and compatibility API."""

from typing import Protocol, TypedDict

from apps.simulated_trading.application.query_services import (
    PerformanceHistoryRow,
    get_user_performance_payload,
)


class PerformanceCurvePayload(TypedDict):
    """A real historical series, with no request-time placeholder observation."""

    range: str
    has_history: bool
    series: list[PerformanceHistoryRow]
    value_unit: str
    return_unit: str


class PerformanceQuery(Protocol):
    """Read daily history for the exact user and optional owned account."""

    def __call__(
        self, *, user_id: int, account_id: int | None, days: int | None
    ) -> list[PerformanceHistoryRow]: ...


def build_performance_curve_payload(
    *,
    user_id: int,
    range_code: str = "ALL",
    query: PerformanceQuery | None = None,
) -> PerformanceCurvePayload:
    """Read 30/90/180/365 inclusive calendar days, or all retained history.

    Yuan and percentage are the existing DailyNetValue persistence contract.
    This endpoint reads history only; it never initializes an account or creates
    a point dated with the request time when no history exists.
    """

    ranges: dict[str, int | None] = {"1M": 30, "3M": 90, "6M": 180, "1Y": 365, "ALL": None}
    normalized_range = range_code.strip().upper()
    if normalized_range not in ranges:
        raise ValueError("range must be one of 1M, 3M, 6M, 1Y, ALL")
    owner_query = query or get_user_performance_payload
    series = owner_query(user_id=user_id, account_id=None, days=ranges[normalized_range])
    return {
        "range": normalized_range,
        "has_history": bool(series),
        "series": series,
        "value_unit": "元",
        "return_unit": "%",
    }
