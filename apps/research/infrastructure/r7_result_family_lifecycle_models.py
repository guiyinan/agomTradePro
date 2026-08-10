"""Claimed append-only ORM ledgers for R7 result-family lifecycle evidence."""

from __future__ import annotations

from collections.abc import Callable, Collection, Iterable, Iterator, Mapping
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from typing import NoReturn, TypeVar, cast

from django.core.exceptions import ValidationError
from django.db import models
from django.db.models.base import ModelBase
from django.db.models.signals import pre_delete
from django.dispatch import receiver

from apps.research.infrastructure.r7_research_result_lifecycle_models import (
    R7ResultLifecycleEventModel,
)
from apps.research.infrastructure.r7_research_result_models import R7ResearchResultModel
from shared.infrastructure.django_append_only import AppendOnlyManager, AppendOnlyQuerySet

_ModelT = TypeVar("_ModelT", bound=models.Model)
_ACTIVE_R7_FAMILY_UOW: ContextVar[object | None] = ContextVar(
    "active_r7_family_lifecycle_uow",
    default=None,
)


@dataclass(frozen=True)
class _R7FamilyInsertClaim:
    token: object
    model_type: type[models.Model]
    expected_values: tuple[tuple[str, object], ...]


_ACTIVE_R7_FAMILY_CLAIM: ContextVar[_R7FamilyInsertClaim | None] = ContextVar(
    "active_r7_family_lifecycle_insert_claim",
    default=None,
)


def _require_active_r7_family_uow() -> object:
    """Require the composition-owned family transaction."""

    token = _ACTIVE_R7_FAMILY_UOW.get()
    if token is None:
        raise ValidationError("R7 family lifecycle access requires an active unit of work.")
    return token


@contextmanager
def _activate_r7_family_uow(token: object) -> Iterator[None]:
    """Activate one private repository capability token."""

    reset = _ACTIVE_R7_FAMILY_UOW.set(token)
    try:
        yield
    finally:
        _ACTIVE_R7_FAMILY_UOW.reset(reset)


@contextmanager
def _claim_r7_family_insert(
    *,
    token: object,
    model_type: type[models.Model],
    expected_values: Mapping[str, object],
) -> Iterator[None]:
    """Authorize one exact model/payload insert inside the active UoW."""

    if _ACTIVE_R7_FAMILY_UOW.get() is not token:
        raise ValidationError("R7 family lifecycle insert requires its unit of work.")
    claim = _R7FamilyInsertClaim(
        token=token,
        model_type=model_type,
        expected_values=tuple(sorted(expected_values.items(), key=lambda item: item[0])),
    )
    reset = _ACTIVE_R7_FAMILY_CLAIM.set(claim)
    try:
        yield
    finally:
        _ACTIVE_R7_FAMILY_CLAIM.reset(reset)


def _require_r7_family_insert_claim(model: models.Model) -> None:
    claim = _ACTIVE_R7_FAMILY_CLAIM.get()
    if (
        claim is None
        or claim.token is not _ACTIVE_R7_FAMILY_UOW.get()
        or claim.model_type is not type(model)
        or any(
            getattr(model, field_name) != expected for field_name, expected in claim.expected_values
        )
    ):
        raise ValidationError("R7 family evidence requires an exact insert claim.")


class R7FamilyLifecycleQuerySet(AppendOnlyQuerySet[_ModelT]):
    """Reject public and private mutation shortcuts."""

    def get_or_create(
        self,
        defaults: Mapping[str, object] | None = None,
        **kwargs: object,
    ) -> NoReturn:
        raise ValidationError("R7 family get_or_create is forbidden.")

    def update_or_create(
        self,
        defaults: Mapping[str, object] | None = None,
        create_defaults: Mapping[str, object] | None = None,
        **kwargs: object,
    ) -> NoReturn:
        raise ValidationError("R7 family update_or_create is forbidden.")

    def bulk_create(
        self,
        objs: Iterable[_ModelT],
        batch_size: int | None = None,
        ignore_conflicts: bool = False,
        update_conflicts: bool = False,
        update_fields: Collection[str] | None = None,
        unique_fields: Collection[str] | None = None,
    ) -> NoReturn:
        raise ValidationError("R7 family rows require exact repository appends.")

    def _update(self, values: object) -> NoReturn:
        raise ValidationError("R7 family evidence cannot be updated.")

    def _raw_delete(self, using: str | None) -> NoReturn:
        raise ValidationError("R7 family evidence cannot be deleted.")

    def _insert(
        self,
        objs: Iterable[_ModelT],
        fields: Iterable[object],
        returning_fields: Iterable[object] | None = None,
        raw: bool = False,
        using: str | None = None,
        on_conflict: object | None = None,
        update_fields: Iterable[object] | None = None,
        unique_fields: Iterable[object] | None = None,
    ) -> list[tuple[object, ...]]:
        items = list(objs)
        if (
            not items
            or raw
            or on_conflict is not None
            or update_fields is not None
            or unique_fields is not None
            or (using is not None and using != self.db)
        ):
            raise ValidationError("R7 family private insert is forbidden.")
        for item in items:
            _require_r7_family_insert_claim(item)
        insert = cast(
            Callable[..., list[tuple[object, ...]]],
            getattr(super(), "_insert"),  # noqa: B009 - typed private Django boundary
        )
        return insert(
            items,
            fields,
            returning_fields=returning_fields,
            raw=False,
            using=using,
            on_conflict=None,
            update_fields=None,
            unique_fields=None,
        )

    def _batched_insert(
        self,
        objs: list[_ModelT],
        fields: list[object],
        batch_size: int | None,
        on_conflict: object | None = None,
        update_fields: Iterable[object] | None = None,
        unique_fields: Iterable[object] | None = None,
    ) -> NoReturn:
        raise ValidationError("R7 family private bulk insert is forbidden.")


class R7FamilyLifecycleManager(AppendOnlyManager[_ModelT]):
    """Expose identical guards through default and base managers."""

    def get_queryset(self) -> R7FamilyLifecycleQuerySet[_ModelT]:
        return R7FamilyLifecycleQuerySet(self.model, using=self._db)

    def bulk_create(
        self,
        objs: Iterable[_ModelT],
        batch_size: int | None = None,
        ignore_conflicts: bool = False,
        update_conflicts: bool = False,
        update_fields: Collection[str] | None = None,
        unique_fields: Collection[str] | None = None,
    ) -> NoReturn:
        raise ValidationError("R7 family rows require exact repository appends.")

    def get_or_create(
        self,
        defaults: Mapping[str, object] | None = None,
        **kwargs: object,
    ) -> NoReturn:
        raise ValidationError("R7 family get_or_create is forbidden.")

    def update_or_create(
        self,
        defaults: Mapping[str, object] | None = None,
        create_defaults: Mapping[str, object] | None = None,
        **kwargs: object,
    ) -> NoReturn:
        raise ValidationError("R7 family update_or_create is forbidden.")


class R7FamilyAppendOnlyModel(models.Model):
    """Permit only one repository-claimed database-keyed insert."""

    objects = R7FamilyLifecycleManager()

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
            raise ValidationError("R7 family evidence is append-only.")
        _require_r7_family_insert_claim(self)
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
            raise ValidationError("R7 family evidence is append-only.")
        _require_r7_family_insert_claim(self)
        super().save_base(
            raw=False,
            force_insert=force_insert,
            force_update=False,
            using=using,
            update_fields=None,
        )

    def delete(
        self,
        using: object | None = None,
        keep_parents: bool = False,
    ) -> tuple[int, dict[str, int]]:
        raise ValidationError("R7 family evidence cannot be deleted.")


class R7FamilyLifecycleAuthorizationModel(R7FamilyAppendOnlyModel):
    """Owner authorization receipt; never an authorization provider itself."""

    authorization_id = models.CharField(max_length=192)
    authorization_version = models.CharField(max_length=192)
    family_id = models.CharField(max_length=192)
    family_version = models.CharField(max_length=192)
    family_hash = models.CharField(max_length=64)
    event_id = models.CharField(max_length=192)
    event_version = models.CharField(max_length=192)
    action = models.CharField(max_length=16)
    expected_sequence = models.PositiveIntegerField()
    expected_previous_event_id = models.CharField(max_length=192, null=True)
    expected_previous_event_version = models.CharField(max_length=192, null=True)
    expected_previous_event_hash = models.CharField(max_length=64, null=True)
    subject_result = models.ForeignKey(
        R7ResearchResultModel,
        on_delete=models.PROTECT,
        related_name="+",
    )
    subject_result_id_value = models.CharField(max_length=192)
    subject_result_version = models.CharField(max_length=192)
    subject_result_hash = models.CharField(max_length=64)
    subject_local_lifecycle_head = models.ForeignKey(
        R7ResultLifecycleEventModel,
        on_delete=models.PROTECT,
        related_name="+",
    )
    subject_owner_attestation_hash = models.CharField(max_length=64)
    rollback_target_result = models.ForeignKey(
        R7ResearchResultModel,
        on_delete=models.PROTECT,
        related_name="+",
        null=True,
    )
    rollback_target_result_id_value = models.CharField(max_length=192, null=True)
    rollback_target_result_version = models.CharField(max_length=192, null=True)
    rollback_target_result_hash = models.CharField(max_length=64, null=True)
    rollback_target_local_lifecycle_head = models.ForeignKey(
        R7ResultLifecycleEventModel,
        on_delete=models.PROTECT,
        related_name="+",
        null=True,
    )
    rollback_target_owner_attestation_hash = models.CharField(max_length=64, null=True)
    owner = models.CharField(max_length=64)
    issued_at = models.DateTimeField()
    owner_recorded_at = models.DateTimeField()
    valid_until = models.DateTimeField()
    payload_schema_version = models.CharField(max_length=96)
    payload = models.JSONField()
    content_hash = models.CharField(max_length=64, unique=True)
    ledger_recorded_at = models.DateTimeField(db_index=True)
    row_hash = models.CharField(max_length=64, unique=True)

    class Meta(R7FamilyAppendOnlyModel.Meta):
        db_table = "research_r7_family_lifecycle_authorization"
        indexes = [
            models.Index(
                fields=["family_id", "family_version", "ledger_recorded_at"],
                name="res_r7_fam_auth_pit_idx",
            )
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["authorization_id", "authorization_version"],
                name="res_r7_fam_auth_ident_uq",
            ),
            models.UniqueConstraint(
                fields=["event_id", "event_version"],
                name="res_r7_fam_auth_event_uq",
            ),
            models.CheckConstraint(
                condition=models.Q(issued_at__lte=models.F("owner_recorded_at"))
                & models.Q(owner_recorded_at__lt=models.F("valid_until"))
                & models.Q(owner_recorded_at__lte=models.F("ledger_recorded_at")),
                name="res_r7_fam_auth_clock_ck",
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(
                        expected_sequence=1,
                        expected_previous_event_id__isnull=True,
                        expected_previous_event_version__isnull=True,
                        expected_previous_event_hash__isnull=True,
                    )
                    | models.Q(
                        expected_sequence__gt=1,
                        expected_previous_event_id__isnull=False,
                        expected_previous_event_version__isnull=False,
                        expected_previous_event_hash__isnull=False,
                    )
                ),
                name="res_r7_fam_auth_prev_ck",
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(
                        action="rollback",
                        rollback_target_result__isnull=False,
                        rollback_target_result_id_value__isnull=False,
                        rollback_target_result_version__isnull=False,
                        rollback_target_result_hash__isnull=False,
                        rollback_target_local_lifecycle_head__isnull=False,
                        rollback_target_owner_attestation_hash__isnull=False,
                    )
                    | models.Q(
                        action__in=("promote", "retire"),
                        rollback_target_result__isnull=True,
                        rollback_target_result_id_value__isnull=True,
                        rollback_target_result_version__isnull=True,
                        rollback_target_result_hash__isnull=True,
                        rollback_target_local_lifecycle_head__isnull=True,
                        rollback_target_owner_attestation_hash__isnull=True,
                    )
                ),
                name="res_r7_fam_auth_target_ck",
            ),
        ]


class R7FamilyLifecycleEventModel(R7FamilyAppendOnlyModel):
    """Canonical family event bound to exact local result evidence."""

    authorization_row = models.OneToOneField(
        R7FamilyLifecycleAuthorizationModel,
        on_delete=models.PROTECT,
        related_name="+",
    )
    family_id = models.CharField(max_length=192)
    family_version = models.CharField(max_length=192)
    family_hash = models.CharField(max_length=64)
    event_id = models.CharField(max_length=192)
    event_version = models.CharField(max_length=192)
    action = models.CharField(max_length=16)
    sequence = models.PositiveIntegerField()
    subject_result = models.ForeignKey(
        R7ResearchResultModel,
        on_delete=models.PROTECT,
        related_name="+",
    )
    subject_local_lifecycle_head = models.ForeignKey(
        R7ResultLifecycleEventModel,
        on_delete=models.PROTECT,
        related_name="+",
    )
    rollback_target_result = models.ForeignKey(
        R7ResearchResultModel,
        on_delete=models.PROTECT,
        related_name="+",
        null=True,
    )
    rollback_target_local_lifecycle_head = models.ForeignKey(
        R7ResultLifecycleEventModel,
        on_delete=models.PROTECT,
        related_name="+",
        null=True,
    )
    occurred_at = models.DateTimeField()
    owner_recorded_at = models.DateTimeField()
    previous_event_hash = models.CharField(max_length=64, null=True)
    payload_schema_version = models.CharField(max_length=96)
    payload = models.JSONField()
    content_hash = models.CharField(max_length=64, unique=True)
    ledger_recorded_at = models.DateTimeField(db_index=True)
    row_hash = models.CharField(max_length=64, unique=True)

    class Meta(R7FamilyAppendOnlyModel.Meta):
        db_table = "research_r7_family_lifecycle_event"
        indexes = [
            models.Index(
                fields=["family_id", "family_version", "ledger_recorded_at"],
                name="res_r7_fam_evt_pit_idx",
            )
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["event_id", "event_version"],
                name="res_r7_fam_evt_ident_uq",
            ),
            models.UniqueConstraint(
                fields=["family_id", "family_version", "sequence"],
                name="res_r7_fam_evt_id_seq_uq",
            ),
            models.UniqueConstraint(
                fields=["family_hash", "sequence"],
                name="res_r7_fam_evt_hash_seq_uq",
            ),
            models.CheckConstraint(
                condition=models.Q(occurred_at__lte=models.F("owner_recorded_at"))
                & models.Q(owner_recorded_at__lte=models.F("ledger_recorded_at")),
                name="res_r7_fam_evt_clock_ck",
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(sequence=1, previous_event_hash__isnull=True)
                    | models.Q(sequence__gt=1, previous_event_hash__isnull=False)
                ),
                name="res_r7_fam_evt_prev_ck",
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(
                        action="rollback",
                        rollback_target_result__isnull=False,
                        rollback_target_local_lifecycle_head__isnull=False,
                    )
                    | models.Q(
                        action__in=("promote", "retire"),
                        rollback_target_result__isnull=True,
                        rollback_target_local_lifecycle_head__isnull=True,
                    )
                ),
                name="res_r7_fam_evt_target_ck",
            ),
        ]


class R7FamilyLifecycleStreamCommitModel(R7FamilyAppendOnlyModel):
    """Third-party completeness anchor for each authorization/event pair."""

    authorization_row = models.OneToOneField(
        R7FamilyLifecycleAuthorizationModel,
        on_delete=models.PROTECT,
        related_name="+",
    )
    event_row = models.OneToOneField(
        R7FamilyLifecycleEventModel,
        on_delete=models.PROTECT,
        related_name="+",
    )
    family_id = models.CharField(max_length=192)
    family_version = models.CharField(max_length=192)
    family_hash = models.CharField(max_length=64)
    sequence = models.PositiveIntegerField()
    authorization_id = models.CharField(max_length=192)
    authorization_version = models.CharField(max_length=192)
    authorization_hash = models.CharField(max_length=64)
    event_id = models.CharField(max_length=192)
    event_version = models.CharField(max_length=192)
    event_hash = models.CharField(max_length=64)
    subject_result_hash = models.CharField(max_length=64)
    subject_local_lifecycle_head_hash = models.CharField(max_length=64)
    rollback_target_result_hash = models.CharField(max_length=64, null=True)
    rollback_target_local_lifecycle_head_hash = models.CharField(max_length=64, null=True)
    ledger_recorded_at = models.DateTimeField(db_index=True)
    content_hash = models.CharField(max_length=64, unique=True)

    class Meta(R7FamilyAppendOnlyModel.Meta):
        db_table = "research_r7_family_lifecycle_stream_commit"
        constraints = [
            models.UniqueConstraint(
                fields=["family_id", "family_version", "sequence"],
                name="res_r7_fam_com_id_seq_uq",
            ),
            models.UniqueConstraint(
                fields=["family_hash", "sequence"],
                name="res_r7_fam_com_hash_seq_uq",
            ),
            models.UniqueConstraint(
                fields=["authorization_id", "authorization_version"],
                name="res_r7_fam_com_auth_uq",
            ),
            models.UniqueConstraint(
                fields=["event_id", "event_version"],
                name="res_r7_fam_com_event_uq",
            ),
        ]


class R7FamilyLifecycleAuditSnapshotModel(R7FamilyAppendOnlyModel):
    """Immutable signed-audit manifest materialization."""

    snapshot_id = models.CharField(max_length=192)
    snapshot_version = models.CharField(max_length=96)
    family_id = models.CharField(max_length=192)
    family_version = models.CharField(max_length=192)
    family_hash = models.CharField(max_length=64)
    as_of = models.DateTimeField()
    total_count = models.PositiveIntegerField()
    manifest_hash = models.CharField(max_length=64)
    payload_schema_version = models.CharField(max_length=96)
    payload = models.JSONField()
    created_at = models.DateTimeField()
    ledger_recorded_at = models.DateTimeField(db_index=True)
    content_hash = models.CharField(max_length=64, unique=True)

    class Meta(R7FamilyAppendOnlyModel.Meta):
        db_table = "research_r7_family_lifecycle_audit_snapshot"
        constraints = [
            models.UniqueConstraint(
                fields=["snapshot_id", "snapshot_version"],
                name="res_r7_fam_audit_ident_uq",
            ),
            models.CheckConstraint(
                condition=models.Q(as_of__lte=models.F("created_at"))
                & models.Q(created_at__lte=models.F("ledger_recorded_at")),
                name="res_r7_fam_audit_clock_ck",
            ),
        ]


@receiver(
    pre_delete,
    sender=R7FamilyLifecycleAuthorizationModel,
    dispatch_uid="reject_r7_family_authorization_collector_delete",
)
@receiver(
    pre_delete,
    sender=R7FamilyLifecycleEventModel,
    dispatch_uid="reject_r7_family_event_collector_delete",
)
@receiver(
    pre_delete,
    sender=R7FamilyLifecycleStreamCommitModel,
    dispatch_uid="reject_r7_family_commit_collector_delete",
)
@receiver(
    pre_delete,
    sender=R7FamilyLifecycleAuditSnapshotModel,
    dispatch_uid="reject_r7_family_audit_collector_delete",
)
def _reject_r7_family_collector_delete(
    sender: type[models.Model],
    instance: models.Model,
    using: str,
    origin: object | None,
    **kwargs: object,
) -> NoReturn:
    del sender, instance, using, origin, kwargs
    raise ValidationError("R7 family evidence cannot be deleted by Collector.")


__all__ = [
    "R7FamilyLifecycleAuditSnapshotModel",
    "R7FamilyLifecycleAuthorizationModel",
    "R7FamilyLifecycleEventModel",
    "R7FamilyLifecycleStreamCommitModel",
]
