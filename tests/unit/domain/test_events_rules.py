"""Filtering, deduplication, throttling, and validation tests for Events."""

from datetime import UTC, datetime, timedelta

from apps.events.domain.entities import DomainEvent, EventType
from apps.events.domain.rules import (
    EventAgeRule,
    EventDeduplicationRule,
    EventFilterRule,
    EventPriorityRule,
    EventRuleEngine,
    EventThrottleRule,
    EventValidationRule,
    Rule,
    create_default_rule_engine,
    create_strict_rule_engine,
)


def _event(
    *,
    event_type: EventType = EventType.REGIME_CHANGED,
    occurred_at: datetime | None = None,
    payload: dict[str, object] | None = None,
    metadata: dict[str, object] | None = None,
) -> DomainEvent:
    """Build a deterministic event."""
    return DomainEvent(
        event_id="event-1",
        event_type=event_type,
        occurred_at=occurred_at or datetime.now(UTC),
        payload=payload or {"regime": "Recovery"},
        metadata=metadata or {},
    )


def test_priority_rule_rejects_invalid_context_and_uses_default() -> None:
    """Unmapped and malformed events remain low priority."""
    rule = EventPriorityRule({EventType.SYSTEM_ERROR: 1})
    assert rule.evaluate({}) is False
    assert rule.evaluate({"event": object()}) is False
    assert rule.evaluate({"event": _event()}) is False
    urgent = _event(event_type=EventType.SYSTEM_ERROR)
    assert rule.evaluate({"event": urgent}) is True
    assert rule.get_priority(urgent) == 1
    assert rule.get_priority(_event()) == 100


def test_filter_rule_enforces_block_allow_and_metadata_lists() -> None:
    """Blocked types, allow lists, and required metadata are conjunctive."""
    event = _event(metadata={"correlation_id": "corr-1"})
    assert EventFilterRule().evaluate({"event": event}) is True
    assert EventFilterRule().evaluate({}) is False
    assert (
        EventFilterRule(blocked_types={EventType.REGIME_CHANGED}).evaluate({"event": event})
        is False
    )
    assert (
        EventFilterRule(allowed_types={EventType.SYSTEM_ERROR}).evaluate({"event": event}) is False
    )
    assert (
        EventFilterRule(require_metadata={"correlation_id", "tenant"}).evaluate({"event": event})
        is False
    )
    assert EventFilterRule(require_metadata={"correlation_id"}).evaluate({"event": event}) is True


def test_deduplication_signature_window_and_cleanup() -> None:
    """Deduplication uses governed payload identity and expires old signatures."""
    rule = EventDeduplicationRule(dedup_window=60)
    event = _event(payload={"regime": "Recovery", "asset_code": "000001.SZ"})
    assert rule.evaluate({"event": object()}) is False
    assert rule.evaluate({"event": event}) is False
    assert rule.evaluate({"event": event}) is True

    different = _event(payload={"regime": "Deflation", "signal_id": "signal-1"})
    assert rule.evaluate({"event": different}) is False
    signature = rule._create_signature(different)
    rule._seen_events[signature] = datetime.now(UTC) - timedelta(hours=2)
    assert rule.cleanup_old_events(older_than=3600) == 1
    assert rule.cleanup_old_events(older_than=3600) == 0


def test_throttle_rule_discards_old_events_and_blocks_at_capacity() -> None:
    """Only timestamps inside the configured window count toward throttling."""
    rule = EventThrottleRule(max_events_per_window=2, window_seconds=60)
    event = _event()
    assert rule.evaluate({}) is False
    rule._event_counts[event.event_type.value] = [datetime.now(UTC) - timedelta(minutes=2)]
    assert rule.evaluate({"event": event}) is False
    assert rule.evaluate({"event": event}) is False
    assert rule.evaluate({"event": event}) is True


def test_age_and_validation_rules_cover_all_rejection_reasons() -> None:
    """Age, correlation, causation, and payload size fail independently."""
    fresh = _event(metadata={"correlation_id": "c", "causation_id": "p"})
    stale = _event(occurred_at=datetime.now(UTC) - timedelta(hours=2))
    assert EventAgeRule(max_age_seconds=3600).evaluate({}) is False
    assert EventAgeRule(max_age_seconds=3600).evaluate({"event": fresh}) is False
    assert EventAgeRule(max_age_seconds=3600).evaluate({"event": stale}) is True

    strict = EventValidationRule(
        require_correlation_id=True,
        require_causation_id=True,
        min_payload_size=2,
        max_payload_size=100,
    )
    assert strict.evaluate({}) is False
    assert strict.evaluate({"event": _event()}) is False
    assert strict.evaluate({"event": _event(metadata={"correlation_id": "c"})}) is False
    assert strict.evaluate({"event": fresh}) is True
    assert EventValidationRule(min_payload_size=1000).evaluate({"event": fresh}) is False
    assert EventValidationRule(max_payload_size=1).evaluate({"event": fresh}) is False


class _ExplodingRule(Rule):
    """A controlled rule failure used to verify engine isolation."""

    def evaluate(self, context: dict[str, object]) -> bool:
        """Raise a deterministic error."""
        del context
        raise ValueError("broken rule")


def test_event_rule_engine_reports_each_rejection_category_and_errors() -> None:
    """Rule failures are isolated and returned as auditable rejection reasons."""
    event = _event(occurred_at=datetime.now(UTC) - timedelta(hours=2))
    engine = EventRuleEngine()
    blocked = EventFilterRule(blocked_types={EventType.REGIME_CHANGED})
    duplicate = EventDeduplicationRule()
    throttle = EventThrottleRule(max_events_per_window=0)
    age = EventAgeRule(max_age_seconds=1)
    validation = EventValidationRule(require_correlation_id=True)
    exploding = _ExplodingRule()
    engine.add_rule(blocked, "blocked")
    engine.add_rule(duplicate, "duplicate")
    engine.add_rule(throttle, "throttle")
    engine.add_rule(age, "age")
    engine.add_rule(validation, "validation")
    engine.add_rule(exploding, "exploding")
    duplicate.evaluate({"event": event})

    should_process, reasons = engine.should_process(event)
    assert should_process is False
    assert len(reasons) == 6
    assert any("过滤规则" in reason for reason in reasons)
    assert any("重复事件" in reason for reason in reasons)
    assert any("事件节流" in reason for reason in reasons)
    assert any("事件过期" in reason for reason in reasons)
    assert any("事件无效" in reason for reason in reasons)
    assert any("broken rule" in reason for reason in reasons)

    assert engine.get_rule_count() == 6
    engine.remove_rule(exploding)
    engine.remove_rule(exploding)
    assert engine.get_rule_count() == 5
    engine.clear()
    assert engine.get_rule_count() == 0


def test_default_and_strict_engines_publish_expected_policy() -> None:
    """Factory rule sets differ on correlation requirements and stay usable."""
    default = create_default_rule_engine()
    strict = create_strict_rule_engine()
    event = _event()

    assert default.get_rule_count() == 4
    assert strict.get_rule_count() == 4
    assert default.should_process(event)[0] is True
    assert strict.should_process(event)[0] is False
