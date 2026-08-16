"""Append-only ledgers for Broker order risk authorizations."""

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
_ACTIVE_BROKER_RISK_AUTHORIZATION_UOW: ContextVar[object | None] = ContextVar(
    "active_risk_center_broker_order_risk_authorization_uow", default=None
)


@dataclass(frozen=True)
class _InsertClaim:
    token: object
    model_type: type[models.Model]
    expected_values: tuple[tuple[str, object], ...]


_ACTIVE_BROKER_RISK_AUTHORIZATION_CLAIM: ContextVar[_InsertClaim | None] = ContextVar(
    "active_risk_center_broker_order_risk_authorization_claim", default=None
)


@contextmanager
def _activate_broker_order_risk_authorization_uow(token: object) -> Iterator[None]:
    """Activate this ledger's private unit-of-work token."""

    reset = _ACTIVE_BROKER_RISK_AUTHORIZATION_UOW.set(token)
    try:
        yield
    finally:
        _ACTIVE_BROKER_RISK_AUTHORIZATION_UOW.reset(reset)


@contextmanager
def _claim_broker_order_risk_authorization_insert(
    *, token: object, model_type: type[models.Model], expected_values: Mapping[str, object]
) -> Iterator[None]:
    """Claim one exact repository-controlled insert."""

    if _ACTIVE_BROKER_RISK_AUTHORIZATION_UOW.get() is not token:
        raise ValidationError("Broker risk authorization insert requires its private UOW.")
    reset = _ACTIVE_BROKER_RISK_AUTHORIZATION_CLAIM.set(
        _InsertClaim(token, model_type, tuple(sorted(expected_values.items())))
    )
    try:
        yield
    finally:
        _ACTIVE_BROKER_RISK_AUTHORIZATION_CLAIM.reset(reset)


class BrokerOrderRiskAuthorizationQuerySet(AppendOnlyQuerySet[_ModelT]):
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
        raise ValidationError("Broker risk authorizations require exact repository appends.")

    def _update(self, values: list[tuple[object, object, object]]) -> NoReturn:
        raise ValidationError("Broker risk authorizations cannot be updated.")

    def _raw_delete(self, using: str | None) -> NoReturn:
        raise ValidationError("Broker risk authorizations cannot be deleted.")


class BrokerOrderRiskAuthorizationManager(AppendOnlyManager[_ModelT]):
    """Expose strict append-only guards through every manager path."""

    def get_queryset(self) -> BrokerOrderRiskAuthorizationQuerySet[_ModelT]:
        return BrokerOrderRiskAuthorizationQuerySet(self.model, using=self._db)

    def bulk_create(
        self,
        objs: Iterable[_ModelT],
        batch_size: int | None = None,
        ignore_conflicts: bool = False,
        update_conflicts: bool = False,
        update_fields: Collection[str] | None = None,
        unique_fields: Collection[str] | None = None,
    ) -> NoReturn:
        raise ValidationError("Broker risk authorizations require exact repository appends.")


class BrokerOrderRiskAuthorizationAppendOnlyModel(models.Model):
    """Permit only exact, repository-claimed inserts."""

    objects: BrokerOrderRiskAuthorizationManager[Self] = BrokerOrderRiskAuthorizationManager()

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
            raise ValidationError("Broker risk authorizations are append-only.")
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
            raise ValidationError("Broker risk authorizations are append-only.")
        self._require_claim()
        super().save_base(force_insert=force_insert, using=using)

    def _require_claim(self) -> None:
        claim = _ACTIVE_BROKER_RISK_AUTHORIZATION_CLAIM.get()
        if (
            claim is None
            or claim.token is not _ACTIVE_BROKER_RISK_AUTHORIZATION_UOW.get()
            or claim.model_type is not type(self)
            or any(getattr(self, name) != expected for name, expected in claim.expected_values)
        ):
            raise ValidationError("Broker risk authorization requires an exact insert claim.")

    def delete(
        self, using: object | None = None, keep_parents: bool = False
    ) -> tuple[int, dict[str, int]]:
        raise ValidationError("Broker risk authorizations cannot be deleted.")


class BrokerOrderRiskAuthorizationSubjectModel(BrokerOrderRiskAuthorizationAppendOnlyModel):
    """One immutable authorization subject first winner."""

    subject_id = models.CharField(max_length=192)
    subject_version = models.CharField(max_length=192)
    subject_identity_hash = models.CharField(max_length=64, unique=True)
    account_id = models.PositiveBigIntegerField()
    order_id = models.CharField(max_length=36)
    scope_content_hash = models.CharField(max_length=64)
    supersedes_authorization_hash = models.CharField(max_length=64, null=True)
    requested_actor_id = models.CharField(max_length=192)
    requested_actor_kind = models.CharField(max_length=16)
    requested_actor_is_staff = models.BooleanField()
    requested_actor_user_id = models.PositiveBigIntegerField(null=True)
    requested_at = models.DateTimeField()
    valid_until = models.DateTimeField()
    recorded_at = models.DateTimeField(db_index=True)
    canonical_payload = models.JSONField()
    content_hash = models.CharField(max_length=64, unique=True)
    ledger_header_hash = models.CharField(max_length=64, unique=True)
    persisted_at = models.DateTimeField(auto_now_add=True)

    class Meta(BrokerOrderRiskAuthorizationAppendOnlyModel.Meta):
        db_table = "risk_center_broker_order_risk_subject"
        indexes = [
            models.Index(
                fields=("account_id", "order_id", "recorded_at"),
                name="risk_br_ord_subj_pit_ix",
            )
        ]
        constraints = [
            models.UniqueConstraint(
                fields=("subject_id", "subject_version"), name="risk_br_ord_subj_id_uq"
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(requested_at=models.F("recorded_at"))
                    & models.Q(recorded_at__lt=models.F("valid_until"))
                ),
                name="risk_br_ord_subj_clock_ck",
            ),
            models.CheckConstraint(
                condition=models.Q(
                    requested_actor_kind="human",
                    requested_actor_is_staff=True,
                    requested_actor_user_id__isnull=False,
                ),
                name="risk_br_ord_subj_actor_ck",
            ),
        ]


class BrokerOrderRiskAuthorizationRecordModel(BrokerOrderRiskAuthorizationAppendOnlyModel):
    """One immutable authorization in an account/order hash chain."""

    subject = models.OneToOneField(
        BrokerOrderRiskAuthorizationSubjectModel,
        on_delete=models.PROTECT,
        related_name="authorization_record",
    )
    owner = models.CharField(max_length=32)
    capability = models.CharField(max_length=64)
    permission_cap = models.CharField(max_length=32)
    authorization_id = models.CharField(max_length=192)
    authorization_version = models.CharField(max_length=192)
    authorization_identity_hash = models.CharField(max_length=64, unique=True)
    subject_hash = models.CharField(max_length=64, unique=True)
    account_id = models.PositiveBigIntegerField()
    order_id = models.CharField(max_length=36)
    supersedes_authorization_hash = models.CharField(max_length=64, null=True)
    approved_actor_id = models.CharField(max_length=192)
    approved_actor_kind = models.CharField(max_length=16)
    approved_actor_is_staff = models.BooleanField()
    approved_actor_user_id = models.PositiveBigIntegerField()
    issued_at = models.DateTimeField()
    valid_until = models.DateTimeField()
    recorded_at = models.DateTimeField(db_index=True)
    canonical_payload = models.JSONField()
    content_hash = models.CharField(max_length=64, unique=True)
    ledger_header_hash = models.CharField(max_length=64, unique=True)
    persisted_at = models.DateTimeField(auto_now_add=True)

    class Meta(BrokerOrderRiskAuthorizationAppendOnlyModel.Meta):
        db_table = "risk_center_broker_order_risk_authorization"
        indexes = [
            models.Index(
                fields=("account_id", "order_id", "recorded_at"),
                name="risk_br_ord_auth_pit_ix",
            )
        ]
        constraints = [
            models.UniqueConstraint(
                fields=("authorization_id", "authorization_version"),
                name="risk_br_ord_auth_id_uq",
            ),
            models.UniqueConstraint(
                fields=("supersedes_authorization_hash",),
                condition=models.Q(supersedes_authorization_hash__isnull=False),
                name="risk_br_ord_auth_next_uq",
            ),
            models.UniqueConstraint(
                fields=("account_id", "order_id"),
                condition=models.Q(supersedes_authorization_hash__isnull=True),
                name="risk_br_ord_auth_root_uq",
            ),
            models.CheckConstraint(
                condition=models.Q(
                    capability="broker_order_risk_authorization",
                    owner="risk_center",
                    permission_cap="execution_eligible",
                ),
                name="risk_br_ord_auth_owner_ck",
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(issued_at=models.F("recorded_at"))
                    & models.Q(recorded_at__lt=models.F("valid_until"))
                ),
                name="risk_br_ord_auth_clock_ck",
            ),
            models.CheckConstraint(
                condition=models.Q(
                    approved_actor_kind="human",
                    approved_actor_is_staff=True,
                    approved_actor_user_id__isnull=False,
                ),
                name="risk_br_ord_auth_actor_ck",
            ),
        ]


def _reject_broker_order_risk_authorization_pre_delete(
    sender: type[models.Model],
    instance: models.Model,
    using: str,
    origin: object,
    **kwargs: object,
) -> None:
    """Reject collector/cascade deletion paths."""

    del sender, instance, using, origin, kwargs
    raise ValidationError("Broker risk authorizations cannot be deleted.")


for _model in (
    BrokerOrderRiskAuthorizationSubjectModel,
    BrokerOrderRiskAuthorizationRecordModel,
):
    pre_delete.connect(
        _reject_broker_order_risk_authorization_pre_delete,
        sender=_model,
        dispatch_uid=f"reject_{_model._meta.db_table}_delete",
        weak=False,
    )


__all__ = [
    "BrokerOrderRiskAuthorizationRecordModel",
    "BrokerOrderRiskAuthorizationSubjectModel",
]
