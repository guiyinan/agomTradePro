"""Append-only persistence and exact PIT reads for Broker account identities."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from typing import Protocol, cast

from django.db import IntegrityError, transaction
from django.utils import timezone

from apps.broker_execution.application.broker_account_identity_snapshot import (
    BrokerAccountIdentityIssuanceActor,
    BrokerAccountIdentitySnapshotConflict,
    BrokerAccountIdentitySnapshotCorruption,
    BrokerAccountIdentitySnapshotUnavailable,
    PersistedBrokerAccountIdentitySnapshot,
)
from apps.broker_execution.domain.broker_account_identity_snapshot import (
    BrokerAccountIdentitySnapshot,
    validate_broker_account_identity_snapshot_successor,
)
from apps.broker_execution.infrastructure.broker_account_identity_snapshot_codec import (
    BrokerAccountIdentitySnapshotCodecError,
    decode_broker_account_identity_snapshot,
    encode_broker_account_identity_snapshot,
)
from apps.broker_execution.infrastructure.broker_account_identity_snapshot_models import (
    _ACTIVE_BROKER_ACCOUNT_IDENTITY_UOW,
    BrokerAccountIdentitySnapshotModel,
    _activate_broker_account_identity_uow,
    _claim_broker_account_identity_insert,
)


class BrokerAccountIdentitySnapshotClock(Protocol):
    """Authoritative Broker persistence clock."""

    def now(self) -> datetime:
        """Return one timezone-aware server timestamp."""


class DjangoBrokerAccountIdentitySnapshotClock:
    """Django timezone-backed production clock."""

    def now(self) -> datetime:
        """Return the current timezone-aware server timestamp."""

        return cast(datetime, timezone.now())


class DjangoBrokerAccountIdentitySnapshotRepository:
    """Private first-winner ledger with closed-world inactive PIT restore."""

    __slots__ = ("_clock", "_using")

    def __init__(
        self,
        *,
        using: str = "default",
        clock: BrokerAccountIdentitySnapshotClock | None = None,
    ) -> None:
        self._using = using
        self._clock = clock or DjangoBrokerAccountIdentitySnapshotClock()

    @contextmanager
    def atomic(self) -> Iterator[None]:
        """Open this ledger's independent private append transaction."""

        token = object()
        with (
            transaction.atomic(using=self._using),
            _activate_broker_account_identity_uow(token),
        ):
            yield

    def now(self) -> datetime:
        """Return the validated authoritative Broker clock."""

        value = self._clock.now()
        if value.tzinfo is None or value.utcoffset() is None:
            raise BrokerAccountIdentitySnapshotCorruption("Broker account identity clock is naive")
        return value

    def append(
        self,
        record: PersistedBrokerAccountIdentitySnapshot,
        *,
        expected_predecessor_hash: str | None,
        recorded_at: datetime,
    ) -> PersistedBrokerAccountIdentitySnapshot:
        """CAS-append or return the exact actor-bound first winner."""

        token = _active_token()
        checked = _require_record(record)
        snapshot = checked.snapshot
        _require_aware(recorded_at, "recorded_at")
        if recorded_at > self.now():
            raise BrokerAccountIdentitySnapshotUnavailable(
                "future Broker account identity persistence clock is forbidden"
            )
        if recorded_at != snapshot.recorded_at:
            raise BrokerAccountIdentitySnapshotConflict(
                "persisted_at and snapshot recorded_at must be identical"
            )
        if expected_predecessor_hash != snapshot.supersedes_snapshot_hash:
            raise BrokerAccountIdentitySnapshotConflict(
                "snapshot does not bind the expected predecessor"
            )
        if not snapshot.is_knowable_at(recorded_at):
            raise BrokerAccountIdentitySnapshotConflict(
                "snapshot must be persisted inside its validity window"
            )
        existing = self._exact_model(checked)
        if existing is not None:
            return self._restore(existing)
        current = self._current_head(
            broker_account_namespace=snapshot.broker_account_namespace,
            broker_account_id=snapshot.broker_account_id,
            as_of=recorded_at,
            lock=True,
        )
        actual_predecessor = current.snapshot.content_hash if current is not None else None
        if actual_predecessor != expected_predecessor_hash:
            raise BrokerAccountIdentitySnapshotConflict(
                "Broker account identity predecessor CAS conflict"
            )
        if current is not None:
            try:
                validate_broker_account_identity_snapshot_successor(current.snapshot, snapshot)
            except (TypeError, ValueError) as error:
                raise BrokerAccountIdentitySnapshotConflict(
                    "Broker account identity successor is invalid"
                ) from error
        values = _model_values(checked, recorded_at=recorded_at)
        model = BrokerAccountIdentitySnapshotModel(**values)
        try:
            with transaction.atomic(using=self._using):
                with _claim_broker_account_identity_insert(
                    token=token,
                    model_type=BrokerAccountIdentitySnapshotModel,
                    expected_values=values,
                ):
                    model.save(force_insert=True, using=self._using)
        except IntegrityError:
            winner = self._exact_model(checked)
            if winner is None:
                raise BrokerAccountIdentitySnapshotConflict(
                    "snapshot append conflicted without an exact visible first winner"
                ) from None
            return self._restore(winner)
        return self._restore(model)

    def get_identity_winner(
        self, *, snapshot_id: str, snapshot_version: str, as_of: datetime
    ) -> PersistedBrokerAccountIdentitySnapshot | None:
        """Return the immutable identity winner when knowable at the cutoff."""

        self._require_cutoff(as_of)
        records = self._visible_records(as_of=as_of, lock=False)
        matches = tuple(
            record
            for record in records
            if record.snapshot.snapshot_id == snapshot_id
            and record.snapshot.snapshot_version == snapshot_version
        )
        if not matches:
            return None
        if len(matches) != 1:
            raise BrokerAccountIdentitySnapshotCorruption(
                "snapshot identity first winner is ambiguous"
            )
        return matches[0] if matches[0].snapshot.is_knowable_at(as_of) else None

    def get_exact_by_hash(
        self,
        *,
        snapshot_id: str,
        snapshot_version: str,
        expected_content_hash: str,
        as_of: datetime,
    ) -> PersistedBrokerAccountIdentitySnapshot | None:
        """Return one exact actor-bound inactive identity/hash/PIT record."""

        self._require_cutoff(as_of)
        records = self._visible_records(as_of=as_of, lock=False)
        anchors = tuple(
            record
            for record in records
            if (
                (
                    record.snapshot.snapshot_id == snapshot_id
                    and record.snapshot.snapshot_version == snapshot_version
                )
                or record.snapshot.content_hash == expected_content_hash
            )
        )
        if not anchors:
            return None
        matches = tuple(
            record
            for record in anchors
            if record.snapshot.snapshot_id == snapshot_id
            and record.snapshot.snapshot_version == snapshot_version
            and record.snapshot.content_hash == expected_content_hash
        )
        if len(anchors) != 1 or len(matches) != 1:
            raise BrokerAccountIdentitySnapshotCorruption(
                "snapshot exact identity/content anchors are ambiguous"
            )
        return matches[0] if matches[0].snapshot.is_knowable_at(as_of) else None

    def get_current_head(
        self,
        *,
        broker_account_namespace: str,
        broker_account_id: int,
        as_of: datetime,
    ) -> PersistedBrokerAccountIdentitySnapshot | None:
        """Return the exact inactive PIT head without expired fallback."""

        self._require_cutoff(as_of)
        return self._current_head(
            broker_account_namespace=broker_account_namespace,
            broker_account_id=broker_account_id,
            as_of=as_of,
            lock=False,
        )

    def _current_head(
        self,
        *,
        broker_account_namespace: str,
        broker_account_id: int,
        as_of: datetime,
        lock: bool,
    ) -> PersistedBrokerAccountIdentitySnapshot | None:
        records = self._visible_records(as_of=as_of, lock=lock)
        chain = tuple(
            record
            for record in records
            if record.snapshot.broker_account_namespace == broker_account_namespace
            and record.snapshot.broker_account_id == broker_account_id
        )
        if not chain:
            return None
        head = _restore_full_chain(chain)
        return head if head.snapshot.is_knowable_at(as_of) else None

    def _visible_records(
        self, *, as_of: datetime, lock: bool
    ) -> tuple[PersistedBrokerAccountIdentitySnapshot, ...]:
        """Restore the closed world before trusting mutable selector headers."""

        queryset = BrokerAccountIdentitySnapshotModel._default_manager.using(self._using).all()
        if lock:
            queryset = queryset.select_for_update()
        rows = list(queryset.order_by("recorded_at", "pk"))
        records = tuple(self._restore(row) for row in rows)
        visible = tuple(record for record in records if record.snapshot.recorded_at <= as_of)
        _validate_closed_world(visible)
        return visible

    def _require_cutoff(self, as_of: datetime) -> None:
        _require_aware(as_of, "snapshot as_of")
        if as_of > self.now():
            raise BrokerAccountIdentitySnapshotUnavailable(
                "future Broker account identity as_of is forbidden"
            )

    def _exact_model(
        self, record: PersistedBrokerAccountIdentitySnapshot
    ) -> BrokerAccountIdentitySnapshotModel | None:
        snapshot = record.snapshot
        rows = list(BrokerAccountIdentitySnapshotModel._default_manager.using(self._using).all())
        if not rows:
            return None
        restored = tuple((row, self._restore(row)) for row in rows)
        _validate_closed_world(tuple(value for _, value in restored))
        root_claim = _root_claim_hash(snapshot)
        anchors = tuple(
            (row, value)
            for row, value in restored
            if (
                (
                    value.snapshot.snapshot_id == snapshot.snapshot_id
                    and value.snapshot.snapshot_version == snapshot.snapshot_version
                )
                or value.snapshot.content_hash == snapshot.content_hash
                or (snapshot.supersedes_snapshot_hash is None and row.root_claim_hash == root_claim)
                or (
                    snapshot.supersedes_snapshot_hash is not None
                    and value.snapshot.supersedes_snapshot_hash == snapshot.supersedes_snapshot_hash
                )
            )
        )
        if not anchors:
            return None
        matches = tuple(row for row, value in anchors if value == record)
        if len(anchors) != 1 or len(matches) != 1:
            raise BrokerAccountIdentitySnapshotConflict(
                "snapshot uniqueness or logical-chain claim has another first winner"
            )
        return cast(BrokerAccountIdentitySnapshotModel, matches[0])

    def _restore(
        self, model: BrokerAccountIdentitySnapshotModel
    ) -> PersistedBrokerAccountIdentitySnapshot:
        try:
            snapshot = decode_broker_account_identity_snapshot(model.canonical_payload)
            actor = BrokerAccountIdentityIssuanceActor(
                actor_id=model.actor_id,
                user_id=model.actor_user_id,
                kind=model.actor_kind,
                is_staff=model.actor_is_staff,
            )
            record = PersistedBrokerAccountIdentitySnapshot(snapshot, actor)
        except (BrokerAccountIdentitySnapshotCodecError, TypeError, ValueError) as error:
            raise BrokerAccountIdentitySnapshotCorruption(
                "snapshot canonical record cannot be restored"
            ) from error
        if _record_headers(record) != _model_headers(model):
            raise BrokerAccountIdentitySnapshotCorruption(
                "snapshot headers do not match canonical record"
            )
        if model.root_claim_hash != (
            _root_claim_hash(snapshot) if snapshot.supersedes_snapshot_hash is None else None
        ):
            raise BrokerAccountIdentitySnapshotCorruption(
                "snapshot root logical-chain claim is invalid"
            )
        if model.ledger_header_hash != _ledger_header_hash(record, recorded_at=model.recorded_at):
            raise BrokerAccountIdentitySnapshotCorruption("snapshot ledger header seal is invalid")
        if (
            model.persisted_at.tzinfo is None
            or model.persisted_at.utcoffset() is None
            or model.persisted_at != model.recorded_at
            or model.recorded_at != snapshot.recorded_at
        ):
            raise BrokerAccountIdentitySnapshotCorruption(
                "snapshot database persistence clock is invalid"
            )
        return record


def _active_token() -> object:
    token = _ACTIVE_BROKER_ACCOUNT_IDENTITY_UOW.get()
    if token is None:
        raise BrokerAccountIdentitySnapshotConflict(
            "snapshot append requires an active private unit of work"
        )
    return token


def _require_record(value: object) -> PersistedBrokerAccountIdentitySnapshot:
    if type(value) is not PersistedBrokerAccountIdentitySnapshot:
        raise BrokerAccountIdentitySnapshotCorruption("snapshot record type substitution")
    PersistedBrokerAccountIdentitySnapshot.__post_init__(value)
    return value


def _require_aware(value: datetime, field_name: str) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise BrokerAccountIdentitySnapshotUnavailable(f"{field_name} must be timezone-aware")


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


def _root_claim_hash(snapshot: BrokerAccountIdentitySnapshot) -> str:
    return _hash_payload(
        {
            "broker_account_namespace": snapshot.broker_account_namespace,
            "broker_account_id": snapshot.broker_account_id,
        }
    )


def _ledger_header_hash(
    record: PersistedBrokerAccountIdentitySnapshot, *, recorded_at: datetime
) -> str:
    snapshot = record.snapshot
    return _hash_payload(
        {
            "canonical_payload": encode_broker_account_identity_snapshot(snapshot),
            "actor": {
                "actor_id": record.issued_by.actor_id,
                "user_id": record.issued_by.user_id,
                "kind": record.issued_by.kind,
                "is_staff": record.issued_by.is_staff,
            },
            "root_claim_hash": (
                _root_claim_hash(snapshot) if snapshot.supersedes_snapshot_hash is None else None
            ),
            "persisted_at": _time(recorded_at),
        }
    )


def _model_values(
    record: PersistedBrokerAccountIdentitySnapshot, *, recorded_at: datetime
) -> dict[str, object]:
    snapshot = record.snapshot
    source = snapshot.account_source_ref
    digest = snapshot.qmt_account_ref_digest
    return {
        "owner": snapshot.owner,
        "artifact_type": snapshot.artifact_type,
        "schema": snapshot.schema,
        "authority_scope": snapshot.authority_scope,
        "permission": snapshot.permission,
        "snapshot_id": snapshot.snapshot_id,
        "snapshot_version": snapshot.snapshot_version,
        "identity_hash": snapshot.identity_hash,
        "content_hash": snapshot.content_hash,
        "broker_account_namespace": snapshot.broker_account_namespace,
        "broker_account_id": snapshot.broker_account_id,
        "owner_user_id": snapshot.owner_user_id,
        "account_source_owner": source.owner,
        "account_source_artifact_type": source.artifact_type,
        "account_source_id": source.source_id,
        "account_source_version": source.source_version,
        "account_source_content_hash": source.content_hash,
        "account_namespace": source.account_namespace,
        "account_id": source.account_id,
        "account_source_owner_user_id": source.owner_user_id,
        "account_type": source.account_type,
        "is_active": source.is_active,
        "account_source_recorded_at": source.recorded_at,
        "account_source_valid_until": source.valid_until,
        "binding_revision": snapshot.binding_revision,
        "binding_owner_user_id": snapshot.binding_owner_user_id,
        "binding_content_hash": snapshot.binding_content_hash,
        "agent_id": snapshot.agent_id,
        "agent_version": snapshot.agent_version,
        "agent_owner_user_id": snapshot.agent_owner_user_id,
        "agent_content_hash": snapshot.agent_content_hash,
        "qmt_digest_algorithm": digest.algorithm,
        "qmt_digest_key_id": digest.key_id,
        "qmt_digest": digest.digest,
        "broker_account_category": snapshot.broker_account_category,
        "issued_at": snapshot.issued_at,
        "recorded_at": recorded_at,
        "ttl_valid_until": snapshot.ttl_valid_until,
        "valid_until": snapshot.valid_until,
        "supersedes_snapshot_hash": snapshot.supersedes_snapshot_hash,
        "root_claim_hash": (
            _root_claim_hash(snapshot) if snapshot.supersedes_snapshot_hash is None else None
        ),
        "actor_id": record.issued_by.actor_id,
        "actor_user_id": record.issued_by.user_id,
        "actor_kind": record.issued_by.kind,
        "actor_is_staff": record.issued_by.is_staff,
        "canonical_payload": encode_broker_account_identity_snapshot(snapshot),
        "ledger_header_hash": _ledger_header_hash(record, recorded_at=recorded_at),
        "persisted_at": recorded_at,
    }


def _record_headers(record: PersistedBrokerAccountIdentitySnapshot) -> tuple[object, ...]:
    snapshot = record.snapshot
    source = snapshot.account_source_ref
    digest = snapshot.qmt_account_ref_digest
    return (
        snapshot.owner,
        snapshot.artifact_type,
        snapshot.schema,
        snapshot.authority_scope,
        snapshot.permission,
        snapshot.snapshot_id,
        snapshot.snapshot_version,
        snapshot.identity_hash,
        snapshot.content_hash,
        snapshot.broker_account_namespace,
        snapshot.broker_account_id,
        snapshot.owner_user_id,
        source.owner,
        source.artifact_type,
        source.source_id,
        source.source_version,
        source.content_hash,
        source.account_namespace,
        source.account_id,
        source.owner_user_id,
        source.account_type,
        source.is_active,
        source.recorded_at,
        source.valid_until,
        snapshot.binding_revision,
        snapshot.binding_owner_user_id,
        snapshot.binding_content_hash,
        snapshot.agent_id,
        snapshot.agent_version,
        snapshot.agent_owner_user_id,
        snapshot.agent_content_hash,
        digest.algorithm,
        digest.key_id,
        digest.digest,
        snapshot.broker_account_category,
        snapshot.issued_at,
        snapshot.recorded_at,
        snapshot.ttl_valid_until,
        snapshot.valid_until,
        snapshot.supersedes_snapshot_hash,
        record.issued_by.actor_id,
        record.issued_by.user_id,
        record.issued_by.kind,
        record.issued_by.is_staff,
    )


def _model_headers(model: BrokerAccountIdentitySnapshotModel) -> tuple[object, ...]:
    return (
        model.owner,
        model.artifact_type,
        model.schema,
        model.authority_scope,
        model.permission,
        model.snapshot_id,
        model.snapshot_version,
        model.identity_hash,
        model.content_hash,
        model.broker_account_namespace,
        model.broker_account_id,
        model.owner_user_id,
        model.account_source_owner,
        model.account_source_artifact_type,
        model.account_source_id,
        model.account_source_version,
        model.account_source_content_hash,
        model.account_namespace,
        model.account_id,
        model.account_source_owner_user_id,
        model.account_type,
        model.is_active,
        model.account_source_recorded_at,
        model.account_source_valid_until,
        model.binding_revision,
        model.binding_owner_user_id,
        model.binding_content_hash,
        model.agent_id,
        model.agent_version,
        model.agent_owner_user_id,
        model.agent_content_hash,
        model.qmt_digest_algorithm,
        model.qmt_digest_key_id,
        model.qmt_digest,
        model.broker_account_category,
        model.issued_at,
        model.recorded_at,
        model.ttl_valid_until,
        model.valid_until,
        model.supersedes_snapshot_hash,
        model.actor_id,
        model.actor_user_id,
        model.actor_kind,
        model.actor_is_staff,
    )


def _validate_closed_world(
    records: tuple[PersistedBrokerAccountIdentitySnapshot, ...],
) -> None:
    """Validate every visible chain before any selector may hide a bad link."""

    by_hash = {record.snapshot.content_hash: record for record in records}
    if len(by_hash) != len(records):
        raise BrokerAccountIdentitySnapshotCorruption("snapshot ledger has duplicate content")
    successors: dict[str, PersistedBrokerAccountIdentitySnapshot] = {}
    groups: dict[tuple[str, int], list[PersistedBrokerAccountIdentitySnapshot]] = {}
    for record in records:
        snapshot = record.snapshot
        groups.setdefault(
            (snapshot.broker_account_namespace, snapshot.broker_account_id), []
        ).append(record)
        predecessor_hash = snapshot.supersedes_snapshot_hash
        if predecessor_hash is None:
            continue
        predecessor = by_hash.get(predecessor_hash)
        if predecessor is None:
            raise BrokerAccountIdentitySnapshotCorruption(
                "snapshot chain predecessor is missing at cutoff"
            )
        if predecessor_hash in successors:
            raise BrokerAccountIdentitySnapshotCorruption(
                "snapshot chain predecessor has multiple successors"
            )
        try:
            validate_broker_account_identity_snapshot_successor(predecessor.snapshot, snapshot)
        except (TypeError, ValueError) as error:
            raise BrokerAccountIdentitySnapshotCorruption(
                "snapshot chain successor link is invalid"
            ) from error
        successors[predecessor_hash] = record
    for group in groups.values():
        _restore_full_chain(tuple(group))


def _restore_full_chain(
    records: tuple[PersistedBrokerAccountIdentitySnapshot, ...],
) -> PersistedBrokerAccountIdentitySnapshot:
    by_hash = {record.snapshot.content_hash: record for record in records}
    if len(by_hash) != len(records):
        raise BrokerAccountIdentitySnapshotCorruption("snapshot chain has duplicate content")
    roots = tuple(record for record in records if record.snapshot.supersedes_snapshot_hash is None)
    if len(roots) != 1:
        raise BrokerAccountIdentitySnapshotCorruption(
            "snapshot chain must have exactly one visible root"
        )
    successors: dict[str, PersistedBrokerAccountIdentitySnapshot] = {}
    for record in records:
        predecessor_hash = record.snapshot.supersedes_snapshot_hash
        if predecessor_hash is None:
            continue
        predecessor = by_hash.get(predecessor_hash)
        if predecessor is None:
            raise BrokerAccountIdentitySnapshotCorruption(
                "snapshot chain predecessor is missing at cutoff"
            )
        if predecessor_hash in successors:
            raise BrokerAccountIdentitySnapshotCorruption(
                "snapshot chain predecessor has multiple successors"
            )
        successors[predecessor_hash] = record
    visited: set[str] = set()
    current = roots[0]
    while current.snapshot.content_hash not in visited:
        visited.add(current.snapshot.content_hash)
        successor = successors.get(current.snapshot.content_hash)
        if successor is None:
            break
        current = successor
    if len(visited) != len(records):
        raise BrokerAccountIdentitySnapshotCorruption("snapshot chain is disconnected or cyclic")
    return current


__all__ = [
    "BrokerAccountIdentitySnapshotClock",
    "DjangoBrokerAccountIdentitySnapshotClock",
    "DjangoBrokerAccountIdentitySnapshotRepository",
]
