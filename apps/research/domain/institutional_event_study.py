"""Pure event-study primitives; registration, source qualification and I/O stay outside.

All session indices refer to one exact, complete exchange-calendar version. Callers
must provide normalized exact price versions, never a mutable latest-price pointer.
No function declares a complete study, statistical support or trading eligibility.
"""

from __future__ import annotations

import calendar
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
    """One qualified close version for a single target and exchange session.

    Supersession identifies a documented direct predecessor. A later publication
    date or a matching rounded value alone does not establish that relationship.
    """

    session_on: date
    price: float | None
    version_id: str
    available_at: datetime
    first_seen_at: datetime
    recorded_at: datetime
    supersedes_version_id: str | None = None


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
    At each cutoff, visible versions must form one documented revision chain
    for that session. Missing prices fail closed; other sessions are ignored.
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
        row, known_at = _select_close_version(
            rows, session, prediction_cutoff if index == 0 else label_known_at, knowledge_mode
        )
        if row.price is None or not math.isfinite(row.price) or row.price <= 0:
            raise EventStudyError("PRICE_INVALID")
        selected.append(row)
        usable_times.append(known_at)
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


def _select_close_version(
    rows: list[PriceVersion], session: Session, cutoff: datetime, mode: KnowledgeMode
) -> tuple[PriceVersion, datetime]:
    visible: dict[str, PriceVersion] = {}
    usable_at = session.closes_at
    for row in rows:
        known_at = _version_known_at(row.available_at, row.first_seen_at, row.recorded_at, mode)
        if known_at > cutoff:
            continue
        if not row.version_id.strip():
            raise EventStudyError("PRICE_VERSION_REQUIRED")
        if row.available_at < session.closes_at:
            raise EventStudyError("PRICE_PRECEDES_CLOSE")
        if row.version_id in visible:
            raise EventStudyError("PRICE_AMBIGUOUS")
        visible[row.version_id] = row
        usable_at = max(usable_at, known_at)
    if not visible:
        raise EventStudyError("PRICE_NOT_KNOWN")

    predecessors = {r.supersedes_version_id for r in visible.values()}
    tips = [r for key, r in visible.items() if key not in predecessors]
    if len(tips) > 1:
        raise EventStudyError("PRICE_AMBIGUOUS")
    if not tips:
        raise EventStudyError("PRICE_REVISION_CHAIN_INVALID")
    selected = tips[0]
    # Walk the explicit links. A unique tip alone can hide a disconnected cycle.
    cursor: str | None = selected.version_id
    child_available_at = selected.available_at
    while cursor is not None:
        linked = visible.pop(cursor, None)
        if linked is None or linked.available_at > child_available_at:
            raise EventStudyError("PRICE_REVISION_CHAIN_INVALID")
        child_available_at = linked.available_at
        cursor = linked.supersedes_version_id
    if visible:
        raise EventStudyError("PRICE_REVISION_CHAIN_INVALID")
    return selected, usable_at


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
    validate_matching_features(target, knowledge_mode, zone)
    if not target.event_ids:
        raise EventStudyError("TARGET_EVENT_REQUIRED")
    seen = {target.sample_id}
    matched: list[MatchingFeatures] = []
    for row in candidates:
        _require_aware(row.prediction_cutoff)
        if row.prediction_cutoff > target.prediction_cutoff:
            continue
        validate_matching_features(row, knowledge_mode, zone)
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


@dataclass(frozen=True, slots=True)
class WalkForwardPolicy:
    """Explicit frozen design thresholds; no outcome-dependent tuning defaults."""

    minimum_history_years: int
    minimum_complete_rows: int
    first_training_years: int
    validation_sessions: int
    minimum_folds: int
    final_oos_sessions: int
    minimum_separation_sessions: int
    embargo_sessions: int
    minimum_coverage: float

    def __post_init__(self) -> None:
        """Reject impossible scalar policies before constructing any windows."""
        for count in (
            self.minimum_history_years,
            self.minimum_complete_rows,
            self.first_training_years,
            self.validation_sessions,
            self.minimum_folds,
            self.final_oos_sessions,
        ):
            if type(count) is not int or count < 1:
                raise EventStudyError("WALK_FORWARD_POLICY_INVALID")
        for count in (self.minimum_separation_sessions, self.embargo_sessions):
            if type(count) is not int or count < 0:
                raise EventStudyError("WALK_FORWARD_POLICY_INVALID")
        if (
            self.first_training_years > self.minimum_history_years
            or not math.isfinite(self.minimum_coverage)
            or not 0 < self.minimum_coverage <= 1
        ):
            raise EventStudyError("WALK_FORWARD_POLICY_INVALID")


@dataclass(frozen=True, slots=True)
class WalkForwardFold:
    """One expanding fold; window indices denote prediction origins, not returns."""

    training_origins: tuple[int, ...]
    validation_origins: LabelInterval
    fit_at: datetime


@dataclass(frozen=True, slots=True)
class WalkForwardPlan:
    """Outcome-blind calendar plan, pending exact-version label and source checks."""

    folds: tuple[WalkForwardFold, ...]
    final_training_origins: tuple[int, ...]
    final_oos_origins: LabelInterval
    final_fit_at: datetime
    known_at: datetime
    session_coverage: float


def plan_walk_forward(
    *,
    sessions: tuple[Session, ...],
    calendar_version: str,
    complete_price_dates: frozenset[date],
    known_at: datetime,
    clock: StudyClock,
    policy: WalkForwardPolicy,
    prior_final_oos_uses: int,
) -> WalkForwardPlan:
    """Plan frozen expanding folds and a trailing mature final OOS without prices.

    This validates date/count support only. It never inspects endpoint values or
    certifies source/PIT qualifications. Actual labels must still pass the exact
    version/maturity builder and interval purge at each fold's fit_at. Before
    evaluating final OOS, Application must atomically claim its one use through
    the existing Research registry; this caller-supplied count is not a lock.

    The initial training origins span at least the registered calendar years
    *after* maximum-horizon purge/separation. Consecutive validation windows have
    fixed session counts; previous held-out embargo origins stay excluded from
    later expanding training sets. Missing price dates never compress calendars.
    """
    _require_aware(known_at)
    _validate_sessions(sessions, clock.timezone_name)
    if type(prior_final_oos_uses) is not int or prior_final_oos_uses < 0:
        raise EventStudyError("FINAL_OOS_USE_COUNT_INVALID")
    if prior_final_oos_uses:
        raise EventStudyError("FINAL_OOS_ALREADY_USED")
    if any(type(day) is not date for day in complete_price_dates):
        raise EventStudyError("PRICE_DATE_INVALID")
    closed = tuple(row for row in sessions if row.closes_at <= known_at)
    if not closed:
        raise EventStudyError("HISTORY_INSUFFICIENT")
    if any(_prediction_clock(row.session_on, clock) <= row.closes_at for row in closed):
        raise EventStudyError("PREDICTION_CUTOFF_INVALID")
    expected_dates = frozenset(row.session_on for row in closed)
    complete = complete_price_dates & expected_dates
    if len(complete) < policy.minimum_complete_rows:
        raise EventStudyError("COMPLETE_ROWS_INSUFFICIENT")
    coverage = len(complete) / len(closed)
    if coverage < policy.minimum_coverage:
        raise EventStudyError("SESSION_COVERAGE_INSUFFICIENT")
    if max(complete) < _anniversary(min(complete), policy.minimum_history_years):
        raise EventStudyError("HISTORY_INSUFFICIENT")
    maximum_horizon = max(clock.horizons)
    # Origins in [0, eligible_stop) have all h future sessions completed.
    eligible_stop = len(closed) - maximum_horizon
    oos_start = eligible_stop - policy.final_oos_sessions
    if oos_start <= 0:
        raise EventStudyError("FINAL_OOS_WINDOW_INSUFFICIENT")
    final_oos = LabelInterval(calendar_version, oos_start, eligible_stop)
    anniversary = _anniversary(closed[0].session_on, policy.first_training_years)
    first_training_end = next(
        index for index, row in enumerate(closed) if row.session_on >= anniversary
    )
    validation_start = first_training_end + maximum_horizon + policy.minimum_separation_sessions
    folds: list[WalkForwardFold] = []
    embargoed: set[int] = set()
    while validation_start + policy.validation_sessions <= oos_start:
        validation = LabelInterval(
            calendar_version, validation_start, validation_start + policy.validation_sessions
        )
        training = _expanding_training_origins(
            validation.start, maximum_horizon, policy.minimum_separation_sessions, embargoed
        )
        folds.append(
            WalkForwardFold(
                training_origins=training,
                validation_origins=validation,
                fit_at=_prediction_clock(closed[validation.start].session_on, clock),
            )
        )
        embargoed.update(range(validation.stop, validation.stop + policy.embargo_sessions))
        validation_start = validation.stop
    if len(folds) < policy.minimum_folds:
        raise EventStudyError("WALK_FORWARD_FOLDS_INSUFFICIENT")
    return WalkForwardPlan(
        folds=tuple(folds),
        final_training_origins=_expanding_training_origins(
            oos_start, maximum_horizon, policy.minimum_separation_sessions, embargoed
        ),
        final_oos_origins=final_oos,
        final_fit_at=_prediction_clock(closed[oos_start].session_on, clock),
        known_at=known_at,
        session_coverage=coverage,
    )


def _anniversary(day: date, years: int) -> date:
    year = day.year + years
    if year > 9999:
        raise EventStudyError("WALK_FORWARD_POLICY_INVALID")
    return date(year, day.month, min(day.day, calendar.monthrange(year, day.month)[1]))


def _prediction_clock(day: date, clock: StudyClock) -> datetime:
    return datetime.combine(day, clock.local_cutoff, ZoneInfo(clock.timezone_name))


def _expanding_training_origins(
    held_out_start: int, maximum_horizon: int, separation: int, embargoed: set[int]
) -> tuple[int, ...]:
    # For last train origin t and first held-out origin v, label gap = v-t-h.
    stop = held_out_start - maximum_horizon - separation + 1
    return tuple(index for index in range(stop) if index not in embargoed)


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


def validate_matching_features(row: MatchingFeatures, mode: KnowledgeMode, zone: ZoneInfo) -> None:
    """Check calendar covariates and their availability at their own prediction origin."""
    _require_mode(mode)
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
