"""Boundary, expiry, and invalidation tests for the Alpha Trigger Domain."""

from datetime import UTC, date, datetime, timedelta

import pytest

from apps.alpha_trigger.domain.entities import (
    AlphaCandidate,
    AlphaTrigger,
    CandidateStatus,
    InvalidationCondition,
    InvalidationType,
    SignalStrength,
    TriggerConfig,
    TriggerEvent,
    TriggerStatus,
    TriggerType,
    create_invalidations,
)
from apps.alpha_trigger.domain.services import (
    CandidateGenerator,
    TriggerEvaluator,
    TriggerFilter,
    TriggerInvalidator,
    check_invalidations,
    evaluate_trigger,
    generate_candidate,
)


def _trigger(
    trigger_type: TriggerType = TriggerType.MOMENTUM_SIGNAL,
    *,
    condition: dict[str, object] | None = None,
    direction: str = "LONG",
    status: TriggerStatus = TriggerStatus.ACTIVE,
    strength: SignalStrength = SignalStrength.STRONG,
    confidence: float = 0.75,
    invalidations: list[InvalidationCondition] | None = None,
    expires_at: datetime | None = None,
) -> AlphaTrigger:
    """Build a fixed, timezone-aware trigger."""
    now = datetime.now(UTC)
    return AlphaTrigger(
        trigger_id=f"trigger-{trigger_type.value}",
        trigger_type=trigger_type,
        asset_code="AAA",
        asset_class="equity",
        direction=direction,
        trigger_condition=dict(condition or {}),
        invalidation_conditions=list(invalidations or []),
        strength=strength,
        confidence=confidence,
        created_at=now - timedelta(days=2),
        expires_at=expires_at,
        status=status,
        triggered_at=now - timedelta(days=1) if status == TriggerStatus.TRIGGERED else None,
        thesis="deterministic thesis",
    )


def test_invalidation_condition_normalizes_both_legacy_directions() -> None:
    """Legacy aliases and canonical fields round-trip without losing proof conditions."""
    legacy = InvalidationCondition(
        condition_type="threshold_cross",
        threshold=49.5,
        direction="below",
        time_limit_hours=12,
        custom_condition={"expected_regime": "Recovery"},
    )
    canonical = InvalidationCondition(
        condition_type=InvalidationType.REGIME_MISMATCH,
        threshold_value=50,
        cross_direction="above",
        time_window_hours=24,
        required_regime="Overheat",
    )

    assert legacy.threshold_value == legacy.threshold == 49.5
    assert legacy.cross_direction == legacy.direction == "below"
    assert legacy.time_window_hours == legacy.time_limit_hours == 12
    assert legacy.required_regime == "Recovery"
    assert canonical.threshold == 50
    assert canonical.direction == "above"
    assert canonical.time_limit_hours == 24
    assert canonical.custom_condition == {"expected_regime": "Overheat"}
    assert InvalidationCondition.from_dict(canonical.to_dict()).required_regime == "Overheat"


def test_trigger_lifecycle_properties_round_trip_and_event_projection() -> None:
    """Trigger state, expiry clocks, serialization, and event evidence stay aligned."""
    now = datetime.now(UTC)
    active = _trigger(expires_at=now + timedelta(days=5))
    triggered = _trigger(status=TriggerStatus.TRIGGERED)
    invalidated = _trigger(status=TriggerStatus.INVALIDATED)
    expired = _trigger(expires_at=now - timedelta(seconds=1))

    assert active.is_active
    assert not active.is_expired
    assert active.days_since_creation >= 1
    assert active.days_since_trigger is None
    assert active.remaining_days is not None
    assert triggered.is_triggered
    assert triggered.days_since_trigger is not None
    assert invalidated.is_invalidated
    assert expired.is_expired
    assert _trigger().remaining_days is None
    restored = AlphaTrigger.from_dict(active.to_dict())
    assert restored.trigger_id == active.trigger_id
    assert restored.invalidation_conditions == active.invalidation_conditions

    event = TriggerEvent("event", active.trigger_id, "triggered", now, reason="met")
    assert event.to_dict()["occurred_at"] == now.isoformat()
    assert event.to_dict()["reason"] == "met"


def _candidate(**overrides: object) -> AlphaCandidate:
    """Build a deterministic candidate."""
    values: dict[str, object] = {
        "candidate_id": "candidate",
        "trigger_id": "trigger",
        "asset_code": "AAA",
        "asset_class": "equity",
        "direction": "LONG",
        "strength": SignalStrength.STRONG,
        "confidence": 0.75,
        "thesis": "thesis",
        "time_window_start": date.today(),
        "time_window_end": date.today() + timedelta(days=5),
    }
    values.update(overrides)
    return AlphaCandidate(**values)  # type: ignore[arg-type]


def test_candidate_status_aliases_expiry_and_decision_linkage() -> None:
    """Candidate lifecycle helpers accept canonical values and preserve unknown legacy status."""
    actionable = _candidate(status="ACTIONABLE", time_horizon=10, last_decision_request_id="req")
    watch = _candidate(status="WATCH")
    executed = _candidate(status="EXECUTED")
    dropped = _candidate(status="DROPPED", time_window_end=date.today() - timedelta(days=1))
    unknown = _candidate(status="LEGACY")

    assert actionable.is_actionable
    assert actionable.has_decision_request
    assert actionable.time_window_end == date.today() + timedelta(days=10)
    assert watch.is_watch
    assert executed.is_executed
    assert dropped.is_dropped and dropped.is_expired
    assert unknown.status == "LEGACY"
    assert not _candidate(last_decision_request_id="").has_decision_request
    assert isinstance(actionable.days_remaining, int)
    payload = executed.to_dict()
    assert payload["is_executed"] is True
    assert payload["status"] == "EXECUTED"


def test_trigger_config_and_invalidation_factory_cover_all_rule_types() -> None:
    """Config serialization and proof-condition factory retain every supported rule."""
    config = TriggerConfig(weak_threshold=0.25, moderate_threshold=0.55, strong_threshold=0.85)
    restored = TriggerConfig.from_dict(config.to_dict())
    conditions = create_invalidations(
        [{"indicator_code": "PMI", "threshold_value": 50, "cross_direction": "below"}],
        time_decay_days=20,
        regime_mismatch="Recovery",
    )

    assert restored == config
    assert config.get_strength(0.7) == SignalStrength.STRONG
    assert [condition.condition_type for condition in conditions] == [
        InvalidationType.THRESHOLD_CROSS,
        InvalidationType.TIME_DECAY,
        InvalidationType.REGIME_MISMATCH,
    ]


@pytest.mark.parametrize(
    ("trigger", "data", "expected"),
    [
        (_trigger(status=TriggerStatus.PAUSED), {}, False),
        (_trigger(expires_at=datetime.now(UTC) - timedelta(seconds=1)), {}, False),
        (_trigger(TriggerType.THRESHOLD_CROSS), {}, False),
        (
            _trigger(
                TriggerType.THRESHOLD_CROSS,
                condition={"indicator_code": "PMI", "threshold": 50},
            ),
            {},
            False,
        ),
        (
            _trigger(
                TriggerType.THRESHOLD_CROSS,
                condition={"indicator_code": "PMI", "threshold": 50, "direction": "above"},
            ),
            {"PMI": 51},
            True,
        ),
        (
            _trigger(
                TriggerType.THRESHOLD_CROSS,
                condition={"indicator_code": "PMI", "threshold": 50, "direction": "below"},
            ),
            {"PMI": 49},
            True,
        ),
        (_trigger(TriggerType.MOMENTUM_SIGNAL), {}, False),
        (
            _trigger(TriggerType.MOMENTUM_SIGNAL, condition={"momentum_pct": 0.05}),
            {},
            False,
        ),
        (
            _trigger(
                TriggerType.MOMENTUM_SIGNAL,
                condition={"momentum_pct": 0.05},
                direction="SHORT",
            ),
            {"momentum": -0.06},
            True,
        ),
        (_trigger(TriggerType.REGIME_TRANSITION), {}, False),
        (
            _trigger(
                TriggerType.REGIME_TRANSITION,
                condition={"target_regime": "Recovery"},
            ),
            {},
            False,
        ),
        (
            _trigger(
                TriggerType.REGIME_TRANSITION,
                condition={"target_regime": "Recovery"},
            ),
            {"current_regime": "Recovery"},
            True,
        ),
        (_trigger(TriggerType.POLICY_CHANGE), {}, False),
        (
            _trigger(TriggerType.POLICY_CHANGE, condition={"target_policy_level": 1}),
            {},
            False,
        ),
        (
            _trigger(TriggerType.POLICY_CHANGE, condition={"target_policy_level": 1}),
            {"policy_level": 1},
            True,
        ),
        (_trigger(TriggerType.MANUAL_OVERRIDE), {}, True),
        (_trigger(TriggerType.STRUCTURAL_MISALIGNMENT), {}, False),
    ],
)
def test_trigger_evaluator_maps_each_boundary_to_explicit_outcome(
    trigger: AlphaTrigger,
    data: dict[str, object],
    expected: bool,
) -> None:
    """Missing inputs and unsupported types never trigger silently."""
    assert TriggerEvaluator().should_trigger(trigger, data)[0] is expected
    assert evaluate_trigger(trigger, data)[0] is expected


def test_invalidator_reports_missing_invalid_and_met_conditions() -> None:
    """Invalidation checks distinguish malformed input, non-matches, and proof matches."""
    invalidator = TriggerInvalidator()
    now = datetime.now(UTC)
    conditions = [
        InvalidationCondition("threshold_cross"),
        InvalidationCondition("threshold_cross", indicator_code="PMI"),
        InvalidationCondition("threshold_cross", indicator_code="PMI", threshold_value=50),
        InvalidationCondition("time_decay"),
        InvalidationCondition("time_decay", time_window_hours=4),
        InvalidationCondition("regime_mismatch"),
        InvalidationCondition("regime_mismatch", required_regime="Recovery"),
        InvalidationCondition("manual_invalidation"),
    ]
    trigger = _trigger(status=TriggerStatus.TRIGGERED, invalidations=conditions)

    assert not invalidator.check_invalidations(trigger, {}).is_invalidated
    invalid_time = invalidator._check_time_decay(conditions[4], {"triggered_at": 123})
    assert invalid_time[1] == "无效的触发时间格式"
    recent_time = invalidator._check_time_decay(
        conditions[4],
        {"triggered_at": now.isoformat()},
    )
    assert recent_time[0] is False
    met_time = invalidator._check_time_decay(
        conditions[4],
        {"triggered_at": now - timedelta(hours=5)},
    )
    assert met_time[0] is True
    day_condition = InvalidationCondition("time_decay", max_holding_days=1)
    assert invalidator._check_time_decay(
        day_condition,
        {"triggered_at": now - timedelta(days=2)},
    )[0]
    assert not invalidator._check_time_decay(day_condition, {"triggered_at": now})[0]
    assert invalidator._check_regime_mismatch(
        conditions[6],
        {"current_regime": "Overheat"},
    )[0]
    assert not invalidator._check_regime_mismatch(
        conditions[6],
        {"current_regime": "Recovery"},
    )[0]

    met_trigger = _trigger(
        status=TriggerStatus.TRIGGERED,
        invalidations=[
            InvalidationCondition(
                "threshold_cross",
                indicator_code="PMI",
                threshold_value=50,
                cross_direction="above",
            )
        ],
    )
    result = check_invalidations(met_trigger, {"PMI": 51})
    assert result.is_invalidated
    assert result.details


def test_candidate_generation_describes_invalidation_asymmetry_and_status() -> None:
    """Generated candidates expose proof rules and only strongest signals become actionable."""
    conditions = create_invalidations(
        [{"indicator_code": "PMI", "threshold_value": 50, "cross_direction": "below"}],
        time_decay_days=10,
        regime_mismatch="Recovery",
    )
    strong = _trigger(
        strength=SignalStrength.VERY_STRONG,
        confidence=0.9,
        invalidations=conditions,
    )
    medium = _trigger(confidence=0.6)
    weak = _trigger(confidence=0.3)
    generator = CandidateGenerator()

    candidate = generator.from_trigger(strong, 20)
    assert candidate.status == CandidateStatus.ACTIONABLE
    assert candidate.expected_asymmetry == "HIGH"
    assert "PMI 跌破 50" in candidate.invalidation
    assert "持仓超过 10 天" in candidate.invalidation
    assert "Regime 不再是 Recovery" in candidate.invalidation
    assert generator.from_trigger(medium).expected_asymmetry == "MED"
    assert generator.from_trigger(weak).expected_asymmetry == "LOW"
    assert generator.from_trigger(weak).invalidation == "无证伪条件"
    assert generate_candidate(strong, 15).time_horizon == 15


def test_trigger_filter_covers_status_asset_strength_expiry_sort_and_top_n() -> None:
    """Filtering and ranking are deterministic across all public selectors."""
    now = datetime.now(UTC)
    high = _trigger(strength=SignalStrength.VERY_STRONG, confidence=0.9)
    low = _trigger(strength=SignalStrength.WEAK, confidence=0.2)
    expired = _trigger(
        strength=SignalStrength.MODERATE,
        confidence=0.5,
        expires_at=now - timedelta(seconds=1),
    )
    paused = _trigger(status=TriggerStatus.PAUSED, confidence=0.7)
    paused.asset_code = "BBB"
    triggers = [low, high, expired, paused]
    trigger_filter = TriggerFilter()

    assert trigger_filter.filter_by_status(triggers, TriggerStatus.PAUSED) == [paused]
    assert trigger_filter.filter_by_asset(triggers, "BBB") == [paused]
    assert trigger_filter.filter_by_strength(triggers, SignalStrength.STRONG) == [high, paused]
    assert trigger_filter.filter_active(triggers) == [low, high]
    assert trigger_filter.sort_by_confidence(triggers)[0] is high
    assert trigger_filter.sort_by_confidence(triggers, descending=False)[0] is low
    assert trigger_filter.get_top_n(triggers, 1, "created_at")
    assert trigger_filter.get_top_n(triggers, 2, "unchanged") == triggers[:2]
