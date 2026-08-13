"""Component evidence for the closed Account creation-claim receipt-v3 ledger."""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime
from importlib import import_module
from unittest.mock import patch

import pytest
from django.core.exceptions import ValidationError
from django.db import IntegrityError, connection

from apps.account.application.account_owner_assignment_evidence import (
    AccountOwnerAssignmentConflict,
    AccountOwnerAssignmentCorruption,
    AccountOwnerAssignmentServerActor,
)
from apps.account.application.account_owner_assignment_provenance_receipt_v3 import (
    PersistedAccountOwnerAssignmentProvenanceReceiptV3,
)
from apps.account.application.canonical_account_creation_binding_v2 import (
    CanonicalAccountCreationBindingV2Corruption,
)
from apps.account.infrastructure.account_owner_assignment_provenance_receipt_v3_models import (
    AccountOwnerAssignmentProvenanceReceiptV3Model,
)
from apps.account.infrastructure.account_owner_assignment_provenance_receipt_v3_repository import (
    DjangoAccountOwnerAssignmentProvenanceReceiptV3Repository,
)
from apps.account.infrastructure.canonical_account_creation_consumption_models import (
    CanonicalAccountCreationConsumptionClaimModel,
)
from tests.component.account.test_canonical_account_creation_consumption_repository import (
    _append_pair,
    _pair,
    _seed_v2_foreign_evidence,
)
from tests.component.account.test_canonical_account_creation_consumption_repository import (
    _repository as _consumption_repository,
)
from tests.unit.account.test_account_owner_assignment_provenance_receipt_v3 import _at, _receipt


class _Clock:
    def now(self) -> datetime:
        return _at(9)


def _seed_binding():  # type: ignore[no-untyped-def]
    binding, claim = _pair()
    _seed_v2_foreign_evidence(binding)
    consumption = _consumption_repository()
    with consumption.atomic():
        _append_pair(consumption, binding, claim)
    return binding


def _record(*, receipt_changes: dict[str, object] | None = None):  # type: ignore[no-untyped-def]
    binding = _seed_binding()
    receipt = _receipt(binding=binding, **(receipt_changes or {}))
    actor = AccountOwnerAssignmentServerActor(
        receipt.claimant.actor_id, receipt.claimant.user_id, receipt.claimant.role
    )
    return PersistedAccountOwnerAssignmentProvenanceReceiptV3(receipt, actor)


@pytest.mark.django_db(transaction=True)
def test_roundtrip_historical_exact_and_append_only_guards() -> None:
    record = _record()
    repository = DjangoAccountOwnerAssignmentProvenanceReceiptV3Repository(clock=_Clock())
    with repository.atomic():
        assert (
            repository.append(
                record, expected_predecessor_hash=None, recorded_at=record.receipt.recorded_at
            )
            == record
        )
    assert (
        repository.get_winner(
            receipt_id=record.receipt.receipt_id,
            receipt_version=record.receipt.receipt_version,
            as_of=_at(16),
        )
        == record
    )
    assert (
        repository.get_exact_by_hash(
            receipt_id=record.receipt.receipt_id,
            receipt_version=record.receipt.receipt_version,
            expected_content_hash=record.receipt.content_hash,
            as_of=_at(16),
        )
        == record
    )
    row = AccountOwnerAssignmentProvenanceReceiptV3Model.objects.get()
    assert row.binding_id is not None and len(row.root_claim_hash or "") == 64
    assert all(
        len(getattr(row, name)) == 64
        for name in (
            "binding_seal",
            "claimant_seal",
            "actor_binding_seal",
            "chain_seal",
            "fixed_authority_seal",
            "header_seal",
            "record_seal",
            "ledger_seal",
        )
    )
    with pytest.raises(ValidationError):
        AccountOwnerAssignmentProvenanceReceiptV3Model().save()


@pytest.mark.django_db(transaction=True)
def test_missing_claim_knowledge_fails_closed() -> None:
    record = _record()
    repository = DjangoAccountOwnerAssignmentProvenanceReceiptV3Repository(clock=_Clock())
    table = connection.ops.quote_name(CanonicalAccountCreationConsumptionClaimModel._meta.db_table)
    with connection.cursor() as cursor:
        cursor.execute(f"UPDATE {table} SET knowledge_at = NULL")  # noqa: S608
    with pytest.raises(CanonicalAccountCreationBindingV2Corruption):
        with repository.atomic():
            repository.append(
                record, expected_predecessor_hash=None, recorded_at=record.receipt.recorded_at
            )


@pytest.mark.django_db(transaction=True)
def test_claim_known_after_receipt_clock_cannot_be_backdated() -> None:
    record = _record()
    repository = DjangoAccountOwnerAssignmentProvenanceReceiptV3Repository(clock=_Clock())
    table = connection.ops.quote_name(CanonicalAccountCreationConsumptionClaimModel._meta.db_table)
    with connection.cursor() as cursor:
        cursor.execute(f"UPDATE {table} SET knowledge_at = %s", [_at(15)])  # noqa: S608
    with pytest.raises(AccountOwnerAssignmentCorruption):
        with repository.atomic():
            repository.append(
                record, expected_predecessor_hash=None, recorded_at=record.receipt.recorded_at
            )


@pytest.mark.django_db(transaction=True)
def test_unrelated_header_tamper_fails_every_selector_closed() -> None:
    record = _record()
    repository = DjangoAccountOwnerAssignmentProvenanceReceiptV3Repository(clock=_Clock())
    with repository.atomic():
        repository.append(
            record, expected_predecessor_hash=None, recorded_at=record.receipt.recorded_at
        )
    table = connection.ops.quote_name(AccountOwnerAssignmentProvenanceReceiptV3Model._meta.db_table)
    with connection.cursor() as cursor:
        cursor.execute(f"UPDATE {table} SET header_seal = %s", ["0" * 64])  # noqa: S608
    with pytest.raises(AccountOwnerAssignmentCorruption):
        repository.get_winner(receipt_id="not-the-row", receipt_version="v0", as_of=_at(16))


@pytest.mark.django_db(transaction=True)
def test_integrity_error_uses_savepoint_before_exact_replay_check() -> None:
    record = _record()
    repository = DjangoAccountOwnerAssignmentProvenanceReceiptV3Repository(clock=_Clock())
    queryset_type = type(AccountOwnerAssignmentProvenanceReceiptV3Model.objects.all())
    with repository.atomic():
        with patch.object(queryset_type, "create", side_effect=IntegrityError("race")):
            with pytest.raises(AccountOwnerAssignmentConflict, match="concurrent"):
                repository.append(
                    record,
                    expected_predecessor_hash=None,
                    recorded_at=record.receipt.recorded_at,
                )
        assert AccountOwnerAssignmentProvenanceReceiptV3Model.objects.count() == 0


@pytest.mark.django_db(transaction=True)
def test_expired_successor_remains_final_ledger_head_without_fallback() -> None:
    first = _record(receipt_changes={"valid_until": _at(11)})
    repository = DjangoAccountOwnerAssignmentProvenanceReceiptV3Repository(clock=_Clock())
    with repository.atomic():
        repository.append(
            first, expected_predecessor_hash=None, recorded_at=first.receipt.recorded_at
        )
    second_receipt = replace(
        first.receipt,
        receipt_version="v3.2",
        issued_at=_at(9),
        recorded_at=_at(10),
        valid_until=_at(12),
        supersedes_content_hash=first.receipt.content_hash,
        identity_hash="",
        content_hash="",
    )
    second = PersistedAccountOwnerAssignmentProvenanceReceiptV3(second_receipt, first.issued_by)
    with repository.atomic():
        repository.append(
            second,
            expected_predecessor_hash=first.receipt.content_hash,
            recorded_at=second.receipt.recorded_at,
        )
    assert repository.get_current_head(receipt_id=first.receipt.receipt_id, as_of=_at(13)) == second


def test_0049_is_schema_only_zero_seed_migration() -> None:
    migration = import_module(
        "apps.account.migrations.0049_account_owner_assignment_provenance_receipt_v3_ledger"
    ).Migration
    assert migration.dependencies == [
        ("account", "0048_canonical_account_creation_consumption_knowledge_clock_expand")
    ]
    assert migration.operations
    assert all(
        type(operation).__name__ not in {"RunPython", "RunSQL"}
        for operation in migration.operations
    )
