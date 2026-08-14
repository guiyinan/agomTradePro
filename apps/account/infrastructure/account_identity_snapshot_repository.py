"""Append-only persistence and exact PIT reads for Account identity snapshots."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from typing import Protocol, cast

from django.db import IntegrityError, transaction
from django.utils import timezone

from apps.account.application.account_identity_snapshot import (
    AccountIdentitySnapshotActor,
    AccountIdentitySnapshotConflict,
    AccountIdentitySnapshotCorruption,
    AccountIdentitySnapshotUnavailable,
    PersistedAccountIdentitySnapshot,
)
from apps.account.domain.account_identity_snapshot import (
    AccountIdentitySnapshot,
    validate_account_identity_snapshot_successor,
)
from apps.account.infrastructure.account_identity_snapshot_codec import (
    AccountIdentitySnapshotCodecError,
    decode_account_identity_snapshot_record,
    encode_account_identity_snapshot_record,
)
from apps.account.infrastructure.account_identity_snapshot_models import (
    _ACTIVE_ACCOUNT_IDENTITY_SNAPSHOT_UOW,
    AccountIdentitySnapshotModel,
    _activate_account_identity_snapshot_uow,
    _claim_account_identity_snapshot_insert,
)


class DjangoAccountIdentitySnapshotUnavailable(AccountIdentitySnapshotUnavailable):
    """An exact historical Account identity record is unavailable."""


class DjangoAccountIdentitySnapshotConflict(AccountIdentitySnapshotConflict):
    """An immutable identity or logical-chain claim has another winner."""


class DjangoAccountIdentitySnapshotCorruption(AccountIdentitySnapshotCorruption):
    """Persisted identity data or chain structure failed exact validation."""


class AccountIdentitySnapshotClock(Protocol):
    """Authoritative Account persistence clock."""

    def now(self) -> datetime:
        """Return one timezone-aware server timestamp."""


class DjangoAccountIdentitySnapshotClock:
    """Django timezone-backed production clock."""

    def now(self) -> datetime:
        """Return the current timezone-aware server timestamp."""

        return cast(datetime, timezone.now())


class DjangoAccountIdentitySnapshotRepository:
    """Private first-winner ledger with full-chain inactive PIT restore."""

    __slots__ = ("_clock", "_using")

    def __init__(
        self,
        *,
        using: str = "default",
        clock: AccountIdentitySnapshotClock | None = None,
    ) -> None:
        self._using = using
        self._clock = clock or DjangoAccountIdentitySnapshotClock()

    @contextmanager
    def atomic(self) -> Iterator[None]:
        """Open this ledger's independent private append transaction."""

        token = object()
        with (
            transaction.atomic(using=self._using),
            _activate_account_identity_snapshot_uow(token),
        ):
            yield

    def now(self) -> datetime:
        """Return the validated authoritative Account server clock."""

        value = self._clock.now()
        if value.tzinfo is None or value.utcoffset() is None:
            raise DjangoAccountIdentitySnapshotCorruption(
                "Account identity snapshot clock is naive"
            )
        return value

    def append(
        self,
        record: PersistedAccountIdentitySnapshot,
        *,
        expected_predecessor_hash: str | None,
        recorded_at: datetime,
    ) -> PersistedAccountIdentitySnapshot:
        """CAS-append or return the exact identity/logical-claim first winner."""

        token = _active_token()
        checked = _require_exact_record(record)
        snapshot = checked.snapshot
        _require_aware(recorded_at, "recorded_at")
        if recorded_at != snapshot.recorded_at:
            raise DjangoAccountIdentitySnapshotConflict(
                "persisted_at and snapshot recorded_at must be identical"
            )
        if expected_predecessor_hash != snapshot.supersedes_content_hash:
            raise DjangoAccountIdentitySnapshotConflict(
                "snapshot does not bind the expected predecessor"
            )
        if not snapshot.is_knowable_at(recorded_at):
            raise DjangoAccountIdentitySnapshotConflict(
                "snapshot must be persisted inside its validity window"
            )
        existing = self._exact_model(checked)
        if existing is not None:
            return self._restore(existing)
        current = self._current_head(
            account_namespace=snapshot.account_namespace,
            account_id=snapshot.account_id,
            as_of=recorded_at,
            lock=True,
        )
        actual_predecessor = current.snapshot.content_hash if current is not None else None
        if actual_predecessor != expected_predecessor_hash:
            raise DjangoAccountIdentitySnapshotConflict(
                "account identity snapshot predecessor CAS conflict"
            )
        if current is not None:
            try:
                validate_account_identity_snapshot_successor(
                    current.snapshot,
                    snapshot,
                )
            except (TypeError, ValueError) as error:
                raise DjangoAccountIdentitySnapshotConflict(
                    "account identity snapshot successor is invalid"
                ) from error
        values = _model_values(checked, recorded_at=recorded_at)
        model = AccountIdentitySnapshotModel(**values)
        try:
            with transaction.atomic(using=self._using):
                with _claim_account_identity_snapshot_insert(
                    token=token,
                    model_type=AccountIdentitySnapshotModel,
                    expected_values=values,
                ):
                    model.save(force_insert=True, using=self._using)
        except IntegrityError:
            winner = self._exact_model(checked)
            if winner is None:
                raise DjangoAccountIdentitySnapshotConflict(
                    "snapshot append conflicted without an exact visible first winner"
                ) from None
            return self._restore(winner)
        return self._restore(model)

    def get_winner(
        self,
        *,
        source_id: str,
        source_version: str,
        as_of: datetime,
    ) -> PersistedAccountIdentitySnapshot | None:
        """Return the identity first winner recorded by the exact PIT cutoff."""

        self._require_cutoff(as_of)
        records = self._visible_records(as_of=as_of, lock=False)
        matches = tuple(
            record
            for record in records
            if record.snapshot.source_id == source_id
            and record.snapshot.source_version == source_version
        )
        if not matches:
            return None
        if len(matches) != 1:
            raise DjangoAccountIdentitySnapshotCorruption(
                "account identity snapshot first winner is ambiguous"
            )
        return matches[0]

    def get_exact_by_hash(
        self,
        *,
        source_id: str,
        source_version: str,
        expected_content_hash: str,
        as_of: datetime,
    ) -> PersistedAccountIdentitySnapshot | None:
        """Return one exact inactive identity/hash/PIT record."""

        self._require_cutoff(as_of)
        records = self._visible_records(as_of=as_of, lock=False)
        anchors = tuple(
            record
            for record in records
            if (
                (
                    record.snapshot.source_id == source_id
                    and record.snapshot.source_version == source_version
                )
                or record.snapshot.content_hash == expected_content_hash
            )
        )
        if not anchors:
            return None
        matches = tuple(
            record
            for record in anchors
            if record.snapshot.source_id == source_id
            and record.snapshot.source_version == source_version
            and record.snapshot.content_hash == expected_content_hash
        )
        if len(anchors) != 1 or len(matches) != 1:
            raise DjangoAccountIdentitySnapshotCorruption(
                "account identity snapshot exact anchors are ambiguous"
            )
        record = matches[0]
        return record if record.snapshot.is_knowable_at(as_of) else None

    def get_current_head(
        self,
        *,
        account_namespace: str,
        account_id: str,
        as_of: datetime,
    ) -> PersistedAccountIdentitySnapshot | None:
        """Return the full-chain PIT head, including an expired final head."""

        self._require_cutoff(as_of)
        return self._current_head(
            account_namespace=account_namespace,
            account_id=account_id,
            as_of=as_of,
            lock=False,
        )

    def _current_head(
        self,
        *,
        account_namespace: str,
        account_id: str,
        as_of: datetime,
        lock: bool,
    ) -> PersistedAccountIdentitySnapshot | None:
        records = self._visible_records(as_of=as_of, lock=lock)
        chain = tuple(
            record
            for record in records
            if record.snapshot.account_namespace == account_namespace
            and record.snapshot.account_id == account_id
        )
        return _restore_full_chain(chain) if chain else None

    def _visible_records(
        self,
        *,
        as_of: datetime,
        lock: bool,
    ) -> tuple[PersistedAccountIdentitySnapshot, ...]:
        """Restore the closed world before trusting mutable selector headers."""

        queryset = AccountIdentitySnapshotModel._default_manager.using(self._using).all()
        if lock:
            queryset = queryset.select_for_update()
        rows = list(queryset.order_by("recorded_at", "pk"))
        restored = tuple(self._restore(row) for row in rows)
        return tuple(record for record in restored if record.snapshot.recorded_at <= as_of)

    def _require_cutoff(self, as_of: datetime) -> None:
        _require_aware(as_of, "snapshot as_of")
        if as_of > self.now():
            raise DjangoAccountIdentitySnapshotUnavailable(
                "future account identity snapshot as_of is forbidden"
            )

    def _exact_model(
        self,
        record: PersistedAccountIdentitySnapshot,
    ) -> AccountIdentitySnapshotModel | None:
        snapshot = record.snapshot
        root_claim = _root_claim_hash(snapshot)
        actor_binding = _actor_binding_hash(record)
        rows = list(AccountIdentitySnapshotModel._default_manager.using(self._using).all())
        if not rows:
            return None
        restored = tuple((row, self._restore(row)) for row in rows)
        anchors = tuple(
            (row, value)
            for row, value in restored
            if (
                (
                    value.snapshot.source_id == snapshot.source_id
                    and value.snapshot.source_version == snapshot.source_version
                )
                or value.snapshot.identity_hash == snapshot.identity_hash
                or value.snapshot.content_hash == snapshot.content_hash
                or row.actor_binding_hash == actor_binding
                or (snapshot.supersedes_content_hash is None and row.root_claim_hash == root_claim)
                or (
                    snapshot.supersedes_content_hash is not None
                    and value.snapshot.supersedes_content_hash == snapshot.supersedes_content_hash
                )
            )
        )
        if not anchors:
            return None
        matches = tuple(row for row, value in anchors if value == record)
        if len(anchors) != 1 or len(matches) != 1:
            raise DjangoAccountIdentitySnapshotConflict(
                "snapshot uniqueness or logical-chain claim has another first winner"
            )
        return cast(AccountIdentitySnapshotModel, matches[0])

    def _restore(
        self,
        model: AccountIdentitySnapshotModel,
    ) -> PersistedAccountIdentitySnapshot:
        try:
            record = decode_account_identity_snapshot_record(model.canonical_payload)
        except AccountIdentitySnapshotCodecError as error:
            raise DjangoAccountIdentitySnapshotCorruption(
                "account identity snapshot canonical payload cannot be restored"
            ) from error
        snapshot = record.snapshot
        if _record_headers(record) != _model_headers(model):
            raise DjangoAccountIdentitySnapshotCorruption(
                "account identity snapshot headers do not match canonical payload"
            )
        if model.root_claim_hash != (
            _root_claim_hash(snapshot) if snapshot.supersedes_content_hash is None else None
        ):
            raise DjangoAccountIdentitySnapshotCorruption(
                "account identity snapshot root claim is invalid"
            )
        if model.actor_binding_hash != _actor_binding_hash(record):
            raise DjangoAccountIdentitySnapshotCorruption(
                "account identity snapshot actor binding seal is invalid"
            )
        if model.ledger_header_hash != _ledger_header_hash(
            record,
            recorded_at=model.recorded_at,
        ):
            raise DjangoAccountIdentitySnapshotCorruption(
                "account identity snapshot ledger header seal is invalid"
            )
        if (
            model.persisted_at.tzinfo is None
            or model.persisted_at.utcoffset() is None
            or model.persisted_at != model.recorded_at
            or model.recorded_at != snapshot.recorded_at
        ):
            raise DjangoAccountIdentitySnapshotCorruption(
                "account identity snapshot persistence clock is invalid"
            )
        return record


def _active_token() -> object:
    token = _ACTIVE_ACCOUNT_IDENTITY_SNAPSHOT_UOW.get()
    if token is None:
        raise DjangoAccountIdentitySnapshotConflict(
            "snapshot append requires an active private unit of work"
        )
    return token


def _require_exact_record(value: object) -> PersistedAccountIdentitySnapshot:
    if type(value) is not PersistedAccountIdentitySnapshot:
        raise DjangoAccountIdentitySnapshotCorruption(
            "account identity snapshot record type substitution"
        )
    PersistedAccountIdentitySnapshot.__post_init__(value)
    return value


def _require_aware(value: datetime, field_name: str) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise DjangoAccountIdentitySnapshotUnavailable(f"{field_name} must be timezone-aware")


def _hash_payload(payload: dict[str, object]) -> str:
    return hashlib.sha256(
        json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()


def _time(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _root_claim_hash(snapshot: AccountIdentitySnapshot) -> str:
    return _hash_payload(
        {
            "account_namespace": snapshot.account_namespace,
            "account_id": snapshot.account_id,
        }
    )


def _actor_payload(actor: AccountIdentitySnapshotActor) -> dict[str, object]:
    return {
        "actor_id": actor.actor_id,
        "user_id": actor.user_id,
        "role": actor.role,
        "kind": actor.kind,
        "is_staff": actor.is_staff,
    }


def _actor_binding_hash(record: PersistedAccountIdentitySnapshot) -> str:
    return _hash_payload(
        {
            "content_hash": record.snapshot.content_hash,
            "issued_by": _actor_payload(record.issued_by),
        }
    )


def _ledger_header_hash(
    record: PersistedAccountIdentitySnapshot,
    *,
    recorded_at: datetime,
) -> str:
    snapshot = record.snapshot
    return _hash_payload(
        {
            "record": encode_account_identity_snapshot_record(record),
            "root_claim_hash": (
                _root_claim_hash(snapshot) if snapshot.supersedes_content_hash is None else None
            ),
            "actor_binding_hash": _actor_binding_hash(record),
            "persisted_at": _time(recorded_at),
        }
    )


def _model_values(
    record: PersistedAccountIdentitySnapshot,
    *,
    recorded_at: datetime,
) -> dict[str, object]:
    snapshot = record.snapshot
    actor = record.issued_by
    return {
        "owner": snapshot.owner,
        "artifact_type": snapshot.artifact_type,
        "schema": snapshot.schema,
        "source_id": snapshot.source_id,
        "source_version": snapshot.source_version,
        "account_namespace": snapshot.account_namespace,
        "account_id": snapshot.account_id,
        "underlying_unified_account_namespace": (snapshot.underlying_unified_account_namespace),
        "underlying_unified_account_id": snapshot.underlying_unified_account_id,
        "owner_user_id": snapshot.owner_user_id,
        "account_type": snapshot.account_type,
        "is_active": snapshot.is_active,
        "provenance_kind": snapshot.provenance_kind,
        "legacy_default_user_assignment": snapshot.legacy_default_user_assignment,
        "underlying_source_id": snapshot.underlying_source_id,
        "underlying_source_version": snapshot.underlying_source_version,
        "underlying_source_content_hash": snapshot.underlying_source_content_hash,
        "underlying_source_recorded_at": snapshot.underlying_source_recorded_at,
        "underlying_source_valid_until": snapshot.underlying_source_valid_until,
        "ttl_valid_until": snapshot.ttl_valid_until,
        "issued_at": snapshot.issued_at,
        "recorded_at": recorded_at,
        "valid_until": snapshot.valid_until,
        "reclaim_receipt_owner": snapshot.reclaim_receipt_owner,
        "reclaim_receipt_artifact_type": snapshot.reclaim_receipt_artifact_type,
        "reclaim_receipt_id": snapshot.reclaim_receipt_id,
        "reclaim_receipt_version": snapshot.reclaim_receipt_version,
        "reclaim_receipt_content_hash": snapshot.reclaim_receipt_content_hash,
        "supersedes_content_hash": snapshot.supersedes_content_hash,
        "root_claim_hash": (
            _root_claim_hash(snapshot) if snapshot.supersedes_content_hash is None else None
        ),
        "permission": snapshot.permission,
        "status": snapshot.status,
        "blocker_codes": list(snapshot.blocker_codes),
        "issued_actor_id": actor.actor_id,
        "issued_actor_user_id": actor.user_id,
        "issued_actor_role": actor.role,
        "issued_actor_kind": actor.kind,
        "issued_actor_is_staff": actor.is_staff,
        "canonical_payload": encode_account_identity_snapshot_record(record),
        "identity_hash": snapshot.identity_hash,
        "content_hash": snapshot.content_hash,
        "actor_binding_hash": _actor_binding_hash(record),
        "ledger_header_hash": _ledger_header_hash(record, recorded_at=recorded_at),
        "persisted_at": recorded_at,
    }


def _record_headers(record: PersistedAccountIdentitySnapshot) -> tuple[object, ...]:
    snapshot = record.snapshot
    actor = record.issued_by
    return (
        snapshot.owner,
        snapshot.artifact_type,
        snapshot.schema,
        snapshot.source_id,
        snapshot.source_version,
        snapshot.account_namespace,
        snapshot.account_id,
        snapshot.underlying_unified_account_namespace,
        snapshot.underlying_unified_account_id,
        snapshot.owner_user_id,
        snapshot.account_type,
        snapshot.is_active,
        snapshot.provenance_kind,
        snapshot.legacy_default_user_assignment,
        snapshot.underlying_source_id,
        snapshot.underlying_source_version,
        snapshot.underlying_source_content_hash,
        snapshot.underlying_source_recorded_at,
        snapshot.underlying_source_valid_until,
        snapshot.ttl_valid_until,
        snapshot.issued_at,
        snapshot.recorded_at,
        snapshot.valid_until,
        snapshot.reclaim_receipt_owner,
        snapshot.reclaim_receipt_artifact_type,
        snapshot.reclaim_receipt_id,
        snapshot.reclaim_receipt_version,
        snapshot.reclaim_receipt_content_hash,
        snapshot.supersedes_content_hash,
        snapshot.permission,
        snapshot.status,
        snapshot.blocker_codes,
        actor.actor_id,
        actor.user_id,
        actor.role,
        actor.kind,
        actor.is_staff,
        snapshot.identity_hash,
        snapshot.content_hash,
    )


def _model_headers(model: AccountIdentitySnapshotModel) -> tuple[object, ...]:
    return (
        model.owner,
        model.artifact_type,
        model.schema,
        model.source_id,
        model.source_version,
        model.account_namespace,
        model.account_id,
        model.underlying_unified_account_namespace,
        model.underlying_unified_account_id,
        model.owner_user_id,
        model.account_type,
        model.is_active,
        model.provenance_kind,
        model.legacy_default_user_assignment,
        model.underlying_source_id,
        model.underlying_source_version,
        model.underlying_source_content_hash,
        model.underlying_source_recorded_at,
        model.underlying_source_valid_until,
        model.ttl_valid_until,
        model.issued_at,
        model.recorded_at,
        model.valid_until,
        model.reclaim_receipt_owner,
        model.reclaim_receipt_artifact_type,
        model.reclaim_receipt_id,
        model.reclaim_receipt_version,
        model.reclaim_receipt_content_hash,
        model.supersedes_content_hash,
        model.permission,
        model.status,
        tuple(model.blocker_codes),
        model.issued_actor_id,
        model.issued_actor_user_id,
        model.issued_actor_role,
        model.issued_actor_kind,
        model.issued_actor_is_staff,
        model.identity_hash,
        model.content_hash,
    )


def _restore_full_chain(
    records: tuple[PersistedAccountIdentitySnapshot, ...],
) -> PersistedAccountIdentitySnapshot:
    by_hash = {record.snapshot.content_hash: record for record in records}
    if len(by_hash) != len(records):
        raise DjangoAccountIdentitySnapshotCorruption(
            "account identity snapshot chain has duplicate content"
        )
    roots = tuple(record for record in records if record.snapshot.supersedes_content_hash is None)
    if len(roots) != 1:
        raise DjangoAccountIdentitySnapshotCorruption(
            "account identity snapshot chain must have exactly one visible root"
        )
    successor_by_predecessor: dict[str, PersistedAccountIdentitySnapshot] = {}
    for record in records:
        predecessor_hash = record.snapshot.supersedes_content_hash
        if predecessor_hash is None:
            continue
        predecessor = by_hash.get(predecessor_hash)
        if predecessor is None:
            raise DjangoAccountIdentitySnapshotCorruption(
                "account identity snapshot predecessor is missing at cutoff"
            )
        if predecessor_hash in successor_by_predecessor:
            raise DjangoAccountIdentitySnapshotCorruption(
                "account identity snapshot predecessor has multiple successors"
            )
        try:
            validate_account_identity_snapshot_successor(
                predecessor.snapshot,
                record.snapshot,
            )
        except (TypeError, ValueError) as error:
            raise DjangoAccountIdentitySnapshotCorruption(
                "account identity snapshot successor link is invalid"
            ) from error
        successor_by_predecessor[predecessor_hash] = record
    visited: set[str] = set()
    current = roots[0]
    while current.snapshot.content_hash not in visited:
        visited.add(current.snapshot.content_hash)
        successor = successor_by_predecessor.get(current.snapshot.content_hash)
        if successor is None:
            break
        current = successor
    if len(visited) != len(records):
        raise DjangoAccountIdentitySnapshotCorruption(
            "account identity snapshot chain is disconnected or cyclic"
        )
    return current


__all__ = [
    "AccountIdentitySnapshotClock",
    "DjangoAccountIdentitySnapshotClock",
    "DjangoAccountIdentitySnapshotConflict",
    "DjangoAccountIdentitySnapshotCorruption",
    "DjangoAccountIdentitySnapshotRepository",
    "DjangoAccountIdentitySnapshotUnavailable",
]
