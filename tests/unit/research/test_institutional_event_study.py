"""Offline golden and rejection cases; all inputs are synthetic, never OOS results."""

from __future__ import annotations

import math
from dataclasses import replace
from datetime import UTC, date, datetime, time, timedelta

import pytest

from apps.research.domain.institutional_event_study import (
    EventStudyError,
    KnowledgeMode,
    LabelInterval,
    MatchingFeatures,
    PriceVersion,
    SampleGateSpec,
    SampleSupport,
    Session,
    SquaredReturnLabel,
    StudyClock,
    build_squared_return_label,
    evaluate_sample_gate,
    holm_adjusted_p_values,
    match_controls,
    purge_training_labels,
    six_category_contrast,
)

# Portable test inputs, checked against the retained frozen specification offline.
# Source SHA256: 29a44d0cd2670dd2a72853494d21271c9765d6584dafa4998e1df3c2a6edfe71
SPEC = {
    "knowledge_cutoff": {"timezone": "Asia/Shanghai", "local_time": "18:00:00"},
    "primary_endpoint": {"horizons_trading_days": [1, 3, 5]},
    "temporal_split": {"embargo": {"trading_days": 5}},
    "controls": {
        "six_periods": {
            "categories": ["01-05", "06-10", "11-15", "16-20", "21-25", "26-month_end"],
            "reference_category": "01-05",
        }
    },
    "sample_gates": {
        "target_expected_session_coverage_min": 0.98,
        "distinct_events_total_min": 30,
        "training_events_min": 20,
        "validation_events_total_min": 5,
        "oos_events_total_min": 5,
    },
}
CLOCK = StudyClock(
    timezone_name=SPEC["knowledge_cutoff"]["timezone"],
    local_cutoff=time.fromisoformat(SPEC["knowledge_cutoff"]["local_time"]),
    horizons=tuple(SPEC["primary_endpoint"]["horizons_trading_days"]),
)
# Explicit exchange sessions include a weekend and a synthetic holiday gap.
DATES = (date(2026, 1, 8), date(2026, 1, 9), date(2026, 1, 12)) + tuple(
    date(2026, 1, 14) + timedelta(days=i) for i in range(18)
)
SESSIONS = tuple(Session(day, datetime.combine(day, time(7), UTC)) for day in DATES)


def cutoff(index: int) -> datetime:
    return datetime.combine(DATES[index], time(10), UTC)


def prices() -> tuple[PriceVersion, ...]:
    return tuple(
        PriceVersion(
            session_on=day,
            price=100 * math.exp(index / 10),
            version_id=f"official-close-{index}",
            available_at=session.closes_at,
            first_seen_at=session.closes_at + timedelta(minutes=1),
            recorded_at=session.closes_at + timedelta(minutes=2),
        )
        for index, (day, session) in enumerate(zip(DATES, SESSIONS, strict=True))
    )


def label(origin: int = 0, horizon: int = 5) -> SquaredReturnLabel:
    return build_squared_return_label(
        sessions=SESSIONS,
        calendar_version="calendar-sha256-fixture",
        prices=prices(),
        prediction_cutoff=cutoff(origin),
        label_known_at=cutoff(len(DATES) - 1),
        horizon=horizon,
        clock=CLOCK,
        knowledge_mode="market_available",
    )


@pytest.mark.parametrize("horizon,expected", [(1, 0.01), (3, 0.03), (5, 0.05)])
def test_golden_unannualized_sum(horizon: int, expected: float) -> None:
    result = label(horizon=horizon)
    assert result.value == pytest.approx(expected, abs=1e-14)
    assert result.interval == LabelInterval("calendar-sha256-fixture", 1, horizon + 1)
    assert result.source_versions == tuple(f"official-close-{i}" for i in range(horizon + 1))


@pytest.mark.parametrize("value", [None, 0.0, -1.0, math.nan, math.inf, -math.inf])
def test_rejects_bad_required_prices(value: float | None) -> None:
    rows = list(prices())
    rows[3] = replace(rows[3], price=value)
    with pytest.raises(EventStudyError, match="PRICE_INVALID"):
        build_squared_return_label(
            sessions=SESSIONS,
            calendar_version="fixture",
            prices=tuple(rows),
            prediction_cutoff=cutoff(0),
            label_known_at=cutoff(6),
            horizon=5,
            clock=CLOCK,
            knowledge_mode="market_available",
        )


def test_flat_price_is_genuine_zero_and_one_day_is_not_standard_deviation() -> None:
    flat = tuple(replace(row, price=100.0) for row in prices())
    result = build_squared_return_label(
        sessions=SESSIONS,
        calendar_version="fixture",
        prices=flat,
        prediction_cutoff=cutoff(0),
        label_known_at=cutoff(6),
        horizon=1,
        clock=CLOCK,
        knowledge_mode="market_available",
    )
    assert result.value == 0.0
    assert label(horizon=1).value > 0.0


def revision_label(
    rows: tuple[PriceVersion, ...],
    as_of: datetime,
    mode: KnowledgeMode = "market_available",
) -> SquaredReturnLabel:
    return build_squared_return_label(
        sessions=SESSIONS,
        calendar_version="fixture",
        prices=rows,
        prediction_cutoff=cutoff(0),
        label_known_at=as_of,
        horizon=1,
        clock=CLOCK,
        knowledge_mode=mode,
    )


def test_price_revisions_respect_each_cutoff_and_knowledge_mode() -> None:
    origin, close = prices()[:2]
    later_origin = replace(
        origin,
        price=200.0,
        version_id="new-origin",
        supersedes_version_id=origin.version_id,
        available_at=cutoff(1),
    )
    corrected = replace(
        close,
        price=120.0,
        version_id="correction",
        supersedes_version_id=close.version_id,
        available_at=cutoff(2),
        first_seen_at=cutoff(3),
        recorded_at=cutoff(4),
    )
    second = replace(
        corrected,
        price=125.0,
        version_id="second",
        supersedes_version_id="correction",
        available_at=cutoff(5),
        first_seen_at=cutoff(5),
        recorded_at=cutoff(5),
    )
    rows = (second, corrected, later_origin, close, origin)
    assert revision_label(rows, cutoff(1)).source_versions == (origin.version_id, close.version_id)
    assert revision_label(rows, cutoff(3), "system_known").source_versions[-1] == close.version_id
    for mode, known in (("market_available", cutoff(2)), ("system_known", cutoff(4))):
        result = revision_label(rows, known, mode)
        assert result.source_versions == (origin.version_id, "correction")
        assert result.usable_at == known
        assert result.value == pytest.approx(math.log(1.2) ** 2)
    assert revision_label(rows, cutoff(5)).source_versions[-1] == "second"


@pytest.mark.parametrize(
    "shape", ["two_originals", "fork", "orphan", "cycle", "disconnected_cycle"]
)
def test_unproven_price_revision_order_is_rejected(shape: str) -> None:
    origin, close = prices()[:2]
    a = replace(close, version_id="a", supersedes_version_id=close.version_id)
    b = replace(a, version_id="b")
    cases = {
        "two_originals": (close, replace(a, supersedes_version_id=None)),
        "fork": (close, a, b),
        "orphan": (a,),
        "cycle": (replace(a, supersedes_version_id="b"), replace(b, supersedes_version_id="a")),
        "disconnected_cycle": (
            close,
            replace(a, supersedes_version_id="b"),
            replace(b, supersedes_version_id="a"),
        ),
    }
    with pytest.raises(EventStudyError, match="PRICE_AMBIGUOUS|PRICE_REVISION_CHAIN_INVALID"):
        revision_label((origin, *cases[shape]), cutoff(2))


def test_late_parent_limits_system_replay_and_invalid_correction_does_not_fall_back() -> None:
    origin, close = prices()[:2]
    parent = replace(close, first_seen_at=cutoff(3), recorded_at=cutoff(3))
    child = replace(
        close,
        version_id="child",
        supersedes_version_id=parent.version_id,
        available_at=cutoff(1),
        first_seen_at=cutoff(2),
        recorded_at=cutoff(2),
    )
    rows = (origin, child, parent)
    with pytest.raises(EventStudyError, match="PRICE_REVISION_CHAIN_INVALID"):
        revision_label(rows, cutoff(2), "system_known")
    assert revision_label(rows, cutoff(4), "system_known").usable_at == cutoff(3)
    with pytest.raises(EventStudyError, match="PRICE_INVALID"):
        revision_label((origin, close, replace(child, price=None)), cutoff(2))


@pytest.mark.parametrize("kind", ["missing", "duplicate", "late_origin", "late_label", "immature"])
def test_label_rejections(kind: str) -> None:
    rows = list(prices())
    known = cutoff(6)
    expected = {
        "missing": "PRICE_MISSING",
        "duplicate": "PRICE_AMBIGUOUS",
        "late_origin": "PRICE_NOT_KNOWN",
        "late_label": "PRICE_NOT_KNOWN",
        "immature": "LABEL_UNMATURED",
    }[kind]
    if kind == "missing":
        rows.pop(3)
    elif kind == "duplicate":
        rows.append(rows[3])
    elif kind == "late_origin":
        rows[0] = replace(rows[0], available_at=cutoff(1))
    elif kind == "late_label":
        rows[5] = replace(rows[5], available_at=cutoff(7))
    else:
        known = SESSIONS[5].closes_at - timedelta(microseconds=1)
    with pytest.raises(EventStudyError, match=expected):
        build_squared_return_label(
            sessions=SESSIONS,
            calendar_version="fixture",
            prices=tuple(rows),
            prediction_cutoff=cutoff(0),
            label_known_at=known,
            horizon=5,
            clock=CLOCK,
            knowledge_mode="market_available",
        )


def test_market_reconstruction_never_impersonates_system_replay() -> None:
    rows = tuple(replace(row, first_seen_at=cutoff(10), recorded_at=cutoff(10)) for row in prices())
    kwargs = {
        "sessions": SESSIONS,
        "calendar_version": "fixture",
        "prices": rows,
        "prediction_cutoff": cutoff(0),
        "label_known_at": cutoff(6),
        "horizon": 5,
        "clock": CLOCK,
    }
    assert build_squared_return_label(**kwargs, knowledge_mode="market_available").value > 0
    with pytest.raises(EventStudyError, match="PRICE_NOT_KNOWN"):
        build_squared_return_label(**kwargs, knowledge_mode="system_known")


def test_future_unrequired_prices_do_not_change_historical_label() -> None:
    rows = prices()[:6] + tuple(
        replace(row, price=math.nan, available_at=cutoff(20)) for row in prices()[6:]
    )
    result = build_squared_return_label(
        sessions=SESSIONS,
        calendar_version="calendar-sha256-fixture",
        prices=rows,
        prediction_cutoff=cutoff(0),
        label_known_at=cutoff(20),
        horizon=5,
        clock=CLOCK,
        knowledge_mode="market_available",
    )
    assert result == label()


def test_extreme_finite_positive_prices_avoid_ratio_overflow() -> None:
    rows = prices()
    rows = (replace(rows[0], price=1e-300), replace(rows[1], price=1e300)) + rows[2:]
    result = build_squared_return_label(
        sessions=SESSIONS,
        calendar_version="fixture",
        prices=rows,
        prediction_cutoff=cutoff(0),
        label_known_at=cutoff(6),
        horizon=1,
        clock=CLOCK,
        knowledge_mode="market_available",
    )
    assert result.value == pytest.approx((600 * math.log(10)) ** 2)


@pytest.mark.parametrize(
    "change,code",
    [
        ("early", "PREDICTION_CUTOFF_INVALID"),
        ("naive", "TIMEZONE_REQUIRED"),
        ("off_clock", "PREDICTION_CUTOFF_INVALID"),
        ("horizon", "HORIZON_NOT_REGISTERED"),
        ("calendar", "CALENDAR_INVALID"),
        ("short", "LABEL_UNMATURED"),
        ("mode", "KNOWLEDGE_MODE_INVALID"),
    ],
)
def test_clock_calendar_and_horizon_rejections(change: str, code: str) -> None:
    kwargs = {
        "sessions": SESSIONS,
        "calendar_version": "fixture",
        "prices": prices(),
        "prediction_cutoff": cutoff(0),
        "label_known_at": cutoff(6),
        "horizon": 5,
        "clock": CLOCK,
        "knowledge_mode": "market_available",
    }
    if change == "early":
        kwargs["prediction_cutoff"] = cutoff(0) - timedelta(hours=4)
    elif change == "off_clock":
        kwargs["prediction_cutoff"] = cutoff(0) + timedelta(minutes=1)
    elif change == "naive":
        kwargs["prediction_cutoff"] = cutoff(0).replace(tzinfo=None)
    elif change == "horizon":
        kwargs["horizon"] = 2
    elif change == "calendar":
        kwargs["sessions"] = SESSIONS[::-1]
    elif change == "short":
        kwargs["sessions"] = SESSIONS[:5]
    else:
        kwargs["knowledge_mode"] = "latest"
    with pytest.raises(EventStudyError, match=code):
        build_squared_return_label(**kwargs)


def test_half_open_overlap_and_minimum_separation_are_independent() -> None:
    held = (label(5),)
    training = (label(0), label(1), label(15))
    kept = purge_training_labels(
        training,
        held,
        held_out_segments=(LabelInterval("calendar-sha256-fixture", 5, 6),),
        fit_at=cutoff(20),
        minimum_separation_sessions=0,
        embargo_sessions=0,
    )
    assert kept == (training[0], training[2])  # [1,6) and [6,11) only touch.
    kept = purge_training_labels(
        training,
        held,
        held_out_segments=(LabelInterval("calendar-sha256-fixture", 5, 6),),
        fit_at=cutoff(20),
        minimum_separation_sessions=5,
        embargo_sessions=0,
    )
    assert kept == (training[2],)


def test_embargo_counts_complete_supplied_sessions_not_calendar_days() -> None:
    held = (label(0, 1),)
    training = tuple(label(i, 1) for i in range(1, 8))
    kept = purge_training_labels(
        training,
        held,
        held_out_segments=(LabelInterval("calendar-sha256-fixture", 0, 1),),
        fit_at=cutoff(20),
        minimum_separation_sessions=0,
        embargo_sessions=SPEC["temporal_split"]["embargo"]["trading_days"],
    )
    assert kept == training[5:]


def test_purge_rejects_unmatured_training_and_different_calendar() -> None:
    with pytest.raises(EventStudyError, match="TRAINING_LABEL_NOT_KNOWN"):
        purge_training_labels(
            (label(0),),
            (label(10),),
            held_out_segments=(LabelInterval("calendar-sha256-fixture", 10, 11),),
            fit_at=cutoff(4),
            minimum_separation_sessions=5,
            embargo_sessions=5,
        )
    with pytest.raises(EventStudyError, match="CALENDAR_VERSION_MISMATCH"):
        purge_training_labels(
            (label(0),),
            (replace(label(10), interval=LabelInterval("other", 11, 16)),),
            held_out_segments=(LabelInterval("calendar-sha256-fixture", 10, 11),),
            fit_at=cutoff(20),
            minimum_separation_sessions=5,
            embargo_sessions=5,
        )


def feature(identity: str, index: int = 0) -> MatchingFeatures:
    return MatchingFeatures(
        sample_id=identity,
        prediction_cutoff=cutoff(index),
        observed_through=SESSIONS[index].closes_at,
        available_at=cutoff(index),
        first_seen_at=cutoff(index),
        recorded_at=cutoff(index),
        weekday=DATES[index].weekday(),
        month=DATES[index].month,
        market_state="state-at-cutoff",
        lagged_volatility=0.02,
        event_ids=(),
    )


def test_matching_uses_pit_features_and_keeps_no_post_event_information() -> None:
    target = replace(feature("target", 11), event_ids=("cpi",))
    old = feature("old")
    future = feature("future", 18)
    other_event = replace(old, sample_id="other-event", event_ids=("another",))
    wrong_state = replace(old, sample_id="state", market_state="other")
    assert match_controls(
        target,
        (future, other_event, wrong_state, old),
        volatility_tolerance=0.001,
        knowledge_mode="market_available",
        timezone_name=CLOCK.timezone_name,
    ) == (old,)


@pytest.mark.parametrize(
    "field", ["observed_through", "available_at", "first_seen_at", "recorded_at"]
)
def test_future_matching_variables_rejected(field: str) -> None:
    row = replace(feature("control"), **{field: cutoff(1)})
    if field == "first_seen_at":
        row = replace(row, recorded_at=cutoff(1))
    with pytest.raises(EventStudyError, match="MATCHING_FEATURE_NOT_KNOWN"):
        match_controls(
            replace(feature("target"), event_ids=("cpi",)),
            (row,),
            volatility_tolerance=0.0,
            knowledge_mode="system_known",
            timezone_name=CLOCK.timezone_name,
        )


def test_six_categories_exhaust_dates_without_fake_non_event_group() -> None:
    categories = tuple(SPEC["controls"]["six_periods"]["categories"])
    reference = SPEC["controls"]["six_periods"]["reference_category"]
    assert (
        six_category_contrast(categories[0], categories=categories, reference=reference) == (0,) * 5
    )
    assert six_category_contrast(categories[3], categories=categories, reference=reference) == (
        0,
        0,
        1,
        0,
        0,
    )
    with pytest.raises(EventStudyError, match="SIX_CATEGORY_INVALID"):
        six_category_contrast("non-event", categories=categories, reference=reference)


def gate_spec() -> SampleGateSpec:
    gate = SPEC["sample_gates"]
    return SampleGateSpec(
        coverage_min=gate["target_expected_session_coverage_min"],
        distinct_total_min=gate["distinct_events_total_min"],
        training_min=gate["training_events_min"],
        validation_min=gate["validation_events_total_min"],
        oos_min=gate["oos_events_total_min"],
    )


def support() -> SampleSupport:
    return SampleSupport(
        expected_sessions=2000,
        valid_sessions=1960,
        training_events=frozenset(f"train-{i}" for i in range(20)),
        validation_events=frozenset(f"val-{i}" for i in range(5)),
        oos_events=frozenset(f"oos-{i}" for i in range(5)),
    )


def test_frozen_sample_threshold_exact_boundary_and_insufficient_data() -> None:
    assert evaluate_sample_gate(support(), gate_spec()) == ()
    assert evaluate_sample_gate(replace(support(), valid_sessions=1959), gate_spec()) == (
        "SESSION_COVERAGE_INSUFFICIENT",
    )
    reasons = evaluate_sample_gate(replace(support(), oos_events=frozenset()), gate_spec())
    assert reasons == ("DISTINCT_EVENTS_INSUFFICIENT", "OOS_EVENTS_INSUFFICIENT")


def test_gate_refuses_double_counted_events_and_invalid_coverage() -> None:
    with pytest.raises(EventStudyError, match="EVENT_SPLIT_OVERLAP"):
        evaluate_sample_gate(replace(support(), oos_events=frozenset({"train-1"})), gate_spec())
    with pytest.raises(EventStudyError, match="SESSION_COUNTS_INVALID"):
        evaluate_sample_gate(replace(support(), valid_sessions=2001), gate_spec())


def test_holm_golden_preserves_family_order_and_monotonicity() -> None:
    assert holm_adjusted_p_values((0.04, 0.001, 0.03, 0.01)) == pytest.approx(
        (0.06, 0.004, 0.06, 0.03)
    )
    assert holm_adjusted_p_values((0.05, 0.05)) == (0.1, 0.1)
    assert holm_adjusted_p_values(()) == ()


@pytest.mark.parametrize("value", [math.nan, math.inf, -0.1, 1.1])
def test_holm_rejects_invalid_probability(value: float) -> None:
    with pytest.raises(EventStudyError, match="P_VALUE_INVALID"):
        holm_adjusted_p_values((0.01, value))


@pytest.mark.parametrize("horizons", [(), (0,), (-1,), (1, 1), (True,)])
def test_clock_rejects_invalid_horizons(horizons: tuple[int, ...]) -> None:
    with pytest.raises(EventStudyError, match="STUDY_HORIZONS_INVALID"):
        replace(CLOCK, horizons=horizons)


def test_clock_rejects_unknown_zone_and_timezone_in_wall_clock() -> None:
    with pytest.raises(EventStudyError, match="STUDY_TIMEZONE_INVALID"):
        replace(CLOCK, timezone_name="not/a/zone")
    with pytest.raises(EventStudyError, match="STUDY_CLOCK_INVALID"):
        replace(CLOCK, local_cutoff=time(18, tzinfo=UTC))


@pytest.mark.parametrize("start,stop", [(-1, 2), (1, 1), (2, 1), (False, 1)])
def test_invalid_label_intervals(start: int, stop: int) -> None:
    with pytest.raises(EventStudyError, match="LABEL_INTERVAL_INVALID"):
        LabelInterval("fixture", start, stop)


@pytest.mark.parametrize(
    "kind,code",
    [
        ("version", "PRICE_VERSION_REQUIRED"),
        ("preclose", "PRICE_PRECEDES_CLOSE"),
        ("clock_order", "VERSION_CLOCK_ORDER_INVALID"),
        ("naive", "TIMEZONE_REQUIRED"),
    ],
)
def test_rejects_invalid_exact_version_provenance(kind: str, code: str) -> None:
    rows = list(prices())
    if kind == "version":
        rows[1] = replace(rows[1], version_id=" ")
    elif kind == "preclose":
        rows[1] = replace(rows[1], available_at=SESSIONS[1].closes_at - timedelta(seconds=1))
    elif kind == "clock_order":
        rows[1] = replace(rows[1], first_seen_at=cutoff(2))
    else:
        rows[1] = replace(rows[1], available_at=rows[1].available_at.replace(tzinfo=None))
    with pytest.raises(EventStudyError, match=code):
        build_squared_return_label(
            sessions=SESSIONS,
            calendar_version="fixture",
            prices=tuple(rows),
            prediction_cutoff=cutoff(0),
            label_known_at=cutoff(6),
            horizon=5,
            clock=CLOCK,
            knowledge_mode="market_available",
        )


@pytest.mark.parametrize(
    "kind,code",
    [
        ("empty", "CALENDAR_INVALID"),
        ("date", "CALENDAR_INVALID"),
        ("no_origin", "PREDICTION_CUTOFF_INVALID"),
    ],
)
def test_rejects_unusable_calendar(kind: str, code: str) -> None:
    sessions = SESSIONS
    prediction = cutoff(0)
    if kind == "empty":
        sessions = ()
    elif kind == "date":
        sessions = (replace(sessions[0], session_on=DATES[1]),) + sessions[1:]
    else:
        prediction = SESSIONS[0].closes_at
    with pytest.raises(EventStudyError, match=code):
        build_squared_return_label(
            sessions=sessions,
            calendar_version="fixture",
            prices=prices(),
            prediction_cutoff=prediction,
            label_known_at=cutoff(6),
            horizon=5,
            clock=CLOCK,
            knowledge_mode="market_available",
        )


def test_exact_final_close_matures_market_label_but_not_late_system_version() -> None:
    kwargs = {
        "sessions": SESSIONS,
        "calendar_version": "fixture",
        "prices": prices(),
        "prediction_cutoff": cutoff(0),
        "label_known_at": SESSIONS[5].closes_at,
        "horizon": 5,
        "clock": CLOCK,
    }
    assert build_squared_return_label(**kwargs, knowledge_mode="market_available").value > 0
    with pytest.raises(EventStudyError, match="PRICE_NOT_KNOWN"):
        build_squared_return_label(**kwargs, knowledge_mode="system_known")


@pytest.mark.parametrize(
    "kind,code",
    [
        ("policy", "SPLIT_POLICY_INVALID"),
        ("heldout", "HELD_OUT_REQUIRED"),
        ("segment", "HELD_OUT_SEGMENT_MISMATCH"),
        ("mode", "KNOWLEDGE_MODE_MISMATCH"),
    ],
)
def test_purge_rejects_incompatible_split_inputs(kind: str, code: str) -> None:
    held = label(10)
    segment = LabelInterval("calendar-sha256-fixture", 10, 11)
    if kind == "mode":
        held = replace(held, knowledge_mode="system_known")
    if kind == "segment":
        segment = LabelInterval("calendar-sha256-fixture", 11, 12)
    with pytest.raises(EventStudyError, match=code):
        purge_training_labels(
            (label(),),
            () if kind == "heldout" else (held,),
            held_out_segments=(segment,),
            fit_at=cutoff(20),
            minimum_separation_sessions=-1 if kind == "policy" else 5,
            embargo_sessions=5,
        )


@pytest.mark.parametrize(
    "kind,code",
    [
        ("tolerance", "MATCHING_TOLERANCE_INVALID"),
        ("duplicate", "MATCHING_IDENTITY_DUPLICATE"),
        ("feature", "MATCHING_FEATURE_INVALID"),
        ("date", "MATCHING_FEATURE_INVALID"),
        ("clock", "MATCHING_FEATURE_CLOCK_INVALID"),
        ("event", "TARGET_EVENT_REQUIRED"),
    ],
)
def test_matching_negative_contracts(kind: str, code: str) -> None:
    target = replace(feature("target", 11), event_ids=("cpi",))
    rows = (feature("old"),)
    if kind == "duplicate":
        rows = rows + rows
    elif kind == "feature":
        rows = (replace(rows[0], lagged_volatility=math.nan),)
    elif kind == "date":
        rows = (replace(rows[0], month=2),)
    elif kind == "clock":
        rows = (replace(rows[0], available_at=SESSIONS[0].closes_at - timedelta(seconds=1)),)
    elif kind == "event":
        target = replace(target, event_ids=())
    with pytest.raises(EventStudyError, match=code):
        match_controls(
            target,
            rows,
            volatility_tolerance=-1 if kind == "tolerance" else 0,
            knowledge_mode="market_available",
            timezone_name=CLOCK.timezone_name,
        )


def test_future_invalid_control_is_ignored_and_order_is_deterministic() -> None:
    target = replace(feature("target", 11), event_ids=("cpi",))
    a, b = feature("a"), feature("b")
    future = replace(feature("future", 18), lagged_volatility=math.nan)
    assert match_controls(
        target,
        (future, b, a),
        volatility_tolerance=0,
        knowledge_mode="market_available",
        timezone_name=CLOCK.timezone_name,
    ) == (a, b)


@pytest.mark.parametrize("coverage,count", [(math.nan, 1), (0, 1), (1.1, 1), (0.98, 0)])
def test_invalid_sample_gate_spec(coverage: float, count: int) -> None:
    with pytest.raises(EventStudyError, match="SAMPLE_GATE_SPEC_INVALID"):
        replace(gate_spec(), coverage_min=coverage, training_min=count)


def test_missing_event_identity_and_each_split_gate_are_not_pooled() -> None:
    with pytest.raises(EventStudyError, match="EVENT_IDENTITY_REQUIRED"):
        evaluate_sample_gate(replace(support(), training_events=frozenset({" "})), gate_spec())
    for field, reason in (
        ("training_events", "TRAINING_EVENTS_INSUFFICIENT"),
        ("validation_events", "VALIDATION_EVENTS_INSUFFICIENT"),
        ("oos_events", "OOS_EVENTS_INSUFFICIENT"),
    ):
        assert reason in evaluate_sample_gate(
            replace(support(), **{field: frozenset()}), gate_spec()
        )


def test_frozen_category_design_cannot_add_non_event_reference() -> None:
    categories = tuple(SPEC["controls"]["six_periods"]["categories"])
    with pytest.raises(EventStudyError, match="SIX_CATEGORY_INVALID"):
        six_category_contrast(categories[0], categories=categories, reference="non-event")


def test_expanding_folds_reuse_past_validation_but_count_distinct_events_once() -> None:
    row = replace(
        support(),
        training_events=frozenset(f"train-{i}" for i in range(25)),
        validation_events=frozenset(f"train-{i}" for i in range(5)),
    )
    assert evaluate_sample_gate(row, gate_spec()) == ()
    row = replace(row, training_events=frozenset(f"train-{i}" for i in range(20)))
    assert evaluate_sample_gate(row, gate_spec()) == ("DISTINCT_EVENTS_INSUFFICIENT",)
