"""Django append-only repository for Account raw identity source evidence."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from typing import Protocol

from django.db import IntegrityError, transaction
from django.utils import timezone

from apps.account.application.account_identity_raw_source import (
    AccountIdentityRawSourceActor,
    AccountIdentityRawSourceConflict,
    AccountIdentityRawSourceCorruption,
    AccountIdentityRawSourceUnavailable,
    PersistedAccountIdentityRawSource,
)
from apps.account.domain.account_identity_raw_source import (
    AccountIdentityRawSource,
    validate_account_identity_raw_source_successor,
)
from apps.account.infrastructure.account_identity_raw_source_codec import (
    AccountIdentityRawSourceCodecError,
    decode_account_identity_raw_source_record,
    encode_account_identity_raw_source_record,
)
from apps.account.infrastructure.account_identity_raw_source_models import (
    _ACTIVE_RAW_SOURCE_UOW,
    AccountIdentityRawSourceModel,
    _activate_account_identity_raw_source_uow,
    _claim_account_identity_raw_source_insert,
)


class DjangoAccountIdentityRawSourceUnavailable(AccountIdentityRawSourceUnavailable):
    """Django raw-source evidence is unavailable at the requested cutoff."""


class DjangoAccountIdentityRawSourceConflict(AccountIdentityRawSourceConflict):
    """Django raw-source first-winner or CAS claim conflicted."""


class DjangoAccountIdentityRawSourceCorruption(AccountIdentityRawSourceCorruption):
    """Persisted raw-source evidence failed closed-world verification."""


class AccountIdentityRawSourceClock(Protocol):
    """Provide the Account server clock."""

    def now(self) -> datetime:
        """Return one timezone-aware server time."""


class DjangoAccountIdentityRawSourceClock:
    """Production Django clock."""

    def now(self) -> datetime:
        """Return current Django time."""

        return timezone.now()


class DjangoAccountIdentityRawSourceRepository:
    """Append-only closed-world raw-source ledger repository."""

    def __init__(
        self,
        *,
        using: str = "default",
        clock: AccountIdentityRawSourceClock | None = None,
    ) -> None:
        self._using = using
        self._clock = clock or DjangoAccountIdentityRawSourceClock()

    @contextmanager
    def atomic(self) -> Iterator[None]:
        """Open this ledger's private transactional unit of work."""

        token = object()
        with transaction.atomic(using=self._using):
            with _activate_account_identity_raw_source_uow(token):
                yield

    def now(self) -> datetime:
        """Return the authoritative Account clock."""

        value = self._clock.now()
        _require_aware(value, "raw source clock")
        return value

    def append(
        self,
        record: PersistedAccountIdentityRawSource,
        *,
        expected_predecessor_hash: str | None,
        recorded_at: datetime,
    ) -> PersistedAccountIdentityRawSource:
        """Append one exact record under identity and predecessor CAS claims."""

        checked = _require_exact_record(record)
        token = _active_token()
        _require_aware(recorded_at, "raw source recorded_at")
        source = checked.source
        if source.recorded_at != recorded_at:
            raise DjangoAccountIdentityRawSourceCorruption(
                "raw source recorded_at does not match the append clock"
            )
        current = self._current_head(
            account_namespace=source.account_namespace,
            account_id=source.account_id,
            as_of=recorded_at,
            lock=True,
        )
        current_hash = current.source.content_hash if current is not None else None
        if current_hash != expected_predecessor_hash:
            raise DjangoAccountIdentityRawSourceConflict(
                "account identity raw source predecessor CAS conflict"
            )
        if source.supersedes_content_hash != expected_predecessor_hash:
            raise DjangoAccountIdentityRawSourceConflict(
                "account identity raw source predecessor claim is invalid"
            )
        if current is not None:
            try:
                validate_account_identity_raw_source_successor(current.source, source)
            except (TypeError, ValueError) as error:
                raise DjangoAccountIdentityRawSourceConflict(
                    "account identity raw source successor is invalid"
                ) from error
        values = _model_values(checked, recorded_at=recorded_at)
        model = AccountIdentityRawSourceModel(**values)
        try:
            with transaction.atomic(using=self._using):
                with _claim_account_identity_raw_source_insert(
                    token=token,
                    model_type=AccountIdentityRawSourceModel,
                    expected_values=values,
                ):
                    model.save(force_insert=True, using=self._using)
        except IntegrityError:
            winner = self._exact_model(checked)
            if winner is None:
                raise DjangoAccountIdentityRawSourceConflict(
                    "raw-source append conflicted without an exact visible first winner"
                ) from None
            return self._restore(winner)
        return self._restore(model)

    def get_winner(
        self,
        *,
        source_id: str,
        source_version: str,
        as_of: datetime,
    ) -> PersistedAccountIdentityRawSource | None:
        """Return the exact first winner recorded by the PIT cutoff."""

        self._require_cutoff(as_of)
        records = self._visible_records(as_of=as_of, lock=False)
        matches = tuple(
            record
            for record in records
            if record.source.source_id == source_id
            and record.source.source_version == source_version
        )
        if not matches:
            return None
        if len(matches) != 1:
            raise DjangoAccountIdentityRawSourceCorruption(
                "account identity raw source first winner is ambiguous"
            )
        return matches[0]

    def get_exact_by_hash(
        self,
        *,
        source_id: str,
        source_version: str,
        expected_content_hash: str,
        as_of: datetime,
    ) -> PersistedAccountIdentityRawSource | None:
        """Return one exact inactive identity/hash/PIT record."""

        self._require_cutoff(as_of)
        records = self._visible_records(as_of=as_of, lock=False)
        anchors = tuple(
            record
            for record in records
            if (
                (
                    record.source.source_id == source_id
                    and record.source.source_version == source_version
                )
                or record.source.content_hash == expected_content_hash
            )
        )
        if not anchors:
            return None
        matches = tuple(
            record
            for record in anchors
            if record.source.source_id == source_id
            and record.source.source_version == source_version
            and record.source.content_hash == expected_content_hash
        )
        if len(anchors) != 1 or len(matches) != 1:
            raise DjangoAccountIdentityRawSourceCorruption(
                "account identity raw source exact anchors are ambiguous"
            )
        record = matches[0]
        return record if record.source.is_knowable_at(as_of) else None

    def get_current_head(
        self,
        *,
        account_namespace: str,
        account_id: str,
        as_of: datetime,
    ) -> PersistedAccountIdentityRawSource | None:
        """Return the full-chain PIT head, including inactive or expired final heads."""

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
    ) -> PersistedAccountIdentityRawSource | None:
        records = self._visible_records(as_of=as_of, lock=lock)
        chain = tuple(
            record
            for record in records
            if record.source.account_namespace == account_namespace
            and record.source.account_id == account_id
        )
        return _restore_full_chain(chain) if chain else None

    def _visible_records(
        self,
        *,
        as_of: datetime,
        lock: bool,
    ) -> tuple[PersistedAccountIdentityRawSource, ...]:
        """Restore the closed world before trusting mutable selector headers."""

        queryset = AccountIdentityRawSourceModel._default_manager.using(self._using).all()
        if lock:
            queryset = queryset.select_for_update()
        rows = list(queryset.order_by("recorded_at", "pk"))
        restored = tuple(self._restore(row) for row in rows)
        return tuple(record for record in restored if record.source.recorded_at <= as_of)

    def _require_cutoff(self, as_of: datetime) -> None:
        _require_aware(as_of, "raw source as_of")
        if as_of > self.now():
            raise DjangoAccountIdentityRawSourceUnavailable(
                "future account identity raw source as_of is forbidden"
            )

    def _exact_model(
        self,
        record: PersistedAccountIdentityRawSource,
    ) -> AccountIdentityRawSourceModel | None:
        source = record.source
        root_claim = _root_claim_hash(source)
        actor_binding = _actor_binding_hash(record)
        rows = list(AccountIdentityRawSourceModel._default_manager.using(self._using).all())
        if not rows:
            return None
        restored = tuple((row, self._restore(row)) for row in rows)
        anchors = tuple(
            (row, value)
            for row, value in restored
            if (
                (
                    value.source.source_id == source.source_id
                    and value.source.source_version == source.source_version
                )
                or value.source.identity_hash == source.identity_hash
                or value.source.content_hash == source.content_hash
                or row.actor_binding_hash == actor_binding
                or (source.supersedes_content_hash is None and row.root_claim_hash == root_claim)
                or (
                    source.supersedes_content_hash is not None
                    and value.source.supersedes_content_hash == source.supersedes_content_hash
                )
            )
        )
        if not anchors:
            return None
        matches = tuple(row for row, value in anchors if value == record)
        if len(anchors) != 1 or len(matches) != 1:
            raise DjangoAccountIdentityRawSourceConflict(
                "raw-source uniqueness or logical-chain claim has another first winner"
            )
        return matches[0]

    def _restore(
        self,
        model: AccountIdentityRawSourceModel,
    ) -> PersistedAccountIdentityRawSource:
        try:
            record = decode_account_identity_raw_source_record(model.canonical_payload)
        except AccountIdentityRawSourceCodecError as error:
            raise DjangoAccountIdentityRawSourceCorruption(
                "account identity raw source canonical payload cannot be restored"
            ) from error
        source = record.source
        if _record_headers(record) != _model_headers(model):
            raise DjangoAccountIdentityRawSourceCorruption(
                "account identity raw source headers do not match canonical payload"
            )
        if model.root_claim_hash != (
            _root_claim_hash(source) if source.supersedes_content_hash is None else None
        ):
            raise DjangoAccountIdentityRawSourceCorruption(
                "account identity raw source root claim is invalid"
            )
        if model.actor_binding_hash != _actor_binding_hash(record):
            raise DjangoAccountIdentityRawSourceCorruption(
                "account identity raw source actor binding seal is invalid"
            )
        if model.ledger_header_hash != _ledger_header_hash(record, recorded_at=model.recorded_at):
            raise DjangoAccountIdentityRawSourceCorruption(
                "account identity raw source ledger header seal is invalid"
            )
        if (
            model.persisted_at.tzinfo is None
            or model.persisted_at.utcoffset() is None
            or model.persisted_at != model.recorded_at
            or model.recorded_at != source.recorded_at
        ):
            raise DjangoAccountIdentityRawSourceCorruption(
                "account identity raw source persistence clock is invalid"
            )
        return record


def _active_token() -> object:
    token = _ACTIVE_RAW_SOURCE_UOW.get()
    if token is None:
        raise DjangoAccountIdentityRawSourceConflict(
            "raw-source append requires an active private unit of work"
        )
    return token


def _require_exact_record(value: object) -> PersistedAccountIdentityRawSource:
    if type(value) is not PersistedAccountIdentityRawSource:
        raise DjangoAccountIdentityRawSourceCorruption("raw-source record type substitution")
    PersistedAccountIdentityRawSource.__post_init__(value)
    return value


def _require_aware(value: datetime, field_name: str) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise DjangoAccountIdentityRawSourceUnavailable(f"{field_name} must be timezone-aware")


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


def _root_claim_hash(source: AccountIdentityRawSource) -> str:
    return _hash_payload(
        {"account_namespace": source.account_namespace, "account_id": source.account_id}
    )


def _actor_payload(actor: AccountIdentityRawSourceActor) -> dict[str, object]:
    return {
        "actor_id": actor.actor_id,
        "user_id": actor.user_id,
        "role": actor.role,
        "kind": actor.kind,
        "is_staff": actor.is_staff,
    }


def _actor_binding_hash(record: PersistedAccountIdentityRawSource) -> str:
    return _hash_payload(
        {
            "content_hash": record.source.content_hash,
            "captured_by": _actor_payload(record.captured_by),
        }
    )


def _ledger_header_hash(
    record: PersistedAccountIdentityRawSource,
    *,
    recorded_at: datetime,
) -> str:
    source = record.source
    return _hash_payload(
        {
            "record": encode_account_identity_raw_source_record(record),
            "root_claim_hash": (
                _root_claim_hash(source) if source.supersedes_content_hash is None else None
            ),
            "actor_binding_hash": _actor_binding_hash(record),
            "persisted_at": _time(recorded_at),
        }
    )


def _model_values(
    record: PersistedAccountIdentityRawSource,
    *,
    recorded_at: datetime,
) -> dict[str, object]:
    source = record.source
    actor = record.captured_by
    values: dict[str, object] = {
        name: getattr(source, name)
        for name in (
            "owner",
            "artifact_type",
            "schema",
            "source_id",
            "source_version",
            "account_namespace",
            "account_id",
            "underlying_unified_account_namespace",
            "underlying_unified_account_id",
            "owner_user_id",
            "assignment_state",
            "assignment_evidence_owner",
            "assignment_evidence_artifact_type",
            "assignment_evidence_id",
            "assignment_evidence_version",
            "assignment_evidence_content_hash",
            "row_source_owner",
            "row_source_artifact_type",
            "row_source_id",
            "row_source_version",
            "row_source_content_hash",
            "observed_at",
            "row_source_valid_until",
            "ttl_valid_until",
            "valid_until",
            "account_type",
            "is_active",
            "supersedes_content_hash",
            "permission",
            "status",
            "identity_hash",
            "content_hash",
        )
    }
    values.update(
        {
            "recorded_at": recorded_at,
            "root_claim_hash": (
                _root_claim_hash(source) if source.supersedes_content_hash is None else None
            ),
            "blocker_codes": list(source.blocker_codes),
            "captured_actor_id": actor.actor_id,
            "captured_actor_user_id": actor.user_id,
            "captured_actor_role": actor.role,
            "captured_actor_kind": actor.kind,
            "captured_actor_is_staff": actor.is_staff,
            "canonical_payload": encode_account_identity_raw_source_record(record),
            "actor_binding_hash": _actor_binding_hash(record),
            "ledger_header_hash": _ledger_header_hash(record, recorded_at=recorded_at),
            "persisted_at": recorded_at,
        }
    )
    return values


def _record_headers(record: PersistedAccountIdentityRawSource) -> tuple[object, ...]:
    source = record.source
    actor = record.captured_by
    return tuple(getattr(source, name) for name in _SOURCE_HEADER_NAMES) + (
        source.blocker_codes,
        actor.actor_id,
        actor.user_id,
        actor.role,
        actor.kind,
        actor.is_staff,
    )


def _model_headers(model: AccountIdentityRawSourceModel) -> tuple[object, ...]:
    return tuple(getattr(model, name) for name in _SOURCE_HEADER_NAMES) + (
        tuple(model.blocker_codes),
        model.captured_actor_id,
        model.captured_actor_user_id,
        model.captured_actor_role,
        model.captured_actor_kind,
        model.captured_actor_is_staff,
    )


_SOURCE_HEADER_NAMES = (
    "owner",
    "artifact_type",
    "schema",
    "source_id",
    "source_version",
    "account_namespace",
    "account_id",
    "underlying_unified_account_namespace",
    "underlying_unified_account_id",
    "owner_user_id",
    "assignment_state",
    "assignment_evidence_owner",
    "assignment_evidence_artifact_type",
    "assignment_evidence_id",
    "assignment_evidence_version",
    "assignment_evidence_content_hash",
    "row_source_owner",
    "row_source_artifact_type",
    "row_source_id",
    "row_source_version",
    "row_source_content_hash",
    "observed_at",
    "recorded_at",
    "row_source_valid_until",
    "ttl_valid_until",
    "valid_until",
    "account_type",
    "is_active",
    "supersedes_content_hash",
    "permission",
    "status",
    "identity_hash",
    "content_hash",
)


def _restore_full_chain(
    records: tuple[PersistedAccountIdentityRawSource, ...],
) -> PersistedAccountIdentityRawSource:
    by_hash = {record.source.content_hash: record for record in records}
    if len(by_hash) != len(records):
        raise DjangoAccountIdentityRawSourceCorruption("raw-source chain has duplicate content")
    roots = tuple(record for record in records if record.source.supersedes_content_hash is None)
    if len(roots) != 1:
        raise DjangoAccountIdentityRawSourceCorruption(
            "raw-source chain must have exactly one visible root"
        )
    successor_by_predecessor: dict[str, PersistedAccountIdentityRawSource] = {}
    for record in records:
        predecessor_hash = record.source.supersedes_content_hash
        if predecessor_hash is None:
            continue
        predecessor = by_hash.get(predecessor_hash)
        if predecessor is None:
            raise DjangoAccountIdentityRawSourceCorruption(
                "raw-source predecessor is missing at cutoff"
            )
        if predecessor_hash in successor_by_predecessor:
            raise DjangoAccountIdentityRawSourceCorruption(
                "raw-source predecessor has multiple successors"
            )
        try:
            validate_account_identity_raw_source_successor(predecessor.source, record.source)
        except (TypeError, ValueError) as error:
            raise DjangoAccountIdentityRawSourceCorruption(
                "raw-source successor link is invalid"
            ) from error
        successor_by_predecessor[predecessor_hash] = record
    visited: set[str] = set()
    current = roots[0]
    while current.source.content_hash not in visited:
        visited.add(current.source.content_hash)
        successor = successor_by_predecessor.get(current.source.content_hash)
        if successor is None:
            break
        current = successor
    if len(visited) != len(records):
        raise DjangoAccountIdentityRawSourceCorruption("raw-source chain is disconnected or cyclic")
    return current


__all__ = [
    "AccountIdentityRawSourceClock",
    "DjangoAccountIdentityRawSourceClock",
    "DjangoAccountIdentityRawSourceConflict",
    "DjangoAccountIdentityRawSourceCorruption",
    "DjangoAccountIdentityRawSourceRepository",
    "DjangoAccountIdentityRawSourceUnavailable",
]
