"""Dedicated service policy must preserve canonical scope and active runtime provenance."""

from collections.abc import Iterator
from contextlib import contextmanager
from copy import deepcopy
from dataclasses import replace
from datetime import timedelta

import pytest

from apps.account import simulated_corporate_action_policy_scope_composition as policies
from apps.account.application.simulated_corporate_action_write_grant import (
    SimulatedCorporateActionWriteGrantUnavailable,
)
from apps.account.domain.simulated_corporate_action_write_capabilities import (
    SimulatedCorporateActionWriteCapability,
)
from apps.account.domain.simulated_corporate_action_write_grant import (
    SIMULATED_CORPORATE_ACTION_STAGE_WRITE_PERMISSION,
    SIMULATED_CORPORATE_ACTION_WRITE_GRANT_SCHEMA,
    SIMULATED_CORPORATE_ACTION_WRITE_GRANT_V2_PERMISSION,
    SIMULATED_CORPORATE_ACTION_WRITE_GRANT_V2_SCHEMA,
)
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

    def install(
        items=None,
        schema_version: str = "simulated-corporate-action-write-policies.v1",
    ):
        payload = {
            "schema_version": schema_version,
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


def _v2_item(
    item: dict[str, object],
    *,
    capabilities: list[str],
    terms_version: str,
    terms_sha256: str,
) -> dict[str, object]:
    """Build a fully explicit V2 policy row for contract tests."""

    return {
        **item,
        "permission": SIMULATED_CORPORATE_ACTION_WRITE_GRANT_V2_PERMISSION,
        "capabilities": capabilities,
        "terms_version": terms_version,
        "terms_sha256": terms_sha256,
    }


def _v2_capabilities(
    *values: SimulatedCorporateActionWriteCapability,
) -> list[str]:
    """Return explicit serialized capabilities without adding policy defaults."""

    return [value.value for value in values]


def test_explicit_ordinary_owner_scope_is_accepted_without_staff_reader_authority(policy_world):
    _, install = policy_world
    binding, _, _, _ = install()
    result = policies._read_policy(binding=binding, environment="development", as_of=_AT)
    assert result.owner_user_id == 81 and result.maximum_grant_seconds == 600
    assert result.content_hash == binding.policy_content_hash
    assert result.grant_schema == SIMULATED_CORPORATE_ACTION_WRITE_GRANT_SCHEMA
    assert (
        result.capabilities is None and result.terms_version is None and result.terms_sha256 is None
    )


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


def test_v2_policy_requires_explicit_schema_and_fails_closed_for_legacy_readers(
    policy_world, monkeypatch
):
    item, install = policy_world
    row = _v2_item(
        item,
        capabilities=_v2_capabilities(SimulatedCorporateActionWriteCapability.TAX_ASSESS),
        terms_version="tax-terms-v1",
        terms_sha256="b" * 64,
    )
    binding, _, _, _ = install([row], schema_version="simulated-corporate-action-write-policies.v2")

    with pytest.raises(ValueError, match="expected grant schema"):
        policies._read_policy(binding=binding, environment="development", as_of=_AT)

    result = policies.read_current_simulated_action_write_policy(
        canonical_account_id=binding.account_id,
        owner_user_id=binding.owner_user_id,
        environment="development",
        as_of=_AT,
        expected_grant_schema=SIMULATED_CORPORATE_ACTION_WRITE_GRANT_V2_SCHEMA,
    )
    assert result.grant_schema == SIMULATED_CORPORATE_ACTION_WRITE_GRANT_V2_SCHEMA
    assert result.capabilities == (SimulatedCorporateActionWriteCapability.TAX_ASSESS,)
    assert result.terms_version == "tax-terms-v1"
    assert result.terms_sha256 == "b" * 64
    assert result.content_hash == binding.policy_content_hash

    @contextmanager
    def unlocked_runtime_environment(*, environment: str, using: str) -> Iterator[None]:
        yield

    monkeypatch.setattr(policies, "locked_runtime_environment", unlocked_runtime_environment)
    monkeypatch.setattr(policies.timezone, "now", lambda: _AT)
    with pytest.raises(SimulatedCorporateActionWriteGrantUnavailable):
        with policies.locked_simulated_action_owner_policy(
            binding=binding,
            canonical_namespace="account",
            using="default",
            runtime_environment="development",
        ):
            pytest.fail("legacy locked callers must not accept V2 policy")


def test_v2_policy_fingerprint_binds_capabilities_and_terms(policy_world):
    item, install = policy_world
    rows = (
        _v2_item(
            item,
            capabilities=_v2_capabilities(SimulatedCorporateActionWriteCapability.TAX_ASSESS),
            terms_version="tax-terms-v1",
            terms_sha256="b" * 64,
        ),
        _v2_item(
            item,
            capabilities=_v2_capabilities(
                SimulatedCorporateActionWriteCapability.TAX_ASSESS,
                SimulatedCorporateActionWriteCapability.TAX_WITHHOLD,
            ),
            terms_version="tax-terms-v1",
            terms_sha256="b" * 64,
        ),
        _v2_item(
            item,
            capabilities=_v2_capabilities(SimulatedCorporateActionWriteCapability.TAX_ASSESS),
            terms_version="tax-terms-v2",
            terms_sha256="b" * 64,
        ),
        _v2_item(
            item,
            capabilities=_v2_capabilities(SimulatedCorporateActionWriteCapability.TAX_ASSESS),
            terms_version="tax-terms-v1",
            terms_sha256="c" * 64,
        ),
    )
    fingerprints: list[str] = []
    for row in rows:
        binding, _, _, _ = install(
            [row], schema_version="simulated-corporate-action-write-policies.v2"
        )
        result = policies.read_current_simulated_action_write_policy(
            canonical_account_id=binding.account_id,
            owner_user_id=binding.owner_user_id,
            environment="development",
            as_of=_AT,
            expected_grant_schema=SIMULATED_CORPORATE_ACTION_WRITE_GRANT_V2_SCHEMA,
        )
        fingerprints.append(result.content_hash)
    assert len(set(fingerprints)) == len(rows)


@pytest.mark.parametrize(
    "defect",
    [
        "empty_capabilities",
        "unknown_capability",
        "duplicate_capability",
        "noncanonical_order",
        "nonstring_capability",
        "v1_permission",
        "missing_terms_version",
        "missing_terms_sha256",
        "empty_terms_version",
        "uppercase_terms_sha256",
        "unknown_field",
    ],
)
def test_v2_policy_rejects_noncanonical_rights_or_terms(policy_world, defect: str):
    item, install = policy_world
    row = _v2_item(
        item,
        capabilities=_v2_capabilities(
            SimulatedCorporateActionWriteCapability.TAX_ASSESS,
            SimulatedCorporateActionWriteCapability.TAX_WITHHOLD,
        ),
        terms_version="tax-terms-v1",
        terms_sha256="b" * 64,
    )
    if defect == "empty_capabilities":
        row["capabilities"] = []
    elif defect == "unknown_capability":
        row["capabilities"] = ["simulated.corporate_action_tax.unknown"]
    elif defect == "duplicate_capability":
        row["capabilities"] = _v2_capabilities(
            SimulatedCorporateActionWriteCapability.TAX_ASSESS,
            SimulatedCorporateActionWriteCapability.TAX_ASSESS,
        )
    elif defect == "noncanonical_order":
        row["capabilities"] = _v2_capabilities(
            SimulatedCorporateActionWriteCapability.TAX_WITHHOLD,
            SimulatedCorporateActionWriteCapability.TAX_ASSESS,
        )
    elif defect == "nonstring_capability":
        row["capabilities"] = [True]
    elif defect == "v1_permission":
        row["permission"] = SIMULATED_CORPORATE_ACTION_STAGE_WRITE_PERMISSION
    elif defect == "missing_terms_version":
        del row["terms_version"]
    elif defect == "missing_terms_sha256":
        del row["terms_sha256"]
    elif defect == "empty_terms_version":
        row["terms_version"] = ""
    elif defect == "uppercase_terms_sha256":
        row["terms_sha256"] = "B" * 64
    else:
        row["unexpected"] = "extra"
    binding, _, _, _ = install([row], schema_version="simulated-corporate-action-write-policies.v2")
    with pytest.raises(ValueError):
        policies._read_policy(
            binding=binding,
            environment="development",
            as_of=_AT,
            expected_grant_schema=SIMULATED_CORPORATE_ACTION_WRITE_GRANT_V2_SCHEMA,
        )


def test_v1_policy_rejects_v2_rights_fields_and_permission(policy_world):
    item, install = policy_world
    row = _v2_item(
        item,
        capabilities=_v2_capabilities(SimulatedCorporateActionWriteCapability.TAX_ASSESS),
        terms_version="tax-terms-v1",
        terms_sha256="b" * 64,
    )
    binding, _, _, _ = install([row])
    with pytest.raises(ValueError):
        policies._read_policy(binding=binding, environment="development", as_of=_AT)


def test_locked_v2_policy_recheck_compares_new_scope_fields(policy_world, monkeypatch):
    item, install = policy_world
    row = _v2_item(
        item,
        capabilities=_v2_capabilities(SimulatedCorporateActionWriteCapability.TAX_ASSESS),
        terms_version="tax-terms-v1",
        terms_sha256="b" * 64,
    )
    binding, _, _, _ = install([row], schema_version="simulated-corporate-action-write-policies.v2")

    @contextmanager
    def unlocked_runtime_environment(*, environment: str, using: str) -> Iterator[None]:
        yield

    original_read_policy = policies._read_policy
    read_count = 0

    def changed_final_read(*, binding, environment, as_of, expected_grant_schema):
        nonlocal read_count
        result = original_read_policy(
            binding=binding,
            environment=environment,
            as_of=as_of,
            expected_grant_schema=expected_grant_schema,
        )
        read_count += 1
        if read_count == 2:
            return replace(
                result,
                capabilities=(SimulatedCorporateActionWriteCapability.TAX_WITHHOLD,),
            )
        return result

    monkeypatch.setattr(policies, "locked_runtime_environment", unlocked_runtime_environment)
    monkeypatch.setattr(policies.timezone, "now", lambda: _AT)
    monkeypatch.setattr(policies, "_read_policy", changed_final_read)
    with pytest.raises(SimulatedCorporateActionWriteGrantUnavailable):
        with policies.locked_simulated_action_owner_policy(
            binding=binding,
            canonical_namespace="account",
            using="default",
            runtime_environment="development",
            expected_grant_schema=SIMULATED_CORPORATE_ACTION_WRITE_GRANT_V2_SCHEMA,
        ):
            pass
    assert read_count == 2


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
