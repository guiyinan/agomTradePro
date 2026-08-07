"""Append-only ORM ledgers for approved R7 sample policies."""

from __future__ import annotations

from collections.abc import Collection, Iterable, Iterator, Mapping
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from typing import NoReturn, TypeVar

from django.core.exceptions import ValidationError
from django.db import models
from django.db.models.base import ModelBase

from shared.infrastructure.django_append_only import AppendOnlyManager, AppendOnlyQuerySet

_ModelT = TypeVar("_ModelT", bound=models.Model)
_ACTIVE_R7_POLICY_UOW: ContextVar[object | None] = ContextVar(
    "active_r7_sample_policy_uow",
    default=None,
)


@dataclass(frozen=True)
class _R7PolicyInsertClaim:
    token: object
    model_type: type[models.Model]
    expected_values: tuple[tuple[str, object], ...]


_ACTIVE_R7_POLICY_CLAIM: ContextVar[_R7PolicyInsertClaim | None] = ContextVar(
    "active_r7_sample_policy_claim",
    default=None,
)


def _require_active_r7_sample_policy_uow() -> object:
    """Require a repository-owned transaction before owner rereads."""

    token = _ACTIVE_R7_POLICY_UOW.get()
    if token is None:
        raise ValidationError("R7 sample policy owner query requires an active unit of work.")
    return token


@contextmanager
def _activate_r7_sample_policy_uow(token: object) -> Iterator[None]:
    reset = _ACTIVE_R7_POLICY_UOW.set(token)
    try:
        yield
    finally:
        _ACTIVE_R7_POLICY_UOW.reset(reset)


@contextmanager
def _claim_r7_sample_policy_insert(
    *,
    token: object,
    model_type: type[models.Model],
    expected_values: Mapping[str, object],
) -> Iterator[None]:
    if _ACTIVE_R7_POLICY_UOW.get() is not token:
        raise ValidationError("R7 sample policy insert requires its repository unit of work.")
    claim = _R7PolicyInsertClaim(
        token=token,
        model_type=model_type,
        expected_values=tuple(sorted(expected_values.items(), key=lambda item: item[0])),
    )
    reset = _ACTIVE_R7_POLICY_CLAIM.set(claim)
    try:
        yield
    finally:
        _ACTIVE_R7_POLICY_CLAIM.reset(reset)


class R7SamplePolicyQuerySet(AppendOnlyQuerySet[_ModelT]):
    """Reject every bulk insert shortcut."""

    def bulk_create(
        self,
        objs: Iterable[_ModelT],
        batch_size: int | None = None,
        ignore_conflicts: bool = False,
        update_conflicts: bool = False,
        update_fields: Collection[str] | None = None,
        unique_fields: Collection[str] | None = None,
    ) -> NoReturn:
        raise ValidationError("R7 sample policies require exact repository appends.")


class R7SamplePolicyManager(AppendOnlyManager[_ModelT]):
    """Expose identical guards through default, base, and related managers."""

    def get_queryset(self) -> R7SamplePolicyQuerySet[_ModelT]:
        return R7SamplePolicyQuerySet(self.model, using=self._db)

    def bulk_create(
        self,
        objs: Iterable[_ModelT],
        batch_size: int | None = None,
        ignore_conflicts: bool = False,
        update_conflicts: bool = False,
        update_fields: Collection[str] | None = None,
        unique_fields: Collection[str] | None = None,
    ) -> NoReturn:
        raise ValidationError("R7 sample policies require exact repository appends.")


class R7SamplePolicyAppendOnlyModel(models.Model):
    """Permit only an exact claimed insert with a database-assigned key."""

    objects = R7SamplePolicyManager()

    class Meta:
        abstract = True
        base_manager_name = "objects"
        default_manager_name = "objects"

    def save(
        self,
        *,
        force_insert: bool | tuple[ModelBase, ...] = False,
        force_update: bool = False,
        using: str | None = None,
        update_fields: Iterable[str] | None = None,
    ) -> None:
        if force_update or update_fields is not None or self.pk is not None:
            raise ValidationError("R7 sample policy evidence is append-only.")
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
            raise ValidationError("R7 sample policy evidence is append-only.")
        self._require_claim()
        super().save_base(
            raw=False,
            force_insert=force_insert,
            force_update=False,
            using=using,
            update_fields=None,
        )

    def _require_claim(self) -> None:
        claim = _ACTIVE_R7_POLICY_CLAIM.get()
        if (
            claim is None
            or claim.token is not _ACTIVE_R7_POLICY_UOW.get()
            or claim.model_type is not type(self)
            or any(
                getattr(self, field_name) != expected
                for field_name, expected in claim.expected_values
            )
        ):
            raise ValidationError("R7 sample policy requires an exact insert claim.")

    def delete(
        self,
        using: object | None = None,
        keep_parents: bool = False,
    ) -> tuple[int, dict[str, int]]:
        raise ValidationError("R7 sample policy evidence cannot be deleted.")


class R7SamplePolicyApprovalReceiptModel(R7SamplePolicyAppendOnlyModel):
    """Research copy of one exact external-owner authorization receipt."""

    authorization_id = models.CharField(max_length=192)
    authorization_version = models.CharField(max_length=192)
    owner_record_id = models.CharField(max_length=192)
    owner_record_version = models.CharField(max_length=192)
    owner_record_hash = models.CharField(max_length=64)
    policy_id = models.CharField(max_length=192)
    policy_version = models.CharField(max_length=192)
    scope_content_hash = models.CharField(max_length=64, db_index=True)
    policy_definition_hash = models.CharField(max_length=64)
    approved_by = models.CharField(max_length=192)
    issued_at = models.DateTimeField()
    valid_until = models.DateTimeField()
    recorded_at = models.DateTimeField(db_index=True)
    canonical_payload = models.JSONField()
    authorization_content_hash = models.CharField(max_length=64, unique=True)
    record_hash = models.CharField(max_length=64, unique=True)
    persisted_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "research_r7_sample_policy_approval"
        base_manager_name = "objects"
        default_manager_name = "objects"
        constraints = [
            models.UniqueConstraint(
                fields=["authorization_id", "authorization_version"],
                name="res_r7_auth_identity_uq",
            ),
            models.UniqueConstraint(
                fields=["owner_record_id", "owner_record_version"],
                name="res_r7_auth_owner_uq",
            ),
            models.UniqueConstraint(
                fields=["policy_id", "policy_version"],
                name="res_r7_auth_policy_uq",
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(issued_at__lte=models.F("recorded_at"))
                    & models.Q(recorded_at__lt=models.F("valid_until"))
                ),
                name="res_r7_auth_clock_ck",
            ),
        ]


class R7SamplePolicyModel(R7SamplePolicyAppendOnlyModel):
    """Canonical scope-bound R7 sample policy and immutable safety seal."""

    approval = models.OneToOneField(
        R7SamplePolicyApprovalReceiptModel,
        on_delete=models.PROTECT,
        related_name="sample_policy",
    )
    policy_id = models.CharField(max_length=192)
    policy_version = models.CharField(max_length=192)
    scope_content_hash = models.CharField(max_length=64, db_index=True)
    policy_content_hash = models.CharField(max_length=64, unique=True)
    authorization_content_hash = models.CharField(max_length=64)
    activated_at = models.DateTimeField(db_index=True)
    valid_until = models.DateTimeField(db_index=True)
    sample_window_start = models.DateTimeField()
    sample_window_end = models.DateTimeField()
    forecast_horizon_seconds = models.DecimalField(max_digits=30, decimal_places=6)
    censoring_lag_seconds = models.DecimalField(max_digits=30, decimal_places=6)
    censoring_rule_version = models.CharField(max_length=192)
    minimum_forecasts_per_revision = models.PositiveIntegerField()
    minimum_resolved_outcomes_per_revision = models.PositiveIntegerField()
    minimum_binary_class_observations = models.PositiveIntegerField()
    minimum_multiclass_groups = models.PositiveIntegerField()
    minimum_multiclass_class_observations = models.PositiveIntegerField()
    minimum_historical_analogies = models.PositiveIntegerField()
    minimum_path_probability_observations = models.PositiveIntegerField()
    path_horizon_periods = models.PositiveIntegerField()
    require_all_path_initial_states = models.BooleanField()
    recorded_at = models.DateTimeField(db_index=True)
    canonical_payload = models.JSONField()
    content_hash = models.CharField(max_length=64, unique=True)
    research_only = models.BooleanField(default=True)
    must_not_use_for_decision = models.BooleanField(default=True)
    must_not_execute = models.BooleanField(default=True)
    persisted_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "research_r7_sample_policy"
        base_manager_name = "objects"
        default_manager_name = "objects"
        indexes = [
            models.Index(
                fields=["scope_content_hash", "recorded_at"],
                name="res_r7_policy_pit_ix",
            )
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["policy_id", "policy_version"],
                name="res_r7_policy_identity_uq",
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(recorded_at__lte=models.F("activated_at"))
                    & models.Q(activated_at__lt=models.F("valid_until"))
                    & models.Q(sample_window_start__lt=models.F("sample_window_end"))
                ),
                name="res_r7_policy_clock_ck",
            ),
            models.CheckConstraint(
                condition=models.Q(
                    research_only=True,
                    must_not_use_for_decision=True,
                    must_not_execute=True,
                ),
                name="res_r7_policy_safety_ck",
            ),
        ]


__all__ = ["R7SamplePolicyApprovalReceiptModel", "R7SamplePolicyModel"]
