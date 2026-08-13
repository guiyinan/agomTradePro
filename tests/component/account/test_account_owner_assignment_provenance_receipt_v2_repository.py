"""Component coverage for the closed Account provenance v2 ledger."""

from __future__ import annotations

import ast
from dataclasses import replace
from datetime import datetime
from pathlib import Path

import pytest
from django.core.exceptions import ValidationError
from django.db import connection

from apps.account.application.account_owner_assignment_evidence import (
    AccountOwnerAssignmentServerActor,
)
from apps.account.application.account_owner_assignment_provenance_receipt_v2 import (
    AccountOwnerAssignmentProvenanceReceiptV2Conflict,
    AccountOwnerAssignmentProvenanceReceiptV2Corruption,
    PersistedAccountOwnerAssignmentProvenanceReceiptV2,
)
from apps.account.infrastructure.account_owner_assignment_provenance_receipt_v2_codec import (
    AccountOwnerAssignmentProvenanceReceiptV2CodecError,
    decode_account_owner_assignment_provenance_receipt_v2_record,
    encode_account_owner_assignment_provenance_receipt_v2_record,
)
from apps.account.infrastructure.account_owner_assignment_provenance_receipt_v2_models import (
    AccountOwnerAssignmentProvenanceReceiptV2Model,
)
from apps.account.infrastructure.account_owner_assignment_provenance_receipt_v2_repository import (
    DjangoAccountOwnerAssignmentProvenanceReceiptV2Repository,
)
from tests.unit.account.test_account_owner_assignment_provenance_receipt_v2 import (
    _at,
    _receipt,
)


class _Clock:
    def now(self) -> datetime:
        return _at(6)


def _record(*, receipt_version: str = "v1") -> PersistedAccountOwnerAssignmentProvenanceReceiptV2:
    receipt = _receipt(receipt_version=receipt_version)
    actor = AccountOwnerAssignmentServerActor(
        actor_id=receipt.claimant.actor_id,
        user_id=receipt.claimant.user_id,
        role=receipt.claimant.role,
        kind=receipt.claimant.kind,
        is_staff=receipt.claimant.is_staff,
    )
    return PersistedAccountOwnerAssignmentProvenanceReceiptV2(receipt, actor)


@pytest.mark.django_db(transaction=True)
def test_roundtrip_exact_first_winner_and_append_only_guards() -> None:
    repository = DjangoAccountOwnerAssignmentProvenanceReceiptV2Repository(clock=_Clock())
    record = _record()
    with repository.atomic():
        assert (
            repository.append(
                record,
                expected_predecessor_hash=None,
                recorded_at=record.receipt.recorded_at,
            )
            == record
        )
    assert (
        repository.get_winner(
            receipt_id=record.receipt.receipt_id,
            receipt_version=record.receipt.receipt_version,
            as_of=_at(7),
        )
        == record
    )
    assert (
        repository.get_exact_by_hash(
            receipt_id=record.receipt.receipt_id,
            receipt_version=record.receipt.receipt_version,
            expected_content_hash=record.receipt.content_hash,
            as_of=_at(7),
        )
        == record
    )
    row = AccountOwnerAssignmentProvenanceReceiptV2Model.objects.get()
    assert row.persisted_at == record.receipt.recorded_at
    assert len(row.root_claim_hash or "") == 64
    assert all(
        len(getattr(row, name)) == 64
        for name in (
            "row_binding_seal",
            "actor_binding_seal",
            "fixed_authority_seal",
            "header_seal",
            "record_seal",
            "ledger_seal",
        )
    )
    with pytest.raises(ValidationError):
        AccountOwnerAssignmentProvenanceReceiptV2Model().save()


@pytest.mark.django_db(transaction=True)
def test_second_root_is_rejected_and_header_tampering_cannot_hide_it() -> None:
    repository = DjangoAccountOwnerAssignmentProvenanceReceiptV2Repository(clock=_Clock())
    first = _record()
    with repository.atomic():
        repository.append(
            first,
            expected_predecessor_hash=None,
            recorded_at=first.receipt.recorded_at,
        )
    second_root = _record(receipt_version="v2")
    with pytest.raises(AccountOwnerAssignmentProvenanceReceiptV2Conflict):
        with repository.atomic():
            repository.append(
                second_root,
                expected_predecessor_hash=None,
                recorded_at=second_root.receipt.recorded_at,
            )
    table = connection.ops.quote_name(AccountOwnerAssignmentProvenanceReceiptV2Model._meta.db_table)
    row_id = AccountOwnerAssignmentProvenanceReceiptV2Model._base_manager.get().pk
    with connection.cursor() as cursor:
        cursor.execute(f"UPDATE {table} SET receipt_id = %s WHERE id = %s", ["hidden", row_id])
    with pytest.raises(AccountOwnerAssignmentProvenanceReceiptV2Corruption):
        repository.get_current_head(receipt_id=first.receipt.receipt_id, as_of=_at(7))


@pytest.mark.django_db(transaction=True)
def test_successor_cas_and_expired_head_never_fall_back() -> None:
    repository = DjangoAccountOwnerAssignmentProvenanceReceiptV2Repository(clock=_Clock())
    first = _record()
    successor_receipt = replace(
        first.receipt,
        receipt_version="v2",
        row_observation_version="v2",
        row_observation_identity_hash="1" * 64,
        row_observation_content_hash="2" * 64,
        row_observation_supersedes_content_hash=first.receipt.row_observation_content_hash,
        issued_at=_at(7),
        recorded_at=_at(8),
        valid_until=_at(9),
        supersedes_content_hash=first.receipt.content_hash,
        identity_hash="",
        content_hash="",
    )
    successor = PersistedAccountOwnerAssignmentProvenanceReceiptV2(
        successor_receipt, first.issued_by
    )
    with repository.atomic():
        repository.append(
            first,
            expected_predecessor_hash=None,
            recorded_at=first.receipt.recorded_at,
        )
        assert (
            repository.append(
                successor,
                expected_predecessor_hash=first.receipt.content_hash,
                recorded_at=successor.receipt.recorded_at,
            )
            == successor
        )
    assert (
        repository.get_current_head(receipt_id=first.receipt.receipt_id, as_of=_at(8)) == successor
    )
    assert (
        repository.get_exact_by_hash(
            receipt_id=successor.receipt.receipt_id,
            receipt_version=successor.receipt.receipt_version,
            expected_content_hash=successor.receipt.content_hash,
            as_of=_at(9),
        )
        is None
    )
    assert (
        repository.get_exact_by_hash(
            receipt_id=first.receipt.receipt_id,
            receipt_version=first.receipt.receipt_version,
            expected_content_hash=first.receipt.content_hash,
            as_of=_at(9),
        )
        is None
    )


@pytest.mark.django_db(transaction=True)
def test_codec_and_all_direct_mutation_paths_fail_closed() -> None:
    repository = DjangoAccountOwnerAssignmentProvenanceReceiptV2Repository(clock=_Clock())
    record = _record()
    payload = encode_account_owner_assignment_provenance_receipt_v2_record(record)
    assert decode_account_owner_assignment_provenance_receipt_v2_record(payload) == record
    with pytest.raises(AccountOwnerAssignmentProvenanceReceiptV2CodecError):
        decode_account_owner_assignment_provenance_receipt_v2_record({**payload, "extra": True})
    with repository.atomic():
        repository.append(
            record,
            expected_predecessor_hash=None,
            recorded_at=record.receipt.recorded_at,
        )
    row = AccountOwnerAssignmentProvenanceReceiptV2Model._base_manager.get()
    for action in (
        lambda: AccountOwnerAssignmentProvenanceReceiptV2Model.objects.update(status="active"),
        lambda: AccountOwnerAssignmentProvenanceReceiptV2Model.objects.all().delete(),
        lambda: AccountOwnerAssignmentProvenanceReceiptV2Model.objects.bulk_create([row]),
        lambda: row.save(update_fields=["status"]),
        lambda: row.save_base(raw=True),
        lambda: row.delete(),
    ):
        with pytest.raises(ValidationError):
            action()


def test_0043_migration_is_schema_only() -> None:
    migration = Path(
        "apps/account/migrations/0043_account_owner_assignment_provenance_receipt_v2_ledger.py"
    )
    tree = ast.parse(migration.read_text(encoding="utf-8"))
    calls = {
        node.func.attr
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
    }
    assert "CreateModel" in calls
    assert calls.isdisjoint({"RunPython", "RunSQL", "AddField", "AlterField"})
