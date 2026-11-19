"""Pure event-study primitives; registration, source qualification and I/O stay outside.

All session indices refer to one exact, complete exchange-calendar version. Callers
must provide normalized exact price versions, never a mutable latest-price pointer.
No function declares a complete study, statistical support or trading eligibility.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import date, datetime, time
from typing import Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

KnowledgeMode = Literal["market_available", "system_known"]


class EventStudyError(ValueError):
    """Reject invalid research evidence with a stable boundary-mappable reason."""

    def __init__(self, code: str) -> None:
        """Keep the rejection code without importing framework exceptions."""
        self.code = code
        super().__init__(code)


@dataclass(frozen=True, slots=True)
class Session:
    """One eligible exchange session; omitted holidays are never synthesized."""

    session_on: date
    closes_at: datetime


@dataclass(frozen=True, slots=True)
class StudyClock:
    """Explicit preregistered local prediction clock and eligible horizons."""

    timezone_name: str
    local_cutoff: time
    horizons: tuple[int, ...]

    def __post_init__(self) -> None:
        """Require a real zone, naive local time and distinct positive horizons."""
        try:
            ZoneInfo(self.timezone_name)
        except (ValueError, ZoneInfoNotFoundError) as exc:
            raise EventStudyError("STUDY_TIMEZONE_INVALID") from exc
        if self.local_cutoff.tzinfo is not None:
            raise EventStudyError("STUDY_CLOCK_INVALID")
        if not self.horizons or any(type(h) is not int or h < 1 for h in self.horizons):
            raise EventStudyError("STUDY_HORIZONS_INVALID")
        if len(set(self.horizons)) != len(self.horizons):
            raise EventStudyError("STUDY_HORIZONS_INVALID")


@dataclass(frozen=True, slots=True)
class PriceVersion:
    """Normalized official close and the exact version's independent clocks."""

    session_on: date
    price: float | None
    version_id: str
    available_at: datetime
    first_seen_at: datetime
    recorded_at: datetime


@dataclass(frozen=True, slots=True)
class LabelInterval:
    """Half-open interval of actual return-session indices, [start, stop)."""

    calendar_version: str
    start: int
    stop: int

    def __post_init__(self) -> None:
        """Reject empty, reversed, negative or unversioned label intervals."""
        if (
            not self.calendar_version.strip()
            or type(self.start) is not int
            or type(self.stop) is not int
            or self.start < 0
            or self.stop <= self.start
        ):
            raise EventStudyError("LABEL_INTERVAL_INVALID")


@dataclass(frozen=True, slots=True)
class SquaredReturnLabel:
    """Unannualized sum with provenance and its earliest usable knowledge time."""

    value: float
    prediction_cutoff: datetime
    origin_index: int
    interval: LabelInterval
    usable_at: datetime
    source_versions: tuple[str, ...]
    knowledge_mode: KnowledgeMode


def build_squared_return_label(
    *,
    sessions: tuple[Session, ...],
    calendar_version: str,
    prices: tuple[PriceVersion, ...],
    prediction_cutoff: datetime,
    label_known_at: datetime,
    horizon: int,
    clock: StudyClock,
    knowledge_mode: KnowledgeMode,
) -> SquaredReturnLabel:
    """Compute sum(log(P[t+i])-log(P[t+i-1]))**2 after full label maturity.

    Origin is the last close strictly before the registered day-end cutoff.
    Its exact price must already be known at prediction; future closes must be
    known at label_known_at. Log differences avoid finite-price ratio overflow.
    Missing required prices fail closed; prices outside this label are ignored.
    """
    _require_aware(prediction_cutoff)
    _require_aware(label_known_at)
    _require_mode(knowledge_mode)
    _validate_sessions(sessions, clock.timezone_name)
    if type(horizon) is not int or horizon not in clock.horizons:
        raise EventStudyError("HORIZON_NOT_REGISTERED")
    local = prediction_cutoff.astimezone(ZoneInfo(clock.timezone_name))
    origins = [i for i, session in enumerate(sessions) if session.closes_at < prediction_cutoff]
    if not origins:
        raise EventStudyError("PREDICTION_CUTOFF_INVALID")
    origin = origins[-1]
    if local.time() != clock.local_cutoff or sessions[origin].session_on != local.date():
        raise EventStudyError("PREDICTION_CUTOFF_INVALID")
    stop = origin + horizon + 1
    if stop > len(sessions) or sessions[stop - 1].closes_at > label_known_at:
        raise EventStudyError("LABEL_UNMATURED")
    required = sessions[origin:stop]
    selected: list[PriceVersion] = []
    usable_times: list[datetime] = []
    for index, session in enumerate(required):
        rows = [row for row in prices if row.session_on == session.session_on]
        if not rows:
            raise EventStudyError("PRICE_MISSING")
        if len(rows) != 1:
            raise EventStudyError("PRICE_AMBIGUOUS")
        row = rows[0]
        if row.price is None or not math.isfinite(row.price) or row.price <= 0:
            raise EventStudyError("PRICE_INVALID")
        if not row.version_id.strip():
            raise EventStudyError("PRICE_VERSION_REQUIRED")
        known_at = _version_known_at(
            row.available_at, row.first_seen_at, row.recorded_at, knowledge_mode
        )
        if row.available_at < session.closes_at:
            raise EventStudyError("PRICE_PRECEDES_CLOSE")
        if known_at > (prediction_cutoff if index == 0 else label_known_at):
            raise EventStudyError("PRICE_NOT_KNOWN")
        selected.append(row)
        usable_times.append(max(known_at, session.closes_at))
    logs = [math.log(row.price) for row in selected if row.price is not None]
    value = math.fsum((right - left) ** 2 for left, right in zip(logs, logs[1:], strict=False))
    return SquaredReturnLabel(
        value=value,
        prediction_cutoff=prediction_cutoff,
        origin_index=origin,
        interval=LabelInterval(calendar_version, origin + 1, stop),
        usable_at=max(usable_times),
        source_versions=tuple(row.version_id for row in selected),
        knowledge_mode=knowledge_mode,
    )


def purge_training_labels(
    training: tuple[SquaredReturnLabel, ...],
    held_out: tuple[SquaredReturnLabel, ...],
    *,
    held_out_segments: tuple[LabelInterval, ...],
    fit_at: datetime,
    minimum_separation_sessions: int,
    embargo_sessions: int,
) -> tuple[SquaredReturnLabel, ...]:
    """Purge overlap, enforce full-session gaps, then embargo held-out origins.

    Separation is the number of complete return sessions strictly between two
    half-open label intervals. Boundary-only contact is not overlap (gap zero).
    Held-out segments are half-open *prediction-origin* indices. Embargo starts
    at each segment's stop, independent of the label-interval purge. These are
    exchange-session counts, never natural-day timedeltas.
    """
    _require_aware(fit_at)
    for count in (minimum_separation_sessions, embargo_sessions):
        if type(count) is not int or count < 0:
            raise EventStudyError("SPLIT_POLICY_INVALID")
    if not held_out or not held_out_segments:
        raise EventStudyError("HELD_OUT_REQUIRED")
    intervals = tuple(row.interval for row in training + held_out) + held_out_segments
    if len({interval.calendar_version for interval in intervals}) != 1:
        raise EventStudyError("CALENDAR_VERSION_MISMATCH")
    if len({row.knowledge_mode for row in training + held_out}) != 1:
        raise EventStudyError("KNOWLEDGE_MODE_MISMATCH")
    if any(
        not any(segment.start <= row.origin_index < segment.stop for segment in held_out_segments)
        for row in held_out
    ):
        raise EventStudyError("HELD_OUT_SEGMENT_MISMATCH")
    kept: list[SquaredReturnLabel] = []
    for row in training:
        _require_aware(row.usable_at)
        _require_aware(row.prediction_cutoff)
        if row.usable_at > fit_at or row.prediction_cutoff > fit_at:
            raise EventStudyError("TRAINING_LABEL_NOT_KNOWN")
        separated = all(
            max(row.interval.start - other.interval.stop, other.interval.start - row.interval.stop)
            >= minimum_separation_sessions
            for other in held_out
        )
        embargoed = any(
            segment.stop <= row.origin_index < segment.stop + embargo_sessions
            for segment in held_out_segments
        )
        if separated and not embargoed:
            kept.append(row)
    return tuple(kept)


@dataclass(frozen=True, slots=True)
class MatchingFeatures:
    """PIT covariates only; no future return or future-volatility label fields."""

    sample_id: str
    prediction_cutoff: datetime
    observed_through: datetime
    available_at: datetime
    first_seen_at: datetime
    recorded_at: datetime
    weekday: int
    month: int
    market_state: str
    lagged_volatility: float
    event_ids: tuple[str, ...]


def match_controls(
    target: MatchingFeatures,
    candidates: tuple[MatchingFeatures, ...],
    *,
    volatility_tolerance: float,
    knowledge_mode: KnowledgeMode,
    timezone_name: str,
) -> tuple[MatchingFeatures, ...]:
    """Match historical non-event windows using each window's known covariates.

    The caller supplies source-qualified event markers and causal market-state
    features. Future candidate windows are excluded before reading covariates.
    Output order is stable by sample identity, independent of input order.
    """
    _require_mode(knowledge_mode)
    if not math.isfinite(volatility_tolerance) or volatility_tolerance < 0:
        raise EventStudyError("MATCHING_TOLERANCE_INVALID")
    zone = ZoneInfo(timezone_name)
    _validate_features(target, knowledge_mode, zone)
    if not target.event_ids:
        raise EventStudyError("TARGET_EVENT_REQUIRED")
    seen = {target.sample_id}
    matched: list[MatchingFeatures] = []
    for row in candidates:
        _require_aware(row.prediction_cutoff)
        if row.prediction_cutoff > target.prediction_cutoff:
            continue
        _validate_features(row, knowledge_mode, zone)
        if row.sample_id in seen:
            raise EventStudyError("MATCHING_IDENTITY_DUPLICATE")
        seen.add(row.sample_id)
        if (
            not row.event_ids
            and row.weekday == target.weekday
            and row.month == target.month
            and row.market_state == target.market_state
            and abs(row.lagged_volatility - target.lagged_volatility) <= volatility_tolerance
        ):
            matched.append(row)
    return tuple(sorted(matched, key=lambda row: row.sample_id))


def six_category_contrast(
    category: str, *, categories: tuple[str, ...], reference: str
) -> tuple[int, ...]:
    """Encode the existing calendar's six classes against an explicit reference.

    The all-zero vector is the reference class, never a non-six-period day.
    This is an unadjusted design component; it makes no statistical claim.
    """
    if (
        len(categories) != 6
        or len(set(categories)) != 6
        or any(not item.strip() for item in categories)
        or reference not in categories
        or category not in categories
    ):
        raise EventStudyError("SIX_CATEGORY_INVALID")
    return tuple(int(category == item) for item in categories if item != reference)


@dataclass(frozen=True, slots=True)
class SampleGateSpec:
    """Versioned thresholds supplied by the frozen research specification."""

    coverage_min: float
    distinct_total_min: int
    training_min: int
    validation_min: int
    oos_min: int

    def __post_init__(self) -> None:
        """Prevent invalid thresholds without supplying business defaults."""
        if not math.isfinite(self.coverage_min) or not 0 < self.coverage_min <= 1:
            raise EventStudyError("SAMPLE_GATE_SPEC_INVALID")
        for count in (
            self.distinct_total_min,
            self.training_min,
            self.validation_min,
            self.oos_min,
        ):
            if type(count) is not int or count < 1:
                raise EventStudyError("SAMPLE_GATE_SPEC_INVALID")


@dataclass(frozen=True, slots=True)
class SampleSupport:
    """Per-target/family/horizon event identities after all label exclusions.

    Historical validation events may enter later expanding training folds. The
    final OOS identity set stays disjoint from both; total support uses the union.
    """

    expected_sessions: int
    valid_sessions: int
    training_events: frozenset[str]
    validation_events: frozenset[str]
    oos_events: frozenset[str]


def evaluate_sample_gate(support: SampleSupport, spec: SampleGateSpec) -> tuple[str, ...]:
    """Return stable insufficient-data reasons; empty reasons pass only this gate.

    This does not check the full walk-forward design, infer significance or pool
    different targets. The caller maps any reason to insufficient_data and must
    additionally enforce the frozen history, folds and one-use final OOS rules.
    """
    if (
        type(support.expected_sessions) is not int
        or type(support.valid_sessions) is not int
        or not 0 <= support.valid_sessions <= support.expected_sessions
        or support.expected_sessions < 1
    ):
        raise EventStudyError("SESSION_COUNTS_INVALID")
    train, validation, oos = support.training_events, support.validation_events, support.oos_events
    if any(not identity.strip() for identity in train | validation | oos):
        raise EventStudyError("EVENT_IDENTITY_REQUIRED")
    if train & oos or validation & oos:
        raise EventStudyError("EVENT_SPLIT_OVERLAP")
    checks = (
        (
            support.valid_sessions / support.expected_sessions < spec.coverage_min,
            "SESSION_COVERAGE_INSUFFICIENT",
        ),
        (len(train | validation | oos) < spec.distinct_total_min, "DISTINCT_EVENTS_INSUFFICIENT"),
        (len(train) < spec.training_min, "TRAINING_EVENTS_INSUFFICIENT"),
        (len(validation) < spec.validation_min, "VALIDATION_EVENTS_INSUFFICIENT"),
        (len(oos) < spec.oos_min, "OOS_EVENTS_INSUFFICIENT"),
    )
    return tuple(reason for failed, reason in checks if failed)


def holm_adjusted_p_values(p_values: tuple[float, ...]) -> tuple[float, ...]:
    """Adjust the complete preregistered hypothesis family in original order.

    The caller must include every hypothesis, target, horizon and subsample in
    the frozen family. Missing test results must block correction, not shrink
    the family. Existing BH q-value computation remains separate and exploratory.
    """
    if any(not math.isfinite(value) or not 0 <= value <= 1 for value in p_values):
        raise EventStudyError("P_VALUE_INVALID")
    ranked = sorted(enumerate(p_values), key=lambda item: (item[1], item[0]))
    adjusted = [1.0] * len(p_values)
    running = 0.0
    for rank, (index, value) in enumerate(ranked):
        running = max(running, (len(p_values) - rank) * value)
        adjusted[index] = min(1.0, running)
    return tuple(adjusted)


def _require_aware(value: datetime) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise EventStudyError("TIMEZONE_REQUIRED")


def _require_mode(mode: KnowledgeMode) -> None:
    if mode not in ("market_available", "system_known"):
        raise EventStudyError("KNOWLEDGE_MODE_INVALID")


def _version_known_at(
    available_at: datetime, first_seen_at: datetime, recorded_at: datetime, mode: KnowledgeMode
) -> datetime:
    for value in (available_at, first_seen_at, recorded_at):
        _require_aware(value)
    if first_seen_at > recorded_at:
        raise EventStudyError("VERSION_CLOCK_ORDER_INVALID")
    return max(available_at, first_seen_at, recorded_at) if mode == "system_known" else available_at


def _validate_sessions(sessions: tuple[Session, ...], timezone_name: str) -> None:
    if not sessions:
        raise EventStudyError("CALENDAR_INVALID")
    zone = ZoneInfo(timezone_name)
    for index, row in enumerate(sessions):
        _require_aware(row.closes_at)
        if (
            type(row.session_on) is not date
            or row.closes_at.astimezone(zone).date() != row.session_on
        ):
            raise EventStudyError("CALENDAR_INVALID")
        if index and (
            sessions[index - 1].session_on >= row.session_on
            or sessions[index - 1].closes_at >= row.closes_at
        ):
            raise EventStudyError("CALENDAR_INVALID")


def _validate_features(row: MatchingFeatures, mode: KnowledgeMode, zone: ZoneInfo) -> None:
    _require_aware(row.prediction_cutoff)
    _require_aware(row.observed_through)
    known = _version_known_at(row.available_at, row.first_seen_at, row.recorded_at, mode)
    if row.observed_through > row.prediction_cutoff or known > row.prediction_cutoff:
        raise EventStudyError("MATCHING_FEATURE_NOT_KNOWN")
    if row.observed_through > row.available_at:
        raise EventStudyError("MATCHING_FEATURE_CLOCK_INVALID")
    local = row.prediction_cutoff.astimezone(zone)
    if (
        not row.sample_id.strip()
        or not row.market_state.strip()
        or type(row.weekday) is not int
        or not 0 <= row.weekday <= 6
        or type(row.month) is not int
        or not 1 <= row.month <= 12
        or row.weekday != local.weekday()
        or row.month != local.month
        or not math.isfinite(row.lagged_volatility)
        or row.lagged_volatility < 0
        or any(not event_id.strip() for event_id in row.event_ids)
    ):
        raise EventStudyError("MATCHING_FEATURE_INVALID")
