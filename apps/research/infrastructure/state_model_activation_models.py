"""Claimed append-only ORM ledgers for R6 activation control-plane evidence."""

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

from shared.infrastructure.django_append_only import AppendOnlyManager, AppendOnlyQuerySet

_ModelT = TypeVar("_ModelT", bound=models.Model)
_ACTIVE_R6_ACTIVATION_UOW: ContextVar[object | None] = ContextVar(
    "active_r6_activation_uow",
    default=None,
)


@dataclass(frozen=True)
class _R6ActivationInsertClaim:
    token: object
    model_type: type[models.Model]
    expected_values: tuple[tuple[str, object], ...]


_ACTIVE_R6_ACTIVATION_CLAIM: ContextVar[_R6ActivationInsertClaim | None] = ContextVar(
    "active_r6_activation_insert_claim",
    default=None,
)


def _require_active_r6_activation_uow() -> object:
    """Require the composition-owned activation transaction."""

    token = _ACTIVE_R6_ACTIVATION_UOW.get()
    if token is None:
        raise ValidationError("R6 activation access requires an active unit of work.")
    return token


@contextmanager
def _activate_r6_activation_uow(token: object) -> Iterator[None]:
    """Activate one repository capability token."""

    reset = _ACTIVE_R6_ACTIVATION_UOW.set(token)
    try:
        yield
    finally:
        _ACTIVE_R6_ACTIVATION_UOW.reset(reset)


@contextmanager
def _claim_r6_activation_insert(
    *,
    token: object,
    model_type: type[models.Model],
    expected_values: Mapping[str, object],
) -> Iterator[None]:
    """Authorize one exact model/payload insert inside the active UoW."""

    if _ACTIVE_R6_ACTIVATION_UOW.get() is not token:
        raise ValidationError("R6 activation insert requires its unit of work.")
    claim = _R6ActivationInsertClaim(
        token=token,
        model_type=model_type,
        expected_values=tuple(sorted(expected_values.items(), key=lambda item: item[0])),
    )
    reset = _ACTIVE_R6_ACTIVATION_CLAIM.set(claim)
    try:
        yield
    finally:
        _ACTIVE_R6_ACTIVATION_CLAIM.reset(reset)


def _require_r6_activation_insert_claim(model: models.Model) -> None:
    claim = _ACTIVE_R6_ACTIVATION_CLAIM.get()
    if (
        claim is None
        or claim.token is not _ACTIVE_R6_ACTIVATION_UOW.get()
        or claim.model_type is not type(model)
        or any(
            getattr(model, field_name) != expected for field_name, expected in claim.expected_values
        )
    ):
        raise ValidationError("R6 activation evidence requires an exact insert claim.")


class R6ActivationQuerySet(AppendOnlyQuerySet[_ModelT]):
    """Reject public and private mutation shortcuts."""

    def get_or_create(
        self,
        defaults: Mapping[str, object] | None = None,
        **kwargs: object,
    ) -> NoReturn:
        raise ValidationError("R6 activation get_or_create is forbidden.")

    def update_or_create(
        self,
        defaults: Mapping[str, object] | None = None,
        create_defaults: Mapping[str, object] | None = None,
        **kwargs: object,
    ) -> NoReturn:
        raise ValidationError("R6 activation update_or_create is forbidden.")

    def bulk_create(
        self,
        objs: Iterable[_ModelT],
        batch_size: int | None = None,
        ignore_conflicts: bool = False,
        update_conflicts: bool = False,
        update_fields: Collection[str] | None = None,
        unique_fields: Collection[str] | None = None,
    ) -> NoReturn:
        raise ValidationError("R6 activation rows require exact repository appends.")

    def _update(self, values: object) -> NoReturn:
        raise ValidationError("R6 activation evidence cannot be updated.")

    def _raw_delete(self, using: str | None) -> NoReturn:
        raise ValidationError("R6 activation evidence cannot be deleted.")

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
            raise ValidationError("R6 activation private insert is forbidden.")
        for item in items:
            _require_r6_activation_insert_claim(item)
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
        raise ValidationError("R6 activation private bulk insert is forbidden.")


class R6ActivationManager(AppendOnlyManager[_ModelT]):
    """Expose identical guards through default and base managers."""

    def get_queryset(self) -> R6ActivationQuerySet[_ModelT]:
        return R6ActivationQuerySet(self.model, using=self._db)

    def bulk_create(
        self,
        objs: Iterable[_ModelT],
        batch_size: int | None = None,
        ignore_conflicts: bool = False,
        update_conflicts: bool = False,
        update_fields: Collection[str] | None = None,
        unique_fields: Collection[str] | None = None,
    ) -> NoReturn:
        raise ValidationError("R6 activation rows require exact repository appends.")

    def get_or_create(
        self,
        defaults: Mapping[str, object] | None = None,
        **kwargs: object,
    ) -> NoReturn:
        raise ValidationError("R6 activation get_or_create is forbidden.")

    def update_or_create(
        self,
        defaults: Mapping[str, object] | None = None,
        create_defaults: Mapping[str, object] | None = None,
        **kwargs: object,
    ) -> NoReturn:
        raise ValidationError("R6 activation update_or_create is forbidden.")


class R6ActivationAppendOnlyModel(models.Model):
    """Permit only one repository-claimed database-keyed insert."""

    objects = R6ActivationManager()

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
            raise ValidationError("R6 activation evidence is append-only.")
        _require_r6_activation_insert_claim(self)
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
            raise ValidationError("R6 activation evidence is append-only.")
        _require_r6_activation_insert_claim(self)
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
        raise ValidationError("R6 activation evidence cannot be deleted.")


class R6ActivationAuthorizationModel(R6ActivationAppendOnlyModel):
    """Immutable exact owner authorization snapshot."""

    authorization_id = models.CharField(max_length=192)
    authorization_version = models.CharField(max_length=192)
    event_id = models.CharField(max_length=192)
    event_version = models.CharField(max_length=192)
    scope_id = models.CharField(max_length=192)
    scope_version = models.CharField(max_length=192)
    scope_hash = models.CharField(max_length=64)
    action = models.CharField(max_length=16)
    subject_approval_id = models.CharField(max_length=192)
    subject_approval_version = models.CharField(max_length=192)
    subject_approval_hash = models.CharField(max_length=64)
    rollback_approval_id = models.CharField(max_length=192, null=True)
    rollback_approval_version = models.CharField(max_length=192, null=True)
    rollback_approval_hash = models.CharField(max_length=64, null=True)
    expected_sequence = models.PositiveIntegerField()
    expected_previous_event_hash = models.CharField(max_length=64, null=True)
    owner = models.CharField(max_length=192)
    issued_at = models.DateTimeField()
    owner_recorded_at = models.DateTimeField()
    valid_until = models.DateTimeField()
    reason_codes = models.JSONField()
    evidence_ref = models.CharField(max_length=300)
    canonical_payload = models.JSONField()
    content_hash = models.CharField(max_length=64, unique=True)
    ledger_recorded_at = models.DateTimeField(db_index=True)
    ledger_header_hash = models.CharField(max_length=64)
    research_only = models.BooleanField(default=True)
    must_not_use_for_decision = models.BooleanField(default=True)
    must_not_replace_regime = models.BooleanField(default=True)
    must_not_publish_current = models.BooleanField(default=True)
    must_not_execute = models.BooleanField(default=True)
    persisted_at = models.DateTimeField(auto_now_add=True)

    class Meta(R6ActivationAppendOnlyModel.Meta):
        db_table = "research_r6_activation_authorization"
        indexes = [
            models.Index(
                fields=["scope_id", "scope_version", "scope_hash", "ledger_recorded_at"],
                name="res_r6_act_auth_pit_ix",
            )
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["authorization_id", "authorization_version"],
                name="res_r6_act_auth_ident_uq",
            ),
            models.UniqueConstraint(
                fields=["event_id", "event_version"],
                name="res_r6_act_auth_event_uq",
            ),
            models.CheckConstraint(
                condition=models.Q(
                    action__in=("activate", "retire", "rollback"),
                    owner="research",
                ),
                name="res_r6_act_auth_type_ck",
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(issued_at__lte=models.F("owner_recorded_at"))
                    & models.Q(owner_recorded_at__lt=models.F("valid_until"))
                    & models.Q(owner_recorded_at__lte=models.F("ledger_recorded_at"))
                ),
                name="res_r6_act_auth_clock_ck",
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(
                        expected_sequence=1,
                        expected_previous_event_hash__isnull=True,
                    )
                    | models.Q(
                        expected_sequence__gt=1,
                        expected_previous_event_hash__isnull=False,
                    )
                ),
                name="res_r6_act_auth_head_ck",
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(
                        action="rollback",
                        rollback_approval_id__isnull=False,
                        rollback_approval_version__isnull=False,
                        rollback_approval_hash__isnull=False,
                    )
                    | (
                        ~models.Q(action="rollback")
                        & models.Q(
                            rollback_approval_id__isnull=True,
                            rollback_approval_version__isnull=True,
                            rollback_approval_hash__isnull=True,
                        )
                    )
                ),
                name="res_r6_act_auth_roll_ck",
            ),
            models.CheckConstraint(
                condition=models.Q(
                    research_only=True,
                    must_not_use_for_decision=True,
                    must_not_replace_regime=True,
                    must_not_publish_current=True,
                    must_not_execute=True,
                ),
                name="res_r6_act_auth_safe_ck",
            ),
        ]


class R6ActivationEventModel(R6ActivationAppendOnlyModel):
    """Immutable event in one scope-local activation stack."""

    authorization_row = models.OneToOneField(
        R6ActivationAuthorizationModel,
        on_delete=models.PROTECT,
        related_name="activation_event",
    )
    event_id = models.CharField(max_length=192)
    event_version = models.CharField(max_length=192)
    scope_id = models.CharField(max_length=192)
    scope_version = models.CharField(max_length=192)
    scope_hash = models.CharField(max_length=64)
    action = models.CharField(max_length=16)
    subject_approval_id = models.CharField(max_length=192)
    subject_approval_version = models.CharField(max_length=192)
    subject_approval_hash = models.CharField(max_length=64)
    rollback_approval_id = models.CharField(max_length=192, null=True)
    rollback_approval_version = models.CharField(max_length=192, null=True)
    rollback_approval_hash = models.CharField(max_length=64, null=True)
    authorization_id = models.CharField(max_length=192)
    authorization_version = models.CharField(max_length=192)
    authorization_hash = models.CharField(max_length=64)
    sequence = models.PositiveIntegerField()
    occurred_at = models.DateTimeField()
    recorded_at = models.DateTimeField()
    previous_event_hash = models.CharField(max_length=64, null=True)
    reason_codes = models.JSONField()
    canonical_payload = models.JSONField()
    content_hash = models.CharField(max_length=64, unique=True)
    ledger_recorded_at = models.DateTimeField(db_index=True)
    ledger_header_hash = models.CharField(max_length=64)
    research_only = models.BooleanField(default=True)
    must_not_use_for_decision = models.BooleanField(default=True)
    must_not_replace_regime = models.BooleanField(default=True)
    must_not_publish_current = models.BooleanField(default=True)
    must_not_execute = models.BooleanField(default=True)
    # Operational insertion metadata only. PIT semantics use sealed ledger_recorded_at.
    persisted_at = models.DateTimeField(auto_now_add=True)

    class Meta(R6ActivationAppendOnlyModel.Meta):
        db_table = "research_r6_activation_event"
        indexes = [
            models.Index(
                fields=["scope_id", "scope_version", "scope_hash", "ledger_recorded_at"],
                name="res_r6_act_evt_pit_ix",
            )
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["event_id", "event_version"],
                name="res_r6_act_evt_ident_uq",
            ),
            models.UniqueConstraint(
                fields=["scope_id", "scope_version", "sequence"],
                name="res_r6_act_evt_sid_seq_uq",
            ),
            models.UniqueConstraint(
                fields=["scope_hash", "sequence"],
                name="res_r6_act_evt_hash_seq_uq",
            ),
            models.CheckConstraint(
                condition=models.Q(action__in=("activate", "retire", "rollback")),
                name="res_r6_act_evt_type_ck",
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(occurred_at__lte=models.F("recorded_at"))
                    & models.Q(recorded_at__lte=models.F("ledger_recorded_at"))
                ),
                name="res_r6_act_evt_clock_ck",
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(sequence=1, previous_event_hash__isnull=True)
                    | models.Q(sequence__gt=1, previous_event_hash__isnull=False)
                ),
                name="res_r6_act_evt_head_ck",
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(
                        action="rollback",
                        rollback_approval_id__isnull=False,
                        rollback_approval_version__isnull=False,
                        rollback_approval_hash__isnull=False,
                    )
                    | (
                        ~models.Q(action="rollback")
                        & models.Q(
                            rollback_approval_id__isnull=True,
                            rollback_approval_version__isnull=True,
                            rollback_approval_hash__isnull=True,
                        )
                    )
                ),
                name="res_r6_act_evt_roll_ck",
            ),
            models.CheckConstraint(
                condition=models.Q(
                    research_only=True,
                    must_not_use_for_decision=True,
                    must_not_replace_regime=True,
                    must_not_publish_current=True,
                    must_not_execute=True,
                ),
                name="res_r6_act_evt_safe_ck",
            ),
        ]


class R6ActivationStreamCommitModel(R6ActivationAppendOnlyModel):
    """Immutable three-way commit anchor for one activation transition."""

    authorization_row = models.OneToOneField(
        R6ActivationAuthorizationModel,
        on_delete=models.PROTECT,
        related_name="activation_stream_commit",
    )
    event_row = models.OneToOneField(
        R6ActivationEventModel,
        on_delete=models.PROTECT,
        related_name="activation_stream_commit",
    )
    authorization_id = models.CharField(max_length=192)
    authorization_version = models.CharField(max_length=192)
    authorization_hash = models.CharField(max_length=64)
    event_id = models.CharField(max_length=192)
    event_version = models.CharField(max_length=192)
    event_hash = models.CharField(max_length=64)
    scope_id = models.CharField(max_length=192)
    scope_version = models.CharField(max_length=192)
    scope_hash = models.CharField(max_length=64)
    sequence = models.PositiveIntegerField()
    previous_event_hash = models.CharField(max_length=64, null=True)
    ledger_recorded_at = models.DateTimeField(db_index=True)
    ledger_header_hash = models.CharField(max_length=64, unique=True)
    research_only = models.BooleanField(default=True)
    must_not_use_for_decision = models.BooleanField(default=True)
    must_not_replace_regime = models.BooleanField(default=True)
    must_not_publish_current = models.BooleanField(default=True)
    must_not_execute = models.BooleanField(default=True)
    persisted_at = models.DateTimeField(auto_now_add=True)

    class Meta(R6ActivationAppendOnlyModel.Meta):
        db_table = "research_r6_activation_stream_commit"
        indexes = [
            models.Index(
                fields=["scope_id", "scope_version", "scope_hash", "ledger_recorded_at"],
                name="res_r6_act_cmt_pit_ix",
            )
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["authorization_id", "authorization_version"],
                name="res_r6_act_cmt_auth_uq",
            ),
            models.UniqueConstraint(
                fields=["event_id", "event_version"],
                name="res_r6_act_cmt_event_uq",
            ),
            models.UniqueConstraint(
                fields=["scope_id", "scope_version", "sequence"],
                name="res_r6_act_cmt_sid_seq_uq",
            ),
            models.UniqueConstraint(
                fields=["scope_hash", "sequence"],
                name="res_r6_act_cmt_hash_seq_uq",
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(sequence=1, previous_event_hash__isnull=True)
                    | models.Q(sequence__gt=1, previous_event_hash__isnull=False)
                ),
                name="res_r6_act_cmt_head_ck",
            ),
            models.CheckConstraint(
                condition=models.Q(
                    research_only=True,
                    must_not_use_for_decision=True,
                    must_not_replace_regime=True,
                    must_not_publish_current=True,
                    must_not_execute=True,
                ),
                name="res_r6_act_cmt_safe_ck",
            ),
        ]


class R6ActivationAuditSnapshotModel(R6ActivationAppendOnlyModel):
    """Immutable materialized manifest for stable activation audit paging."""

    snapshot_id = models.CharField(max_length=192)
    snapshot_version = models.CharField(max_length=192)
    as_of = models.DateTimeField(db_index=True)
    created_at = models.DateTimeField(db_index=True)
    entry_count = models.PositiveIntegerField()
    canonical_payload = models.JSONField()
    content_hash = models.CharField(max_length=64, unique=True)
    internal_audit_only = models.BooleanField(default=True)
    research_only = models.BooleanField(default=True)
    must_not_use_for_decision = models.BooleanField(default=True)
    must_not_replace_regime = models.BooleanField(default=True)
    must_not_publish_current = models.BooleanField(default=True)
    must_not_execute = models.BooleanField(default=True)
    persisted_at = models.DateTimeField(auto_now_add=True)

    class Meta(R6ActivationAppendOnlyModel.Meta):
        db_table = "research_r6_activation_audit_snapshot"
        indexes = [
            models.Index(
                fields=["as_of", "created_at"],
                name="res_r6_act_snap_pit_ix",
            )
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["snapshot_id", "snapshot_version"],
                name="res_r6_act_snap_ident_uq",
            ),
            models.CheckConstraint(
                condition=models.Q(as_of__lte=models.F("created_at")),
                name="res_r6_act_snap_clock_ck",
            ),
            models.CheckConstraint(
                condition=models.Q(
                    internal_audit_only=True,
                    research_only=True,
                    must_not_use_for_decision=True,
                    must_not_replace_regime=True,
                    must_not_publish_current=True,
                    must_not_execute=True,
                ),
                name="res_r6_act_snap_safe_ck",
            ),
        ]


@receiver(pre_delete, sender=R6ActivationAuthorizationModel, weak=False)
@receiver(pre_delete, sender=R6ActivationEventModel, weak=False)
@receiver(pre_delete, sender=R6ActivationStreamCommitModel, weak=False)
@receiver(pre_delete, sender=R6ActivationAuditSnapshotModel, weak=False)
def _reject_r6_activation_collector_delete(
    *,
    sender: type[models.Model],
    instance: models.Model,
    using: str,
    origin: object | None,
    **kwargs: object,
) -> NoReturn:
    """Reject Django Collector, cascade, and direct deletion paths."""

    raise ValidationError("R6 activation evidence cannot be deleted.")


__all__ = [
    "R6ActivationAuditSnapshotModel",
    "R6ActivationAuthorizationModel",
    "R6ActivationEventModel",
    "R6ActivationStreamCommitModel",
    "_activate_r6_activation_uow",
    "_claim_r6_activation_insert",
    "_require_active_r6_activation_uow",
]
