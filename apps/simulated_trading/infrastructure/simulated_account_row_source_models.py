"""Append-only storage model for simulated account-row sources."""

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
_ACTIVE_SIMULATED_ACCOUNT_ROW_SOURCE_UOW: ContextVar[object | None] = ContextVar(
    "active_simulated_account_row_source_uow",
    default=None,
)


@dataclass(frozen=True)
class _SimulatedAccountRowSourceInsertClaim:
    token: object
    model_type: type[models.Model]
    expected_values: tuple[tuple[str, object], ...]


_ACTIVE_SIMULATED_ACCOUNT_ROW_SOURCE_CLAIM: ContextVar[
    _SimulatedAccountRowSourceInsertClaim | None
] = ContextVar(
    "active_simulated_account_row_source_claim",
    default=None,
)


@contextmanager
def _activate_simulated_account_row_source_uow(token: object) -> Iterator[None]:
    """Activate only this ledger's private unit-of-work token."""

    reset = _ACTIVE_SIMULATED_ACCOUNT_ROW_SOURCE_UOW.set(token)
    try:
        yield
    finally:
        _ACTIVE_SIMULATED_ACCOUNT_ROW_SOURCE_UOW.reset(reset)


@contextmanager
def _claim_simulated_account_row_source_insert(
    *,
    token: object,
    model_type: type[models.Model],
    expected_values: Mapping[str, object],
) -> Iterator[None]:
    """Claim one exact repository-controlled source insert."""

    if _ACTIVE_SIMULATED_ACCOUNT_ROW_SOURCE_UOW.get() is not token:
        raise ValidationError("Simulated account-row source insert requires its private UOW.")
    reset = _ACTIVE_SIMULATED_ACCOUNT_ROW_SOURCE_CLAIM.set(
        _SimulatedAccountRowSourceInsertClaim(
            token,
            model_type,
            tuple(sorted(expected_values.items())),
        )
    )
    try:
        yield
    finally:
        _ACTIVE_SIMULATED_ACCOUNT_ROW_SOURCE_CLAIM.reset(reset)


class SimulatedAccountRowSourceQuerySet(AppendOnlyQuerySet[_ModelT]):
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
        raise ValidationError("Simulated account-row sources require exact repository appends.")

    def _update(self, values: list[tuple[object, object, object]]) -> NoReturn:
        raise ValidationError("Simulated account-row sources cannot be updated.")

    def _raw_delete(self, using: str | None) -> NoReturn:
        raise ValidationError("Simulated account-row sources cannot be deleted.")


class SimulatedAccountRowSourceManager(AppendOnlyManager[_ModelT]):
    """Expose strict append-only guards through every manager path."""

    def get_queryset(self) -> SimulatedAccountRowSourceQuerySet[_ModelT]:
        return SimulatedAccountRowSourceQuerySet(self.model, using=self._db)

    def bulk_create(
        self,
        objs: Iterable[_ModelT],
        batch_size: int | None = None,
        ignore_conflicts: bool = False,
        update_conflicts: bool = False,
        update_fields: Collection[str] | None = None,
        unique_fields: Collection[str] | None = None,
    ) -> NoReturn:
        raise ValidationError("Simulated account-row sources require exact repository appends.")


class SimulatedAccountRowSourceModel(models.Model):
    """One immutable actor-bound SimulatedTrading source ledger record."""

    objects = SimulatedAccountRowSourceManager()

    owner = models.CharField(max_length=32)
    artifact_type = models.CharField(max_length=64)
    schema = models.CharField(max_length=64)
    source_id = models.CharField(max_length=192)
    source_version = models.CharField(max_length=192)
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
    observed_at = models.DateTimeField()
    recorded_at = models.DateTimeField(db_index=True)
    source_valid_until = models.DateTimeField()
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
    row_fact_hash = models.CharField(max_length=64)
    logical_binding_hash = models.CharField(max_length=64)
    actor_binding_hash = models.CharField(max_length=64, unique=True)
    record_header_hash = models.CharField(max_length=64, unique=True)
    ledger_header_hash = models.CharField(max_length=64, unique=True)
    persisted_at = models.DateTimeField()

    class Meta:
        app_label = "simulated_trading"
        db_table = "simulated_account_row_source_ledger"
        base_manager_name = "objects"
        default_manager_name = "objects"
        indexes = [
            models.Index(
                fields=("source_id", "account_namespace", "account_id", "recorded_at"),
                name="sim_row_src_chain_ix",
            )
        ]
        constraints = [
            models.UniqueConstraint(
                fields=("source_id", "source_version"),
                name="sim_row_src_identity_uq",
            ),
            models.UniqueConstraint(
                fields=("root_claim_hash",),
                condition=models.Q(root_claim_hash__isnull=False),
                name="sim_row_src_root_uq",
            ),
            models.UniqueConstraint(
                fields=("supersedes_content_hash",),
                condition=models.Q(supersedes_content_hash__isnull=False),
                name="sim_row_src_next_uq",
            ),
            models.CheckConstraint(
                condition=models.Q(
                    owner="simulated_trading",
                    artifact_type="simulated_account_row",
                    schema="simulated-account-row.v1",
                    owner_assignment_state="unknown",
                    permission="evidence_only",
                    status="inactive",
                    captured_actor_kind="human",
                    captured_actor_is_staff=True,
                ),
                name="sim_row_src_fixed_ck",
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(
                        row_created_at__lte=models.F("row_updated_at"),
                        row_updated_at__lte=models.F("observed_at"),
                        observed_at__lte=models.F("recorded_at"),
                        recorded_at__lt=models.F("valid_until"),
                        valid_until__lte=models.F("source_valid_until"),
                        persisted_at=models.F("recorded_at"),
                    )
                    & models.Q(valid_until__lte=models.F("ttl_valid_until"))
                ),
                name="sim_row_src_clock_ck",
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(is_present=True, is_tombstone=False)
                    | models.Q(is_present=False, is_tombstone=True)
                ),
                name="sim_row_src_presence_ck",
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
                name="sim_row_src_link_ck",
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
            raise ValidationError("Simulated account-row sources are append-only.")
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
            raise ValidationError("Simulated account-row sources are append-only.")
        self._require_claim()
        super().save_base(force_insert=force_insert, using=using)

    def _require_claim(self) -> None:
        claim = _ACTIVE_SIMULATED_ACCOUNT_ROW_SOURCE_CLAIM.get()
        if (
            claim is None
            or claim.token is not _ACTIVE_SIMULATED_ACCOUNT_ROW_SOURCE_UOW.get()
            or claim.model_type is not type(self)
            or any(getattr(self, name) != expected for name, expected in claim.expected_values)
        ):
            raise ValidationError("Simulated account-row source requires an exact insert claim.")

    def delete(
        self,
        using: object | None = None,
        keep_parents: bool = False,
    ) -> tuple[int, dict[str, int]]:
        """Reject instance deletion."""

        raise ValidationError("Simulated account-row sources cannot be deleted.")


def _reject_simulated_account_row_source_delete(
    sender: type[models.Model],
    instance: models.Model,
    using: str,
    origin: object,
    **kwargs: object,
) -> None:
    """Reject collector deletion paths."""

    del sender, instance, using, origin, kwargs
    raise ValidationError("Simulated account-row sources cannot be deleted.")


pre_delete.connect(
    _reject_simulated_account_row_source_delete,
    sender=SimulatedAccountRowSourceModel,
    dispatch_uid="reject_simulated_account_row_source_delete",
    weak=False,
)


__all__ = ["SimulatedAccountRowSourceModel"]
