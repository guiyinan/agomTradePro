"""Dedicated service policy must preserve canonical scope and active runtime provenance."""

from copy import deepcopy
from dataclasses import replace
from datetime import timedelta

import pytest

from apps.account import simulated_corporate_action_policy_scope_composition as policies
from apps.config_center.domain.runtime_config import (
    RuntimeConfigProfile,
    RuntimeConfigSnapshot,
    RuntimeProfileStatus,
)
from core.integration.config_center_runtime import ActiveRuntimeValueEvidence
from tests.unit.account.test_simulated_corporate_action_write_grant import _AT, _binding


@pytest.fixture
def policy_world(monkeypatch: pytest.MonkeyPatch):
    item = {
        "policy_id": "service-policy",
        "policy_version": "1",
        "canonical_account_id": "canonical-41",
        "owner_user_id": 81,
        "tenant_id": "tenant-7",
        "owner_id": "owner-81",
        "valid_from": (_AT - timedelta(minutes=1)).isoformat(),
        "valid_until": (_AT + timedelta(hours=1)).isoformat(),
        "maximum_grant_seconds": 600,
        "permission": "simulated_corporate_action_stage_write",
        "service_actor_id": "simulated-trading",
    }

    def install(items=None):
        payload = {
            "schema_version": "simulated-corporate-action-write-policies.v1",
            "enabled": True,
            "policies": deepcopy([item] if items is None else items),
        }
        profile = RuntimeConfigProfile(
            profile_id="profile-1",
            profile_key="development",
            environment="development",
            version=1,
            status=RuntimeProfileStatus.ACTIVE,
            content_hash="a" * 64,
            created_at=_AT - timedelta(hours=2),
            activated_at=_AT - timedelta(hours=1),
        )
        values = {policies.SIMULATED_ACTION_WRITE_POLICY_KEY: payload}
        snapshot = RuntimeConfigSnapshot(
            snapshot_id="snapshot-1",
            profile_id=profile.profile_id,
            profile_key=profile.profile_key,
            profile_version=profile.version,
            snapshot_hash=policies._hash(values),
            resolved_values=values,
            generated_at=_AT - timedelta(minutes=59),
            effective_from=profile.activated_at,
        )
        evidence = ActiveRuntimeValueEvidence(
            environment="development",
            definition_key=policies.SIMULATED_ACTION_WRITE_POLICY_KEY,
            value=payload,
            profile_id=profile.profile_id,
            profile_key=profile.profile_key,
            profile_version=profile.version,
            profile_content_hash=profile.content_hash,
            snapshot_id=snapshot.snapshot_id,
            snapshot_hash=snapshot.snapshot_hash,
            created_at=profile.created_at,
            known_at=profile.created_at,
            activated_at=profile.activated_at,
            snapshot_generated_at=snapshot.generated_at,
            effective_at=snapshot.effective_from,
            as_of=_AT,
        )
        fingerprint = policies._hash(
            {
                "policy": payload["policies"][0],
                "profile_id": profile.profile_id,
                "profile_version": profile.version,
                "profile_hash": profile.content_hash,
                "snapshot_id": snapshot.snapshot_id,
                "snapshot_hash": snapshot.snapshot_hash,
                "effective_at": evidence.effective_at.isoformat(),
            }
        )
        binding = _binding(
            account_id="canonical-41",
            policy_id="service-policy",
            policy_version="1",
            policy_content_hash=fingerprint,
        )
        monkeypatch.setattr(
            policies, "get_active_runtime_value_evidence", lambda **kwargs: evidence
        )
        monkeypatch.setattr(policies, "get_active_runtime_profile", lambda environment: profile)
        monkeypatch.setattr(policies, "get_latest_runtime_snapshot", lambda key: snapshot)
        return binding, evidence, profile, snapshot

    return item, install


def test_explicit_ordinary_owner_scope_is_accepted_without_staff_reader_authority(policy_world):
    _, install = policy_world
    binding, _, _, _ = install()
    result = policies._read_policy(binding=binding, environment="development", as_of=_AT)
    assert result.owner_user_id == 81 and result.maximum_grant_seconds == 600
    assert result.content_hash == binding.policy_content_hash


def test_owner_policy_discovery_retains_source_identity_without_issuing_permission(policy_world):
    _, install = policy_world
    binding, _, _, _ = install()
    result = policies.read_current_simulated_action_write_policy(
        canonical_account_id=binding.account_id,
        owner_user_id=binding.owner_user_id,
        environment="development",
        as_of=_AT,
    )
    assert result.content_hash == binding.policy_content_hash
    assert result.policy_id == binding.policy_id


def test_large_representable_duration_is_bounded_before_datetime_addition(policy_world):
    item, install = policy_world
    binding, _, _, _ = install([{**item, "maximum_grant_seconds": 10**13}])
    policy = policies._read_policy(binding=binding, environment="development", as_of=_AT)
    source_end = _AT + timedelta(minutes=10)
    assert policy.grant_valid_until(as_of=_AT, source_valid_until=source_end) == source_end


def test_owner_policy_discovery_does_not_filter_away_another_owner_collision(policy_world):
    item, install = policy_world
    binding, _, _, _ = install([item, {**item, "owner_user_id": 82, "policy_id": "other"}])
    with pytest.raises(ValueError, match="one account scope"):
        policies.read_current_simulated_action_write_policy(
            canonical_account_id=binding.account_id,
            owner_user_id=binding.owner_user_id,
            environment="development",
            as_of=_AT,
        )


def test_second_owner_is_not_hidden_by_user_specific_filtering(policy_world):
    item, install = policy_world
    binding, _, _, _ = install([item, {**item, "owner_user_id": 82, "policy_id": "other"}])
    with pytest.raises(ValueError, match="one account scope"):
        policies._read_policy(binding=binding, environment="development", as_of=_AT)


@pytest.mark.parametrize(
    "change",
    [
        {"permission": "evidence_read"},
        {"service_actor_id": "another-service"},
        {"maximum_grant_seconds": True},
        {"maximum_grant_seconds": 0},
        {"maximum_grant_seconds": 10**40},
        {"owner_user_id": True},
        {"owner_user_id": 82},
        {"valid_until": _AT.isoformat()},
        {"valid_from": (_AT + timedelta(seconds=1)).isoformat()},
        {"valid_from": "2026-11-11T01:00:00"},
        {"unknown": "field"},
    ],
)
def test_invalid_expired_or_wrong_owner_policy_is_rejected(policy_world, change):
    item, install = policy_world
    binding, _, _, _ = install([{**item, **change}])
    with pytest.raises(ValueError):
        policies._read_policy(binding=binding, environment="development", as_of=_AT)


@pytest.mark.parametrize("defect", ["snapshot_hash", "known_at", "profile", "disabled"])
def test_snapshot_or_evidence_tampering_is_not_laundered(policy_world, monkeypatch, defect):
    _, install = policy_world
    binding, evidence, profile, snapshot = install()
    if defect == "snapshot_hash":
        monkeypatch.setattr(
            policies,
            "get_latest_runtime_snapshot",
            lambda key: replace(snapshot, snapshot_hash="f" * 64),
        )
    elif defect == "known_at":
        monkeypatch.setattr(
            policies,
            "get_active_runtime_value_evidence",
            lambda **kwargs: replace(evidence, known_at=_AT + timedelta(seconds=1)),
        )
    elif defect == "profile":
        monkeypatch.setattr(
            policies, "get_active_runtime_profile", lambda environment: replace(profile, version=2)
        )
    else:
        evidence.value["enabled"] = False
    with pytest.raises(ValueError):
        policies._read_policy(binding=binding, environment="development", as_of=_AT)
