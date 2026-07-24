"""Boundary and compatibility tests for the Beta Gate Domain."""

from datetime import UTC, date, datetime, timedelta
from enum import Enum

import pytest

from apps.beta_gate.domain.entities import (
    GateConfig,
    GateDecision,
    GateMatchResult,
    GateStatus,
    PolicyConstraint,
    PortfolioConstraint,
    RegimeConstraint,
    RiskProfile,
    VisibilityUniverse,
    create_gate_config,
    get_default_configs,
)
from apps.beta_gate.domain.services import (
    BetaGateEvaluator,
    GateConfigSelector,
    VisibilityUniverseBuilder,
    build_universe,
    evaluate_visibility,
)


def test_regime_constraint_priorities_and_round_trip() -> None:
    """Explicit veto, allow-list, confidence, and high-confidence checks have stable priority."""
    constraint = RegimeConstraint(
        allowed_regimes=["Recovery", "Overheat"],
        min_confidence=0.4,
        require_high_confidence=True,
        disallowed_regimes=["Overheat"],
    )

    assert constraint.is_regime_allowed("Overheat", 0.9)[0] is False
    assert "禁止列表" in constraint.is_regime_allowed("Overheat", 0.9)[1]
    assert "不在允许列表" in constraint.is_regime_allowed("Deflation", 0.9)[1]
    assert "低于阈值" in constraint.is_regime_allowed("Recovery", 0.3)[1]
    assert "要求高置信度" in constraint.is_regime_allowed("Recovery", 0.5)[1]
    assert constraint.is_regime_allowed("Recovery", 0.6) == (True, "")
    assert RegimeConstraint.from_dict(constraint.to_dict()) == constraint


def test_policy_constraint_covers_every_policy_rejection() -> None:
    """P3 veto, maximum level, and explicit P1/P2 switches expose distinct reasons."""
    assert "自动否决" in PolicyConstraint().is_policy_allowed(3)[1]
    assert "超过最大允许" in PolicyConstraint(veto_on_p3=False).is_policy_allowed(3)[1]
    assert "P2" in PolicyConstraint().is_policy_allowed(2)[1]
    assert "P1" in PolicyConstraint(allowed_on_p1=False).is_policy_allowed(1)[1]
    allowed = PolicyConstraint(allowed_on_p1=True, allowed_on_p2=True)
    assert allowed.is_policy_allowed(2) == (True, "")
    assert PolicyConstraint.from_dict(allowed.to_dict()) == allowed


def test_portfolio_constraint_aliases_limits_and_round_trip() -> None:
    """Legacy aliases normalize into canonical percentages and every limit remains attributable."""
    aliased = PortfolioConstraint(
        max_total_position_pct=90,
        max_single_position_weight=25,
        max_concentration_ratio=55,
    )
    assert aliased.max_single_position_pct == 25
    assert aliased.max_correlated_exposure == 55
    assert aliased.check_position_limit(10, 5, 0) == (True, "")
    assert "总仓位" in aliased.check_position_limit(80, 20, 100)[1]
    assert "单资产仓位" in aliased.check_position_limit(10, 30, 100)[1]
    cash_guard = PortfolioConstraint(
        max_total_position_pct=100,
        max_single_position_pct=100,
        min_cash_pct=20,
    )
    assert "现金比例" in cash_guard.check_position_limit(70, 15, 100)[1]
    permissive = PortfolioConstraint(
        max_total_position_pct=100,
        max_single_position_pct=100,
        min_cash_pct=0,
    )
    assert permissive.check_position_limit(20, 10, 100) == (True, "")
    assert PortfolioConstraint.from_dict(permissive.to_dict()) == permissive


def _decision(status: GateStatus, **overrides: object) -> GateDecision:
    """Build a decision with fixed public context."""
    values: dict[str, object] = {
        "status": status,
        "asset_code": "AAA",
        "asset_class": "equity",
        "current_regime": "Recovery",
        "policy_level": 0,
        "regime_confidence": 0.8,
    }
    values.update(overrides)
    return GateDecision(**values)  # type: ignore[arg-type]


def test_gate_decision_derives_blocking_reason_and_projects_checks() -> None:
    """A blocked decision identifies the first failed check and never invents a business cause."""
    blocked = _decision(
        GateStatus.BLOCKED_POLICY,
        regime_check=(True, ""),
        policy_check=(False, "P2 blocked"),
    )
    unknown = _decision(GateStatus.BLOCKED_RISK)
    watch = _decision(GateStatus.WATCH)

    assert blocked.is_blocked
    assert blocked.blocking_reason == "[Policy] P2 blocked"
    assert blocked.created_at == blocked.evaluated_at
    assert blocked.to_dict()["policy_check"] == {"passed": False, "reason": "P2 blocked"}
    assert unknown.blocking_reason == "未知原因"
    assert watch.is_watch
    assert not watch.is_blocked
    assert _decision(GateStatus.PASSED).all_checks_passed


def test_gate_config_validity_serialization_and_defaults() -> None:
    """Inactive, expired, future, override, and round-trip validity paths are explicit."""
    now = datetime.now(UTC)
    active = create_gate_config()
    inactive = GateConfig("inactive", RiskProfile.BALANCED, is_active=False)
    future = GateConfig("future", RiskProfile.BALANCED, valid_from=now + timedelta(days=1))
    past = GateConfig("past", RiskProfile.BALANCED, valid_until=now - timedelta(days=1))
    expired = GateConfig(
        "expired",
        RiskProfile.BALANCED,
        expires_at=date.today() - timedelta(days=1),
    )
    overridden = GateConfig("override", RiskProfile.BALANCED, _is_valid_init=False)

    assert active.is_valid
    assert not inactive.is_valid
    assert not future.is_valid
    assert not past.is_valid
    assert expired.is_expired
    assert not expired.is_valid
    assert not overridden.is_valid
    assert not active.is_expired
    restored = GateConfig.from_dict(active.to_dict())
    assert restored.config_id == active.config_id
    assert restored.risk_profile == RiskProfile.BALANCED
    assert set(get_default_configs()) == set(RiskProfile)


def test_visibility_universe_queries_exclusions_and_round_trip() -> None:
    """Visibility lookup supports tuple and legacy scalar exclusions without ambiguity."""
    universe = VisibilityUniverse(
        as_of=date(2024, 1, 1),
        regime_snapshot_id="regime",
        policy_snapshot_id="policy",
        risk_profile=RiskProfile.BALANCED,
        visible_asset_categories=["equity"],
        visible_strategies=["value"],
        hard_exclusions=[("commodity", "P3"), "crypto"],
        watch_list=["gold"],
        notes="test",
    )

    assert universe.is_asset_visible("equity")
    assert universe.is_strategy_visible("value")
    assert universe.get_exclusion_reason("commodity") == "P3"
    assert universe.get_exclusion_reason("crypto") == "hard excluded"
    assert universe.get_exclusion_reason("bond") is None
    assert VisibilityUniverse.from_dict(universe.to_dict()).to_dict() == universe.to_dict()


def test_modern_evaluator_returns_distinct_rejection_statuses_and_batch() -> None:
    """Regime, policy, and portfolio failures retain distinct statuses and reasons."""
    config = create_gate_config(
        allowed_regimes=["Recovery"],
        min_confidence=0.5,
        max_policy_level=1,
        max_total_position=90,
        max_single_position=20,
    )
    evaluator = BetaGateEvaluator(config)
    common = {
        "asset_code": "AAA",
        "asset_class": "equity",
        "current_regime": "Recovery",
        "regime_confidence": 0.8,
        "policy_level": 0,
    }

    assert evaluator.evaluate(**common).status == GateStatus.PASSED
    assert evaluator.evaluate(**{**common, "current_regime": "Deflation"}).status == (
        GateStatus.BLOCKED_REGIME
    )
    assert evaluator.evaluate(**{**common, "policy_level": 2}).status == GateStatus.BLOCKED_POLICY
    assert (
        evaluator.evaluate(
            **common,
            current_portfolio_value=80,
            new_position_value=20,
        ).status
        == GateStatus.BLOCKED_PORTFOLIO
    )
    batch = evaluator.evaluate_batch(
        [("AAA", "equity"), ("BBB", "bond")],
        "Recovery",
        0.8,
        0,
    )
    assert [decision.asset_code for decision in batch] == ["AAA", "BBB"]


def _legacy_config() -> GateConfig:
    """Build the compatibility configuration used by legacy evaluation tests."""
    return GateConfig(
        "legacy",
        RiskProfile.BALANCED,
        regime_constraints={
            "Recovery": GateMatchResult(
                allowed_categories=["equity"],
                forbidden_assets=["BLOCKED"],
                forbidden_categories=["commodity"],
            )
        },
        policy_constraints={
            1: GateMatchResult(forbidden_categories=["equity"]),
        },
        confidence_threshold=0.5,
        portfolio_exposure_limit=0.2,
    )


@pytest.mark.parametrize(
    ("changes", "status"),
    [
        ({"regime_confidence": 0.4}, GateStatus.BLOCKED_CONFIDENCE),
        ({"current_regime": "Unknown"}, GateStatus.BLOCKED_REGIME),
        ({"asset_code": "BLOCKED"}, GateStatus.BLOCKED_REGIME),
        ({"asset_class": "commodity"}, GateStatus.BLOCKED_REGIME),
        ({"asset_class": "bond"}, GateStatus.BLOCKED_REGIME),
        ({"policy_level": 1}, GateStatus.BLOCKED_POLICY),
        (
            {"current_portfolio_value": 100, "new_position_value": 30},
            GateStatus.BLOCKED_PORTFOLIO,
        ),
    ],
)
def test_legacy_evaluator_preserves_compatibility_rejection_reasons(
    changes: dict[str, object],
    status: GateStatus,
) -> None:
    """Legacy dictionary constraints remain deterministic during migration."""
    values: dict[str, object] = {
        "asset_code": "AAA",
        "asset_class": "equity",
        "current_regime": "Recovery",
        "regime_confidence": 0.8,
        "policy_level": 0,
    }
    values.update(changes)

    decision = BetaGateEvaluator(_legacy_config()).evaluate(**values)  # type: ignore[arg-type]

    assert decision.status == status
    assert decision.blocking_reason


def test_legacy_evaluator_allows_broad_a_share_alias_and_success() -> None:
    """The documented broad A-share alias remains compatible without weakening other checks."""
    config = _legacy_config()
    config.regime_constraints["Recovery"].allowed_categories = ["a_share_large_cap"]
    decision = BetaGateEvaluator(config).evaluate(
        "AAA",
        "a_share_growth",
        "Recovery",
        0.8,
        0,
    )
    assert decision.status == GateStatus.PASSED


class PolicyLevel(Enum):
    """Small enum fake for policy-level normalization."""

    P2 = "P2"
    BROKEN = "broken"


def test_universe_builder_visibility_strategy_and_policy_normalization() -> None:
    """Universe construction applies visibility maps, policy vetoes, watch state, and strategy limits."""
    config = _legacy_config()
    config.asset_category_visibility = {"equity": True, "commodity": False}
    builder = VisibilityUniverseBuilder({RiskProfile.BALANCED: config})
    universe = builder.build(
        "Recovery",
        0.4,
        1,
        RiskProfile.BALANCED,
        candidate_assets=[("AAA", "equity")],
    )

    assert universe.visible_asset_categories == ["equity"]
    assert "equity" in universe.watch_list
    assert "commodity" in universe.hard_exclusions
    assert builder._determine_visible_strategies("Overheat", 0, RiskProfile.CONSERVATIVE) == [
        "inflation_hedge",
        "observe",
        "value",
    ]
    assert builder._determine_visible_strategies(
        "Recovery", PolicyLevel.P2, RiskProfile.BALANCED
    ) == ["observe"]
    assert builder._policy_level_num("P3") == 3
    assert builder._policy_level_num("Pbad") == 0
    assert builder._policy_level_num(PolicyLevel.BROKEN) == 0
    assert builder._policy_level_num(object()) == 0


def test_config_selector_and_convenience_functions_cover_lifecycle() -> None:
    """Config selection supports iterable inputs, lifecycle changes, and convenience entrypoints."""
    balanced = create_gate_config(RiskProfile.BALANCED)
    selector = GateConfigSelector([balanced])

    assert selector.get_config(RiskProfile.BALANCED) is balanced
    assert selector.get_active_configs() == [balanced]
    aggressive = create_gate_config(RiskProfile.AGGRESSIVE)
    selector.add_config(aggressive)
    assert selector.remove_config(RiskProfile.AGGRESSIVE)
    assert not selector.remove_config(RiskProfile.AGGRESSIVE)
    with pytest.raises(ValueError, match="No config found"):
        selector.get_config(RiskProfile.CONSERVATIVE)

    assert evaluate_visibility("AAA", "equity", "Recovery", 0.8, 0).is_passed
    assert (
        build_universe(
            "Recovery",
            0.8,
            0,
            candidate_assets=[("AAA", "equity")],
        ).current_regime
        == "Recovery"
    )
