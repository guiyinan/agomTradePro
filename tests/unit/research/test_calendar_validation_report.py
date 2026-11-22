"""Validation-only statistics, synthetic report and holdout boundary checks."""

from __future__ import annotations

import math
from dataclasses import replace
from datetime import date

import pytest

from apps.research.application.calendar_validation import run_calendar_validation
from apps.research.domain.calendar_validation_statistics import paired_loss_inference
from apps.research.domain.institutional_event_study import EventStudyError, plan_walk_forward
from apps.research.infrastructure.validation_ridge import ridge_predict
from scripts.run_cal03_synthetic_walk_forward import synthetic_case


def test_bartlett_interval_uses_actual_origin_distances() -> None:
    observations = ((10, 1.0), (11, 2.0), (13, 4.0), (14, 5.0))
    result = paired_loss_inference(observations, bandwidth=1, confidence=0.95)
    # Scores about the mean are -2,-1,+1,+2. Only two adjacent pairs contribute.
    se = math.sqrt(10 + 2 * 0.5 * 4) / 4
    assert result.mean == 3.0
    assert result.standard_error == pytest.approx(se)
    assert result.raw_p == pytest.approx(math.erfc(3 / (se * math.sqrt(2))))
    assert result.lower == pytest.approx(3 - 1.95996398454 * se)
    assert paired_loss_inference(((1, 0.0), (2, 0.0)), bandwidth=1, confidence=0.95).raw_p is None


def test_ridge_fits_only_training_and_preserves_intercept() -> None:
    prediction = ridge_predict(((0.0,), (2.0,)), (2.0, 4.0), ((1.0,), (3.0,)), penalty=2.0)
    assert prediction == pytest.approx((3.0, 4.0))
    assert ridge_predict(((1.0,), (1.0,)), (2.0, 4.0), ((100.0,),), penalty=2.0) == (3.0,)


def test_synthetic_walk_forward_honors_final_fence_and_empty_family_member() -> None:
    design, calendar, series = synthetic_case()
    target = design.targets[0]
    data = series[target]
    guarded = LastAllowed(data.prices, max(data.prices))
    reports = run_calendar_validation(
        design, calendar, {target: replace(data, prices=guarded)}, predict=ridge_predict
    )
    result = reports[0]
    assert result.target == target and result.horizon == 1
    assert len(result.folds) >= design.policy.minimum_folds
    assert all(f.validation_expected == 126 for f in result.folds)
    assert result.slices[0].inference is not None
    assert all(s.holm_adjusted_p is None for r in reports for s in r.slices)
    assert any(r.status == "insufficient_data" for r in reports if r.target != target)
    assert max(guarded.accesses) < result.final_oos_start


class LastAllowed(dict):
    def __init__(self, values, last: date):
        super().__init__(values)
        self.last = last
        self.accesses = []

    def get(self, key, default=None):
        assert key <= self.last, "final OOS input requested"
        self.accesses.append(key)
        return super().get(key, default)


def test_labels_crossing_holdout_are_excluded_before_any_data_access() -> None:
    design, calendar, series = synthetic_case()
    data = series[design.targets[0]]
    design = replace(design, targets=(data.target,))
    plan = plan_walk_forward(
        sessions=calendar.sessions,
        calendar_version=calendar.version,
        complete_price_dates=data.complete_dates,
        known_at=calendar.known_at,
        clock=design.clock,
        policy=design.policy,
        prior_final_oos_uses=0,
    )
    boundary = plan.folds[-1].validation_origins.stop
    last = calendar.sessions[boundary - 1].session_on
    calendar = replace(
        calendar,
        sessions=calendar.sessions[
            : boundary + design.policy.final_oos_sessions + max(design.clock.horizons)
        ],
    )
    guarded = replace(
        data, prices=LastAllowed(data.prices, last), features=LastAllowed(data.features, last)
    )
    reports = run_calendar_validation(
        design, calendar, {data.target: guarded}, predict=ridge_predict
    )
    for report in reports:
        assert report.final_oos_start == calendar.sessions[boundary].session_on
        fold = report.folds[-1]
        assert fold.validation_exclusions == {"LABEL_CROSSES_BOUNDARY": report.horizon}
        assert fold.validation_valid == fold.validation_expected - report.horizon
        if report.horizon == 5:
            assert "VALIDATION_COVERAGE_INSUFFICIENT" in report.reasons
    assert all(s.holm_adjusted_p is None for r in reports for s in r.slices)


def test_complete_family_keeps_model_and_correction_order() -> None:
    design, calendar, series = synthetic_case()
    reports = run_calendar_validation(design, calendar, series, predict=ridge_predict)
    samples = [s for r in reports for s in r.slices]
    assert len(reports) == 9 and len(samples) == 27
    for r in reports:
        assert r.status == "validation_only" and not r.reasons
        all_days, single, exclusive = r.slices
        assert 0 < exclusive.observations < single.observations < all_days.observations
        assert all_days.observations == sum(f.validation_valid for f in r.folds)
        assert all_days.inference.mean == pytest.approx(
            sum((f.adjusted_mse - f.calendar_mse) * f.validation_valid for f in r.folds)
            / all_days.observations,
            abs=1e-18,
        )
        assert all(sum(f.category_counts.values()) == f.validation_valid for f in r.folds)
    ordered = sorted(samples, key=lambda s: s.inference.raw_p)
    raw = [s.inference.raw_p for s in ordered]
    m = len(ordered)
    for i, sample in enumerate(ordered):
        assert sample.holm_adjusted_p == pytest.approx(
            min(1, max((m - j) * raw[j] for j in range(i + 1)))
        )
        assert sample.exploratory_bh_q == pytest.approx(
            min(1, min(m * raw[j] / (j + 1) for j in range(i, m)))
        )


@pytest.mark.parametrize("observations", [((1, 1.0), (1, 2.0)), ((1, float("nan")),)])
def test_invalid_loss_series_is_not_a_statistical_result(observations) -> None:
    with pytest.raises(EventStudyError):
        paired_loss_inference(observations, bandwidth=1, confidence=0.95)


@pytest.mark.parametrize(
    ("observations", "bandwidth", "code"),
    [
        ((), 1, "LOSS_SERIES_EMPTY"),
        (((0, 1.0),), -1, "INFERENCE_DESIGN_INVALID"),
    ],
)
def test_invalid_inference_settings_are_rejected(observations, bandwidth, code) -> None:
    with pytest.raises(EventStudyError) as error:
        paired_loss_inference(observations, bandwidth=bandwidth, confidence=0.95)
    assert error.value.code == code


def test_incomplete_sessions_and_late_features_have_distinct_exclusions() -> None:
    design, calendar, series = synthetic_case()
    data = series[design.targets[0]]
    design = replace(design, targets=(data.target,))
    plan = plan_walk_forward(
        sessions=calendar.sessions,
        calendar_version=calendar.version,
        complete_price_dates=data.complete_dates,
        known_at=calendar.known_at,
        clock=design.clock,
        policy=design.policy,
        prior_final_oos_uses=0,
    )
    start = plan.folds[0].validation_origins.start
    late = calendar.sessions[start + 10].session_on
    missing = calendar.sessions[start + 20].session_on
    item = data.features[late]
    features = dict(data.features)
    features[late] = replace(item, features=replace(item.features, recorded_at=calendar.known_at))
    data = replace(data, features=features, complete_dates=data.complete_dates - {missing})
    reports = run_calendar_validation(design, calendar, {data.target: data}, predict=ridge_predict)
    for report in reports:
        assert report.folds[0].validation_exclusions == {
            "MATCHING_FEATURE_NOT_KNOWN": 1,
            "SESSION_DATA_INCOMPLETE": report.horizon + 1,
        }
        assert report.status == "insufficient_data"
