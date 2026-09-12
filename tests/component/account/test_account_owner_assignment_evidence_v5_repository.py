"""PostgreSQL contract for the re-observation-backed Evidence V5 ledger."""

from __future__ import annotations

import json
from collections.abc import Iterator
from contextlib import AbstractContextManager
from datetime import UTC, datetime
from importlib import import_module
from typing import Protocol

import pytest
from django.apps import apps
from django.core.exceptions import ValidationError
from django.db import connections
from django.db.migrations.state import ProjectState

from apps.account.application.account_owner_assignment_actor_authority_v3 import (
    CurrentAccountActorAuthorityV3,
)
from apps.account.application.account_owner_assignment_evidence_v5 import (
    AccountOwnerAssignmentEvidenceV5Corruption,
    AccountOwnerAssignmentEvidenceV5Unavailable,
    PersistedAccountOwnerAssignmentEvidenceV5,
)
from apps.account.application.account_owner_assignment_provenance_receipt_v5 import (
    PersistedAccountOwnerAssignmentProvenanceReceiptV5,
)
from apps.account.application.account_owner_assignment_subject_v5 import (
    PersistedAccountOwnerAssignmentSubjectV5,
)
from apps.account.domain.account_owner_assignment_actor_authority_source_v3 import (
    AccountOwnerAssignmentActorAuthoritySourceV3,
    root_claim_hash_for_actor_authority_source_v3,
)
from apps.account.infrastructure.account_owner_assignment_actor_authority_source_v3_repository import (
    DjangoAccountOwnerAssignmentActorAuthoritySourceV3Repository,
)
from apps.account.infrastructure.account_owner_assignment_evidence_v5_record_codec import (
    encode_account_owner_assignment_evidence_v5_record,
)
from apps.account.infrastructure.account_owner_assignment_evidence_v5_repository import (
    DjangoAccountOwnerAssignmentEvidenceV5Repository,
)
from apps.account.infrastructure.account_owner_assignment_provenance_receipt_v5_repository import (
    DjangoAccountOwnerAssignmentProvenanceReceiptV5Repository,
)
from apps.account.infrastructure.account_owner_assignment_subject_v5_repository import (
    DjangoAccountOwnerAssignmentSubjectV5Repository,
)
from apps.account.infrastructure.account_owner_assignment_v5_models import (
    AccountOwnerAssignmentEvidenceV5Model,
    AccountOwnerAssignmentProvenanceReceiptV5Model,
    AccountOwnerAssignmentSubjectV5Model,
)
from apps.account.infrastructure.allocated_physical_account_row_observation_v3_models import (
    AllocatedPhysicalAccountRowObservationV3Model,
)
from apps.account.infrastructure.canonical_account_creation_consumption_models import (
    CanonicalAccountCreationBindingV2Model,
    CanonicalAccountCreationConsumptionClaimModel,
)
from apps.account.infrastructure.canonical_account_creation_models import (
    CanonicalAccountCreationAllocationModel,
    CanonicalAccountCreationBindingModel,
)
from apps.account.infrastructure.canonical_account_ownership_reobservation_v1_models import (
    CanonicalAccountOwnershipReobservationV1Model,
)
from apps.account.infrastructure.physical_account_row_observation_v2_models import (
    PhysicalAccountRowObservationV2Model,
)
from apps.account.infrastructure.single_owner_authority_policy_v1_models import (
    SingleOwnerAuthorityPolicyV1Model,
)
from tests.component.account.test_account_actor_authority_raw_source_publisher_postgres import (
    evid06_alias as evid06_alias,
)
from tests.component.account.test_account_owner_assignment_actor_authority_source_v3_repository import (
    _record as _actor_record,
)
from tests.component.account.test_account_owner_assignment_provenance_receipt_v5_repository import (
    _seed_graph,
)
from tests.unit.account.test_account_owner_assignment_actor_authority_source_v3 import (
    _source as _actor_source,
)
from tests.unit.account.test_account_owner_assignment_evidence_v5 import _evidence
from tests.unit.account.test_account_owner_assignment_subject_v5 import _subject


class _DjangoDbBlocker(Protocol):
    """Narrow fixture protocol for isolated schema DDL."""

    def unblock(self) -> AbstractContextManager[None]:
        """Temporarily allow isolated schema changes."""
        ...


class _Clock:
    """Return one deterministic cutoff after every sealed source clock."""

    def now(self) -> datetime:
        """Return the test repository clock."""

        return datetime(2026, 8, 30, 12, tzinfo=UTC)


_MODELS = (
    CanonicalAccountCreationAllocationModel,
    AllocatedPhysicalAccountRowObservationV3Model,
    CanonicalAccountCreationConsumptionClaimModel,
    CanonicalAccountCreationBindingModel,
    CanonicalAccountCreationBindingV2Model,
    PhysicalAccountRowObservationV2Model,
    CanonicalAccountOwnershipReobservationV1Model,
    SingleOwnerAuthorityPolicyV1Model,
    AccountOwnerAssignmentProvenanceReceiptV5Model,
    AccountOwnerAssignmentSubjectV5Model,
    AccountOwnerAssignmentEvidenceV5Model,
)


@pytest.fixture(name="evidence_v5_alias")
def evidence_v5_alias(evid06_alias: str, django_db_blocker: _DjangoDbBlocker) -> Iterator[str]:
    """Extend the disposable authority database with the exact V5 parent graph."""

    connection = connections[evid06_alias]
    created: list[type] = []
    with django_db_blocker.unblock():
        try:
            with connection.schema_editor() as editor:
                for model in _MODELS:
                    editor.create_model(model)
                    created.append(model)
            yield evid06_alias
        finally:
            with connection.schema_editor() as editor:
                for model in reversed(created):
                    editor.delete_model(model)


def _authority_source() -> AccountOwnerAssignmentActorAuthoritySourceV3:
    recorded_at = datetime(2026, 8, 15, 14, 20, tzinfo=UTC)
    valid_until = datetime(2026, 8, 30, 12, tzinfo=UTC)
    return _actor_source(
        source_id="account-authority-source",
        source_version="v3",
        principal_id="principal-42",
        user_id=42,
        authentication_context_id="session-admin-42",
        user_source_id="django-user-42",
        rbac_source_id="account-profile-42",
        actor_id="django-user:42",
        is_staff=True,
        is_superuser=True,
        rbac_role="admin",
        principal_authenticated_at=datetime(2026, 8, 15, 14, tzinfo=UTC),
        principal_valid_until=valid_until,
        source_recorded_at=datetime(2026, 8, 15, 14, 10, tzinfo=UTC),
        source_valid_until=valid_until,
        issued_at=datetime(2026, 8, 15, 14, 15, tzinfo=UTC),
        recorded_at=recorded_at,
        ttl_valid_until=valid_until,
        valid_until=valid_until,
        root_claim_hash=root_claim_hash_for_actor_authority_source_v3(
            source_id="account-authority-source",
            principal_id="principal-42",
            user_id=42,
            authentication_context_identity_hash="a" * 64,
            actor_id="django-user:42",
        ),
    )


def _authority(
    source: AccountOwnerAssignmentActorAuthoritySourceV3,
) -> CurrentAccountActorAuthorityV3:
    return CurrentAccountActorAuthorityV3(
        source.principal_id,
        source.user_id,
        source.authentication_context_content_hash,
        source.actor_id,
        source.is_authenticated,
        source.is_active,
        source.is_staff,
        source.is_superuser,
        source.rbac_role,
        source.source_id,
        source.source_version,
        source.content_hash,
        source.recorded_at,
        source.valid_until,
    )


def _seed(
    alias: str,
    *,
    actor_source: AccountOwnerAssignmentActorAuthoritySourceV3 | None = None,
) -> PersistedAccountOwnerAssignmentEvidenceV5:
    """Persist the historical graph with an optional real current actor source."""
    clock = _Clock()
    subject = _subject()
    _seed_graph(alias, subject.receipt)
    receipts = DjangoAccountOwnerAssignmentProvenanceReceiptV5Repository(using=alias, clock=clock)
    receipt_record = PersistedAccountOwnerAssignmentProvenanceReceiptV5(subject.receipt)
    with receipts.atomic():
        receipts.append(
            receipt_record,
            expected_predecessor_hash=None,
            recorded_at=subject.receipt.recorded_at,
        )
    subjects = DjangoAccountOwnerAssignmentSubjectV5Repository(using=alias, clock=clock)
    with subjects.atomic():
        subjects.append(
            PersistedAccountOwnerAssignmentSubjectV5(subject),
            requested_at=subject.requested_at,
        )
    source = actor_source if actor_source is not None else _authority_source()
    actors = DjangoAccountOwnerAssignmentActorAuthoritySourceV3Repository(using=alias, clock=clock)
    with actors.atomic():
        actors.append(
            _actor_record(source),
            expected_predecessor_hash=None,
            recorded_at=source.recorded_at,
        )
    return PersistedAccountOwnerAssignmentEvidenceV5(_evidence(subject), _authority(source))


@pytest.mark.django_db(transaction=True, databases="__all__")
def test_evidence_v5_repository_replay_exact_heads_and_tamper(
    evidence_v5_alias: str,
) -> None:
    """Prove exact parents, first-winner replay, both heads, and tamper closure."""

    expected = _seed(evidence_v5_alias)
    evidence = expected.evidence
    repository = DjangoAccountOwnerAssignmentEvidenceV5Repository(
        using=evidence_v5_alias, clock=_Clock()
    )
    with repository.atomic():
        assert (
            repository.append_root(
                expected,
                expected_account_head_hash=None,
                expected_underlying_head_hash=None,
                recorded_at=evidence.recorded_at,
            )
            == expected
        )
        assert (
            repository.append_root(
                expected,
                expected_account_head_hash=None,
                expected_underlying_head_hash=None,
                recorded_at=evidence.recorded_at,
            )
            == expected
        )
    assert (
        repository.get_exact_by_hash(
            evidence_id=evidence.evidence_id,
            evidence_version=evidence.evidence_version,
            expected_content_hash=evidence.content_hash,
            as_of=_Clock().now(),
        )
        == expected
    )
    binding = evidence.subject.binding
    assert (
        repository.get_account_head(
            account_namespace=binding.account_namespace_claim,
            account_id=binding.account_id_claim,
            as_of=_Clock().now(),
        )
        == expected
    )
    assert (
        repository.get_underlying_head(
            underlying_unified_account_namespace=(
                binding.underlying_unified_account_namespace_claim
            ),
            underlying_unified_account_id=binding.underlying_unified_account_id_claim,
            as_of=_Clock().now(),
        )
        == expected
    )
    with pytest.raises(AccountOwnerAssignmentEvidenceV5Unavailable, match="future"):
        repository.get_winner(
            evidence_id=evidence.evidence_id,
            evidence_version=evidence.evidence_version,
            as_of=datetime(2026, 8, 30, 12, 0, 0, 1, tzinfo=UTC),
        )
    row = AccountOwnerAssignmentEvidenceV5Model._base_manager.using(evidence_v5_alias).get()
    assert row.subject_id > 0 and row.actor_source_id > 0
    assert row.canonical_payload == encode_account_owner_assignment_evidence_v5_record(expected)
    with pytest.raises(ValidationError):
        row.delete(using=evidence_v5_alias)
    canonical = row.canonical_payload
    record_seal = row.record_seal
    with connections[evidence_v5_alias].cursor() as cursor:
        table = connections[evidence_v5_alias].ops.quote_name(row._meta.db_table)
        cursor.execute(
            f"UPDATE {table} SET canonical_payload = %s::jsonb",  # noqa: S608
            [json.dumps({"tampered": True})],
        )
    with pytest.raises(AccountOwnerAssignmentEvidenceV5Corruption):
        repository.get_winner(
            evidence_id=evidence.evidence_id,
            evidence_version=evidence.evidence_version,
            as_of=_Clock().now(),
        )
    with connections[evidence_v5_alias].cursor() as cursor:
        cursor.execute(
            f"UPDATE {table} SET canonical_payload = %s::jsonb",  # noqa: S608
            [json.dumps(canonical, sort_keys=True)],
        )
        cursor.execute(  # noqa: S608
            f"UPDATE {table} SET record_seal = %s",
            ["0" * 64],
        )
    with pytest.raises(AccountOwnerAssignmentEvidenceV5Corruption):
        repository.get_winner(
            evidence_id=evidence.evidence_id,
            evidence_version=evidence.evidence_version,
            as_of=_Clock().now(),
        )
    with connections[evidence_v5_alias].cursor() as cursor:
        cursor.execute(  # noqa: S608
            f"UPDATE {table} SET record_seal = %s",
            [record_seal],
        )


@pytest.mark.django_db(transaction=True, databases="__all__")
def test_migration_0062_roundtrip_constraints_and_parent_foreign_keys(
    evidence_v5_alias: str,
) -> None:
    """Apply, reverse, and reapply the schema-only Evidence V5 migration."""

    connection = connections[evidence_v5_alias]
    migration_module = import_module(
        "apps.account.migrations.0062_account_owner_assignment_evidence_v5"
    )
    migration = migration_module.Migration("0062_account_owner_assignment_evidence_v5", "account")
    before = ProjectState.from_apps(apps)
    before.remove_model("account", "accountownerassignmentevidencev5model")
    with connection.schema_editor() as editor:
        editor.delete_model(AccountOwnerAssignmentEvidenceV5Model)
    try:
        for _ in range(2):
            with connection.schema_editor() as editor:
                migration.apply(before.clone(), editor)
            try:
                with connection.cursor() as cursor:
                    constraints = connection.introspection.get_constraints(
                        cursor, AccountOwnerAssignmentEvidenceV5Model._meta.db_table
                    )
                assert {
                    constraint.name
                    for constraint in AccountOwnerAssignmentEvidenceV5Model._meta.constraints
                } <= set(constraints)
                assert sum(bool(value["foreign_key"]) for value in constraints.values()) == 2
            finally:
                with connection.schema_editor() as editor:
                    migration.unapply(before.clone(), editor)
            assert (
                AccountOwnerAssignmentEvidenceV5Model._meta.db_table
                not in connection.introspection.table_names()
            )
    finally:
        with connection.schema_editor() as editor:
            editor.create_model(AccountOwnerAssignmentEvidenceV5Model)
