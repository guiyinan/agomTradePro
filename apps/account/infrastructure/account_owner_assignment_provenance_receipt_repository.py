"""Django append-only repository for Account assignment provenance receipts."""

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
from apps.account.application.account_owner_assignment_provenance_receipt import (
    AccountOwnerAssignmentProvenanceReceiptConflict,
    AccountOwnerAssignmentProvenanceReceiptCorruption,
    AccountOwnerAssignmentProvenanceReceiptUnavailable,
    PersistedAccountOwnerAssignmentProvenanceReceipt,
)
from apps.account.domain.account_owner_assignment_provenance_receipt import (
    AccountOwnerAssignmentProvenanceReceipt,
    validate_account_owner_assignment_provenance_receipt_successor,
)
from apps.account.infrastructure.account_owner_assignment_provenance_receipt_codec import (
    AccountOwnerAssignmentProvenanceReceiptCodecError,
    decode_account_owner_assignment_provenance_receipt_record,
    encode_account_owner_assignment_provenance_receipt_record,
)
from apps.account.infrastructure.account_owner_assignment_provenance_receipt_models import (
    _ACTIVE_PROVENANCE_UOW,
    AccountOwnerAssignmentProvenanceReceiptModel,
    _activate_account_owner_assignment_provenance_uow,
    _claim_account_owner_assignment_provenance_insert,
)


class AccountOwnerAssignmentProvenanceReceiptClock(Protocol):
    """Provide the authoritative Account persistence clock."""

    def now(self) -> datetime:
        """Return one timezone-aware server time."""


class DjangoAccountOwnerAssignmentProvenanceReceiptClock:
    """Django timezone-backed production clock."""

    def now(self) -> datetime:
        """Return current Django time."""

        return timezone.now()


class DjangoAccountOwnerAssignmentProvenanceReceiptRepository:
    """Private first-winner ledger with full-table closed-world restore."""

    __slots__ = ("_clock", "_using")

    def __init__(
        self,
        *,
        using: str = "default",
        clock: AccountOwnerAssignmentProvenanceReceiptClock | None = None,
    ) -> None:
        self._using = using
        self._clock = clock or DjangoAccountOwnerAssignmentProvenanceReceiptClock()

    @contextmanager
    def atomic(self) -> Iterator[None]:
        """Open this ledger's independent private append transaction."""

        token = object()
        with (
            transaction.atomic(using=self._using),
            _activate_account_owner_assignment_provenance_uow(token),
        ):
            yield

    def now(self) -> datetime:
        """Return the validated authoritative Account server clock."""

        value = self._clock.now()
        _require_aware(value, "account provenance clock")
        return value

    def append(
        self,
        record: PersistedAccountOwnerAssignmentProvenanceReceipt,
        *,
        expected_predecessor_hash: str | None,
        recorded_at: datetime,
    ) -> PersistedAccountOwnerAssignmentProvenanceReceipt:
        """CAS-append or return the exact immutable first winner."""

        token = _active_token()
        checked = _require_exact_record(record)
        receipt = checked.receipt
        _require_aware(recorded_at, "recorded_at")
        if receipt.recorded_at != recorded_at:
            raise AccountOwnerAssignmentProvenanceReceiptConflict(
                "persisted_at and receipt recorded_at must be identical"
            )
        if receipt.supersedes_content_hash != expected_predecessor_hash:
            raise AccountOwnerAssignmentProvenanceReceiptConflict(
                "provenance receipt does not bind the expected predecessor"
            )
        if not receipt.is_knowable_at(recorded_at):
            raise AccountOwnerAssignmentProvenanceReceiptConflict(
                "provenance receipt must be persisted inside its validity window"
            )
        existing = self._exact_model(checked)
        if existing is not None:
            return self._restore(existing)
        current = self._current_head(receipt_id=receipt.receipt_id, as_of=recorded_at, lock=True)
        actual_predecessor = current.receipt.content_hash if current is not None else None
        if actual_predecessor != expected_predecessor_hash:
            raise AccountOwnerAssignmentProvenanceReceiptConflict(
                "provenance receipt predecessor CAS conflict"
            )
        if current is not None:
            try:
                validate_account_owner_assignment_provenance_receipt_successor(
                    current.receipt, receipt
                )
            except (TypeError, ValueError) as error:
                raise AccountOwnerAssignmentProvenanceReceiptConflict(
                    "provenance receipt successor is invalid"
                ) from error
        values = _model_values(checked, recorded_at=recorded_at)
        model = AccountOwnerAssignmentProvenanceReceiptModel(**values)
        try:
            with transaction.atomic(using=self._using):
                with _claim_account_owner_assignment_provenance_insert(
                    token=token,
                    model_type=AccountOwnerAssignmentProvenanceReceiptModel,
                    expected_values=values,
                ):
                    model.save(force_insert=True, using=self._using)
        except IntegrityError:
            winner = self._exact_model(checked)
            if winner is None:
                raise AccountOwnerAssignmentProvenanceReceiptConflict(
                    "provenance append conflicted without an exact first winner"
                ) from None
            return self._restore(winner)
        return self._restore(model)

    def get_winner(
        self,
        *,
        receipt_id: str,
        receipt_version: str,
        as_of: datetime,
    ) -> PersistedAccountOwnerAssignmentProvenanceReceipt | None:
        """Return the identity first winner recorded by the PIT cutoff."""

        _require_token(receipt_id, "receipt_id")
        _require_token(receipt_version, "receipt_version")
        self._require_cutoff(as_of)
        matches = tuple(
            record
            for record in self._visible_records(as_of=as_of, lock=False)
            if record.receipt.receipt_id == receipt_id
            and record.receipt.receipt_version == receipt_version
        )
        if not matches:
            return None
        if len(matches) != 1:
            raise AccountOwnerAssignmentProvenanceReceiptCorruption(
                "provenance receipt first winner is ambiguous"
            )
        return matches[0]

    def get_exact_by_hash(
        self,
        *,
        receipt_id: str,
        receipt_version: str,
        expected_content_hash: str,
        as_of: datetime,
    ) -> PersistedAccountOwnerAssignmentProvenanceReceipt | None:
        """Return one exact inactive identity/hash/historical PIT record."""

        _require_token(receipt_id, "receipt_id")
        _require_token(receipt_version, "receipt_version")
        _require_hash(expected_content_hash, "expected_content_hash")
        self._require_cutoff(as_of)
        records = self._visible_records(as_of=as_of, lock=False)
        anchors = tuple(
            record
            for record in records
            if (
                (
                    record.receipt.receipt_id == receipt_id
                    and record.receipt.receipt_version == receipt_version
                )
                or record.receipt.content_hash == expected_content_hash
            )
        )
        if not anchors:
            return None
        matches = tuple(
            record
            for record in anchors
            if record.receipt.receipt_id == receipt_id
            and record.receipt.receipt_version == receipt_version
            and record.receipt.content_hash == expected_content_hash
        )
        if len(anchors) != 1 or len(matches) != 1:
            raise AccountOwnerAssignmentProvenanceReceiptCorruption(
                "provenance receipt exact anchors are ambiguous"
            )
        record = matches[0]
        return record if record.receipt.is_knowable_at(as_of) else None

    def get_current_head(
        self, *, receipt_id: str, as_of: datetime
    ) -> PersistedAccountOwnerAssignmentProvenanceReceipt | None:
        """Return the final PIT head even when it is inactive or expired."""

        _require_token(receipt_id, "receipt_id")
        self._require_cutoff(as_of)
        return self._current_head(receipt_id=receipt_id, as_of=as_of, lock=False)

    def _current_head(
        self, *, receipt_id: str, as_of: datetime, lock: bool
    ) -> PersistedAccountOwnerAssignmentProvenanceReceipt | None:
        chain = tuple(
            record
            for record in self._visible_records(as_of=as_of, lock=lock)
            if record.receipt.receipt_id == receipt_id
        )
        return _restore_full_chain(chain) if chain else None

    def _visible_records(
        self, *, as_of: datetime, lock: bool
    ) -> tuple[PersistedAccountOwnerAssignmentProvenanceReceipt, ...]:
        """Restore the full table before trusting selector or PIT headers."""

        queryset = AccountOwnerAssignmentProvenanceReceiptModel._default_manager.using(
            self._using
        ).all()
        if lock:
            queryset = queryset.select_for_update()
        rows = list(queryset.order_by("recorded_at", "pk"))
        restored = tuple(self._restore(row) for row in rows)
        return tuple(record for record in restored if record.receipt.recorded_at <= as_of)

    def _require_cutoff(self, as_of: datetime) -> None:
        _require_aware(as_of, "account provenance as_of")
        if as_of > self.now():
            raise AccountOwnerAssignmentProvenanceReceiptUnavailable(
                "future account provenance as_of is forbidden"
            )

    def _exact_model(
        self, record: PersistedAccountOwnerAssignmentProvenanceReceipt
    ) -> AccountOwnerAssignmentProvenanceReceiptModel | None:
        receipt = record.receipt
        rows = list(
            AccountOwnerAssignmentProvenanceReceiptModel._default_manager.using(self._using).all()
        )
        if not rows:
            return None
        restored = tuple((row, self._restore(row)) for row in rows)
        root_claim = _root_claim_hash(receipt)
        issuer_binding = _issuer_binding_hash(record)
        anchors = tuple(
            (row, value)
            for row, value in restored
            if (
                (
                    value.receipt.receipt_id == receipt.receipt_id
                    and value.receipt.receipt_version == receipt.receipt_version
                )
                or value.receipt.identity_hash == receipt.identity_hash
                or value.receipt.content_hash == receipt.content_hash
                or row.issuer_binding_hash == issuer_binding
                or (receipt.supersedes_content_hash is None and row.root_claim_hash == root_claim)
                or (
                    receipt.supersedes_content_hash is not None
                    and value.receipt.supersedes_content_hash == receipt.supersedes_content_hash
                )
            )
        )
        if not anchors:
            return None
        matches = tuple(row for row, value in anchors if value == record)
        if len(anchors) != 1 or len(matches) != 1:
            raise AccountOwnerAssignmentProvenanceReceiptConflict(
                "provenance uniqueness or chain claim has another first winner"
            )
        return matches[0]

    def _restore(
        self, model: AccountOwnerAssignmentProvenanceReceiptModel
    ) -> PersistedAccountOwnerAssignmentProvenanceReceipt:
        try:
            record = decode_account_owner_assignment_provenance_receipt_record(
                model.canonical_payload
            )
        except AccountOwnerAssignmentProvenanceReceiptCodecError as error:
            raise AccountOwnerAssignmentProvenanceReceiptCorruption(
                "account provenance canonical payload cannot be restored"
            ) from error
        expected = _model_values(record, recorded_at=record.receipt.recorded_at)
        for field_name, expected_value in expected.items():
            if getattr(model, field_name) != expected_value:
                raise AccountOwnerAssignmentProvenanceReceiptCorruption(
                    f"account provenance {field_name} seal is invalid"
                )
        if (
            model.persisted_at.tzinfo is None
            or model.persisted_at.utcoffset() is None
            or model.persisted_at != model.recorded_at
        ):
            raise AccountOwnerAssignmentProvenanceReceiptCorruption(
                "account provenance persistence clock is invalid"
            )
        return record


def _active_token() -> object:
    token = _ACTIVE_PROVENANCE_UOW.get()
    if token is None:
        raise AccountOwnerAssignmentProvenanceReceiptConflict(
            "provenance append requires an active private unit of work"
        )
    return token


def _require_exact_record(
    value: object,
) -> PersistedAccountOwnerAssignmentProvenanceReceipt:
    if type(value) is not PersistedAccountOwnerAssignmentProvenanceReceipt:
        raise AccountOwnerAssignmentProvenanceReceiptCorruption(
            "persisted provenance record type substitution"
        )
    PersistedAccountOwnerAssignmentProvenanceReceipt.__post_init__(value)
    return value


def _require_aware(value: object, field_name: str) -> None:
    if type(value) is not datetime or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware")


def _require_token(value: object, field_name: str) -> None:
    if (
        type(value) is not str
        or not value
        or value.strip() != value
        or len(value) > 192
        or any(character.isspace() for character in value)
    ):
        raise ValueError(f"{field_name} must be a bounded canonical token")


def _require_hash(value: object, field_name: str) -> None:
    if (
        type(value) is not str
        or len(value) != 64
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise ValueError(f"{field_name} must be a lowercase SHA-256 digest")


def _hash_payload(payload: dict[str, object]) -> str:
    return hashlib.sha256(
        json.dumps(
            payload,
            allow_nan=False,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    ).hexdigest()


def _time(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _root_claim_hash(receipt: AccountOwnerAssignmentProvenanceReceipt) -> str:
    return _hash_payload(
        {
            "kind": "account-owner-assignment-provenance-root.v1",
            "owner": receipt.owner,
            "receipt_id": receipt.receipt_id,
        }
    )


def _row_binding_hash(receipt: AccountOwnerAssignmentProvenanceReceipt) -> str:
    return _hash_payload(
        {
            "account_namespace": receipt.account_namespace,
            "account_id": receipt.account_id,
            "underlying_unified_account_namespace": (receipt.underlying_unified_account_namespace),
            "underlying_unified_account_id": receipt.underlying_unified_account_id,
            "row_observation_owner": receipt.row_observation_owner,
            "row_observation_artifact_type": receipt.row_observation_artifact_type,
            "row_observation_id": receipt.row_observation_id,
            "row_observation_version": receipt.row_observation_version,
            "row_observation_identity_hash": receipt.row_observation_identity_hash,
            "row_observation_content_hash": receipt.row_observation_content_hash,
            "row_observation_valid_until": _time(receipt.row_observation_valid_until),
        }
    )


def _actor_payload(actor: AccountOwnerAssignmentServerActor) -> dict[str, object]:
    return actor.to_payload()


def _issuer_binding_hash(
    record: PersistedAccountOwnerAssignmentProvenanceReceipt,
) -> str:
    return _hash_payload(
        {
            "receipt_content_hash": record.receipt.content_hash,
            "issued_by": _actor_payload(record.issued_by),
        }
    )


def _record_header_hash(
    record: PersistedAccountOwnerAssignmentProvenanceReceipt,
) -> str:
    return _hash_payload(
        {
            "receipt_identity_hash": record.receipt.identity_hash,
            "receipt_content_hash": record.receipt.content_hash,
            "issued_by": _actor_payload(record.issued_by),
        }
    )


def _ledger_header_hash(
    record: PersistedAccountOwnerAssignmentProvenanceReceipt,
    *,
    recorded_at: datetime,
) -> str:
    receipt = record.receipt
    return _hash_payload(
        {
            "kind": "account-owner-assignment-provenance-ledger.v1",
            "record_header_hash": _record_header_hash(record),
            "root_claim_hash": (
                _root_claim_hash(receipt) if receipt.supersedes_content_hash is None else None
            ),
            "supersedes_content_hash": receipt.supersedes_content_hash,
            "recorded_at": _time(recorded_at),
        }
    )


def _model_values(
    record: PersistedAccountOwnerAssignmentProvenanceReceipt,
    *,
    recorded_at: datetime,
) -> dict[str, object]:
    receipt = record.receipt
    actor = record.issued_by
    return {
        "owner": receipt.owner,
        "artifact_type": receipt.artifact_type,
        "schema": receipt.schema,
        "receipt_id": receipt.receipt_id,
        "receipt_version": receipt.receipt_version,
        "provenance_kind": receipt.provenance_kind,
        "assignment_state": receipt.assignment_state,
        "assigned_owner_user_id": receipt.assigned_owner_user_id,
        "account_namespace": receipt.account_namespace,
        "account_id": receipt.account_id,
        "underlying_unified_account_namespace": receipt.underlying_unified_account_namespace,
        "underlying_unified_account_id": receipt.underlying_unified_account_id,
        "row_observation_owner": receipt.row_observation_owner,
        "row_observation_artifact_type": receipt.row_observation_artifact_type,
        "row_observation_id": receipt.row_observation_id,
        "row_observation_version": receipt.row_observation_version,
        "row_observation_identity_hash": receipt.row_observation_identity_hash,
        "row_observation_content_hash": receipt.row_observation_content_hash,
        "row_observation_valid_until": receipt.row_observation_valid_until,
        "claimant_actor_id": receipt.claimant.actor_id,
        "claimant_user_id": receipt.claimant.user_id,
        "claimant_role": receipt.claimant.role,
        "claimant_kind": receipt.claimant.kind,
        "claimant_is_staff": receipt.claimant.is_staff,
        "issued_at": receipt.issued_at,
        "recorded_at": receipt.recorded_at,
        "valid_until": receipt.valid_until,
        "supersedes_content_hash": receipt.supersedes_content_hash,
        "root_claim_hash": (
            _root_claim_hash(receipt) if receipt.supersedes_content_hash is None else None
        ),
        "permission": receipt.permission,
        "status": receipt.status,
        "blocker_codes": list(receipt.blocker_codes),
        "issuer_actor_id": actor.actor_id,
        "issuer_user_id": actor.user_id,
        "issuer_role": actor.role,
        "issuer_kind": actor.kind,
        "issuer_is_staff": actor.is_staff,
        "canonical_payload": encode_account_owner_assignment_provenance_receipt_record(record),
        "identity_hash": receipt.identity_hash,
        "content_hash": receipt.content_hash,
        "row_binding_hash": _row_binding_hash(receipt),
        "issuer_binding_hash": _issuer_binding_hash(record),
        "record_header_hash": _record_header_hash(record),
        "ledger_header_hash": _ledger_header_hash(record, recorded_at=recorded_at),
        "persisted_at": recorded_at,
    }


def _restore_full_chain(
    records: tuple[PersistedAccountOwnerAssignmentProvenanceReceipt, ...],
) -> PersistedAccountOwnerAssignmentProvenanceReceipt:
    ordered = tuple(sorted(records, key=lambda value: value.receipt.recorded_at))
    roots = tuple(value for value in ordered if value.receipt.supersedes_content_hash is None)
    if len(roots) != 1 or ordered[0] != roots[0]:
        raise AccountOwnerAssignmentProvenanceReceiptCorruption(
            "provenance receipt chain must have one visible root"
        )
    for previous, successor in zip(ordered, ordered[1:], strict=False):
        try:
            validate_account_owner_assignment_provenance_receipt_successor(
                previous.receipt, successor.receipt
            )
        except (TypeError, ValueError) as error:
            raise AccountOwnerAssignmentProvenanceReceiptCorruption(
                "provenance receipt chain is discontinuous"
            ) from error
    return ordered[-1]


__all__ = [
    "DjangoAccountOwnerAssignmentProvenanceReceiptClock",
    "DjangoAccountOwnerAssignmentProvenanceReceiptRepository",
]
