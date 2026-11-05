"""Isolated rechecks: actual typed fixtures, never evidence of real-source admission."""

from __future__ import annotations

import json
from dataclasses import replace
from datetime import timedelta
from decimal import Decimal
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest

from apps.risk_center.application.portfolio_risk_serialization import canonical_portfolio_risk_json
from apps.simulated_trading.application.execution_settlement_uow import (
    SimulatedTradeExecutionBlocked,
)
from apps.simulated_trading.application.rebalance_journey_current_pins import (
    JourneyCurrentPolicyPinsValidator,
)
from tests.unit.simulated_trading import test_execution_instrument_classification as classifications
from tests.unit.simulated_trading import test_portfolio_risk_service as resources


def _validator(harness=None, *, classification=None):
    harness = harness or resources._harness()
    return JourneyCurrentPolicyPinsValidator(
        risk_policy_reader=harness.policy_reader,
        baseline_reader=harness.baseline_reader,
        resource_reader=harness.resources,
        classification_reader=SimpleNamespace(
            resolve_simulated_instrument_classification=lambda **kwargs: classification
        ),
        calendar_reader=object(),
        fee_reader=object(),
        rule_reader=object(),
        business_timezone=ZoneInfo("Asia/Shanghai"),
    )


def _risk_case():
    harness = resources._harness()
    snapshot = harness.resources.snapshot
    basis = SimpleNamespace(
        account_id=snapshot.account_id,
        owner_user_id=snapshot.owner_user_id,
        execution_session=snapshot.execution_session,
        money_unit=snapshot.money_unit,
    )
    captured = json.loads(
        canonical_portfolio_risk_json(
            {
                "policy": harness.policy_reader.policy,
                "baseline": harness.baseline_reader.policy,
                "native_account_limits": harness.resources.native_limits,
            }
        )
    )
    return harness, SimpleNamespace(basis=basis), captured


def test_current_risk_pins_allow_real_cash_change_and_later_policy_read_clock():
    harness, revision, captured = _risk_case()
    harness.resources.snapshot = replace(harness.resources.snapshot, cash=Decimal("15000.81"))
    harness.policy_reader.policy = replace(
        harness.policy_reader.policy, as_of=resources._AS_OF + timedelta(seconds=1)
    )
    _validator(harness)._verify_risk(
        revision, risk=captured, inputs=captured, as_of=resources._AS_OF + timedelta(seconds=1)
    )
    assert harness.resources.snapshot.cash == Decimal("15000.81")


@pytest.mark.parametrize("changed", ["native", "baseline", "profile"])
def test_current_risk_rejects_actual_native_baseline_or_profile_version_drift(changed):
    harness, revision, captured = _risk_case()
    if changed == "native":
        harness.resources.native_limits = replace(
            harness.resources.native_limits, max_single_weight=Decimal("0.90")
        )
    elif changed == "baseline":
        harness.baseline_reader.policy = replace(
            harness.baseline_reader.policy, content_sha256="e" * 64
        )
    else:
        harness.policy_reader.policy = replace(
            harness.policy_reader.policy, profile_content_hash="f" * 64
        )
    with pytest.raises(SimulatedTradeExecutionBlocked) as blocked:
        _validator(harness)._verify_risk(
            revision, risk=captured, inputs=captured, as_of=resources._AS_OF
        )
    assert (
        blocked.value.code
        == {
            "native": "TRANSITION_PLAN_NATIVE_LIMITS_CHANGED",
            "baseline": "TRANSITION_PLAN_BASELINE_POLICY_CHANGED",
            "profile": "TRANSITION_PLAN_RISK_POLICY_CHANGED",
        }[changed]
    )


def _classification_case(current=None):
    original = classifications._classification(classifications._selector())
    order = SimpleNamespace(
        asset_code=original.identity_evidence.asset_code,
        security_id=original.identity_evidence.security_id,
        asset_type=original.simulated_asset_type,
        classification_content_hash=original.content_hash,
    )
    row = {
        "classification_evidence": {
            "content_hash": original.content_hash,
            "evidence": original.to_payload(),
        }
    }
    return original, order, row


def test_later_classification_read_keeps_original_source_clocks_and_accepts_same_stable_pins():
    original, order, row = _classification_case()
    now = original.read_at + timedelta(seconds=1)
    current = replace(
        original,
        identity_evidence=replace(
            original.identity_evidence,
            selection=replace(original.identity_evidence.selection, selected_at=now),
        ),
        read_at=now,
    )
    assert current.content_hash != original.content_hash
    _validator(classification=current)._verify_classification(order=order, row=row, as_of=now)
    assert current.identity_evidence.source_evidence == original.identity_evidence.source_evidence
    assert row["classification_evidence"]["content_hash"] == original.content_hash


def test_classification_selector_change_is_rejected_even_when_asset_type_is_unchanged():
    original, order, row = _classification_case()
    selector = replace(original.selector, max_local_reference_age_seconds=3599)
    current = classifications._classification(selector)
    assert current.simulated_asset_type == original.simulated_asset_type
    with pytest.raises(SimulatedTradeExecutionBlocked) as blocked:
        _validator(classification=current)._verify_classification(
            order=order, row=row, as_of=current.read_at
        )
    assert blocked.value.code == "TRANSITION_PLAN_CURRENT_CLASSIFICATION_CHANGED"


@pytest.mark.parametrize("changed", ["missing_current", "original_hash", "asset_type"])
def test_classification_unknown_tampered_original_and_type_drift_cannot_qualify(changed):
    original, order, row = _classification_case()
    current = original
    if changed == "missing_current":
        current = None
    elif changed == "original_hash":
        order.classification_content_hash = "a" * 64
    else:
        order.asset_type = "another_configured_fixture_type"
    with pytest.raises(SimulatedTradeExecutionBlocked) as blocked:
        _validator(classification=current)._verify_classification(
            order=order, row=row, as_of=original.read_at
        )
    assert blocked.value.code == (
        "TRANSITION_PLAN_CURRENT_CLASSIFICATION_UNAVAILABLE"
        if changed == "missing_current"
        else "TRANSITION_PLAN_ORIGINAL_CLASSIFICATION_INVALID"
    )
