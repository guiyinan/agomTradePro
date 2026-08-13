"""Closed-world Django repository for canonical Account creation evidence."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from typing import Protocol, TypeVar

from django.db import IntegrityError, transaction
from django.utils import timezone

from apps.account.application.canonical_account_creation import (
    CanonicalAccountCreationConflict,
    CanonicalAccountCreationCorruption,
    CanonicalAccountCreationUnavailable,
)
from apps.account.domain.canonical_account_creation import (
    CanonicalAccountCreationAllocation,
    CanonicalAccountCreationBinding,
)
from apps.account.infrastructure.canonical_account_creation_codec import (
    CanonicalAccountCreationCodecError,
    decode_canonical_account_creation_allocation,
    decode_canonical_account_creation_binding,
    encode_canonical_account_creation_allocation,
    encode_canonical_account_creation_binding,
)
from apps.account.infrastructure.canonical_account_creation_models import (
    CanonicalAccountCreationAllocationModel,
    CanonicalAccountCreationBindingModel,
    _activate_canonical_account_creation_uow,
    _claim_canonical_account_creation_insert,
)


class CanonicalAccountCreationClock(Protocol):
    """Provide the authoritative persistence clock."""

    def now(self) -> datetime: ...


class DjangoCanonicalAccountCreationClock:
    """Django timezone-backed production clock."""

    def now(self) -> datetime:
        """Return one aware server timestamp."""

        return timezone.now()


_ValueT = TypeVar("_ValueT")


class DjangoCanonicalAccountCreationRepository:
    """Restore the complete two-table world before every selection or append."""

    def __init__(
        self, *, clock: CanonicalAccountCreationClock | None = None, using: str = "default"
    ) -> None:
        self._clock = clock or DjangoCanonicalAccountCreationClock()
        self._using = using
        self._uow: object | None = None

    @contextmanager
    def atomic(self) -> Iterator[None]:
        """Open one non-nestable private append transaction."""

        if self._uow is not None:
            raise CanonicalAccountCreationConflict("nested canonical creation UOW")
        token = object()
        self._uow = token
        try:
            with (
                transaction.atomic(using=self._using),
                _activate_canonical_account_creation_uow(token),
            ):
                yield
        finally:
            self._uow = None

    def now(self) -> datetime:
        """Return the validated authoritative repository clock."""

        value = self._clock.now()
        if type(value) is not datetime or value.tzinfo is None or value.utcoffset() is None:
            raise CanonicalAccountCreationCorruption("repository clock is naive")
        return value

    def get_allocation_winner(
        self, *, allocation_id: str, allocation_version: str, as_of: datetime
    ) -> CanonicalAccountCreationAllocation | None:
        """Return the immutable identity winner knowable at the cutoff."""

        self._cutoff(as_of)
        allocations, _ = self._closed_world(lock=False)
        matches = tuple(
            value
            for _, value in allocations
            if value.allocation_id == allocation_id
            and value.allocation_version == allocation_version
            and value.allocated_at <= as_of
        )
        return self._single(matches, "allocation identity")

    def get_allocation_by_request(
        self,
        *,
        requester_actor_id: str,
        requester_user_id: int,
        request_fingerprint_hash: str,
        as_of: datetime,
    ) -> CanonicalAccountCreationAllocation | None:
        """Return the request first winner without substituting another user or actor."""

        self._cutoff(as_of)
        allocations, _ = self._closed_world(lock=False)
        matches = tuple(
            value
            for _, value in allocations
            if value.requested_by.actor_id == requester_actor_id
            and value.requested_by.user_id == requester_user_id
            and value.request_fingerprint_hash == request_fingerprint_hash
            and value.allocated_at <= as_of
        )
        return self._single(matches, "allocation request")

    def get_exact_allocation(
        self,
        *,
        allocation_id: str,
        allocation_version: str,
        expected_content_hash: str,
        as_of: datetime,
    ) -> CanonicalAccountCreationAllocation | None:
        """Return only the exact immutable allocation knowable at the cutoff."""

        self._cutoff(as_of)
        allocations, _ = self._closed_world(lock=False)
        anchors = tuple(
            value
            for _, value in allocations
            if (
                value.allocation_id == allocation_id
                and value.allocation_version == allocation_version
            )
            or value.content_hash == expected_content_hash
        )
        matches = tuple(
            value
            for value in anchors
            if value.allocation_id == allocation_id
            and value.allocation_version == allocation_version
            and value.content_hash == expected_content_hash
            and value.allocated_at <= as_of
        )
        if anchors and (len(anchors) != 1 or len(matches) > 1):
            raise CanonicalAccountCreationCorruption("allocation exact anchors disagree")
        return matches[0] if matches else None

    def get_current_unconsumed_allocation(
        self,
        *,
        allocation_id: str,
        allocation_version: str,
        expected_content_hash: str,
        as_of: datetime,
    ) -> CanonicalAccountCreationAllocation | None:
        """Return a live exact allocation only while no binding has consumed it."""

        self._cutoff(as_of)
        allocations, bindings = self._closed_world(lock=False)
        exact = self._exact_from_world(
            allocations,
            allocation_id=allocation_id,
            allocation_version=allocation_version,
            expected_content_hash=expected_content_hash,
            as_of=as_of,
        )
        if exact is None or not exact.allocated_at <= as_of < exact.valid_until:
            return None
        if any(value.allocation.content_hash == exact.content_hash for _, value in bindings):
            return None
        return exact

    def append_allocation(
        self, allocation: CanonicalAccountCreationAllocation, *, recorded_at: datetime
    ) -> CanonicalAccountCreationAllocation:
        """Append or replay one exact allocation first winner."""

        checked = _allocation(allocation)
        self._require_uow()
        _aware(recorded_at, "recorded_at")
        if recorded_at != checked.allocated_at:
            raise CanonicalAccountCreationConflict("allocation persistence clock differs")
        allocations, _ = self._closed_world(lock=True)
        anchors = tuple(
            value for _, value in allocations if _allocation_anchor_overlap(value, checked)
        )
        if anchors:
            if len(anchors) == 1 and anchors[0] == checked:
                return anchors[0]
            raise CanonicalAccountCreationConflict("allocation first-winner anchor differs")
        values = _allocation_values(checked)
        try:
            with transaction.atomic(using=self._using):
                self._insert(CanonicalAccountCreationAllocationModel, values)
        except IntegrityError as error:
            allocations, _ = self._closed_world(lock=True)
            exact = tuple(value for _, value in allocations if value == checked)
            if len(exact) == 1:
                return exact[0]
            raise CanonicalAccountCreationConflict("concurrent allocation first winner") from error
        restored = self.get_allocation_winner(
            allocation_id=checked.allocation_id,
            allocation_version=checked.allocation_version,
            as_of=recorded_at,
        )
        if restored != checked:
            raise CanonicalAccountCreationCorruption("allocation restore mismatch")
        return restored

    def get_binding_winner(
        self, *, binding_id: str, binding_version: str, as_of: datetime
    ) -> CanonicalAccountCreationBinding | None:
        """Return the immutable binding identity winner knowable at the cutoff."""

        self._cutoff(as_of)
        _, bindings = self._closed_world(lock=False)
        matches = tuple(
            value
            for _, value in bindings
            if value.binding_id == binding_id
            and value.binding_version == binding_version
            and value.recorded_at <= as_of
        )
        return self._single(matches, "binding identity")

    def get_binding_by_any_anchor(
        self,
        *,
        allocation_content_hash: str,
        account_namespace: str,
        account_id: str,
        underlying_unified_account_namespace: str,
        underlying_unified_account_id: int,
        physical_content_hash: str,
        as_of: datetime,
    ) -> CanonicalAccountCreationBinding | None:
        """Find consumption by any of the four independently unique anchors."""

        self._cutoff(as_of)
        _, bindings = self._closed_world(lock=False)
        matches = tuple(
            value
            for _, value in bindings
            if value.recorded_at <= as_of
            and (
                value.allocation.content_hash == allocation_content_hash
                or (
                    value.account_namespace_claim == account_namespace
                    and value.account_id_claim == account_id
                )
                or (
                    value.underlying_unified_account_namespace_claim
                    == underlying_unified_account_namespace
                    and value.underlying_unified_account_id_claim == underlying_unified_account_id
                )
                or value.physical_observation.content_hash == physical_content_hash
            )
        )
        return self._single(matches, "binding anchors")

    def get_exact_binding(
        self,
        *,
        binding_id: str,
        binding_version: str,
        expected_content_hash: str,
        as_of: datetime,
    ) -> CanonicalAccountCreationBinding | None:
        """Return only an exact immutable binding knowable at the cutoff."""

        self._cutoff(as_of)
        _, bindings = self._closed_world(lock=False)
        anchors = tuple(
            value
            for _, value in bindings
            if (value.binding_id == binding_id and value.binding_version == binding_version)
            or value.content_hash == expected_content_hash
        )
        matches = tuple(
            value
            for value in anchors
            if value.binding_id == binding_id
            and value.binding_version == binding_version
            and value.content_hash == expected_content_hash
            and value.recorded_at <= as_of
        )
        if anchors and (len(anchors) != 1 or len(matches) > 1):
            raise CanonicalAccountCreationCorruption("binding exact anchors disagree")
        return matches[0] if matches else None

    def append_binding(
        self,
        binding: CanonicalAccountCreationBinding,
        *,
        expected_allocation_content_hash: str,
        expected_account_claim_hash: str,
        expected_underlying_claim_hash: str,
        expected_physical_content_hash: str,
        recorded_at: datetime,
    ) -> CanonicalAccountCreationBinding:
        """Consume a current allocation under all four exact database anchors."""

        checked = _binding(binding)
        self._require_uow()
        _aware(recorded_at, "recorded_at")
        if recorded_at != checked.recorded_at:
            raise CanonicalAccountCreationConflict("binding persistence clock differs")
        expected = (
            expected_allocation_content_hash,
            expected_account_claim_hash,
            expected_underlying_claim_hash,
            expected_physical_content_hash,
        )
        actual = (
            checked.allocation.content_hash,
            checked.account_claim_hash,
            checked.underlying_claim_hash,
            checked.physical_observation.content_hash,
        )
        if actual != expected:
            raise CanonicalAccountCreationConflict("binding append anchors differ")
        allocations, bindings = self._closed_world(lock=True)
        allocation_rows = tuple(
            (row, value)
            for row, value in allocations
            if value.content_hash == checked.allocation.content_hash
        )
        if len(allocation_rows) != 1 or allocation_rows[0][1] != checked.allocation:
            raise CanonicalAccountCreationConflict("binding allocation is not exact")
        if not checked.allocation.allocated_at <= recorded_at < checked.allocation.valid_until:
            raise CanonicalAccountCreationConflict("binding allocation is expired")
        anchors = tuple(value for _, value in bindings if _binding_anchor_overlap(value, checked))
        if anchors:
            if len(anchors) == 1 and anchors[0] == checked:
                return anchors[0]
            raise CanonicalAccountCreationConflict("binding first-winner anchor differs")
        values = _binding_values(checked, allocation_pk=allocation_rows[0][0].pk)
        try:
            with transaction.atomic(using=self._using):
                self._insert(CanonicalAccountCreationBindingModel, values)
        except IntegrityError as error:
            _, bindings = self._closed_world(lock=True)
            exact = tuple(value for _, value in bindings if value == checked)
            if len(exact) == 1:
                return exact[0]
            raise CanonicalAccountCreationConflict("concurrent binding first winner") from error
        restored = self.get_binding_winner(
            binding_id=checked.binding_id,
            binding_version=checked.binding_version,
            as_of=recorded_at,
        )
        if restored != checked:
            raise CanonicalAccountCreationCorruption("binding restore mismatch")
        return restored

    def _closed_world(self, *, lock: bool) -> tuple[
        tuple[
            tuple[CanonicalAccountCreationAllocationModel, CanonicalAccountCreationAllocation], ...
        ],
        tuple[tuple[CanonicalAccountCreationBindingModel, CanonicalAccountCreationBinding], ...],
    ]:
        allocation_query = CanonicalAccountCreationAllocationModel._base_manager.using(
            self._using
        ).all()
        if lock:
            allocation_query = allocation_query.select_for_update()
        allocations = tuple(
            (row, _restore_allocation(row)) for row in allocation_query.order_by("pk")
        )
        by_pk = {row.pk: value for row, value in allocations if row.pk is not None}
        binding_query = CanonicalAccountCreationBindingModel._base_manager.using(self._using).all()
        if lock:
            binding_query = binding_query.select_for_update()
        bindings: list[
            tuple[CanonicalAccountCreationBindingModel, CanonicalAccountCreationBinding]
        ] = []
        used_allocations: set[int] = set()
        for row in binding_query.order_by("pk"):
            allocation = by_pk.get(row.allocation_id)
            if allocation is None or row.allocation_id in used_allocations:
                raise CanonicalAccountCreationCorruption(
                    "binding allocation OneToOne is orphaned or duplicated"
                )
            value = _restore_binding(row, allocation)
            used_allocations.add(row.allocation_id)
            bindings.append((row, value))
        return allocations, tuple(bindings)

    def _exact_from_world(
        self,
        allocations: tuple[
            tuple[CanonicalAccountCreationAllocationModel, CanonicalAccountCreationAllocation], ...
        ],
        *,
        allocation_id: str,
        allocation_version: str,
        expected_content_hash: str,
        as_of: datetime,
    ) -> CanonicalAccountCreationAllocation | None:
        anchors = tuple(
            value
            for _, value in allocations
            if (
                value.allocation_id == allocation_id
                and value.allocation_version == allocation_version
            )
            or value.content_hash == expected_content_hash
        )
        matches = tuple(
            value
            for value in anchors
            if value.allocation_id == allocation_id
            and value.allocation_version == allocation_version
            and value.content_hash == expected_content_hash
            and value.allocated_at <= as_of
        )
        if anchors and (len(anchors) != 1 or len(matches) > 1):
            raise CanonicalAccountCreationCorruption("allocation exact anchors disagree")
        return matches[0] if matches else None

    def _insert(
        self,
        model_type: (
            type[CanonicalAccountCreationAllocationModel]
            | type[CanonicalAccountCreationBindingModel]
        ),
        values: dict[str, object],
    ) -> None:
        token = self._require_uow()
        with _claim_canonical_account_creation_insert(
            token=token, model_type=model_type, expected_values=values
        ):
            model_type._default_manager.using(self._using).create(**values)

    def _require_uow(self) -> object:
        if self._uow is None:
            raise CanonicalAccountCreationConflict("append requires private UOW")
        return self._uow

    def _cutoff(self, as_of: datetime) -> None:
        _aware(as_of, "as_of")
        if as_of > self.now():
            raise CanonicalAccountCreationUnavailable("future as_of is forbidden")

    @staticmethod
    def _single(values: tuple[_ValueT, ...], label: str) -> _ValueT | None:
        if len(values) > 1:
            raise CanonicalAccountCreationCorruption(f"{label} is ambiguous")
        return values[0] if values else None


def _allocation(value: object) -> CanonicalAccountCreationAllocation:
    if type(value) is not CanonicalAccountCreationAllocation:
        raise CanonicalAccountCreationCorruption("allocation type substitution")
    value.__post_init__()
    return value


def _binding(value: object) -> CanonicalAccountCreationBinding:
    if type(value) is not CanonicalAccountCreationBinding:
        raise CanonicalAccountCreationCorruption("binding type substitution")
    value.__post_init__()
    return value


def _aware(value: datetime, name: str) -> None:
    if type(value) is not datetime or value.tzinfo is None or value.utcoffset() is None:
        raise CanonicalAccountCreationUnavailable(f"{name} must be timezone-aware")


def _hash(payload: object) -> str:
    return hashlib.sha256(
        json.dumps(
            payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
        ).encode()
    ).hexdigest()


def _time(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _allocation_values(value: CanonicalAccountCreationAllocation) -> dict[str, object]:
    payload = encode_canonical_account_creation_allocation(value)
    requester, recorder = value.requested_by, value.recorded_by
    values: dict[str, object] = {
        "owner": value.owner,
        "artifact_type": value.artifact_type,
        "schema": value.schema,
        "allocation_id": value.allocation_id,
        "allocation_version": value.allocation_version,
        "canonical_account_namespace": value.canonical_account_namespace,
        "canonical_account_id": value.canonical_account_id,
        "requested_row_user_id": value.requested_row_user_id,
        "requested_raw_account_type": value.requested_raw_account_type,
        "intended_underlying_unified_account_namespace": value.intended_underlying_unified_account_namespace,
        "request_fingerprint_hash": value.request_fingerprint_hash,
        "requester_actor_id": requester.actor_id,
        "requester_user_id": requester.user_id,
        "requester_role": requester.role,
        "requester_kind": requester.kind,
        "requester_is_authenticated": requester.is_authenticated,
        "allocated_at": value.allocated_at,
        "valid_until": value.valid_until,
        "recorded_service_id": recorder.service_id,
        "recorded_role": recorder.role,
        "recorded_kind": recorder.kind,
        "recorded_is_automated": recorder.is_automated,
        "intended_purpose": value.intended_purpose,
        "permission": value.permission,
        "status": value.status,
        "canonical_payload": payload,
        "identity_hash": value.identity_hash,
        "content_hash": value.content_hash,
        "requester_binding_seal": _hash(payload["requested_by"]),
        "recorder_binding_seal": _hash(payload["recorded_by"]),
        "fixed_authority_seal": _hash(
            {
                "owner": value.owner,
                "artifact_type": value.artifact_type,
                "schema": value.schema,
                "intended_purpose": value.intended_purpose,
                "permission": value.permission,
                "status": value.status,
            }
        ),
        "record_seal": _hash({"allocation": payload}),
        "persisted_at": value.allocated_at,
    }
    values["ledger_seal"] = _hash(
        {
            "record_seal": values["record_seal"],
            "requester_binding_seal": values["requester_binding_seal"],
            "recorder_binding_seal": values["recorder_binding_seal"],
            "fixed_authority_seal": values["fixed_authority_seal"],
            "persisted_at": _time(value.allocated_at),
        }
    )
    return values


def _binding_values(
    value: CanonicalAccountCreationBinding, *, allocation_pk: int | None
) -> dict[str, object]:
    if allocation_pk is None:
        raise CanonicalAccountCreationCorruption("allocation has no database identity")
    payload = encode_canonical_account_creation_binding(value)
    physical, recorder = value.physical_observation, value.recorded_by
    values: dict[str, object] = {
        "allocation_id": allocation_pk,
        "allocation_content_hash": value.allocation.content_hash,
        "owner": value.owner,
        "artifact_type": value.artifact_type,
        "schema": value.schema,
        "binding_id": value.binding_id,
        "binding_version": value.binding_version,
        "physical_observation_id": physical.observation_id,
        "physical_observation_version": physical.observation_version,
        "physical_identity_hash": physical.identity_hash,
        "physical_content_hash": physical.content_hash,
        "account_namespace_claim": value.account_namespace_claim,
        "account_id_claim": value.account_id_claim,
        "underlying_unified_account_namespace_claim": value.underlying_unified_account_namespace_claim,
        "underlying_unified_account_id_claim": value.underlying_unified_account_id_claim,
        "recorded_service_id": recorder.service_id,
        "recorded_role": recorder.role,
        "recorded_kind": recorder.kind,
        "recorded_is_automated": recorder.is_automated,
        "recorded_at": value.recorded_at,
        "valid_until": value.valid_until,
        "account_claim_hash": value.account_claim_hash,
        "underlying_claim_hash": value.underlying_claim_hash,
        "permission": value.permission,
        "status": value.status,
        "binding_state": value.binding_state,
        "owner_assignment_state": value.owner_assignment_state,
        "canonical_payload": payload,
        "identity_hash": value.identity_hash,
        "content_hash": value.content_hash,
        "allocation_binding_seal": _hash(payload["allocation"]),
        "physical_binding_seal": _hash(payload["physical_observation"]),
        "recorder_binding_seal": _hash(payload["recorded_by"]),
        "fixed_authority_seal": _hash(
            {
                "owner": value.owner,
                "artifact_type": value.artifact_type,
                "schema": value.schema,
                "permission": value.permission,
                "status": value.status,
                "binding_state": value.binding_state,
                "owner_assignment_state": value.owner_assignment_state,
            }
        ),
        "record_seal": _hash({"binding": payload}),
        "persisted_at": value.recorded_at,
    }
    values["ledger_seal"] = _hash(
        {
            "record_seal": values["record_seal"],
            "allocation_binding_seal": values["allocation_binding_seal"],
            "physical_binding_seal": values["physical_binding_seal"],
            "recorder_binding_seal": values["recorder_binding_seal"],
            "fixed_authority_seal": values["fixed_authority_seal"],
            "persisted_at": _time(value.recorded_at),
        }
    )
    return values


def _restore_allocation(
    row: CanonicalAccountCreationAllocationModel,
) -> CanonicalAccountCreationAllocation:
    try:
        value = decode_canonical_account_creation_allocation(row.canonical_payload)
    except CanonicalAccountCreationCodecError as error:
        raise CanonicalAccountCreationCorruption("allocation payload corrupt") from error
    expected = _allocation_values(value)
    for name, item in expected.items():
        if getattr(row, name) != item:
            raise CanonicalAccountCreationCorruption(f"allocation ledger mismatch: {name}")
    return value


def _restore_binding(
    row: CanonicalAccountCreationBindingModel,
    allocation: CanonicalAccountCreationAllocation,
) -> CanonicalAccountCreationBinding:
    try:
        value = decode_canonical_account_creation_binding(row.canonical_payload)
    except CanonicalAccountCreationCodecError as error:
        raise CanonicalAccountCreationCorruption("binding payload corrupt") from error
    if value.allocation != allocation:
        raise CanonicalAccountCreationCorruption("binding allocation payload mismatch")
    expected = _binding_values(value, allocation_pk=row.allocation_id)
    for name, item in expected.items():
        if getattr(row, name) != item:
            raise CanonicalAccountCreationCorruption(f"binding ledger mismatch: {name}")
    return value


def _allocation_anchor_overlap(
    left: CanonicalAccountCreationAllocation, right: CanonicalAccountCreationAllocation
) -> bool:
    return (
        (left.allocation_id, left.allocation_version)
        == (right.allocation_id, right.allocation_version)
        or (
            left.canonical_account_namespace,
            left.canonical_account_id,
        )
        == (right.canonical_account_namespace, right.canonical_account_id)
        or (
            left.requested_by.actor_id,
            left.requested_by.user_id,
            left.request_fingerprint_hash,
        )
        == (
            right.requested_by.actor_id,
            right.requested_by.user_id,
            right.request_fingerprint_hash,
        )
        or left.identity_hash == right.identity_hash
        or left.content_hash == right.content_hash
    )


def _binding_anchor_overlap(
    left: CanonicalAccountCreationBinding, right: CanonicalAccountCreationBinding
) -> bool:
    return (
        (left.binding_id, left.binding_version) == (right.binding_id, right.binding_version)
        or left.allocation.content_hash == right.allocation.content_hash
        or (left.account_namespace_claim, left.account_id_claim)
        == (right.account_namespace_claim, right.account_id_claim)
        or (
            left.underlying_unified_account_namespace_claim,
            left.underlying_unified_account_id_claim,
        )
        == (
            right.underlying_unified_account_namespace_claim,
            right.underlying_unified_account_id_claim,
        )
        or left.physical_observation.content_hash == right.physical_observation.content_hash
        or left.identity_hash == right.identity_hash
        or left.content_hash == right.content_hash
    )


__all__ = [
    "CanonicalAccountCreationClock",
    "DjangoCanonicalAccountCreationClock",
    "DjangoCanonicalAccountCreationRepository",
]
