"""Django append-only repository for Account claimant provenance receipts v2."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from typing import Protocol

from django.db import IntegrityError, transaction
from django.utils import timezone

from apps.account.application.account_owner_assignment_evidence import (
    AccountOwnerAssignmentServerActor,
)
from apps.account.application.account_owner_assignment_provenance_receipt_v2 import (
    AccountOwnerAssignmentProvenanceReceiptV2Conflict,
    AccountOwnerAssignmentProvenanceReceiptV2Corruption,
    PersistedAccountOwnerAssignmentProvenanceReceiptV2,
)
from apps.account.domain.account_owner_assignment_evidence import (
    AccountOwnerAssignmentActor,
)
from apps.account.domain.account_owner_assignment_provenance_receipt_v2 import (
    AccountOwnerAssignmentProvenanceReceiptV2,
    validate_account_owner_assignment_provenance_receipt_v2_root,
    validate_account_owner_assignment_provenance_receipt_v2_successor,
)
from apps.account.infrastructure.account_owner_assignment_provenance_receipt_v2_codec import (
    decode_account_owner_assignment_provenance_receipt_v2_record,
    encode_account_owner_assignment_provenance_receipt_v2_record,
)
from apps.account.infrastructure.account_owner_assignment_provenance_receipt_v2_models import (
    AccountOwnerAssignmentProvenanceReceiptV2Model,
    _activate_account_owner_assignment_provenance_receipt_v2_uow,
    _claim_account_owner_assignment_provenance_receipt_v2_insert,
)


class AccountOwnerAssignmentProvenanceReceiptV2Clock(Protocol):
    def now(self) -> datetime: ...


class DjangoAccountOwnerAssignmentProvenanceReceiptV2Clock:
    def now(self) -> datetime:
        return timezone.now()


class DjangoAccountOwnerAssignmentProvenanceReceiptV2Repository:
    """Restore the closed world before selecting and CAS-appending."""

    def __init__(
        self,
        *,
        clock: AccountOwnerAssignmentProvenanceReceiptV2Clock | None = None,
        using: str = "default",
    ) -> None:
        self._clock = clock or DjangoAccountOwnerAssignmentProvenanceReceiptV2Clock()
        self._using = using
        self._uow: object | None = None

    @contextmanager
    def atomic(self) -> Iterator[None]:
        if self._uow is not None:
            raise AccountOwnerAssignmentProvenanceReceiptV2Conflict("nested provenance v2 UOW")
        token = object()
        self._uow = token
        try:
            with (
                transaction.atomic(using=self._using),
                _activate_account_owner_assignment_provenance_receipt_v2_uow(token),
            ):
                yield
        finally:
            self._uow = None

    def now(self) -> datetime:
        value = self._clock.now()
        if type(value) is not datetime or value.tzinfo is None or value.utcoffset() is None:
            raise AccountOwnerAssignmentProvenanceReceiptV2Corruption("repository clock is naive")
        return value

    def get_winner(
        self, *, receipt_id: str, receipt_version: str, as_of: datetime
    ) -> PersistedAccountOwnerAssignmentProvenanceReceiptV2 | None:
        records = self._closed_chain(receipt_id, as_of=as_of)
        return next((r for r in records if r.receipt.receipt_version == receipt_version), None)

    def get_current_head(
        self, *, receipt_id: str, as_of: datetime
    ) -> PersistedAccountOwnerAssignmentProvenanceReceiptV2 | None:
        records = self._closed_chain(receipt_id, as_of=as_of)
        return records[-1] if records else None

    def get_exact_by_hash(
        self, *, receipt_id: str, receipt_version: str, expected_content_hash: str, as_of: datetime
    ) -> PersistedAccountOwnerAssignmentProvenanceReceiptV2 | None:
        record = self.get_winner(
            receipt_id=receipt_id, receipt_version=receipt_version, as_of=as_of
        )
        if (
            record is None
            or record.receipt.content_hash != expected_content_hash
            or not record.receipt.is_current_at(as_of)
        ):
            return None
        return record

    def append(
        self,
        record: PersistedAccountOwnerAssignmentProvenanceReceiptV2,
        *,
        expected_predecessor_hash: str | None,
        recorded_at: datetime,
    ) -> PersistedAccountOwnerAssignmentProvenanceReceiptV2:
        PersistedAccountOwnerAssignmentProvenanceReceiptV2.__post_init__(record)
        receipt = record.receipt
        if self._uow is None:
            raise AccountOwnerAssignmentProvenanceReceiptV2Conflict("append requires private UOW")
        if recorded_at != receipt.recorded_at:
            raise AccountOwnerAssignmentProvenanceReceiptV2Corruption(
                "persisted_at must equal receipt recorded_at"
            )
        existing = self.get_winner(
            receipt_id=receipt.receipt_id,
            receipt_version=receipt.receipt_version,
            as_of=recorded_at,
        )
        if existing is not None:
            if existing != record:
                raise AccountOwnerAssignmentProvenanceReceiptV2Conflict(
                    "receipt identity first winner differs"
                )
            return existing
        head = self.get_current_head(receipt_id=receipt.receipt_id, as_of=recorded_at)
        actual = head.receipt.content_hash if head is not None else None
        if (
            actual != expected_predecessor_hash
            or receipt.supersedes_content_hash != expected_predecessor_hash
        ):
            raise AccountOwnerAssignmentProvenanceReceiptV2Conflict(
                "receipt predecessor CAS failed"
            )
        try:
            if head is None:
                validate_account_owner_assignment_provenance_receipt_v2_root(receipt)
            else:
                validate_account_owner_assignment_provenance_receipt_v2_successor(
                    head.receipt, receipt
                )
        except (TypeError, ValueError) as error:
            raise AccountOwnerAssignmentProvenanceReceiptV2Corruption(
                "invalid receipt chain append"
            ) from error
        values = _model_values(record)
        try:
            with _claim_account_owner_assignment_provenance_receipt_v2_insert(
                token=self._uow,
                model_type=AccountOwnerAssignmentProvenanceReceiptV2Model,
                expected_values=values,
            ):
                AccountOwnerAssignmentProvenanceReceiptV2Model._default_manager.using(
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
            raise AccountOwnerAssignmentProvenanceReceiptV2Conflict(
                "concurrent receipt first winner or successor"
            ) from error
        restored = self.get_winner(
            receipt_id=receipt.receipt_id,
            receipt_version=receipt.receipt_version,
            as_of=recorded_at,
        )
        if restored != record:
            raise AccountOwnerAssignmentProvenanceReceiptV2Corruption("receipt restore mismatch")
        return restored

    def _closed_chain(
        self, receipt_id: str, *, as_of: datetime
    ) -> tuple[PersistedAccountOwnerAssignmentProvenanceReceiptV2, ...]:
        # Restore every stored row before applying canonical selectors.  Filtering on
        # mutable duplicate headers would let a corrupted successor disappear and
        # incorrectly resurrect an older head.
        stored = tuple(
            AccountOwnerAssignmentProvenanceReceiptV2Model._base_manager.using(
                self._using
            ).order_by("pk")
        )
        restored = tuple(_restore(model) for model in stored)
        records = tuple(
            record
            for record in restored
            if record.receipt.receipt_id == receipt_id and record.receipt.recorded_at <= as_of
        )
        if not records:
            return ()
        by_hash = {r.receipt.content_hash: r for r in records}
        if len(by_hash) != len(records):
            raise AccountOwnerAssignmentProvenanceReceiptV2Corruption("duplicate receipt content")
        roots = [r for r in records if r.receipt.supersedes_content_hash is None]
        if len(roots) != 1:
            raise AccountOwnerAssignmentProvenanceReceiptV2Corruption("receipt chain root count")
        successor: dict[str, PersistedAccountOwnerAssignmentProvenanceReceiptV2] = {}
        for record in records:
            predecessor_hash = record.receipt.supersedes_content_hash
            if predecessor_hash is None:
                continue
            previous = by_hash.get(predecessor_hash)
            if previous is None or predecessor_hash in successor:
                raise AccountOwnerAssignmentProvenanceReceiptV2Corruption(
                    "receipt chain is not closed"
                )
            try:
                validate_account_owner_assignment_provenance_receipt_v2_successor(
                    previous.receipt, record.receipt
                )
            except (TypeError, ValueError) as error:
                raise AccountOwnerAssignmentProvenanceReceiptV2Corruption(
                    "receipt successor invalid"
                ) from error
            successor[predecessor_hash] = record
        ordered: list[PersistedAccountOwnerAssignmentProvenanceReceiptV2] = []
        current = roots[0]
        while current.receipt.content_hash not in {r.receipt.content_hash for r in ordered}:
            ordered.append(current)
            next_record = successor.get(current.receipt.content_hash)
            if next_record is None:
                break
            current = next_record
        if len(ordered) != len(records):
            raise AccountOwnerAssignmentProvenanceReceiptV2Corruption("receipt chain disconnected")
        return tuple(ordered)


def _json_hash(value: object) -> str:
    return hashlib.sha256(
        json.dumps(
            value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
        ).encode()
    ).hexdigest()


def _time(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _actor(
    actor: AccountOwnerAssignmentActor | AccountOwnerAssignmentServerActor,
) -> dict[str, object]:
    return {
        "actor_id": actor.actor_id,
        "user_id": actor.user_id,
        "role": actor.role,
        "kind": actor.kind,
        "is_staff": actor.is_staff,
    }


def _row_binding(receipt: AccountOwnerAssignmentProvenanceReceiptV2) -> str:
    names = (
        "account_namespace",
        "account_id",
        "underlying_unified_account_namespace",
        "underlying_unified_account_id",
        "row_observation_owner",
        "row_observation_artifact_type",
        "row_observation_schema",
        "row_observation_id",
        "row_observation_version",
        "row_observation_identity_hash",
        "row_observation_content_hash",
        "row_observation_supersedes_content_hash",
        "row_observation_recorded_at",
        "row_observation_valid_until",
        "source_content_hash",
        "raw_observation_content_hash",
        "row_is_active",
        "row_is_present",
        "row_is_tombstone",
        "row_user_id",
    )
    return _json_hash(
        {
            n: (
                _time(getattr(receipt, n))
                if type(getattr(receipt, n)) is datetime
                else getattr(receipt, n)
            )
            for n in names
        }
    )


def _fixed_authority(receipt: AccountOwnerAssignmentProvenanceReceiptV2) -> str:
    return _json_hash(
        {
            "owner": receipt.owner,
            "artifact_type": receipt.artifact_type,
            "schema": receipt.schema,
            "permission": receipt.permission,
            "status": receipt.status,
            "blocker_codes": list(receipt.blocker_codes),
        }
    )


def _header(receipt: AccountOwnerAssignmentProvenanceReceiptV2) -> str:
    return _json_hash(
        {
            "identity_hash": receipt.identity_hash,
            "content_hash": receipt.content_hash,
            "receipt_id": receipt.receipt_id,
            "receipt_version": receipt.receipt_version,
            "recorded_at": _time(receipt.recorded_at),
            "supersedes_content_hash": receipt.supersedes_content_hash,
        }
    )


def _root(receipt: AccountOwnerAssignmentProvenanceReceiptV2) -> str:
    # A root claim is a deterministic lock for the logical chain, not a digest of
    # the candidate root.  Thus two competing roots collide at the database edge.
    return _json_hash(
        {
            "domain": "account-owner-assignment-provenance-receipt-v2-root",
            "owner": receipt.owner,
            "artifact_type": receipt.artifact_type,
            "schema": receipt.schema,
            "receipt_id": receipt.receipt_id,
        }
    )


def _model_values(record: PersistedAccountOwnerAssignmentProvenanceReceiptV2) -> dict[str, object]:
    r, issuer = record.receipt, record.issued_by
    payload = encode_account_owner_assignment_provenance_receipt_v2_record(record)
    values: dict[str, object] = {name: getattr(r, name) for name in _HEADER_NAMES}
    values.update(
        {
            "claimant_actor_id": r.claimant.actor_id,
            "claimant_user_id": r.claimant.user_id,
            "claimant_role": r.claimant.role,
            "claimant_kind": r.claimant.kind,
            "claimant_is_staff": r.claimant.is_staff,
            "issuer_actor_id": issuer.actor_id,
            "issuer_user_id": issuer.user_id,
            "issuer_role": issuer.role,
            "issuer_kind": issuer.kind,
            "issuer_is_staff": issuer.is_staff,
            "blocker_codes": list(r.blocker_codes),
            "canonical_payload": payload,
            "root_claim_hash": _root(r) if r.supersedes_content_hash is None else None,
            "row_binding_seal": _row_binding(r),
            "actor_binding_seal": _json_hash(
                {
                    "content_hash": r.content_hash,
                    "claimant": _actor(r.claimant),
                    "issued_by": _actor(issuer),
                }
            ),
            "fixed_authority_seal": _fixed_authority(r),
            "header_seal": _header(r),
            "record_seal": _json_hash({"record": payload}),
            "persisted_at": r.recorded_at,
        }
    )
    values["ledger_seal"] = _json_hash(
        {
            "record_seal": values["record_seal"],
            "row_binding_seal": values["row_binding_seal"],
            "actor_binding_seal": values["actor_binding_seal"],
            "fixed_authority_seal": values["fixed_authority_seal"],
            "header_seal": values["header_seal"],
            "root_claim_hash": values["root_claim_hash"],
            "persisted_at": _time(r.recorded_at),
        }
    )
    return values


_HEADER_NAMES = (
    "owner",
    "artifact_type",
    "schema",
    "receipt_id",
    "receipt_version",
    "provenance_kind",
    "assignment_state",
    "assigned_owner_user_id",
    "account_namespace",
    "account_id",
    "underlying_unified_account_namespace",
    "underlying_unified_account_id",
    "row_observation_owner",
    "row_observation_artifact_type",
    "row_observation_schema",
    "row_observation_id",
    "row_observation_version",
    "row_observation_identity_hash",
    "row_observation_content_hash",
    "row_observation_supersedes_content_hash",
    "row_observation_recorded_at",
    "row_observation_valid_until",
    "source_content_hash",
    "raw_observation_content_hash",
    "row_is_active",
    "row_is_present",
    "row_is_tombstone",
    "row_user_id",
    "issued_at",
    "recorded_at",
    "valid_until",
    "supersedes_content_hash",
    "permission",
    "status",
    "identity_hash",
    "content_hash",
)


def _restore(
    model: AccountOwnerAssignmentProvenanceReceiptV2Model,
) -> PersistedAccountOwnerAssignmentProvenanceReceiptV2:
    try:
        record = decode_account_owner_assignment_provenance_receipt_v2_record(
            model.canonical_payload
        )
    except (TypeError, ValueError) as error:
        raise AccountOwnerAssignmentProvenanceReceiptV2Corruption(
            "receipt payload corrupt"
        ) from error
    expected = _model_values(record)
    for name, value in expected.items():
        if getattr(model, name) != value:
            raise AccountOwnerAssignmentProvenanceReceiptV2Corruption(
                f"receipt ledger seal mismatch: {name}"
            )
    return record


__all__ = [
    "AccountOwnerAssignmentProvenanceReceiptV2Clock",
    "DjangoAccountOwnerAssignmentProvenanceReceiptV2Clock",
    "DjangoAccountOwnerAssignmentProvenanceReceiptV2Repository",
]
