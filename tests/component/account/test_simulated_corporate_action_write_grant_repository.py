"""Component checks for immutable simulated corporate-action grant persistence."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest
from django.core.exceptions import ValidationError

from apps.account.application.simulated_corporate_action_write_grant import (
    RequireSimulatedCorporateActionWriteGrant,
    SimulatedCorporateActionWriteGrantConflict,
    SimulatedCorporateActionWriteGrantUnavailable,
)
from apps.account.domain.simulated_corporate_action_write_grant import (
    SimulatedCorporateActionWriteGrant,
    SimulatedCorporateActionWriteGrantBinding,
    SimulatedCorporateActionWriteGrantRevocation,
)
from apps.account.infrastructure.simulated_corporate_action_write_grant_models import (
    SimulatedCorporateActionWriteGrantModel,
    SimulatedCorporateActionWriteGrantRevocationModel,
)
from apps.account.infrastructure.simulated_corporate_action_write_grant_repository import (
    DjangoSimulatedCorporateActionWriteGrantRepository,
)

pytestmark = pytest.mark.django_db

_AT = datetime(2026, 11, 11, 3, 0, tzinfo=UTC)
_HASH_A = "a" * 64
_HASH_B = "b" * 64
_HASH_C = "c" * 64


class _Clock:
    """Return a fixed aware repository timestamp for deterministic persistence tests."""

    def __init__(self, value: datetime) -> None:
        self.value = value

    def now(self) -> datetime:
        """Return the configured server time."""

        return self.value


def _binding() -> SimulatedCorporateActionWriteGrantBinding:
    """Return the fixture's exact simulated account and owner/tenant scope."""

    return SimulatedCorporateActionWriteGrantBinding(
        account_namespace="simulated",
        account_id="sim-account-41",
        owner_user_id=81,
        tenant_id="tenant-7",
        owner_id="owner-81",
        account_source_id="sim-account-source-41",
        account_source_version="source-v3",
        account_source_content_hash=_HASH_A,
        policy_id="corporate-action-policy-1",
        policy_version="policy-v2",
        policy_content_hash=_HASH_B,
    )


def _grant(
    *,
    grant_id: str = "sim-corp-action-grant-41",
    version: str = "grant-v1",
    at: datetime = _AT,
    supersedes_content_hash: str | None = None,
    policy_version: str = "policy-v2",
    policy_content_hash: str = _HASH_B,
    valid_until: datetime | None = None,
    binding: SimulatedCorporateActionWriteGrantBinding | None = None,
) -> SimulatedCorporateActionWriteGrant:
    """Build one grant version whose source and policy facts are explicitly hashed."""

    grant_binding = binding or _binding()
    if binding is None and policy_version != "policy-v2":
        grant_binding = SimulatedCorporateActionWriteGrantBinding(
            account_namespace=grant_binding.account_namespace,
            account_id=grant_binding.account_id,
            owner_user_id=grant_binding.owner_user_id,
            tenant_id=grant_binding.tenant_id,
            owner_id=grant_binding.owner_id,
            account_source_id=grant_binding.account_source_id,
            account_source_version=grant_binding.account_source_version,
            account_source_content_hash=grant_binding.account_source_content_hash,
            policy_id=grant_binding.policy_id,
            policy_version=policy_version,
            policy_content_hash=policy_content_hash,
        )
    return SimulatedCorporateActionWriteGrant(
        grant_id=grant_id,
        grant_version=version,
        binding=grant_binding,
        consent_evidence_id="consent-41",
        consent_evidence_version="consent-v1",
        consent_evidence_hash=_HASH_B,
        issuer_evidence_id="issuer-41",
        issuer_evidence_version="issuer-v1",
        issuer_evidence_hash=_HASH_C,
        consented_at=at - timedelta(minutes=2),
        issued_at=at - timedelta(minutes=1),
        recorded_at=at,
        valid_until=valid_until or at + timedelta(hours=2),
        supersedes_content_hash=supersedes_content_hash,
    )


def _revocation(
    grant: SimulatedCorporateActionWriteGrant,
    *,
    recorded_at: datetime,
) -> SimulatedCorporateActionWriteGrantRevocation:
    """Build one revocation for an exact grant content hash."""

    return SimulatedCorporateActionWriteGrantRevocation(
        revocation_id="sim-corp-action-revocation-41",
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


def test_repository_appends_replays_and_reads_one_exact_root() -> None:
    repository = DjangoSimulatedCorporateActionWriteGrantRepository(clock=_Clock(_AT))
    grant = _grant()

    assert repository.append_grant(grant, expected_predecessor_content_hash=None) == grant
    assert repository.append_grant(grant, expected_predecessor_content_hash=None) == grant
    current = repository.get_current_grant(
        selector=grant.selector, as_of=_AT + timedelta(minutes=1)
    )

    assert current is not None
    assert current.grant == grant
    assert current.revocation is None
    assert (
        not SimulatedCorporateActionWriteGrantModel.objects.filter(grant_id=grant.grant_id)
        .exclude(content_hash=grant.content_hash)
        .exists()
    )


def test_repository_successor_replaces_exact_head_without_old_version_fallback() -> None:
    root = _grant()
    repository = DjangoSimulatedCorporateActionWriteGrantRepository(clock=_Clock(_AT))
    repository.append_grant(root, expected_predecessor_content_hash=None)
    successor_at = _AT + timedelta(minutes=10)
    successor = _grant(
        version="grant-v2",
        at=successor_at,
        supersedes_content_hash=root.content_hash,
        policy_version="policy-v3",
        policy_content_hash=_HASH_C,
    )
    repository._clock.value = successor_at

    assert (
        repository.append_grant(
            successor,
            expected_predecessor_content_hash=root.content_hash,
        )
        == successor
    )
    assert (
        repository.get_current_grant(
            selector=root.selector,
            as_of=successor_at + timedelta(minutes=1),
        )
        is None
    )
    current = repository.get_current_grant(
        selector=successor.selector,
        as_of=successor_at + timedelta(minutes=1),
    )
    assert current is not None
    assert current.grant == successor
    assert SimulatedCorporateActionWriteGrantModel.objects.count() == 2


def test_repository_rejects_wrong_predecessor_and_preserves_the_old_head() -> None:
    root = _grant()
    repository = DjangoSimulatedCorporateActionWriteGrantRepository(clock=_Clock(_AT))
    repository.append_grant(root, expected_predecessor_content_hash=None)
    next_at = _AT + timedelta(minutes=10)
    successor = _grant(
        version="grant-v2",
        at=next_at,
        supersedes_content_hash=root.content_hash,
    )
    repository._clock.value = next_at

    with pytest.raises(SimulatedCorporateActionWriteGrantConflict):
        repository.append_grant(successor, expected_predecessor_content_hash=_HASH_A)

    assert SimulatedCorporateActionWriteGrantModel.objects.count() == 1
    assert (
        repository.get_current_grant(
            selector=root.selector,
            as_of=next_at + timedelta(minutes=1),
        )
        is not None
    )


def test_repository_persists_a_separate_revocation_and_application_fails_closed() -> None:
    grant = _grant()
    repository = DjangoSimulatedCorporateActionWriteGrantRepository(clock=_Clock(_AT))
    repository.append_grant(grant, expected_predecessor_content_hash=None)
    revoked_at = _AT + timedelta(minutes=10)
    revocation = _revocation(grant, recorded_at=revoked_at)
    repository._clock.value = revoked_at

    assert repository.append_revocation(revocation) == revocation
    assert repository.append_revocation(revocation) == revocation
    current = repository.get_current_grant(
        selector=grant.selector,
        as_of=revoked_at + timedelta(minutes=1),
    )
    assert current is None
    assert SimulatedCorporateActionWriteGrantRevocationModel.objects.count() == 1
    assert (
        repository.get_current_for_scope(
            "simulated",
            "sim-account-41",
            as_of=revoked_at + timedelta(minutes=1),
        )
        == ()
    )

    require = RequireSimulatedCorporateActionWriteGrant(repository)
    with pytest.raises(SimulatedCorporateActionWriteGrantUnavailable):
        require.execute(grant.selector, as_of=revoked_at + timedelta(minutes=1))


def test_exact_selector_absence_does_not_fallback_to_an_available_root() -> None:
    grant = _grant()
    repository = DjangoSimulatedCorporateActionWriteGrantRepository(clock=_Clock(_AT))
    repository.append_grant(grant, expected_predecessor_content_hash=None)

    missing = _grant(version="grant-v0")
    assert (
        repository.get_current_grant(
            selector=missing.selector,
            as_of=_AT + timedelta(minutes=1),
        )
        is None
    )


def test_scope_reader_preserves_owner_conflicts_and_never_falls_back_from_expired_head() -> None:
    repository = DjangoSimulatedCorporateActionWriteGrantRepository(clock=_Clock(_AT))
    first = _grant(
        grant_id="scope-grant-first",
        valid_until=_AT + timedelta(hours=5),
    )
    second_binding = replace(_binding(), owner_user_id=82, owner_id="owner-82")
    second = _grant(grant_id="scope-grant-second", binding=second_binding)
    repository.append_grant(first, expected_predecessor_content_hash=None)
    repository.append_grant(second, expected_predecessor_content_hash=None)

    initial = repository.get_current_for_scope(
        "simulated",
        "sim-account-41",
        as_of=_AT + timedelta(minutes=1),
    )
    assert {grant.grant_id for grant in initial} == {first.grant_id, second.grant_id}
    assert {grant.binding.owner_user_id for grant in initial} == {81, 82}
    assert (
        repository.get_current_for_scope(
            "physical",
            "sim-account-41",
            as_of=_AT + timedelta(minutes=1),
        )
        == ()
    )

    successor_at = _AT + timedelta(minutes=10)
    successor = _grant(
        grant_id=first.grant_id,
        version="grant-v2",
        at=successor_at,
        supersedes_content_hash=first.content_hash,
        valid_until=successor_at + timedelta(minutes=10),
    )
    repository._clock.value = successor_at
    repository.append_grant(
        successor,
        expected_predecessor_content_hash=first.content_hash,
    )

    current_heads = repository.get_current_for_scope(
        "simulated",
        "sim-account-41",
        as_of=successor_at + timedelta(minutes=5),
    )
    assert {grant.grant_version for grant in current_heads} == {"grant-v2", "grant-v1"}
    expired_heads = repository.get_current_for_scope(
        "simulated",
        "sim-account-41",
        as_of=successor_at + timedelta(minutes=10),
    )
    assert tuple(grant.grant_id for grant in expired_heads) == (second.grant_id,)


def test_orm_paths_cannot_bypass_the_repository_append_claim() -> None:
    grant = _grant()
    repository = DjangoSimulatedCorporateActionWriteGrantRepository(clock=_Clock(_AT))
    repository.append_grant(grant, expected_predecessor_content_hash=None)
    row = SimulatedCorporateActionWriteGrantModel.objects.get(content_hash=grant.content_hash)

    with pytest.raises(ValidationError, match="exact appends"):
        SimulatedCorporateActionWriteGrantModel.objects.create(
            **{
                key: value
                for key, value in row.__dict__.items()
                if key
                in {field.name for field in SimulatedCorporateActionWriteGrantModel._meta.fields}
                and key != "id"
            }
        )
    with pytest.raises(ValidationError, match="Append-only"):
        SimulatedCorporateActionWriteGrantModel.objects.filter(pk=row.pk).update(status="revoked")
    row.status = "revoked"
    with pytest.raises(ValidationError, match="append-only"):
        row.save(using="default")
    with pytest.raises(ValidationError, match="append-only"):
        row.delete(using="default")
