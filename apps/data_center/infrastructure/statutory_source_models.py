"""Append-only storage for unqualified statutory revisions and capture manifests."""

from __future__ import annotations

from collections.abc import Callable, Collection, Iterable, Iterator, Mapping
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from typing import NoReturn, Self, TypeVar, cast

from django.core.exceptions import ValidationError
from django.db import connections, models
from django.db.models.base import ModelBase

from apps.data_center.domain.statutory_source_documents import StatutorySourceDatePrecision
from shared.infrastructure.django_append_only import AppendOnlyManager, AppendOnlyQuerySet

_MODEL_T = TypeVar("_MODEL_T", bound=models.Model)
_ACTIVE_UOW: ContextVar[object | None] = ContextVar(
    "data_center_statutory_source_uow", default=None
)


@dataclass(frozen=True, slots=True)
class _InsertClaim:
    """Private capability for one exact repository-controlled source-fact insert."""

    token: object
    using: str
    model_type: type[models.Model]
    expected_values: tuple[tuple[str, object], ...]


_ACTIVE_CLAIM: ContextVar[_InsertClaim | None] = ContextVar(
    "data_center_statutory_source_insert_claim", default=None
)


@contextmanager
def _activate_statutory_source_uow() -> Iterator[object]:
    """Activate one non-nestable append capability for a source metadata insert."""

    if _ACTIVE_UOW.get() is not None:
        raise ValidationError("Statutory source UOWs may not be nested.")
    token = object()
    reset = _ACTIVE_UOW.set(token)
    try:
        yield token
    finally:
        _ACTIVE_UOW.reset(reset)


@contextmanager
def _claim_statutory_source_insert(
    *,
    token: object,
    using: str,
    model_type: type[models.Model],
    expected_values: Mapping[str, object],
) -> Iterator[None]:
    """Claim one exact new source row inside the active repository UOW."""

    if _ACTIVE_UOW.get() is not token:
        raise ValidationError("Statutory source insert requires its private UOW.")
    if not connections[using].in_atomic_block:
        raise ValidationError("Statutory source insert requires its database transaction.")
    if _ACTIVE_CLAIM.get() is not None:
        raise ValidationError("Statutory source insert claims may not be nested.")
    claim = _InsertClaim(
        token=token,
        using=using,
        model_type=model_type,
        expected_values=tuple(sorted(expected_values.items())),
    )
    reset = _ACTIVE_CLAIM.set(claim)
    try:
        yield
    finally:
        _ACTIVE_CLAIM.reset(reset)


def _require_insert_claim(model: models.Model, *, using: str | None = None) -> None:
    """Require the exact values claimed by the active repository transaction."""

    claim = _ACTIVE_CLAIM.get()
    actual_values = tuple(
        sorted(
            (field.attname, getattr(model, field.attname))
            for field in model._meta.concrete_fields
            if field is not model._meta.auto_field
        )
    )
    if (
        claim is None
        or claim.token is not _ACTIVE_UOW.get()
        or (using is not None and using != claim.using)
        or not connections[claim.using].in_atomic_block
        or claim.model_type is not type(model)
        or claim.expected_values != actual_values
    ):
        raise ValidationError("Statutory source insert requires an exact append claim.")


class _StatutorySourceQuerySet(AppendOnlyQuerySet[_MODEL_T]):
    """Reject mutations, deletion, and insert shortcuts around the source repository."""

    def bulk_create(
        self,
        objs: Iterable[_MODEL_T],
        batch_size: int | None = None,
        ignore_conflicts: bool = False,
        update_conflicts: bool = False,
        update_fields: Collection[str] | None = None,
        unique_fields: Collection[str] | None = None,
    ) -> NoReturn:
        """Require every source insert to pass native identity checks."""

        del objs, batch_size, ignore_conflicts, update_conflicts, update_fields, unique_fields
        raise ValidationError("Statutory sources require repository persistence.")

    def _update(self, values: object) -> NoReturn:
        """Block Django's internal bulk update path."""

        del values
        raise ValidationError("Statutory sources are append-only.")

    def _raw_delete(self, using: str | None) -> NoReturn:
        """Block direct SQL deletion through Django's raw queryset path."""

        del using
        raise ValidationError("Statutory sources are append-only.")

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
        """Allow only one exact model.save insert claimed by the repository."""

        items = list(objs)
        if (
            len(items) != 1
            or raw
            or on_conflict is not None
            or update_fields is not None
            or unique_fields is not None
            or (using is not None and using != self.db)
        ):
            raise ValidationError("Statutory source private insert is forbidden.")
        for item in items:
            _require_insert_claim(item, using=self.db)
        insert = cast(
            Callable[..., list[tuple[object, ...]]],
            getattr(super(), "_insert"),  # noqa: B009 -- typed Django private boundary
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
        objs: list[_MODEL_T],
        fields: list[object],
        batch_size: int | None,
        on_conflict: object | None = None,
        update_fields: Iterable[object] | None = None,
        unique_fields: Iterable[object] | None = None,
    ) -> NoReturn:
        """Block Django's batch insert path, including one-row shortcuts."""

        del objs, fields, batch_size, on_conflict, update_fields, unique_fields
        raise ValidationError("Statutory source bulk insertion is forbidden.")


class _StatutorySourceManager(AppendOnlyManager[_MODEL_T]):
    """Expose guarded reads and reject manager-level write shortcuts."""

    def get_queryset(self) -> _StatutorySourceQuerySet[_MODEL_T]:
        """Return an immutable queryset bound to this manager's database."""

        return _StatutorySourceQuerySet(self.model, using=self._db)

    def bulk_create(
        self,
        objs: Iterable[_MODEL_T],
        batch_size: int | None = None,
        ignore_conflicts: bool = False,
        update_conflicts: bool = False,
        update_fields: Collection[str] | None = None,
        unique_fields: Collection[str] | None = None,
    ) -> NoReturn:
        """Reject manager-level insertion around the repository boundary."""

        del objs, batch_size, ignore_conflicts, update_conflicts, update_fields, unique_fields
        raise ValidationError("Statutory sources require repository persistence.")

    def bulk_update(
        self,
        objs: Iterable[_MODEL_T],
        fields: Iterable[str],
        batch_size: int | None = None,
    ) -> NoReturn:
        """Reject manager-level evidence mutation."""

        del objs, fields, batch_size
        raise ValidationError("Statutory sources are append-only.")


class _StatutorySourceImmutableModel(models.Model):
    """Require an exact repository insert claim and reject all row mutation."""

    recorded_at = models.DateTimeField()

    class Meta:
        abstract = True

    def save(
        self,
        force_insert: bool | tuple[ModelBase, ...] = False,
        force_update: bool = False,
        using: str | None = None,
        update_fields: Iterable[str] | None = None,
    ) -> None:
        """Allow only an exact new row inside its repository database transaction."""
        del force_insert
        if force_update or update_fields is not None or not self._state.adding:
            raise ValidationError("Statutory source facts are append-only.")
        _require_insert_claim(self, using=using)
        super().save(force_insert=True, using=using)

    def save_base(
        self,
        raw: bool = False,
        force_insert: bool | tuple[ModelBase, ...] = False,
        force_update: bool = False,
        using: str | None = None,
        update_fields: Iterable[str] | None = None,
    ) -> None:
        """Reject raw fixture insertion and lower-level persistence shortcuts."""
        del force_insert
        if raw or force_update or update_fields is not None or not self._state.adding:
            raise ValidationError("Statutory source facts require repository persistence.")
        _require_insert_claim(self, using=using)
        super().save_base(
            raw=False, force_insert=True, force_update=False, using=using, update_fields=None
        )

    def delete(self, using: object | None = None, keep_parents: bool = False) -> NoReturn:
        """Retain every stored revision, capture and bundle member."""
        del using, keep_parents
        raise ValidationError("Statutory source facts are append-only.")


def _date_shape(prefix: str) -> models.Q:
    """Bind declared DATE/INSTANT/UNKNOWN precision to exactly matching columns."""
    return (
        models.Q(
            **{
                f"{prefix}_precision": StatutorySourceDatePrecision.UNKNOWN.value,
                f"{prefix}_date__isnull": True,
                f"{prefix}_instant__isnull": True,
            }
        )
        | models.Q(
            **{
                f"{prefix}_precision": StatutorySourceDatePrecision.DATE.value,
                f"{prefix}_date__isnull": False,
                f"{prefix}_instant__isnull": True,
            }
        )
        | models.Q(
            **{
                f"{prefix}_precision": StatutorySourceDatePrecision.INSTANT.value,
                f"{prefix}_date__isnull": True,
                f"{prefix}_instant__isnull": False,
            }
        )
    )


class StatutorySourceDocumentRevisionModel(_StatutorySourceImmutableModel):
    """One immutable publisher-native revision; this is not source qualification."""

    issuer = models.CharField(max_length=240)
    document_id = models.CharField(max_length=240)
    source_version = models.CharField(max_length=120)
    canonical_url = models.URLField(max_length=4096)
    title = models.CharField(max_length=1000)
    legal_number = models.CharField(max_length=240)
    publication_precision = models.CharField(max_length=8)
    publication_date = models.DateField(null=True)
    publication_instant = models.DateTimeField(null=True)
    effective_precision = models.CharField(max_length=8)
    effective_date = models.DateField(null=True)
    effective_instant = models.DateTimeField(null=True)
    body_sha256 = models.CharField(max_length=64)
    body_size_bytes = models.PositiveBigIntegerField()
    source_revision_sha256 = models.CharField(max_length=64)
    objects: _StatutorySourceManager[Self] = _StatutorySourceManager()

    class Meta:
        db_table = "dc_statutory_source_revision"
        base_manager_name = "objects"
        default_manager_name = "objects"
        constraints = [
            models.UniqueConstraint(
                fields=("issuer", "document_id", "source_version"), name="dc_stat_src_native_uniq"
            ),
            models.CheckConstraint(
                condition=_date_shape("publication"), name="dc_stat_src_pub_clock_ck"
            ),
            models.CheckConstraint(
                condition=_date_shape("effective"), name="dc_stat_src_eff_clock_ck"
            ),
            models.CheckConstraint(
                condition=models.Q(body_size_bytes__gt=0), name="dc_stat_src_body_size_ck"
            ),
            models.CheckConstraint(
                condition=models.Q(
                    body_sha256__regex=r"^[0-9a-f]{64}$",
                    source_revision_sha256__regex=r"^[0-9a-f]{64}$",
                ),
                name="dc_stat_src_hashes_ck",
            ),
        ]


class StatutorySourceDocumentCaptureModel(_StatutorySourceImmutableModel):
    """One server capture of an exact retained revision and body location."""

    capture_id = models.UUIDField(primary_key=True, editable=False)
    revision = models.ForeignKey(
        StatutorySourceDocumentRevisionModel, on_delete=models.PROTECT, related_name="captures"
    )
    captured_at = models.DateTimeField()
    content_type = models.CharField(max_length=200)
    body_reference = models.CharField(max_length=1024)
    objects: _StatutorySourceManager[Self] = _StatutorySourceManager()

    class Meta:
        db_table = "dc_statutory_source_capture"
        base_manager_name = "objects"
        default_manager_name = "objects"
        constraints = [
            models.CheckConstraint(
                condition=models.Q(recorded_at__gte=models.F("captured_at")),
                name="dc_stat_cap_record_clock_ck",
            ),
        ]


class StatutorySourceDocumentBundleModel(_StatutorySourceImmutableModel):
    """An immutable selected source set with separately bound capture provenance."""

    bundle_id = models.CharField(max_length=240)
    version = models.CharField(max_length=120)
    source_bundle_sha256 = models.CharField(max_length=64)
    capture_manifest_sha256 = models.CharField(max_length=64)
    objects: _StatutorySourceManager[Self] = _StatutorySourceManager()

    class Meta:
        db_table = "dc_statutory_source_bundle"
        base_manager_name = "objects"
        default_manager_name = "objects"
        constraints = [
            models.UniqueConstraint(
                fields=("bundle_id", "version"), name="dc_stat_bundle_native_uniq"
            ),
            models.CheckConstraint(
                condition=models.Q(
                    source_bundle_sha256__regex=r"^[0-9a-f]{64}$",
                    capture_manifest_sha256__regex=r"^[0-9a-f]{64}$",
                ),
                name="dc_stat_bundle_hashes_ck",
            ),
        ]


class StatutorySourceDocumentBundleMemberModel(_StatutorySourceImmutableModel):
    """A protected ordered reference to one exact retained capture in a source set."""

    bundle = models.ForeignKey(
        StatutorySourceDocumentBundleModel, on_delete=models.PROTECT, related_name="members"
    )
    capture = models.ForeignKey(
        StatutorySourceDocumentCaptureModel, on_delete=models.PROTECT, related_name="bundle_members"
    )
    ordinal = models.PositiveIntegerField()
    objects: _StatutorySourceManager[Self] = _StatutorySourceManager()

    class Meta:
        db_table = "dc_statutory_source_bundle_member"
        base_manager_name = "objects"
        default_manager_name = "objects"
        constraints = [
            models.UniqueConstraint(
                fields=("bundle", "capture"), name="dc_stat_member_capture_uniq"
            ),
            models.UniqueConstraint(fields=("bundle", "ordinal"), name="dc_stat_member_order_uniq"),
        ]


__all__ = [
    "StatutorySourceDocumentRevisionModel",
    "StatutorySourceDocumentCaptureModel",
    "StatutorySourceDocumentBundleModel",
    "StatutorySourceDocumentBundleMemberModel",
]
