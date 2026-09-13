"""Policy versions bind every decision field without reinterpreting legacy identity."""

from dataclasses import replace

import pytest

from apps.data_center.domain.contracts import DatasetKey, PublicationPolicy


def _policy() -> PublicationPolicy:
    return PublicationPolicy(
        dataset=DatasetKey("equity.valuation.fact", "1.0", "1.0"),
        minimum_coverage_ratio=0.99,
        allow_partial=True,
        conflict_action="quarantine",
        required_evidence=("source", "observed_at", "available_at", "payload_hash"),
        retention_days=3650,
        policy_version="2",
    )


def test_legacy_policy_identity_remains_contract_and_schema() -> None:
    legacy = replace(_policy(), policy_version="legacy")
    assert legacy.identity == "1.0:1.0"
    assert not legacy.uses_versioned_evidence


def test_policy_identity_is_stable_and_self_describing() -> None:
    policy = _policy()
    assert policy.identity == f"p2:2:{policy.content_hash}"
    assert len(policy.content_hash) == 64
    assert policy.identity == replace(policy).identity
    assert policy.uses_versioned_evidence


def test_maximum_policy_identity_fits_audit_resource_version() -> None:
    policy = replace(
        _policy(),
        dataset=DatasetKey("equity.valuation.fact", "a" * 40, "b" * 40),
        policy_version="c" * 40,
    )
    assert len(policy.identity) == 108


@pytest.mark.parametrize(
    "changed",
    [
        {"dataset": DatasetKey("equity.price.bar", "1.0", "1.0")},
        {"dataset": DatasetKey("equity.valuation.fact", "2.0", "1.0")},
        {"dataset": DatasetKey("equity.valuation.fact", "1.0", "2.0")},
        {"policy_version": "3"},
        {"minimum_coverage_ratio": 1.0},
        {"allow_partial": False},
        {"conflict_action": "block"},
        {"required_evidence": ("source", "observed_at", "payload_hash")},
        {"retention_days": 1825},
    ],
)
def test_each_policy_decision_field_changes_identity(changed: dict[str, object]) -> None:
    policy = _policy()
    assert replace(policy, **changed).content_hash != policy.content_hash


@pytest.mark.parametrize("version", ["", " 2", "2:3", "a" * 41])
def test_policy_version_requires_bounded_unambiguous_token(version: str) -> None:
    with pytest.raises(ValueError, match="policy_version"):
        replace(_policy(), policy_version=version)
