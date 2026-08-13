"""Django append-only repository for Account creation-claim receipts v3."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime
from typing import Protocol

from django.db import IntegrityError, transaction
from django.utils import timezone

from apps.account.application.account_owner_assignment_evidence import (
    AccountOwnerAssignmentConflict,
    AccountOwnerAssignmentCorruption,
)
from apps.account.application.account_owner_assignment_provenance_receipt_v3 import (
    PersistedAccountOwnerAssignmentProvenanceReceiptV3,
)
from apps.account.domain.account_owner_assignment_provenance_receipt_v3 import (
    validate_account_owner_assignment_provenance_receipt_v3_root,
    validate_account_owner_assignment_provenance_receipt_v3_successor,
)
from apps.account.domain.canonical_account_creation_binding_v2 import (
    CanonicalAccountCreationBindingV2,
)
from apps.account.infrastructure.account_owner_assignment_provenance_receipt_v3_codec import (
    decode_account_owner_assignment_provenance_receipt_v3_record,
    encode_account_owner_assignment_provenance_receipt_v3_record,
)
from apps.account.infrastructure.account_owner_assignment_provenance_receipt_v3_models import (
    AccountOwnerAssignmentProvenanceReceiptV3Model,
    _activate_account_owner_assignment_provenance_receipt_v3_uow,
    _claim_account_owner_assignment_provenance_receipt_v3_insert,
)
from apps.account.infrastructure.canonical_account_creation_consumption_models import (
    CanonicalAccountCreationBindingV2Model,
)
from apps.account.infrastructure.canonical_account_creation_consumption_repository import (
    DjangoCanonicalAccountCreationConsumptionRepository,
)


class AccountOwnerAssignmentProvenanceReceiptV3Clock(Protocol):
    def now(self) -> datetime: ...


class DjangoAccountOwnerAssignmentProvenanceReceiptV3Clock:
    def now(self) -> datetime:
        return timezone.now()


class DjangoAccountOwnerAssignmentProvenanceReceiptV3Repository:
    """Restore the entire ledger and every referenced consumption world before selection."""

    def __init__(
        self,
        *,
        clock: AccountOwnerAssignmentProvenanceReceiptV3Clock | None = None,
        using: str = "default",
    ) -> None:
        if type(using) is not str or not using or using.strip() != using:
            raise ValueError("using must be an exact database alias")
        self._clock = clock or DjangoAccountOwnerAssignmentProvenanceReceiptV3Clock()
        self._using = using
        self._consumption = DjangoCanonicalAccountCreationConsumptionRepository(using=using)
        self._uow: object | None = None

    @contextmanager
    def atomic(self) -> Iterator[None]:
        if self._uow is not None:
            raise AccountOwnerAssignmentConflict("nested provenance v3 UOW")
        token = object()
        self._uow = token
        try:
            with (
                transaction.atomic(using=self._using),
                _activate_account_owner_assignment_provenance_receipt_v3_uow(token),
            ):
                yield
        finally:
            self._uow = None

    def now(self) -> datetime:
        value = self._clock.now()
        if type(value) is not datetime or value.tzinfo is None or value.utcoffset() is None:
            raise AccountOwnerAssignmentCorruption("repository clock is naive")
        return value

    def get_winner(
        self, *, receipt_id: str, receipt_version: str, as_of: datetime
    ) -> PersistedAccountOwnerAssignmentProvenanceReceiptV3 | None:
        return next(
            (
                record
                for _, record in self._closed_world(as_of=as_of)
                if (record.receipt.receipt_id, record.receipt.receipt_version)
                == (receipt_id, receipt_version)
                and record.receipt.recorded_at <= as_of
            ),
            None,
        )

    def get_exact_by_hash(
        self, *, receipt_id: str, receipt_version: str, expected_content_hash: str, as_of: datetime
    ) -> PersistedAccountOwnerAssignmentProvenanceReceiptV3 | None:
        record = self.get_winner(
            receipt_id=receipt_id, receipt_version=receipt_version, as_of=as_of
        )
        return (
            record
            if record is not None and record.receipt.content_hash == expected_content_hash
            else None
        )

    def get_current_head(
        self, *, receipt_id: str, as_of: datetime
    ) -> PersistedAccountOwnerAssignmentProvenanceReceiptV3 | None:
        chain = self._chain(receipt_id=receipt_id, as_of=as_of)
        return chain[-1][1] if chain else None

    def append(
        self,
        record: PersistedAccountOwnerAssignmentProvenanceReceiptV3,
        *,
        expected_predecessor_hash: str | None,
        recorded_at: datetime,
    ) -> PersistedAccountOwnerAssignmentProvenanceReceiptV3:
        record.__post_init__()
        if self._uow is None:
            raise AccountOwnerAssignmentConflict("append requires private UOW")
        receipt = record.receipt
        if recorded_at != receipt.recorded_at:
            raise AccountOwnerAssignmentCorruption("persisted_at must equal recorded_at")
        binding_row = (
            CanonicalAccountCreationBindingV2Model._base_manager.using(self._using)
            .select_for_update()
            .filter(
                binding_id=receipt.binding.binding_id,
                binding_version=receipt.binding.binding_version,
                content_hash=receipt.binding.content_hash,
            )
            .first()
        )
        if binding_row is None:
            raise AccountOwnerAssignmentCorruption("Binding-v2 parent is unavailable")
        self._require_binding(binding_row, receipt.binding, as_of=recorded_at)
        existing = self.get_winner(
            receipt_id=receipt.receipt_id,
            receipt_version=receipt.receipt_version,
            as_of=recorded_at,
        )
        if existing is not None:
            if existing != record:
                raise AccountOwnerAssignmentConflict("receipt identity first winner differs")
            return existing
        chain = self._chain(receipt_id=receipt.receipt_id, as_of=recorded_at)
        head_row, head = chain[-1] if chain else (None, None)
        actual = head.receipt.content_hash if head is not None else None
        if (
            actual != expected_predecessor_hash
            or receipt.supersedes_content_hash != expected_predecessor_hash
        ):
            raise AccountOwnerAssignmentConflict("receipt predecessor CAS failed")
        try:
            if head is None:
                validate_account_owner_assignment_provenance_receipt_v3_root(receipt)
            else:
                validate_account_owner_assignment_provenance_receipt_v3_successor(
                    head.receipt, receipt
                )
        except (TypeError, ValueError) as error:
            raise AccountOwnerAssignmentCorruption("invalid receipt chain append") from error
        values = _model_values(
            record,
            binding_pk=binding_row.pk,
            predecessor_pk=(head_row.pk if head_row is not None else None),
        )
        try:
            with (
                transaction.atomic(using=self._using),
                _claim_account_owner_assignment_provenance_receipt_v3_insert(
                    token=self._uow,
                    model_type=AccountOwnerAssignmentProvenanceReceiptV3Model,
                    expected_values=values,
                ),
            ):
                AccountOwnerAssignmentProvenanceReceiptV3Model._default_manager.using(
                    self._using
                ).create(**values)
        except IntegrityError as error:
            winner = self.get_winner(
                receipt_id=receipt.receipt_id,
                receipt_version=receipt.receipt_version,
                as_of=recorded_at,
            )
            if winner == record:
                return winner
            raise AccountOwnerAssignmentConflict(
                "concurrent receipt winner or successor"
            ) from error
        restored = self.get_winner(
            receipt_id=receipt.receipt_id,
            receipt_version=receipt.receipt_version,
            as_of=recorded_at,
        )
        if restored != record:
            raise AccountOwnerAssignmentCorruption("receipt restore mismatch")
        return restored

    def _chain(
        self, *, receipt_id: str, as_of: datetime
    ) -> tuple[
        tuple[
            AccountOwnerAssignmentProvenanceReceiptV3Model,
            PersistedAccountOwnerAssignmentProvenanceReceiptV3,
        ],
        ...,
    ]:
        records = tuple(
            item
            for item in self._closed_world(as_of=as_of)
            if item[1].receipt.receipt_id == receipt_id and item[1].receipt.recorded_at <= as_of
        )
        return _validate_chain(records)

    def _closed_world(
        self, *, as_of: datetime
    ) -> tuple[
        tuple[
            AccountOwnerAssignmentProvenanceReceiptV3Model,
            PersistedAccountOwnerAssignmentProvenanceReceiptV3,
        ],
        ...,
    ]:
        if type(as_of) is not datetime or as_of.tzinfo is None or as_of.utcoffset() is None:
            raise AccountOwnerAssignmentCorruption("selector cutoff is naive")
        rows = tuple(
            AccountOwnerAssignmentProvenanceReceiptV3Model._base_manager.using(
                self._using
            ).order_by("pk")
        )
        restored = tuple((row, _restore(row)) for row in rows)
        for row, record in restored:
            self._require_binding(
                row.binding, record.receipt.binding, as_of=record.receipt.recorded_at
            )
        for receipt_id in {record.receipt.receipt_id for _, record in restored}:
            _validate_chain(
                tuple(item for item in restored if item[1].receipt.receipt_id == receipt_id)
            )
        return restored

    def _require_binding(
        self,
        row: CanonicalAccountCreationBindingV2Model,
        expected: CanonicalAccountCreationBindingV2,
        *,
        as_of: datetime,
    ) -> None:
        persisted = self._consumption.get_winner(
            binding_id=expected.binding_id,
            binding_version=expected.binding_version,
            as_of=as_of,
        )
        if (
            persisted is None
            or persisted.binding != expected
            or row.binding_id != expected.binding_id
            or row.binding_version != expected.binding_version
            or row.content_hash != expected.content_hash
        ):
            raise AccountOwnerAssignmentCorruption("Binding-v2 FK/header/domain mismatch")


def _validate_chain(
    records: tuple[
        tuple[
            AccountOwnerAssignmentProvenanceReceiptV3Model,
            PersistedAccountOwnerAssignmentProvenanceReceiptV3,
        ],
        ...,
    ],
) -> tuple[
    tuple[
        AccountOwnerAssignmentProvenanceReceiptV3Model,
        PersistedAccountOwnerAssignmentProvenanceReceiptV3,
    ],
    ...,
]:
    if not records:
        return ()
    by_hash = {record.receipt.content_hash: (row, record) for row, record in records}
    roots = [item for item in records if item[1].receipt.supersedes_content_hash is None]
    if len(by_hash) != len(records) or len(roots) != 1:
        raise AccountOwnerAssignmentCorruption("receipt chain root/content count")
    successor: dict[
        str,
        tuple[
            AccountOwnerAssignmentProvenanceReceiptV3Model,
            PersistedAccountOwnerAssignmentProvenanceReceiptV3,
        ],
    ] = {}
    for row, record in records:
        predecessor_hash = record.receipt.supersedes_content_hash
        if predecessor_hash is None:
            if row.predecessor_id is not None:
                raise AccountOwnerAssignmentCorruption("root predecessor FK mismatch")
            continue
        previous = by_hash.get(predecessor_hash)
        if (
            previous is None
            or predecessor_hash in successor
            or row.predecessor_id != previous[0].pk
        ):
            raise AccountOwnerAssignmentCorruption("receipt chain is not closed")
        try:
            validate_account_owner_assignment_provenance_receipt_v3_successor(
                previous[1].receipt, record.receipt
            )
        except (TypeError, ValueError) as error:
            raise AccountOwnerAssignmentCorruption("receipt successor invalid") from error
        successor[predecessor_hash] = (row, record)
    ordered = [roots[0]]
    while ordered[-1][1].receipt.content_hash in successor:
        ordered.append(successor[ordered[-1][1].receipt.content_hash])
    if len(ordered) != len(records):
        raise AccountOwnerAssignmentCorruption("receipt chain disconnected")
    return tuple(ordered)


def _hash(value: object) -> str:
    return hashlib.sha256(
        json.dumps(
            value, allow_nan=False, ensure_ascii=False, separators=(",", ":"), sort_keys=True
        ).encode()
    ).hexdigest()


def _model_values(
    record: PersistedAccountOwnerAssignmentProvenanceReceiptV3,
    *,
    binding_pk: int,
    predecessor_pk: int | None,
) -> dict[str, object]:
    receipt = record.receipt
    payload = encode_account_owner_assignment_provenance_receipt_v3_record(record)
    values: dict[str, object] = {
        "predecessor_id": predecessor_pk,
        "owner": receipt.owner,
        "artifact_type": receipt.artifact_type,
        "schema": receipt.schema,
        "provenance_kind": receipt.provenance_kind,
        "assignment_state": receipt.assignment_state,
        "assigned_owner_user_id": receipt.assigned_owner_user_id,
        "receipt_id": receipt.receipt_id,
        "receipt_version": receipt.receipt_version,
        "binding_id": binding_pk,
        "binding_ref_id": receipt.binding.binding_id,
        "binding_ref_version": receipt.binding.binding_version,
        "binding_identity_hash": receipt.binding_identity_hash,
        "binding_content_hash": receipt.binding_content_hash,
        "binding_recorded_at": receipt.binding.recorded_at,
        "allocation_identity_hash": receipt.allocation_identity_hash,
        "creation_root_content_hash": receipt.creation_root_content_hash,
        "creation_root_identity_hash": receipt.creation_root_identity_hash,
        "creation_root_recorded_at": receipt.binding.creation_root.recorded_at,
        "creation_root_valid_until": receipt.binding.creation_root.valid_until,
        "allocation_content_hash": receipt.allocation_content_hash,
        "account_claim_hash": receipt.account_claim_hash,
        "underlying_claim_hash": receipt.underlying_claim_hash,
        "physical_observation_content_hash": receipt.physical_observation_content_hash,
        "physical_source_content_hash": receipt.physical_source_content_hash,
        "physical_raw_observation_content_hash": receipt.physical_raw_observation_content_hash,
        "physical_row_user_id": receipt.binding.creation_root.physical_observation.row_user_id,
        "claimant_user_id": receipt.claimant.user_id,
        "claimant_actor_id": receipt.claimant.actor_id,
        "claimant_role": receipt.claimant.role,
        "claimant_kind": receipt.claimant.kind,
        "claimant_is_staff": receipt.claimant.is_staff,
        "issuer_actor_id": record.issued_by.actor_id,
        "issuer_user_id": record.issued_by.user_id,
        "issuer_role": record.issued_by.role,
        "issuer_kind": record.issued_by.kind,
        "issuer_is_staff": record.issued_by.is_staff,
        "issued_at": receipt.issued_at,
        "recorded_at": receipt.recorded_at,
        "valid_until": receipt.valid_until,
        "supersedes_content_hash": receipt.supersedes_content_hash,
        "permission": receipt.permission,
        "status": receipt.status,
        "blocker_codes": list(receipt.blocker_codes),
        "canonical_payload": payload,
        "identity_hash": receipt.identity_hash,
        "content_hash": receipt.content_hash,
        "binding_seal": _hash(receipt.binding.to_payload()),
        "claimant_seal": _hash(receipt.claimant.to_payload()),
        "actor_binding_seal": _hash(record.issued_by.to_payload()),
        "chain_seal": _hash({"predecessor": receipt.supersedes_content_hash}),
        "fixed_authority_seal": _hash(
            {
                "owner": receipt.owner,
                "artifact_type": receipt.artifact_type,
                "schema": receipt.schema,
                "permission": receipt.permission,
                "status": receipt.status,
            }
        ),
        "header_seal": _hash(
            {"receipt_id": receipt.receipt_id, "receipt_version": receipt.receipt_version}
        ),
        "record_seal": _hash(payload),
        "ledger_seal": _hash(
            {"payload": payload, "binding_pk": binding_pk, "predecessor_pk": predecessor_pk}
        ),
        "root_claim_hash": (
            _hash(
                {
                    "owner": receipt.owner,
                    "artifact_type": receipt.artifact_type,
                    "schema": receipt.schema,
                    "receipt_id": receipt.receipt_id,
                }
            )
            if predecessor_pk is None
            else None
        ),
        "persisted_at": receipt.recorded_at,
    }
    return values


def _restore(
    model: AccountOwnerAssignmentProvenanceReceiptV3Model,
) -> PersistedAccountOwnerAssignmentProvenanceReceiptV3:
    try:
        record = decode_account_owner_assignment_provenance_receipt_v3_record(
            model.canonical_payload
        )
    except (TypeError, ValueError) as error:
        raise AccountOwnerAssignmentCorruption("receipt payload corrupt") from error
    expected = _model_values(
        record, binding_pk=model.binding_id, predecessor_pk=model.predecessor_id
    )
    for name, value in expected.items():
        if getattr(model, name) != value:
            raise AccountOwnerAssignmentCorruption(f"receipt ledger seal mismatch: {name}")
    return record


__all__ = [
    "AccountOwnerAssignmentProvenanceReceiptV3Clock",
    "DjangoAccountOwnerAssignmentProvenanceReceiptV3Clock",
    "DjangoAccountOwnerAssignmentProvenanceReceiptV3Repository",
]
