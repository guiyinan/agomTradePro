"""Append-only ledgers for canonical Account creation allocation and binding."""

from __future__ import annotations

from collections.abc import Collection, Iterable, Iterator, Mapping
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from typing import NoReturn, TypeVar, cast

from django.core.exceptions import ValidationError
from django.db import connections, models
from django.db.models.base import ModelBase
from django.db.models.signals import pre_delete

from shared.infrastructure.django_append_only import AppendOnlyManager, AppendOnlyQuerySet

_T = TypeVar("_T", bound=models.Model)
_UOW: ContextVar[object | None] = ContextVar("canonical_creation_uow", default=None)


@dataclass(frozen=True)
class _InsertClaim:
    token: object
    model_type: type[models.Model]
    values: tuple[tuple[str, object], ...]


_CLAIM: ContextVar[_InsertClaim | None] = ContextVar("canonical_creation_claim", default=None)
_KNOWLEDGE_BACKFILL: ContextVar[object | None] = ContextVar(
    "canonical_creation_knowledge_backfill", default=None
)


@contextmanager
def _activate_canonical_account_creation_uow(token: object) -> Iterator[None]:
    reset = _UOW.set(token)
    try:
        yield
    finally:
        _UOW.reset(reset)


@contextmanager
def _claim_canonical_account_creation_insert(
    *, token: object, model_type: type[models.Model], expected_values: Mapping[str, object]
) -> Iterator[None]:
    if _UOW.get() is not token:
        raise ValidationError("canonical creation insert requires private UOW")
    reset = _CLAIM.set(_InsertClaim(token, model_type, tuple(sorted(expected_values.items()))))
    try:
        yield
    finally:
        _CLAIM.reset(reset)


@contextmanager
def _activate_canonical_account_creation_knowledge_backfill(
    token: object,
) -> Iterator[None]:
    """Activate the private legacy-link maintenance capability."""

    if _UOW.get() is not token:
        raise ValidationError("knowledge backfill requires private creation UOW")
    reset = _KNOWLEDGE_BACKFILL.set(token)
    try:
        yield
    finally:
        _KNOWLEDGE_BACKFILL.reset(reset)


def _compare_and_set_canonical_account_creation_binding_claim(
    *,
    using: str,
    token: object,
    binding_pk: int,
    claim_pk: int,
    allocation_pk: int,
    consumer_identity_hash: str,
    consumer_content_hash: str,
    claim_content_hash: str,
) -> int:
    """Link one legacy row only when its exact Claim consumer exists."""

    if (
        _UOW.get() is not token
        or _KNOWLEDGE_BACKFILL.get() is not token
        or any(
            type(value) is not int or value <= 0 for value in (binding_pk, claim_pk, allocation_pk)
        )
        or any(
            type(value) is not str
            or len(value) != 64
            or any(character not in "0123456789abcdef" for character in value)
            for value in (
                consumer_identity_hash,
                consumer_content_hash,
                claim_content_hash,
            )
        )
    ):
        raise ValidationError("knowledge backfill capability is unavailable")
    connection = connections[using]
    binding_table = connection.ops.quote_name(CanonicalAccountCreationBindingModel._meta.db_table)
    claim_table = connection.ops.quote_name("canonical_account_creation_consumption_claim_ledger")
    with connection.cursor() as cursor:
        cursor.execute(
            f"UPDATE {binding_table} SET consumption_claim_id = %s "  # noqa: S608
            "WHERE id = %s AND allocation_id = %s AND consumption_claim_id IS NULL "
            f"AND EXISTS (SELECT 1 FROM {claim_table} claim "  # noqa: S608
            "WHERE claim.id = %s AND claim.allocation_id = %s "
            "AND claim.consumer_generation = 'v1' "
            "AND claim.consumer_identity_hash = %s "
            "AND claim.consumer_content_hash = %s AND claim.content_hash = %s)",
            [
                claim_pk,
                binding_pk,
                allocation_pk,
                claim_pk,
                allocation_pk,
                consumer_identity_hash,
                consumer_content_hash,
                claim_content_hash,
            ],
        )
        return cast(int, cursor.rowcount)


class CanonicalAccountCreationQuerySet(AppendOnlyQuerySet[_T]):
    def bulk_create(
        self,
        objs: Iterable[_T],
        batch_size: int | None = None,
        ignore_conflicts: bool = False,
        update_conflicts: bool = False,
        update_fields: Collection[str] | None = None,
        unique_fields: Collection[str] | None = None,
    ) -> NoReturn:
        raise ValidationError("canonical creation requires exact appends")

    def _update(self, values: list[tuple[object, object, object]]) -> NoReturn:
        raise ValidationError("canonical creation is append-only")

    def _raw_delete(self, using: str | None) -> NoReturn:
        raise ValidationError("canonical creation is append-only")


class CanonicalAccountCreationManager(AppendOnlyManager[_T]):
    def get_queryset(self) -> CanonicalAccountCreationQuerySet[_T]:
        return CanonicalAccountCreationQuerySet(self.model, using=self._db)

    def bulk_create(self, objs: Iterable[_T], **kwargs: object) -> NoReturn:
        raise ValidationError("canonical creation requires exact appends")


class _AppendOnlyCanonicalAccountCreationModel(models.Model):
    objects = CanonicalAccountCreationManager()

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
            raise ValidationError("canonical creation is append-only")
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
            raise ValidationError("canonical creation is append-only")
        self._require_claim()
        super().save_base(force_insert=force_insert, using=using)

    def _require_claim(self) -> None:
        claim = _CLAIM.get()
        if (
            claim is None
            or claim.token is not _UOW.get()
            or claim.model_type is not type(self)
            or any(getattr(self, name) != value for name, value in claim.values)
        ):
            raise ValidationError("canonical creation requires exact insert claim")

    def delete(
        self, using: object | None = None, keep_parents: bool = False
    ) -> tuple[int, dict[str, int]]:
        raise ValidationError("canonical creation is append-only")


class CanonicalAccountCreationAllocationModel(_AppendOnlyCanonicalAccountCreationModel):
    owner = models.CharField(max_length=32)
    artifact_type = models.CharField(max_length=64)
    schema = models.CharField(max_length=64)
    allocation_id = models.CharField(max_length=192)
    allocation_version = models.CharField(max_length=192)
    canonical_account_namespace = models.CharField(max_length=192)
    canonical_account_id = models.CharField(max_length=192)
    requested_row_user_id = models.PositiveBigIntegerField()
    requested_raw_account_type = models.CharField(max_length=192)
    intended_underlying_unified_account_namespace = models.CharField(max_length=192)
    request_fingerprint_hash = models.CharField(max_length=64)
    requester_actor_id = models.CharField(max_length=192)
    requester_user_id = models.PositiveBigIntegerField()
    requester_role = models.CharField(max_length=192)
    requester_kind = models.CharField(max_length=16)
    requester_is_authenticated = models.BooleanField()
    allocated_at = models.DateTimeField(db_index=True)
    valid_until = models.DateTimeField(db_index=True)
    recorded_service_id = models.CharField(max_length=192)
    recorded_role = models.CharField(max_length=192)
    recorded_kind = models.CharField(max_length=16)
    recorded_is_automated = models.BooleanField()
    intended_purpose = models.CharField(max_length=64)
    permission = models.CharField(max_length=32)
    status = models.CharField(max_length=16)
    canonical_payload = models.JSONField()
    identity_hash = models.CharField(max_length=64, unique=True)
    content_hash = models.CharField(max_length=64, unique=True)
    requester_binding_seal = models.CharField(max_length=64)
    recorder_binding_seal = models.CharField(max_length=64)
    fixed_authority_seal = models.CharField(max_length=64)
    record_seal = models.CharField(max_length=64, unique=True)
    ledger_seal = models.CharField(max_length=64, unique=True)
    persisted_at = models.DateTimeField()

    class Meta(_AppendOnlyCanonicalAccountCreationModel.Meta):
        app_label = "account"
        db_table = "canonical_account_creation_allocation_ledger"
        constraints = [
            models.UniqueConstraint(
                fields=("allocation_id", "allocation_version"), name="acct_create_alloc_id_uq"
            ),
            models.UniqueConstraint(
                fields=("canonical_account_namespace", "canonical_account_id"),
                name="acct_create_alloc_acct_uq",
            ),
            models.UniqueConstraint(
                fields=("requester_actor_id", "requester_user_id", "request_fingerprint_hash"),
                name="acct_create_alloc_req_uq",
            ),
            models.CheckConstraint(
                condition=models.Q(
                    owner="account",
                    artifact_type="canonical_account_creation_allocation",
                    schema="canonical-account-creation-allocation.v1",
                    canonical_account_namespace="account",
                    intended_underlying_unified_account_namespace="simulated-account-row",
                    requester_role="account_creator",
                    requester_kind="human",
                    requester_is_authenticated=True,
                    recorded_role="canonical_account_identity_allocator",
                    recorded_kind="service",
                    recorded_is_automated=True,
                    intended_purpose="simulated_account_create",
                    permission="identity_allocation_only",
                    status="inactive",
                ),
                name="acct_create_alloc_fixed_ck",
            ),
            models.CheckConstraint(
                condition=models.Q(
                    allocated_at__lt=models.F("valid_until"),
                    persisted_at=models.F("allocated_at"),
                    requested_row_user_id=models.F("requester_user_id"),
                ),
                name="acct_create_alloc_clock_ck",
            ),
        ]


class CanonicalAccountCreationBindingModel(_AppendOnlyCanonicalAccountCreationModel):
    consumption_claim = models.OneToOneField(
        "account.CanonicalAccountCreationConsumptionClaimModel",
        on_delete=models.PROTECT,
        related_name="creation_binding_v1",
        null=True,
    )
    allocation = models.OneToOneField(
        CanonicalAccountCreationAllocationModel,
        on_delete=models.PROTECT,
        related_name="creation_binding",
    )
    allocation_content_hash = models.CharField(max_length=64, unique=True)
    owner = models.CharField(max_length=32)
    artifact_type = models.CharField(max_length=64)
    schema = models.CharField(max_length=64)
    binding_id = models.CharField(max_length=192)
    binding_version = models.CharField(max_length=192)
    physical_observation_id = models.CharField(max_length=192)
    physical_observation_version = models.CharField(max_length=192)
    physical_identity_hash = models.CharField(max_length=64)
    physical_content_hash = models.CharField(max_length=64, unique=True)
    account_namespace_claim = models.CharField(max_length=192)
    account_id_claim = models.CharField(max_length=192)
    underlying_unified_account_namespace_claim = models.CharField(max_length=192)
    underlying_unified_account_id_claim = models.PositiveBigIntegerField()
    recorded_service_id = models.CharField(max_length=192)
    recorded_role = models.CharField(max_length=192)
    recorded_kind = models.CharField(max_length=16)
    recorded_is_automated = models.BooleanField()
    recorded_at = models.DateTimeField(db_index=True)
    valid_until = models.DateTimeField(db_index=True)
    account_claim_hash = models.CharField(max_length=64, unique=True)
    underlying_claim_hash = models.CharField(max_length=64, unique=True)
    permission = models.CharField(max_length=64)
    status = models.CharField(max_length=16)
    binding_state = models.CharField(max_length=32)
    owner_assignment_state = models.CharField(max_length=32)
    canonical_payload = models.JSONField()
    identity_hash = models.CharField(max_length=64, unique=True)
    content_hash = models.CharField(max_length=64, unique=True)
    allocation_binding_seal = models.CharField(max_length=64)
    physical_binding_seal = models.CharField(max_length=64)
    recorder_binding_seal = models.CharField(max_length=64)
    fixed_authority_seal = models.CharField(max_length=64)
    record_seal = models.CharField(max_length=64, unique=True)
    ledger_seal = models.CharField(max_length=64, unique=True)
    persisted_at = models.DateTimeField()

    class Meta(_AppendOnlyCanonicalAccountCreationModel.Meta):
        app_label = "account"
        db_table = "canonical_account_creation_binding_ledger"
        constraints = [
            models.UniqueConstraint(
                fields=("binding_id", "binding_version"), name="acct_create_bind_id_uq"
            ),
            models.UniqueConstraint(
                fields=("account_namespace_claim", "account_id_claim"),
                name="acct_create_bind_acct_uq",
            ),
            models.UniqueConstraint(
                fields=(
                    "underlying_unified_account_namespace_claim",
                    "underlying_unified_account_id_claim",
                ),
                name="acct_create_bind_under_uq",
            ),
            models.CheckConstraint(
                condition=models.Q(
                    owner="account",
                    artifact_type="canonical_account_creation_binding",
                    schema="canonical-account-creation-binding.v1",
                    recorded_role="canonical_account_creation_binder",
                    recorded_kind="service",
                    recorded_is_automated=True,
                    permission="identity_binding_evidence_only",
                    status="inactive",
                    binding_state="pending_owner_approval",
                    owner_assignment_state="unknown",
                ),
                name="acct_create_bind_fixed_ck",
            ),
            models.CheckConstraint(
                condition=models.Q(
                    recorded_at__lt=models.F("valid_until"), persisted_at=models.F("recorded_at")
                ),
                name="acct_create_bind_clock_ck",
            ),
        ]


def _reject_delete(
    sender: type[models.Model], instance: models.Model, using: str, origin: object, **kwargs: object
) -> None:
    del sender, instance, using, origin, kwargs
    raise ValidationError("canonical creation is append-only")


for _model in (CanonicalAccountCreationAllocationModel, CanonicalAccountCreationBindingModel):
    pre_delete.connect(_reject_delete, sender=_model, dispatch_uid=f"{_model.__name__}_append_only")


__all__ = ["CanonicalAccountCreationAllocationModel", "CanonicalAccountCreationBindingModel"]
