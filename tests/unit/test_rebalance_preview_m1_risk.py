"""BUY readiness tests for versioned and falsifiable M1 risk predicates."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from decimal import Decimal

from apps.risk_center.application.m1_rebalance_risk_policy import (
    M1RiskPolicyQualification,
)
from apps.risk_center.domain.m1_rebalance_risk_policy import (
    M1RiskCondition,
    M1RiskObservation,
    M1RiskPolicyRevision,
    M1RiskSourceSnapshot,
    RiskApplicability,
    RiskConditionOutcome,
    RiskQualificationState,
    qualify_revision,
)
from apps.simulated_trading.application.rebalance_plan_preview_contracts import (
    RebalancePlanPreviewItem,
)
from apps.simulated_trading.application.rebalance_preview_m1_risk import (
    block_buys_for_m1_risk,
    build_m1_risk_falsification,
    single_position_observation,
    stop_loss_observation,
    total_position_observation,
)

EFFECTIVE_FROM = datetime(2026, 10, 25, 12, 0, tzinfo=UTC)
EFFECTIVE_UNTIL = datetime(2026, 11, 25, 12, 0, tzinfo=UTC)


def _qualification() -> M1RiskPolicyQualification:
    """Build a qualified real-version value for preview-rule unit tests."""

    source = M1RiskSourceSnapshot(
        account_id=613,
        account_owner_user_id=41,
        account_type="simulated",
        account_is_active=True,
        account_max_single_position_pct=Decimal("20"),
        account_max_total_position_pct=Decimal("95"),
        account_stop_loss_pct=Decimal("8"),
        strategy_selection_state="confirmed_unconfigured",
        strategy_id=None,
        strategy_version=None,
        strategy_max_single_position_pct=None,
        strategy_max_total_position_pct=None,
        strategy_stop_loss_pct=None,
        position_rule_id=None,
        position_rule_source_json=None,
    )
    revision = M1RiskPolicyRevision(
        risk_policy_version="3a34a114-ea06-4b80-bc73-35bc67850b1f",
        account_id=613,
        actor_user_id=41,
        effective_from=EFFECTIVE_FROM,
        effective_until=EFFECTIVE_UNTIL,
        known_at=datetime(2026, 10, 25, 11, 55, tzinfo=UTC),
        reason="Owner approved explicit M1-only limits.",
        max_single_position=M1RiskCondition(
            RiskApplicability.APPLICABLE,
            Decimal("19"),
        ),
        max_total_position=M1RiskCondition(
            RiskApplicability.APPLICABLE,
            Decimal("90"),
        ),
        max_stop_loss=M1RiskCondition(
            RiskApplicability.APPLICABLE,
            Decimal("7"),
        ),
        source_snapshot=source,
    )
    return M1RiskPolicyQualification(
        state=RiskQualificationState.QUALIFIED,
        reason_codes=(),
        revision=revision,
    )


def _buy_item(
    *,
    target_weight: Decimal | None,
    target_amount: Decimal | None = Decimal("2000"),
) -> RebalancePlanPreviewItem:
    """Build a ready BUY with an explicit target weight and projected amount."""

    return RebalancePlanPreviewItem(
        scope="asset",
        action="buy",
        asset_code="000001.SZ",
        asset_name="Fixture A-share",
        asset_type="equity",
        currency_unit="CNY",
        quantity_unit="shares",
        current_weight=Decimal("0"),
        target_weight=target_weight,
        portfolio_value=Decimal("10000"),
        current_amount=Decimal("0"),
        target_amount=target_amount,
        suggested_amount=Decimal("2000"),
        actionable_amount=Decimal("2000"),
        current_quantity=Decimal("0"),
        target_quantity=Decimal("200"),
        suggested_quantity=Decimal("200"),
        actionable_quantity=Decimal("200"),
        remaining_quantity=Decimal("0"),
        sellable_quantity=Decimal("0"),
        reference_price=Decimal("10"),
        price_source="fixture_quote",
        price_as_of=None,
        price_freshness="fresh",
        price_is_fallback=False,
        price_observed_at=EFFECTIVE_FROM,
        identity={},
        fee={},
        drift_threshold=None,
        risk_rule_result=None,
        risk_rule_reason_code=None,
        risk_rule_entry_price_basis=None,
        status="ready",
        reason_codes=(),
    )


def test_real_falsified_buy_predicates_clear_actionable_quantities() -> None:
    """Observed single and total exposure above the owner limits block the BUY."""

    qualification = _qualification()
    item = _buy_item(target_weight=Decimal("0.2001"), target_amount=Decimal("2001"))
    falsification = build_m1_risk_falsification(
        qualification=qualification,
        observations=(
            single_position_observation(
                items=(item,),
                projected_position_pct_by_asset={"000001.SZ": Decimal("20.01")},
            ),
            total_position_observation(
                has_buy=True,
                projected_position_amount=Decimal("9100"),
                projected_equity=Decimal("10000"),
            ),
            stop_loss_observation(positions=(), prices={}),
        ),
    )

    blocked = block_buys_for_m1_risk(
        items=[item],
        qualification=qualification,
        falsification=falsification,
    )[0]

    assert falsification.status == "falsified"
    assert falsification.conditions[0].outcome is RiskConditionOutcome.FALSIFIED
    assert falsification.conditions[0].observed_pct == Decimal("20.01")
    assert falsification.conditions[1].observed_pct == Decimal("91")
    assert blocked.status == "blocked"
    assert blocked.actionable_amount is None
    assert blocked.actionable_quantity is None
    assert "M1_RISK_FALSIFICATION_TRIGGERED" in blocked.reason_codes


def test_missing_same_security_projection_is_not_reported_as_not_applicable() -> None:
    """A BUY without final same-security exposure blocks instead of passing N/A."""

    qualification = _qualification()
    item = _buy_item(target_weight=Decimal("0.2"), target_amount=None)
    falsification = build_m1_risk_falsification(
        qualification=qualification,
        observations=(
            single_position_observation(
                items=(item,),
                projected_position_pct_by_asset=None,
            ),
            total_position_observation(
                has_buy=True,
                projected_position_amount=Decimal("8000"),
                projected_equity=Decimal("10000"),
            ),
            stop_loss_observation(positions=(), prices={}),
        ),
    )

    blocked = block_buys_for_m1_risk(
        items=[item],
        qualification=qualification,
        falsification=falsification,
    )[0]

    assert falsification.status == "unknown"
    assert falsification.conditions[0].policy_applicability is RiskApplicability.APPLICABLE
    assert falsification.conditions[0].observation_applicability is RiskApplicability.UNKNOWN
    assert falsification.conditions[0].outcome is RiskConditionOutcome.UNKNOWN
    assert blocked.status == "blocked"
    assert blocked.actionable_quantity is None
    assert "M1_RISK_FALSIFICATION_UNKNOWN" in blocked.reason_codes


def test_final_same_security_projection_falsifies_a_stricter_owner_cap() -> None:
    """Existing holding plus open reservation exposure beats the BUY-row target."""

    qualification = _qualification()
    item = _buy_item(target_weight=Decimal("0.05"), target_amount=Decimal("500"))
    falsification = build_m1_risk_falsification(
        qualification=qualification,
        observations=(
            single_position_observation(
                items=(item,),
                projected_position_pct_by_asset={"000001.SZ": Decimal("25")},
            ),
            total_position_observation(
                has_buy=True,
                projected_position_amount=Decimal("8000"),
                projected_equity=Decimal("10000"),
            ),
            stop_loss_observation(positions=(), prices={}),
        ),
    )

    blocked = block_buys_for_m1_risk(
        items=[item],
        qualification=qualification,
        falsification=falsification,
    )[0]

    assert falsification.conditions[0].observed_pct == Decimal("25")
    assert falsification.conditions[0].outcome is RiskConditionOutcome.FALSIFIED
    assert blocked.status == "blocked"
    assert blocked.actionable_amount is None
    assert blocked.actionable_quantity is None


def test_buy_is_blocked_when_every_policy_predicate_has_no_runtime_observation() -> None:
    """A lone configured stop-loss cannot make an otherwise empty BUY policy ready."""

    base = _qualification()
    source = replace(
        base.revision.source_snapshot,
        account_max_single_position_pct=None,
        account_max_total_position_pct=None,
    )
    revision = replace(
        base.revision,
        source_snapshot=source,
        max_single_position=M1RiskCondition(
            RiskApplicability.NOT_APPLICABLE,
            None,
            "No existing account single-position limit is configured.",
        ),
        max_total_position=M1RiskCondition(
            RiskApplicability.NOT_APPLICABLE,
            None,
            "No existing account total-position limit is configured.",
        ),
    )
    qualification = qualify_revision(
        revision=revision,
        account_id=613,
        as_of=EFFECTIVE_FROM,
        current_source=source,
    )
    item = _buy_item(target_weight=Decimal("0.20"))
    falsification = build_m1_risk_falsification(
        qualification=qualification,
        observations=(
            M1RiskObservation(
                "max_single_position",
                RiskApplicability.APPLICABLE,
                Decimal("20"),
            ),
            M1RiskObservation(
                "max_total_position",
                RiskApplicability.APPLICABLE,
                Decimal("80"),
            ),
            stop_loss_observation(positions=(), prices={}),
        ),
    )

    blocked = block_buys_for_m1_risk(
        items=[item],
        qualification=qualification,
        falsification=falsification,
    )[0]

    assert falsification.status == "not_applicable"
    assert blocked.status == "blocked"
    assert "M1_RISK_POLICY_HAS_NO_APPLICABLE_BUY_OBSERVATION" in blocked.reason_codes


def test_missing_policy_qualification_blocks_a_buy_even_with_known_measurements() -> None:
    """No real version/effective window means the otherwise valid row is not BUY-ready."""

    missing = M1RiskPolicyQualification(
        state=RiskQualificationState.MISSING,
        reason_codes=("M1_RISK_POLICY_VERSION_UNKNOWN",),
        revision=None,
    )
    item = _buy_item(target_weight=Decimal("0.10"))
    falsification = build_m1_risk_falsification(
        qualification=missing,
        observations=(
            M1RiskObservation(
                dimension="max_single_position",
                applicability=RiskApplicability.APPLICABLE,
                observed_pct=Decimal("10"),
            ),
            M1RiskObservation(
                dimension="max_total_position",
                applicability=RiskApplicability.APPLICABLE,
                observed_pct=Decimal("80"),
            ),
            stop_loss_observation(positions=(), prices={}),
        ),
    )

    blocked = block_buys_for_m1_risk(
        items=[item],
        qualification=missing,
        falsification=falsification,
    )[0]

    assert falsification.risk_policy_version is None
    assert falsification.effective_from is None
    assert falsification.status == "unknown"
    assert blocked.status == "blocked"
    assert blocked.actionable_amount is None
    assert "M1_RISK_POLICY_VERSION_UNKNOWN" in blocked.reason_codes
