"""Append-only ORM rows for candidate-level multi-batch RawAudit manifests."""

from __future__ import annotations

from collections.abc import Callable, Collection, Iterable, Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from typing import NoReturn, TypeVar, cast
from uuid import uuid4

from django.core.exceptions import ValidationError
from django.db import models
from django.db.models.base import ModelBase
from django.db.models.signals import pre_delete, pre_save

from shared.infrastructure.django_append_only import AppendOnlyManager, AppendOnlyQuerySet

_MODEL_T = TypeVar("_MODEL_T", bound=models.Model)
_MANIFEST_INSERT: ContextVar[object | None] = ContextVar(
    "candidate_raw_audit_manifest_insert", default=None
)
_MANIFEST_FIXTURE_RESTORE: ContextVar[object | None] = ContextVar(
    "candidate_raw_audit_manifest_fixture_restore", default=None
)


@contextmanager
def _allow_candidate_manifest_inserts() -> Iterator[None]:
    """Grant the repository one scoped insert capability for both manifest tables."""

    if _MANIFEST_INSERT.get() is not None:
        raise ValidationError("candidate manifest insert scopes may not be nested")
    reset = _MANIFEST_INSERT.set(object())
    try:
        yield
    finally:
        _MANIFEST_INSERT.reset(reset)


@contextmanager
def _allow_candidate_manifest_fixture_restore() -> Iterator[None]:
    """Grant the deployment loaddata runner a process-local restore capability."""

    if _MANIFEST_FIXTURE_RESTORE.get() is not None:
        raise ValidationError("candidate manifest fixture scopes may not be nested")
    reset = _MANIFEST_FIXTURE_RESTORE.set(object())
    try:
        yield
    finally:
        _MANIFEST_FIXTURE_RESTORE.reset(reset)


def _require_candidate_manifest_insert() -> None:
    if _MANIFEST_INSERT.get() is None:
        raise ValidationError("candidate manifest evidence requires repository staging")


class _CandidateManifestQuerySet(AppendOnlyQuerySet[_MODEL_T]):
    """Append-only queryset with repository-only bulk inserts."""

    def bulk_create(
        self,
        objs: Iterable[_MODEL_T],
        batch_size: int | None = None,
        ignore_conflicts: bool = False,
        update_conflicts: bool = False,
        update_fields: Collection[str] | None = None,
        unique_fields: Collection[str] | None = None,
    ) -> list[_MODEL_T]:
        """Allow only conflict-free bulk inserts inside a repository stage."""

        _require_candidate_manifest_insert()
        if (
            ignore_conflicts
            or update_conflicts
            or update_fields is not None
            or unique_fields is not None
        ):
            raise ValidationError("candidate manifest bulk conflicts are forbidden")
        return super().bulk_create(
            objs,
            batch_size=batch_size,
            ignore_conflicts=False,
            update_conflicts=False,
            update_fields=None,
            unique_fields=None,
        )

    def _raw_delete(self, using: str | None) -> NoReturn:
        del using
        raise ValidationError("candidate manifest evidence cannot be deleted")

    def _insert(
        self,
        objs: Iterable[_MODEL_T],
        fields: Iterable[object],
        returning_fields: Iterable[object] | None = None,
        raw: bool = False,
        using: str | None = None,
        on_conflict: object | None = None,
        update_fields: Iterable[object] | None = None,
        unique_fields: Iterable[object] | None = None,
    ) -> list[tuple[object, ...]]:
        """Guard Django's private insert path, including direct queryset callers."""

        items = list(objs)
        if (
            not items
            or on_conflict is not None
            or update_fields is not None
            or unique_fields is not None
            or (using is not None and using != self.db)
        ):
            raise ValidationError("candidate manifest low-level inserts are restricted")
        if raw:
            if _MANIFEST_FIXTURE_RESTORE.get() is None:
                raise ValidationError("raw candidate manifest inserts require fixture restore")
        elif _MANIFEST_INSERT.get() is None:
            raise ValidationError("candidate manifest low-level inserts require repository staging")
        insert = cast(
            Callable[..., list[tuple[object, ...]]],
            getattr(super(), "_insert"),  # noqa: B009 -- typed Django private boundary
        )
        return insert(
            items,
            fields,
            returning_fields=returning_fields,
            raw=raw,
            using=using,
            on_conflict=None,
            update_fields=None,
            unique_fields=None,
        )


class _CandidateManifestManager(AppendOnlyManager[_MODEL_T]):
    """Expose repository-only inserts and immutable reads for both tables."""

    def get_queryset(self) -> _CandidateManifestQuerySet[_MODEL_T]:
        return _CandidateManifestQuerySet(self.model, using=self._db)

    def bulk_create(
        self,
        objs: Iterable[_MODEL_T],
        batch_size: int | None = None,
        ignore_conflicts: bool = False,
        update_conflicts: bool = False,
        update_fields: Collection[str] | None = None,
        unique_fields: Collection[str] | None = None,
    ) -> list[_MODEL_T]:
        """Route inserts through the guarded queryset."""

        _require_candidate_manifest_insert()
        return self.get_queryset().bulk_create(
            objs,
            batch_size=batch_size,
            ignore_conflicts=ignore_conflicts,
            update_conflicts=update_conflicts,
            update_fields=update_fields,
            unique_fields=unique_fields,
        )


class _CandidateManifestAppendOnlyModel(models.Model):
    """Block row rewrites and deletes while allowing repository-owned inserts."""

    objects = _CandidateManifestManager()

    class Meta:
        abstract = True

    def save(
        self,
        *,
        force_insert: bool | tuple[ModelBase, ...] = False,
        force_update: bool = False,
        using: str | None = None,
        update_fields: Iterable[str] | None = None,
    ) -> None:
        """Allow inserts only, under the repository's scoped capability."""

        if not self._state.adding or force_update or update_fields is not None:
            raise ValidationError("candidate manifest evidence is append-only")
        _require_candidate_manifest_insert()
        super().save(force_insert=force_insert, using=using)

    def save_base(
        self,
        raw: bool = False,
        force_insert: bool | tuple[ModelBase, ...] = False,
        force_update: bool = False,
        using: str | None = None,
        update_fields: Iterable[str] | None = None,
    ) -> None:
        """Apply insert-only checks to Django's lower-level persistence path."""

        if (
            not self._state.adding
            or force_update
            or update_fields is not None
            or (raw and _MANIFEST_FIXTURE_RESTORE.get() is None)
        ):
            raise ValidationError("candidate manifest evidence is append-only")
        if raw:
            super().save_base(
                raw=True,
                force_insert=force_insert,
                force_update=False,
                using=using,
                update_fields=None,
            )
            return
        _require_candidate_manifest_insert()
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
        """Reject direct row deletion."""

        del using, keep_parents
        raise ValidationError("candidate manifest evidence cannot be deleted")


class CandidateRawAuditManifestModel(_CandidateManifestAppendOnlyModel):
    """Immutable manifest header bound to one canonical publication candidate."""

    manifest_id = models.UUIDField(primary_key=True, default=uuid4, editable=False)
    manifest_version = models.CharField(max_length=16)
    publication = models.OneToOneField(
        "data_center.CanonicalPublicationModel",
        on_delete=models.PROTECT,
        related_name="candidate_raw_audit_manifest",
    )
    publication_hash = models.CharField(max_length=64)
    run_id = models.UUIDField(db_index=True)
    dataset_key = models.CharField(max_length=160, db_index=True)
    publication_key = models.CharField(max_length=300)
    task_attempt_id = models.CharField(max_length=160, db_index=True)
    raw_audit_count = models.PositiveIntegerField()
    raw_audit_hash = models.CharField(max_length=64)
    manifest_hash = models.CharField(max_length=64, unique=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "data_center_candidate_raw_audit_manifest"
        base_manager_name = "objects"
        default_manager_name = "objects"
        constraints = [
            models.CheckConstraint(
                condition=models.Q(
                    manifest_version="1",
                    raw_audit_count__gte=1,
                ),
                name="dc_raw_manifest_header_ck",
            ),
        ]
        indexes = [
            models.Index(
                fields=["dataset_key", "publication_key"], name="dc_raw_manifest_scope_ix"
            ),
        ]


class CandidateRawAuditManifestMemberModel(_CandidateManifestAppendOnlyModel):
    """One stable ordered RawAudit reference stored under a manifest header."""

    id = models.BigAutoField(primary_key=True)
    manifest = models.ForeignKey(
        CandidateRawAuditManifestModel,
        on_delete=models.PROTECT,
        related_name="members",
    )
    ordinal = models.PositiveIntegerField()
    raw_audit = models.ForeignKey(
        "data_center.RawAuditModel",
        on_delete=models.PROTECT,
        related_name="candidate_manifest_memberships",
    )
    raw_audit_version = models.CharField(max_length=16)
    raw_audit_content_hash = models.CharField(max_length=64)
    provider_name = models.CharField(max_length=50)
    capability = models.CharField(max_length=30)
    run_id = models.UUIDField(db_index=True)
    ingested_run_id = models.UUIDField(db_index=True)

    class Meta:
        db_table = "data_center_candidate_raw_audit_manifest_member"
        base_manager_name = "objects"
        default_manager_name = "objects"
        ordering = ["manifest_id", "ordinal"]
        constraints = [
            models.UniqueConstraint(
                fields=["manifest", "ordinal"],
                name="dc_raw_manifest_member_ord_uq",
            ),
            models.UniqueConstraint(
                fields=["manifest", "raw_audit"],
                name="dc_raw_manifest_member_audit_uq",
            ),
            models.CheckConstraint(
                condition=models.Q(raw_audit_version="1"),
                name="dc_raw_manifest_member_ver_ck",
            ),
        ]
        indexes = [
            models.Index(
                fields=["manifest", "ordinal"],
                name="dc_raw_manifest_member_ord_ix",
            )
        ]


def _reject_candidate_manifest_delete(sender: type[models.Model], **kwargs: object) -> None:
    """Reject collector deletion paths for immutable candidate manifest rows."""

    del sender, kwargs
    raise ValidationError("candidate manifest evidence cannot be deleted")


pre_delete.connect(
    _reject_candidate_manifest_delete,
    sender=CandidateRawAuditManifestModel,
    dispatch_uid="data_center_candidate_raw_audit_manifest_delete_guard",
)


def _require_candidate_manifest_save_capability(
    sender: type[models.Model],
    instance: models.Model,
    raw: bool,
    **kwargs: object,
) -> None:
    """Reject direct base-save and fixture writes outside their scoped capabilities."""

    del sender, kwargs
    if not instance._state.adding:
        raise ValidationError("candidate manifest evidence is append-only")
    if raw and _MANIFEST_FIXTURE_RESTORE.get() is not None:
        return
    if not raw and _MANIFEST_INSERT.get() is not None:
        return
    raise ValidationError("candidate manifest evidence requires a repository or fixture capability")


pre_save.connect(
    _require_candidate_manifest_save_capability,
    sender=CandidateRawAuditManifestModel,
    dispatch_uid="data_center_candidate_raw_audit_manifest_save_guard",
    weak=False,
)
pre_save.connect(
    _require_candidate_manifest_save_capability,
    sender=CandidateRawAuditManifestMemberModel,
    dispatch_uid="data_center_candidate_raw_audit_manifest_member_save_guard",
    weak=False,
)
pre_delete.connect(
    _reject_candidate_manifest_delete,
    sender=CandidateRawAuditManifestMemberModel,
    dispatch_uid="data_center_candidate_raw_audit_manifest_member_delete_guard",
)


__all__ = [
    "CandidateRawAuditManifestMemberModel",
    "CandidateRawAuditManifestModel",
]
