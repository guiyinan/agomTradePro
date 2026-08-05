"""Published Data Center adapter for governed stress-scenario calculations."""

from __future__ import annotations

import math
from collections.abc import Mapping
from datetime import UTC, date, datetime, time
from decimal import Decimal, InvalidOperation

from apps.data_center.application.public import get_published_price_bar_series
from apps.risk_center.application.scenario_dtos import ScenarioMarketDataDTO
from apps.risk_center.domain.scenarios import (
    AssetReturnSeries,
    HistoricalReturnPoint,
    HistoricalWindowParameters,
    RollingExtremeParameters,
    ScenarioRevision,
)


class ScenarioMarketDataUnavailableError(RuntimeError):
    """Raised when published point-in-time data cannot support a scenario run."""


def _aware_datetime(value: object, *, field_name: str) -> datetime:
    """Parse a source timestamp without substituting the request time."""

    parsed: datetime
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, date):
        parsed = datetime.combine(value, time.min, tzinfo=UTC)
    elif isinstance(value, str) and value.strip():
        text = value.strip().replace("Z", "+00:00")
        if "T" not in text and " " not in text:
            try:
                return datetime.combine(date.fromisoformat(text), time.min, tzinfo=UTC)
            except ValueError as exc:
                raise ScenarioMarketDataUnavailableError(f"invalid_{field_name}") from exc
        try:
            parsed = datetime.fromisoformat(text)
        except ValueError:
            try:
                parsed = datetime.combine(date.fromisoformat(text), time.min, tzinfo=UTC)
            except ValueError as exc:
                raise ScenarioMarketDataUnavailableError(f"invalid_{field_name}") from exc
    else:
        raise ScenarioMarketDataUnavailableError(f"missing_{field_name}")
    if parsed.utcoffset() is None:
        raise ScenarioMarketDataUnavailableError(f"naive_{field_name}")
    return parsed


def _decimal_close(row: Mapping[str, object]) -> Decimal:
    """Return a finite positive close from one published row."""

    value = row.get("close")
    if isinstance(value, bool):
        raise ScenarioMarketDataUnavailableError("invalid_price_close")
    try:
        parsed = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise ScenarioMarketDataUnavailableError("invalid_price_close") from exc
    if not parsed.is_finite() or parsed <= 0:
        raise ScenarioMarketDataUnavailableError("invalid_price_close")
    return parsed


def _row_date(row: Mapping[str, object]) -> date:
    """Read the price-bar observation date from a canonical payload."""

    raw = row.get("timestamp") or row.get("bar_date") or row.get("trade_date")
    return _aware_datetime(raw, field_name="price_observation").date()


def _return_series(asset_code: str, rows: list[Mapping[str, object]]) -> AssetReturnSeries:
    """Calculate close-to-close returns while preserving bar observation dates."""

    ordered = sorted(
        ((_row_date(row), _decimal_close(row)) for row in rows), key=lambda item: item[0]
    )
    if len(ordered) < 2:
        raise ScenarioMarketDataUnavailableError(f"insufficient_price_observations:{asset_code}")
    if len({item[0] for item in ordered}) != len(ordered):
        raise ScenarioMarketDataUnavailableError(f"duplicate_price_observations:{asset_code}")
    points = tuple(
        HistoricalReturnPoint(
            observed_on=current_date,
            value=(current_close / previous_close) - Decimal("1"),
        )
        for (_previous_date, previous_close), (current_date, current_close) in zip(
            ordered,
            ordered[1:],
            strict=False,
        )
        if current_date > _previous_date
    )
    return AssetReturnSeries(asset_code=asset_code, points=points)


def _date_bounds(revision: ScenarioRevision) -> tuple[date | None, date | None, int]:
    parameters = revision.parameters
    if isinstance(parameters, HistoricalWindowParameters):
        span_days = (parameters.end_date - parameters.start_date).days + 5
        return parameters.start_date, parameters.end_date, max(span_days, 2)
    if isinstance(parameters, RollingExtremeParameters):
        return None, None, max(parameters.lookback_days + 5, 2)
    return None, None, 2


class PublishedScenarioMarketDataProvider:
    """Read only explicitly published price bars; stale or missing gates block."""

    def get_market_data(
        self,
        revision: ScenarioRevision,
        *,
        asset_codes: tuple[str, ...],
        as_of_time: datetime,
    ) -> ScenarioMarketDataDTO:
        """Return source-timestamped returns and publication evidence."""

        if as_of_time.utcoffset() is None:
            raise ValueError("as_of_time must be timezone-aware")
        if not asset_codes:
            raise ScenarioMarketDataUnavailableError("portfolio_assets_missing")
        start, end, limit = _date_bounds(revision)
        bounded_end = min(end, as_of_time.date()) if end is not None else as_of_time.date()
        series: list[AssetReturnSeries] = []
        evidence_ids: list[str] = []
        published_times: list[datetime] = []
        observation_times: list[datetime] = []
        publication_ids: set[str] = set()
        for asset_code in asset_codes:
            payload = get_published_price_bar_series(
                asset_code,
                start=start,
                end=bounded_end,
                limit=limit,
            )
            blocked = bool(payload.get("must_not_use_for_decision", True))
            if blocked:
                reason = str(payload.get("blocked_reason") or "price_publication_blocked")
                raise ScenarioMarketDataUnavailableError(reason)
            publication_id = str(payload.get("publication_id") or "").strip()
            if not publication_id:
                raise ScenarioMarketDataUnavailableError("price_publication_id_missing")
            published_at = _aware_datetime(
                payload.get("published_at"), field_name="publication_time"
            )
            if published_at > as_of_time:
                raise ScenarioMarketDataUnavailableError("price_publication_from_future")
            raw_rows = payload.get("rows")
            if not isinstance(raw_rows, list):
                raise ScenarioMarketDataUnavailableError("price_rows_missing")
            rows = [row for row in raw_rows if isinstance(row, Mapping)]
            asset_series = _return_series(asset_code, rows)
            latest_observation = datetime.combine(
                asset_series.points[-1].observed_on,
                time.min,
                tzinfo=UTC,
            )
            if latest_observation > as_of_time:
                raise ScenarioMarketDataUnavailableError("price_observation_from_future")
            if any(not math.isfinite(float(point.value)) for point in asset_series.points):
                raise ScenarioMarketDataUnavailableError("non_finite_price_return")
            series.append(asset_series)
            publication_ids.add(publication_id)
            evidence_ids.append(f"{publication_id}:{asset_code}")
            published_times.append(published_at)
            observation_times.append(latest_observation)
        if len(publication_ids) != 1:
            raise ScenarioMarketDataUnavailableError("mixed_price_publications")
        return ScenarioMarketDataDTO(
            return_series=tuple(series),
            evidence_ids=tuple(evidence_ids),
            observed_at=max(observation_times),
            published_at=max(published_times),
            must_not_use_for_decision=False,
            blocked_reason="",
        )


__all__ = [
    "PublishedScenarioMarketDataProvider",
    "ScenarioMarketDataUnavailableError",
]
