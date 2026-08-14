"""Django append-only repository for Account physical-row evidence."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from typing import Protocol

from django.db import IntegrityError, transaction
from django.utils import timezone

from apps.account.application.physical_account_row_observation import (
    PersistedPhysicalAccountRowObservation,
    PhysicalAccountRowObservationActor,
    PhysicalAccountRowObservationConflict,
    PhysicalAccountRowObservationCorruption,
    PhysicalAccountRowObservationUnavailable,
)
from apps.account.domain.physical_account_row_observation import (
    PhysicalAccountRowObservation,
    validate_physical_account_row_observation_successor,
)
from apps.account.infrastructure.physical_account_row_observation_codec import (
    PhysicalAccountRowObservationCodecError,
    decode_physical_account_row_observation_record,
    encode_physical_account_row_observation_record,
)
from apps.account.infrastructure.physical_account_row_observation_models import (
    _ACTIVE_PHYSICAL_ROW_UOW,
    PhysicalAccountRowObservationModel,
    _activate_physical_account_row_observation_uow,
    _claim_physical_account_row_observation_insert,
)


class DjangoPhysicalAccountRowObservationUnavailable(PhysicalAccountRowObservationUnavailable):
    """Physical row evidence is unavailable at the requested cutoff."""


class DjangoPhysicalAccountRowObservationConflict(PhysicalAccountRowObservationConflict):
    """A physical-row first-winner or predecessor claim conflicted."""


class DjangoPhysicalAccountRowObservationCorruption(PhysicalAccountRowObservationCorruption):
    """Persisted physical-row evidence failed closed-world verification."""


class PhysicalAccountRowObservationClock(Protocol):
    """Provide the authoritative Account persistence clock."""

    def now(self) -> datetime:
        """Return one timezone-aware server time."""


class DjangoPhysicalAccountRowObservationClock:
    """Django timezone-backed production clock."""

    def now(self) -> datetime:
        """Return current Django time."""

        return timezone.now()


class DjangoPhysicalAccountRowObservationRepository:
    """Private first-winner ledger with full-table closed-world restore."""

    __slots__ = ("_clock", "_using")

    def __init__(
        self,
        *,
        using: str = "default",
        clock: PhysicalAccountRowObservationClock | None = None,
    ) -> None:
        self._using = using
        self._clock = clock or DjangoPhysicalAccountRowObservationClock()

    @contextmanager
    def atomic(self) -> Iterator[None]:
        """Open this ledger's independent private append transaction."""

        token = object()
        with (
            transaction.atomic(using=self._using),
            _activate_physical_account_row_observation_uow(token),
        ):
            yield

    def now(self) -> datetime:
        """Return the validated authoritative Account server clock."""

        value = self._clock.now()
        _require_aware(value, "physical account-row clock")
        return value

    def append(
        self,
        record: PersistedPhysicalAccountRowObservation,
        *,
        expected_predecessor_hash: str | None,
        recorded_at: datetime,
    ) -> PersistedPhysicalAccountRowObservation:
        """CAS-append or return the exact immutable first winner."""

        token = _active_token()
        checked = _require_exact_record(record)
        observation = checked.observation
        _require_aware(recorded_at, "recorded_at")
        if observation.recorded_at != recorded_at:
            raise DjangoPhysicalAccountRowObservationConflict(
                "persisted_at and observation recorded_at must be identical"
            )
        if observation.supersedes_content_hash != expected_predecessor_hash:
            raise DjangoPhysicalAccountRowObservationConflict(
                "physical account-row does not bind the expected predecessor"
            )
        if not observation.is_knowable_at(recorded_at):
            raise DjangoPhysicalAccountRowObservationConflict(
                "physical account-row must be persisted inside its validity window"
            )
        existing = self._exact_model(checked)
        if existing is not None:
            return self._restore(existing)
        current = self._current_head(
            account_namespace=observation.account_namespace,
            account_id=observation.account_id,
            underlying_unified_account_namespace=(observation.underlying_unified_account_namespace),
            underlying_unified_account_id=observation.underlying_unified_account_id,
            raw_source_id=observation.raw_source_id,
            as_of=recorded_at,
            lock=True,
        )
        actual_predecessor = current.observation.content_hash if current is not None else None
        if actual_predecessor != expected_predecessor_hash:
            raise DjangoPhysicalAccountRowObservationConflict(
                "physical account-row predecessor CAS conflict"
            )
        if current is not None:
            try:
                validate_physical_account_row_observation_successor(
                    current.observation,
                    observation,
                )
            except (TypeError, ValueError) as error:
                raise DjangoPhysicalAccountRowObservationConflict(
                    "physical account-row successor is invalid"
                ) from error
        values = _model_values(checked, recorded_at=recorded_at)
        model = PhysicalAccountRowObservationModel(**values)
        try:
            with transaction.atomic(using=self._using):
                with _claim_physical_account_row_observation_insert(
                    token=token,
                    model_type=PhysicalAccountRowObservationModel,
                    expected_values=values,
                ):
                    model.save(force_insert=True, using=self._using)
        except IntegrityError:
            winner = self._exact_model(checked)
            if winner is None:
                raise DjangoPhysicalAccountRowObservationConflict(
                    "physical-row append conflicted without an exact visible first winner"
                ) from None
            return self._restore(winner)
        return self._restore(model)

    def get_winner(
        self,
        *,
        observation_id: str,
        observation_version: str,
        as_of: datetime,
    ) -> PersistedPhysicalAccountRowObservation | None:
        """Return the exact first winner recorded by the PIT cutoff."""

        _require_token(observation_id, "observation_id")
        _require_token(observation_version, "observation_version")
        self._require_cutoff(as_of)
        records = self._visible_records(as_of=as_of, lock=False)
        matches = tuple(
            record
            for record in records
            if record.observation.observation_id == observation_id
            and record.observation.observation_version == observation_version
        )
        if not matches:
            return None
        if len(matches) != 1:
            raise DjangoPhysicalAccountRowObservationCorruption(
                "physical account-row first winner is ambiguous"
            )
        return matches[0]

    def get_exact_by_hash(
        self,
        *,
        observation_id: str,
        observation_version: str,
        expected_content_hash: str,
        as_of: datetime,
    ) -> PersistedPhysicalAccountRowObservation | None:
        """Return one exact inactive identity/hash/historical PIT record."""

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
            raise DjangoPhysicalAccountRowObservationCorruption(
                "physical account-row exact anchors are ambiguous"
            )
        record = matches[0]
        return record if record.observation.is_knowable_at(as_of) else None

    def get_current_head(
        self,
        *,
        account_namespace: str,
        account_id: str,
        underlying_unified_account_namespace: str,
        underlying_unified_account_id: int,
        raw_source_id: str,
        as_of: datetime,
    ) -> PersistedPhysicalAccountRowObservation | None:
        """Return the final PIT head, even when it is inactive or expired."""

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
        _require_token(raw_source_id, "raw_source_id")
        self._require_cutoff(as_of)
        return self._current_head(
            account_namespace=account_namespace,
            account_id=account_id,
            underlying_unified_account_namespace=(underlying_unified_account_namespace),
            underlying_unified_account_id=underlying_unified_account_id,
            raw_source_id=raw_source_id,
            as_of=as_of,
            lock=False,
        )

    def _current_head(
        self,
        *,
        account_namespace: str,
        account_id: str,
        underlying_unified_account_namespace: str,
        underlying_unified_account_id: int,
        raw_source_id: str,
        as_of: datetime,
        lock: bool,
    ) -> PersistedPhysicalAccountRowObservation | None:
        records = self._visible_records(as_of=as_of, lock=lock)
        chain = tuple(
            record
            for record in records
            if record.observation.account_namespace == account_namespace
            and record.observation.account_id == account_id
            and record.observation.underlying_unified_account_namespace
            == underlying_unified_account_namespace
            and record.observation.underlying_unified_account_id == underlying_unified_account_id
            and record.observation.raw_source_id == raw_source_id
        )
        return _restore_full_chain(chain) if chain else None

    def _visible_records(
        self,
        *,
        as_of: datetime,
        lock: bool,
    ) -> tuple[PersistedPhysicalAccountRowObservation, ...]:
        """Restore the full table before trusting any selector header."""

        queryset = PhysicalAccountRowObservationModel._default_manager.using(self._using).all()
        if lock:
            queryset = queryset.select_for_update()
        rows = list(queryset.order_by("recorded_at", "pk"))
        restored = tuple(self._restore(row) for row in rows)
        return tuple(record for record in restored if record.observation.recorded_at <= as_of)

    def _require_cutoff(self, as_of: datetime) -> None:
        _require_aware(as_of, "physical account-row as_of")
        if as_of > self.now():
            raise DjangoPhysicalAccountRowObservationUnavailable(
                "future physical account-row as_of is forbidden"
            )

    def _exact_model(
        self,
        record: PersistedPhysicalAccountRowObservation,
    ) -> PhysicalAccountRowObservationModel | None:
        observation = record.observation
        root_claim = _root_claim_hash(observation)
        raw_source_binding = _raw_source_binding_hash(observation)
        actor_binding = _actor_binding_hash(record)
        rows = list(PhysicalAccountRowObservationModel._default_manager.using(self._using).all())
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
                or row.raw_source_binding_hash == raw_source_binding
                or row.actor_binding_hash == actor_binding
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
            raise DjangoPhysicalAccountRowObservationConflict(
                "physical-row uniqueness or logical-chain claim has another first winner"
            )
        return matches[0]

    def _restore(
        self,
        model: PhysicalAccountRowObservationModel,
    ) -> PersistedPhysicalAccountRowObservation:
        try:
            record = decode_physical_account_row_observation_record(model.canonical_payload)
        except PhysicalAccountRowObservationCodecError as error:
            raise DjangoPhysicalAccountRowObservationCorruption(
                "physical account-row canonical payload cannot be restored"
            ) from error
        observation = record.observation
        if _record_headers(record) != _model_headers(model):
            raise DjangoPhysicalAccountRowObservationCorruption(
                "physical account-row headers do not match canonical payload"
            )
        expected_root = (
            _root_claim_hash(observation) if observation.supersedes_content_hash is None else None
        )
        if model.root_claim_hash != expected_root:
            raise DjangoPhysicalAccountRowObservationCorruption(
                "physical account-row root claim is invalid"
            )
        if model.raw_row_hash != _raw_row_hash(observation):
            raise DjangoPhysicalAccountRowObservationCorruption(
                "physical account-row raw row seal is invalid"
            )
        if model.raw_source_binding_hash != _raw_source_binding_hash(observation):
            raise DjangoPhysicalAccountRowObservationCorruption(
                "physical account-row source binding seal is invalid"
            )
        if model.actor_binding_hash != _actor_binding_hash(record):
            raise DjangoPhysicalAccountRowObservationCorruption(
                "physical account-row actor binding seal is invalid"
            )
        if model.record_header_hash != _record_header_hash(record):
            raise DjangoPhysicalAccountRowObservationCorruption(
                "physical account-row record header seal is invalid"
            )
        if model.ledger_header_hash != _ledger_header_hash(
            record,
            recorded_at=model.recorded_at,
        ):
            raise DjangoPhysicalAccountRowObservationCorruption(
                "physical account-row ledger header seal is invalid"
            )
        if (
            model.persisted_at.tzinfo is None
            or model.persisted_at.utcoffset() is None
            or model.persisted_at != model.recorded_at
            or model.recorded_at != observation.recorded_at
        ):
            raise DjangoPhysicalAccountRowObservationCorruption(
                "physical account-row persistence clock is invalid"
            )
        return record


def _active_token() -> object:
    token = _ACTIVE_PHYSICAL_ROW_UOW.get()
    if token is None:
        raise DjangoPhysicalAccountRowObservationConflict(
            "physical-row append requires an active private unit of work"
        )
    return token


def _require_exact_record(value: object) -> PersistedPhysicalAccountRowObservation:
    if type(value) is not PersistedPhysicalAccountRowObservation:
        raise DjangoPhysicalAccountRowObservationCorruption(
            "physical account-row record type substitution"
        )
    PersistedPhysicalAccountRowObservation.__post_init__(value)
    return value


def _require_aware(value: object, field_name: str) -> None:
    if type(value) is not datetime or value.tzinfo is None or value.utcoffset() is None:
        raise DjangoPhysicalAccountRowObservationUnavailable(f"{field_name} must be timezone-aware")


def _require_token(value: object, field_name: str) -> None:
    if (
        type(value) is not str
        or not value
        or value.strip() != value
        or len(value) > 192
        or any(character.isspace() for character in value)
    ):
        raise DjangoPhysicalAccountRowObservationUnavailable(
            f"{field_name} must be a bounded canonical token"
        )


def _require_hash(value: object, field_name: str) -> None:
    if (
        type(value) is not str
        or len(value) != 64
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise DjangoPhysicalAccountRowObservationUnavailable(
            f"{field_name} must be a lowercase SHA-256 digest"
        )


def _require_positive_integer(value: object, field_name: str) -> None:
    if type(value) is not int or value <= 0:
        raise DjangoPhysicalAccountRowObservationUnavailable(
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


def _root_claim_hash(observation: PhysicalAccountRowObservation) -> str:
    return _hash_payload(
        {
            "account_namespace": observation.account_namespace,
            "account_id": observation.account_id,
            "underlying_unified_account_namespace": (
                observation.underlying_unified_account_namespace
            ),
            "underlying_unified_account_id": (observation.underlying_unified_account_id),
            "raw_source_id": observation.raw_source_id,
        }
    )


def _raw_row_hash(observation: PhysicalAccountRowObservation) -> str:
    return _hash_payload(
        {
            "account_namespace": observation.account_namespace,
            "account_id": observation.account_id,
            "underlying_unified_account_namespace": (
                observation.underlying_unified_account_namespace
            ),
            "underlying_unified_account_id": (observation.underlying_unified_account_id),
            "row_user_id": observation.row_user_id,
            "account_type": observation.account_type,
            "is_active": observation.is_active,
            "row_created_at": _time(observation.row_created_at),
            "row_updated_at": _time(observation.row_updated_at),
            "observed_at": _time(observation.observed_at),
        }
    )


def _raw_source_binding_hash(observation: PhysicalAccountRowObservation) -> str:
    return _hash_payload(
        {
            "raw_source_owner": observation.raw_source_owner,
            "raw_source_artifact_type": observation.raw_source_artifact_type,
            "raw_source_id": observation.raw_source_id,
            "raw_source_version": observation.raw_source_version,
            "raw_source_content_hash": observation.raw_source_content_hash,
            "raw_source_valid_until": _time(observation.raw_source_valid_until),
            "raw_row_hash": _raw_row_hash(observation),
        }
    )


def _actor_payload(actor: PhysicalAccountRowObservationActor) -> dict[str, object]:
    return {
        "actor_id": actor.actor_id,
        "user_id": actor.user_id,
        "role": actor.role,
        "kind": actor.kind,
        "is_staff": actor.is_staff,
    }


def _actor_binding_hash(record: PersistedPhysicalAccountRowObservation) -> str:
    return _hash_payload(
        {
            "content_hash": record.observation.content_hash,
            "captured_by": _actor_payload(record.captured_by),
        }
    )


def _record_header_hash(record: PersistedPhysicalAccountRowObservation) -> str:
    return _hash_payload({"record": encode_physical_account_row_observation_record(record)})


def _ledger_header_hash(
    record: PersistedPhysicalAccountRowObservation,
    *,
    recorded_at: datetime,
) -> str:
    observation = record.observation
    return _hash_payload(
        {
            "record_header_hash": _record_header_hash(record),
            "root_claim_hash": (
                _root_claim_hash(observation)
                if observation.supersedes_content_hash is None
                else None
            ),
            "raw_row_hash": _raw_row_hash(observation),
            "raw_source_binding_hash": _raw_source_binding_hash(observation),
            "actor_binding_hash": _actor_binding_hash(record),
            "persisted_at": _time(recorded_at),
        }
    )


def _model_values(
    record: PersistedPhysicalAccountRowObservation,
    *,
    recorded_at: datetime,
) -> dict[str, object]:
    observation = record.observation
    actor = record.captured_by
    values: dict[str, object] = {
        name: getattr(observation, name)
        for name in _OBSERVATION_HEADER_NAMES
        if name not in {"recorded_at", "blocker_codes"}
    }
    values.update(
        {
            "recorded_at": recorded_at,
            "root_claim_hash": (
                _root_claim_hash(observation)
                if observation.supersedes_content_hash is None
                else None
            ),
            "blocker_codes": list(observation.blocker_codes),
            "captured_actor_id": actor.actor_id,
            "captured_actor_user_id": actor.user_id,
            "captured_actor_role": actor.role,
            "captured_actor_kind": actor.kind,
            "captured_actor_is_staff": actor.is_staff,
            "canonical_payload": encode_physical_account_row_observation_record(record),
            "raw_row_hash": _raw_row_hash(observation),
            "raw_source_binding_hash": _raw_source_binding_hash(observation),
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


def _record_headers(
    record: PersistedPhysicalAccountRowObservation,
) -> tuple[object, ...]:
    observation = record.observation
    actor = record.captured_by
    return tuple(getattr(observation, name) for name in _OBSERVATION_HEADER_NAMES) + (
        observation.blocker_codes,
        actor.actor_id,
        actor.user_id,
        actor.role,
        actor.kind,
        actor.is_staff,
    )


def _model_headers(
    model: PhysicalAccountRowObservationModel,
) -> tuple[object, ...]:
    return tuple(getattr(model, name) for name in _OBSERVATION_HEADER_NAMES) + (
        tuple(model.blocker_codes),
        model.captured_actor_id,
        model.captured_actor_user_id,
        model.captured_actor_role,
        model.captured_actor_kind,
        model.captured_actor_is_staff,
    )


_OBSERVATION_HEADER_NAMES = (
    "owner",
    "artifact_type",
    "schema",
    "observation_id",
    "observation_version",
    "account_namespace",
    "account_id",
    "underlying_unified_account_namespace",
    "underlying_unified_account_id",
    "raw_source_owner",
    "raw_source_artifact_type",
    "raw_source_id",
    "raw_source_version",
    "raw_source_content_hash",
    "row_user_id",
    "account_type",
    "is_active",
    "row_created_at",
    "row_updated_at",
    "observed_at",
    "recorded_at",
    "raw_source_valid_until",
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
    records: tuple[PersistedPhysicalAccountRowObservation, ...],
) -> PersistedPhysicalAccountRowObservation:
    by_hash = {record.observation.content_hash: record for record in records}
    if len(by_hash) != len(records):
        raise DjangoPhysicalAccountRowObservationCorruption(
            "physical account-row chain has duplicate content"
        )
    roots = tuple(
        record for record in records if record.observation.supersedes_content_hash is None
    )
    if len(roots) != 1:
        raise DjangoPhysicalAccountRowObservationCorruption(
            "physical account-row chain must have exactly one visible root"
        )
    successor_by_predecessor: dict[str, PersistedPhysicalAccountRowObservation] = {}
    for record in records:
        predecessor_hash = record.observation.supersedes_content_hash
        if predecessor_hash is None:
            continue
        predecessor = by_hash.get(predecessor_hash)
        if predecessor is None:
            raise DjangoPhysicalAccountRowObservationCorruption(
                "physical account-row predecessor is missing at cutoff"
            )
        if predecessor_hash in successor_by_predecessor:
            raise DjangoPhysicalAccountRowObservationCorruption(
                "physical account-row predecessor has multiple successors"
            )
        try:
            validate_physical_account_row_observation_successor(
                predecessor.observation,
                record.observation,
            )
        except (TypeError, ValueError) as error:
            raise DjangoPhysicalAccountRowObservationCorruption(
                "physical account-row successor link is invalid"
            ) from error
        successor_by_predecessor[predecessor_hash] = record
    visited: set[str] = set()
    current = roots[0]
    while current.observation.content_hash not in visited:
        visited.add(current.observation.content_hash)
        successor = successor_by_predecessor.get(current.observation.content_hash)
        if successor is None:
            break
        current = successor
    if len(visited) != len(records):
        raise DjangoPhysicalAccountRowObservationCorruption(
            "physical account-row chain is disconnected or cyclic"
        )
    return current


__all__ = [
    "DjangoPhysicalAccountRowObservationClock",
    "DjangoPhysicalAccountRowObservationConflict",
    "DjangoPhysicalAccountRowObservationCorruption",
    "DjangoPhysicalAccountRowObservationRepository",
    "DjangoPhysicalAccountRowObservationUnavailable",
    "PhysicalAccountRowObservationClock",
]
