"""Closed-world Django repository for canonical Account creation evidence."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol, TypeVar

from django.db import IntegrityError, transaction
from django.utils import timezone

from apps.account.application.canonical_account_creation import (
    CanonicalAccountCreationConflict,
    CanonicalAccountCreationCorruption,
    CanonicalAccountCreationUnavailable,
    PersistedCanonicalAccountCreationBinding,
)
from apps.account.domain.allocated_physical_account_row_observation_v3 import (
    AllocatedPhysicalAccountRowObservationV3,
)
from apps.account.domain.canonical_account_creation import (
    CanonicalAccountCreationAllocation,
    CanonicalAccountCreationBinding,
)
from apps.account.domain.canonical_account_creation_binding_v2 import (
    CanonicalAccountCreationBindingV2,
)
from apps.account.domain.canonical_account_creation_consumption import (
    CanonicalAccountCreationConsumptionClaim,
)
from apps.account.infrastructure.allocated_physical_account_row_observation_v3_codec import (
    AllocatedPhysicalAccountRowObservationV3CodecError,
    decode_allocated_physical_account_row_observation_v3_record,
)
from apps.account.infrastructure.allocated_physical_account_row_observation_v3_models import (
    AllocatedPhysicalAccountRowObservationV3Model,
)
from apps.account.infrastructure.allocated_physical_account_row_observation_v3_repository import (
    _model_values as _creation_root_values,
)
from apps.account.infrastructure.canonical_account_creation_binding_v2_codec import (
    CanonicalAccountCreationBindingV2CodecError,
    decode_canonical_account_creation_binding_v2,
)
from apps.account.infrastructure.canonical_account_creation_codec import (
    CanonicalAccountCreationCodecError,
    decode_canonical_account_creation_allocation,
    decode_canonical_account_creation_binding,
    encode_canonical_account_creation_allocation,
    encode_canonical_account_creation_binding,
)
from apps.account.infrastructure.canonical_account_creation_consumption_codec import (
    CanonicalAccountCreationConsumptionCodecError,
    decode_canonical_account_creation_consumption_claim,
    encode_canonical_account_creation_consumption_claim,
)
from apps.account.infrastructure.canonical_account_creation_consumption_models import (
    CanonicalAccountCreationBindingV2Model,
    CanonicalAccountCreationConsumptionClaimModel,
    _activate_canonical_account_creation_consumption_uow,
    _claim_canonical_account_creation_consumption_insert,
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


@dataclass(frozen=True, slots=True)
class _ConsumptionWorld:
    allocations: tuple[
        tuple[CanonicalAccountCreationAllocationModel, CanonicalAccountCreationAllocation], ...
    ]
    roots: tuple[
        tuple[
            AllocatedPhysicalAccountRowObservationV3Model,
            AllocatedPhysicalAccountRowObservationV3,
        ],
        ...,
    ]
    bindings_v1: tuple[
        tuple[CanonicalAccountCreationBindingModel, CanonicalAccountCreationBinding], ...
    ]
    bindings_v2: tuple[
        tuple[CanonicalAccountCreationBindingV2Model, CanonicalAccountCreationBindingV2], ...
    ]
    claims: tuple[
        tuple[
            CanonicalAccountCreationConsumptionClaimModel,
            CanonicalAccountCreationConsumptionClaim,
        ],
        ...,
    ]


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
                _activate_canonical_account_creation_consumption_uow(token),
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
        allocations = self._closed_consumption_world(lock=False).allocations
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
        allocations = self._closed_consumption_world(lock=False).allocations
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
        allocations = self._closed_consumption_world(lock=False).allocations
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
        world = self._closed_consumption_world(lock=False)
        exact = self._exact_from_world(
            world.allocations,
            allocation_id=allocation_id,
            allocation_version=allocation_version,
            expected_content_hash=expected_content_hash,
            as_of=as_of,
        )
        if exact is None or not exact.allocated_at <= as_of < exact.valid_until:
            return None
        if any(value.allocation.content_hash == exact.content_hash for _, value in world.claims):
            return None
        if any(
            row.consumption_claim_id is None and value.allocation.content_hash == exact.content_hash
            for row, value in world.bindings_v1
        ):
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
        allocations = self._closed_consumption_world(lock=True).allocations
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
            allocations = self._closed_consumption_world(lock=True).allocations
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
    ) -> PersistedCanonicalAccountCreationBinding | None:
        """Return one atomic Binding-v1/claim pair knowable at the cutoff."""

        self._cutoff(as_of)
        world = self._closed_consumption_world(lock=False)
        matches = tuple(
            (row, value)
            for row, value in world.bindings_v1
            if value.binding_id == binding_id
            and value.binding_version == binding_version
            and value.recorded_at <= as_of
        )
        selected = self._single(matches, "binding identity")
        if selected is None:
            return None
        row, binding = selected
        claim_pk = _optional_fk_id(row, "consumption_claim_id")
        if claim_pk is None:
            raise CanonicalAccountCreationCorruption(
                "legacy Binding-v1 has no unified consumption claim"
            )
        claim = _claim_by_pk(world, claim_pk)
        if claim is None or claim.recorded_at > as_of:
            raise CanonicalAccountCreationCorruption("Binding-v1 claim is unavailable")
        try:
            return PersistedCanonicalAccountCreationBinding(binding, claim)
        except (TypeError, ValueError) as error:
            raise CanonicalAccountCreationCorruption("Binding-v1 claim pair differs") from error

    def get_consumption_claim_by_any_anchor(
        self,
        *,
        claim_id: str,
        claim_version: str,
        allocation_identity_hash: str,
        allocation_content_hash: str,
        consumer_identity_hash: str,
        consumer_content_hash: str,
        account_namespace: str,
        account_id: str,
        underlying_unified_account_namespace: str,
        underlying_unified_account_id: int,
        physical_v2_content_hash: str,
        physical_v3_root_content_hash: None,
        as_of: datetime,
    ) -> CanonicalAccountCreationConsumptionClaim | None:
        """Return an occupied unified anchor, rejecting unbackfilled legacy rows."""

        if physical_v3_root_content_hash is not None:
            raise CanonicalAccountCreationCorruption("Binding-v1 root selector must be None")
        self._cutoff(as_of)
        world = self._closed_consumption_world(lock=False)
        matches = tuple(
            value
            for _, value in world.claims
            if value.recorded_at <= as_of
            and _claim_anchor_matches_v1(
                value,
                claim_id=claim_id,
                claim_version=claim_version,
                allocation_identity_hash=allocation_identity_hash,
                allocation_content_hash=allocation_content_hash,
                consumer_identity_hash=consumer_identity_hash,
                consumer_content_hash=consumer_content_hash,
                account_namespace=account_namespace,
                account_id=account_id,
                underlying_namespace=underlying_unified_account_namespace,
                underlying_id=underlying_unified_account_id,
                physical_v2_hash=physical_v2_content_hash,
            )
        )
        result = self._single(matches, "consumption anchors")
        legacy = tuple(
            value
            for row, value in world.bindings_v1
            if row.consumption_claim_id is None
            and value.recorded_at <= as_of
            and _legacy_binding_anchor_matches(
                value,
                allocation_content_hash=allocation_content_hash,
                account_namespace=account_namespace,
                account_id=account_id,
                underlying_namespace=underlying_unified_account_namespace,
                underlying_id=underlying_unified_account_id,
                physical_v2_hash=physical_v2_content_hash,
            )
        )
        if legacy:
            raise CanonicalAccountCreationConflict(
                "legacy Binding-v1 already occupies a consumption anchor"
            )
        return result

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
        bindings = self._closed_consumption_world(lock=False).bindings_v1
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
        bindings = self._closed_consumption_world(lock=False).bindings_v1
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
        """Reject the obsolete null-claim append seam after schema expansion."""

        del (
            binding,
            expected_allocation_content_hash,
            expected_account_claim_hash,
            expected_underlying_claim_hash,
            expected_physical_content_hash,
            recorded_at,
        )
        raise CanonicalAccountCreationConflict("Binding-v1 requires a unified consumption claim")

    def append_binding_with_consumption_claim(
        self,
        binding: CanonicalAccountCreationBinding,
        claim: CanonicalAccountCreationConsumptionClaim,
        *,
        expected_allocation_content_hash: str,
        expected_account_claim_hash: str,
        expected_underlying_claim_hash: str,
        expected_physical_content_hash: str,
        expected_consumption_claim_content_hash: str,
        recorded_at: datetime,
    ) -> tuple[CanonicalAccountCreationBinding, CanonicalAccountCreationConsumptionClaim]:
        """Append the unified claim first and Binding-v1 second in one transaction."""

        checked_binding = _binding(binding)
        checked_claim = _consumption_claim(claim)
        self._require_uow()
        _aware(recorded_at, "recorded_at")
        if (
            checked_binding.recorded_at != recorded_at
            or checked_claim.recorded_at != recorded_at
            or checked_claim.consumer_generation != "v1"
            or checked_claim.consumer != checked_binding
            or checked_claim.allocation != checked_binding.allocation
        ):
            raise CanonicalAccountCreationConflict("binding/claim pair or clock differs")
        if (
            checked_binding.allocation.content_hash != expected_allocation_content_hash
            or checked_binding.account_claim_hash != expected_account_claim_hash
            or checked_binding.underlying_claim_hash != expected_underlying_claim_hash
            or checked_binding.physical_observation.content_hash != expected_physical_content_hash
            or checked_claim.content_hash != expected_consumption_claim_content_hash
        ):
            raise CanonicalAccountCreationConflict("binding/claim append anchors differ")

        world = self._closed_consumption_world(lock=True)
        allocation_rows = tuple(
            (row, value)
            for row, value in world.allocations
            if value.content_hash == checked_binding.allocation.content_hash
        )
        if len(allocation_rows) != 1 or allocation_rows[0][1] != checked_binding.allocation:
            raise CanonicalAccountCreationConflict("binding allocation is not exact")
        if (
            not checked_binding.allocation.allocated_at
            <= recorded_at
            < checked_binding.allocation.valid_until
        ):
            raise CanonicalAccountCreationConflict("binding allocation is expired")
        if any(_claims_overlap(value, checked_claim) for _, value in world.claims) or any(
            _binding_anchor_overlap(value, checked_binding) for _, value in world.bindings_v1
        ):
            exact = _exact_v1_pair(world, checked_binding, checked_claim)
            if exact is not None:
                return exact.binding, exact.claim
            raise CanonicalAccountCreationConflict("consumption first-winner anchor differs")

        claim_values = _consumption_claim_values(
            checked_claim, allocation_pk=allocation_rows[0][0].pk
        )
        try:
            with transaction.atomic(using=self._using):
                claim_row = self._insert_consumption_claim(claim_values)
                binding_values = _binding_values(
                    checked_binding,
                    allocation_pk=allocation_rows[0][0].pk,
                    consumption_claim_pk=claim_row.pk,
                )
                self._insert(CanonicalAccountCreationBindingModel, binding_values)
        except IntegrityError as error:
            refreshed = self._closed_consumption_world(lock=True)
            exact = _exact_v1_pair(refreshed, checked_binding, checked_claim)
            if exact is not None:
                return exact.binding, exact.claim
            raise CanonicalAccountCreationConflict(
                "concurrent consumption first winner differs"
            ) from error
        refreshed = self._closed_consumption_world(lock=True)
        exact = _exact_v1_pair(refreshed, checked_binding, checked_claim)
        if exact is None:
            raise CanonicalAccountCreationCorruption("appended Binding-v1/claim restore mismatch")
        return exact.binding, exact.claim

    def _closed_consumption_world(self, *, lock: bool) -> _ConsumptionWorld:
        """Restore every ledger participating in cross-generation consumption."""

        allocations, bindings_v1 = self._closed_world(lock=lock)
        allocation_by_pk = {row.pk: value for row, value in allocations}
        root_query = AllocatedPhysicalAccountRowObservationV3Model._base_manager.using(
            self._using
        ).all()
        v2_query = CanonicalAccountCreationBindingV2Model._base_manager.using(self._using).all()
        claim_query = CanonicalAccountCreationConsumptionClaimModel._base_manager.using(
            self._using
        ).all()
        if lock:
            root_query = root_query.select_for_update()
            v2_query = v2_query.select_for_update()
            claim_query = claim_query.select_for_update()
        roots = tuple((row, _restore_creation_root(row)) for row in root_query.order_by("pk"))
        root_by_pk = {row.pk: value for row, value in roots}
        bindings_v2 = tuple(
            (row, _restore_binding_v2(row, allocation_by_pk, root_by_pk))
            for row in v2_query.order_by("pk")
        )
        consumers: dict[
            tuple[str, str, str, str],
            CanonicalAccountCreationBinding | CanonicalAccountCreationBindingV2,
        ] = {}
        for _, value in (*bindings_v1, *bindings_v2):
            key = (value.owner, value.artifact_type, value.binding_id, value.binding_version)
            if key in consumers:
                raise CanonicalAccountCreationCorruption("consumer reference is ambiguous")
            consumers[key] = value
        claims = tuple(
            (row, _restore_consumption_claim(row, allocation_by_pk, consumers))
            for row in claim_query.order_by("pk")
        )
        claims_by_pk = {row.pk: value for row, value in claims}
        for row, value in bindings_v1:
            claim_pk = _optional_fk_id(row, "consumption_claim_id")
            if claim_pk is not None:
                linked = claims_by_pk.get(claim_pk)
                if linked is None or linked.consumer_generation != "v1" or linked.consumer != value:
                    raise CanonicalAccountCreationCorruption("Binding-v1 claim link differs")
        for row, value in bindings_v2:
            linked = claims_by_pk.get(_required_fk_id(row, "consumption_claim_id"))
            if (
                linked is None
                or linked.consumer_generation != "v2"
                or linked.consumer != value
                or row.consumption_claim_content_hash != linked.content_hash
            ):
                raise CanonicalAccountCreationCorruption("Binding-v2 claim link differs")
        return _ConsumptionWorld(allocations, roots, bindings_v1, bindings_v2, claims)

    def _insert_consumption_claim(
        self, values: dict[str, object]
    ) -> CanonicalAccountCreationConsumptionClaimModel:
        token = self._require_uow()
        with _claim_canonical_account_creation_consumption_insert(
            token=token,
            model_type=CanonicalAccountCreationConsumptionClaimModel,
            expected_values=values,
        ):
            return CanonicalAccountCreationConsumptionClaimModel._default_manager.using(
                self._using
            ).create(**values)

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


def _consumption_claim(value: object) -> CanonicalAccountCreationConsumptionClaim:
    if type(value) is not CanonicalAccountCreationConsumptionClaim:
        raise CanonicalAccountCreationCorruption("consumption claim type substitution")
    try:
        value.__post_init__()
    except (TypeError, ValueError) as error:
        raise CanonicalAccountCreationCorruption("consumption claim is corrupt") from error
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
    value: CanonicalAccountCreationBinding,
    *,
    allocation_pk: int | None,
    consumption_claim_pk: int | None = None,
) -> dict[str, object]:
    if allocation_pk is None:
        raise CanonicalAccountCreationCorruption("allocation has no database identity")
    payload = encode_canonical_account_creation_binding(value)
    physical, recorder = value.physical_observation, value.recorded_by
    values: dict[str, object] = {
        "consumption_claim_id": consumption_claim_pk,
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


def _consumption_claim_values(
    value: CanonicalAccountCreationConsumptionClaim, *, allocation_pk: int | None
) -> dict[str, object]:
    if allocation_pk is None:
        raise CanonicalAccountCreationCorruption("claim allocation has no database identity")
    payload = encode_canonical_account_creation_consumption_claim(value)
    consumer = value.consumer
    values: dict[str, object] = {
        "owner": value.owner,
        "artifact_type": value.artifact_type,
        "schema": value.schema,
        "claim_id": value.claim_id,
        "claim_version": value.claim_version,
        "allocation_id": allocation_pk,
        "allocation_identity_hash": value.allocation.identity_hash,
        "allocation_content_hash": value.allocation.content_hash,
        "consumer_generation": value.consumer_generation,
        "consumer_owner": consumer.owner,
        "consumer_artifact_type": consumer.artifact_type,
        "consumer_schema": consumer.schema,
        "consumer_id": consumer.binding_id,
        "consumer_version": consumer.binding_version,
        "consumer_identity_hash": consumer.identity_hash,
        "consumer_content_hash": consumer.content_hash,
        "account_namespace": value.account_namespace,
        "account_id": value.account_id,
        "underlying_unified_account_namespace": value.underlying_unified_account_namespace,
        "underlying_unified_account_id": value.underlying_unified_account_id,
        "physical_v2_content_hash": value.physical_v2_content_hash,
        "physical_v3_root_content_hash": value.physical_v3_root_content_hash,
        "recorded_at": value.recorded_at,
        "permission": value.permission,
        "status": value.status,
        "canonical_payload": payload,
        "identity_hash": value.identity_hash,
        "content_hash": value.content_hash,
        "allocation_binding_seal": _hash(payload["allocation"]),
        "consumer_binding_seal": _hash(payload["consumer_ref"]),
        "fixed_authority_seal": _hash(
            {
                "owner": value.owner,
                "artifact_type": value.artifact_type,
                "schema": value.schema,
                "permission": value.permission,
                "status": value.status,
            }
        ),
        "record_seal": _hash({"claim": payload}),
        "persisted_at": value.recorded_at,
    }
    values["ledger_seal"] = _hash(
        {
            "record_seal": values["record_seal"],
            "allocation_binding_seal": values["allocation_binding_seal"],
            "consumer_binding_seal": values["consumer_binding_seal"],
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
    expected = _binding_values(
        value,
        allocation_pk=row.allocation_id,
        consumption_claim_pk=_optional_fk_id(row, "consumption_claim_id"),
    )
    for name, item in expected.items():
        if getattr(row, name) != item:
            raise CanonicalAccountCreationCorruption(f"binding ledger mismatch: {name}")
    return value


def _restore_creation_root(
    row: AllocatedPhysicalAccountRowObservationV3Model,
) -> AllocatedPhysicalAccountRowObservationV3:
    try:
        record = decode_allocated_physical_account_row_observation_v3_record(row.canonical_payload)
        expected = _creation_root_values(record, recorded_at=record.observation.recorded_at)
    except (AllocatedPhysicalAccountRowObservationV3CodecError, TypeError, ValueError) as error:
        raise CanonicalAccountCreationCorruption(
            "creation-root ledger cannot be restored"
        ) from error
    _match_row_values(row, expected, "creation-root")
    return record.observation


def _restore_binding_v2(
    row: CanonicalAccountCreationBindingV2Model,
    allocations: dict[int | None, CanonicalAccountCreationAllocation],
    roots: dict[int | None, AllocatedPhysicalAccountRowObservationV3],
) -> CanonicalAccountCreationBindingV2:
    try:
        value = decode_canonical_account_creation_binding_v2(row.canonical_payload)
    except CanonicalAccountCreationBindingV2CodecError as error:
        raise CanonicalAccountCreationCorruption("Binding-v2 payload cannot be restored") from error
    if (
        allocations.get(_required_fk_id(row, "allocation_id")) != value.allocation
        or roots.get(_required_fk_id(row, "creation_root_id")) != value.creation_root
    ):
        raise CanonicalAccountCreationCorruption("Binding-v2 foreign evidence differs")
    return value


def _restore_consumption_claim(
    row: CanonicalAccountCreationConsumptionClaimModel,
    allocations: dict[int | None, CanonicalAccountCreationAllocation],
    consumers: dict[
        tuple[str, str, str, str],
        CanonicalAccountCreationBinding | CanonicalAccountCreationBindingV2,
    ],
) -> CanonicalAccountCreationConsumptionClaim:
    consumer = consumers.get(
        (row.consumer_owner, row.consumer_artifact_type, row.consumer_id, row.consumer_version)
    )
    if consumer is None:
        raise CanonicalAccountCreationCorruption("claim consumer is orphaned")
    try:
        value = decode_canonical_account_creation_consumption_claim(
            row.canonical_payload, consumer=consumer
        )
    except CanonicalAccountCreationConsumptionCodecError as error:
        raise CanonicalAccountCreationCorruption("claim payload cannot be restored") from error
    allocation_pk = _required_fk_id(row, "allocation_id")
    if allocations.get(allocation_pk) != value.allocation:
        raise CanonicalAccountCreationCorruption("claim allocation differs")
    _match_row_values(
        row,
        _consumption_claim_values(value, allocation_pk=allocation_pk),
        "consumption claim",
    )
    return value


def _optional_fk_id(row: object, name: str) -> int | None:
    value = getattr(row, name)
    if value is None:
        return None
    if type(value) is not int or value <= 0:
        raise CanonicalAccountCreationCorruption(f"{name} is invalid")
    return value


def _required_fk_id(row: object, name: str) -> int:
    value = _optional_fk_id(row, name)
    if value is None:
        raise CanonicalAccountCreationCorruption(f"{name} is missing")
    return value


def _match_row_values(row: object, expected: dict[str, object], label: str) -> None:
    for name, value in expected.items():
        if getattr(row, name) != value:
            raise CanonicalAccountCreationCorruption(f"{label} ledger mismatch: {name}")


def _claim_by_pk(
    world: _ConsumptionWorld, pk: int
) -> CanonicalAccountCreationConsumptionClaim | None:
    return next((value for row, value in world.claims if row.pk == pk), None)


def _claim_anchor_matches_v1(
    value: CanonicalAccountCreationConsumptionClaim, **anchors: object
) -> bool:
    return (
        (value.claim_id, value.claim_version) == (anchors["claim_id"], anchors["claim_version"])
        or value.allocation.identity_hash == anchors["allocation_identity_hash"]
        or value.allocation.content_hash == anchors["allocation_content_hash"]
        or value.consumer.identity_hash == anchors["consumer_identity_hash"]
        or value.consumer.content_hash == anchors["consumer_content_hash"]
        or (value.account_namespace, value.account_id)
        == (anchors["account_namespace"], anchors["account_id"])
        or (value.underlying_unified_account_namespace, value.underlying_unified_account_id)
        == (anchors["underlying_namespace"], anchors["underlying_id"])
        or value.physical_v2_content_hash == anchors["physical_v2_hash"]
    )


def _legacy_binding_anchor_matches(
    value: CanonicalAccountCreationBinding, **anchors: object
) -> bool:
    return (
        value.allocation.content_hash == anchors["allocation_content_hash"]
        or (value.account_namespace_claim, value.account_id_claim)
        == (anchors["account_namespace"], anchors["account_id"])
        or (
            value.underlying_unified_account_namespace_claim,
            value.underlying_unified_account_id_claim,
        )
        == (anchors["underlying_namespace"], anchors["underlying_id"])
        or value.physical_observation.content_hash == anchors["physical_v2_hash"]
    )


def _claims_overlap(
    left: CanonicalAccountCreationConsumptionClaim,
    right: CanonicalAccountCreationConsumptionClaim,
) -> bool:
    return _claim_anchor_matches_v1(
        left,
        claim_id=right.claim_id,
        claim_version=right.claim_version,
        allocation_identity_hash=right.allocation.identity_hash,
        allocation_content_hash=right.allocation.content_hash,
        consumer_identity_hash=right.consumer.identity_hash,
        consumer_content_hash=right.consumer.content_hash,
        account_namespace=right.account_namespace,
        account_id=right.account_id,
        underlying_namespace=right.underlying_unified_account_namespace,
        underlying_id=right.underlying_unified_account_id,
        physical_v2_hash=right.physical_v2_content_hash,
    )


def _exact_v1_pair(
    world: _ConsumptionWorld,
    binding: CanonicalAccountCreationBinding,
    claim: CanonicalAccountCreationConsumptionClaim,
) -> PersistedCanonicalAccountCreationBinding | None:
    bindings = tuple((row, value) for row, value in world.bindings_v1 if value == binding)
    claims = tuple((row, value) for row, value in world.claims if value == claim)
    if len(bindings) != 1 or len(claims) != 1:
        return None
    if _optional_fk_id(bindings[0][0], "consumption_claim_id") != claims[0][0].pk:
        return None
    try:
        return PersistedCanonicalAccountCreationBinding(binding, claim)
    except (TypeError, ValueError) as error:
        raise CanonicalAccountCreationCorruption("exact Binding-v1 claim pair differs") from error


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
