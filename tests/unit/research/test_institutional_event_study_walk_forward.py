"""Outcome-blind frozen split tests on an explicitly synthetic exchange calendar."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, date, datetime, time, timedelta

import pytest

from apps.research.domain.institutional_event_study import (
    EventStudyError,
    Session,
    StudyClock,
    WalkForwardPlan,
    WalkForwardPolicy,
    plan_walk_forward,
)

# Exact test inputs from CAL-EVENT-STUDY-20261110-V1; this fixture is not a policy store.
POLICY = WalkForwardPolicy(
    minimum_history_years=8,
    minimum_complete_rows=2000,
    first_training_years=5,
    validation_sessions=126,
    minimum_folds=5,
    final_oos_sessions=504,
    minimum_separation_sessions=5,
    embargo_sessions=5,
    minimum_coverage=0.98,
)
CLOCK = StudyClock("Asia/Shanghai", time(18), (1, 3, 5))


def synthetic_calendar(
    start: date = date(2010, 1, 4), end: date = date(2024, 12, 31)
) -> tuple[Session, ...]:
    # Weekday generation is a synthetic fixture only, never a production calendar fallback.
    days = (start + timedelta(days=i) for i in range((end - start).days + 1))
    return tuple(
        Session(day, datetime.combine(day, time(7), UTC)) for day in days if day.weekday() < 5
    )


CALENDAR = synthetic_calendar()
KNOWN = datetime(2024, 12, 31, 10, tzinfo=UTC)
DATES = frozenset(row.session_on for row in CALENDAR)


def make_plan(
    *,
    sessions: tuple[Session, ...] = CALENDAR,
    complete_dates: frozenset[date] = DATES,
    known_at: datetime = KNOWN,
    policy: WalkForwardPolicy = POLICY,
    prior_uses: int = 0,
) -> WalkForwardPlan:
    return plan_walk_forward(
        sessions=sessions,
        calendar_version="synthetic-calendar-v1",
        complete_price_dates=complete_dates,
        known_at=known_at,
        clock=CLOCK,
        policy=policy,
        prior_final_oos_uses=prior_uses,
    )


def test_frozen_plan_golden_boundaries_and_replay() -> None:
    result = make_plan()
    assert make_plan() == result
    assert result.session_coverage == 1.0
    assert len(result.folds) >= 5
    first = result.folds[0]
    assert first.training_origins[0] == 0
    assert CALENDAR[first.training_origins[-1]].session_on == date(2015, 1, 5)
    assert first.validation_origins.start - first.training_origins[-1] == 10
    assert first.fit_at == datetime.combine(
        CALENDAR[first.validation_origins.start].session_on, time(10), UTC
    )
    assert result.final_oos_origins.stop - result.final_oos_origins.start == 504
    assert result.final_oos_origins.stop == len(CALENDAR) - 5
    assert result.final_fit_at == datetime.combine(
        CALENDAR[result.final_oos_origins.start].session_on, time(10), UTC
    )


def test_every_fold_preserves_actual_label_gap_and_independent_session_embargo() -> None:
    result = make_plan()
    embargoed: set[int] = set()
    for fold in result.folds:
        validation = fold.validation_origins
        assert validation.stop - validation.start == 126
        assert validation.stop <= result.final_oos_origins.start
        assert not set(fold.training_origins) & embargoed
        last_training = fold.training_origins[-1]
        # [t+1,t+6) label versus first held-out [v+1,v+6): v-t-5 full gap sessions.
        assert validation.start - last_training - 5 >= 5
        assert CALENDAR[last_training + 5].closes_at < fold.fit_at
        embargoed.update(range(validation.stop, validation.stop + 5))
    assert not set(result.final_training_origins) & embargoed
    assert result.final_oos_origins.start - result.final_training_origins[-1] - 5 >= 5


def test_future_calendar_and_date_metadata_do_not_shift_historical_final_oos() -> None:
    future = synthetic_calendar(date(2025, 1, 1), date(2025, 12, 31))
    result = make_plan(
        sessions=CALENDAR + future,
        complete_dates=DATES | frozenset(row.session_on for row in future),
    )
    assert result == make_plan()


def test_missing_price_dates_do_not_compress_exchange_session_windows() -> None:
    absent = CALENDAR[100].session_on
    result = make_plan(complete_dates=DATES - {absent})
    assert result.folds == make_plan().folds
    assert result.final_oos_origins == make_plan().final_oos_origins
    assert result.session_coverage == pytest.approx((len(DATES) - 1) / len(DATES))


@pytest.mark.parametrize(
    "kind,code",
    [
        ("rows", "COMPLETE_ROWS_INSUFFICIENT"),
        ("coverage", "SESSION_COVERAGE_INSUFFICIENT"),
        ("years", "HISTORY_INSUFFICIENT"),
        ("folds", "WALK_FORWARD_FOLDS_INSUFFICIENT"),
        ("oos", "FINAL_OOS_WINDOW_INSUFFICIENT"),
    ],
)
def test_frozen_support_failures_never_shrink_windows(kind: str, code: str) -> None:
    sessions, dates, policy = CALENDAR, DATES, POLICY
    if kind == "rows":
        dates = frozenset(row.session_on for row in CALENDAR[:1999])
    elif kind == "coverage":
        dates = DATES - frozenset(row.session_on for row in CALENDAR[:120])
    elif kind == "years":
        sessions = synthetic_calendar(date(2015, 1, 5), date(2022, 12, 30))
        dates = frozenset(row.session_on for row in sessions)
    elif kind == "folds":
        sessions = synthetic_calendar(date(2010, 1, 4), date(2018, 7, 31))
        dates = frozenset(row.session_on for row in sessions)
    else:
        policy = replace(POLICY, final_oos_sessions=10000)
    with pytest.raises(EventStudyError, match=code):
        make_plan(sessions=sessions, complete_dates=dates, policy=policy)


@pytest.mark.parametrize(
    "uses,code",
    [
        (1, "FINAL_OOS_ALREADY_USED"),
        (2, "FINAL_OOS_ALREADY_USED"),
        (-1, "FINAL_OOS_USE_COUNT_INVALID"),
        (False, "FINAL_OOS_USE_COUNT_INVALID"),
    ],
)
def test_known_final_oos_reuse_and_invalid_counts_are_rejected(uses: int, code: str) -> None:
    with pytest.raises(EventStudyError, match=code):
        make_plan(prior_uses=uses)


def test_clock_and_date_type_rejections() -> None:
    with pytest.raises(EventStudyError, match="TIMEZONE_REQUIRED"):
        make_plan(known_at=KNOWN.replace(tzinfo=None))
    with pytest.raises(EventStudyError, match="PRICE_DATE_INVALID"):
        make_plan(complete_dates=DATES | {KNOWN})
    with pytest.raises(EventStudyError, match="HISTORY_INSUFFICIENT"):
        make_plan(known_at=datetime(2000, 1, 1, tzinfo=UTC))


@pytest.mark.parametrize(
    "field,value",
    [
        ("minimum_history_years", 0),
        ("minimum_complete_rows", -1),
        ("validation_sessions", False),
        ("minimum_separation_sessions", -1),
        ("embargo_sessions", -1),
        ("minimum_coverage", 0.0),
        ("minimum_coverage", float("nan")),
        ("first_training_years", 9),
    ],
)
def test_invalid_design_policy(field: str, value: float) -> None:
    with pytest.raises(EventStudyError, match="WALK_FORWARD_POLICY_INVALID"):
        replace(POLICY, **{field: value})


def test_leap_anniversary_and_calendar_holiday_use_provided_sessions() -> None:
    leap = synthetic_calendar(date(2012, 2, 29), date(2024, 12, 31))
    plan = make_plan(sessions=leap, complete_dates=frozenset(row.session_on for row in leap))
    assert leap[plan.folds[0].training_origins[-1]].session_on == date(2017, 2, 28)
    holiday = tuple(row for row in CALENDAR if row.session_on != date(2015, 1, 5))
    plan = make_plan(sessions=holiday, complete_dates=frozenset(row.session_on for row in holiday))
    assert holiday[plan.folds[0].training_origins[-1]].session_on == date(2015, 1, 6)


def test_out_of_range_anniversary_fails_with_a_stable_policy_error() -> None:
    with pytest.raises(EventStudyError, match="WALK_FORWARD_POLICY_INVALID"):
        make_plan(policy=replace(POLICY, minimum_history_years=9999))


def test_planning_rejects_prediction_clock_before_the_actual_close() -> None:
    late_closes = tuple(
        replace(row, closes_at=row.closes_at + timedelta(hours=4)) for row in CALENDAR
    )
    with pytest.raises(EventStudyError, match="PREDICTION_CUTOFF_INVALID"):
        make_plan(sessions=late_closes)
