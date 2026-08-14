"""Append-only storage model for allocated Account Physical-v3 roots."""

from __future__ import annotations

from collections.abc import Collection, Iterable, Iterator, Mapping
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from typing import NoReturn, TypeVar

from django.core.exceptions import ValidationError
from django.db import models
from django.db.models.base import ModelBase
from django.db.models.signals import pre_delete

from shared.infrastructure.django_append_only import AppendOnlyManager, AppendOnlyQuerySet

_ModelT = TypeVar("_ModelT", bound=models.Model)
_ACTIVE_ALLOCATED_PHYSICAL_V3_UOW: ContextVar[object | None] = ContextVar(
    "active_allocated_physical_account_row_observation_v3_uow",
    default=None,
)


@dataclass(frozen=True)
class _AllocatedPhysicalV3InsertClaim:
    token: object
    model_type: type[models.Model]
    expected_values: tuple[tuple[str, object], ...]


_ACTIVE_ALLOCATED_PHYSICAL_V3_CLAIM: ContextVar[_AllocatedPhysicalV3InsertClaim | None] = (
    ContextVar(
        "active_allocated_physical_account_row_observation_v3_claim",
        default=None,
    )
)


@contextmanager
def _activate_allocated_physical_account_row_observation_v3_uow(
    token: object,
) -> Iterator[None]:
    """Activate only this ledger's private unit-of-work token."""

    reset = _ACTIVE_ALLOCATED_PHYSICAL_V3_UOW.set(token)
    try:
        yield
    finally:
        _ACTIVE_ALLOCATED_PHYSICAL_V3_UOW.reset(reset)


@contextmanager
def _claim_allocated_physical_account_row_observation_v3_insert(
    *,
    token: object,
    model_type: type[models.Model],
    expected_values: Mapping[str, object],
) -> Iterator[None]:
    """Claim one exact repository-controlled creation-root insert."""

    if _ACTIVE_ALLOCATED_PHYSICAL_V3_UOW.get() is not token:
        raise ValidationError("allocated Physical-v3 insert requires its private UOW")
    reset = _ACTIVE_ALLOCATED_PHYSICAL_V3_CLAIM.set(
        _AllocatedPhysicalV3InsertClaim(
            token=token,
            model_type=model_type,
            expected_values=tuple(sorted(expected_values.items())),
        )
    )
    try:
        yield
    finally:
        _ACTIVE_ALLOCATED_PHYSICAL_V3_CLAIM.reset(reset)


class AllocatedPhysicalAccountRowObservationV3QuerySet(AppendOnlyQuerySet[_ModelT]):
    """Reject every bulk insert, mutation, and raw deletion shortcut."""

    def bulk_create(
        self,
        objs: Iterable[_ModelT],
        batch_size: int | None = None,
        ignore_conflicts: bool = False,
        update_conflicts: bool = False,
        update_fields: Collection[str] | None = None,
        unique_fields: Collection[str] | None = None,
    ) -> NoReturn:
        raise ValidationError("allocated Physical-v3 requires exact repository appends")

    def _update(self, values: list[tuple[object, object, object]]) -> NoReturn:
        raise ValidationError("allocated Physical-v3 roots cannot be updated")

    def _raw_delete(self, using: str | None) -> NoReturn:
        raise ValidationError("allocated Physical-v3 roots cannot be deleted")


class AllocatedPhysicalAccountRowObservationV3Manager(AppendOnlyManager[_ModelT]):
    """Expose the strict creation-root guards through every manager path."""

    def get_queryset(
        self,
    ) -> AllocatedPhysicalAccountRowObservationV3QuerySet[_ModelT]:
        return AllocatedPhysicalAccountRowObservationV3QuerySet(
            self.model,
            using=self._db,
        )

    def bulk_create(
        self,
        objs: Iterable[_ModelT],
        batch_size: int | None = None,
        ignore_conflicts: bool = False,
        update_conflicts: bool = False,
        update_fields: Collection[str] | None = None,
        unique_fields: Collection[str] | None = None,
    ) -> NoReturn:
        raise ValidationError("allocated Physical-v3 requires exact repository appends")


class AllocatedPhysicalAccountRowObservationV3Model(models.Model):
    """One immutable service-projected allocated Physical-v3 creation root."""

    objects = AllocatedPhysicalAccountRowObservationV3Manager()

    owner = models.CharField(max_length=32)
    artifact_type = models.CharField(max_length=64)
    schema = models.CharField(max_length=64)
    observation_id = models.CharField(max_length=192)
    observation_version = models.CharField(max_length=192)
    allocation_id = models.CharField(max_length=192)
    allocation_version = models.CharField(max_length=192)
    allocation_identity_hash = models.CharField(max_length=64, unique=True)
    allocation_content_hash = models.CharField(max_length=64, unique=True)
    account_namespace = models.CharField(max_length=192)
    account_id = models.CharField(max_length=192)
    underlying_unified_account_namespace = models.CharField(max_length=192)
    underlying_unified_account_id = models.PositiveBigIntegerField()
    physical_observation_id = models.CharField(max_length=192)
    physical_observation_version = models.CharField(max_length=192)
    physical_identity_hash = models.CharField(max_length=64, unique=True)
    physical_content_hash = models.CharField(max_length=64, unique=True)
    recorded_at = models.DateTimeField(db_index=True)
    ttl_valid_until = models.DateTimeField()
    valid_until = models.DateTimeField(db_index=True)
    identity_anchor_kind = models.CharField(max_length=32)
    owner_assignment_state = models.CharField(max_length=32)
    permission = models.CharField(max_length=32)
    status = models.CharField(max_length=16)
    recorded_by_service_id = models.CharField(max_length=192)
    recorded_by_role = models.CharField(max_length=192)
    recorded_by_kind = models.CharField(max_length=16)
    recorded_by_is_automated = models.BooleanField()
    canonical_payload = models.JSONField()
    identity_hash = models.CharField(max_length=64, unique=True)
    content_hash = models.CharField(max_length=64, unique=True)
    identity_claim_hash = models.CharField(max_length=64, unique=True)
    allocation_claim_hash = models.CharField(max_length=64, unique=True)
    account_claim_hash = models.CharField(max_length=64, unique=True)
    underlying_claim_hash = models.CharField(max_length=64, unique=True)
    physical_claim_hash = models.CharField(max_length=64, unique=True)
    root_claim_hash = models.CharField(max_length=64, unique=True)
    allocation_binding_seal = models.CharField(max_length=64)
    physical_binding_seal = models.CharField(max_length=64)
    projector_binding_seal = models.CharField(max_length=64)
    fixed_authority_seal = models.CharField(max_length=64)
    clock_seal = models.CharField(max_length=64)
    record_seal = models.CharField(max_length=64, unique=True)
    ledger_seal = models.CharField(max_length=64, unique=True)
    persisted_at = models.DateTimeField()

    class Meta:
        app_label = "account"
        db_table = "account_allocated_physical_row_observation_v3_ledger"
        base_manager_name = "objects"
        default_manager_name = "objects"
        indexes = [
            models.Index(
                fields=(
                    "allocation_content_hash",
                    "account_namespace",
                    "account_id",
                    "recorded_at",
                ),
                name="acct_apv3_head_ix",
            )
        ]
        constraints = [
            models.UniqueConstraint(
                fields=("observation_id", "observation_version"),
                name="acct_apv3_obs_uq",
            ),
            models.UniqueConstraint(
                fields=("allocation_id", "allocation_version"),
                name="acct_apv3_alloc_id_uq",
            ),
            models.UniqueConstraint(
                fields=("account_namespace", "account_id"),
                name="acct_apv3_account_uq",
            ),
            models.UniqueConstraint(
                fields=(
                    "underlying_unified_account_namespace",
                    "underlying_unified_account_id",
                ),
                name="acct_apv3_under_uq",
            ),
            models.UniqueConstraint(
                fields=(
                    "physical_observation_id",
                    "physical_observation_version",
                ),
                name="acct_apv3_phys_id_uq",
            ),
            models.CheckConstraint(
                condition=models.Q(
                    owner="account",
                    artifact_type="allocated_physical_account_row_observation_v3",
                    schema="allocated-physical-account-row-observation.v3",
                    account_namespace="account",
                    identity_anchor_kind="creation_allocation",
                    owner_assignment_state="unknown",
                    permission="evidence_only",
                    status="inactive",
                    recorded_by_role="allocated_physical_creation_projector",
                    recorded_by_kind="service",
                    recorded_by_is_automated=True,
                ),
                name="acct_apv3_fixed_ck",
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(recorded_at__lt=models.F("ttl_valid_until"))
                    & models.Q(recorded_at__lt=models.F("valid_until"))
                    & models.Q(valid_until__lte=models.F("ttl_valid_until"))
                    & models.Q(persisted_at=models.F("recorded_at"))
                ),
                name="acct_apv3_clock_ck",
            ),
        ]

    def save(
        self,
        *,
        force_insert: bool | tuple[ModelBase, ...] = False,
        force_update: bool = False,
        using: str | None = None,
        update_fields: Iterable[str] | None = None,
    ) -> None:
        if force_update or update_fields is not None or self.pk is not None:
            raise ValidationError("allocated Physical-v3 roots are append-only")
        self._require_claim()
        super().save(force_insert=force_insert, using=using)

    def save_base(
        self,
        raw: bool = False,
        force_insert: bool | tuple[ModelBase, ...] = False,
        force_update: bool = False,
        using: str | None = None,
        update_fields: Iterable[str] | None = None,
    ) -> None:
        if raw or force_update or update_fields is not None or self.pk is not None:
            raise ValidationError("allocated Physical-v3 roots are append-only")
        self._require_claim()
        super().save_base(force_insert=force_insert, using=using)

    def _require_claim(self) -> None:
        claim = _ACTIVE_ALLOCATED_PHYSICAL_V3_CLAIM.get()
        if (
            claim is None
            or claim.token is not _ACTIVE_ALLOCATED_PHYSICAL_V3_UOW.get()
            or claim.model_type is not type(self)
            or any(getattr(self, name) != expected for name, expected in claim.expected_values)
        ):
            raise ValidationError("allocated Physical-v3 requires an exact insert claim")

    def delete(
        self,
        using: object | None = None,
        keep_parents: bool = False,
    ) -> tuple[int, dict[str, int]]:
        raise ValidationError("allocated Physical-v3 roots cannot be deleted")


def _reject_allocated_physical_account_row_observation_v3_delete(
    sender: type[models.Model],
    instance: models.Model,
    using: str,
    origin: object,
    **kwargs: object,
) -> None:
    del sender, instance, using, origin, kwargs
    raise ValidationError("allocated Physical-v3 roots cannot be deleted")


pre_delete.connect(
    _reject_allocated_physical_account_row_observation_v3_delete,
    sender=AllocatedPhysicalAccountRowObservationV3Model,
    dispatch_uid="reject_allocated_physical_account_row_observation_v3_delete",
    weak=False,
)


__all__ = ["AllocatedPhysicalAccountRowObservationV3Model"]
