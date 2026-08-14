"""Django append-only repository for simulated account-row source v2s."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from typing import Protocol

from django.db import IntegrityError, transaction
from django.utils import timezone

from apps.simulated_trading.application.simulated_account_row_source_v2 import (
    PersistedSimulatedAccountRowSourceV2,
    SimulatedAccountRowSourceV2Conflict,
    SimulatedAccountRowSourceV2Corruption,
    SimulatedAccountRowSourceV2Unavailable,
)
from apps.simulated_trading.domain.simulated_account_row_source_v2 import (
    SimulatedAccountRowSourceV2,
    validate_simulated_account_row_source_v2_successor,
)
from apps.simulated_trading.infrastructure.simulated_account_row_source_v2_codec import (
    SimulatedAccountRowSourceV2CodecError,
    decode_simulated_account_row_source_v2_record,
    encode_simulated_account_row_source_v2_record,
)
from apps.simulated_trading.infrastructure.simulated_account_row_source_v2_models import (
    _ACTIVE_SIMULATED_ACCOUNT_ROW_SOURCE_V2_UOW,
    SimulatedAccountRowSourceV2Model,
    _activate_simulated_account_row_source_v2_uow,
    _claim_simulated_account_row_source_v2_insert,
)


class DjangoSimulatedAccountRowSourceV2Unavailable(SimulatedAccountRowSourceV2Unavailable):
    """Source evidence is unavailable at the requested cutoff."""


class DjangoSimulatedAccountRowSourceV2Conflict(SimulatedAccountRowSourceV2Conflict):
    """A source first-winner or predecessor claim conflicted."""


class DjangoSimulatedAccountRowSourceV2Corruption(SimulatedAccountRowSourceV2Corruption):
    """Persisted source evidence failed closed-world verification."""


class SimulatedAccountRowSourceV2Clock(Protocol):
    """Provide the authoritative SimulatedTrading persistence clock."""

    def now(self) -> datetime: ...


class DjangoSimulatedAccountRowSourceV2Clock:
    """Django timezone-backed production clock."""

    def now(self) -> datetime:
        """Return current Django time."""

        return timezone.now()


class DjangoSimulatedAccountRowSourceV2Repository:
    """Private first-winner ledger with full-table closed-world restore."""

    __slots__ = ("_clock", "_using")

    def __init__(
        self,
        *,
        using: str = "default",
        clock: SimulatedAccountRowSourceV2Clock | None = None,
    ) -> None:
        self._using = using
        self._clock = clock or DjangoSimulatedAccountRowSourceV2Clock()

    @contextmanager
    def atomic(self) -> Iterator[None]:
        """Open this ledger's independent private append transaction."""

        token = object()
        with (
            transaction.atomic(using=self._using),
            _activate_simulated_account_row_source_v2_uow(token),
        ):
            yield

    def now(self) -> datetime:
        """Return the validated authoritative server clock."""

        value = self._clock.now()
        _require_aware(value, "simulated account-row source v2 clock")
        return value

    def append(
        self,
        record: PersistedSimulatedAccountRowSourceV2,
        *,
        expected_predecessor_hash: str | None,
        recorded_at: datetime,
    ) -> PersistedSimulatedAccountRowSourceV2:
        """CAS-append or return the exact immutable first winner."""

        token = _active_token()
        checked = _require_exact_record(record)
        source = checked.source
        _require_aware(recorded_at, "recorded_at")
        if source.recorded_at != recorded_at:
            raise DjangoSimulatedAccountRowSourceV2Conflict(
                "persisted_at and source recorded_at must be identical"
            )
        if source.supersedes_content_hash != expected_predecessor_hash:
            raise DjangoSimulatedAccountRowSourceV2Conflict(
                "simulated account-row source v2 does not bind the expected predecessor"
            )
        if not source.is_knowable_at(recorded_at):
            raise DjangoSimulatedAccountRowSourceV2Conflict(
                "simulated account-row source v2 must be persisted inside its validity window"
            )
        existing = self._exact_model(checked)
        if existing is not None:
            return self._restore(existing)
        current = self._current_head(source, as_of=recorded_at, lock=True)
        actual_predecessor = current.source.content_hash if current is not None else None
        if actual_predecessor != expected_predecessor_hash:
            raise DjangoSimulatedAccountRowSourceV2Conflict(
                "simulated account-row source v2 predecessor CAS conflict"
            )
        if current is not None:
            try:
                validate_simulated_account_row_source_v2_successor(
                    current.source,
                    source,
                )
            except (TypeError, ValueError) as error:
                raise DjangoSimulatedAccountRowSourceV2Conflict(
                    "simulated account-row source v2 successor is invalid"
                ) from error
        values = _model_values(checked, recorded_at=recorded_at)
        model = SimulatedAccountRowSourceV2Model(**values)
        try:
            with transaction.atomic(using=self._using):
                with _claim_simulated_account_row_source_v2_insert(
                    token=token,
                    model_type=SimulatedAccountRowSourceV2Model,
                    expected_values=values,
                ):
                    model.save(force_insert=True, using=self._using)
        except IntegrityError:
            winner = self._exact_model(checked)
            if winner is None:
                raise DjangoSimulatedAccountRowSourceV2Conflict(
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
    ) -> PersistedSimulatedAccountRowSourceV2 | None:
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
            raise DjangoSimulatedAccountRowSourceV2Corruption(
                "simulated account-row source v2 first winner is ambiguous"
            )
        return matches[0]

    def get_exact_by_hash(
        self,
        *,
        source_id: str,
        source_version: str,
        expected_content_hash: str,
        as_of: datetime,
    ) -> PersistedSimulatedAccountRowSourceV2 | None:
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
            raise DjangoSimulatedAccountRowSourceV2Corruption(
                "simulated account-row source v2 exact anchors are ambiguous"
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
    ) -> PersistedSimulatedAccountRowSourceV2 | None:
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
        key = (
            source_id,
            account_namespace,
            account_id,
            underlying_unified_account_namespace,
            underlying_unified_account_id,
        )
        records = self._visible_records(as_of=as_of, lock=False)
        chain = tuple(record for record in records if _logical_key(record.source) == key)
        return _restore_full_chain(chain) if chain else None

    def _current_head(
        self,
        selector: SimulatedAccountRowSourceV2,
        *,
        as_of: datetime,
        lock: bool,
    ) -> PersistedSimulatedAccountRowSourceV2 | None:
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
    ) -> tuple[PersistedSimulatedAccountRowSourceV2, ...]:
        """Restore the full table before trusting any selector header."""

        queryset = SimulatedAccountRowSourceV2Model._default_manager.using(self._using).all()
        if lock:
            queryset = queryset.select_for_update()
        rows = list(queryset.order_by("recorded_at", "pk"))
        restored = tuple(self._restore(row) for row in rows)
        return tuple(record for record in restored if record.source.recorded_at <= as_of)

    def _require_cutoff(self, as_of: datetime) -> None:
        _require_aware(as_of, "simulated account-row source v2 as_of")
        if as_of > self.now():
            raise DjangoSimulatedAccountRowSourceV2Unavailable(
                "future simulated account-row source v2 as_of is forbidden"
            )

    def _exact_model(
        self,
        record: PersistedSimulatedAccountRowSourceV2,
    ) -> SimulatedAccountRowSourceV2Model | None:
        source = record.source
        root_claim = _root_claim_hash(source)
        rows = list(SimulatedAccountRowSourceV2Model._default_manager.using(self._using).all())
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
                or row.raw_binding_seal == _raw_binding_seal(source)
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
            raise DjangoSimulatedAccountRowSourceV2Conflict(
                "source uniqueness or logical-chain claim has another first winner"
            )
        return matches[0]

    def _restore(
        self,
        model: SimulatedAccountRowSourceV2Model,
    ) -> PersistedSimulatedAccountRowSourceV2:
        try:
            record = decode_simulated_account_row_source_v2_record(model.canonical_payload)
        except SimulatedAccountRowSourceV2CodecError as error:
            raise DjangoSimulatedAccountRowSourceV2Corruption(
                "simulated account-row source v2 payload cannot be restored"
            ) from error
        source = record.source
        if _record_headers(record) != _model_headers(model):
            raise DjangoSimulatedAccountRowSourceV2Corruption(
                "simulated account-row source v2 headers do not match payload"
            )
        expected_root = _root_claim_hash(source) if source.supersedes_content_hash is None else None
        checks = (
            (model.root_claim_hash, expected_root, "root claim"),
            (model.raw_binding_seal, _raw_binding_seal(source), "raw binding seal"),
            (model.row_seal, _row_fact_hash(source), "row fact seal"),
            (model.logical_seal, _logical_binding_hash(source), "logical binding seal"),
            (model.clock_seal, _clock_seal(source), "clock seal"),
            (model.record_seal, _record_header_hash(record), "record header seal"),
            (
                model.ledger_seal,
                _ledger_header_hash(record, recorded_at=model.recorded_at),
                "ledger header seal",
            ),
        )
        for actual, expected, label in checks:
            if actual != expected:
                raise DjangoSimulatedAccountRowSourceV2Corruption(
                    f"simulated account-row source v2 {label} is invalid"
                )
        if (
            model.persisted_at.tzinfo is None
            or model.persisted_at.utcoffset() is None
            or model.persisted_at != model.recorded_at
            or model.recorded_at != source.recorded_at
        ):
            raise DjangoSimulatedAccountRowSourceV2Corruption(
                "simulated account-row source v2 persistence clock is invalid"
            )
        return record


def _active_token() -> object:
    token = _ACTIVE_SIMULATED_ACCOUNT_ROW_SOURCE_V2_UOW.get()
    if token is None:
        raise DjangoSimulatedAccountRowSourceV2Conflict(
            "source append requires an active private unit of work"
        )
    return token


def _require_exact_record(value: object) -> PersistedSimulatedAccountRowSourceV2:
    if type(value) is not PersistedSimulatedAccountRowSourceV2:
        raise DjangoSimulatedAccountRowSourceV2Corruption("source record type substitution")
    PersistedSimulatedAccountRowSourceV2.__post_init__(value)
    return value


def _require_aware(value: object, field_name: str) -> None:
    if type(value) is not datetime or value.tzinfo is None or value.utcoffset() is None:
        raise DjangoSimulatedAccountRowSourceV2Unavailable(f"{field_name} must be timezone-aware")


def _require_token(value: object, field_name: str) -> None:
    if (
        type(value) is not str
        or not value
        or value.strip() != value
        or len(value) > 192
        or any(character.isspace() for character in value)
    ):
        raise DjangoSimulatedAccountRowSourceV2Unavailable(
            f"{field_name} must be a bounded canonical token"
        )


def _require_hash(value: object, field_name: str) -> None:
    if (
        type(value) is not str
        or len(value) != 64
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise DjangoSimulatedAccountRowSourceV2Unavailable(
            f"{field_name} must be a lowercase SHA-256 digest"
        )


def _require_positive_integer(value: object, field_name: str) -> None:
    if type(value) is not int or value <= 0:
        raise DjangoSimulatedAccountRowSourceV2Unavailable(
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


def _logical_key(source: SimulatedAccountRowSourceV2) -> tuple[object, ...]:
    return (
        source.source_id,
        source.account_namespace,
        source.account_id,
        source.underlying_unified_account_namespace,
        source.underlying_unified_account_id,
    )


def _root_claim_hash(source: SimulatedAccountRowSourceV2) -> str:
    return _hash_payload({"logical_key": list(_logical_key(source))})


def _row_fact_hash(source: SimulatedAccountRowSourceV2) -> str:
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


def _raw_binding_seal(source: SimulatedAccountRowSourceV2) -> str:
    return _hash_payload(
        {
            "owner": source.raw_observation_owner,
            "artifact_type": source.raw_observation_artifact_type,
            "schema": source.raw_observation_schema,
            "observation_id": source.raw_observation_id,
            "observation_version": source.raw_observation_version,
            "identity_hash": source.raw_observation_identity_hash,
            "content_hash": source.raw_observation_content_hash,
            "supersedes_content_hash": source.raw_observation_supersedes_content_hash,
        }
    )


def _clock_seal(source: SimulatedAccountRowSourceV2) -> str:
    return _hash_payload(
        {
            "observed_at": _time(source.observed_at),
            "recorded_at": _time(source.recorded_at),
            "source_valid_until": _time(source.source_valid_until),
            "ttl_valid_until": _time(source.ttl_valid_until),
            "valid_until": _time(source.valid_until),
            "raw_observation_observed_at": _time(source.raw_observation_observed_at),
            "raw_observation_valid_until": _time(source.raw_observation_valid_until),
        }
    )


def _logical_binding_hash(source: SimulatedAccountRowSourceV2) -> str:
    return _hash_payload(
        {
            "logical_key": list(_logical_key(source)),
            "source_version": source.source_version,
            "raw_binding_seal": _raw_binding_seal(source),
            "row_fact_hash": _row_fact_hash(source),
        }
    )


def _record_header_hash(record: PersistedSimulatedAccountRowSourceV2) -> str:
    return _hash_payload({"record": encode_simulated_account_row_source_v2_record(record)})


def _ledger_header_hash(
    record: PersistedSimulatedAccountRowSourceV2,
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
            "raw_binding_seal": _raw_binding_seal(source),
            "row_fact_hash": _row_fact_hash(source),
            "logical_binding_hash": _logical_binding_hash(source),
            "clock_seal": _clock_seal(source),
            "persisted_at": _time(recorded_at),
        }
    )


def _model_values(
    record: PersistedSimulatedAccountRowSourceV2,
    *,
    recorded_at: datetime,
) -> dict[str, object]:
    source = record.source
    values: dict[str, object] = {
        name: getattr(source, name) for name in _SOURCE_HEADER_NAMES if name != "recorded_at"
    }
    values.update(
        {
            "recorded_at": recorded_at,
            "root_claim_hash": (
                _root_claim_hash(source) if source.supersedes_content_hash is None else None
            ),
            "canonical_payload": encode_simulated_account_row_source_v2_record(record),
            "raw_binding_seal": _raw_binding_seal(source),
            "row_seal": _row_fact_hash(source),
            "logical_seal": _logical_binding_hash(source),
            "clock_seal": _clock_seal(source),
            "record_seal": _record_header_hash(record),
            "ledger_seal": _ledger_header_hash(
                record,
                recorded_at=recorded_at,
            ),
            "persisted_at": recorded_at,
        }
    )
    return values


def _record_headers(record: PersistedSimulatedAccountRowSourceV2) -> tuple[object, ...]:
    source = record.source
    return tuple(getattr(source, name) for name in _SOURCE_HEADER_NAMES)


def _model_headers(model: SimulatedAccountRowSourceV2Model) -> tuple[object, ...]:
    return tuple(getattr(model, name) for name in _SOURCE_HEADER_NAMES)


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
    "raw_observation_id",
    "raw_observation_version",
    "raw_observation_identity_hash",
    "raw_observation_content_hash",
    "raw_observation_observed_at",
    "raw_observation_valid_until",
    "raw_observation_supersedes_content_hash",
    "owner_assignment_state",
    "raw_observation_owner",
    "raw_observation_artifact_type",
    "raw_observation_schema",
    "supersedes_content_hash",
    "permission",
    "status",
    "identity_hash",
    "content_hash",
)


def _restore_full_chain(
    records: tuple[PersistedSimulatedAccountRowSourceV2, ...],
) -> PersistedSimulatedAccountRowSourceV2:
    by_hash = {record.source.content_hash: record for record in records}
    if len(by_hash) != len(records):
        raise DjangoSimulatedAccountRowSourceV2Corruption("source chain has duplicate content")
    roots = tuple(record for record in records if record.source.supersedes_content_hash is None)
    if len(roots) != 1:
        raise DjangoSimulatedAccountRowSourceV2Corruption(
            "source chain must have exactly one visible root"
        )
    successor_by_predecessor: dict[str, PersistedSimulatedAccountRowSourceV2] = {}
    for record in records:
        predecessor_hash = record.source.supersedes_content_hash
        if predecessor_hash is None:
            continue
        predecessor = by_hash.get(predecessor_hash)
        if predecessor is None:
            raise DjangoSimulatedAccountRowSourceV2Corruption(
                "source predecessor is missing at cutoff"
            )
        if predecessor_hash in successor_by_predecessor:
            raise DjangoSimulatedAccountRowSourceV2Corruption(
                "source predecessor has multiple successors"
            )
        try:
            validate_simulated_account_row_source_v2_successor(
                predecessor.source,
                record.source,
            )
        except (TypeError, ValueError) as error:
            raise DjangoSimulatedAccountRowSourceV2Corruption(
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
        raise DjangoSimulatedAccountRowSourceV2Corruption("source chain is disconnected or cyclic")
    return current


__all__ = [
    "DjangoSimulatedAccountRowSourceV2Clock",
    "DjangoSimulatedAccountRowSourceV2Conflict",
    "DjangoSimulatedAccountRowSourceV2Corruption",
    "DjangoSimulatedAccountRowSourceV2Repository",
    "DjangoSimulatedAccountRowSourceV2Unavailable",
    "SimulatedAccountRowSourceV2Clock",
]
