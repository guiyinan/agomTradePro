"""Private append-only ledgers for Broker execution-risk policies."""

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
_ACTIVE_BROKER_EXECUTION_POLICY_UOW: ContextVar[object | None] = ContextVar(
    "active_risk_center_broker_execution_policy_uow", default=None
)


@dataclass(frozen=True)
class _InsertClaim:
    token: object
    model_type: type[models.Model]
    expected_values: tuple[tuple[str, object], ...]


_ACTIVE_BROKER_EXECUTION_POLICY_CLAIM: ContextVar[_InsertClaim | None] = ContextVar(
    "active_risk_center_broker_execution_policy_claim", default=None
)


@contextmanager
def _activate_broker_execution_policy_uow(token: object) -> Iterator[None]:
    """Activate only this ledger's private unit-of-work token."""

    reset = _ACTIVE_BROKER_EXECUTION_POLICY_UOW.set(token)
    try:
        yield
    finally:
        _ACTIVE_BROKER_EXECUTION_POLICY_UOW.reset(reset)


@contextmanager
def _claim_broker_execution_policy_insert(
    *, token: object, model_type: type[models.Model], expected_values: Mapping[str, object]
) -> Iterator[None]:
    """Claim one exact repository-controlled insert."""

    if _ACTIVE_BROKER_EXECUTION_POLICY_UOW.get() is not token:
        raise ValidationError("Broker execution policy insert requires its private UOW.")
    reset = _ACTIVE_BROKER_EXECUTION_POLICY_CLAIM.set(
        _InsertClaim(token, model_type, tuple(sorted(expected_values.items())))
    )
    try:
        yield
    finally:
        _ACTIVE_BROKER_EXECUTION_POLICY_CLAIM.reset(reset)


class BrokerExecutionPolicyQuerySet(AppendOnlyQuerySet[_ModelT]):
    """Reject bulk insertion, mutation, and deletion shortcuts."""

    def bulk_create(
        self,
        objs: Iterable[_ModelT],
        batch_size: int | None = None,
        ignore_conflicts: bool = False,
        update_conflicts: bool = False,
        update_fields: Collection[str] | None = None,
        unique_fields: Collection[str] | None = None,
    ) -> NoReturn:
        raise ValidationError("Broker execution policies require exact repository appends.")

    def _update(self, values: list[tuple[object, object, object]]) -> NoReturn:
        raise ValidationError("Broker execution policies cannot be updated.")

    def _raw_delete(self, using: str) -> NoReturn:
        raise ValidationError("Broker execution policies cannot be deleted.")


class BrokerExecutionPolicyManager(AppendOnlyManager[_ModelT]):
    """Expose the strict append-only queryset on every manager path."""

    def get_queryset(self) -> BrokerExecutionPolicyQuerySet[_ModelT]:
        return BrokerExecutionPolicyQuerySet(self.model, using=self._db)

    def bulk_create(
        self,
        objs: Iterable[_ModelT],
        batch_size: int | None = None,
        ignore_conflicts: bool = False,
        update_conflicts: bool = False,
        update_fields: Collection[str] | None = None,
        unique_fields: Collection[str] | None = None,
    ) -> NoReturn:
        raise ValidationError("Broker execution policies require exact repository appends.")


class BrokerExecutionPolicyAppendOnlyModel(models.Model):
    """Permit only exact inserts claimed by this capability's repository."""

    objects: BrokerExecutionPolicyManager[models.Model] = BrokerExecutionPolicyManager()

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
            raise ValidationError("Broker execution policies are append-only.")
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
            raise ValidationError("Broker execution policies are append-only.")
        self._require_claim()
        super().save_base(force_insert=force_insert, using=using)

    def _require_claim(self) -> None:
        claim = _ACTIVE_BROKER_EXECUTION_POLICY_CLAIM.get()
        if (
            claim is None
            or claim.token is not _ACTIVE_BROKER_EXECUTION_POLICY_UOW.get()
            or claim.model_type is not type(self)
            or any(getattr(self, name) != expected for name, expected in claim.expected_values)
        ):
            raise ValidationError("Broker execution policy requires an exact insert claim.")

    def delete(
        self, using: object | None = None, keep_parents: bool = False
    ) -> tuple[int, dict[str, int]]:
        raise ValidationError("Broker execution policies cannot be deleted.")


class BrokerOrderExecutionPolicySourceModel(BrokerExecutionPolicyAppendOnlyModel):
    """One immutable complete five-component source-bundle first winner."""

    source_snapshot_id = models.CharField(max_length=192)
    source_snapshot_version = models.CharField(max_length=192)
    source_identity_hash = models.CharField(max_length=64, unique=True)
    account_id = models.PositiveBigIntegerField()
    source_recorded_at = models.DateTimeField()
    recorded_at = models.DateTimeField(db_index=True)
    valid_until = models.DateTimeField()
    canonical_payload = models.JSONField()
    content_hash = models.CharField(max_length=64, db_index=True)
    ledger_header_hash = models.CharField(max_length=64, unique=True)
    persisted_at = models.DateTimeField()

    class Meta(BrokerExecutionPolicyAppendOnlyModel.Meta):
        db_table = "risk_center_broker_execution_policy_source"
        indexes = [
            models.Index(fields=("account_id", "recorded_at"), name="risk_br_pol_src_pit_ix")
        ]
        constraints = [
            models.UniqueConstraint(
                fields=("source_snapshot_id", "source_snapshot_version"),
                name="risk_br_pol_src_id_uq",
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(source_recorded_at__lte=models.F("recorded_at"))
                    & models.Q(recorded_at__lt=models.F("valid_until"))
                    & models.Q(persisted_at=models.F("recorded_at"))
                ),
                name="risk_br_pol_src_clock_ck",
            ),
        ]


class BrokerOrderExecutionPolicyActivationModel(BrokerExecutionPolicyAppendOnlyModel):
    """One immutable actor-bound policy activation in an account hash chain."""

    source = models.ForeignKey(
        BrokerOrderExecutionPolicySourceModel,
        on_delete=models.PROTECT,
        related_name="policy_activations",
    )
    owner = models.CharField(max_length=32)
    capability = models.CharField(max_length=64)
    schema = models.CharField(max_length=64)
    permission_cap = models.CharField(max_length=32)
    policy_id = models.CharField(max_length=192)
    policy_version = models.CharField(max_length=192)
    policy_identity_hash = models.CharField(max_length=64, unique=True)
    account_id = models.PositiveBigIntegerField()
    source_snapshot_id = models.CharField(max_length=192)
    source_snapshot_version = models.CharField(max_length=192)
    source_snapshot_hash = models.CharField(max_length=64)
    supersedes_policy_hash = models.CharField(max_length=64, null=True)
    activated_actor_id = models.CharField(max_length=192)
    activated_actor_user_id = models.PositiveBigIntegerField()
    activated_actor_kind = models.CharField(max_length=16)
    activated_actor_is_staff = models.BooleanField()
    recorded_at = models.DateTimeField(db_index=True)
    activated_at = models.DateTimeField()
    valid_until = models.DateTimeField()
    canonical_policy = models.JSONField()
    canonical_activation = models.JSONField()
    policy_content_hash = models.CharField(max_length=64, unique=True)
    activation_content_hash = models.CharField(max_length=64, unique=True)
    ledger_header_hash = models.CharField(max_length=64, unique=True)
    persisted_at = models.DateTimeField()

    class Meta(BrokerExecutionPolicyAppendOnlyModel.Meta):
        db_table = "risk_center_broker_execution_policy_activation"
        indexes = [
            models.Index(fields=("account_id", "recorded_at"), name="risk_br_pol_act_pit_ix")
        ]
        constraints = [
            models.UniqueConstraint(
                fields=("policy_id", "policy_version"), name="risk_br_pol_act_id_uq"
            ),
            models.UniqueConstraint(
                fields=("supersedes_policy_hash",),
                condition=models.Q(supersedes_policy_hash__isnull=False),
                name="risk_br_pol_act_next_uq",
            ),
            models.UniqueConstraint(
                fields=("account_id",),
                condition=models.Q(supersedes_policy_hash__isnull=True),
                name="risk_br_pol_act_root_uq",
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(owner="risk_center")
                    & models.Q(capability="broker_order_execution_risk_policy")
                    & models.Q(permission_cap="execution_eligible")
                ),
                name="risk_br_pol_act_owner_ck",
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(recorded_at=models.F("activated_at"))
                    & models.Q(activated_at__lt=models.F("valid_until"))
                    & models.Q(persisted_at=models.F("recorded_at"))
                ),
                name="risk_br_pol_act_clock_ck",
            ),
            models.CheckConstraint(
                condition=models.Q(
                    activated_actor_kind="human",
                    activated_actor_is_staff=True,
                ),
                name="risk_br_pol_act_actor_ck",
            ),
        ]


def _reject_broker_execution_policy_pre_delete(
    sender: type[models.Model],
    instance: models.Model,
    using: str,
    origin: object,
    **kwargs: object,
) -> None:
    """Reject collector and cascade deletion paths."""

    del sender, instance, using, origin, kwargs
    raise ValidationError("Broker execution policies cannot be deleted.")


for _model in (
    BrokerOrderExecutionPolicySourceModel,
    BrokerOrderExecutionPolicyActivationModel,
):
    pre_delete.connect(
        _reject_broker_execution_policy_pre_delete,
        sender=_model,
        dispatch_uid=f"reject_{_model._meta.db_table}_delete",
        weak=False,
    )


__all__ = [
    "BrokerOrderExecutionPolicyActivationModel",
    "BrokerOrderExecutionPolicySourceModel",
]
