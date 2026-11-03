"""Published Data Center adapter for governed stress-scenario calculations."""

from __future__ import annotations

import math
from collections.abc import Mapping
from datetime import UTC, date, datetime
from decimal import Decimal, InvalidOperation

from apps.data_center.application.public import get_published_price_bar_series
from apps.risk_center.application.scenario_dtos import ScenarioMarketDataDTO
from apps.risk_center.domain.portfolio_risk_sources import SourceObservationPrecision
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
    """Parse a real aware timestamp; a date-only value is never promoted."""

    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str) and value.strip():
        text = value.strip()
        if "T" not in text and " " not in text:
            raise ScenarioMarketDataUnavailableError(f"date_only_{field_name}")
        try:
            parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
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
    """Read a bar date without adding a time-of-day to date-precision data."""

    return _row_observation(row)[0]


def _row_observation(row: Mapping[str, object]) -> tuple[date, datetime | None]:
    """Parse one source bar as either its actual aware timestamp or an exact date."""

    raw: object | None = row.get("timestamp")
    if raw is None:
        raw = row.get("bar_date")
    if raw is None:
        raw = row.get("trade_date")
    if isinstance(raw, datetime):
        if raw.utcoffset() is None:
            raise ScenarioMarketDataUnavailableError("naive_price_observation")
        return raw.date(), raw
    if isinstance(raw, date):
        return raw, None
    if isinstance(raw, str) and raw.strip():
        text = raw.strip()
        if "T" in text or " " in text:
            timestamp = _aware_datetime(text, field_name="price_observation")
            return timestamp.date(), timestamp
        try:
            return date.fromisoformat(text), None
        except ValueError as exc:
            raise ScenarioMarketDataUnavailableError("invalid_price_observation") from exc
    raise ScenarioMarketDataUnavailableError("missing_price_observation")


def _return_series(asset_code: str, rows: list[Mapping[str, object]]) -> AssetReturnSeries:
    """Calculate close-to-close returns while preserving bar observation dates."""

    ordered = sorted(
        ((_row_observation(row)[0], _decimal_close(row)) for row in rows),
        key=lambda item: item[0],
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
        latest_observation_dates: list[date] = []
        latest_observation_times: list[datetime | None] = []
        publication_ids: set[str] = set()
        for asset_code in asset_codes:
            payload = get_published_price_bar_series(
                asset_code,
                start=start,
                end=bounded_end,
                limit=limit,
                knowledge_cutoff=as_of_time,
            )
            decision_prohibition = payload.get("must_not_use_for_decision", True)
            if type(decision_prohibition) is not bool or decision_prohibition:
                reason = str(payload.get("blocked_reason") or "price_publication_blocked")
                raise ScenarioMarketDataUnavailableError(reason)
            raw_publication_id = payload.get("publication_id")
            if type(raw_publication_id) is not str or not raw_publication_id.strip():
                raise ScenarioMarketDataUnavailableError("price_publication_id_missing")
            publication_id = raw_publication_id.strip()
            published_at = _aware_datetime(
                payload.get("published_at"), field_name="publication_time"
            )
            if published_at.astimezone(UTC) > as_of_time.astimezone(UTC):
                raise ScenarioMarketDataUnavailableError("price_publication_from_future")
            raw_rows = payload.get("rows")
            if not isinstance(raw_rows, list):
                raise ScenarioMarketDataUnavailableError("price_rows_missing")
            rows = [row for row in raw_rows if isinstance(row, Mapping)]
            if len(rows) != len(raw_rows):
                raise ScenarioMarketDataUnavailableError("price_rows_invalid")
            asset_series = _return_series(asset_code, rows)
            row_observations = tuple(_row_observation(row) for row in rows)
            for row_observed_on, row_observed_at in row_observations:
                if row_observed_at is not None:
                    if row_observed_at.astimezone(UTC) > as_of_time.astimezone(UTC):
                        raise ScenarioMarketDataUnavailableError("price_observation_from_future")
                elif row_observed_on >= as_of_time.date():
                    raise ScenarioMarketDataUnavailableError(
                        "date_precision_bar_not_before_as_of_day"
                    )
            latest_on, latest_timestamp = max(
                row_observations,
                key=lambda item: item[0],
            )
            if any(not math.isfinite(float(point.value)) for point in asset_series.points):
                raise ScenarioMarketDataUnavailableError("non_finite_price_return")
            series.append(asset_series)
            publication_ids.add(publication_id)
            evidence_ids.append(f"{publication_id}:{asset_code}")
            published_times.append(published_at)
            latest_observation_dates.append(latest_on)
            latest_observation_times.append(latest_timestamp)
        if len(publication_ids) != 1:
            raise ScenarioMarketDataUnavailableError("mixed_price_publications")
        result_observed_at: datetime | None
        result_observed_on: date | None
        if all(item is not None for item in latest_observation_times):
            precision = SourceObservationPrecision.TIMESTAMP
            result_observed_at = max(
                (item for item in latest_observation_times if item is not None),
                key=lambda item: item.astimezone(UTC),
            )
            result_observed_on = None
        else:
            precision = SourceObservationPrecision.DATE
            result_observed_at = None
            result_observed_on = max(latest_observation_dates)
        return ScenarioMarketDataDTO(
            return_series=tuple(series),
            evidence_ids=tuple(evidence_ids),
            observed_at=result_observed_at,
            published_at=max(published_times),
            must_not_use_for_decision=False,
            blocked_reason="",
            observed_on=result_observed_on,
            observation_precision=precision,
        )


__all__ = [
    "PublishedScenarioMarketDataProvider",
    "ScenarioMarketDataUnavailableError",
]
