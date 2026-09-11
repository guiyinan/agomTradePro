"""Append-only storage for canonical Account ownership re-observation v1."""

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

from apps.account.infrastructure.canonical_account_creation_consumption_models import (
    CanonicalAccountCreationBindingV2Model,
)
from apps.account.infrastructure.physical_account_row_observation_v2_models import (
    PhysicalAccountRowObservationV2Model,
)
from shared.infrastructure.django_append_only import AppendOnlyManager, AppendOnlyQuerySet

_ModelT = TypeVar("_ModelT", bound=models.Model)
_ACTIVE_OWNERSHIP_REOBSERVATION_V1_UOW: ContextVar[object | None] = ContextVar(
    "active_canonical_account_ownership_reobservation_v1_uow", default=None
)


@dataclass(frozen=True)
class _OwnershipReobservationV1InsertClaim:
    token: object
    model_type: type[models.Model]
    expected_values: tuple[tuple[str, object], ...]


_ACTIVE_OWNERSHIP_REOBSERVATION_V1_CLAIM: ContextVar[
    _OwnershipReobservationV1InsertClaim | None
] = ContextVar("active_canonical_account_ownership_reobservation_v1_claim", default=None)


@contextmanager
def _activate_canonical_account_ownership_reobservation_v1_uow(
    token: object,
) -> Iterator[None]:
    """Activate only this ledger's private unit-of-work token."""

    reset = _ACTIVE_OWNERSHIP_REOBSERVATION_V1_UOW.set(token)
    try:
        yield
    finally:
        _ACTIVE_OWNERSHIP_REOBSERVATION_V1_UOW.reset(reset)


@contextmanager
def _claim_canonical_account_ownership_reobservation_v1_insert(
    *,
    token: object,
    model_type: type[models.Model],
    expected_values: Mapping[str, object],
) -> Iterator[None]:
    """Claim one exact repository-controlled insert."""

    if _ACTIVE_OWNERSHIP_REOBSERVATION_V1_UOW.get() is not token:
        raise ValidationError("Ownership re-observation v1 insert requires its private UOW.")
    reset = _ACTIVE_OWNERSHIP_REOBSERVATION_V1_CLAIM.set(
        _OwnershipReobservationV1InsertClaim(
            token, model_type, tuple(sorted(expected_values.items()))
        )
    )
    try:
        yield
    finally:
        _ACTIVE_OWNERSHIP_REOBSERVATION_V1_CLAIM.reset(reset)


class CanonicalAccountOwnershipReobservationV1QuerySet(AppendOnlyQuerySet[_ModelT]):
    """Reject bulk insertion, mutation, and raw deletion shortcuts."""

    def bulk_create(
        self,
        objs: Iterable[_ModelT],
        batch_size: int | None = None,
        ignore_conflicts: bool = False,
        update_conflicts: bool = False,
        update_fields: Collection[str] | None = None,
        unique_fields: Collection[str] | None = None,
    ) -> NoReturn:
        raise ValidationError("Ownership re-observation v1 requires exact appends.")

    def _update(self, values: list[tuple[object, object, object]]) -> NoReturn:
        raise ValidationError("Ownership re-observation v1 cannot be updated.")

    def _raw_delete(self, using: str | None) -> NoReturn:
        raise ValidationError("Ownership re-observation v1 cannot be deleted.")


class CanonicalAccountOwnershipReobservationV1Manager(AppendOnlyManager[_ModelT]):
    """Expose strict append-only guards through every manager path."""

    def get_queryset(self) -> CanonicalAccountOwnershipReobservationV1QuerySet[_ModelT]:
        return CanonicalAccountOwnershipReobservationV1QuerySet(self.model, using=self._db)

    def bulk_create(
        self,
        objs: Iterable[_ModelT],
        batch_size: int | None = None,
        ignore_conflicts: bool = False,
        update_conflicts: bool = False,
        update_fields: Collection[str] | None = None,
        unique_fields: Collection[str] | None = None,
    ) -> NoReturn:
        raise ValidationError("Ownership re-observation v1 requires exact appends.")


class CanonicalAccountOwnershipReobservationV1Model(models.Model):
    """One immutable Binding-v2 and Physical-v2 re-observation record."""

    objects = CanonicalAccountOwnershipReobservationV1Manager()

    binding = models.ForeignKey(
        CanonicalAccountCreationBindingV2Model,
        on_delete=models.PROTECT,
        related_name="ownership_reobservations_v1",
    )
    current_physical = models.ForeignKey(
        PhysicalAccountRowObservationV2Model,
        on_delete=models.PROTECT,
        related_name="ownership_reobservations_v1",
    )
    owner = models.CharField(max_length=32)
    artifact_type = models.CharField(max_length=96)
    schema = models.CharField(max_length=96)
    permission = models.CharField(max_length=32)
    status = models.CharField(max_length=16)
    observation_id = models.CharField(max_length=192)
    observation_version = models.CharField(max_length=192)
    binding_identity_hash = models.CharField(max_length=64)
    binding_content_hash = models.CharField(max_length=64)
    current_physical_identity_hash = models.CharField(max_length=64)
    current_physical_content_hash = models.CharField(max_length=64)
    recorded_at = models.DateTimeField(db_index=True)
    valid_until = models.DateTimeField(db_index=True)
    persisted_at = models.DateTimeField()
    canonical_payload = models.JSONField()
    identity_hash = models.CharField(max_length=64, unique=True)
    content_hash = models.CharField(max_length=64, unique=True)
    record_seal = models.CharField(max_length=64, unique=True)
    ledger_seal = models.CharField(max_length=64, unique=True)

    class Meta:
        app_label = "account"
        db_table = "canonical_account_ownership_reobservation_v1_ledger"
        base_manager_name = "objects"
        default_manager_name = "objects"
        indexes = [
            models.Index(
                fields=("binding", "recorded_at"),
                name="acct_reobs_v1_binding_time_ix",
            ),
            models.Index(
                fields=("current_physical", "recorded_at"),
                name="acct_reobs_v1_phys_time_ix",
            ),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=("observation_id", "observation_version"),
                name="acct_reobs_v1_obs_uq",
            ),
            models.CheckConstraint(
                condition=models.Q(
                    owner="account",
                    artifact_type="canonical_account_ownership_reobservation_v1",
                    schema="canonical-account-ownership-reobservation.v1",
                    permission="evidence_only",
                    status="inactive",
                ),
                name="acct_reobs_v1_fixed_ck",
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(recorded_at__lt=models.F("valid_until"))
                    & models.Q(persisted_at=models.F("recorded_at"))
                ),
                name="acct_reobs_v1_clock_ck",
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
            raise ValidationError("Ownership re-observation v1 is append-only.")
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
            raise ValidationError("Ownership re-observation v1 is append-only.")
        self._require_claim()
        super().save_base(force_insert=force_insert, using=using)

    def _require_claim(self) -> None:
        claim = _ACTIVE_OWNERSHIP_REOBSERVATION_V1_CLAIM.get()
        if (
            claim is None
            or claim.token is not _ACTIVE_OWNERSHIP_REOBSERVATION_V1_UOW.get()
            or claim.model_type is not type(self)
            or any(getattr(self, name) != expected for name, expected in claim.expected_values)
        ):
            raise ValidationError("Ownership re-observation v1 requires an exact insert claim.")

    def delete(
        self, using: object | None = None, keep_parents: bool = False
    ) -> tuple[int, dict[str, int]]:
        raise ValidationError("Ownership re-observation v1 cannot be deleted.")


def _reject_canonical_account_ownership_reobservation_v1_delete(
    sender: type[models.Model],
    instance: models.Model,
    using: str,
    origin: object,
    **kwargs: object,
) -> None:
    del sender, instance, using, origin, kwargs
    raise ValidationError("Ownership re-observation v1 cannot be deleted.")


pre_delete.connect(
    _reject_canonical_account_ownership_reobservation_v1_delete,
    sender=CanonicalAccountOwnershipReobservationV1Model,
    dispatch_uid="reject_canonical_account_ownership_reobservation_v1_delete",
    weak=False,
)


__all__ = ["CanonicalAccountOwnershipReobservationV1Model"]
