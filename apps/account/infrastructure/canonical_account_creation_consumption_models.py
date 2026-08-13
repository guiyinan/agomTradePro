"""Append-only consumption claims and durable Account creation bindings v2."""

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

from .allocated_physical_account_row_observation_v3_models import (
    AllocatedPhysicalAccountRowObservationV3Model,
)
from .canonical_account_creation_models import CanonicalAccountCreationAllocationModel

_ModelT = TypeVar("_ModelT", bound=models.Model)
_ACTIVE_CONSUMPTION_UOW: ContextVar[object | None] = ContextVar(
    "canonical_account_creation_consumption_uow",
    default=None,
)


@dataclass(frozen=True)
class _ConsumptionInsertClaim:
    token: object
    model_type: type[models.Model]
    expected_values: tuple[tuple[str, object], ...]


_ACTIVE_CONSUMPTION_CLAIM: ContextVar[_ConsumptionInsertClaim | None] = ContextVar(
    "canonical_account_creation_consumption_claim",
    default=None,
)


@contextmanager
def _activate_canonical_account_creation_consumption_uow(
    token: object,
) -> Iterator[None]:
    """Activate the private unit of work used by the consumption ledger only."""

    reset = _ACTIVE_CONSUMPTION_UOW.set(token)
    try:
        yield
    finally:
        _ACTIVE_CONSUMPTION_UOW.reset(reset)


@contextmanager
def _claim_canonical_account_creation_consumption_insert(
    *,
    token: object,
    model_type: type[models.Model],
    expected_values: Mapping[str, object],
) -> Iterator[None]:
    """Claim one exact repository-controlled consumption-ledger append."""

    if _ACTIVE_CONSUMPTION_UOW.get() is not token:
        raise ValidationError("canonical creation consumption insert requires private UOW")
    reset = _ACTIVE_CONSUMPTION_CLAIM.set(
        _ConsumptionInsertClaim(
            token=token,
            model_type=model_type,
            expected_values=tuple(sorted(expected_values.items())),
        )
    )
    try:
        yield
    finally:
        _ACTIVE_CONSUMPTION_CLAIM.reset(reset)


class CanonicalAccountCreationConsumptionQuerySet(AppendOnlyQuerySet[_ModelT]):
    """Reject bulk inserts and every mutation shortcut."""

    def bulk_create(
        self,
        objs: Iterable[_ModelT],
        batch_size: int | None = None,
        ignore_conflicts: bool = False,
        update_conflicts: bool = False,
        update_fields: Collection[str] | None = None,
        unique_fields: Collection[str] | None = None,
    ) -> NoReturn:
        raise ValidationError("canonical creation consumption requires exact appends")

    def _update(self, values: list[tuple[object, object, object]]) -> NoReturn:
        raise ValidationError("canonical creation consumption is append-only")

    def _raw_delete(self, using: str | None) -> NoReturn:
        raise ValidationError("canonical creation consumption is append-only")


class CanonicalAccountCreationConsumptionManager(AppendOnlyManager[_ModelT]):
    """Expose strict append-only guards through every manager path."""

    def get_queryset(self) -> CanonicalAccountCreationConsumptionQuerySet[_ModelT]:
        return CanonicalAccountCreationConsumptionQuerySet(self.model, using=self._db)

    def bulk_create(
        self,
        objs: Iterable[_ModelT],
        batch_size: int | None = None,
        ignore_conflicts: bool = False,
        update_conflicts: bool = False,
        update_fields: Collection[str] | None = None,
        unique_fields: Collection[str] | None = None,
    ) -> NoReturn:
        raise ValidationError("canonical creation consumption requires exact appends")


class _AppendOnlyCanonicalAccountCreationConsumptionModel(models.Model):
    objects = CanonicalAccountCreationConsumptionManager()

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
            raise ValidationError("canonical creation consumption is append-only")
        self._require_insert_claim()
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
            raise ValidationError("canonical creation consumption is append-only")
        self._require_insert_claim()
        super().save_base(force_insert=force_insert, using=using)

    def _require_insert_claim(self) -> None:
        claim = _ACTIVE_CONSUMPTION_CLAIM.get()
        if (
            claim is None
            or claim.token is not _ACTIVE_CONSUMPTION_UOW.get()
            or claim.model_type is not type(self)
            or any(getattr(self, name) != expected for name, expected in claim.expected_values)
        ):
            raise ValidationError("canonical creation consumption requires exact insert claim")

    def delete(
        self,
        using: object | None = None,
        keep_parents: bool = False,
    ) -> tuple[int, dict[str, int]]:
        raise ValidationError("canonical creation consumption is append-only")


class CanonicalAccountCreationConsumptionClaimModel(
    _AppendOnlyCanonicalAccountCreationConsumptionModel
):
    """One cross-generation claim that permanently consumes creation anchors."""

    owner = models.CharField(max_length=32)
    artifact_type = models.CharField(max_length=64)
    schema = models.CharField(max_length=64)
    claim_id = models.CharField(max_length=192)
    claim_version = models.CharField(max_length=192)
    allocation = models.OneToOneField(
        CanonicalAccountCreationAllocationModel,
        on_delete=models.PROTECT,
        related_name="creation_consumption_claim",
    )
    allocation_identity_hash = models.CharField(max_length=64, unique=True)
    allocation_content_hash = models.CharField(max_length=64, unique=True)
    consumer_generation = models.CharField(max_length=16)
    consumer_owner = models.CharField(max_length=32)
    consumer_artifact_type = models.CharField(max_length=64)
    consumer_schema = models.CharField(max_length=64)
    consumer_id = models.CharField(max_length=192)
    consumer_version = models.CharField(max_length=192)
    consumer_identity_hash = models.CharField(max_length=64, unique=True)
    consumer_content_hash = models.CharField(max_length=64, unique=True)
    account_namespace = models.CharField(max_length=192)
    account_id = models.CharField(max_length=192)
    underlying_unified_account_namespace = models.CharField(max_length=192)
    underlying_unified_account_id = models.PositiveBigIntegerField()
    physical_v2_content_hash = models.CharField(max_length=64, unique=True)
    physical_v3_root_content_hash = models.CharField(max_length=64, null=True)
    recorded_at = models.DateTimeField(db_index=True)
    permission = models.CharField(max_length=32)
    status = models.CharField(max_length=16)
    canonical_payload = models.JSONField()
    identity_hash = models.CharField(max_length=64, unique=True)
    content_hash = models.CharField(max_length=64, unique=True)
    allocation_binding_seal = models.CharField(max_length=64)
    consumer_binding_seal = models.CharField(max_length=64)
    fixed_authority_seal = models.CharField(max_length=64)
    record_seal = models.CharField(max_length=64, unique=True)
    ledger_seal = models.CharField(max_length=64, unique=True)
    persisted_at = models.DateTimeField()

    class Meta(_AppendOnlyCanonicalAccountCreationConsumptionModel.Meta):
        app_label = "account"
        db_table = "canonical_account_creation_consumption_claim_ledger"
        constraints = [
            models.UniqueConstraint(
                fields=("claim_id", "claim_version"),
                name="acct_create_cons_claim_uq",
            ),
            models.UniqueConstraint(
                fields=(
                    "consumer_owner",
                    "consumer_artifact_type",
                    "consumer_id",
                    "consumer_version",
                ),
                name="acct_create_cons_ref_uq",
            ),
            models.UniqueConstraint(
                fields=("account_namespace", "account_id"),
                name="acct_create_cons_acct_uq",
            ),
            models.UniqueConstraint(
                fields=(
                    "underlying_unified_account_namespace",
                    "underlying_unified_account_id",
                ),
                name="acct_create_cons_under_uq",
            ),
            models.UniqueConstraint(
                fields=("physical_v3_root_content_hash",),
                condition=models.Q(physical_v3_root_content_hash__isnull=False),
                name="acct_create_cons_root_uq",
            ),
            models.CheckConstraint(
                condition=models.Q(
                    owner="account",
                    artifact_type="canonical_account_creation_consumption_claim",
                    schema="canonical-account-creation-consumption-claim.v1",
                    consumer_owner="account",
                    account_namespace="account",
                    underlying_unified_account_namespace="simulated-account-row",
                    permission="evidence_only",
                    status="inactive",
                ),
                name="acct_create_cons_fixed_ck",
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(
                        consumer_generation="v1",
                        consumer_artifact_type="canonical_account_creation_binding",
                        consumer_schema="canonical-account-creation-binding.v1",
                        physical_v3_root_content_hash__isnull=True,
                    )
                    | models.Q(
                        consumer_generation="v2",
                        consumer_artifact_type="canonical_account_creation_binding_v2",
                        consumer_schema="canonical-account-creation-binding.v2",
                        physical_v3_root_content_hash__isnull=False,
                    )
                ),
                name="acct_create_cons_branch_ck",
            ),
            models.CheckConstraint(
                condition=models.Q(persisted_at=models.F("recorded_at")),
                name="acct_create_cons_clock_ck",
            ),
        ]


class CanonicalAccountCreationBindingV2Model(_AppendOnlyCanonicalAccountCreationConsumptionModel):
    """One immutable durable Binding-v2 backed by a unified consumption claim."""

    consumption_claim = models.OneToOneField(
        CanonicalAccountCreationConsumptionClaimModel,
        on_delete=models.PROTECT,
        related_name="creation_binding_v2",
    )
    consumption_claim_content_hash = models.CharField(max_length=64, unique=True)
    allocation = models.ForeignKey(
        CanonicalAccountCreationAllocationModel,
        on_delete=models.PROTECT,
        related_name="creation_bindings_v2",
    )
    allocation_identity_hash = models.CharField(max_length=64, unique=True)
    allocation_content_hash = models.CharField(max_length=64, unique=True)
    creation_root = models.OneToOneField(
        AllocatedPhysicalAccountRowObservationV3Model,
        on_delete=models.PROTECT,
        related_name="creation_binding_v2",
    )
    owner = models.CharField(max_length=32)
    artifact_type = models.CharField(max_length=64)
    schema = models.CharField(max_length=64)
    binding_id = models.CharField(max_length=192)
    binding_version = models.CharField(max_length=192)
    creation_root_observation_id = models.CharField(max_length=192)
    creation_root_observation_version = models.CharField(max_length=192)
    creation_root_identity_hash = models.CharField(max_length=64, unique=True)
    creation_root_content_hash = models.CharField(max_length=64, unique=True)
    physical_observation_content_hash = models.CharField(max_length=64, unique=True)
    physical_source_content_hash = models.CharField(max_length=64, unique=True)
    physical_raw_observation_content_hash = models.CharField(max_length=64, unique=True)
    account_namespace_claim = models.CharField(max_length=192)
    account_id_claim = models.CharField(max_length=192)
    underlying_unified_account_namespace_claim = models.CharField(max_length=192)
    underlying_unified_account_id_claim = models.PositiveBigIntegerField()
    recorded_service_id = models.CharField(max_length=192)
    recorded_role = models.CharField(max_length=192)
    recorded_kind = models.CharField(max_length=16)
    recorded_is_automated = models.BooleanField()
    recorded_at = models.DateTimeField(db_index=True)
    account_claim_hash = models.CharField(max_length=64, unique=True)
    underlying_claim_hash = models.CharField(max_length=64, unique=True)
    permission = models.CharField(max_length=64)
    status = models.CharField(max_length=16)
    binding_state = models.CharField(max_length=32)
    owner_assignment_state = models.CharField(max_length=32)
    canonical_payload = models.JSONField()
    identity_hash = models.CharField(max_length=64, unique=True)
    content_hash = models.CharField(max_length=64, unique=True)
    consumption_claim_binding_seal = models.CharField(max_length=64)
    allocation_binding_seal = models.CharField(max_length=64)
    creation_root_binding_seal = models.CharField(max_length=64)
    physical_binding_seal = models.CharField(max_length=64)
    recorder_binding_seal = models.CharField(max_length=64)
    fixed_authority_seal = models.CharField(max_length=64)
    record_seal = models.CharField(max_length=64, unique=True)
    ledger_seal = models.CharField(max_length=64, unique=True)
    persisted_at = models.DateTimeField()

    class Meta(_AppendOnlyCanonicalAccountCreationConsumptionModel.Meta):
        app_label = "account"
        db_table = "canonical_account_creation_binding_v2_ledger"
        constraints = [
            models.UniqueConstraint(
                fields=("binding_id", "binding_version"),
                name="acct_create_bind_v2_id_uq",
            ),
            models.UniqueConstraint(
                fields=("account_namespace_claim", "account_id_claim"),
                name="acct_create_bind_v2_acct_uq",
            ),
            models.UniqueConstraint(
                fields=(
                    "underlying_unified_account_namespace_claim",
                    "underlying_unified_account_id_claim",
                ),
                name="acct_create_bind_v2_under_uq",
            ),
            models.CheckConstraint(
                condition=models.Q(
                    owner="account",
                    artifact_type="canonical_account_creation_binding_v2",
                    schema="canonical-account-creation-binding.v2",
                    account_namespace_claim="account",
                    underlying_unified_account_namespace_claim="simulated-account-row",
                    recorded_role="canonical_account_creation_binder",
                    recorded_kind="service",
                    recorded_is_automated=True,
                    permission="identity_binding_evidence_only",
                    status="inactive",
                    binding_state="bound_pending_owner_approval",
                    owner_assignment_state="unknown",
                ),
                name="acct_create_bind_v2_fixed_ck",
            ),
            models.CheckConstraint(
                condition=models.Q(persisted_at=models.F("recorded_at")),
                name="acct_create_bind_v2_clock_ck",
            ),
        ]


def _reject_canonical_account_creation_consumption_delete(
    sender: type[models.Model],
    instance: models.Model,
    using: str,
    origin: object,
    **kwargs: object,
) -> None:
    del sender, instance, using, origin, kwargs
    raise ValidationError("canonical creation consumption is append-only")


for _model in (
    CanonicalAccountCreationConsumptionClaimModel,
    CanonicalAccountCreationBindingV2Model,
):
    pre_delete.connect(
        _reject_canonical_account_creation_consumption_delete,
        sender=_model,
        dispatch_uid=f"{_model.__name__}_append_only",
        weak=False,
    )


__all__ = [
    "CanonicalAccountCreationBindingV2Model",
    "CanonicalAccountCreationConsumptionClaimModel",
]
