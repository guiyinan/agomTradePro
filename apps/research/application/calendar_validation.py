"""Six-period walk-forward validation and receipt-bound final evaluation."""

from __future__ import annotations

import math
from collections import Counter
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import date, datetime
from typing import Protocol
from zoneinfo import ZoneInfo

from apps.research.domain.calendar_validation_statistics import LossInference, paired_loss_inference
from apps.research.domain.event_study_control import (
    EventStudyBinding,
    EventStudyControlError,
    FinalOOSClaim,
)
from apps.research.domain.institutional_event_study import (
    EventStudyError,
    KnowledgeMode,
    MatchingFeatures,
    PriceVersion,
    SampleGateSpec,
    SampleSupport,
    Session,
    StudyClock,
    WalkForwardFold,
    WalkForwardPlan,
    WalkForwardPolicy,
    build_squared_return_label,
    evaluate_sample_gate,
    holm_adjusted_p_values,
    plan_walk_forward,
    six_category_contrast,
    validate_matching_features,
)
from apps.research.domain.statistics import benjamini_hochberg_q_values


class ValidationPredictor(Protocol):
    """Fit on training features/labels and predict from validation features alone."""

    def __call__(
        self,
        training: tuple[tuple[float, ...], ...],
        outcomes: tuple[float, ...],
        validation: tuple[tuple[float, ...], ...],
        *,
        penalty: float,
    ) -> tuple[float, ...]: ...


@dataclass(frozen=True)
class ValidationDesign:
    """Frozen calendar design plus explicit, pre-outcome validation model choices."""

    targets: tuple[str, ...]
    clock: StudyClock
    policy: WalkForwardPolicy
    gates: SampleGateSpec
    categories: tuple[str, ...]
    reference: str
    states: tuple[str, ...]
    mode: KnowledgeMode
    ridge_penalty: float
    hac_lags: int
    confidence: float

    def __post_init__(self) -> None:
        """Reject ambiguous model levels or inference settings before reading observations."""
        for levels in (self.targets, self.states):
            if not levels or len(set(levels)) != len(levels) or any(not s.strip() for s in levels):
                raise EventStudyError("VALIDATION_DESIGN_INVALID")
        six_category_contrast(self.reference, categories=self.categories, reference=self.reference)
        if (
            not math.isfinite(self.ridge_penalty)
            or self.ridge_penalty <= 0
            or type(self.hac_lags) is not int
            or self.hac_lags < max(self.clock.horizons) - 1
            or not 0 < self.confidence < 1
            or self.mode not in ("system_known", "market_available")
        ):
            raise EventStudyError("VALIDATION_DESIGN_INVALID")


@dataclass(frozen=True)
class ValidationCalendar:
    """Full date-only planning metadata. Outcomes are supplied separately."""

    sessions: tuple[Session, ...]
    version: str
    known_at: datetime


@dataclass(frozen=True)
class PeriodObservation:
    """Causal covariates plus one calendar window and its known overlapping events.

    features.event_ids names additional events active at the prediction origin.
    window_other_events covers additional scheduled events in the entire six-period window.
    """

    features: MatchingFeatures
    category: str
    window_id: str
    elapsed_month_sessions: int
    window_other_events: tuple[str, ...]


@dataclass(frozen=True)
class ValidationSeries:
    """Single-target normalized inputs. Only requested pre-holdout dates are looked up."""

    target: str
    complete_dates: frozenset[date]
    prices: Mapping[date, tuple[PriceVersion, ...]]
    features: Mapping[date, PeriodObservation]


@dataclass(frozen=True)
class _Row:
    origin: int
    features: PeriodObservation
    value: float
    historical: tuple[float, ...]
    adjusted: tuple[float, ...]
    calendar: tuple[float, ...]


@dataclass(frozen=True)
class ValidationFoldResult:
    """Training/validation denominators, exclusions and validation MSE of each model."""

    fit_at: datetime
    score_at: datetime
    first_validation: date
    last_validation: date
    training_expected: int
    training_valid: int
    validation_expected: int
    validation_valid: int
    training_exclusions: dict[str, int]
    validation_exclusions: dict[str, int]
    category_counts: dict[str, int]
    category_mean_label: dict[str, float | None]
    historical_mse: float | None
    adjusted_mse: float | None
    calendar_mse: float | None
    reasons: tuple[str, ...]


@dataclass(frozen=True)
class ValidationSlice:
    """Paired validation loss estimate for one prespecified overlap sensitivity."""

    name: str
    observations: int
    training_windows: int
    minimum_fold_training_windows: int
    validation_windows: int
    distinct_windows: int
    inference: LossInference | None
    reasons: tuple[str, ...]
    holm_adjusted_p: float | None = None
    exploratory_bh_q: float | None = None


@dataclass(frozen=True)
class CalendarValidationReport:
    """Per target and horizon, with no final OOS observations, gates or claims."""

    target: str
    horizon: int
    status: str
    reasons: tuple[str, ...]
    final_oos_start: date | None
    folds: tuple[ValidationFoldResult, ...]
    slices: tuple[ValidationSlice, ...]


# These are three views of the same fitted calendar model, not three refits.
_SLICES = ("all", "single_event", "exclusive_window")


def _include(name: str, row: _Row) -> bool:
    if name == "single_event":
        return not row.features.features.event_ids
    if name == "exclusive_window":
        return not row.features.window_other_events
    return True


def _row(
    origin: int,
    horizon: int,
    known_at: datetime,
    sessions: tuple[Session, ...],
    version: str,
    data: ValidationSeries,
    design: ValidationDesign,
    zone: ZoneInfo,
) -> _Row:
    window = sessions[origin : origin + horizon + 1]
    if any(session.session_on not in data.complete_dates for session in window):
        raise EventStudyError("SESSION_DATA_INCOMPLETE")
    day = window[0].session_on
    item = data.features.get(day)
    if item is None:
        raise EventStudyError("FEATURE_MISSING")
    cov = item.features
    cutoff = datetime.combine(day, design.clock.local_cutoff, zone)
    if cov.prediction_cutoff != cutoff:
        raise EventStudyError("FEATURE_ORIGIN_MISMATCH")
    validate_matching_features(cov, design.mode, zone)
    if (
        cov.market_state not in design.states
        or not item.window_id.strip()
        or type(item.elapsed_month_sessions) is not int
        or not 1 <= item.elapsed_month_sessions <= day.day
        or not set(cov.event_ids).issubset(item.window_other_events)
        or any(not s.strip() for s in item.window_other_events)
    ):
        raise EventStudyError("PERIOD_FEATURE_INVALID")
    contrast = six_category_contrast(
        item.category, categories=design.categories, reference=design.reference
    )
    prices = tuple(row for sess in window for row in data.prices.get(sess.session_on, ()))
    label = build_squared_return_label(
        sessions=window,
        calendar_version=version,
        prices=prices,
        prediction_cutoff=cutoff,
        label_known_at=known_at,
        horizon=horizon,
        clock=design.clock,
        knowledge_mode=design.mode,
    )
    historical = (cov.lagged_volatility, *(float(cov.market_state == s) for s in design.states[1:]))
    adjusted = (
        *historical,
        *(float(cov.weekday == d) for d in range(1, 7)),
        *(float(cov.month == m) for m in range(2, 13)),
        float(item.elapsed_month_sessions),
    )
    return _Row(origin, item, label.value, historical, adjusted, (*adjusted, *contrast))


def _collect(
    origins: Sequence[int],
    horizon: int,
    known_at: datetime,
    calendar: ValidationCalendar,
    limit: int,
    data: ValidationSeries,
    design: ValidationDesign,
) -> tuple[list[_Row], dict[str, int]]:
    rows: list[_Row] = []
    excluded: Counter[str] = Counter()
    zone = ZoneInfo(design.clock.timezone_name)
    for origin in origins:
        # Check the last price required, before touching even an origin feature.
        if origin + horizon >= limit:
            excluded["LABEL_CROSSES_BOUNDARY"] += 1
            continue
        try:
            rows.append(
                _row(
                    origin,
                    horizon,
                    known_at,
                    calendar.sessions,
                    calendar.version,
                    data,
                    design,
                    zone,
                )
            )
        except EventStudyError as exc:
            excluded[exc.code] += 1
    return rows, dict(sorted(excluded.items()))


def _losses(
    training: list[_Row], validation: list[_Row], predict: ValidationPredictor, penalty: float
) -> tuple[tuple[float, ...], ...]:
    outcomes = tuple(r.value for r in training)
    result = []
    for x, v in (
        (tuple(r.historical for r in training), tuple(r.historical for r in validation)),
        (tuple(r.adjusted for r in training), tuple(r.adjusted for r in validation)),
        (tuple(r.calendar for r in training), tuple(r.calendar for r in validation)),
    ):
        predicted = predict(x, outcomes, v, penalty=penalty)
        loss = tuple((r.value - p) ** 2 for r, p in zip(validation, predicted, strict=True))
        if not all(math.isfinite(n) for n in loss):
            raise EventStudyError("VALIDATION_LOSS_INVALID")
        result.append(loss)
    return tuple(result)


def _evaluate_fold(
    fold: WalkForwardFold,
    label_limit: int,
    calendar: ValidationCalendar,
    data: ValidationSeries,
    design: ValidationDesign,
    horizon: int,
    predict: ValidationPredictor,
) -> tuple[ValidationFoldResult, list[_Row], list[_Row], tuple[float, ...]]:
    start, stop = fold.validation_origins.start, fold.validation_origins.stop
    # Label intervals are [origin+1, origin+h+1). The last training return may be
    # at start-separation, leaving exactly separation sessions before start+1.
    training, train_ex = _collect(
        fold.training_origins,
        horizon,
        fold.fit_at,
        calendar,
        start - design.policy.minimum_separation_sessions + 1,
        data,
        design,
    )
    score_day = calendar.sessions[min(stop - 1 + horizon, label_limit - 1)].session_on
    score_at = min(
        calendar.known_at,
        datetime.combine(
            score_day, design.clock.local_cutoff, ZoneInfo(design.clock.timezone_name)
        ),
    )
    validation, val_ex = _collect(
        range(start, stop), horizon, score_at, calendar, label_limit, data, design
    )
    counts = Counter(r.features.category for r in validation)
    reasons = []
    if len(training) / len(fold.training_origins) < design.gates.coverage_min:
        reasons.append("TRAINING_COVERAGE_INSUFFICIENT")
    if len(validation) / (stop - start) < design.gates.coverage_min:
        reasons.append("VALIDATION_COVERAGE_INSUFFICIENT")
    if {r.features.category for r in training} != set(design.categories):
        reasons.append("TRAINING_CATEGORY_MISSING")
    if len({r.features.window_id for r in training}) < design.gates.training_min:
        reasons.append("TRAINING_EVENTS_INSUFFICIENT")
    means: tuple[float | None, ...] = (None, None, None)
    delta: tuple[float, ...] = ()
    if not reasons:
        losses = _losses(training, validation, predict, design.ridge_penalty)
        means = tuple(math.fsum(values) / len(values) for values in losses)
        delta = tuple(a - b for a, b in zip(losses[1], losses[2], strict=True))
    result = ValidationFoldResult(
        fold.fit_at,
        score_at,
        calendar.sessions[start].session_on,
        calendar.sessions[stop - 1].session_on,
        len(fold.training_origins),
        len(training),
        stop - start,
        len(validation),
        train_ex,
        val_ex,
        {c: counts[c] for c in design.categories},
        {
            c: (
                math.fsum(r.value for r in validation if r.features.category == c) / counts[c]
                if counts[c]
                else None
            )
            for c in design.categories
        },
        means[0],
        means[1],
        means[2],
        tuple(reasons),
    )
    return result, training, validation, delta


def _target(
    design: ValidationDesign,
    calendar: ValidationCalendar,
    data: ValidationSeries,
    plan: WalkForwardPlan,
    horizon: int,
    predict: ValidationPredictor,
) -> tuple[CalendarValidationReport, dict[str, set[str]]]:
    folds = []
    samples: dict[str, list[tuple[int, float]]] = {k: [] for k in _SLICES}
    train_ids: dict[str, set[str]] = {k: set() for k in _SLICES}
    fold_training_counts: dict[str, list[int]] = {k: [] for k in _SLICES}
    val_ids: dict[str, set[str]] = {k: set() for k in _SLICES}
    for fold in plan.folds:
        result, train, val, delta = _evaluate_fold(
            fold, plan.final_oos_origins.start, calendar, data, design, horizon, predict
        )
        folds.append(result)
        for name in _SLICES:
            training_windows = {r.features.window_id for r in train if _include(name, r)}
            train_ids[name].update(training_windows)
            fold_training_counts[name].append(len(training_windows))
            if result.reasons:
                continue
            for r, d in zip(val, delta, strict=True):
                if _include(name, r):
                    samples[name].append((r.origin, d))
                    val_ids[name].add(r.features.window_id)
    fold_reasons = tuple(sorted({reason for f in folds for reason in f.reasons}))
    slices = []
    for name in _SLICES:
        tr, va = train_ids[name], val_ids[name]
        minimum_training = min(fold_training_counts[name])
        reasons = list(fold_reasons)
        if (
            minimum_training < design.gates.training_min
            or len(va) < design.gates.validation_min
            or len(tr | va) < design.gates.distinct_total_min
        ):
            reasons.append("EVENT_SUPPORT_INSUFFICIENT")
        inference = None
        if not reasons:
            inference = paired_loss_inference(
                tuple(samples[name]), bandwidth=design.hac_lags, confidence=design.confidence
            )
            if inference.raw_p is None:
                reasons.append("LOSS_INFERENCE_UNAVAILABLE")
        slices.append(
            ValidationSlice(
                name,
                len(samples[name]),
                len(tr),
                minimum_training,
                len(va),
                len(tr | va),
                inference,
                tuple(reasons),
            )
        )
    all_reasons = tuple(sorted({r for s in slices for r in s.reasons}))
    report = CalendarValidationReport(
        data.target,
        horizon,
        "insufficient_data" if all_reasons else "validation_only",
        all_reasons,
        calendar.sessions[plan.final_oos_origins.start].session_on,
        tuple(folds),
        tuple(slices),
    )
    return report, val_ids


def run_calendar_validation(
    design: ValidationDesign,
    calendar: ValidationCalendar,
    series: Mapping[str, ValidationSeries],
    *,
    predict: ValidationPredictor,
) -> tuple[CalendarValidationReport, ...]:
    """Fit expanding training windows, score validation, and correct only the full family.

    The planner reads session metadata for the holdout. No feature, price, label,
    final-training score, or use receipt is requested from that interval.
    """
    reports = []
    for code in design.targets:
        try:
            data = series.get(code)
            if data is None or data.target != code:
                raise EventStudyError("TARGET_DATA_MISSING")
            plan = plan_walk_forward(
                sessions=calendar.sessions,
                calendar_version=calendar.version,
                complete_price_dates=data.complete_dates,
                known_at=calendar.known_at,
                clock=design.clock,
                policy=design.policy,
                prior_final_oos_uses=0,
            )
        except EventStudyError as exc:
            for h in design.clock.horizons:
                reports.append(
                    CalendarValidationReport(
                        code,
                        h,
                        "insufficient_data",
                        (exc.code,),
                        None,
                        (),
                        tuple(
                            ValidationSlice(k, 0, 0, 0, 0, 0, None, (exc.code,)) for k in _SLICES
                        ),
                    )
                )
            continue
        reports.extend(
            _target(design, calendar, data, plan, h, predict)[0] for h in design.clock.horizons
        )
    raw = tuple(
        s.inference.raw_p
        for r in reports
        for s in r.slices
        if s.inference is not None and s.inference.raw_p is not None and not s.reasons
    )
    if len(raw) != len(design.targets) * len(design.clock.horizons) * len(_SLICES):
        return tuple(reports)
    adjusted = iter(
        zip(holm_adjusted_p_values(raw), benjamini_hochberg_q_values(list(raw)), strict=True)
    )
    corrected = []
    for report in reports:
        slices = []
        for sample in report.slices:
            p, q = next(adjusted)
            slices.append(replace(sample, holm_adjusted_p=p, exploratory_bh_q=q))
        corrected.append(replace(report, slices=tuple(slices)))
    return tuple(corrected)


@dataclass(frozen=True)
class FinalCalendarInputs:
    """Normalized exact-version inputs resolved from the claim's immutable registry snapshot.

    The reader must verify the bound manifest, parameters, date split and complete
    registered hypothesis family before returning these inputs. Prices and features
    may be lazy. Every family key begins with its registered trial ID and a slash.
    """

    binding: EventStudyBinding
    design: ValidationDesign
    calendar: ValidationCalendar
    series: Mapping[str, ValidationSeries]
    first_origin: date
    last_origin: date
    family: tuple[str, ...]
    sibling_raw_p: Mapping[str, float]
    alpha: float


@dataclass(frozen=True)
class FinalCalendarEstimate:
    """One prespecified final holdout contrast, with support and uncertainty."""

    hypothesis: str
    support: SampleSupport
    inference: LossInference | None
    reasons: tuple[str, ...]
    status: str = "insufficient_data"
    holm_p: float | None = None
    exploratory_bh_q: float | None = None


@dataclass(frozen=True)
class FinalCalendarTarget:
    """In-sample fitted losses, walk-forward diagnostics and one final test segment."""

    target: str
    horizon: int
    validation: CalendarValidationReport
    final: ValidationFoldResult
    training_mse: tuple[float, ...] | None
    estimates: tuple[FinalCalendarEstimate, ...]


@dataclass(frozen=True)
class FinalCalendarReport:
    """Final results identified by the durable claim and exact registered inputs."""

    claim: FinalOOSClaim
    targets: tuple[FinalCalendarTarget, ...]
    family_complete: bool


def _final_calendar_target(
    inputs: FinalCalendarInputs,
    data: ValidationSeries,
    plan: WalkForwardPlan,
    horizon: int,
    predict: ValidationPredictor,
) -> FinalCalendarTarget:
    design, calendar = inputs.design, inputs.calendar
    validation, validation_ids = _target(design, calendar, data, plan, horizon, predict)
    segment = WalkForwardFold(
        plan.final_training_origins, plan.final_oos_origins, plan.final_fit_at
    )
    result, train, test, delta = _evaluate_fold(
        segment,
        plan.final_oos_origins.stop + max(design.clock.horizons),
        calendar,
        data,
        design,
        horizon,
        predict,
    )
    training_mse = None
    if not result.reasons:
        training_mse = tuple(
            math.fsum(loss) / len(loss)
            for loss in _losses(train, train, predict, design.ridge_penalty)
        )
    estimates = []
    for view in validation.slices:
        name = view.name
        valid = [r for r in test if _include(name, r)]
        support = SampleSupport(
            result.validation_expected,
            result.validation_valid,
            frozenset(r.features.window_id for r in train if _include(name, r)),
            frozenset(validation_ids[name]),
            frozenset(r.features.window_id for r in valid),
        )
        reasons = list(dict.fromkeys((*view.reasons, *result.reasons)))
        try:
            reasons.extend(evaluate_sample_gate(support, design.gates))
        except EventStudyError as exc:
            reasons.append(exc.code)
        inference = None
        if not reasons:
            inference = paired_loss_inference(
                tuple((r.origin, d) for r, d in zip(test, delta, strict=True) if _include(name, r)),
                bandwidth=design.hac_lags,
                confidence=design.confidence,
            )
            if inference.raw_p is None:
                reasons.append("LOSS_INFERENCE_UNAVAILABLE")
        estimates.append(
            FinalCalendarEstimate(
                f"{inputs.binding.trial_id}/{data.target}/{horizon}/{name}",
                support,
                inference,
                tuple(dict.fromkeys(reasons)),
            )
        )
    return FinalCalendarTarget(
        data.target, horizon, validation, result, training_mse, tuple(estimates)
    )


class FinalCalendarEvaluator:
    """Score exact-version calendar inputs through EventStudyControl.run_final_once."""

    def __init__(
        self,
        read: Callable[[FinalOOSClaim], FinalCalendarInputs],
        publish: Callable[[FinalCalendarReport], None],
        predict: ValidationPredictor,
    ) -> None:
        """Inject the verified claim-bound reader, durable report writer and frozen model."""
        self._read = read
        self._publish = publish
        self._predict = predict

    def evaluate(self, claim: FinalOOSClaim) -> None:
        """Publish final estimates only after checking binding, split, data clocks and family."""
        inputs = self._read(claim)
        if inputs.binding != claim.binding:
            raise EventStudyControlError("FINAL_INPUT_BINDING_MISMATCH")
        design, calendar = inputs.design, inputs.calendar
        if calendar.known_at > claim.claimed_at or not 0 < inputs.alpha < 1:
            raise EventStudyControlError("FINAL_INPUT_METADATA_INVALID")
        keys = {
            f"{claim.binding.trial_id}/{code}/{h}/{name}"
            for code in design.targets
            for h in design.clock.horizons
            for name in _SLICES
        }
        family = set(inputs.family)
        siblings = dict(inputs.sibling_raw_p)
        if (
            len(family) != len(inputs.family)
            or any(not key.partition("/")[0] or not key.partition("/")[2] for key in family)
            or len({key.partition("/")[0] for key in family}) != claim.cumulative_family_trials
            or not keys <= family
            or siblings.keys() - (family - keys)
            or any(not math.isfinite(p) or not 0 <= p <= 1 for p in siblings.values())
        ):
            raise EventStudyControlError("FINAL_HYPOTHESIS_FAMILY_MISMATCH")
        plans = {}
        for code in design.targets:
            data = inputs.series.get(code)
            if data is None or data.target != code:
                raise EventStudyError("TARGET_DATA_MISSING")
            plan = plan_walk_forward(
                sessions=calendar.sessions,
                calendar_version=calendar.version,
                complete_price_dates=data.complete_dates,
                known_at=calendar.known_at,
                clock=design.clock,
                policy=design.policy,
                prior_final_oos_uses=0,  # This evaluation is running under its own committed claim.
            )
            start, stop = plan.final_oos_origins.start, plan.final_oos_origins.stop
            if (calendar.sessions[start].session_on, calendar.sessions[stop - 1].session_on) != (
                inputs.first_origin,
                inputs.last_origin,
            ):
                raise EventStudyControlError("FINAL_REGISTERED_SPLIT_MISMATCH")
            plans[code] = plan
        results = tuple(
            _final_calendar_target(inputs, inputs.series[code], plans[code], h, self._predict)
            for code in design.targets
            for h in design.clock.horizons
        )
        raw = dict(siblings)
        for result in results:
            for item in result.estimates:
                if (
                    not item.reasons
                    and item.inference is not None
                    and item.inference.raw_p is not None
                ):
                    raw[item.hypothesis] = item.inference.raw_p
        complete = raw.keys() == family
        if complete:
            values = tuple(raw[key] for key in inputs.family)
            adjusted = dict(zip(inputs.family, holm_adjusted_p_values(values), strict=True))
            exploratory = dict(
                zip(inputs.family, benjamini_hochberg_q_values(list(values)), strict=True)
            )
            results = tuple(
                replace(
                    result,
                    estimates=tuple(
                        replace(
                            item,
                            holm_p=adjusted[item.hypothesis],
                            exploratory_bh_q=exploratory[item.hypothesis],
                            status=(
                                "oos_supported"
                                if item.inference is not None
                                and item.inference.mean > 0
                                and adjusted[item.hypothesis] < inputs.alpha
                                else "not_confirmed"
                            ),
                        )
                        for item in result.estimates
                    ),
                )
                for result in results
            )
        else:
            results = tuple(
                replace(
                    result,
                    estimates=tuple(
                        replace(
                            item,
                            reasons=tuple(
                                dict.fromkeys((*item.reasons, "FINAL_FAMILY_INCOMPLETE"))
                            ),
                        )
                        for item in result.estimates
                    ),
                )
                for result in results
            )
        self._publish(FinalCalendarReport(claim, results, complete))
