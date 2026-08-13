"""Django append-only repository for raw simulated-account observations."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from typing import Protocol

from django.db import IntegrityError, transaction
from django.utils import timezone

from apps.simulated_trading.application.simulated_account_raw_observation import (
    PersistedSimulatedAccountRawObservation,
    SimulatedAccountRawObservationConflict,
    SimulatedAccountRawObservationCorruption,
    SimulatedAccountRawObservationUnavailable,
)
from apps.simulated_trading.domain.simulated_account_raw_observation import (
    SimulatedAccountRawObservation,
    validate_simulated_account_raw_observation_successor,
)
from apps.simulated_trading.infrastructure.simulated_account_raw_observation_codec import (
    SimulatedAccountRawObservationCodecError,
    decode_simulated_account_raw_observation_record,
    encode_simulated_account_raw_observation_record,
)
from apps.simulated_trading.infrastructure.simulated_account_raw_observation_models import (
    _ACTIVE_SIMULATED_ACCOUNT_RAW_OBSERVATION_UOW,
    SimulatedAccountRawObservationModel,
    _activate_simulated_account_raw_observation_uow,
    _claim_simulated_account_raw_observation_insert,
)


class DjangoSimulatedAccountRawObservationUnavailable(SimulatedAccountRawObservationUnavailable):
    """Raw observation evidence is unavailable at the requested cutoff."""


class DjangoSimulatedAccountRawObservationConflict(SimulatedAccountRawObservationConflict):
    """A raw observation first-winner or predecessor claim conflicted."""


class DjangoSimulatedAccountRawObservationCorruption(SimulatedAccountRawObservationCorruption):
    """Persisted raw observation evidence failed closed-world verification."""


class SimulatedAccountRawObservationClock(Protocol):
    """Provide the authoritative persistence clock."""

    def now(self) -> datetime: ...


class DjangoSimulatedAccountRawObservationClock:
    """Django timezone-backed production clock."""

    def now(self) -> datetime:
        """Return current Django time."""

        return timezone.now()


class DjangoSimulatedAccountRawObservationRepository:
    """Private first-winner ledger with full-table closed-world restore."""

    __slots__ = ("_clock", "_using")

    def __init__(
        self,
        *,
        using: str = "default",
        clock: SimulatedAccountRawObservationClock | None = None,
    ) -> None:
        self._using = using
        self._clock = clock or DjangoSimulatedAccountRawObservationClock()

    @contextmanager
    def atomic(self) -> Iterator[None]:
        """Open this ledger's independent private append transaction."""

        token = object()
        with (
            transaction.atomic(using=self._using),
            _activate_simulated_account_raw_observation_uow(token),
        ):
            yield

    def now(self) -> datetime:
        """Return the validated authoritative server clock."""

        value = self._clock.now()
        _require_aware(value, "raw observation clock")
        return value

    @property
    def database_alias(self) -> str:
        """Return the database alias shared with the owner mutation UOW."""

        return self._using

    def append(
        self,
        record: PersistedSimulatedAccountRawObservation,
        *,
        expected_predecessor_hash: str | None,
        recorded_at: datetime,
    ) -> PersistedSimulatedAccountRawObservation:
        """CAS-append or return only the exact immutable first winner."""

        token = _active_token()
        checked = _require_record(record)
        observation = checked.observation
        _require_aware(recorded_at, "recorded_at")
        if checked.recorded_at != recorded_at:
            raise DjangoSimulatedAccountRawObservationConflict(
                "recorded_at and persisted_at must be identical"
            )
        if observation.supersedes_content_hash != expected_predecessor_hash:
            raise DjangoSimulatedAccountRawObservationConflict(
                "raw observation does not bind the expected predecessor"
            )
        if not observation.is_knowable_at(recorded_at):
            raise DjangoSimulatedAccountRawObservationConflict(
                "raw observation must be persisted inside its validity window"
            )
        existing = self._exact_model(checked)
        if existing is not None:
            return self._restore(existing)
        current = self._current_head(observation, as_of=recorded_at, lock=True)
        actual = current.observation.content_hash if current is not None else None
        if actual != expected_predecessor_hash:
            raise DjangoSimulatedAccountRawObservationConflict(
                "raw observation predecessor CAS conflict"
            )
        if current is not None:
            try:
                validate_simulated_account_raw_observation_successor(
                    current.observation, observation
                )
            except (TypeError, ValueError) as error:
                raise DjangoSimulatedAccountRawObservationConflict(
                    "raw observation successor is invalid"
                ) from error
        values = _model_values(checked)
        model = SimulatedAccountRawObservationModel(**values)
        try:
            with transaction.atomic(using=self._using):
                with _claim_simulated_account_raw_observation_insert(
                    token=token,
                    model_type=SimulatedAccountRawObservationModel,
                    expected_values=values,
                ):
                    model.save(force_insert=True, using=self._using)
        except IntegrityError:
            winner = self._exact_model(checked)
            if winner is None:
                raise DjangoSimulatedAccountRawObservationConflict(
                    "append conflicted without an exact candidate first winner"
                ) from None
            return self._restore(winner)
        return self._restore(model)

    def get_winner(
        self,
        *,
        observation_id: str,
        observation_version: str,
        as_of: datetime,
    ) -> PersistedSimulatedAccountRawObservation | None:
        """Return the exact identity first winner recorded by the PIT cutoff."""

        _require_token(observation_id, "observation_id")
        _require_token(observation_version, "observation_version")
        self._require_cutoff(as_of)
        matches = tuple(
            record
            for record in self._visible_records(as_of=as_of, lock=False)
            if record.observation.observation_id == observation_id
            and record.observation.observation_version == observation_version
        )
        if not matches:
            return None
        if len(matches) != 1:
            raise DjangoSimulatedAccountRawObservationCorruption(
                "raw observation first winner is ambiguous"
            )
        return matches[0]

    def get_exact_by_hash(
        self,
        *,
        observation_id: str,
        observation_version: str,
        expected_content_hash: str,
        as_of: datetime,
    ) -> PersistedSimulatedAccountRawObservation | None:
        """Return one exact identity/hash historical PIT record."""

        _require_token(observation_id, "observation_id")
        _require_token(observation_version, "observation_version")
        _require_hash(expected_content_hash, "expected_content_hash")
        self._require_cutoff(as_of)
        records = self._visible_records(as_of=as_of, lock=False)
        anchors = tuple(
            record
            for record in records
            if (
                (
                    record.observation.observation_id == observation_id
                    and record.observation.observation_version == observation_version
                )
                or record.observation.content_hash == expected_content_hash
            )
        )
        if not anchors:
            return None
        matches = tuple(
            record
            for record in anchors
            if record.observation.observation_id == observation_id
            and record.observation.observation_version == observation_version
            and record.observation.content_hash == expected_content_hash
        )
        if len(anchors) != 1 or len(matches) != 1:
            raise DjangoSimulatedAccountRawObservationCorruption(
                "raw observation exact anchors are ambiguous"
            )
        record = matches[0]
        return record if record.observation.is_knowable_at(as_of) else None

    def get_current_head(
        self,
        *,
        observation_id: str,
        row_pk: int,
        as_of: datetime,
    ) -> PersistedSimulatedAccountRawObservation | None:
        """Return the final PIT head without tombstone or expiry fallback."""

        _require_token(observation_id, "observation_id")
        _require_positive_integer(row_pk, "row_pk")
        self._require_cutoff(as_of)
        records = self._visible_records(as_of=as_of, lock=False)
        chain = tuple(
            record
            for record in records
            if record.observation.observation_id == observation_id
            and record.observation.row_pk == row_pk
        )
        return _restore_full_chain(chain) if chain else None

    def get_physical_row_head(
        self,
        *,
        row_pk: int,
        as_of: datetime,
    ) -> PersistedSimulatedAccountRawObservation | None:
        """Return the sole final chain head for a physical row across opaque IDs."""

        _require_positive_integer(row_pk, "row_pk")
        self._require_cutoff(as_of)
        chain = tuple(
            record
            for record in self._visible_records(as_of=as_of, lock=False)
            if record.observation.row_pk == row_pk
        )
        return _restore_full_chain(chain) if chain else None

    def _current_head(
        self,
        selector: SimulatedAccountRawObservation,
        *,
        as_of: datetime,
        lock: bool,
    ) -> PersistedSimulatedAccountRawObservation | None:
        records = self._visible_records(as_of=as_of, lock=lock)
        chain = tuple(
            record
            for record in records
            if _logical_key(record.observation) == _logical_key(selector)
        )
        return _restore_full_chain(chain) if chain else None

    def _visible_records(
        self, *, as_of: datetime, lock: bool
    ) -> tuple[PersistedSimulatedAccountRawObservation, ...]:
        queryset = SimulatedAccountRawObservationModel._default_manager.using(self._using).all()
        if lock:
            queryset = queryset.select_for_update()
        restored = tuple(self._restore(row) for row in queryset.order_by("recorded_at", "pk"))
        return tuple(record for record in restored if record.recorded_at <= as_of)

    def _require_cutoff(self, as_of: datetime) -> None:
        _require_aware(as_of, "raw observation as_of")
        if as_of > self.now():
            raise DjangoSimulatedAccountRawObservationUnavailable(
                "future raw observation as_of is forbidden"
            )

    def _exact_model(
        self, record: PersistedSimulatedAccountRawObservation
    ) -> SimulatedAccountRawObservationModel | None:
        observation = record.observation
        root_claim = _root_claim_hash(observation)
        rows = tuple(SimulatedAccountRawObservationModel._default_manager.using(self._using).all())
        if not rows:
            return None
        restored = tuple((row, self._restore(row)) for row in rows)
        anchors = tuple(
            (row, value)
            for row, value in restored
            if (
                (
                    value.observation.observation_id == observation.observation_id
                    and value.observation.observation_version == observation.observation_version
                )
                or value.observation.identity_hash == observation.identity_hash
                or value.observation.content_hash == observation.content_hash
                or (
                    observation.supersedes_content_hash is None
                    and row.root_claim_hash == root_claim
                )
                or (
                    observation.supersedes_content_hash is not None
                    and value.observation.supersedes_content_hash
                    == observation.supersedes_content_hash
                )
            )
        )
        if not anchors:
            return None
        matches = tuple(row for row, value in anchors if value == record)
        if len(anchors) != 1 or len(matches) != 1:
            raise DjangoSimulatedAccountRawObservationConflict(
                "raw observation uniqueness claim has another first winner"
            )
        return matches[0]

    def _restore(
        self, model: SimulatedAccountRawObservationModel
    ) -> PersistedSimulatedAccountRawObservation:
        try:
            record = decode_simulated_account_raw_observation_record(model.canonical_payload)
        except SimulatedAccountRawObservationCodecError as error:
            raise DjangoSimulatedAccountRawObservationCorruption(
                "raw observation payload cannot be restored"
            ) from error
        observation = record.observation
        if _record_headers(record) != _model_headers(model):
            raise DjangoSimulatedAccountRawObservationCorruption(
                "raw observation headers do not match payload"
            )
        checks = (
            (
                model.root_claim_hash,
                (
                    _root_claim_hash(observation)
                    if observation.supersedes_content_hash is None
                    else None
                ),
                "root claim",
            ),
            (model.authority_seal, _authority_seal(observation), "authority seal"),
            (model.row_seal, _row_seal(observation), "row seal"),
            (model.clock_seal, _clock_seal(record), "clock seal"),
            (model.record_seal, _record_seal(record), "record seal"),
            (model.ledger_seal, _ledger_seal(record), "ledger seal"),
        )
        for actual, expected, label in checks:
            if actual != expected:
                raise DjangoSimulatedAccountRawObservationCorruption(
                    f"raw observation {label} is invalid"
                )
        if model.persisted_at != model.recorded_at or model.recorded_at != record.recorded_at:
            raise DjangoSimulatedAccountRawObservationCorruption(
                "raw observation persistence clock is invalid"
            )
        return record


def _active_token() -> object:
    token = _ACTIVE_SIMULATED_ACCOUNT_RAW_OBSERVATION_UOW.get()
    if token is None:
        raise DjangoSimulatedAccountRawObservationConflict(
            "raw observation append requires an active private UOW"
        )
    return token


def _require_record(value: object) -> PersistedSimulatedAccountRawObservation:
    if type(value) is not PersistedSimulatedAccountRawObservation:
        raise DjangoSimulatedAccountRawObservationCorruption(
            "raw observation record type substitution"
        )
    PersistedSimulatedAccountRawObservation.__post_init__(value)
    return value


def _require_aware(value: object, field_name: str) -> None:
    if type(value) is not datetime or value.tzinfo is None or value.utcoffset() is None:
        raise DjangoSimulatedAccountRawObservationUnavailable(
            f"{field_name} must be timezone-aware"
        )


def _require_token(value: object, field_name: str) -> None:
    if (
        type(value) is not str
        or not value
        or value.strip() != value
        or len(value) > 192
        or any(character.isspace() for character in value)
    ):
        raise DjangoSimulatedAccountRawObservationUnavailable(
            f"{field_name} must be a bounded canonical token"
        )


def _require_hash(value: object, field_name: str) -> None:
    if (
        type(value) is not str
        or len(value) != 64
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise DjangoSimulatedAccountRawObservationUnavailable(
            f"{field_name} must be a lowercase SHA-256 digest"
        )


def _require_positive_integer(value: object, field_name: str) -> None:
    if type(value) is not int or value <= 0:
        raise DjangoSimulatedAccountRawObservationUnavailable(
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


def _logical_key(value: SimulatedAccountRawObservation) -> tuple[object, ...]:
    return value.observation_id, value.row_pk


def _root_claim_hash(value: SimulatedAccountRawObservation) -> str:
    return _hash_payload({"logical_key": list(_logical_key(value))})


def _authority_seal(value: SimulatedAccountRawObservation) -> str:
    return _hash_payload(
        {
            "owner": value.owner,
            "artifact_type": value.artifact_type,
            "schema": value.schema,
            "permission": value.permission,
            "status": value.status,
        }
    )


def _row_seal(value: SimulatedAccountRawObservation) -> str:
    return _hash_payload(
        {
            "logical_key": list(_logical_key(value)),
            "row_user_id": value.row_user_id,
            "raw_account_type": value.raw_account_type,
            "is_active": value.is_active,
            "row_created_at": _time(value.row_created_at),
            "row_updated_at": _time(value.row_updated_at),
            "is_present": value.is_present,
            "is_tombstone": value.is_tombstone,
        }
    )


def _clock_seal(record: PersistedSimulatedAccountRawObservation) -> str:
    value = record.observation
    return _hash_payload(
        {
            "observed_at": _time(value.observed_at),
            "valid_until": _time(value.valid_until),
            "recorded_at": _time(record.recorded_at),
            "persisted_at": _time(record.recorded_at),
        }
    )


def _record_seal(record: PersistedSimulatedAccountRawObservation) -> str:
    return _hash_payload({"record": encode_simulated_account_raw_observation_record(record)})


def _ledger_seal(record: PersistedSimulatedAccountRawObservation) -> str:
    value = record.observation
    return _hash_payload(
        {
            "record_seal": _record_seal(record),
            "root_claim_hash": (
                _root_claim_hash(value) if value.supersedes_content_hash is None else None
            ),
            "authority_seal": _authority_seal(value),
            "row_seal": _row_seal(value),
            "clock_seal": _clock_seal(record),
        }
    )


_OBSERVATION_HEADERS = (
    "owner",
    "artifact_type",
    "schema",
    "observation_id",
    "observation_version",
    "row_pk",
    "row_user_id",
    "raw_account_type",
    "is_active",
    "row_created_at",
    "row_updated_at",
    "is_present",
    "is_tombstone",
    "observed_at",
    "valid_until",
    "supersedes_content_hash",
    "permission",
    "status",
    "identity_hash",
    "content_hash",
)


def _model_values(
    record: PersistedSimulatedAccountRawObservation,
) -> dict[str, object]:
    value = record.observation
    result: dict[str, object] = {name: getattr(value, name) for name in _OBSERVATION_HEADERS}
    result.update(
        {
            "root_claim_hash": (
                _root_claim_hash(value) if value.supersedes_content_hash is None else None
            ),
            "canonical_payload": encode_simulated_account_raw_observation_record(record),
            "authority_seal": _authority_seal(value),
            "row_seal": _row_seal(value),
            "clock_seal": _clock_seal(record),
            "record_seal": _record_seal(record),
            "ledger_seal": _ledger_seal(record),
            "recorded_at": record.recorded_at,
            "persisted_at": record.recorded_at,
        }
    )
    return result


def _record_headers(
    record: PersistedSimulatedAccountRawObservation,
) -> tuple[object, ...]:
    return tuple(getattr(record.observation, name) for name in _OBSERVATION_HEADERS) + (
        record.recorded_at,
    )


def _model_headers(model: SimulatedAccountRawObservationModel) -> tuple[object, ...]:
    return tuple(getattr(model, name) for name in _OBSERVATION_HEADERS) + (model.recorded_at,)


def _restore_full_chain(
    records: tuple[PersistedSimulatedAccountRawObservation, ...],
) -> PersistedSimulatedAccountRawObservation:
    by_hash = {record.observation.content_hash: record for record in records}
    if len(by_hash) != len(records):
        raise DjangoSimulatedAccountRawObservationCorruption(
            "raw observation chain has duplicate content"
        )
    roots = tuple(
        record for record in records if record.observation.supersedes_content_hash is None
    )
    if len(roots) != 1:
        raise DjangoSimulatedAccountRawObservationCorruption(
            "raw observation chain must have exactly one visible root"
        )
    successors: dict[str, PersistedSimulatedAccountRawObservation] = {}
    for record in records:
        predecessor_hash = record.observation.supersedes_content_hash
        if predecessor_hash is None:
            continue
        predecessor = by_hash.get(predecessor_hash)
        if predecessor is None or predecessor_hash in successors:
            raise DjangoSimulatedAccountRawObservationCorruption(
                "raw observation predecessor graph is invalid"
            )
        try:
            validate_simulated_account_raw_observation_successor(
                predecessor.observation, record.observation
            )
        except (TypeError, ValueError) as error:
            raise DjangoSimulatedAccountRawObservationCorruption(
                "raw observation successor link is invalid"
            ) from error
        successors[predecessor_hash] = record
    visited: set[str] = set()
    current = roots[0]
    while current.observation.content_hash not in visited:
        visited.add(current.observation.content_hash)
        successor = successors.get(current.observation.content_hash)
        if successor is None:
            break
        current = successor
    if len(visited) != len(records):
        raise DjangoSimulatedAccountRawObservationCorruption(
            "raw observation chain is disconnected or cyclic"
        )
    return current


__all__ = [
    "DjangoSimulatedAccountRawObservationClock",
    "DjangoSimulatedAccountRawObservationConflict",
    "DjangoSimulatedAccountRawObservationCorruption",
    "DjangoSimulatedAccountRawObservationRepository",
    "DjangoSimulatedAccountRawObservationUnavailable",
    "SimulatedAccountRawObservationClock",
]
