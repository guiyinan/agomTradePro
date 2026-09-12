"""Real local PG storage for authenticated V4 evidence over explicit creation fixtures."""

from collections.abc import Iterator
from dataclasses import replace
from datetime import timedelta

import pytest
from django.core.exceptions import ValidationError
from django.db import connections, transaction

from apps.account.application.account_owner_assignment_evidence import (
    AccountOwnerAssignmentConflict,
    AccountOwnerAssignmentCorruption,
    AccountOwnerAssignmentUnavailable,
)
from apps.account.application.account_owner_assignment_evidence_v4 import (
    PersistedAccountOwnerAssignmentEvidenceV4,
)
from apps.account.infrastructure.account_owner_assignment_evidence_v4_models import (
    AccountOwnerAssignmentEvidenceV4Model,
    AccountOwnerAssignmentSubjectV4Model,
)
from apps.account.infrastructure.account_owner_assignment_evidence_v4_repository import (
    DjangoAccountOwnerAssignmentEvidenceV4Repository,
)
from apps.account.infrastructure.account_owner_assignment_provenance_receipt_v4_repository import (
    DjangoAccountOwnerAssignmentProvenanceReceiptV4Repository,
)
from apps.account.infrastructure.single_owner_authority_policy_v1_repository import (
    DjangoSingleOwnerAuthorityPolicyV1Repository,
)
from tests.component.account.test_account_owner_assignment_provenance_receipt_v4_repository import (
    _append,
    _seed_record,
)
from tests.component.account.test_account_owner_assignment_provenance_receipt_v4_repository import (
    creation_alias as creation_alias,
)
from tests.component.account.test_account_owner_assignment_provenance_receipt_v4_repository import (
    evid06_alias as evid06_alias,
)
from tests.component.account.test_account_owner_assignment_provenance_receipt_v4_repository import (
    receipt_alias as receipt_alias,
)
from tests.unit.account.test_account_owner_assignment_evidence_v4 import _evidence, _subject


@pytest.fixture
def assignment_alias(receipt_alias: str) -> Iterator[str]:
    connection = connections[receipt_alias]
    models = (AccountOwnerAssignmentSubjectV4Model, AccountOwnerAssignmentEvidenceV4Model)
    with connection.schema_editor() as editor:
        for model in models:
            editor.create_model(model)
    try:
        yield receipt_alias
    finally:
        with connection.schema_editor() as editor:
            for model in reversed(models):
                editor.delete_model(model)


def _seed(alias, monkeypatch):
    receipt_record = _seed_record(alias, monkeypatch)
    _append(DjangoAccountOwnerAssignmentProvenanceReceiptV4Repository(using=alias), receipt_record)
    now = receipt_record.receipt.recorded_at
    subject = _subject(receipt_record.receipt, requested_at=now)
    evidence = _evidence(
        subject,
        approved_at=now,
        recorded_at=now,
        approval_valid_until=receipt_record.authority.valid_until,
        valid_until=min(subject.valid_until, receipt_record.authority.valid_until),
    )
    return PersistedAccountOwnerAssignmentEvidenceV4(evidence, receipt_record.authority)


def _append_graph(repository, record):
    with repository.atomic():
        subject = record.evidence.subject
        assert repository.append_subject(subject, recorded_at=subject.requested_at) == subject
        return repository.append_root(
            record,
            expected_account_head_hash=None,
            expected_underlying_head_hash=None,
            recorded_at=record.evidence.recorded_at,
        )


def test_graph_roundtrip_selected_alias_outer_rollback_and_exact_replay(
    assignment_alias, monkeypatch
):
    record = _seed(assignment_alias, monkeypatch)
    repository = DjangoAccountOwnerAssignmentEvidenceV4Repository(using=assignment_alias)
    with pytest.raises(RuntimeError, match="rollback graph"):
        with transaction.atomic(using=assignment_alias):
            assert _append_graph(repository, record) == record
            raise RuntimeError("rollback graph")
    assert AccountOwnerAssignmentSubjectV4Model.objects.using(assignment_alias).count() == 0
    assert AccountOwnerAssignmentEvidenceV4Model.objects.using(assignment_alias).count() == 0

    def reject_default_query(execute, sql, params, many, context):
        raise AssertionError("assignment repository queried default alias")

    with connections["default"].execute_wrapper(reject_default_query):
        assert _append_graph(repository, record) == _append_graph(repository, record) == record
        evidence = record.evidence
        assert (
            repository.get_exact_by_hash(
                evidence_id=evidence.evidence_id,
                evidence_version=evidence.evidence_version,
                expected_content_hash=evidence.content_hash,
                as_of=evidence.recorded_at,
            )
            == record
        )
    assert AccountOwnerAssignmentEvidenceV4Model.objects.using(assignment_alias).count() == 1


def test_root_mapping_cas_and_expired_head_never_allow_second_root(assignment_alias, monkeypatch):
    record = _seed(assignment_alias, monkeypatch)
    repository = DjangoAccountOwnerAssignmentEvidenceV4Repository(using=assignment_alias)
    _append_graph(repository, record)
    evidence = record.evidence
    later = evidence.valid_until + timedelta(seconds=1)
    assert (
        repository.get_account_head(
            account_namespace=evidence.subject.binding.account_namespace_claim,
            account_id=evidence.subject.binding.account_id_claim,
            as_of=later,
        )
        == record
    )
    other = replace(
        record,
        evidence=replace(
            evidence,
            evidence_id="another-root",
            identity_hash="",
            content_hash="",
        ),
    )
    with pytest.raises(AccountOwnerAssignmentConflict):
        _append_graph(repository, other)
    assert AccountOwnerAssignmentEvidenceV4Model.objects.using(assignment_alias).count() == 1


def test_unrelated_selector_detects_subject_parent_and_record_tamper(assignment_alias, monkeypatch):
    record = _seed(assignment_alias, monkeypatch)
    repository = DjangoAccountOwnerAssignmentEvidenceV4Repository(using=assignment_alias)
    _append_graph(repository, record)
    table = AccountOwnerAssignmentSubjectV4Model._meta.db_table
    with connections[assignment_alias].cursor() as cursor:
        cursor.execute(f'UPDATE "{table}" SET ledger_seal = %s', ["a" * 64])
    with pytest.raises(AccountOwnerAssignmentCorruption):
        repository.get_winner(
            evidence_id="unrelated", evidence_version="none", as_of=record.evidence.recorded_at
        )


def test_public_orm_mutations_and_private_uow_reentry_are_rejected(assignment_alias, monkeypatch):
    record = _seed(assignment_alias, monkeypatch)
    repository = DjangoAccountOwnerAssignmentEvidenceV4Repository(using=assignment_alias)
    _append_graph(repository, record)
    rows = AccountOwnerAssignmentEvidenceV4Model.objects.using(assignment_alias)
    row = rows.get()
    for operation in (
        lambda: rows.update(status="active"),
        lambda: rows.delete(),
        lambda: rows.bulk_create([AccountOwnerAssignmentEvidenceV4Model()]),
        lambda: row.save(using=assignment_alias),
        lambda: row.save_base(using=assignment_alias),
        lambda: AccountOwnerAssignmentSubjectV4Model.objects.using(assignment_alias).create(),
    ):
        with pytest.raises(ValidationError):
            operation()
    with repository.atomic():
        with pytest.raises(AccountOwnerAssignmentConflict):
            with repository.atomic():
                pass


def test_committed_policy_revocation_rejects_new_approval_without_erasing_subject(
    assignment_alias, monkeypatch
):
    record = _seed(assignment_alias, monkeypatch)
    repository = DjangoAccountOwnerAssignmentEvidenceV4Repository(using=assignment_alias)
    subject = record.evidence.subject
    with repository.atomic():
        repository.append_subject(subject, recorded_at=subject.requested_at)
    now = subject.requested_at + timedelta(seconds=1)
    monkeypatch.setattr("django.utils.timezone.now", lambda: now)
    policy_repository = DjangoSingleOwnerAuthorityPolicyV1Repository(using=assignment_alias)
    revoked = replace(
        subject.policy,
        policy_version="revoked",
        status="revoked",
        observed_at=now,
        identity_hash="",
        content_hash="",
    )
    with policy_repository.atomic():
        policy_repository.append(
            policy=revoked, expected_previous_content_hash=subject.policy.content_hash
        )
    candidate = replace(
        record,
        evidence=replace(
            record.evidence,
            approved_at=now,
            recorded_at=now,
            identity_hash="",
            content_hash="",
        ),
    )
    with pytest.raises(AccountOwnerAssignmentCorruption, match="policy unavailable"):
        with repository.atomic():
            repository.append_root(
                candidate,
                expected_account_head_hash=None,
                expected_underlying_head_hash=None,
                recorded_at=now,
            )
    assert (
        repository.get_subject_winner(
            subject_id=subject.subject_id, subject_version=subject.subject_version, as_of=now
        )
        == subject
    )
    assert AccountOwnerAssignmentEvidenceV4Model.objects.using(assignment_alias).count() == 0


def test_repeatable_read_snapshot_cannot_append_assignment(assignment_alias, monkeypatch):
    record = _seed(assignment_alias, monkeypatch)
    repository = DjangoAccountOwnerAssignmentEvidenceV4Repository(using=assignment_alias)
    with transaction.atomic(using=assignment_alias):
        with connections[assignment_alias].cursor() as cursor:
            cursor.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ")
        with pytest.raises(AccountOwnerAssignmentUnavailable, match="READ COMMITTED"):
            _append_graph(repository, record)
    assert AccountOwnerAssignmentSubjectV4Model.objects.using(assignment_alias).count() == 0
