"""Closed-world Django repository for allocated Account Physical-v3 roots."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from typing import Protocol, cast

from django.db import IntegrityError, transaction
from django.utils import timezone

from apps.account.application.allocated_physical_account_row_observation_v3 import (
    AllocatedPhysicalAccountRowObservationV3Conflict,
    AllocatedPhysicalAccountRowObservationV3Corruption,
    AllocatedPhysicalAccountRowObservationV3Unavailable,
    PersistedAllocatedPhysicalAccountRowObservationV3,
)
from apps.account.domain.allocated_physical_account_row_observation_v3 import (
    AllocatedPhysicalAccountRowObservationV3,
)
from apps.account.infrastructure.allocated_physical_account_row_observation_v3_codec import (
    AllocatedPhysicalAccountRowObservationV3CodecError,
    decode_allocated_physical_account_row_observation_v3_record,
    encode_allocated_physical_account_row_observation_v3_record,
)
from apps.account.infrastructure.allocated_physical_account_row_observation_v3_models import (
    _ACTIVE_ALLOCATED_PHYSICAL_V3_UOW,
    AllocatedPhysicalAccountRowObservationV3Model,
    _activate_allocated_physical_account_row_observation_v3_uow,
    _claim_allocated_physical_account_row_observation_v3_insert,
)


class DjangoAllocatedPhysicalAccountRowObservationV3Unavailable(
    AllocatedPhysicalAccountRowObservationV3Unavailable
):
    """Allocated Physical-v3 evidence is unavailable at the requested cutoff."""


class DjangoAllocatedPhysicalAccountRowObservationV3Conflict(
    AllocatedPhysicalAccountRowObservationV3Conflict
):
    """A creation-root first-winner or root-only CAS claim conflicted."""


class DjangoAllocatedPhysicalAccountRowObservationV3Corruption(
    AllocatedPhysicalAccountRowObservationV3Corruption
):
    """Persisted creation-root evidence failed closed-world verification."""


class AllocatedPhysicalAccountRowObservationV3Clock(Protocol):
    """Provide the authoritative Account persistence clock."""

    def now(self) -> datetime:
        """Return one timezone-aware server time."""


class DjangoAllocatedPhysicalAccountRowObservationV3Clock:
    """Django timezone-backed production clock."""

    def now(self) -> datetime:
        """Return current Django time."""

        return timezone.now()


class DjangoAllocatedPhysicalAccountRowObservationV3Repository:
    """Private root-only ledger restoring the complete world before selection."""

    __slots__ = ("_clock", "_using", "_uow")

    def __init__(
        self,
        *,
        using: str = "default",
        clock: AllocatedPhysicalAccountRowObservationV3Clock | None = None,
    ) -> None:
        self._using = using
        self._clock = clock or DjangoAllocatedPhysicalAccountRowObservationV3Clock()
        self._uow: object | None = None

    @contextmanager
    def atomic(self) -> Iterator[None]:
        """Open this ledger's non-nestable private append transaction."""

        if self._uow is not None or _ACTIVE_ALLOCATED_PHYSICAL_V3_UOW.get() is not None:
            raise DjangoAllocatedPhysicalAccountRowObservationV3Conflict(
                "nested allocated Physical-v3 UOW is forbidden"
            )
        token = object()
        self._uow = token
        try:
            with (
                transaction.atomic(using=self._using),
                _activate_allocated_physical_account_row_observation_v3_uow(token),
            ):
                yield
        finally:
            self._uow = None

    def now(self) -> datetime:
        """Return the validated authoritative Account server clock."""

        value = self._clock.now()
        if not _is_exact_aware_datetime(value):
            raise DjangoAllocatedPhysicalAccountRowObservationV3Corruption(
                "allocated Physical-v3 repository clock is naive"
            )
        return value

    def get_winner(
        self,
        *,
        observation_id: str,
        observation_version: str,
        as_of: datetime,
    ) -> PersistedAllocatedPhysicalAccountRowObservationV3 | None:
        """Return the immutable identity first winner recorded by the cutoff."""

        _require_token(observation_id, "observation_id")
        _require_token(observation_version, "observation_version")
        self._require_cutoff(as_of)
        records = self._closed_world(lock=False)
        matches = tuple(
            record
            for record in records
            if record.observation.observation_id == observation_id
            and record.observation.observation_version == observation_version
            and record.observation.recorded_at <= as_of
        )
        return _single(matches, "creation-root identity")

    def get_current_head(
        self,
        *,
        allocation_content_hash: str,
        account_namespace: str,
        account_id: str,
        underlying_unified_account_namespace: str,
        underlying_unified_account_id: int,
        physical_content_hash: str,
        as_of: datetime,
    ) -> PersistedAllocatedPhysicalAccountRowObservationV3 | None:
        """Return the one exact root-only logical head, including after expiry."""

        _require_hash(allocation_content_hash, "allocation_content_hash")
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
        _require_hash(physical_content_hash, "physical_content_hash")
        self._require_cutoff(as_of)
        records = self._closed_world(lock=False)
        anchors = tuple(
            record
            for record in records
            if record.observation.recorded_at <= as_of
            and _selector_anchor_overlap(
                record.observation,
                allocation_content_hash=allocation_content_hash,
                account_namespace=account_namespace,
                account_id=account_id,
                underlying_unified_account_namespace=(underlying_unified_account_namespace),
                underlying_unified_account_id=underlying_unified_account_id,
                physical_content_hash=physical_content_hash,
            )
        )
        if len(anchors) > 1:
            raise DjangoAllocatedPhysicalAccountRowObservationV3Corruption(
                "creation-root logical-head anchors disagree"
            )
        if not anchors:
            return None
        record = anchors[0]
        return (
            record
            if _selector_exact_match(
                record.observation,
                allocation_content_hash=allocation_content_hash,
                account_namespace=account_namespace,
                account_id=account_id,
                underlying_unified_account_namespace=(underlying_unified_account_namespace),
                underlying_unified_account_id=underlying_unified_account_id,
                physical_content_hash=physical_content_hash,
            )
            else None
        )

    def append(
        self,
        record: PersistedAllocatedPhysicalAccountRowObservationV3,
        *,
        expected_predecessor_hash: str | None,
        recorded_at: datetime,
    ) -> PersistedAllocatedPhysicalAccountRowObservationV3:
        """Root-CAS append or replay the exact immutable first winner."""

        token = self._require_uow()
        checked = _require_exact_record(record)
        observation = checked.observation
        if expected_predecessor_hash is not None:
            _require_hash(expected_predecessor_hash, "expected_predecessor_hash")
            raise DjangoAllocatedPhysicalAccountRowObservationV3Conflict(
                "allocated Physical-v3 accepts root-only CAS"
            )
        if not _is_exact_aware_datetime(recorded_at):
            raise DjangoAllocatedPhysicalAccountRowObservationV3Conflict(
                "recorded_at must be an exact timezone-aware datetime"
            )
        if recorded_at != observation.recorded_at:
            raise DjangoAllocatedPhysicalAccountRowObservationV3Conflict(
                "persisted_at and creation-root recorded_at must be identical"
            )
        if not observation.is_knowable_at(recorded_at):
            raise DjangoAllocatedPhysicalAccountRowObservationV3Conflict(
                "creation root must be persisted inside its validity window"
            )

        records = self._closed_world(lock=True)
        anchors = tuple(value for value in records if _record_anchor_overlap(value, checked))
        if anchors:
            if len(anchors) == 1 and anchors[0] == checked:
                return anchors[0]
            raise DjangoAllocatedPhysicalAccountRowObservationV3Conflict(
                "creation-root first-winner anchor differs"
            )

        values = _model_values(checked, recorded_at=recorded_at)
        model = AllocatedPhysicalAccountRowObservationV3Model(**values)
        try:
            with transaction.atomic(using=self._using):
                with _claim_allocated_physical_account_row_observation_v3_insert(
                    token=token,
                    model_type=AllocatedPhysicalAccountRowObservationV3Model,
                    expected_values=values,
                ):
                    model.save(force_insert=True, using=self._using)
        except IntegrityError as error:
            records = self._closed_world(lock=True)
            exact = tuple(value for value in records if value == checked)
            if len(exact) == 1:
                return exact[0]
            raise DjangoAllocatedPhysicalAccountRowObservationV3Conflict(
                "concurrent creation-root first winner differs"
            ) from error
        restored = self._restore(model)
        if restored != checked:
            raise DjangoAllocatedPhysicalAccountRowObservationV3Corruption(
                "creation-root append restore mismatch"
            )
        return restored

    def get_exact_by_hash(
        self,
        *,
        observation_id: str,
        observation_version: str,
        expected_content_hash: str,
        as_of: datetime,
    ) -> PersistedAllocatedPhysicalAccountRowObservationV3 | None:
        """Return one exact identity/hash creation root knowable at the cutoff."""

        _require_token(observation_id, "observation_id")
        _require_token(observation_version, "observation_version")
        _require_hash(expected_content_hash, "expected_content_hash")
        self._require_cutoff(as_of)
        records = self._closed_world(lock=False)
        anchors = tuple(
            record
            for record in records
            if (
                record.observation.observation_id == observation_id
                and record.observation.observation_version == observation_version
            )
            or record.observation.content_hash == expected_content_hash
        )
        if len(anchors) > 1:
            raise DjangoAllocatedPhysicalAccountRowObservationV3Corruption(
                "creation-root exact anchors disagree"
            )
        if not anchors:
            return None
        record = anchors[0]
        observation = record.observation
        if (
            observation.observation_id != observation_id
            or observation.observation_version != observation_version
            or observation.content_hash != expected_content_hash
            or not observation.is_knowable_at(as_of)
        ):
            return None
        return record

    def _closed_world(
        self,
        *,
        lock: bool,
    ) -> tuple[PersistedAllocatedPhysicalAccountRowObservationV3, ...]:
        """Restore and cross-check the full table before trusting any header."""

        queryset = AllocatedPhysicalAccountRowObservationV3Model._base_manager.using(
            self._using
        ).all()
        if lock:
            queryset = queryset.select_for_update()
        rows = tuple(queryset.order_by("recorded_at", "pk"))
        records = tuple(self._restore(row) for row in rows)
        for index, left in enumerate(records):
            for right in records[index + 1 :]:
                if _record_anchor_overlap(left, right):
                    raise DjangoAllocatedPhysicalAccountRowObservationV3Corruption(
                        "creation-root closed world has overlapping root anchors"
                    )
        return records

    def _restore(
        self,
        model: AllocatedPhysicalAccountRowObservationV3Model,
    ) -> PersistedAllocatedPhysicalAccountRowObservationV3:
        try:
            record = decode_allocated_physical_account_row_observation_v3_record(
                model.canonical_payload
            )
        except AllocatedPhysicalAccountRowObservationV3CodecError as error:
            raise DjangoAllocatedPhysicalAccountRowObservationV3Corruption(
                "allocated Physical-v3 canonical payload cannot be restored"
            ) from error
        expected = _model_values(
            record,
            recorded_at=record.observation.recorded_at,
        )
        for field_name, value in expected.items():
            if getattr(model, field_name) != value:
                raise DjangoAllocatedPhysicalAccountRowObservationV3Corruption(
                    f"allocated Physical-v3 ledger mismatch: {field_name}"
                )
        if (
            not _is_exact_aware_datetime(model.persisted_at)
            or model.persisted_at != model.recorded_at
            or model.recorded_at != record.observation.recorded_at
        ):
            raise DjangoAllocatedPhysicalAccountRowObservationV3Corruption(
                "allocated Physical-v3 persistence clock is invalid"
            )
        return record

    def _require_uow(self) -> object:
        token = self._uow
        if token is None or _ACTIVE_ALLOCATED_PHYSICAL_V3_UOW.get() is not token:
            raise DjangoAllocatedPhysicalAccountRowObservationV3Conflict(
                "creation-root append requires its active private UOW"
            )
        return token

    def _require_cutoff(self, as_of: datetime) -> None:
        if not _is_exact_aware_datetime(as_of):
            raise DjangoAllocatedPhysicalAccountRowObservationV3Unavailable(
                "creation-root as_of must be an exact timezone-aware datetime"
            )
        if as_of > self.now():
            raise DjangoAllocatedPhysicalAccountRowObservationV3Unavailable(
                "future creation-root as_of is forbidden"
            )


def _require_exact_record(
    value: object,
) -> PersistedAllocatedPhysicalAccountRowObservationV3:
    if type(value) is not PersistedAllocatedPhysicalAccountRowObservationV3:
        raise DjangoAllocatedPhysicalAccountRowObservationV3Corruption(
            "creation-root record type substitution"
        )
    try:
        PersistedAllocatedPhysicalAccountRowObservationV3.__post_init__(value)
    except (TypeError, ValueError) as error:
        raise DjangoAllocatedPhysicalAccountRowObservationV3Corruption(
            "creation-root record is invalid"
        ) from error
    return value


def _is_exact_aware_datetime(value: object) -> bool:
    return type(value) is datetime and value.tzinfo is not None and value.utcoffset() is not None


def _require_token(value: object, field_name: str) -> None:
    if (
        type(value) is not str
        or not value
        or value.strip() != value
        or len(value) > 192
        or any(character.isspace() for character in value)
    ):
        raise DjangoAllocatedPhysicalAccountRowObservationV3Unavailable(
            f"{field_name} must be a bounded canonical token"
        )


def _require_hash(value: object, field_name: str) -> None:
    if (
        type(value) is not str
        or len(value) != 64
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise DjangoAllocatedPhysicalAccountRowObservationV3Unavailable(
            f"{field_name} must be a lowercase SHA-256 digest"
        )


def _require_positive_integer(value: object, field_name: str) -> None:
    if type(value) is not int or value <= 0:
        raise DjangoAllocatedPhysicalAccountRowObservationV3Unavailable(
            f"{field_name} must be an exact positive integer"
        )


def _single(
    records: tuple[PersistedAllocatedPhysicalAccountRowObservationV3, ...],
    label: str,
) -> PersistedAllocatedPhysicalAccountRowObservationV3 | None:
    if len(records) > 1:
        raise DjangoAllocatedPhysicalAccountRowObservationV3Corruption(f"{label} is ambiguous")
    return records[0] if records else None


def _hash(payload: object) -> str:
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


def _identity_claim_hash(
    observation: AllocatedPhysicalAccountRowObservationV3,
) -> str:
    return _hash(
        {
            "claim": "allocated_physical_account_row_observation_v3.identity.v1",
            "observation_id": observation.observation_id,
            "observation_version": observation.observation_version,
            "identity_hash": observation.identity_hash,
        }
    )


def _allocation_claim_hash(
    observation: AllocatedPhysicalAccountRowObservationV3,
) -> str:
    allocation = observation.allocation
    return _hash(
        {
            "claim": "allocated_physical_account_row_observation_v3.allocation.v1",
            "allocation_id": allocation.allocation_id,
            "allocation_version": allocation.allocation_version,
            "allocation_identity_hash": allocation.identity_hash,
            "allocation_content_hash": allocation.content_hash,
        }
    )


def _account_claim_hash(
    observation: AllocatedPhysicalAccountRowObservationV3,
) -> str:
    physical = observation.physical_observation
    return _hash(
        {
            "claim": "allocated_physical_account_row_observation_v3.account.v1",
            "account_namespace": physical.account_namespace,
            "account_id": physical.account_id,
        }
    )


def _underlying_claim_hash(
    observation: AllocatedPhysicalAccountRowObservationV3,
) -> str:
    physical = observation.physical_observation
    return _hash(
        {
            "claim": "allocated_physical_account_row_observation_v3.underlying.v1",
            "underlying_unified_account_namespace": (physical.underlying_unified_account_namespace),
            "underlying_unified_account_id": physical.underlying_unified_account_id,
        }
    )


def _physical_claim_hash(
    observation: AllocatedPhysicalAccountRowObservationV3,
) -> str:
    physical = observation.physical_observation
    return _hash(
        {
            "claim": "allocated_physical_account_row_observation_v3.physical.v1",
            "physical_observation_id": physical.observation_id,
            "physical_observation_version": physical.observation_version,
            "physical_identity_hash": physical.identity_hash,
            "physical_content_hash": physical.content_hash,
        }
    )


def _root_claim_hash(
    observation: AllocatedPhysicalAccountRowObservationV3,
) -> str:
    return _hash(
        {
            "claim": "allocated_physical_account_row_observation_v3.root.v1",
            "identity_claim_hash": _identity_claim_hash(observation),
            "allocation_claim_hash": _allocation_claim_hash(observation),
            "account_claim_hash": _account_claim_hash(observation),
            "underlying_claim_hash": _underlying_claim_hash(observation),
            "physical_claim_hash": _physical_claim_hash(observation),
        }
    )


def _encoded_sections(
    record: PersistedAllocatedPhysicalAccountRowObservationV3,
) -> tuple[dict[str, object], dict[str, object], dict[str, object]]:
    payload = encode_allocated_physical_account_row_observation_v3_record(record)
    observation = cast(dict[str, object], payload["observation"])
    recorder = cast(dict[str, object], payload["recorded_by"])
    return payload, observation, recorder


def _model_values(
    record: PersistedAllocatedPhysicalAccountRowObservationV3,
    *,
    recorded_at: datetime,
) -> dict[str, object]:
    observation = record.observation
    allocation = observation.allocation
    physical = observation.physical_observation
    recorder = record.recorded_by
    payload, encoded_observation, encoded_recorder = _encoded_sections(record)
    identity_claim = _identity_claim_hash(observation)
    allocation_claim = _allocation_claim_hash(observation)
    account_claim = _account_claim_hash(observation)
    underlying_claim = _underlying_claim_hash(observation)
    physical_claim = _physical_claim_hash(observation)
    root_claim = _root_claim_hash(observation)
    allocation_seal = _hash(encoded_observation["allocation"])
    physical_seal = _hash(encoded_observation["physical_observation"])
    projector_seal = _hash(
        {
            "content_hash": observation.content_hash,
            "recorded_by": encoded_recorder,
        }
    )
    fixed_seal = _hash(
        {
            "owner": observation.owner,
            "artifact_type": observation.artifact_type,
            "schema": observation.schema,
            "identity_anchor_kind": observation.identity_anchor_kind,
            "owner_assignment_state": observation.owner_assignment_state,
            "permission": observation.permission,
            "status": observation.status,
        }
    )
    clock_seal = _hash(
        {
            "recorded_at": _time(observation.recorded_at),
            "ttl_valid_until": _time(observation.ttl_valid_until),
            "valid_until": _time(observation.valid_until),
        }
    )
    record_seal = _hash({"record": payload})
    values: dict[str, object] = {
        "owner": observation.owner,
        "artifact_type": observation.artifact_type,
        "schema": observation.schema,
        "observation_id": observation.observation_id,
        "observation_version": observation.observation_version,
        "allocation_id": allocation.allocation_id,
        "allocation_version": allocation.allocation_version,
        "allocation_identity_hash": allocation.identity_hash,
        "allocation_content_hash": allocation.content_hash,
        "account_namespace": physical.account_namespace,
        "account_id": physical.account_id,
        "underlying_unified_account_namespace": (physical.underlying_unified_account_namespace),
        "underlying_unified_account_id": physical.underlying_unified_account_id,
        "physical_observation_id": physical.observation_id,
        "physical_observation_version": physical.observation_version,
        "physical_identity_hash": physical.identity_hash,
        "physical_content_hash": physical.content_hash,
        "recorded_at": recorded_at,
        "ttl_valid_until": observation.ttl_valid_until,
        "valid_until": observation.valid_until,
        "identity_anchor_kind": observation.identity_anchor_kind,
        "owner_assignment_state": observation.owner_assignment_state,
        "permission": observation.permission,
        "status": observation.status,
        "recorded_by_service_id": recorder.service_id,
        "recorded_by_role": recorder.role,
        "recorded_by_kind": recorder.kind,
        "recorded_by_is_automated": recorder.is_automated,
        "canonical_payload": payload,
        "identity_hash": observation.identity_hash,
        "content_hash": observation.content_hash,
        "identity_claim_hash": identity_claim,
        "allocation_claim_hash": allocation_claim,
        "account_claim_hash": account_claim,
        "underlying_claim_hash": underlying_claim,
        "physical_claim_hash": physical_claim,
        "root_claim_hash": root_claim,
        "allocation_binding_seal": allocation_seal,
        "physical_binding_seal": physical_seal,
        "projector_binding_seal": projector_seal,
        "fixed_authority_seal": fixed_seal,
        "clock_seal": clock_seal,
        "record_seal": record_seal,
        "persisted_at": recorded_at,
    }
    values["ledger_seal"] = _hash(
        {
            "identity_claim_hash": identity_claim,
            "allocation_claim_hash": allocation_claim,
            "account_claim_hash": account_claim,
            "underlying_claim_hash": underlying_claim,
            "physical_claim_hash": physical_claim,
            "root_claim_hash": root_claim,
            "allocation_binding_seal": allocation_seal,
            "physical_binding_seal": physical_seal,
            "projector_binding_seal": projector_seal,
            "fixed_authority_seal": fixed_seal,
            "clock_seal": clock_seal,
            "record_seal": record_seal,
            "persisted_at": _time(recorded_at),
        }
    )
    return values


def _record_anchor_overlap(
    left: PersistedAllocatedPhysicalAccountRowObservationV3,
    right: PersistedAllocatedPhysicalAccountRowObservationV3,
) -> bool:
    left_observation = left.observation
    right_observation = right.observation
    left_allocation = left_observation.allocation
    right_allocation = right_observation.allocation
    left_physical = left_observation.physical_observation
    right_physical = right_observation.physical_observation
    return (
        (
            left_observation.observation_id,
            left_observation.observation_version,
        )
        == (
            right_observation.observation_id,
            right_observation.observation_version,
        )
        or left_observation.identity_hash == right_observation.identity_hash
        or left_observation.content_hash == right_observation.content_hash
        or (
            left_allocation.allocation_id,
            left_allocation.allocation_version,
        )
        == (
            right_allocation.allocation_id,
            right_allocation.allocation_version,
        )
        or left_allocation.identity_hash == right_allocation.identity_hash
        or left_allocation.content_hash == right_allocation.content_hash
        or (left_physical.account_namespace, left_physical.account_id)
        == (right_physical.account_namespace, right_physical.account_id)
        or (
            left_physical.underlying_unified_account_namespace,
            left_physical.underlying_unified_account_id,
        )
        == (
            right_physical.underlying_unified_account_namespace,
            right_physical.underlying_unified_account_id,
        )
        or (
            left_physical.observation_id,
            left_physical.observation_version,
        )
        == (
            right_physical.observation_id,
            right_physical.observation_version,
        )
        or left_physical.identity_hash == right_physical.identity_hash
        or left_physical.content_hash == right_physical.content_hash
        or _root_claim_hash(left_observation) == _root_claim_hash(right_observation)
    )


def _selector_anchor_overlap(
    observation: AllocatedPhysicalAccountRowObservationV3,
    *,
    allocation_content_hash: str,
    account_namespace: str,
    account_id: str,
    underlying_unified_account_namespace: str,
    underlying_unified_account_id: int,
    physical_content_hash: str,
) -> bool:
    physical = observation.physical_observation
    return (
        observation.allocation.content_hash == allocation_content_hash
        or (physical.account_namespace, physical.account_id) == (account_namespace, account_id)
        or (
            physical.underlying_unified_account_namespace,
            physical.underlying_unified_account_id,
        )
        == (
            underlying_unified_account_namespace,
            underlying_unified_account_id,
        )
        or physical.content_hash == physical_content_hash
    )


def _selector_exact_match(
    observation: AllocatedPhysicalAccountRowObservationV3,
    *,
    allocation_content_hash: str,
    account_namespace: str,
    account_id: str,
    underlying_unified_account_namespace: str,
    underlying_unified_account_id: int,
    physical_content_hash: str,
) -> bool:
    physical = observation.physical_observation
    return (
        observation.allocation.content_hash == allocation_content_hash
        and (physical.account_namespace, physical.account_id) == (account_namespace, account_id)
        and (
            physical.underlying_unified_account_namespace,
            physical.underlying_unified_account_id,
        )
        == (
            underlying_unified_account_namespace,
            underlying_unified_account_id,
        )
        and physical.content_hash == physical_content_hash
    )


__all__ = [
    "AllocatedPhysicalAccountRowObservationV3Clock",
    "DjangoAllocatedPhysicalAccountRowObservationV3Clock",
    "DjangoAllocatedPhysicalAccountRowObservationV3Conflict",
    "DjangoAllocatedPhysicalAccountRowObservationV3Corruption",
    "DjangoAllocatedPhysicalAccountRowObservationV3Repository",
    "DjangoAllocatedPhysicalAccountRowObservationV3Unavailable",
]
