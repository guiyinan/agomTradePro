"""Unit coverage for stable R4 promotion scope and pre-registered policy."""

from __future__ import annotations

from dataclasses import MISSING, fields, replace
from decimal import Decimal

import pytest

from apps.portfolio.domain.macro_factor_risk import MacroRiskCandidateKind
from apps.research.domain.r4_promotion_scope_policy import (
    R4PromotionPolicy,
    R4PromotionScope,
    R4PromotionStudyRegistration,
)
from tests.unit.research.r4_promotion_factories import (
    promotion_policy,
    promotion_scope,
    study_registration,
)


def test_stable_scope_contains_only_semantic_ids_and_target_method() -> None:
    scope = promotion_scope()

    assert {field.name for field in fields(R4PromotionScope)} == {
        "scope_id",
        "owner",
        "capability",
        "purpose",
        "study_family_id",
        "target_method",
        "universe_policy_id",
        "factor_policy_id",
        "split_policy_id",
        "cost_semantics_id",
        "content_hash",
    }
    assert scope.owner == "research"
    assert scope.capability == "r4"
    assert scope.purpose == "macro_risk_method_research"
    assert scope.target_method is MacroRiskCandidateKind.MACRO_FACTOR_RISK_PARITY
    assert all(
        "version" not in field.name and "artifact" not in field.name
        for field in fields(R4PromotionScope)
    )


def test_exact_registration_changes_do_not_change_stable_scope() -> None:
    scope = promotion_scope()
    registration = study_registration()
    changed = R4PromotionStudyRegistration.create(
        study_family_id=registration.study_family_id,
        study_id=registration.study_id,
        universe_policy_id=registration.universe_policy_id,
        asset_codes=registration.asset_codes,
        factor_policy_id=registration.factor_policy_id,
        factor_codes=registration.factor_codes,
        split_policy_id=registration.split_policy_id,
        split_policy_version="r4-walk-forward.v2",
        cost_semantics_id=registration.cost_semantics_id,
        cost_semantics_version=registration.cost_semantics_version,
    )

    assert changed.content_hash != registration.content_hash
    assert promotion_policy(scope=scope, registration=registration).scope == scope
    assert promotion_policy(scope=scope, registration=changed).scope == scope


def test_policy_has_no_default_gate_or_validity_thresholds() -> None:
    required = {
        "required_methods",
        "reference_methods",
        "minimum_fold_count",
        "minimum_regime_coverage_ratio",
        "minimum_relative_net_return",
        "maximum_relative_drawdown_increase",
        "maximum_relative_volatility_increase",
        "maximum_relative_cost_increase",
        "decision_validity_seconds",
    }
    definitions = {field.name: field for field in fields(R4PromotionPolicy)}

    assert all(
        definitions[name].default is MISSING and definitions[name].default_factory is MISSING
        for name in required
    )
    policy = promotion_policy()
    assert policy.required_methods == tuple(
        sorted(MacroRiskCandidateKind, key=lambda item: item.value)
    )
    assert policy.reference_methods == tuple(
        item for item in policy.required_methods if item is not policy.scope.target_method
    )


def test_policy_rejects_weakened_family_threshold_or_scope_registration() -> None:
    policy = promotion_policy()

    with pytest.raises(ValueError, match="complete three-method family"):
        replace(policy, required_methods=policy.required_methods[:-1])
    with pytest.raises(ValueError, match="cannot be negative"):
        replace(policy, maximum_relative_cost_increase=Decimal("-0.1"))
    with pytest.raises(ValueError, match="registration does not match"):
        promotion_policy(
            registration=R4PromotionStudyRegistration.create(
                study_family_id="different-study-family",
                study_id="different-study-family",
                universe_policy_id="cn-two-asset-research-universe",
                asset_codes=("asset-a", "asset-b"),
                factor_policy_id="growth-inflation-factor-family",
                factor_codes=("growth", "inflation"),
                split_policy_id="walk-forward-embargo-research",
                split_policy_version="r4-walk-forward.v1",
                cost_semantics_id="gross-return-cost-separate",
                cost_semantics_version="gross-cost-reported-separately.v1",
            )
        )
    registration = study_registration()
    with pytest.raises(ValueError, match="registration does not match"):
        promotion_policy(
            registration=R4PromotionStudyRegistration.create(
                study_family_id=registration.study_family_id,
                study_id=f"{registration.study_id}-evil",
                universe_policy_id=registration.universe_policy_id,
                asset_codes=registration.asset_codes,
                factor_policy_id=registration.factor_policy_id,
                factor_codes=registration.factor_codes,
                split_policy_id=registration.split_policy_id,
                split_policy_version=registration.split_policy_version,
                cost_semantics_id=registration.cost_semantics_id,
                cost_semantics_version=registration.cost_semantics_version,
            )
        )
    with pytest.raises(ValueError, match="content hash mismatch"):
        replace(policy, content_hash="0" * 64)
