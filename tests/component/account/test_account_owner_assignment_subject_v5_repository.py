"""PostgreSQL component coverage for the durable Subject V5 ledger."""

import json

import pytest
from django.core.exceptions import ValidationError
from django.db import connections

from apps.account.application.account_owner_assignment_provenance_receipt_v5 import (
    PersistedAccountOwnerAssignmentProvenanceReceiptV5,
)
from apps.account.application.account_owner_assignment_subject_v5 import (
    AccountOwnerAssignmentSubjectV5Corruption,
    AccountOwnerAssignmentSubjectV5Unavailable,
    PersistedAccountOwnerAssignmentSubjectV5,
)
from apps.account.infrastructure.account_owner_assignment_subject_v5_record_codec import (
    encode_account_owner_assignment_subject_v5_record,
)
from apps.account.infrastructure.account_owner_assignment_subject_v5_repository import (
    DjangoAccountOwnerAssignmentSubjectV5Repository,
)
from apps.account.infrastructure.account_owner_assignment_v5_models import (
    AccountOwnerAssignmentSubjectV5Model,
)

# isort 6 splits these aliases while Ruff groups imports from the same test module.
# isort: off
from tests.component.account.test_account_owner_assignment_provenance_receipt_v5_repository import (
    _at,
    _Clock,
    _seed_graph,
)
from tests.component.account.test_account_owner_assignment_provenance_receipt_v5_repository import (
    _repository as _receipt_repository,
)
from tests.component.account.test_account_owner_assignment_provenance_receipt_v5_repository import (
    _table as _receipt_table,
)

# isort: on
from tests.unit.account.test_account_owner_assignment_provenance_receipt_v5 import _receipt
from tests.unit.account.test_account_owner_assignment_subject_v5 import _subject


def _seed_subject(alias: str) -> PersistedAccountOwnerAssignmentSubjectV5:
    receipt = _receipt()
    _seed_graph(alias, receipt)
    receipt_repository = _receipt_repository(alias)
    with receipt_repository.atomic():
        receipt_repository.append(
            PersistedAccountOwnerAssignmentProvenanceReceiptV5(receipt),
            expected_predecessor_hash=None,
            recorded_at=receipt.recorded_at,
        )
    return PersistedAccountOwnerAssignmentSubjectV5(_subject(receipt))


def _repository(alias: str) -> DjangoAccountOwnerAssignmentSubjectV5Repository:
    return DjangoAccountOwnerAssignmentSubjectV5Repository(using=alias, clock=_Clock())


def _exercise_subject_v5_repository_contract(receipt_v5_alias: str) -> None:
    """Exercise replay, history, storage integrity, parents, guards, and alias failures."""

    record = _seed_subject(receipt_v5_alias)
    repository = _repository(receipt_v5_alias)
    with repository.atomic():
        assert repository.append(record, requested_at=record.subject.requested_at) == record
        assert repository.append(record, requested_at=record.subject.requested_at) == record
    assert (
        repository.get_exact_by_hash(
            subject_id=record.subject.subject_id,
            subject_version=record.subject.subject_version,
            expected_content_hash=record.subject.content_hash,
            as_of=_at(30),
        )
        == record
    )
    with pytest.raises(AccountOwnerAssignmentSubjectV5Unavailable, match="future"):
        repository.get_exact_by_hash(
            subject_id=record.subject.subject_id,
            subject_version=record.subject.subject_version,
            expected_content_hash=record.subject.content_hash,
            as_of=_at(31),
        )
    row = AccountOwnerAssignmentSubjectV5Model._base_manager.using(receipt_v5_alias).get()
    with pytest.raises(ValidationError):
        row.save(using=receipt_v5_alias, update_fields=["status"])
    with pytest.raises(ValidationError):
        row.delete(using=receipt_v5_alias)
    subject_table = connections[receipt_v5_alias].ops.quote_name(
        AccountOwnerAssignmentSubjectV5Model._meta.db_table
    )
    with connections[receipt_v5_alias].cursor() as cursor:
        cursor.execute(  # noqa: S608
            f"UPDATE {subject_table} SET canonical_payload = %s::jsonb",
            [json.dumps({"subject": {"tampered": True}}, sort_keys=True)],
        )
    with pytest.raises(AccountOwnerAssignmentSubjectV5Corruption):
        repository.get_winner(
            subject_id=record.subject.subject_id,
            subject_version=record.subject.subject_version,
            as_of=_at(30),
        )
    canonical = encode_account_owner_assignment_subject_v5_record(record)
    with connections[receipt_v5_alias].cursor() as cursor:
        cursor.execute(  # noqa: S608
            f"UPDATE {subject_table} SET canonical_payload = %s::jsonb",
            [json.dumps(canonical, sort_keys=True)],
        )
    with connections[receipt_v5_alias].cursor() as cursor:
        cursor.execute(  # noqa: S608
            f"UPDATE {_receipt_table(receipt_v5_alias)} SET account_id = %s",
            ["tampered-parent"],
        )
    with pytest.raises(AccountOwnerAssignmentSubjectV5Corruption):
        repository.get_exact_by_hash(
            subject_id=record.subject.subject_id,
            subject_version=record.subject.subject_version,
            expected_content_hash=record.subject.content_hash,
            as_of=_at(30),
        )
    with pytest.raises(AccountOwnerAssignmentSubjectV5Unavailable):
        DjangoAccountOwnerAssignmentSubjectV5Repository(using="missing-v5-alias").get_winner(
            subject_id=record.subject.subject_id,
            subject_version=record.subject.subject_version,
            as_of=_at(30),
        )
