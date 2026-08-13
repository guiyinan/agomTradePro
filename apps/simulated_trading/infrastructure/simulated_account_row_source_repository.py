"""Django append-only repository for simulated account-row sources."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from typing import Protocol

from django.db import IntegrityError, transaction
from django.utils import timezone

from apps.simulated_trading.application.simulated_account_row_source import (
    PersistedSimulatedAccountRowSource,
    SimulatedAccountRowSourceActor,
    SimulatedAccountRowSourceConflict,
    SimulatedAccountRowSourceCorruption,
    SimulatedAccountRowSourceUnavailable,
)
from apps.simulated_trading.domain.simulated_account_row_source import (
    SimulatedAccountRowSource,
    validate_simulated_account_row_source_successor,
)
from apps.simulated_trading.infrastructure.simulated_account_row_source_codec import (
    SimulatedAccountRowSourceCodecError,
    decode_simulated_account_row_source_record,
    encode_simulated_account_row_source_record,
)
from apps.simulated_trading.infrastructure.simulated_account_row_source_models import (
    _ACTIVE_SIMULATED_ACCOUNT_ROW_SOURCE_UOW,
    SimulatedAccountRowSourceModel,
    _activate_simulated_account_row_source_uow,
    _claim_simulated_account_row_source_insert,
)


class DjangoSimulatedAccountRowSourceUnavailable(SimulatedAccountRowSourceUnavailable):
    """Source evidence is unavailable at the requested cutoff."""


class DjangoSimulatedAccountRowSourceConflict(SimulatedAccountRowSourceConflict):
    """A source first-winner or predecessor claim conflicted."""


class DjangoSimulatedAccountRowSourceCorruption(SimulatedAccountRowSourceCorruption):
    """Persisted source evidence failed closed-world verification."""


class SimulatedAccountRowSourceClock(Protocol):
    """Provide the authoritative SimulatedTrading persistence clock."""

    def now(self) -> datetime: ...


class DjangoSimulatedAccountRowSourceClock:
    """Django timezone-backed production clock."""

    def now(self) -> datetime:
        """Return current Django time."""

        return timezone.now()


class DjangoSimulatedAccountRowSourceRepository:
    """Private first-winner ledger with full-table closed-world restore."""

    __slots__ = ("_clock", "_using")

    def __init__(
        self,
        *,
        using: str = "default",
        clock: SimulatedAccountRowSourceClock | None = None,
    ) -> None:
        self._using = using
        self._clock = clock or DjangoSimulatedAccountRowSourceClock()

    @contextmanager
    def atomic(self) -> Iterator[None]:
        """Open this ledger's independent private append transaction."""

        token = object()
        with (
            transaction.atomic(using=self._using),
            _activate_simulated_account_row_source_uow(token),
        ):
            yield

    def now(self) -> datetime:
        """Return the validated authoritative server clock."""

        value = self._clock.now()
        _require_aware(value, "simulated account-row source clock")
        return value

    def append(
        self,
        record: PersistedSimulatedAccountRowSource,
        *,
        expected_predecessor_hash: str | None,
        recorded_at: datetime,
    ) -> PersistedSimulatedAccountRowSource:
        """CAS-append or return the exact immutable first winner."""

        token = _active_token()
        checked = _require_exact_record(record)
        source = checked.source
        _require_aware(recorded_at, "recorded_at")
        if source.recorded_at != recorded_at:
            raise DjangoSimulatedAccountRowSourceConflict(
                "persisted_at and source recorded_at must be identical"
            )
        if source.supersedes_content_hash != expected_predecessor_hash:
            raise DjangoSimulatedAccountRowSourceConflict(
                "simulated account-row source does not bind the expected predecessor"
            )
        if not source.is_knowable_at(recorded_at):
            raise DjangoSimulatedAccountRowSourceConflict(
                "simulated account-row source must be persisted inside its validity window"
            )
        existing = self._exact_model(checked)
        if existing is not None:
            return self._restore(existing)
        current = self._current_head(source, as_of=recorded_at, lock=True)
        actual_predecessor = current.source.content_hash if current is not None else None
        if actual_predecessor != expected_predecessor_hash:
            raise DjangoSimulatedAccountRowSourceConflict(
                "simulated account-row source predecessor CAS conflict"
            )
        if current is not None:
            try:
                validate_simulated_account_row_source_successor(
                    current.source,
                    source,
                )
            except (TypeError, ValueError) as error:
                raise DjangoSimulatedAccountRowSourceConflict(
                    "simulated account-row source successor is invalid"
                ) from error
        values = _model_values(checked, recorded_at=recorded_at)
        model = SimulatedAccountRowSourceModel(**values)
        try:
            with transaction.atomic(using=self._using):
                with _claim_simulated_account_row_source_insert(
                    token=token,
                    model_type=SimulatedAccountRowSourceModel,
                    expected_values=values,
                ):
                    model.save(force_insert=True, using=self._using)
        except IntegrityError:
            winner = self._exact_model(checked)
            if winner is None:
                raise DjangoSimulatedAccountRowSourceConflict(
                    "source append conflicted without an exact visible first winner"
                ) from None
            return self._restore(winner)
        return self._restore(model)

    def get_winner(
        self,
        *,
        source_id: str,
        source_version: str,
        as_of: datetime,
    ) -> PersistedSimulatedAccountRowSource | None:
        """Return the exact first winner recorded by the PIT cutoff."""

        _require_token(source_id, "source_id")
        _require_token(source_version, "source_version")
        self._require_cutoff(as_of)
        matches = tuple(
            record
            for record in self._visible_records(as_of=as_of, lock=False)
            if record.source.source_id == source_id
            and record.source.source_version == source_version
        )
        if not matches:
            return None
        if len(matches) != 1:
            raise DjangoSimulatedAccountRowSourceCorruption(
                "simulated account-row source first winner is ambiguous"
            )
        return matches[0]

    def get_exact_by_hash(
        self,
        *,
        source_id: str,
        source_version: str,
        expected_content_hash: str,
        as_of: datetime,
    ) -> PersistedSimulatedAccountRowSource | None:
        """Return one exact inactive identity/hash/historical PIT record."""

        _require_token(source_id, "source_id")
        _require_token(source_version, "source_version")
        _require_hash(expected_content_hash, "expected_content_hash")
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
            raise DjangoSimulatedAccountRowSourceCorruption(
                "simulated account-row source exact anchors are ambiguous"
            )
        record = matches[0]
        return record if record.source.is_knowable_at(as_of) else None

    def get_current_head(
        self,
        *,
        source_id: str,
        account_namespace: str,
        account_id: str,
        underlying_unified_account_namespace: str,
        underlying_unified_account_id: int,
        as_of: datetime,
    ) -> PersistedSimulatedAccountRowSource | None:
        """Return the final PIT head, even when inactive, tombstoned, or expired."""

        _require_token(source_id, "source_id")
        _require_token(account_namespace, "account_namespace")
        _require_token(account_id, "account_id")
        _require_token(
            underlying_unified_account_namespace,
            "underlying_unified_account_namespace",
        )
        _require_positive_integer(
            underlying_unified_account_id,
            "underlying_unified_account_id",
        )
        self._require_cutoff(as_of)
        selector = SimulatedAccountRowSource(
            source_id=source_id,
            source_version="selector",
            account_namespace=account_namespace,
            account_id=account_id,
            underlying_unified_account_namespace=underlying_unified_account_namespace,
            underlying_unified_account_id=underlying_unified_account_id,
            row_user_id=None,
            raw_account_type="selector",
            is_active=True,
            row_created_at=as_of,
            row_updated_at=as_of,
            is_present=True,
            is_tombstone=False,
            observed_at=as_of,
            recorded_at=as_of,
            source_valid_until=datetime.max.replace(tzinfo=UTC),
            ttl_valid_until=datetime.max.replace(tzinfo=UTC),
            valid_until=datetime.max.replace(tzinfo=UTC),
        )
        return self._current_head(selector, as_of=as_of, lock=False)

    def _current_head(
        self,
        selector: SimulatedAccountRowSource,
        *,
        as_of: datetime,
        lock: bool,
    ) -> PersistedSimulatedAccountRowSource | None:
        records = self._visible_records(as_of=as_of, lock=lock)
        chain = tuple(
            record for record in records if _logical_key(record.source) == _logical_key(selector)
        )
        return _restore_full_chain(chain) if chain else None

    def _visible_records(
        self,
        *,
        as_of: datetime,
        lock: bool,
    ) -> tuple[PersistedSimulatedAccountRowSource, ...]:
        """Restore the full table before trusting any selector header."""

        queryset = SimulatedAccountRowSourceModel._default_manager.using(self._using).all()
        if lock:
            queryset = queryset.select_for_update()
        rows = list(queryset.order_by("recorded_at", "pk"))
        restored = tuple(self._restore(row) for row in rows)
        return tuple(record for record in restored if record.source.recorded_at <= as_of)

    def _require_cutoff(self, as_of: datetime) -> None:
        _require_aware(as_of, "simulated account-row source as_of")
        if as_of > self.now():
            raise DjangoSimulatedAccountRowSourceUnavailable(
                "future simulated account-row source as_of is forbidden"
            )

    def _exact_model(
        self,
        record: PersistedSimulatedAccountRowSource,
    ) -> SimulatedAccountRowSourceModel | None:
        source = record.source
        root_claim = _root_claim_hash(source)
        actor_binding = _actor_binding_hash(record)
        rows = list(SimulatedAccountRowSourceModel._default_manager.using(self._using).all())
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
            raise DjangoSimulatedAccountRowSourceConflict(
                "source uniqueness or logical-chain claim has another first winner"
            )
        return matches[0]

    def _restore(
        self,
        model: SimulatedAccountRowSourceModel,
    ) -> PersistedSimulatedAccountRowSource:
        try:
            record = decode_simulated_account_row_source_record(model.canonical_payload)
        except SimulatedAccountRowSourceCodecError as error:
            raise DjangoSimulatedAccountRowSourceCorruption(
                "simulated account-row source payload cannot be restored"
            ) from error
        source = record.source
        if _record_headers(record) != _model_headers(model):
            raise DjangoSimulatedAccountRowSourceCorruption(
                "simulated account-row source headers do not match payload"
            )
        expected_root = _root_claim_hash(source) if source.supersedes_content_hash is None else None
        checks = (
            (model.root_claim_hash, expected_root, "root claim"),
            (model.row_fact_hash, _row_fact_hash(source), "row fact seal"),
            (model.logical_binding_hash, _logical_binding_hash(source), "logical binding seal"),
            (model.actor_binding_hash, _actor_binding_hash(record), "actor binding seal"),
            (model.record_header_hash, _record_header_hash(record), "record header seal"),
            (
                model.ledger_header_hash,
                _ledger_header_hash(record, recorded_at=model.recorded_at),
                "ledger header seal",
            ),
        )
        for actual, expected, label in checks:
            if actual != expected:
                raise DjangoSimulatedAccountRowSourceCorruption(
                    f"simulated account-row source {label} is invalid"
                )
        if (
            model.persisted_at.tzinfo is None
            or model.persisted_at.utcoffset() is None
            or model.persisted_at != model.recorded_at
            or model.recorded_at != source.recorded_at
        ):
            raise DjangoSimulatedAccountRowSourceCorruption(
                "simulated account-row source persistence clock is invalid"
            )
        return record


def _active_token() -> object:
    token = _ACTIVE_SIMULATED_ACCOUNT_ROW_SOURCE_UOW.get()
    if token is None:
        raise DjangoSimulatedAccountRowSourceConflict(
            "source append requires an active private unit of work"
        )
    return token


def _require_exact_record(value: object) -> PersistedSimulatedAccountRowSource:
    if type(value) is not PersistedSimulatedAccountRowSource:
        raise DjangoSimulatedAccountRowSourceCorruption("source record type substitution")
    PersistedSimulatedAccountRowSource.__post_init__(value)
    return value


def _require_aware(value: object, field_name: str) -> None:
    if type(value) is not datetime or value.tzinfo is None or value.utcoffset() is None:
        raise DjangoSimulatedAccountRowSourceUnavailable(f"{field_name} must be timezone-aware")


def _require_token(value: object, field_name: str) -> None:
    if (
        type(value) is not str
        or not value
        or value.strip() != value
        or len(value) > 192
        or any(character.isspace() for character in value)
    ):
        raise DjangoSimulatedAccountRowSourceUnavailable(
            f"{field_name} must be a bounded canonical token"
        )


def _require_hash(value: object, field_name: str) -> None:
    if (
        type(value) is not str
        or len(value) != 64
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise DjangoSimulatedAccountRowSourceUnavailable(
            f"{field_name} must be a lowercase SHA-256 digest"
        )


def _require_positive_integer(value: object, field_name: str) -> None:
    if type(value) is not int or value <= 0:
        raise DjangoSimulatedAccountRowSourceUnavailable(
            f"{field_name} must be an exact positive integer"
        )


def _hash_payload(payload: dict[str, object]) -> str:
    return hashlib.sha256(
        json.dumps(
            payload,
            allow_nan=False,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()


def _time(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _logical_key(source: SimulatedAccountRowSource) -> tuple[object, ...]:
    return (
        source.source_id,
        source.account_namespace,
        source.account_id,
        source.underlying_unified_account_namespace,
        source.underlying_unified_account_id,
    )


def _root_claim_hash(source: SimulatedAccountRowSource) -> str:
    return _hash_payload({"logical_key": list(_logical_key(source))})


def _row_fact_hash(source: SimulatedAccountRowSource) -> str:
    return _hash_payload(
        {
            "logical_key": list(_logical_key(source)),
            "row_user_id": source.row_user_id,
            "raw_account_type": source.raw_account_type,
            "is_active": source.is_active,
            "row_created_at": _time(source.row_created_at),
            "row_updated_at": _time(source.row_updated_at),
            "is_present": source.is_present,
            "is_tombstone": source.is_tombstone,
            "observed_at": _time(source.observed_at),
        }
    )


def _logical_binding_hash(source: SimulatedAccountRowSource) -> str:
    return _hash_payload(
        {
            "logical_key": list(_logical_key(source)),
            "source_version": source.source_version,
            "row_fact_hash": _row_fact_hash(source),
        }
    )


def _actor_payload(actor: SimulatedAccountRowSourceActor) -> dict[str, object]:
    return {
        "actor_id": actor.actor_id,
        "user_id": actor.user_id,
        "role": actor.role,
        "kind": actor.kind,
        "is_staff": actor.is_staff,
    }


def _actor_binding_hash(record: PersistedSimulatedAccountRowSource) -> str:
    return _hash_payload(
        {
            "content_hash": record.source.content_hash,
            "captured_by": _actor_payload(record.captured_by),
        }
    )


def _record_header_hash(record: PersistedSimulatedAccountRowSource) -> str:
    return _hash_payload({"record": encode_simulated_account_row_source_record(record)})


def _ledger_header_hash(
    record: PersistedSimulatedAccountRowSource,
    *,
    recorded_at: datetime,
) -> str:
    source = record.source
    return _hash_payload(
        {
            "record_header_hash": _record_header_hash(record),
            "root_claim_hash": (
                _root_claim_hash(source) if source.supersedes_content_hash is None else None
            ),
            "row_fact_hash": _row_fact_hash(source),
            "logical_binding_hash": _logical_binding_hash(source),
            "actor_binding_hash": _actor_binding_hash(record),
            "persisted_at": _time(recorded_at),
        }
    )


def _model_values(
    record: PersistedSimulatedAccountRowSource,
    *,
    recorded_at: datetime,
) -> dict[str, object]:
    source = record.source
    actor = record.captured_by
    values: dict[str, object] = {
        name: getattr(source, name) for name in _SOURCE_HEADER_NAMES if name != "recorded_at"
    }
    values.update(
        {
            "recorded_at": recorded_at,
            "root_claim_hash": (
                _root_claim_hash(source) if source.supersedes_content_hash is None else None
            ),
            "captured_actor_id": actor.actor_id,
            "captured_actor_user_id": actor.user_id,
            "captured_actor_role": actor.role,
            "captured_actor_kind": actor.kind,
            "captured_actor_is_staff": actor.is_staff,
            "canonical_payload": encode_simulated_account_row_source_record(record),
            "row_fact_hash": _row_fact_hash(source),
            "logical_binding_hash": _logical_binding_hash(source),
            "actor_binding_hash": _actor_binding_hash(record),
            "record_header_hash": _record_header_hash(record),
            "ledger_header_hash": _ledger_header_hash(
                record,
                recorded_at=recorded_at,
            ),
            "persisted_at": recorded_at,
        }
    )
    return values


def _record_headers(record: PersistedSimulatedAccountRowSource) -> tuple[object, ...]:
    source = record.source
    actor = record.captured_by
    return tuple(getattr(source, name) for name in _SOURCE_HEADER_NAMES) + (
        actor.actor_id,
        actor.user_id,
        actor.role,
        actor.kind,
        actor.is_staff,
    )


def _model_headers(model: SimulatedAccountRowSourceModel) -> tuple[object, ...]:
    return tuple(getattr(model, name) for name in _SOURCE_HEADER_NAMES) + (
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
    "row_user_id",
    "raw_account_type",
    "is_active",
    "row_created_at",
    "row_updated_at",
    "is_present",
    "is_tombstone",
    "observed_at",
    "recorded_at",
    "source_valid_until",
    "ttl_valid_until",
    "valid_until",
    "owner_assignment_state",
    "supersedes_content_hash",
    "permission",
    "status",
    "identity_hash",
    "content_hash",
)


def _restore_full_chain(
    records: tuple[PersistedSimulatedAccountRowSource, ...],
) -> PersistedSimulatedAccountRowSource:
    by_hash = {record.source.content_hash: record for record in records}
    if len(by_hash) != len(records):
        raise DjangoSimulatedAccountRowSourceCorruption("source chain has duplicate content")
    roots = tuple(record for record in records if record.source.supersedes_content_hash is None)
    if len(roots) != 1:
        raise DjangoSimulatedAccountRowSourceCorruption(
            "source chain must have exactly one visible root"
        )
    successor_by_predecessor: dict[str, PersistedSimulatedAccountRowSource] = {}
    for record in records:
        predecessor_hash = record.source.supersedes_content_hash
        if predecessor_hash is None:
            continue
        predecessor = by_hash.get(predecessor_hash)
        if predecessor is None:
            raise DjangoSimulatedAccountRowSourceCorruption(
                "source predecessor is missing at cutoff"
            )
        if predecessor_hash in successor_by_predecessor:
            raise DjangoSimulatedAccountRowSourceCorruption(
                "source predecessor has multiple successors"
            )
        try:
            validate_simulated_account_row_source_successor(
                predecessor.source,
                record.source,
            )
        except (TypeError, ValueError) as error:
            raise DjangoSimulatedAccountRowSourceCorruption(
                "source successor link is invalid"
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
        raise DjangoSimulatedAccountRowSourceCorruption("source chain is disconnected or cyclic")
    return current


__all__ = [
    "DjangoSimulatedAccountRowSourceClock",
    "DjangoSimulatedAccountRowSourceConflict",
    "DjangoSimulatedAccountRowSourceCorruption",
    "DjangoSimulatedAccountRowSourceRepository",
    "DjangoSimulatedAccountRowSourceUnavailable",
    "SimulatedAccountRowSourceClock",
]
