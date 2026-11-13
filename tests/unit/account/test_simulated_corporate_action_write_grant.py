"""Unit contracts for the Account simulated corporate-action grant ledger."""

from __future__ import annotations

import hashlib
import json
from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest

from apps.account.application.simulated_corporate_action_write_grant import (
    RequireSimulatedCorporateActionWriteGrant,
    SimulatedCorporateActionWriteGrantUnavailable,
)
from apps.account.domain.simulated_corporate_action_write_capabilities import (
    SimulatedCorporateActionWriteCapability,
)
from apps.account.domain.simulated_corporate_action_write_grant import (
    SIMULATED_CORPORATE_ACTION_SERVICE_ACTOR_ID,
    SIMULATED_CORPORATE_ACTION_STAGE_WRITE_PERMISSION,
    SIMULATED_CORPORATE_ACTION_WRITE_GRANT_V2_PERMISSION,
    SIMULATED_CORPORATE_ACTION_WRITE_GRANT_V2_SCHEMA,
    SIMULATED_CORPORATE_ACTION_WRITE_GRANT_V3_PERMISSION,
    SIMULATED_CORPORATE_ACTION_WRITE_GRANT_V3_SCHEMA,
    SimulatedCorporateActionWriteGrant,
    SimulatedCorporateActionWriteGrantBinding,
    SimulatedCorporateActionWriteGrantCurrent,
    SimulatedCorporateActionWriteGrantRecord,
    SimulatedCorporateActionWriteGrantRevocation,
    SimulatedCorporateActionWriteGrantSelector,
    validate_simulated_corporate_action_write_grant_revocation,
    validate_simulated_corporate_action_write_grant_successor,
)

_AT = datetime(2026, 11, 11, 3, 0, tzinfo=UTC)
_HASH_A = "a" * 64
_HASH_B = "b" * 64
_HASH_C = "c" * 64


def _binding(**changes: object) -> SimulatedCorporateActionWriteGrantBinding:
    """Build one exact simulated-account, owner, tenant, source and policy scope."""

    values: dict[str, object] = {
        "account_namespace": "simulated",
        "account_id": "sim-account-41",
        "owner_user_id": 81,
        "tenant_id": "tenant-7",
        "owner_id": "owner-81",
        "account_source_id": "sim-account-source-41",
        "account_source_version": "source-v3",
        "account_source_content_hash": _HASH_A,
        "policy_id": "corporate-action-policy-1",
        "policy_version": "policy-v2",
        "policy_content_hash": _HASH_B,
    }
    values.update(changes)
    return SimulatedCorporateActionWriteGrantBinding(**values)  # type: ignore[arg-type]


def _grant(
    *,
    grant_version: str = "grant-v1",
    recorded_at: datetime = _AT,
    valid_until: datetime | None = None,
    supersedes_content_hash: str | None = None,
    binding: SimulatedCorporateActionWriteGrantBinding | None = None,
) -> SimulatedCorporateActionWriteGrant:
    """Build one finite immutable grant with explicit consent and issuer evidence."""

    return SimulatedCorporateActionWriteGrant(
        grant_id="sim-corp-action-grant-41",
        grant_version=grant_version,
        binding=binding or _binding(),
        consent_evidence_id="consent-41",
        consent_evidence_version="consent-v1",
        consent_evidence_hash=_HASH_B,
        issuer_evidence_id="issuer-41",
        issuer_evidence_version="issuer-v1",
        issuer_evidence_hash=_HASH_C,
        consented_at=recorded_at - timedelta(minutes=2),
        issued_at=recorded_at - timedelta(minutes=1),
        recorded_at=recorded_at,
        valid_until=valid_until or recorded_at + timedelta(hours=2),
        supersedes_content_hash=supersedes_content_hash,
    )


def _grant_v2(
    *,
    capabilities: tuple[SimulatedCorporateActionWriteCapability, ...],
    grant_id: str = "sim-corp-action-grant-41",
    grant_version: str = "grant-v2",
    recorded_at: datetime = _AT + timedelta(hours=1),
    supersedes_content_hash: str | None,
    binding: SimulatedCorporateActionWriteGrantBinding | None = None,
    terms_version: str = "owner-terms-v2",
    terms_sha256: str = _HASH_C,
    service_actor_id: str = SIMULATED_CORPORATE_ACTION_SERVICE_ACTOR_ID,
) -> SimulatedCorporateActionWriteGrant:
    """Build one V2 capability bundle with explicit terms and chain predecessor."""

    return SimulatedCorporateActionWriteGrant(
        grant_id=grant_id,
        grant_version=grant_version,
        binding=binding or _binding(),
        consent_evidence_id="consent-v2-41",
        consent_evidence_version=terms_version,
        consent_evidence_hash=terms_sha256,
        issuer_evidence_id="issuer-v2-41",
        issuer_evidence_version="issuer-v2",
        issuer_evidence_hash=_HASH_A,
        consented_at=recorded_at - timedelta(minutes=2),
        issued_at=recorded_at - timedelta(minutes=1),
        recorded_at=recorded_at,
        valid_until=recorded_at + timedelta(hours=2),
        supersedes_content_hash=supersedes_content_hash,
        permission=SIMULATED_CORPORATE_ACTION_WRITE_GRANT_V2_PERMISSION,
        service_actor_id=service_actor_id,
        schema=SIMULATED_CORPORATE_ACTION_WRITE_GRANT_V2_SCHEMA,
        capabilities=capabilities,
        terms_version=terms_version,
        terms_sha256=terms_sha256,
    )


def _grant_v3(
    *,
    capabilities: tuple[SimulatedCorporateActionWriteCapability, ...],
    grant_id: str = "sim-corp-action-grant-41",
    grant_version: str = "grant-v3",
    recorded_at: datetime = _AT + timedelta(hours=2),
    supersedes_content_hash: str,
    binding: SimulatedCorporateActionWriteGrantBinding | None = None,
    terms_version: str = "owner-terms-v3",
    terms_sha256: str = _HASH_C,
) -> SimulatedCorporateActionWriteGrant:
    """Build one V3 capability bundle with explicit terms and chain predecessor."""

    return SimulatedCorporateActionWriteGrant(
        grant_id=grant_id,
        grant_version=grant_version,
        binding=binding or _binding(),
        consent_evidence_id="consent-v3-41",
        consent_evidence_version=terms_version,
        consent_evidence_hash=terms_sha256,
        issuer_evidence_id="issuer-v3-41",
        issuer_evidence_version="issuer-v3",
        issuer_evidence_hash=_HASH_A,
        consented_at=recorded_at - timedelta(minutes=2),
        issued_at=recorded_at - timedelta(minutes=1),
        recorded_at=recorded_at,
        valid_until=recorded_at + timedelta(hours=2),
        supersedes_content_hash=supersedes_content_hash,
        permission=SIMULATED_CORPORATE_ACTION_WRITE_GRANT_V3_PERMISSION,
        schema=SIMULATED_CORPORATE_ACTION_WRITE_GRANT_V3_SCHEMA,
        capabilities=capabilities,
        terms_version=terms_version,
        terms_sha256=terms_sha256,
    )


def _selector(
    grant: SimulatedCorporateActionWriteGrant,
) -> SimulatedCorporateActionWriteGrantSelector:
    """Build the exact selector for one immutable grant version."""

    return SimulatedCorporateActionWriteGrantSelector(
        grant_id=grant.grant_id,
        grant_version=grant.grant_version,
        identity_hash=grant.identity_hash,
        content_hash=grant.content_hash,
        binding=grant.binding,
    )


def _revocation(
    grant: SimulatedCorporateActionWriteGrant,
    *,
    recorded_at: datetime = _AT + timedelta(minutes=5),
) -> SimulatedCorporateActionWriteGrantRevocation:
    """Build one explicit immutable revocation event for the selected grant."""

    return SimulatedCorporateActionWriteGrantRevocation(
        revocation_id="revoke-41",
        revocation_version="revoke-v1",
        grant_id=grant.grant_id,
        grant_version=grant.grant_version,
        grant_identity_hash=grant.identity_hash,
        grant_content_hash=grant.content_hash,
        revocation_evidence_id="revocation-evidence-41",
        revocation_evidence_version="revocation-evidence-v1",
        revocation_evidence_hash=_HASH_A,
        issuer_evidence_id="issuer-42",
        issuer_evidence_version="issuer-v2",
        issuer_evidence_hash=_HASH_B,
        revoked_at=recorded_at - timedelta(seconds=1),
        recorded_at=recorded_at,
    )


class _Provider:
    """Return a configured exact-current grant projection and record read selectors."""

    def __init__(self, result: object) -> None:
        self.result = result
        self.calls: list[tuple[SimulatedCorporateActionWriteGrantSelector, datetime]] = []

    def get_current_grant(
        self,
        *,
        selector: SimulatedCorporateActionWriteGrantSelector,
        as_of: datetime,
    ) -> object:
        """Record the exact selector request and return the configured projection."""

        self.calls.append((selector, as_of))
        return self.result


def test_grant_binds_only_the_fixed_permission_service_actor_and_exact_scope() -> None:
    grant = _grant()

    assert grant.binding.account_namespace == "simulated"
    assert grant.binding.owner_user_id == 81
    assert grant.permission == SIMULATED_CORPORATE_ACTION_STAGE_WRITE_PERMISSION
    assert grant.service_actor_id == SIMULATED_CORPORATE_ACTION_SERVICE_ACTOR_ID
    assert grant.content_hash == _grant().content_hash
    assert grant.is_active_at(_AT + timedelta(minutes=1))
    assert not grant.is_active_at(grant.valid_until)

    with pytest.raises(ValueError, match="account_namespace"):
        _binding(account_namespace="physical")
    with pytest.raises(ValueError, match="policy_content_hash"):
        _binding(policy_content_hash="not-a-digest")


def test_v1_hashes_payload_and_legacy_permission_mapping_remain_byte_stable() -> None:
    grant = _grant()

    assert grant.identity_hash == "f12b878e7bd6d77d78b830b070eef96ee4cafae97ea1f92dd3a2c086fc309700"
    assert grant.content_hash == "a539aeb903b0d19e69b39109b1cbbbb38e6934c5eab013bf7d2dfc99b2b6a645"
    assert "capabilities" not in grant.to_payload()
    assert "terms_version" not in grant.to_payload()
    assert "terms_sha256" not in grant.to_payload()
    assert grant.supports_capability(SimulatedCorporateActionWriteCapability.CASH_STAGE_WRITE)
    assert not grant.supports_capability(SimulatedCorporateActionWriteCapability.TAX_ASSESS)
    assert not grant.supports_capability(SimulatedCorporateActionWriteCapability.TAX_WITHHOLD)


def test_v2_grant_requires_explicit_capabilities_terms_and_a_distinct_scalar_marker() -> None:
    predecessor = _grant()
    grant = _grant_v2(
        capabilities=(SimulatedCorporateActionWriteCapability.TAX_ASSESS,),
        supersedes_content_hash=predecessor.content_hash,
    )

    assert grant.permission == SIMULATED_CORPORATE_ACTION_WRITE_GRANT_V2_PERMISSION
    assert grant.permission != SIMULATED_CORPORATE_ACTION_STAGE_WRITE_PERMISSION
    assert grant.identity_hash == predecessor.identity_hash
    assert grant.content_hash != predecessor.content_hash
    assert grant.to_payload()["capabilities"] == ["simulated.corporate_action_tax.assess"]
    assert grant.to_payload()["terms_version"] == "owner-terms-v2"
    assert grant.to_payload()["terms_sha256"] == _HASH_C
    assert grant.supports_capability(SimulatedCorporateActionWriteCapability.TAX_ASSESS)
    assert not grant.supports_capability(SimulatedCorporateActionWriteCapability.CASH_STAGE_WRITE)
    assert not grant.supports_capability(SimulatedCorporateActionWriteCapability.TAX_WITHHOLD)
    with pytest.raises(TypeError, match="exact known enum"):
        grant.supports_capability("simulated.corporate_action_tax.assess")  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="service actor"):
        _grant_v2(
            capabilities=(SimulatedCorporateActionWriteCapability.TAX_ASSESS,),
            supersedes_content_hash=predecessor.content_hash,
            service_actor_id="another-service",
        )


def test_v2_grant_rejects_missing_or_invalid_capability_and_terms_fields() -> None:
    predecessor = _grant()
    values: dict[str, object] = {
        "grant_id": predecessor.grant_id,
        "grant_version": "grant-v2",
        "binding": predecessor.binding,
        "consent_evidence_id": "consent-v2",
        "consent_evidence_version": "terms-v2",
        "consent_evidence_hash": _HASH_A,
        "issuer_evidence_id": "issuer-v2",
        "issuer_evidence_version": "issuer-v2",
        "issuer_evidence_hash": _HASH_B,
        "consented_at": _AT,
        "issued_at": _AT,
        "recorded_at": _AT,
        "valid_until": _AT + timedelta(hours=1),
        "supersedes_content_hash": predecessor.content_hash,
        "permission": SIMULATED_CORPORATE_ACTION_WRITE_GRANT_V2_PERMISSION,
        "schema": SIMULATED_CORPORATE_ACTION_WRITE_GRANT_V2_SCHEMA,
    }
    for invalid in (
        {},
        {"capabilities": ()},
        {
            "capabilities": (
                SimulatedCorporateActionWriteCapability.TAX_ASSESS,
                SimulatedCorporateActionWriteCapability.TAX_ASSESS,
            ),
        },
        {
            "capabilities": (
                SimulatedCorporateActionWriteCapability.TAX_WITHHOLD,
                SimulatedCorporateActionWriteCapability.TAX_ASSESS,
            ),
        },
        {"capabilities": ("unknown.permission",)},
        {"capabilities": (SimulatedCorporateActionWriteCapability.TAX_ASSESS,)},
        {
            "capabilities": (SimulatedCorporateActionWriteCapability.TAX_ASSESS,),
            "terms_version": "",
            "terms_sha256": _HASH_A,
        },
        {
            "capabilities": (SimulatedCorporateActionWriteCapability.TAX_ASSESS,),
            "terms_version": "terms-v2",
            "terms_sha256": "not-a-digest",
        },
    ):
        with pytest.raises((TypeError, ValueError)):
            SimulatedCorporateActionWriteGrant(**(values | invalid))  # type: ignore[arg-type]


@pytest.mark.parametrize(
    "capability",
    (
        SimulatedCorporateActionWriteCapability.SHARE_STAGE_WRITE,
        SimulatedCorporateActionWriteCapability.RIGHTS_NOT_EXERCISED,
    ),
)
def test_v2_grant_cannot_claim_new_v3_capabilities(
    capability: SimulatedCorporateActionWriteCapability,
) -> None:
    predecessor = _grant()
    capabilities = tuple(
        sorted(
            (SimulatedCorporateActionWriteCapability.TAX_ASSESS, capability),
            key=lambda item: item.value,
        )
    )

    with pytest.raises(ValueError, match="V2 grant cannot include V3 capabilities"):
        _grant_v2(capabilities=capabilities, supersedes_content_hash=predecessor.content_hash)


def test_v3_grant_binds_new_capabilities_and_uses_its_own_content_hash_domain() -> None:
    predecessor = _grant_v2(
        capabilities=(SimulatedCorporateActionWriteCapability.CASH_STAGE_WRITE,),
        recorded_at=_AT + timedelta(hours=1),
        supersedes_content_hash=_grant().content_hash,
    )
    capabilities = tuple(
        sorted(
            (
                SimulatedCorporateActionWriteCapability.SHARE_STAGE_WRITE,
                SimulatedCorporateActionWriteCapability.RIGHTS_NOT_EXERCISED,
                SimulatedCorporateActionWriteCapability.CASH_STAGE_WRITE,
            ),
            key=lambda item: item.value,
        )
    )
    grant = _grant_v3(
        capabilities=capabilities,
        supersedes_content_hash=predecessor.content_hash,
    )

    assert grant.schema == SIMULATED_CORPORATE_ACTION_WRITE_GRANT_V3_SCHEMA
    assert grant.permission == SIMULATED_CORPORATE_ACTION_WRITE_GRANT_V3_PERMISSION
    assert grant.identity_hash == predecessor.identity_hash
    assert grant.supports_capability(SimulatedCorporateActionWriteCapability.SHARE_STAGE_WRITE)
    assert grant.supports_capability(SimulatedCorporateActionWriteCapability.RIGHTS_NOT_EXERCISED)
    assert not grant.supports_capability(SimulatedCorporateActionWriteCapability.TAX_WITHHOLD)
    payload = grant.to_payload()
    assert payload["capabilities"] == [item.value for item in capabilities]
    assert payload["terms_version"] == "owner-terms-v3"
    assert payload["terms_sha256"] == _HASH_C
    hash_payload = {
        key: value for key, value in payload.items() if key not in {"identity_hash", "content_hash"}
    }
    expected_hash = hashlib.sha256(
        json.dumps(
            {
                "domain": "account.simulated-corporate-action-write-grant.v3/content",
                "payload": hash_payload,
            },
            allow_nan=False,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    ).hexdigest()
    assert grant.content_hash == expected_hash


def test_successor_schema_may_advance_to_v3_but_never_downgrade() -> None:
    v1 = _grant()
    v2 = _grant_v2(
        capabilities=(SimulatedCorporateActionWriteCapability.CASH_STAGE_WRITE,),
        recorded_at=_AT + timedelta(hours=1),
        supersedes_content_hash=v1.content_hash,
    )
    v3 = _grant_v3(
        capabilities=(SimulatedCorporateActionWriteCapability.SHARE_STAGE_WRITE,),
        recorded_at=_AT + timedelta(hours=2),
        supersedes_content_hash=v2.content_hash,
    )
    v3_from_v1 = _grant_v3(
        capabilities=(SimulatedCorporateActionWriteCapability.SHARE_STAGE_WRITE,),
        grant_version="grant-v3-from-v1",
        recorded_at=_AT + timedelta(minutes=30),
        supersedes_content_hash=v1.content_hash,
    )
    v3_next = _grant_v3(
        capabilities=(SimulatedCorporateActionWriteCapability.RIGHTS_NOT_EXERCISED,),
        grant_version="grant-v3-next",
        recorded_at=_AT + timedelta(hours=3),
        supersedes_content_hash=v3.content_hash,
    )

    validate_simulated_corporate_action_write_grant_successor(v1, v3_from_v1)
    validate_simulated_corporate_action_write_grant_successor(v2, v3)
    validate_simulated_corporate_action_write_grant_successor(v3, v3_next)
    with pytest.raises(ValueError, match="downgrade"):
        validate_simulated_corporate_action_write_grant_successor(v3, v2)


def test_successor_allows_confirmed_v1_to_v2_and_source_policy_refresh_only_in_same_owner_chain():
    predecessor = _grant()
    refreshed = _binding(
        account_source_id="sim-account-source-41-v2",
        account_source_version="source-v4",
        account_source_content_hash=_HASH_C,
        policy_id="corporate-action-policy-2",
        policy_version="policy-v3",
        policy_content_hash=_HASH_A,
    )
    successor = _grant_v2(
        capabilities=(
            SimulatedCorporateActionWriteCapability.TAX_ASSESS,
            SimulatedCorporateActionWriteCapability.TAX_WITHHOLD,
            SimulatedCorporateActionWriteCapability.CASH_STAGE_WRITE,
        ),
        recorded_at=_AT + timedelta(hours=1),
        supersedes_content_hash=predecessor.content_hash,
        binding=refreshed,
    )

    validate_simulated_corporate_action_write_grant_successor(predecessor, successor)


def test_v2_successor_can_explicitly_narrow_and_cannot_cross_owner_or_chain():
    predecessor = _grant_v2(
        capabilities=(
            SimulatedCorporateActionWriteCapability.TAX_ASSESS,
            SimulatedCorporateActionWriteCapability.TAX_WITHHOLD,
            SimulatedCorporateActionWriteCapability.CASH_STAGE_WRITE,
        ),
        grant_version="grant-v2",
        recorded_at=_AT + timedelta(hours=1),
        supersedes_content_hash=_grant().content_hash,
    )
    successor = _grant_v2(
        capabilities=(SimulatedCorporateActionWriteCapability.TAX_ASSESS,),
        grant_version="grant-v3",
        recorded_at=_AT + timedelta(hours=2),
        supersedes_content_hash=predecessor.content_hash,
        binding=_binding(policy_version="policy-v4", policy_content_hash=_HASH_C),
        terms_version="owner-terms-v3",
        terms_sha256=_HASH_B,
    )

    validate_simulated_corporate_action_write_grant_successor(predecessor, successor)

    cross_owner = _grant_v2(
        capabilities=(SimulatedCorporateActionWriteCapability.TAX_ASSESS,),
        grant_version="grant-v3-owner",
        recorded_at=_AT + timedelta(hours=2),
        supersedes_content_hash=predecessor.content_hash,
        binding=_binding(owner_user_id=82, owner_id="owner-82"),
    )
    with pytest.raises(ValueError, match="identity|scope"):
        validate_simulated_corporate_action_write_grant_successor(predecessor, cross_owner)

    cross_chain = _grant_v2(
        capabilities=(SimulatedCorporateActionWriteCapability.TAX_ASSESS,),
        grant_id="another-grant-chain",
        grant_version="grant-v3-chain",
        recorded_at=_AT + timedelta(hours=2),
        supersedes_content_hash=predecessor.content_hash,
    )
    with pytest.raises(ValueError, match="grant_id|identity"):
        validate_simulated_corporate_action_write_grant_successor(predecessor, cross_chain)

    v1_downgrade = _grant(
        grant_version="grant-v3-v1",
        recorded_at=_AT + timedelta(hours=2),
        supersedes_content_hash=predecessor.content_hash,
    )
    with pytest.raises(ValueError, match="downgrade|version"):
        validate_simulated_corporate_action_write_grant_successor(predecessor, v1_downgrade)


def test_v2_exact_revocation_targets_the_complete_capability_bundle_hash():
    grant = _grant_v2(
        capabilities=(
            SimulatedCorporateActionWriteCapability.TAX_ASSESS,
            SimulatedCorporateActionWriteCapability.CASH_STAGE_WRITE,
        ),
        supersedes_content_hash=_grant().content_hash,
    )
    revocation = _revocation(grant, recorded_at=grant.recorded_at + timedelta(minutes=5))

    validate_simulated_corporate_action_write_grant_revocation(grant, revocation)
    assert revocation.grant_content_hash == grant.content_hash

    changed_target = replace(
        revocation, grant_content_hash=_HASH_B, identity_hash="", content_hash=""
    )
    with pytest.raises(ValueError, match="target"):
        validate_simulated_corporate_action_write_grant_revocation(grant, changed_target)


def test_grant_fact_hashes_schema_and_v1_payload_are_fail_closed() -> None:
    grant = _grant()

    with pytest.raises(TypeError, match="exact string"):
        replace(grant, identity_hash=None)  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="does not match"):
        replace(grant, content_hash="f" * 64)
    with pytest.raises(ValueError, match="permission is fixed"):
        replace(grant, permission="another-permission")
    with pytest.raises(ValueError, match="V1 grants"):
        replace(
            grant,
            capabilities=(SimulatedCorporateActionWriteCapability.TAX_ASSESS,),
        )
    with pytest.raises(ValueError, match="V3 grant permission marker is fixed"):
        replace(grant, schema="account.simulated_corporate_action_write_grant.v3")
    with pytest.raises(ValueError, match="exact positive integer"):
        _binding(owner_user_id=True)

    v2 = _grant_v2(
        capabilities=(SimulatedCorporateActionWriteCapability.TAX_ASSESS,),
        supersedes_content_hash=grant.content_hash,
    )
    with pytest.raises(ValueError, match="V2 grant permission marker"):
        replace(
            v2,
            permission=SIMULATED_CORPORATE_ACTION_STAGE_WRITE_PERMISSION,
            identity_hash="",
            content_hash="",
        )
    with pytest.raises(ValueError, match="terms_sha256 is required"):
        replace(v2, terms_sha256=None, identity_hash="", content_hash="")
    with pytest.raises(ValueError, match="capabilities are required"):
        replace(v2, capabilities=None, identity_hash="", content_hash="")


def test_selector_current_and_historical_grant_records_validate_exact_types() -> None:
    grant = _grant()
    revocation = _revocation(grant)

    with pytest.raises(TypeError, match="exact simulated write grant binding"):
        replace(grant.selector, binding=object())  # type: ignore[arg-type]
    with pytest.raises(TypeError, match="exact simulated corporate-action write grant"):
        SimulatedCorporateActionWriteGrantCurrent(grant=object())  # type: ignore[arg-type]
    with pytest.raises(TypeError, match="exact simulated write grant revocation"):
        SimulatedCorporateActionWriteGrantCurrent(
            grant=grant,
            revocation=object(),  # type: ignore[arg-type]
        )

    record = SimulatedCorporateActionWriteGrantRecord(grant=grant, revocation=revocation)
    assert record.grant is grant
    assert record.revocation is revocation
    with pytest.raises(TypeError, match="grant record requires"):
        SimulatedCorporateActionWriteGrantRecord(grant=object())  # type: ignore[arg-type]
    with pytest.raises(TypeError, match="grant record revocation"):
        SimulatedCorporateActionWriteGrantRecord(
            grant=grant,
            revocation=object(),  # type: ignore[arg-type]
        )


def test_grant_rejects_empty_or_naive_validity_and_unsealed_evidence() -> None:
    with pytest.raises(ValueError, match="clock sequence"):
        _grant(valid_until=_AT)
    with pytest.raises(ValueError, match="timezone-aware"):
        _grant(recorded_at=datetime(2026, 11, 11, 3, 0))

    with pytest.raises(ValueError, match="issuer_evidence_hash"):
        SimulatedCorporateActionWriteGrant(
            grant_id="grant-1",
            grant_version="v1",
            binding=_binding(),
            consent_evidence_id="consent-1",
            consent_evidence_version="v1",
            consent_evidence_hash=_HASH_A,
            issuer_evidence_id="issuer-1",
            issuer_evidence_version="v1",
            issuer_evidence_hash="unverified",
            consented_at=_AT,
            issued_at=_AT,
            recorded_at=_AT,
            valid_until=_AT + timedelta(minutes=1),
        )


def test_successor_must_extend_the_same_exact_scope_and_name_its_predecessor() -> None:
    predecessor = _grant()
    successor = _grant(
        grant_version="grant-v2",
        recorded_at=_AT + timedelta(hours=1),
        supersedes_content_hash=predecessor.content_hash,
        binding=_binding(policy_version="policy-v3", policy_content_hash=_HASH_C),
    )

    validate_simulated_corporate_action_write_grant_successor(predecessor, successor)

    changed_owner = _grant(
        grant_version="grant-v3",
        recorded_at=_AT + timedelta(hours=1),
        supersedes_content_hash=predecessor.content_hash,
        binding=_binding(owner_id="owner-82"),
    )
    with pytest.raises(ValueError, match="identity|scope"):
        validate_simulated_corporate_action_write_grant_successor(predecessor, changed_owner)

    wrong_predecessor = _grant(
        grant_version="grant-v4",
        recorded_at=_AT + timedelta(hours=1),
        supersedes_content_hash=_HASH_C,
    )
    with pytest.raises(ValueError, match="predecessor"):
        validate_simulated_corporate_action_write_grant_successor(predecessor, wrong_predecessor)

    same_version = _grant(
        grant_version=predecessor.grant_version,
        recorded_at=_AT + timedelta(hours=1),
        supersedes_content_hash=predecessor.content_hash,
    )
    with pytest.raises(ValueError, match="grant_version"):
        validate_simulated_corporate_action_write_grant_successor(predecessor, same_version)

    same_time = _grant(
        grant_version="grant-v5",
        recorded_at=predecessor.recorded_at,
        supersedes_content_hash=predecessor.content_hash,
    )
    with pytest.raises(ValueError, match="recorded after"):
        validate_simulated_corporate_action_write_grant_successor(predecessor, same_time)


def test_revocation_is_an_explicit_event_bound_to_one_exact_grant_hash() -> None:
    grant = _grant()
    revocation = _revocation(grant)

    validate_simulated_corporate_action_write_grant_revocation(grant, revocation)
    current = SimulatedCorporateActionWriteGrantCurrent(grant=grant, revocation=revocation)

    assert not current.is_active_at(_AT + timedelta(minutes=6))
    assert not SimulatedCorporateActionWriteGrantCurrent(grant=grant).is_active_at(
        grant.valid_until
    )

    different_grant = _grant(
        binding=_binding(policy_version="policy-v3", policy_content_hash=_HASH_C)
    )
    wrong_target = _revocation(different_grant)
    with pytest.raises(ValueError, match="target"):
        validate_simulated_corporate_action_write_grant_revocation(grant, wrong_target)


def test_application_reads_only_the_exact_current_selector_and_fails_closed() -> None:
    grant = _grant()
    selector = _selector(grant)
    provider = _Provider(SimulatedCorporateActionWriteGrantCurrent(grant=grant))
    require = RequireSimulatedCorporateActionWriteGrant(provider)

    assert require.execute(selector, as_of=_AT + timedelta(minutes=1)) == grant
    assert provider.calls == [(selector, _AT + timedelta(minutes=1))]

    stale = _grant(grant_version="grant-v0")
    for invalid in (
        SimulatedCorporateActionWriteGrantCurrent(grant=stale),
        SimulatedCorporateActionWriteGrantCurrent(
            grant=grant,
            revocation=_revocation(grant, recorded_at=_AT + timedelta(minutes=1)),
        ),
        object(),
    ):
        provider.result = invalid
        with pytest.raises(SimulatedCorporateActionWriteGrantUnavailable):
            require.execute(selector, as_of=_AT + timedelta(minutes=1))


def test_application_rejects_missing_provider_and_naive_cutoff() -> None:
    with pytest.raises(SimulatedCorporateActionWriteGrantUnavailable):
        RequireSimulatedCorporateActionWriteGrant(None)

    grant = _grant()
    require = RequireSimulatedCorporateActionWriteGrant(
        _Provider(SimulatedCorporateActionWriteGrantCurrent(grant=grant))
    )
    with pytest.raises(SimulatedCorporateActionWriteGrantUnavailable):
        require.execute(_selector(grant), as_of=datetime(2026, 11, 11, 3, 0))
