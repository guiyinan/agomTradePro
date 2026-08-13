"""Closed-world Django repository for unified creation-consumption claims."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol, TypeVar, cast

from django.db import IntegrityError, transaction
from django.utils import timezone

from apps.account.application.canonical_account_creation_binding_v2 import (
    CanonicalAccountCreationBindingV2Conflict,
    CanonicalAccountCreationBindingV2Corruption,
    CanonicalAccountCreationBindingV2Unavailable,
    PersistedCanonicalAccountCreationBindingV2,
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
    encode_canonical_account_creation_binding_v2,
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
)
from apps.account.infrastructure.canonical_account_creation_repository import (
    _restore_allocation,
    _restore_binding,
)


class CanonicalAccountCreationConsumptionClock(Protocol):
    """Provide the authoritative persistence clock."""

    def now(self) -> datetime: ...


class DjangoCanonicalAccountCreationConsumptionClock:
    """Django timezone-backed production clock."""

    def now(self) -> datetime:
        """Return one aware server timestamp."""

        return timezone.now()


@dataclass(frozen=True, slots=True)
class _World:
    allocations: tuple[
        tuple[CanonicalAccountCreationAllocationModel, CanonicalAccountCreationAllocation], ...
    ]
    roots: tuple[
        tuple[
            AllocatedPhysicalAccountRowObservationV3Model, AllocatedPhysicalAccountRowObservationV3
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
            CanonicalAccountCreationConsumptionClaimModel, CanonicalAccountCreationConsumptionClaim
        ],
        ...,
    ]


_ValueT = TypeVar("_ValueT")


class DjangoCanonicalAccountCreationConsumptionRepository:
    """Restore allocation, root, both binding generations, and claims before selection."""

    def __init__(
        self,
        *,
        using: str = "default",
        clock: CanonicalAccountCreationConsumptionClock | None = None,
    ) -> None:
        self._using = using
        self._clock = clock or DjangoCanonicalAccountCreationConsumptionClock()
        self._uow: object | None = None

    @contextmanager
    def atomic(self) -> Iterator[None]:
        """Open one non-nestable private consumption-ledger transaction."""

        if self._uow is not None:
            raise CanonicalAccountCreationBindingV2Conflict("nested consumption UOW")
        token = object()
        self._uow = token
        try:
            with (
                transaction.atomic(using=self._using),
                _activate_canonical_account_creation_consumption_uow(token),
            ):
                yield
        finally:
            self._uow = None

    def now(self) -> datetime:
        """Return the validated authoritative clock."""

        value = self._clock.now()
        if not _is_aware(value):
            raise CanonicalAccountCreationBindingV2Corruption("repository clock is naive")
        return value

    def get_winner(
        self, *, binding_id: str, binding_version: str, as_of: datetime
    ) -> PersistedCanonicalAccountCreationBindingV2 | None:
        """Return one exact Binding-v2/claim identity winner knowable at cutoff."""

        self._cutoff(as_of)
        world = self._closed_world(lock=False)
        matches = tuple(
            (row, value)
            for row, value in world.bindings_v2
            if value.binding_id == binding_id
            and value.binding_version == binding_version
            and value.recorded_at <= as_of
        )
        selected = _single(matches, "Binding-v2 identity")
        if selected is None:
            return None
        row, binding = selected
        claim = _claim_by_pk(world, _fk_id(row, "consumption_claim_id"))
        if claim is None or claim.recorded_at > as_of:
            raise CanonicalAccountCreationBindingV2Corruption("Binding-v2 claim is unavailable")
        return PersistedCanonicalAccountCreationBindingV2(binding, claim)

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
        physical_v3_root_content_hash: str,
        as_of: datetime,
    ) -> CanonicalAccountCreationConsumptionClaim | None:
        """Return a claim when any independent immutable anchor is occupied."""

        self._cutoff(as_of)
        world = self._closed_world(lock=False)
        matches = tuple(
            value
            for _, value in world.claims
            if value.recorded_at <= as_of
            and _claim_anchor_matches(
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
                physical_v3_hash=physical_v3_root_content_hash,
            )
        )
        result = _single(matches, "consumption anchors")
        legacy = tuple(
            value
            for row, value in world.bindings_v1
            if _fk_id(row, "consumption_claim_id") is None
            and value.recorded_at <= as_of
            and _legacy_anchor_matches(
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
            raise CanonicalAccountCreationBindingV2Conflict(
                "legacy Binding-v1 already occupies a consumption anchor"
            )
        return result

    def get_exact_by_hash(
        self,
        *,
        binding_id: str,
        binding_version: str,
        expected_content_hash: str,
        as_of: datetime,
    ) -> CanonicalAccountCreationBindingV2 | None:
        """Return only an exact permanent Binding-v2 known by cutoff."""

        self._cutoff(as_of)
        world = self._closed_world(lock=False)
        anchors = tuple(
            value
            for _, value in world.bindings_v2
            if (value.binding_id, value.binding_version) == (binding_id, binding_version)
            or value.content_hash == expected_content_hash
        )
        matches = tuple(
            value
            for value in anchors
            if (value.binding_id, value.binding_version, value.content_hash)
            == (binding_id, binding_version, expected_content_hash)
            and value.recorded_at <= as_of
        )
        if anchors and (len(anchors) != 1 or len(matches) > 1):
            raise CanonicalAccountCreationBindingV2Corruption("Binding-v2 exact anchors disagree")
        return matches[0] if matches else None

    def append_with_consumption_claim(
        self,
        binding: CanonicalAccountCreationBindingV2,
        claim: CanonicalAccountCreationConsumptionClaim,
        *,
        expected_allocation_content_hash: str,
        expected_account_claim_hash: str,
        expected_underlying_claim_hash: str,
        expected_creation_root_content_hash: str,
        expected_consumption_claim_content_hash: str,
        recorded_at: datetime,
    ) -> tuple[CanonicalAccountCreationBindingV2, CanonicalAccountCreationConsumptionClaim]:
        """Append claim first and Binding-v2 second in one private transaction."""

        checked_binding = _binding_v2(binding)
        checked_claim = _claim(claim)
        self._require_uow()
        if not _is_aware(recorded_at):
            raise CanonicalAccountCreationBindingV2Unavailable("recorded_at must be aware")
        if (
            checked_binding.recorded_at != recorded_at
            or checked_claim.recorded_at != recorded_at
            or checked_claim.consumer_generation != "v2"
            or checked_claim.consumer != checked_binding
            or checked_claim.allocation != checked_binding.allocation
        ):
            raise CanonicalAccountCreationBindingV2Conflict("append pair or clock differs")
        if (
            checked_binding.allocation.content_hash != expected_allocation_content_hash
            or checked_binding.account_claim_hash != expected_account_claim_hash
            or checked_binding.underlying_claim_hash != expected_underlying_claim_hash
            or checked_binding.creation_root.content_hash != expected_creation_root_content_hash
            or checked_claim.content_hash != expected_consumption_claim_content_hash
        ):
            raise CanonicalAccountCreationBindingV2Conflict("append anchors differ")

        world = self._closed_world(lock=True)
        allocation_row = _exact_allocation_row(world, checked_binding.allocation)
        root_row = _exact_root_row(world, checked_binding.creation_root)
        occupied_claims = tuple(
            value for _, value in world.claims if _claims_overlap(value, checked_claim)
        )
        occupied_v1 = tuple(
            value
            for _, value in world.bindings_v1
            if _legacy_anchor_matches(
                value,
                allocation_content_hash=checked_claim.allocation.content_hash,
                account_namespace=checked_claim.account_namespace,
                account_id=checked_claim.account_id,
                underlying_namespace=checked_claim.underlying_unified_account_namespace,
                underlying_id=checked_claim.underlying_unified_account_id,
                physical_v2_hash=checked_claim.physical_v2_content_hash,
            )
        )
        occupied_v2 = tuple(
            value for _, value in world.bindings_v2 if _bindings_v2_overlap(value, checked_binding)
        )
        if occupied_claims or occupied_v1 or occupied_v2:
            exact = self._exact_pair(world, checked_binding, checked_claim)
            if exact is not None:
                return exact.binding, exact.claim
            raise CanonicalAccountCreationBindingV2Conflict("consumption first winner differs")

        claim_values = _claim_values(checked_claim, allocation_pk=allocation_row.pk)
        try:
            with transaction.atomic(using=self._using):
                claim_row = self._insert_claim(claim_values)
                binding_values = _binding_v2_values(
                    checked_binding,
                    claim_content_hash=checked_claim.content_hash,
                    claim_pk=claim_row.pk,
                    allocation_pk=allocation_row.pk,
                    root_pk=root_row.pk,
                )
                self._insert_binding(binding_values)
        except IntegrityError as error:
            refreshed = self._closed_world(lock=True)
            exact = self._exact_pair(refreshed, checked_binding, checked_claim)
            if exact is not None:
                return exact.binding, exact.claim
            raise CanonicalAccountCreationBindingV2Conflict(
                "concurrent consumption first winner differs"
            ) from error

        refreshed = self._closed_world(lock=True)
        exact = self._exact_pair(refreshed, checked_binding, checked_claim)
        if exact is None:
            raise CanonicalAccountCreationBindingV2Corruption("appended pair restore mismatch")
        return exact.binding, exact.claim

    def _closed_world(self, *, lock: bool) -> _World:
        allocation_query = CanonicalAccountCreationAllocationModel._base_manager.using(
            self._using
        ).all()
        if lock:
            allocation_query = allocation_query.select_for_update()
        allocations = tuple(
            (row, _restore_allocation_checked(row)) for row in allocation_query.order_by("pk")
        )
        allocation_by_pk = {row.pk: value for row, value in allocations}

        root_query = AllocatedPhysicalAccountRowObservationV3Model._base_manager.using(
            self._using
        ).all()
        v1_query = CanonicalAccountCreationBindingModel._base_manager.using(self._using).all()
        v2_query = CanonicalAccountCreationBindingV2Model._base_manager.using(self._using).all()
        claim_query = CanonicalAccountCreationConsumptionClaimModel._base_manager.using(
            self._using
        ).all()
        if lock:
            root_query = root_query.select_for_update()
            v1_query = v1_query.select_for_update()
            v2_query = v2_query.select_for_update()
            claim_query = claim_query.select_for_update()

        roots = tuple((row, _restore_root(row)) for row in root_query.order_by("pk"))
        root_by_pk = {row.pk: value for row, value in roots}
        bindings_v1 = tuple(
            (row, _restore_binding_v1(row, allocation_by_pk.get(_fk_id(row, "allocation_id"))))
            for row in v1_query.order_by("pk")
        )
        bindings_v2 = tuple(
            (row, _restore_binding_v2_row(row, allocation_by_pk, root_by_pk))
            for row in v2_query.order_by("pk")
        )
        consumers: dict[
            tuple[str, str, str, str],
            CanonicalAccountCreationBinding | CanonicalAccountCreationBindingV2,
        ] = {}
        for _, value in bindings_v1:
            key = (value.owner, value.artifact_type, value.binding_id, value.binding_version)
            if key in consumers:
                raise CanonicalAccountCreationBindingV2Corruption("consumer reference is ambiguous")
            consumers[key] = value
        for _, value in bindings_v2:
            key = (value.owner, value.artifact_type, value.binding_id, value.binding_version)
            if key in consumers:
                raise CanonicalAccountCreationBindingV2Corruption("consumer reference is ambiguous")
            consumers[key] = value
        claims = tuple(
            (row, _restore_claim_row(row, allocation_by_pk, consumers))
            for row in claim_query.order_by("pk")
        )
        claim_by_pk = {row.pk: value for row, value in claims}
        for row, value in bindings_v2:
            linked = claim_by_pk.get(_fk_id(row, "consumption_claim_id"))
            if (
                linked is None
                or linked.consumer != value
                or linked.consumer_generation != "v2"
                or row.consumption_claim_content_hash != linked.content_hash
            ):
                raise CanonicalAccountCreationBindingV2Corruption("Binding-v2 claim link differs")
        for row, value in bindings_v1:
            claim_fk = _fk_id(row, "consumption_claim_id")
            if claim_fk is not None:
                linked = claim_by_pk.get(claim_fk)
                if linked is None or linked.consumer != value or linked.consumer_generation != "v1":
                    raise CanonicalAccountCreationBindingV2Corruption(
                        "Binding-v1 claim link differs"
                    )
        return _World(allocations, roots, bindings_v1, bindings_v2, claims)

    def _exact_pair(
        self,
        world: _World,
        binding: CanonicalAccountCreationBindingV2,
        claim: CanonicalAccountCreationConsumptionClaim,
    ) -> PersistedCanonicalAccountCreationBindingV2 | None:
        binding_rows = tuple((row, value) for row, value in world.bindings_v2 if value == binding)
        claim_rows = tuple((row, value) for row, value in world.claims if value == claim)
        if len(binding_rows) != 1 or len(claim_rows) != 1:
            return None
        if _fk_id(binding_rows[0][0], "consumption_claim_id") != claim_rows[0][0].pk:
            return None
        return PersistedCanonicalAccountCreationBindingV2(binding, claim)

    def _insert_claim(
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

    def _insert_binding(self, values: dict[str, object]) -> None:
        token = self._require_uow()
        with _claim_canonical_account_creation_consumption_insert(
            token=token,
            model_type=CanonicalAccountCreationBindingV2Model,
            expected_values=values,
        ):
            CanonicalAccountCreationBindingV2Model._default_manager.using(self._using).create(
                **values
            )

    def _require_uow(self) -> object:
        if self._uow is None:
            raise CanonicalAccountCreationBindingV2Conflict("append requires private UOW")
        return self._uow

    def _cutoff(self, as_of: datetime) -> None:
        if not _is_aware(as_of):
            raise CanonicalAccountCreationBindingV2Unavailable("as_of must be aware")
        if as_of > self.now():
            raise CanonicalAccountCreationBindingV2Unavailable("future as_of is forbidden")


def _restore_allocation_checked(
    row: CanonicalAccountCreationAllocationModel,
) -> CanonicalAccountCreationAllocation:
    try:
        return _restore_allocation(row)
    except Exception as error:
        raise CanonicalAccountCreationBindingV2Corruption(
            "allocation ledger cannot be restored"
        ) from error


def _restore_binding_v1(
    row: CanonicalAccountCreationBindingModel,
    allocation: CanonicalAccountCreationAllocation | None,
) -> CanonicalAccountCreationBinding:
    if allocation is None:
        raise CanonicalAccountCreationBindingV2Corruption("Binding-v1 allocation is orphaned")
    try:
        return _restore_binding(row, allocation)
    except Exception as error:
        raise CanonicalAccountCreationBindingV2Corruption(
            "Binding-v1 ledger cannot be restored"
        ) from error


def _restore_root(
    row: AllocatedPhysicalAccountRowObservationV3Model,
) -> AllocatedPhysicalAccountRowObservationV3:
    try:
        record = decode_allocated_physical_account_row_observation_v3_record(row.canonical_payload)
        expected = _creation_root_values(record, recorded_at=record.observation.recorded_at)
    except (AllocatedPhysicalAccountRowObservationV3CodecError, TypeError, ValueError) as error:
        raise CanonicalAccountCreationBindingV2Corruption(
            "creation-root ledger cannot be restored"
        ) from error
    _match_row(row, expected, "creation-root")
    return record.observation


def _restore_binding_v2_row(
    row: CanonicalAccountCreationBindingV2Model,
    allocations: dict[int | None, CanonicalAccountCreationAllocation],
    roots: dict[int | None, AllocatedPhysicalAccountRowObservationV3],
) -> CanonicalAccountCreationBindingV2:
    try:
        value = decode_canonical_account_creation_binding_v2(row.canonical_payload)
    except CanonicalAccountCreationBindingV2CodecError as error:
        raise CanonicalAccountCreationBindingV2Corruption(
            "Binding-v2 payload cannot be restored"
        ) from error
    if (
        allocations.get(_fk_id(row, "allocation_id")) != value.allocation
        or roots.get(_fk_id(row, "creation_root_id")) != value.creation_root
    ):
        raise CanonicalAccountCreationBindingV2Corruption("Binding-v2 foreign evidence differs")
    expected = _binding_v2_values(
        value,
        claim_content_hash=row.consumption_claim_content_hash,
        claim_pk=_fk_id(row, "consumption_claim_id"),
        allocation_pk=_fk_id(row, "allocation_id"),
        root_pk=_fk_id(row, "creation_root_id"),
    )
    _match_row(row, expected, "Binding-v2")
    return value


def _restore_claim_row(
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
        raise CanonicalAccountCreationBindingV2Corruption("claim consumer is orphaned")
    try:
        value = decode_canonical_account_creation_consumption_claim(
            row.canonical_payload, consumer=consumer
        )
    except CanonicalAccountCreationConsumptionCodecError as error:
        raise CanonicalAccountCreationBindingV2Corruption(
            "claim payload cannot be restored"
        ) from error
    allocation_fk = _fk_id(row, "allocation_id")
    if allocations.get(allocation_fk) != value.allocation:
        raise CanonicalAccountCreationBindingV2Corruption("claim allocation differs")
    _match_row(row, _claim_values(value, allocation_pk=allocation_fk), "claim")
    return value


def _claim_values(
    value: CanonicalAccountCreationConsumptionClaim, *, allocation_pk: int | None
) -> dict[str, object]:
    if allocation_pk is None:
        raise CanonicalAccountCreationBindingV2Corruption(
            "claim allocation has no database identity"
        )
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


def _binding_v2_values(
    value: CanonicalAccountCreationBindingV2,
    *,
    claim_content_hash: str,
    claim_pk: int | None,
    allocation_pk: int | None,
    root_pk: int | None,
) -> dict[str, object]:
    if None in (claim_pk, allocation_pk, root_pk):
        raise CanonicalAccountCreationBindingV2Corruption(
            "Binding-v2 foreign evidence has no database identity"
        )
    payload = encode_canonical_account_creation_binding_v2(value)
    creation_root_payload = cast(dict[str, object], payload["creation_root"])
    recorder = value.recorded_by
    values: dict[str, object] = {
        "consumption_claim_id": claim_pk,
        "consumption_claim_content_hash": claim_content_hash,
        "allocation_id": allocation_pk,
        "allocation_identity_hash": value.allocation.identity_hash,
        "allocation_content_hash": value.allocation.content_hash,
        "creation_root_id": root_pk,
        "owner": value.owner,
        "artifact_type": value.artifact_type,
        "schema": value.schema,
        "binding_id": value.binding_id,
        "binding_version": value.binding_version,
        "creation_root_observation_id": value.creation_root.observation_id,
        "creation_root_observation_version": value.creation_root.observation_version,
        "creation_root_identity_hash": value.creation_root_identity_hash,
        "creation_root_content_hash": value.creation_root_content_hash,
        "physical_observation_content_hash": value.physical_observation_content_hash,
        "physical_source_content_hash": value.physical_source_content_hash,
        "physical_raw_observation_content_hash": value.physical_raw_observation_content_hash,
        "account_namespace_claim": value.account_namespace_claim,
        "account_id_claim": value.account_id_claim,
        "underlying_unified_account_namespace_claim": value.underlying_unified_account_namespace_claim,
        "underlying_unified_account_id_claim": value.underlying_unified_account_id_claim,
        "recorded_service_id": recorder.service_id,
        "recorded_role": recorder.role,
        "recorded_kind": recorder.kind,
        "recorded_is_automated": recorder.is_automated,
        "recorded_at": value.recorded_at,
        "account_claim_hash": value.account_claim_hash,
        "underlying_claim_hash": value.underlying_claim_hash,
        "permission": value.permission,
        "status": value.status,
        "binding_state": value.binding_state,
        "owner_assignment_state": value.owner_assignment_state,
        "canonical_payload": payload,
        "identity_hash": value.identity_hash,
        "content_hash": value.content_hash,
        "consumption_claim_binding_seal": _hash({"claim_content_hash": claim_content_hash}),
        "allocation_binding_seal": _hash(payload["allocation"]),
        "creation_root_binding_seal": _hash(payload["creation_root"]),
        "physical_binding_seal": _hash(creation_root_payload["physical_observation"]),
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
        "record_seal": _hash(
            {"binding": payload, "consumption_claim_content_hash": claim_content_hash}
        ),
        "persisted_at": value.recorded_at,
    }
    values["ledger_seal"] = _hash(
        {
            name: values[name]
            for name in (
                "record_seal",
                "consumption_claim_binding_seal",
                "allocation_binding_seal",
                "creation_root_binding_seal",
                "physical_binding_seal",
                "recorder_binding_seal",
                "fixed_authority_seal",
            )
        }
        | {"persisted_at": _time(value.recorded_at)}
    )
    return values


def _match_row(row: object, expected: dict[str, object], label: str) -> None:
    for name, value in expected.items():
        if getattr(row, name) != value:
            raise CanonicalAccountCreationBindingV2Corruption(f"{label} ledger mismatch: {name}")


def _exact_allocation_row(
    world: _World, value: CanonicalAccountCreationAllocation
) -> CanonicalAccountCreationAllocationModel:
    matches = tuple(row for row, restored in world.allocations if restored == value)
    result = _single(matches, "exact allocation")
    if result is None:
        raise CanonicalAccountCreationBindingV2Conflict("exact allocation is unavailable")
    return result


def _exact_root_row(
    world: _World, value: AllocatedPhysicalAccountRowObservationV3
) -> AllocatedPhysicalAccountRowObservationV3Model:
    matches = tuple(row for row, restored in world.roots if restored == value)
    result = _single(matches, "exact creation root")
    if result is None:
        raise CanonicalAccountCreationBindingV2Conflict("exact creation root is unavailable")
    return result


def _claim_by_pk(world: _World, pk: int | None) -> CanonicalAccountCreationConsumptionClaim | None:
    return next((value for row, value in world.claims if row.pk == pk), None)


def _claim_anchor_matches(
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
        or value.physical_v3_root_content_hash == anchors["physical_v3_hash"]
    )


def _legacy_anchor_matches(value: CanonicalAccountCreationBinding, **anchors: object) -> bool:
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
    left: CanonicalAccountCreationConsumptionClaim, right: CanonicalAccountCreationConsumptionClaim
) -> bool:
    return _claim_anchor_matches(
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
        physical_v3_hash=right.physical_v3_root_content_hash,
    )


def _bindings_v2_overlap(
    left: CanonicalAccountCreationBindingV2, right: CanonicalAccountCreationBindingV2
) -> bool:
    return (
        (left.binding_id, left.binding_version) == (right.binding_id, right.binding_version)
        or left.identity_hash == right.identity_hash
        or left.content_hash == right.content_hash
        or left.creation_root.content_hash == right.creation_root.content_hash
    )


def _binding_v2(value: object) -> CanonicalAccountCreationBindingV2:
    if type(value) is not CanonicalAccountCreationBindingV2:
        raise CanonicalAccountCreationBindingV2Corruption("Binding-v2 type substitution")
    try:
        value.__post_init__()
    except (TypeError, ValueError) as error:
        raise CanonicalAccountCreationBindingV2Corruption("Binding-v2 is invalid") from error
    return value


def _claim(value: object) -> CanonicalAccountCreationConsumptionClaim:
    if type(value) is not CanonicalAccountCreationConsumptionClaim:
        raise CanonicalAccountCreationBindingV2Corruption("claim type substitution")
    try:
        value.__post_init__()
    except (TypeError, ValueError) as error:
        raise CanonicalAccountCreationBindingV2Corruption("claim is invalid") from error
    return value


def _is_aware(value: object) -> bool:
    return type(value) is datetime and value.tzinfo is not None and value.utcoffset() is not None


def _fk_id(row: object, name: str) -> int | None:
    value = getattr(row, name)
    if value is None:
        return None
    if type(value) is not int or value <= 0:
        raise CanonicalAccountCreationBindingV2Corruption(f"{name} is invalid")
    return value


def _single(values: tuple[_ValueT, ...], label: str) -> _ValueT | None:
    if len(values) > 1:
        raise CanonicalAccountCreationBindingV2Corruption(f"{label} is ambiguous")
    return values[0] if values else None


def _hash(payload: object) -> str:
    return hashlib.sha256(
        json.dumps(
            payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
        ).encode()
    ).hexdigest()


def _time(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


__all__ = [
    "CanonicalAccountCreationConsumptionClock",
    "DjangoCanonicalAccountCreationConsumptionClock",
    "DjangoCanonicalAccountCreationConsumptionRepository",
]
