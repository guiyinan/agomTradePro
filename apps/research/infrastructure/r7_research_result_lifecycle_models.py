"""Append-only ORM ledgers for R7 result Promotion and retirement."""

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

from apps.research.infrastructure.r7_research_result_models import R7ResearchResultModel
from shared.infrastructure.django_append_only import AppendOnlyManager, AppendOnlyQuerySet

_ModelT = TypeVar("_ModelT", bound=models.Model)
_ACTIVE_R7_RESULT_LIFECYCLE_UOW: ContextVar[object | None] = ContextVar(
    "active_r7_result_lifecycle_uow",
    default=None,
)


@dataclass(frozen=True)
class _R7ResultLifecycleInsertClaim:
    token: object
    expected_values: tuple[tuple[str, object], ...]


_ACTIVE_R7_RESULT_LIFECYCLE_CLAIM: ContextVar[_R7ResultLifecycleInsertClaim | None] = ContextVar(
    "active_r7_result_lifecycle_claim", default=None
)


def _require_active_r7_result_lifecycle_uow() -> object:
    """Require the composition-owned lifecycle transaction."""

    token = _ACTIVE_R7_RESULT_LIFECYCLE_UOW.get()
    if token is None:
        raise ValidationError("R7 result lifecycle access requires an active unit of work.")
    return token


@contextmanager
def _activate_r7_result_lifecycle_uow(token: object) -> Iterator[None]:
    """Activate one repository-owned lifecycle capability token."""

    reset = _ACTIVE_R7_RESULT_LIFECYCLE_UOW.set(token)
    try:
        yield
    finally:
        _ACTIVE_R7_RESULT_LIFECYCLE_UOW.reset(reset)


@contextmanager
def _claim_r7_result_lifecycle_insert(
    *,
    token: object,
    expected_values: Mapping[str, object],
) -> Iterator[None]:
    """Bind one exact insert payload to the active repository token."""

    if _ACTIVE_R7_RESULT_LIFECYCLE_UOW.get() is not token:
        raise ValidationError("R7 result lifecycle insert requires its unit of work.")
    claim = _R7ResultLifecycleInsertClaim(
        token=token,
        expected_values=tuple(sorted(expected_values.items(), key=lambda item: item[0])),
    )
    reset = _ACTIVE_R7_RESULT_LIFECYCLE_CLAIM.set(claim)
    try:
        yield
    finally:
        _ACTIVE_R7_RESULT_LIFECYCLE_CLAIM.reset(reset)


class R7ResultLifecycleQuerySet(AppendOnlyQuerySet[_ModelT]):
    """Reject every bulk-insert shortcut for exact lifecycle evidence."""

    def bulk_create(
        self,
        objs: Iterable[_ModelT],
        batch_size: int | None = None,
        ignore_conflicts: bool = False,
        update_conflicts: bool = False,
        update_fields: Collection[str] | None = None,
        unique_fields: Collection[str] | None = None,
    ) -> NoReturn:
        raise ValidationError("R7 result lifecycle rows require repository appends.")

    def _update(self, values: object) -> NoReturn:
        """Reject Django's private SQL update entry point."""

        raise ValidationError("R7 result lifecycle evidence cannot be updated.")

    def _raw_delete(self, using: str | None) -> NoReturn:
        """Reject Django's private fast-delete entry point."""

        raise ValidationError("R7 result lifecycle evidence cannot be deleted.")

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
        """Allow only the exact claimed insert used by ``Model.save()``."""

        items = list(objs)
        if (
            not items
            or raw
            or on_conflict is not None
            or update_fields is not None
            or unique_fields is not None
            or (using is not None and using != self.db)
        ):
            raise ValidationError("R7 result lifecycle private insert is forbidden.")
        for item in items:
            _require_r7_result_lifecycle_insert_claim(item)
        insert = cast(
            Callable[..., list[tuple[object, ...]]],
            getattr(super(), "_insert"),  # noqa: B009 - private Django typed boundary
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
        """Reject the private bulk-insert path even when called directly."""

        raise ValidationError("R7 result lifecycle private bulk insert is forbidden.")


class R7ResultLifecycleManager(AppendOnlyManager[_ModelT]):
    """Expose identical append-only guards from every manager path."""

    def get_queryset(self) -> R7ResultLifecycleQuerySet[_ModelT]:
        """Return the lifecycle-specific append-only queryset."""

        return R7ResultLifecycleQuerySet(self.model, using=self._db)

    def bulk_create(
        self,
        objs: Iterable[_ModelT],
        batch_size: int | None = None,
        ignore_conflicts: bool = False,
        update_conflicts: bool = False,
        update_fields: Collection[str] | None = None,
        unique_fields: Collection[str] | None = None,
    ) -> NoReturn:
        raise ValidationError("R7 result lifecycle rows require repository appends.")


class _ClaimedAppendOnlyLifecycleModel(models.Model):
    """Shared claim enforcement for both immutable lifecycle tables."""

    objects = R7ResultLifecycleManager()

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
        """Permit only a repository-claimed first insert."""

        if force_update or update_fields is not None or self.pk is not None:
            raise ValidationError("R7 result lifecycle evidence is append-only.")
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
        """Reject fixture/raw and update paths that could bypass the claim."""

        if raw or force_update or update_fields is not None or self.pk is not None:
            raise ValidationError("R7 result lifecycle evidence is append-only.")
        self._require_claim()
        super().save_base(
            raw=False,
            force_insert=force_insert,
            force_update=False,
            using=using,
            update_fields=None,
        )

    def _require_claim(self) -> None:
        _require_r7_result_lifecycle_insert_claim(self)

    def delete(
        self,
        using: object | None = None,
        keep_parents: bool = False,
    ) -> tuple[int, dict[str, int]]:
        """Reject deletion of immutable lifecycle evidence."""

        raise ValidationError("R7 result lifecycle evidence cannot be deleted.")


class R7ResultLifecycleAuthorizationModel(_ClaimedAppendOnlyLifecycleModel):
    """Exact Research-owner authorization persisted with redundant anchors."""

    result = models.ForeignKey(
        R7ResearchResultModel,
        on_delete=models.PROTECT,
        related_name="lifecycle_authorizations",
    )
    result_key = models.CharField(max_length=192)
    result_version = models.CharField(max_length=192)
    result_content_hash = models.CharField(max_length=64)
    authorization_id = models.CharField(max_length=192)
    authorization_version = models.CharField(max_length=192)
    event_id = models.CharField(max_length=192)
    event_version = models.CharField(max_length=192)
    action = models.CharField(max_length=16)
    expected_sequence = models.PositiveIntegerField()
    owner = models.CharField(max_length=96)
    issued_at = models.DateTimeField()
    recorded_at = models.DateTimeField(db_index=True)
    valid_until = models.DateTimeField()
    reason_codes = models.JSONField()
    evidence_ref = models.CharField(max_length=300)
    canonical_payload = models.JSONField()
    research_only = models.BooleanField(default=True)
    promotes_internal_research_record_only = models.BooleanField(default=True)
    publishes_model_probability = models.BooleanField(default=False)
    produces_decision = models.BooleanField(default=False)
    executes_orders = models.BooleanField(default=False)
    must_not_use_for_decision = models.BooleanField(default=True)
    must_not_execute = models.BooleanField(default=True)
    content_hash = models.CharField(max_length=64, unique=True)
    persisted_at = models.DateTimeField(auto_now_add=True)

    class Meta(_ClaimedAppendOnlyLifecycleModel.Meta):
        db_table = "research_r7_result_lifecycle_authorization"
        indexes = [
            models.Index(
                fields=["result_key", "result_version", "recorded_at"],
                name="res_r7_lc_auth_pit_ix",
            )
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["authorization_id", "authorization_version"],
                name="res_r7_lc_auth_ident_uq",
            ),
            models.UniqueConstraint(
                fields=["event_id", "event_version"],
                name="res_r7_lc_auth_event_uq",
            ),
            models.CheckConstraint(
                condition=models.Q(issued_at__lte=models.F("recorded_at"))
                & models.Q(recorded_at__lt=models.F("valid_until")),
                name="res_r7_lc_auth_clock_ck",
            ),
            models.CheckConstraint(
                condition=models.Q(
                    owner="research",
                    research_only=True,
                    promotes_internal_research_record_only=True,
                    publishes_model_probability=False,
                    produces_decision=False,
                    executes_orders=False,
                    must_not_use_for_decision=True,
                    must_not_execute=True,
                ),
                name="res_r7_lc_auth_safe_ck",
            ),
        ]


class R7ResultLifecycleEventModel(_ClaimedAppendOnlyLifecycleModel):
    """Immutable result-local event bound one-to-one to its authorization."""

    result = models.ForeignKey(
        R7ResearchResultModel,
        on_delete=models.PROTECT,
        related_name="lifecycle_events",
    )
    authorization_record = models.OneToOneField(
        R7ResultLifecycleAuthorizationModel,
        on_delete=models.PROTECT,
        related_name="lifecycle_event",
    )
    result_key = models.CharField(max_length=192)
    result_version = models.CharField(max_length=192)
    result_content_hash = models.CharField(max_length=64)
    event_id = models.CharField(max_length=192)
    event_version = models.CharField(max_length=192)
    authorization_id = models.CharField(max_length=192)
    authorization_version = models.CharField(max_length=192)
    authorization_hash = models.CharField(max_length=64)
    action = models.CharField(max_length=16)
    sequence = models.PositiveIntegerField()
    occurred_at = models.DateTimeField()
    recorded_at = models.DateTimeField(db_index=True)
    previous_event_hash = models.CharField(max_length=64, null=True)
    reason_codes = models.JSONField()
    canonical_payload = models.JSONField()
    research_only = models.BooleanField(default=True)
    promotes_internal_research_record_only = models.BooleanField(default=True)
    publishes_model_probability = models.BooleanField(default=False)
    produces_decision = models.BooleanField(default=False)
    executes_orders = models.BooleanField(default=False)
    must_not_use_for_decision = models.BooleanField(default=True)
    must_not_execute = models.BooleanField(default=True)
    content_hash = models.CharField(max_length=64, unique=True)
    persisted_at = models.DateTimeField(auto_now_add=True)

    class Meta(_ClaimedAppendOnlyLifecycleModel.Meta):
        db_table = "research_r7_result_lifecycle_event"
        indexes = [
            models.Index(
                fields=["result_key", "result_version", "recorded_at"],
                name="res_r7_lc_event_pit_ix",
            )
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["event_id", "event_version"],
                name="res_r7_lc_event_ident_uq",
            ),
            models.UniqueConstraint(
                fields=["result", "sequence"],
                name="res_r7_lc_event_seq_uq",
            ),
            models.CheckConstraint(
                condition=models.Q(occurred_at__lte=models.F("recorded_at")),
                name="res_r7_lc_event_clock_ck",
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(sequence=1, previous_event_hash__isnull=True)
                    | models.Q(sequence__gt=1, previous_event_hash__isnull=False)
                ),
                name="res_r7_lc_event_chain_ck",
            ),
            models.CheckConstraint(
                condition=models.Q(
                    research_only=True,
                    promotes_internal_research_record_only=True,
                    publishes_model_probability=False,
                    produces_decision=False,
                    executes_orders=False,
                    must_not_use_for_decision=True,
                    must_not_execute=True,
                ),
                name="res_r7_lc_event_safe_ck",
            ),
        ]


class R7ResearchResultAuditSnapshotModel(_ClaimedAppendOnlyLifecycleModel):
    """Immutable materialized result/lifecycle graph for stable audit paging."""

    snapshot_id = models.CharField(max_length=192)
    snapshot_version = models.CharField(max_length=192)
    as_of = models.DateTimeField(db_index=True)
    created_at = models.DateTimeField(db_index=True)
    entry_count = models.PositiveIntegerField()
    canonical_payload = models.JSONField()
    internal_audit_only = models.BooleanField(default=True)
    research_only = models.BooleanField(default=True)
    must_not_use_for_decision = models.BooleanField(default=True)
    must_not_execute = models.BooleanField(default=True)
    content_hash = models.CharField(max_length=64, unique=True)
    persisted_at = models.DateTimeField(auto_now_add=True)

    class Meta(_ClaimedAppendOnlyLifecycleModel.Meta):
        db_table = "research_r7_result_audit_snapshot"
        indexes = [
            models.Index(
                fields=["as_of", "created_at"],
                name="res_r7_audit_snap_pit_ix",
            )
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["snapshot_id", "snapshot_version"],
                name="res_r7_audit_snap_ident_uq",
            ),
            models.CheckConstraint(
                condition=models.Q(as_of__lte=models.F("created_at")),
                name="res_r7_audit_snap_clock_ck",
            ),
            models.CheckConstraint(
                condition=models.Q(
                    internal_audit_only=True,
                    research_only=True,
                    must_not_use_for_decision=True,
                    must_not_execute=True,
                ),
                name="res_r7_audit_snap_safe_ck",
            ),
        ]


def _require_r7_result_lifecycle_insert_claim(model: models.Model) -> None:
    claim = _ACTIVE_R7_RESULT_LIFECYCLE_CLAIM.get()
    if (
        claim is None
        or claim.token is not _ACTIVE_R7_RESULT_LIFECYCLE_UOW.get()
        or any(
            getattr(model, field_name) != expected for field_name, expected in claim.expected_values
        )
    ):
        raise ValidationError("R7 result lifecycle requires an exact insert claim.")


@receiver(pre_delete, sender=R7ResultLifecycleAuthorizationModel, weak=False)
@receiver(pre_delete, sender=R7ResultLifecycleEventModel, weak=False)
@receiver(pre_delete, sender=R7ResearchResultAuditSnapshotModel, weak=False)
def _reject_r7_result_lifecycle_collector_delete(
    *,
    sender: type[models.Model],
    instance: models.Model,
    using: str,
    origin: object | None,
    **kwargs: object,
) -> NoReturn:
    """Reject Django Collector and cascade deletion paths."""

    raise ValidationError("R7 result lifecycle evidence cannot be deleted.")


__all__ = [
    "R7ResearchResultAuditSnapshotModel",
    "R7ResultLifecycleAuthorizationModel",
    "R7ResultLifecycleEventModel",
]
