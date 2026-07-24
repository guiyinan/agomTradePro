"""Behavioral tests for Dashboard visibility, layout, and alert rules."""

import pytest

from apps.dashboard.domain.entities import AlertSeverity
from apps.dashboard.domain.rules import (
    CardDependencyRule,
    DashboardCardVisibilityRule,
    DataSourceAvailabilityRule,
    MetricThresholdRule,
    RefreshIntervalRule,
    RuleEngine,
    WidgetPositionRule,
)


def test_visibility_rule_requires_permissions_regime_features_and_data() -> None:
    """Every declared visibility dependency must be satisfied."""
    rule = DashboardCardVisibilityRule(
        card_id="decision",
        conditions={
            "required_permissions": ["view_decision"],
            "required_regimes": ["Recovery"],
            "requires_alpha": True,
            "requires_beta_gate": True,
            "requires_decision_rhythm": True,
            "requires_data_source": ["regime", "policy"],
        },
    )
    context = {
        "user_permissions": ["view_decision"],
        "current_regime": "Recovery",
        "has_alpha": True,
        "has_beta_gate": True,
        "has_decision_rhythm": True,
        "available_data": {"regime": {}, "policy": {"level": "P1"}},
    }
    assert rule.evaluate(context) is False
    context["available_data"]["regime"] = {"name": "Recovery"}
    assert rule.evaluate(context) is True

    for key, value in [
        ("user_permissions", []),
        ("current_regime", "Deflation"),
        ("has_alpha", False),
        ("has_beta_gate", False),
        ("has_decision_rhythm", False),
    ]:
        changed = dict(context)
        changed[key] = value
        assert rule.evaluate(changed) is False

    assert DashboardCardVisibilityRule("always", {}).evaluate({}) is True


@pytest.mark.parametrize(
    ("context", "expected"),
    [
        ({"position": {"row": 0, "col": 0}, "size": {"width": 12, "height": 1}}, True),
        ({"position": {"row": -1}}, False),
        ({"position": {"row": 100}}, False),
        ({"position": {"col": -1}}, False),
        ({"position": {"col": 12}}, False),
        ({"size": {"width": 0}}, False),
        ({"size": {"width": 13}}, False),
        ({"size": {"height": 0}}, False),
        ({"position": {"col": 10}, "size": {"width": 3}}, False),
    ],
)
def test_widget_position_rule_rejects_each_layout_boundary(
    context: dict[str, object], expected: bool
) -> None:
    """Grid placement cannot cross row, column, or size bounds."""
    assert WidgetPositionRule().evaluate(context) is expected


@pytest.mark.parametrize(
    ("operator", "value", "expected"),
    [
        ("gt", 11, True),
        ("gt", 10, False),
        ("lt", 9, True),
        ("gte", 10, True),
        ("lte", 10, True),
        ("eq", 10, True),
        ("unknown", 10, True),
    ],
)
def test_metric_threshold_rule_supports_all_operators(
    operator: str, value: float, expected: bool
) -> None:
    """Threshold comparisons and the fallback operator are deterministic."""
    rule = MetricThresholdRule(
        "drawdown",
        warning_threshold=10,
        operator=operator,
    )
    assert rule.evaluate({"drawdown": value}) is expected


def test_metric_threshold_rule_prioritizes_critical_and_rejects_bad_values() -> None:
    """Critical alerts outrank warnings; missing or malformed data is neutral."""
    rule = MetricThresholdRule(
        "drawdown",
        warning_threshold=5,
        critical_threshold=10,
    )
    assert rule.evaluate({}) is False
    assert rule.evaluate({"drawdown": "bad"}) is False
    assert rule.get_severity({}) is None
    assert rule.get_severity({"drawdown": object()}) is None
    assert rule.get_severity({"drawdown": 10}) == AlertSeverity.CRITICAL
    assert rule.get_severity({"drawdown": 5}) == AlertSeverity.WARNING
    assert rule.get_severity({"drawdown": 4}) is None
    assert MetricThresholdRule("drawdown").evaluate({"drawdown": 10}) is False


def test_dependency_refresh_and_data_source_rules_fail_closed() -> None:
    """Dashboard dependencies reject missing cards, intervals, fields, and sources."""
    dependency = CardDependencyRule("decision", ["regime", "policy"])
    assert dependency.evaluate({"available_cards": {"regime", "policy"}}) is True
    assert dependency.evaluate({"available_cards": {"regime"}}) is False

    refresh = RefreshIntervalRule()
    assert refresh.evaluate({}) is True
    assert refresh.evaluate({"interval": "10"}) is True
    assert refresh.evaluate({"interval": 9}) is False
    assert refresh.evaluate({"interval": 3601}) is False
    assert refresh.evaluate({"interval": "bad"}) is False

    source = DataSourceAvailabilityRule("regime", ["name", "as_of"])
    assert source.evaluate({"available_data": {}}) is False
    assert source.evaluate({"available_data": {"regime": {"name": "Recovery"}}}) is False
    assert source.evaluate({"available_data": {"regime": object()}}) is False
    assert (
        source.evaluate({"available_data": {"regime": {"name": "Recovery", "as_of": "2026-07-24"}}})
        is True
    )
    assert DataSourceAvailabilityRule("regime").evaluate({"available_data": {"regime": object()}})


def test_rule_engine_add_remove_evaluate_and_clear_lifecycle() -> None:
    """The engine composes public rules without hidden state."""
    visible = DashboardCardVisibilityRule("always", {})
    refresh = RefreshIntervalRule()
    engine = RuleEngine()
    engine.add_rule(visible)
    engine.add_rule(refresh)

    assert engine.evaluate_all({"interval": 60}) == {
        "DashboardCardVisibilityRule": True,
        "RefreshIntervalRule": True,
    }
    assert engine.evaluate_any({"interval": 1}) is True
    assert engine.evaluate_all_pass({"interval": 1}) is False

    engine.remove_rule(refresh)
    engine.remove_rule(refresh)
    assert engine.evaluate_all_pass({}) is True
    engine.clear()
    assert engine.evaluate_all({}) == {}
    assert engine.evaluate_any({}) is False
