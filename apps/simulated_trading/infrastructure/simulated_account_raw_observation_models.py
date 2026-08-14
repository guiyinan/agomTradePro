"""Append-only storage model for raw SimulatedAccount row observations."""

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
_ACTIVE_SIMULATED_ACCOUNT_RAW_OBSERVATION_UOW: ContextVar[object | None] = ContextVar(
    "active_simulated_account_raw_observation_uow", default=None
)


@dataclass(frozen=True)
class _SimulatedAccountRawObservationInsertClaim:
    token: object
    model_type: type[models.Model]
    expected_values: tuple[tuple[str, object], ...]


_ACTIVE_SIMULATED_ACCOUNT_RAW_OBSERVATION_CLAIM: ContextVar[
    _SimulatedAccountRawObservationInsertClaim | None
] = ContextVar("active_simulated_account_raw_observation_claim", default=None)


@contextmanager
def _activate_simulated_account_raw_observation_uow(token: object) -> Iterator[None]:
    """Activate only this ledger's private unit-of-work token."""

    reset = _ACTIVE_SIMULATED_ACCOUNT_RAW_OBSERVATION_UOW.set(token)
    try:
        yield
    finally:
        _ACTIVE_SIMULATED_ACCOUNT_RAW_OBSERVATION_UOW.reset(reset)


@contextmanager
def _claim_simulated_account_raw_observation_insert(
    *,
    token: object,
    model_type: type[models.Model],
    expected_values: Mapping[str, object],
) -> Iterator[None]:
    """Claim one exact repository-controlled raw-observation insert."""

    if _ACTIVE_SIMULATED_ACCOUNT_RAW_OBSERVATION_UOW.get() is not token:
        raise ValidationError("Raw observation insert requires its private UOW.")
    reset = _ACTIVE_SIMULATED_ACCOUNT_RAW_OBSERVATION_CLAIM.set(
        _SimulatedAccountRawObservationInsertClaim(
            token, model_type, tuple(sorted(expected_values.items()))
        )
    )
    try:
        yield
    finally:
        _ACTIVE_SIMULATED_ACCOUNT_RAW_OBSERVATION_CLAIM.reset(reset)


class SimulatedAccountRawObservationQuerySet(AppendOnlyQuerySet[_ModelT]):
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
        raise ValidationError("Raw observations require exact repository appends.")

    def _update(self, values: list[tuple[object, object, object]]) -> NoReturn:
        raise ValidationError("Raw observations cannot be updated.")

    def _raw_delete(self, using: str | None) -> NoReturn:
        raise ValidationError("Raw observations cannot be deleted.")


class SimulatedAccountRawObservationManager(AppendOnlyManager[_ModelT]):
    """Expose strict append-only guards through every manager path."""

    def get_queryset(self) -> SimulatedAccountRawObservationQuerySet[_ModelT]:
        return SimulatedAccountRawObservationQuerySet(self.model, using=self._db)

    def bulk_create(
        self,
        objs: Iterable[_ModelT],
        batch_size: int | None = None,
        ignore_conflicts: bool = False,
        update_conflicts: bool = False,
        update_fields: Collection[str] | None = None,
        unique_fields: Collection[str] | None = None,
    ) -> NoReturn:
        raise ValidationError("Raw observations require exact repository appends.")


class SimulatedAccountRawObservationModel(models.Model):
    """One immutable owner-observed physical SimulatedAccount row record."""

    objects = SimulatedAccountRawObservationManager()

    owner = models.CharField(max_length=32)
    artifact_type = models.CharField(max_length=64)
    schema = models.CharField(max_length=64)
    observation_id = models.CharField(max_length=192)
    observation_version = models.CharField(max_length=192)
    row_pk = models.PositiveBigIntegerField()
    row_user_id = models.PositiveBigIntegerField(null=True, blank=True)
    raw_account_type = models.CharField(max_length=192)
    is_active = models.BooleanField()
    row_created_at = models.DateTimeField()
    row_updated_at = models.DateTimeField()
    is_present = models.BooleanField()
    is_tombstone = models.BooleanField()
    observed_at = models.DateTimeField()
    valid_until = models.DateTimeField(db_index=True)
    supersedes_content_hash = models.CharField(max_length=64, null=True, blank=True)
    root_claim_hash = models.CharField(max_length=64, null=True, blank=True)
    permission = models.CharField(max_length=32)
    status = models.CharField(max_length=16)
    canonical_payload = models.JSONField()
    identity_hash = models.CharField(max_length=64, unique=True)
    content_hash = models.CharField(max_length=64, unique=True)
    authority_seal = models.CharField(max_length=64)
    row_seal = models.CharField(max_length=64)
    clock_seal = models.CharField(max_length=64)
    record_seal = models.CharField(max_length=64, unique=True)
    ledger_seal = models.CharField(max_length=64, unique=True)
    recorded_at = models.DateTimeField(db_index=True)
    persisted_at = models.DateTimeField()

    class Meta:
        app_label = "simulated_trading"
        db_table = "simulated_account_raw_observation_ledger"
        base_manager_name = "objects"
        default_manager_name = "objects"
        indexes = [
            models.Index(
                fields=("observation_id", "row_pk", "recorded_at"),
                name="sim_raw_obs_chain_ix",
            )
        ]
        constraints = [
            models.UniqueConstraint(
                fields=("observation_id", "observation_version"),
                name="sim_raw_obs_identity_uq",
            ),
            models.UniqueConstraint(
                fields=("root_claim_hash",),
                condition=models.Q(root_claim_hash__isnull=False),
                name="sim_raw_obs_root_uq",
            ),
            models.UniqueConstraint(
                fields=("supersedes_content_hash",),
                condition=models.Q(supersedes_content_hash__isnull=False),
                name="sim_raw_obs_next_uq",
            ),
            models.CheckConstraint(
                condition=models.Q(
                    owner="simulated_trading",
                    artifact_type="simulated_account_raw_observation",
                    schema="simulated-account-raw-observation.v1",
                    permission="evidence_only",
                    status="inactive",
                ),
                name="sim_raw_obs_fixed_ck",
            ),
            models.CheckConstraint(
                condition=models.Q(
                    row_created_at__lte=models.F("row_updated_at"),
                    row_updated_at__lte=models.F("observed_at"),
                    observed_at__lte=models.F("recorded_at"),
                    recorded_at__lt=models.F("valid_until"),
                    persisted_at=models.F("recorded_at"),
                ),
                name="sim_raw_obs_clock_ck",
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(is_present=True, is_tombstone=False)
                    | models.Q(is_present=False, is_tombstone=True)
                ),
                name="sim_raw_obs_presence_ck",
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(
                        supersedes_content_hash__isnull=True,
                        root_claim_hash__isnull=False,
                    )
                    | models.Q(
                        supersedes_content_hash__isnull=False,
                        root_claim_hash__isnull=True,
                    )
                ),
                name="sim_raw_obs_link_ck",
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
        """Permit only one exact repository-claimed insert."""

        if force_update or update_fields is not None or self.pk is not None:
            raise ValidationError("Raw observations are append-only.")
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
        """Reject raw fixture and update bypasses."""

        if raw or force_update or update_fields is not None or self.pk is not None:
            raise ValidationError("Raw observations are append-only.")
        self._require_claim()
        super().save_base(force_insert=force_insert, using=using)

    def _require_claim(self) -> None:
        claim = _ACTIVE_SIMULATED_ACCOUNT_RAW_OBSERVATION_CLAIM.get()
        if (
            claim is None
            or claim.token is not _ACTIVE_SIMULATED_ACCOUNT_RAW_OBSERVATION_UOW.get()
            or claim.model_type is not type(self)
            or any(getattr(self, name) != expected for name, expected in claim.expected_values)
        ):
            raise ValidationError("Raw observation requires an exact insert claim.")

    def delete(
        self, using: object | None = None, keep_parents: bool = False
    ) -> tuple[int, dict[str, int]]:
        """Reject instance deletion."""

        raise ValidationError("Raw observations cannot be deleted.")


def _reject_simulated_account_raw_observation_delete(
    sender: type[models.Model],
    instance: models.Model,
    using: str,
    origin: object,
    **kwargs: object,
) -> None:
    """Reject collector deletion paths."""

    del sender, instance, using, origin, kwargs
    raise ValidationError("Raw observations cannot be deleted.")


pre_delete.connect(
    _reject_simulated_account_raw_observation_delete,
    sender=SimulatedAccountRawObservationModel,
    dispatch_uid="reject_simulated_account_raw_observation_delete",
    weak=False,
)


__all__ = ["SimulatedAccountRawObservationModel"]
