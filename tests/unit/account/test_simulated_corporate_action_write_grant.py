"""Unit contracts for the Account simulated corporate-action grant ledger."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from apps.account.application.simulated_corporate_action_write_grant import (
    RequireSimulatedCorporateActionWriteGrant,
    SimulatedCorporateActionWriteGrantUnavailable,
)
from apps.account.domain.simulated_corporate_action_write_grant import (
    SIMULATED_CORPORATE_ACTION_SERVICE_ACTOR_ID,
    SIMULATED_CORPORATE_ACTION_STAGE_WRITE_PERMISSION,
    SimulatedCorporateActionWriteGrant,
    SimulatedCorporateActionWriteGrantBinding,
    SimulatedCorporateActionWriteGrantCurrent,
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
