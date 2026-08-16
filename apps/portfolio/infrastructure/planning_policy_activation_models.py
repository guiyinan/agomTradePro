"""Append-only storage models for Portfolio planning-policy activation."""

from __future__ import annotations

from collections.abc import Collection, Iterable, Iterator, Mapping
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from typing import NoReturn, Self, TypeVar

from django.core.exceptions import ValidationError
from django.db import models
from django.db.models.base import ModelBase
from django.db.models.signals import pre_delete

from shared.infrastructure.django_append_only import AppendOnlyManager, AppendOnlyQuerySet

_ModelT = TypeVar("_ModelT", bound=models.Model)
_ACTIVE_PLANNING_POLICY_ACTIVATION_UOW: ContextVar[object | None] = ContextVar(
    "active_portfolio_planning_policy_activation_uow", default=None
)


@dataclass(frozen=True)
class _InsertClaim:
    token: object
    model_type: type[models.Model]
    expected_values: tuple[tuple[str, object], ...]


_ACTIVE_PLANNING_POLICY_ACTIVATION_CLAIM: ContextVar[_InsertClaim | None] = ContextVar(
    "active_portfolio_planning_policy_activation_claim", default=None
)


@contextmanager
def _activate_planning_policy_activation_uow(token: object) -> Iterator[None]:
    """Activate this ledger's private unit-of-work token."""

    reset = _ACTIVE_PLANNING_POLICY_ACTIVATION_UOW.set(token)
    try:
        yield
    finally:
        _ACTIVE_PLANNING_POLICY_ACTIVATION_UOW.reset(reset)


@contextmanager
def _claim_planning_policy_activation_insert(
    *, token: object, model_type: type[models.Model], expected_values: Mapping[str, object]
) -> Iterator[None]:
    """Claim one exact repository-controlled subject or activation insert."""

    if _ACTIVE_PLANNING_POLICY_ACTIVATION_UOW.get() is not token:
        raise ValidationError("Planning-policy activation insert requires its private UOW.")
    reset = _ACTIVE_PLANNING_POLICY_ACTIVATION_CLAIM.set(
        _InsertClaim(token, model_type, tuple(sorted(expected_values.items())))
    )
    try:
        yield
    finally:
        _ACTIVE_PLANNING_POLICY_ACTIVATION_CLAIM.reset(reset)


class PlanningPolicyActivationQuerySet(AppendOnlyQuerySet[_ModelT]):
    """Reject every bulk insertion, mutation, and raw deletion shortcut."""

    def bulk_create(
        self,
        objs: Iterable[_ModelT],
        batch_size: int | None = None,
        ignore_conflicts: bool = False,
        update_conflicts: bool = False,
        update_fields: Collection[str] | None = None,
        unique_fields: Collection[str] | None = None,
    ) -> NoReturn:
        raise ValidationError("Planning-policy activations require exact repository appends.")

    def _update(self, values: list[tuple[object, object, object]]) -> NoReturn:
        raise ValidationError("Planning-policy activations cannot be updated.")

    def _raw_delete(self, using: str | None) -> NoReturn:
        raise ValidationError("Planning-policy activations cannot be deleted.")


class PlanningPolicyActivationManager(AppendOnlyManager[_ModelT]):
    """Expose strict append-only guards through every manager path."""

    def get_queryset(self) -> PlanningPolicyActivationQuerySet[_ModelT]:
        return PlanningPolicyActivationQuerySet(self.model, using=self._db)

    def bulk_create(
        self,
        objs: Iterable[_ModelT],
        batch_size: int | None = None,
        ignore_conflicts: bool = False,
        update_conflicts: bool = False,
        update_fields: Collection[str] | None = None,
        unique_fields: Collection[str] | None = None,
    ) -> NoReturn:
        raise ValidationError("Planning-policy activations require exact repository appends.")


class PlanningPolicyActivationAppendOnlyModel(models.Model):
    """Permit only exact inserts claimed by this ledger's repository."""

    objects: PlanningPolicyActivationManager[Self] = PlanningPolicyActivationManager()

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
        """Permit only one exact repository-claimed insert."""

        if force_update or update_fields is not None or self.pk is not None:
            raise ValidationError("Planning-policy activations are append-only.")
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
            raise ValidationError("Planning-policy activations are append-only.")
        self._require_claim()
        super().save_base(force_insert=force_insert, using=using)

    def _require_claim(self) -> None:
        claim = _ACTIVE_PLANNING_POLICY_ACTIVATION_CLAIM.get()
        if (
            claim is None
            or claim.token is not _ACTIVE_PLANNING_POLICY_ACTIVATION_UOW.get()
            or claim.model_type is not type(self)
            or any(getattr(self, name) != expected for name, expected in claim.expected_values)
        ):
            raise ValidationError("Planning-policy activation requires an exact insert claim.")

    def delete(
        self, using: object | None = None, keep_parents: bool = False
    ) -> tuple[int, dict[str, int]]:
        """Reject instance deletion."""

        raise ValidationError("Planning-policy activations cannot be deleted.")


class PortfolioPlanningPolicyActivationSubjectModel(PlanningPolicyActivationAppendOnlyModel):
    """One immutable activation-request identity first winner."""

    subject_id = models.CharField(max_length=192)
    subject_version = models.CharField(max_length=192)
    subject_identity_hash = models.CharField(max_length=64, unique=True)
    policy_id = models.CharField(max_length=192)
    policy_version = models.CharField(max_length=192)
    definition_identity_hash = models.CharField(max_length=64)
    definition_content_hash = models.CharField(max_length=64)
    definition_recorded_at = models.DateTimeField()
    requested_actor_id = models.CharField(max_length=192)
    requested_actor_user_id = models.PositiveBigIntegerField()
    requested_actor_role = models.CharField(max_length=192)
    requested_actor_kind = models.CharField(max_length=16)
    requested_actor_is_staff = models.BooleanField()
    requested_at = models.DateTimeField()
    valid_until = models.DateTimeField()
    supersedes_activation_hash = models.CharField(max_length=64, null=True)
    recorded_at = models.DateTimeField(db_index=True)
    persisted_at = models.DateTimeField()
    canonical_payload = models.JSONField()
    content_hash = models.CharField(max_length=64, unique=True)
    ledger_header_hash = models.CharField(max_length=64, unique=True)

    class Meta(PlanningPolicyActivationAppendOnlyModel.Meta):
        db_table = "portfolio_planning_policy_activation_subject"
        indexes = [
            models.Index(
                fields=("policy_id", "requested_at"),
                name="port_pol_act_sub_pit_ix",
            )
        ]
        constraints = [
            models.UniqueConstraint(
                fields=("subject_id", "subject_version"),
                name="portfolio_plan_pol_act_sub_id_uq",
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(requested_at=models.F("recorded_at"))
                    & models.Q(persisted_at=models.F("recorded_at"))
                    & models.Q(definition_recorded_at__lte=models.F("requested_at"))
                    & models.Q(requested_at__lt=models.F("valid_until"))
                    & models.Q(requested_actor_kind="human")
                    & models.Q(requested_actor_is_staff=True)
                ),
                name="portfolio_plan_pol_act_sub_seal_ck",
            ),
        ]


class PortfolioPlanningPolicyActivationModel(PlanningPolicyActivationAppendOnlyModel):
    """One immutable activation-chain record first winner."""

    subject_record = models.OneToOneField(
        PortfolioPlanningPolicyActivationSubjectModel,
        on_delete=models.PROTECT,
        related_name="activation_record",
    )
    owner = models.CharField(max_length=32)
    capability = models.CharField(max_length=64)
    schema = models.CharField(max_length=96)
    permission = models.CharField(max_length=64)
    activation_id = models.CharField(max_length=192)
    activation_version = models.CharField(max_length=192)
    activation_identity_hash = models.CharField(max_length=64, unique=True)
    subject_id = models.CharField(max_length=192)
    subject_version = models.CharField(max_length=192)
    subject_content_hash = models.CharField(max_length=64, unique=True)
    policy_id = models.CharField(max_length=192)
    policy_version = models.CharField(max_length=192)
    definition_identity_hash = models.CharField(max_length=64)
    definition_content_hash = models.CharField(max_length=64)
    requested_actor_id = models.CharField(max_length=192)
    requested_actor_user_id = models.PositiveBigIntegerField()
    requested_actor_role = models.CharField(max_length=192)
    approved_actor_id = models.CharField(max_length=192)
    approved_actor_user_id = models.PositiveBigIntegerField()
    approved_actor_role = models.CharField(max_length=192)
    approved_actor_kind = models.CharField(max_length=16)
    approved_actor_is_staff = models.BooleanField()
    issued_at = models.DateTimeField()
    valid_until = models.DateTimeField()
    predecessor_hash = models.CharField(max_length=64, null=True, unique=True)
    recorded_at = models.DateTimeField(db_index=True)
    persisted_at = models.DateTimeField()
    canonical_payload = models.JSONField()
    content_hash = models.CharField(max_length=64, unique=True)
    ledger_header_hash = models.CharField(max_length=64, unique=True)

    class Meta(PlanningPolicyActivationAppendOnlyModel.Meta):
        db_table = "portfolio_planning_policy_activation"
        indexes = [
            models.Index(
                fields=("policy_id", "issued_at"),
                name="port_pol_act_pit_ix",
            )
        ]
        constraints = [
            models.UniqueConstraint(
                fields=("activation_id", "activation_version"),
                name="portfolio_plan_pol_act_id_uq",
            ),
            models.UniqueConstraint(
                fields=("policy_id",),
                condition=models.Q(predecessor_hash__isnull=True),
                name="portfolio_plan_pol_act_root_uq",
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(owner="portfolio")
                    & models.Q(capability="planning_policy_activation")
                    & models.Q(schema="portfolio-planning-policy-activation.v1")
                    & models.Q(permission="policy_configuration_only")
                    & models.Q(issued_at=models.F("recorded_at"))
                    & models.Q(persisted_at=models.F("recorded_at"))
                    & models.Q(issued_at__lt=models.F("valid_until"))
                    & models.Q(approved_actor_kind="human")
                    & models.Q(approved_actor_is_staff=True)
                ),
                name="portfolio_plan_pol_act_seal_ck",
            ),
            models.CheckConstraint(
                condition=~models.Q(approved_actor_id=models.F("requested_actor_id")),
                name="portfolio_plan_pol_act_actor_sep_ck",
            ),
            models.CheckConstraint(
                condition=~models.Q(approved_actor_user_id=models.F("requested_actor_user_id")),
                name="portfolio_plan_pol_act_user_sep_ck",
            ),
        ]


def _reject_planning_policy_activation_delete(
    sender: type[models.Model],
    instance: models.Model,
    using: str,
    origin: object,
    **kwargs: object,
) -> None:
    """Reject collector, cascade, and protected-parent deletion paths."""

    del sender, instance, using, origin, kwargs
    raise ValidationError("Planning-policy activations cannot be deleted.")


for _model in (
    PortfolioPlanningPolicyActivationSubjectModel,
    PortfolioPlanningPolicyActivationModel,
):
    pre_delete.connect(
        _reject_planning_policy_activation_delete,
        sender=_model,
        dispatch_uid=f"reject_{_model._meta.db_table}_delete",
        weak=False,
    )


__all__ = [
    "PortfolioPlanningPolicyActivationModel",
    "PortfolioPlanningPolicyActivationSubjectModel",
]
