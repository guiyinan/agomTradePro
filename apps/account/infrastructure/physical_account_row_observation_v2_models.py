"""Append-only storage model for Account physical-row v2 observations."""

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
_ACTIVE_ACCOUNT_ROW_V2_UOW: ContextVar[object | None] = ContextVar(
    "active_physical_account_row_observation_v2_uow", default=None
)


@dataclass(frozen=True)
class _AccountRowV2InsertClaim:
    token: object
    model_type: type[models.Model]
    expected_values: tuple[tuple[str, object], ...]


_ACTIVE_ACCOUNT_ROW_V2_CLAIM: ContextVar[_AccountRowV2InsertClaim | None] = ContextVar(
    "active_physical_account_row_observation_v2_claim", default=None
)


@contextmanager
def _activate_physical_account_row_observation_v2_uow(
    token: object,
) -> Iterator[None]:
    """Activate only this v2 ledger's private unit-of-work token."""

    reset = _ACTIVE_ACCOUNT_ROW_V2_UOW.set(token)
    try:
        yield
    finally:
        _ACTIVE_ACCOUNT_ROW_V2_UOW.reset(reset)


@contextmanager
def _claim_physical_account_row_observation_v2_insert(
    *,
    token: object,
    model_type: type[models.Model],
    expected_values: Mapping[str, object],
) -> Iterator[None]:
    """Claim one exact repository-controlled v2 insert."""

    if _ACTIVE_ACCOUNT_ROW_V2_UOW.get() is not token:
        raise ValidationError("Account row v2 insert requires its private UOW.")
    reset = _ACTIVE_ACCOUNT_ROW_V2_CLAIM.set(
        _AccountRowV2InsertClaim(token, model_type, tuple(sorted(expected_values.items())))
    )
    try:
        yield
    finally:
        _ACTIVE_ACCOUNT_ROW_V2_CLAIM.reset(reset)


class PhysicalAccountRowObservationV2QuerySet(AppendOnlyQuerySet[_ModelT]):
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
        raise ValidationError("Account row v2 requires exact repository appends.")

    def _update(self, values: list[tuple[object, object, object]]) -> NoReturn:
        raise ValidationError("Account row v2 observations cannot be updated.")

    def _raw_delete(self, using: str | None) -> NoReturn:
        raise ValidationError("Account row v2 observations cannot be deleted.")


class PhysicalAccountRowObservationV2Manager(AppendOnlyManager[_ModelT]):
    """Expose strict append-only guards through every manager path."""

    def get_queryset(self) -> PhysicalAccountRowObservationV2QuerySet[_ModelT]:
        return PhysicalAccountRowObservationV2QuerySet(self.model, using=self._db)

    def bulk_create(
        self,
        objs: Iterable[_ModelT],
        batch_size: int | None = None,
        ignore_conflicts: bool = False,
        update_conflicts: bool = False,
        update_fields: Collection[str] | None = None,
        unique_fields: Collection[str] | None = None,
    ) -> NoReturn:
        raise ValidationError("Account row v2 requires exact repository appends.")


class PhysicalAccountRowObservationV2Model(models.Model):
    """One immutable actor-bound Account v2 ledger record."""

    objects = PhysicalAccountRowObservationV2Manager()

    owner = models.CharField(max_length=32)
    artifact_type = models.CharField(max_length=64)
    schema = models.CharField(max_length=64)
    observation_id = models.CharField(max_length=192)
    observation_version = models.CharField(max_length=192)
    account_namespace = models.CharField(max_length=192)
    account_id = models.CharField(max_length=192)
    underlying_unified_account_namespace = models.CharField(max_length=192)
    underlying_unified_account_id = models.PositiveBigIntegerField()
    row_user_id = models.PositiveBigIntegerField(null=True, blank=True)
    raw_account_type = models.CharField(max_length=192)
    is_active = models.BooleanField()
    row_created_at = models.DateTimeField()
    row_updated_at = models.DateTimeField()
    is_present = models.BooleanField()
    is_tombstone = models.BooleanField()
    source_owner = models.CharField(max_length=32)
    source_artifact_type = models.CharField(max_length=64)
    source_schema = models.CharField(max_length=64)
    source_id = models.CharField(max_length=192)
    source_version = models.CharField(max_length=192)
    source_identity_hash = models.CharField(max_length=64)
    source_content_hash = models.CharField(max_length=64)
    source_supersedes_content_hash = models.CharField(max_length=64, null=True, blank=True)
    source_observed_at = models.DateTimeField()
    source_recorded_at = models.DateTimeField()
    source_valid_until = models.DateTimeField()
    source_ttl_valid_until = models.DateTimeField()
    source_effective_valid_until = models.DateTimeField()
    raw_observation_owner = models.CharField(max_length=32)
    raw_observation_artifact_type = models.CharField(max_length=64)
    raw_observation_schema = models.CharField(max_length=64)
    raw_observation_id = models.CharField(max_length=192)
    raw_observation_version = models.CharField(max_length=192)
    raw_observation_identity_hash = models.CharField(max_length=64)
    raw_observation_content_hash = models.CharField(max_length=64)
    raw_observation_supersedes_content_hash = models.CharField(max_length=64, null=True, blank=True)
    raw_observation_observed_at = models.DateTimeField()
    raw_observation_valid_until = models.DateTimeField()
    recorded_at = models.DateTimeField(db_index=True)
    ttl_valid_until = models.DateTimeField()
    valid_until = models.DateTimeField(db_index=True)
    owner_assignment_state = models.CharField(max_length=32)
    supersedes_content_hash = models.CharField(max_length=64, null=True, blank=True)
    root_claim_hash = models.CharField(max_length=64, null=True, blank=True)
    permission = models.CharField(max_length=32)
    status = models.CharField(max_length=16)
    captured_actor_id = models.CharField(max_length=192)
    captured_actor_user_id = models.PositiveBigIntegerField()
    captured_actor_role = models.CharField(max_length=192)
    captured_actor_kind = models.CharField(max_length=16)
    captured_actor_is_staff = models.BooleanField()
    canonical_payload = models.JSONField()
    identity_hash = models.CharField(max_length=64, unique=True)
    content_hash = models.CharField(max_length=64, unique=True)
    raw_binding_seal = models.CharField(max_length=64)
    source_binding_seal = models.CharField(max_length=64)
    row_seal = models.CharField(max_length=64)
    clock_seal = models.CharField(max_length=64)
    actor_binding_seal = models.CharField(max_length=64)
    record_seal = models.CharField(max_length=64, unique=True)
    ledger_seal = models.CharField(max_length=64, unique=True)
    persisted_at = models.DateTimeField()

    class Meta:
        app_label = "account"
        db_table = "account_physical_row_observation_v2_ledger"
        base_manager_name = "objects"
        default_manager_name = "objects"
        indexes = [
            models.Index(
                fields=("account_namespace", "account_id", "source_id", "recorded_at"),
                name="acct_phys_v2_chain_ix",
            )
        ]
        constraints = [
            models.UniqueConstraint(
                fields=("observation_id", "observation_version"),
                name="acct_phys_v2_obs_uq",
            ),
            models.UniqueConstraint(
                fields=("source_id", "source_version"),
                name="acct_phys_v2_src_uq",
            ),
            models.UniqueConstraint(
                fields=("root_claim_hash",),
                condition=models.Q(root_claim_hash__isnull=False),
                name="acct_phys_v2_root_uq",
            ),
            models.UniqueConstraint(
                fields=("supersedes_content_hash",),
                condition=models.Q(supersedes_content_hash__isnull=False),
                name="acct_phys_v2_next_uq",
            ),
            models.CheckConstraint(
                condition=models.Q(
                    owner="account",
                    artifact_type="physical_account_row_observation_v2",
                    schema="physical-account-row-observation.v2",
                    source_owner="simulated_trading",
                    source_artifact_type="simulated_account_row_v2",
                    source_schema="simulated-account-row.v2",
                    raw_observation_owner="simulated_trading",
                    raw_observation_artifact_type="simulated_account_raw_observation",
                    raw_observation_schema="simulated-account-raw-observation.v1",
                    owner_assignment_state="unknown",
                    permission="evidence_only",
                    status="inactive",
                    captured_actor_kind="human",
                    captured_actor_is_staff=True,
                ),
                name="acct_phys_v2_fixed_ck",
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(
                        row_created_at__lte=models.F("row_updated_at"),
                        row_updated_at__lte=models.F("source_observed_at"),
                        source_observed_at=models.F("raw_observation_observed_at"),
                        source_recorded_at__lte=models.F("recorded_at"),
                        recorded_at__lt=models.F("valid_until"),
                        source_valid_until=models.F("raw_observation_valid_until"),
                        valid_until__lte=models.F("source_effective_valid_until"),
                        persisted_at=models.F("recorded_at"),
                    )
                    & models.Q(valid_until__lte=models.F("ttl_valid_until"))
                ),
                name="acct_phys_v2_clock_ck",
            ),
            models.CheckConstraint(
                condition=models.Q(
                    source_id=models.F("raw_observation_id"),
                    source_version=models.F("raw_observation_version"),
                ),
                name="acct_phys_v2_raw_id_ck",
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(is_present=True, is_tombstone=False)
                    | models.Q(is_present=False, is_tombstone=True)
                ),
                name="acct_phys_v2_presence_ck",
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(
                        supersedes_content_hash__isnull=True,
                        root_claim_hash__isnull=False,
                        source_supersedes_content_hash__isnull=True,
                        raw_observation_supersedes_content_hash__isnull=True,
                    )
                    | models.Q(
                        supersedes_content_hash__isnull=False,
                        root_claim_hash__isnull=True,
                        source_supersedes_content_hash__isnull=False,
                        raw_observation_supersedes_content_hash__isnull=False,
                    )
                ),
                name="acct_phys_v2_link_ck",
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
            raise ValidationError("Account row v2 observations are append-only.")
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
            raise ValidationError("Account row v2 observations are append-only.")
        self._require_claim()
        super().save_base(force_insert=force_insert, using=using)

    def _require_claim(self) -> None:
        claim = _ACTIVE_ACCOUNT_ROW_V2_CLAIM.get()
        if (
            claim is None
            or claim.token is not _ACTIVE_ACCOUNT_ROW_V2_UOW.get()
            or claim.model_type is not type(self)
            or any(getattr(self, name) != expected for name, expected in claim.expected_values)
        ):
            raise ValidationError("Account row v2 requires an exact insert claim.")

    def delete(
        self, using: object | None = None, keep_parents: bool = False
    ) -> tuple[int, dict[str, int]]:
        raise ValidationError("Account row v2 observations cannot be deleted.")


def _reject_physical_account_row_observation_v2_delete(
    sender: type[models.Model],
    instance: models.Model,
    using: str,
    origin: object,
    **kwargs: object,
) -> None:
    del sender, instance, using, origin, kwargs
    raise ValidationError("Account row v2 observations cannot be deleted.")


pre_delete.connect(
    _reject_physical_account_row_observation_v2_delete,
    sender=PhysicalAccountRowObservationV2Model,
    dispatch_uid="reject_physical_account_row_observation_v2_delete",
    weak=False,
)


__all__ = ["PhysicalAccountRowObservationV2Model"]
