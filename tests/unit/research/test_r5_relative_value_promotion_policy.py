"""Stable scope and pre-registration coverage for R5 promotion."""

from __future__ import annotations

from dataclasses import replace

import pytest

from apps.research.domain.r5_relative_value_promotion_policy import (
    r5_relative_value_promotion_policy_hash,
)
from tests.unit.research.r5_relative_value_promotion_factories import (
    make_policy,
    make_scope,
)


def test_scope_and_policy_identities_are_content_addressed_and_replayable() -> None:
    """Semantic scope is stable while each exact policy is strongly sealed."""

    scope = make_scope()
    policy = make_policy(scope=scope)

    assert scope.scope_id == f"r5-rv-scope:{scope.content_hash}"
    assert policy.policy_id == f"r5-rv-policy:{policy.content_hash}"
    assert policy.registration.registration_id == (
        f"r5-rv-registration:{policy.registration.content_hash}"
    )
    assert policy.content_hash == r5_relative_value_promotion_policy_hash(policy)
    assert "a" * 64 not in scope.scope_id


def test_exact_registration_changes_do_not_change_stable_scope() -> None:
    """Trial calendars and exact versions never fragment the semantic stream."""

    scope = make_scope()
    first = make_policy(scope=scope)
    second = make_policy(
        scope=scope,
        expected_observation_ids=("obs-c", "obs-d"),
    )

    assert first.scope == second.scope
    assert first.registration != second.registration
    assert first.policy_id != second.policy_id


def test_same_content_addressed_policy_id_cannot_be_resealed() -> None:
    """A provider cannot keep an ID while replacing thresholds or content."""

    policy = make_policy()
    with pytest.raises(ValueError, match="content hash|identity"):
        replace(policy, maximum_total_cost=policy.maximum_total_cost + 1)
    with pytest.raises(ValueError, match="content hash|identity"):
        replace(policy, content_hash="0" * 64)


def test_policy_has_no_implicit_gate_or_validity_defaults() -> None:
    """Every promotion threshold is mandatory and validated explicitly."""

    policy = make_policy()
    values = vars(policy)
    expected = {
        "minimum_observation_count",
        "minimum_coverage_ratio",
        "minimum_excess_net_return",
        "maximum_drawdown_increase",
        "maximum_total_cost",
        "maximum_liquidity_breach_ratio",
        "maximum_capacity_utilization",
        "maximum_realized_credit_loss",
        "decision_validity_seconds",
    }
    assert expected.issubset(values)
    assert all(values[name] is not None for name in expected)
