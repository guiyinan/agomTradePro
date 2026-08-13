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

from apps.account.application.physical_account_row_observation_v2 import (
    PersistedPhysicalAccountRowObservationV2,
    PhysicalAccountRowObservationActor,
    PhysicalAccountRowObservationV2Conflict,
    PhysicalAccountRowObservationV2Corruption,
    PhysicalAccountRowObservationV2Unavailable,
)
from apps.account.domain.physical_account_row_observation_v2 import (
    PhysicalAccountRowObservationV2,
    validate_physical_account_row_observation_v2_successor,
)
from apps.account.infrastructure.physical_account_row_observation_v2_codec import (
    PhysicalAccountRowObservationV2CodecError,
    decode_physical_account_row_observation_v2_record,
    encode_physical_account_row_observation_v2_record,
)
from apps.account.infrastructure.physical_account_row_observation_v2_models import (
    _ACTIVE_ACCOUNT_ROW_V2_UOW,
    PhysicalAccountRowObservationV2Model,
    _activate_physical_account_row_observation_v2_uow,
    _claim_physical_account_row_observation_v2_insert,
)


class DjangoPhysicalAccountRowObservationV2Unavailable(PhysicalAccountRowObservationV2Unavailable):
    """Physical row evidence is unavailable at the requested cutoff."""


class DjangoPhysicalAccountRowObservationV2Conflict(PhysicalAccountRowObservationV2Conflict):
    """A physical-row first-winner or predecessor claim conflicted."""


class DjangoPhysicalAccountRowObservationV2Corruption(PhysicalAccountRowObservationV2Corruption):
    """Persisted physical-row evidence failed closed-world verification."""


class PhysicalAccountRowObservationV2Clock(Protocol):
    """Provide the authoritative Account persistence clock."""

    def now(self) -> datetime:
        """Return one timezone-aware server time."""


class DjangoPhysicalAccountRowObservationV2Clock:
    """Django timezone-backed production clock."""

    def now(self) -> datetime:
        """Return current Django time."""

        return timezone.now()


class DjangoPhysicalAccountRowObservationV2Repository:
    """Private first-winner ledger with full-table closed-world restore."""

    __slots__ = ("_clock", "_using")

    def __init__(
        self,
        *,
        using: str = "default",
        clock: PhysicalAccountRowObservationV2Clock | None = None,
    ) -> None:
        self._using = using
        self._clock = clock or DjangoPhysicalAccountRowObservationV2Clock()

    @contextmanager
    def atomic(self) -> Iterator[None]:
        """Open this ledger's independent private append transaction."""

        token = object()
        with (
            transaction.atomic(using=self._using),
            _activate_physical_account_row_observation_v2_uow(token),
        ):
            yield

    def now(self) -> datetime:
        """Return the validated authoritative Account server clock."""

        value = self._clock.now()
        _require_aware(value, "physical account-row v2 clock")
        return value

    def append(
        self,
        record: PersistedPhysicalAccountRowObservationV2,
        *,
        expected_predecessor_hash: str | None,
        recorded_at: datetime,
    ) -> PersistedPhysicalAccountRowObservationV2:
        """CAS-append or return the exact immutable first winner."""

        token = _active_token()
        checked = _require_exact_record(record)
        observation = checked.observation
        _require_aware(recorded_at, "recorded_at")
        if observation.recorded_at != recorded_at:
            raise DjangoPhysicalAccountRowObservationV2Conflict(
                "persisted_at and observation recorded_at must be identical"
            )
        if observation.supersedes_content_hash != expected_predecessor_hash:
            raise DjangoPhysicalAccountRowObservationV2Conflict(
                "physical account-row v2 does not bind the expected predecessor"
            )
        if not observation.is_knowable_at(recorded_at):
            raise DjangoPhysicalAccountRowObservationV2Conflict(
                "physical account-row v2 must be persisted inside its validity window"
            )
        existing = self._exact_model(checked)
        if existing is not None:
            return self._restore(existing)
        current = self._current_head(
            account_namespace=observation.account_namespace,
            account_id=observation.account_id,
            underlying_unified_account_namespace=(observation.underlying_unified_account_namespace),
            underlying_unified_account_id=observation.underlying_unified_account_id,
            source_id=observation.source_id,
            as_of=recorded_at,
            lock=True,
        )
        actual_predecessor = current.observation.content_hash if current is not None else None
        if actual_predecessor != expected_predecessor_hash:
            raise DjangoPhysicalAccountRowObservationV2Conflict(
                "physical account-row v2 predecessor CAS conflict"
            )
        if current is not None:
            try:
                validate_physical_account_row_observation_v2_successor(
                    current.observation,
                    observation,
                )
            except (TypeError, ValueError) as error:
                raise DjangoPhysicalAccountRowObservationV2Conflict(
                    "physical account-row v2 successor is invalid"
                ) from error
        values = _model_values(checked, recorded_at=recorded_at)
        model = PhysicalAccountRowObservationV2Model(**values)
        try:
            with transaction.atomic(using=self._using):
                with _claim_physical_account_row_observation_v2_insert(
                    token=token,
                    model_type=PhysicalAccountRowObservationV2Model,
                    expected_values=values,
                ):
                    model.save(force_insert=True, using=self._using)
        except IntegrityError as error:
            winner = self._exact_model(checked)
            if winner is None:
                raise DjangoPhysicalAccountRowObservationV2Conflict(
                    "physical-row append conflicted without an exact visible first winner"
                ) from error
            return self._restore(winner)
        return self._restore(model)

    def get_winner(
        self,
        *,
        observation_id: str,
        observation_version: str,
        as_of: datetime,
    ) -> PersistedPhysicalAccountRowObservationV2 | None:
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
            raise DjangoPhysicalAccountRowObservationV2Corruption(
                "physical account-row v2 first winner is ambiguous"
            )
        return matches[0]

    def get_exact_by_hash(
        self,
        *,
        observation_id: str,
        observation_version: str,
        expected_content_hash: str,
        as_of: datetime,
    ) -> PersistedPhysicalAccountRowObservationV2 | None:
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
            raise DjangoPhysicalAccountRowObservationV2Corruption(
                "physical account-row v2 exact anchors are ambiguous"
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
        source_id: str,
        as_of: datetime,
    ) -> PersistedPhysicalAccountRowObservationV2 | None:
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
        _require_token(source_id, "source_id")
        self._require_cutoff(as_of)
        return self._current_head(
            account_namespace=account_namespace,
            account_id=account_id,
            underlying_unified_account_namespace=(underlying_unified_account_namespace),
            underlying_unified_account_id=underlying_unified_account_id,
            source_id=source_id,
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
        source_id: str,
        as_of: datetime,
        lock: bool,
    ) -> PersistedPhysicalAccountRowObservationV2 | None:
        records = self._visible_records(as_of=as_of, lock=lock)
        chain = tuple(
            record
            for record in records
            if record.observation.account_namespace == account_namespace
            and record.observation.account_id == account_id
            and record.observation.underlying_unified_account_namespace
            == underlying_unified_account_namespace
            and record.observation.underlying_unified_account_id == underlying_unified_account_id
            and record.observation.source_id == source_id
        )
        return _restore_full_chain(chain) if chain else None

    def _visible_records(
        self,
        *,
        as_of: datetime,
        lock: bool,
    ) -> tuple[PersistedPhysicalAccountRowObservationV2, ...]:
        """Restore the full table before trusting any selector header."""

        queryset = PhysicalAccountRowObservationV2Model._default_manager.using(self._using).all()
        if lock:
            queryset = queryset.select_for_update()
        rows = list(queryset.order_by("recorded_at", "pk"))
        restored = tuple(self._restore(row) for row in rows)
        return tuple(record for record in restored if record.observation.recorded_at <= as_of)

    def _require_cutoff(self, as_of: datetime) -> None:
        _require_aware(as_of, "physical account-row v2 as_of")
        if as_of > self.now():
            raise DjangoPhysicalAccountRowObservationV2Unavailable(
                "future physical account-row v2 as_of is forbidden"
            )

    def _exact_model(
        self,
        record: PersistedPhysicalAccountRowObservationV2,
    ) -> PhysicalAccountRowObservationV2Model | None:
        observation = record.observation
        root_claim = _root_claim_hash(observation)
        source_binding = _source_binding_seal(observation)
        actor_binding = _actor_binding_seal(record)
        rows = list(PhysicalAccountRowObservationV2Model._default_manager.using(self._using).all())
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
                    row.source_binding_seal == source_binding
                    and value.observation.source_id == observation.source_id
                    and value.observation.source_version == observation.source_version
                )
                or (
                    row.raw_binding_seal == _raw_binding_seal(observation)
                    and value.observation.raw_observation_id == observation.raw_observation_id
                    and value.observation.raw_observation_version
                    == observation.raw_observation_version
                )
                or (
                    row.actor_binding_seal == actor_binding
                    and value.observation.content_hash == observation.content_hash
                )
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
            raise DjangoPhysicalAccountRowObservationV2Conflict(
                "physical-row uniqueness or logical-chain claim has another first winner"
            )
        return matches[0]

    def _restore(
        self,
        model: PhysicalAccountRowObservationV2Model,
    ) -> PersistedPhysicalAccountRowObservationV2:
        try:
            record = decode_physical_account_row_observation_v2_record(model.canonical_payload)
        except PhysicalAccountRowObservationV2CodecError as error:
            raise DjangoPhysicalAccountRowObservationV2Corruption(
                "physical account-row v2 canonical payload cannot be restored"
            ) from error
        observation = record.observation
        if _record_headers(record) != _model_headers(model):
            raise DjangoPhysicalAccountRowObservationV2Corruption(
                "physical account-row v2 headers do not match canonical payload"
            )
        expected_root = (
            _root_claim_hash(observation) if observation.supersedes_content_hash is None else None
        )
        if model.root_claim_hash != expected_root:
            raise DjangoPhysicalAccountRowObservationV2Corruption(
                "physical account-row v2 root claim is invalid"
            )
        if model.row_seal != _row_seal(observation):
            raise DjangoPhysicalAccountRowObservationV2Corruption(
                "physical account-row v2 raw row seal is invalid"
            )
        if model.source_binding_seal != _source_binding_seal(observation):
            raise DjangoPhysicalAccountRowObservationV2Corruption(
                "physical account-row v2 source binding seal is invalid"
            )
        if model.raw_binding_seal != _raw_binding_seal(observation):
            raise DjangoPhysicalAccountRowObservationV2Corruption(
                "physical account-row v2 raw binding seal is invalid"
            )
        if model.clock_seal != _clock_seal(observation):
            raise DjangoPhysicalAccountRowObservationV2Corruption(
                "physical account-row v2 clock seal is invalid"
            )
        if model.actor_binding_seal != _actor_binding_seal(record):
            raise DjangoPhysicalAccountRowObservationV2Corruption(
                "physical account-row v2 actor binding seal is invalid"
            )
        if model.record_seal != _record_seal(record):
            raise DjangoPhysicalAccountRowObservationV2Corruption(
                "physical account-row v2 record header seal is invalid"
            )
        if model.ledger_seal != _ledger_seal(
            record,
            recorded_at=model.recorded_at,
        ):
            raise DjangoPhysicalAccountRowObservationV2Corruption(
                "physical account-row v2 ledger header seal is invalid"
            )
        if (
            model.persisted_at.tzinfo is None
            or model.persisted_at.utcoffset() is None
            or model.persisted_at != model.recorded_at
            or model.recorded_at != observation.recorded_at
        ):
            raise DjangoPhysicalAccountRowObservationV2Corruption(
                "physical account-row v2 persistence clock is invalid"
            )
        return record


def _active_token() -> object:
    token = _ACTIVE_ACCOUNT_ROW_V2_UOW.get()
    if token is None:
        raise DjangoPhysicalAccountRowObservationV2Conflict(
            "physical-row append requires an active private unit of work"
        )
    return token


def _require_exact_record(value: object) -> PersistedPhysicalAccountRowObservationV2:
    if type(value) is not PersistedPhysicalAccountRowObservationV2:
        raise DjangoPhysicalAccountRowObservationV2Corruption(
            "physical account-row v2 record type substitution"
        )
    PersistedPhysicalAccountRowObservationV2.__post_init__(value)
    return value


def _require_aware(value: object, field_name: str) -> None:
    if type(value) is not datetime or value.tzinfo is None or value.utcoffset() is None:
        raise DjangoPhysicalAccountRowObservationV2Unavailable(
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
        raise DjangoPhysicalAccountRowObservationV2Unavailable(
            f"{field_name} must be a bounded canonical token"
        )


def _require_hash(value: object, field_name: str) -> None:
    if (
        type(value) is not str
        or len(value) != 64
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise DjangoPhysicalAccountRowObservationV2Unavailable(
            f"{field_name} must be a lowercase SHA-256 digest"
        )


def _require_positive_integer(value: object, field_name: str) -> None:
    if type(value) is not int or value <= 0:
        raise DjangoPhysicalAccountRowObservationV2Unavailable(
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


def _root_claim_hash(observation: PhysicalAccountRowObservationV2) -> str:
    return _hash_payload(
        {
            "account_namespace": observation.account_namespace,
            "account_id": observation.account_id,
            "underlying_unified_account_namespace": (
                observation.underlying_unified_account_namespace
            ),
            "underlying_unified_account_id": (observation.underlying_unified_account_id),
            "source_id": observation.source_id,
        }
    )


def _row_seal(observation: PhysicalAccountRowObservationV2) -> str:
    return _hash_payload(
        {
            "account_namespace": observation.account_namespace,
            "account_id": observation.account_id,
            "underlying_unified_account_namespace": (
                observation.underlying_unified_account_namespace
            ),
            "underlying_unified_account_id": (observation.underlying_unified_account_id),
            "row_user_id": observation.row_user_id,
            "raw_account_type": observation.raw_account_type,
            "is_active": observation.is_active,
            "is_present": observation.is_present,
            "is_tombstone": observation.is_tombstone,
            "row_created_at": _time(observation.row_created_at),
            "row_updated_at": _time(observation.row_updated_at),
            "source_observed_at": _time(observation.source_observed_at),
        }
    )


def _source_binding_seal(observation: PhysicalAccountRowObservationV2) -> str:
    return _hash_payload(
        {
            "source_owner": observation.source_owner,
            "source_artifact_type": observation.source_artifact_type,
            "source_schema": observation.source_schema,
            "source_id": observation.source_id,
            "source_version": observation.source_version,
            "source_identity_hash": observation.source_identity_hash,
            "source_content_hash": observation.source_content_hash,
            "source_supersedes_content_hash": (observation.source_supersedes_content_hash),
            "source_observed_at": _time(observation.source_observed_at),
            "source_recorded_at": _time(observation.source_recorded_at),
            "source_valid_until": _time(observation.source_valid_until),
            "source_ttl_valid_until": _time(observation.source_ttl_valid_until),
            "source_effective_valid_until": _time(observation.source_effective_valid_until),
            "row_seal": _row_seal(observation),
        }
    )


def _raw_binding_seal(observation: PhysicalAccountRowObservationV2) -> str:
    return _hash_payload(
        {
            "raw_observation_owner": observation.raw_observation_owner,
            "raw_observation_artifact_type": observation.raw_observation_artifact_type,
            "raw_observation_schema": observation.raw_observation_schema,
            "raw_observation_id": observation.raw_observation_id,
            "raw_observation_version": observation.raw_observation_version,
            "raw_observation_identity_hash": observation.raw_observation_identity_hash,
            "raw_observation_content_hash": observation.raw_observation_content_hash,
            "raw_observation_supersedes_content_hash": (
                observation.raw_observation_supersedes_content_hash
            ),
            "raw_observation_observed_at": _time(observation.raw_observation_observed_at),
            "raw_observation_valid_until": _time(observation.raw_observation_valid_until),
            "row_seal": _row_seal(observation),
        }
    )


def _clock_seal(observation: PhysicalAccountRowObservationV2) -> str:
    return _hash_payload(
        {
            "source_observed_at": _time(observation.source_observed_at),
            "source_recorded_at": _time(observation.source_recorded_at),
            "recorded_at": _time(observation.recorded_at),
            "source_valid_until": _time(observation.source_valid_until),
            "source_ttl_valid_until": _time(observation.source_ttl_valid_until),
            "source_effective_valid_until": _time(observation.source_effective_valid_until),
            "raw_observation_observed_at": _time(observation.raw_observation_observed_at),
            "raw_observation_valid_until": _time(observation.raw_observation_valid_until),
            "ttl_valid_until": _time(observation.ttl_valid_until),
            "valid_until": _time(observation.valid_until),
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


def _actor_binding_seal(record: PersistedPhysicalAccountRowObservationV2) -> str:
    return _hash_payload(
        {
            "content_hash": record.observation.content_hash,
            "captured_by": _actor_payload(record.captured_by),
        }
    )


def _record_seal(record: PersistedPhysicalAccountRowObservationV2) -> str:
    return _hash_payload({"record": encode_physical_account_row_observation_v2_record(record)})


def _ledger_seal(
    record: PersistedPhysicalAccountRowObservationV2,
    *,
    recorded_at: datetime,
) -> str:
    observation = record.observation
    return _hash_payload(
        {
            "record_seal": _record_seal(record),
            "root_claim_hash": (
                _root_claim_hash(observation)
                if observation.supersedes_content_hash is None
                else None
            ),
            "row_seal": _row_seal(observation),
            "source_binding_seal": _source_binding_seal(observation),
            "raw_binding_seal": _raw_binding_seal(observation),
            "clock_seal": _clock_seal(observation),
            "actor_binding_seal": _actor_binding_seal(record),
            "persisted_at": _time(recorded_at),
        }
    )


def _model_values(
    record: PersistedPhysicalAccountRowObservationV2,
    *,
    recorded_at: datetime,
) -> dict[str, object]:
    observation = record.observation
    actor = record.captured_by
    values: dict[str, object] = {
        name: getattr(observation, name)
        for name in _OBSERVATION_HEADER_NAMES
        if name != "recorded_at"
    }
    values.update(
        {
            "recorded_at": recorded_at,
            "root_claim_hash": (
                _root_claim_hash(observation)
                if observation.supersedes_content_hash is None
                else None
            ),
            "captured_actor_id": actor.actor_id,
            "captured_actor_user_id": actor.user_id,
            "captured_actor_role": actor.role,
            "captured_actor_kind": actor.kind,
            "captured_actor_is_staff": actor.is_staff,
            "canonical_payload": encode_physical_account_row_observation_v2_record(record),
            "row_seal": _row_seal(observation),
            "source_binding_seal": _source_binding_seal(observation),
            "raw_binding_seal": _raw_binding_seal(observation),
            "clock_seal": _clock_seal(observation),
            "actor_binding_seal": _actor_binding_seal(record),
            "record_seal": _record_seal(record),
            "ledger_seal": _ledger_seal(
                record,
                recorded_at=recorded_at,
            ),
            "persisted_at": recorded_at,
        }
    )
    return values


def _record_headers(
    record: PersistedPhysicalAccountRowObservationV2,
) -> tuple[object, ...]:
    observation = record.observation
    actor = record.captured_by
    return tuple(getattr(observation, name) for name in _OBSERVATION_HEADER_NAMES) + (
        actor.actor_id,
        actor.user_id,
        actor.role,
        actor.kind,
        actor.is_staff,
    )


def _model_headers(
    model: PhysicalAccountRowObservationV2Model,
) -> tuple[object, ...]:
    return tuple(getattr(model, name) for name in _OBSERVATION_HEADER_NAMES) + (
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
    "source_owner",
    "source_artifact_type",
    "source_schema",
    "source_id",
    "source_version",
    "source_identity_hash",
    "source_content_hash",
    "source_supersedes_content_hash",
    "row_user_id",
    "raw_account_type",
    "is_active",
    "is_present",
    "is_tombstone",
    "row_created_at",
    "row_updated_at",
    "source_observed_at",
    "source_recorded_at",
    "source_valid_until",
    "source_ttl_valid_until",
    "raw_observation_owner",
    "raw_observation_artifact_type",
    "raw_observation_schema",
    "raw_observation_id",
    "raw_observation_version",
    "raw_observation_identity_hash",
    "raw_observation_content_hash",
    "raw_observation_supersedes_content_hash",
    "raw_observation_observed_at",
    "raw_observation_valid_until",
    "recorded_at",
    "source_effective_valid_until",
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
    records: tuple[PersistedPhysicalAccountRowObservationV2, ...],
) -> PersistedPhysicalAccountRowObservationV2:
    by_hash = {record.observation.content_hash: record for record in records}
    if len(by_hash) != len(records):
        raise DjangoPhysicalAccountRowObservationV2Corruption(
            "physical account-row v2 chain has duplicate content"
        )
    roots = tuple(
        record for record in records if record.observation.supersedes_content_hash is None
    )
    if len(roots) != 1:
        raise DjangoPhysicalAccountRowObservationV2Corruption(
            "physical account-row v2 chain must have exactly one visible root"
        )
    successor_by_predecessor: dict[str, PersistedPhysicalAccountRowObservationV2] = {}
    for record in records:
        predecessor_hash = record.observation.supersedes_content_hash
        if predecessor_hash is None:
            continue
        predecessor = by_hash.get(predecessor_hash)
        if predecessor is None:
            raise DjangoPhysicalAccountRowObservationV2Corruption(
                "physical account-row v2 predecessor is missing at cutoff"
            )
        if predecessor_hash in successor_by_predecessor:
            raise DjangoPhysicalAccountRowObservationV2Corruption(
                "physical account-row v2 predecessor has multiple successors"
            )
        try:
            validate_physical_account_row_observation_v2_successor(
                predecessor.observation,
                record.observation,
            )
        except (TypeError, ValueError) as error:
            raise DjangoPhysicalAccountRowObservationV2Corruption(
                "physical account-row v2 successor link is invalid"
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
        raise DjangoPhysicalAccountRowObservationV2Corruption(
            "physical account-row v2 chain is disconnected or cyclic"
        )
    return current


__all__ = [
    "DjangoPhysicalAccountRowObservationV2Clock",
    "DjangoPhysicalAccountRowObservationV2Conflict",
    "DjangoPhysicalAccountRowObservationV2Corruption",
    "DjangoPhysicalAccountRowObservationV2Repository",
    "DjangoPhysicalAccountRowObservationV2Unavailable",
    "PhysicalAccountRowObservationV2Clock",
]
