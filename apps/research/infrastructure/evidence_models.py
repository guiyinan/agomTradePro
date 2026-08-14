"""Strict append-only ORM ledgers for canonical Research evidence."""

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
_ACTIVE_EVIDENCE_UOW: ContextVar[object | None] = ContextVar(
    "active_research_evidence_uow", default=None
)


@dataclass(frozen=True)
class _EvidenceInsertClaim:
    token: object
    model_type: type[models.Model]
    expected_values: tuple[tuple[str, object], ...]


_ACTIVE_EVIDENCE_CLAIM: ContextVar[_EvidenceInsertClaim | None] = ContextVar(
    "active_research_evidence_claim", default=None
)


@contextmanager
def _activate_evidence_uow(token: object) -> Iterator[None]:
    reset = _ACTIVE_EVIDENCE_UOW.set(token)
    try:
        yield
    finally:
        _ACTIVE_EVIDENCE_UOW.reset(reset)


@contextmanager
def _claim_evidence_insert(
    *, token: object, model_type: type[models.Model], expected_values: Mapping[str, object]
) -> Iterator[None]:
    if _ACTIVE_EVIDENCE_UOW.get() is not token:
        raise ValidationError("Research evidence insert requires its private unit of work.")
    reset = _ACTIVE_EVIDENCE_CLAIM.set(
        _EvidenceInsertClaim(
            token=token,
            model_type=model_type,
            expected_values=tuple(sorted(expected_values.items())),
        )
    )
    try:
        yield
    finally:
        _ACTIVE_EVIDENCE_CLAIM.reset(reset)


class EvidenceAppendOnlyQuerySet(AppendOnlyQuerySet[_ModelT]):
    """Reject every bulk, conflict-update, private update, and raw-delete shortcut."""

    def bulk_create(
        self,
        objs: Iterable[_ModelT],
        batch_size: int | None = None,
        ignore_conflicts: bool = False,
        update_conflicts: bool = False,
        update_fields: Collection[str] | None = None,
        unique_fields: Collection[str] | None = None,
    ) -> NoReturn:
        raise ValidationError("Research evidence requires exact repository appends.")

    def _update(self, values: list[tuple[object, object, object]]) -> NoReturn:
        raise ValidationError("Research evidence cannot be updated.")

    def _raw_delete(self, using: str) -> NoReturn:
        raise ValidationError("Research evidence cannot be deleted.")


class EvidenceAppendOnlyManager(AppendOnlyManager[_ModelT]):
    """Expose the strongest evidence guards through every manager path."""

    def get_queryset(self) -> EvidenceAppendOnlyQuerySet[_ModelT]:
        return EvidenceAppendOnlyQuerySet(self.model, using=self._db)

    def bulk_create(
        self,
        objs: Iterable[_ModelT],
        batch_size: int | None = None,
        ignore_conflicts: bool = False,
        update_conflicts: bool = False,
        update_fields: Collection[str] | None = None,
        unique_fields: Collection[str] | None = None,
    ) -> NoReturn:
        raise ValidationError("Research evidence requires exact repository appends.")


class EvidenceAppendOnlyModel(models.Model):
    """Permit only one exact insert claimed by the private repository token."""

    objects: EvidenceAppendOnlyManager[models.Model] = EvidenceAppendOnlyManager()

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
            raise ValidationError("Research evidence is append-only.")
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
            raise ValidationError("Research evidence is append-only.")
        self._require_claim()
        super().save_base(force_insert=force_insert, using=using)

    def _require_claim(self) -> None:
        claim = _ACTIVE_EVIDENCE_CLAIM.get()
        if (
            claim is None
            or claim.token is not _ACTIVE_EVIDENCE_UOW.get()
            or claim.model_type is not type(self)
            or any(getattr(self, name) != expected for name, expected in claim.expected_values)
        ):
            raise ValidationError("Research evidence requires an exact insert claim.")

    def delete(
        self, using: object | None = None, keep_parents: bool = False
    ) -> tuple[int, dict[str, int]]:
        raise ValidationError("Research evidence cannot be deleted.")


class EvidenceOperatorSpecModel(EvidenceAppendOnlyModel):
    """One immutable canonical operator specification version."""

    operator_id = models.CharField(max_length=192)
    operator_version = models.CharField(max_length=192)
    research_family = models.CharField(max_length=192, db_index=True)
    output_artifact_type = models.CharField(max_length=192)
    claim_kind = models.CharField(max_length=32)
    method_kind = models.CharField(max_length=32)
    activated_at = models.DateTimeField(db_index=True)
    valid_until = models.DateTimeField(db_index=True)
    recorded_at = models.DateTimeField(db_index=True)
    canonical_payload = models.JSONField()
    content_hash = models.CharField(max_length=64, unique=True)
    ledger_header_hash = models.CharField(max_length=64, unique=True)
    persisted_at = models.DateTimeField(auto_now_add=True)

    class Meta(EvidenceAppendOnlyModel.Meta):
        db_table = "research_evidence_operator_spec"
        indexes = [
            models.Index(fields=("research_family", "recorded_at"), name="res_ev_op_family_pit_ix")
        ]
        constraints = [
            models.UniqueConstraint(
                fields=("operator_id", "operator_version"), name="res_ev_op_identity_uq"
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(activated_at__lte=models.F("recorded_at"))
                    & models.Q(recorded_at__lt=models.F("valid_until"))
                ),
                name="res_ev_op_clock_ck",
            ),
        ]


class EvidenceTrackRecordModel(EvidenceAppendOnlyModel):
    """One immutable version-specific Track Record snapshot."""

    snapshot_id = models.CharField(max_length=192)
    snapshot_version = models.CharField(max_length=192)
    artifact_owner = models.CharField(max_length=192)
    artifact_type = models.CharField(max_length=192)
    artifact_id = models.CharField(max_length=192)
    artifact_version = models.CharField(max_length=192)
    artifact_hash = models.CharField(max_length=64, db_index=True)
    target = models.CharField(max_length=192)
    horizon = models.CharField(max_length=192)
    sample_policy_id = models.CharField(max_length=192)
    sample_policy_version = models.CharField(max_length=192)
    evaluated_at = models.DateTimeField(db_index=True)
    valid_until = models.DateTimeField(db_index=True)
    recorded_at = models.DateTimeField(db_index=True)
    canonical_payload = models.JSONField()
    content_hash = models.CharField(max_length=64, unique=True)
    ledger_header_hash = models.CharField(max_length=64, unique=True)
    persisted_at = models.DateTimeField(auto_now_add=True)

    class Meta(EvidenceAppendOnlyModel.Meta):
        db_table = "research_evidence_track_record"
        indexes = [
            models.Index(
                fields=("artifact_id", "artifact_version", "recorded_at"),
                name="res_ev_track_art_pit_ix",
            )
        ]
        constraints = [
            models.UniqueConstraint(
                fields=("snapshot_id", "snapshot_version"),
                name="res_ev_track_identity_uq",
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(evaluated_at__lte=models.F("recorded_at"))
                    & models.Q(recorded_at__lt=models.F("valid_until"))
                ),
                name="res_ev_track_clock_ck",
            ),
        ]


class EvidenceEnvelopeModel(EvidenceAppendOnlyModel):
    """One immutable Evidence Envelope winner for an exact output version."""

    output_owner = models.CharField(max_length=192)
    output_artifact_type = models.CharField(max_length=192)
    output_artifact_id = models.CharField(max_length=192)
    output_artifact_version = models.CharField(max_length=192)
    output_artifact_hash = models.CharField(max_length=64, db_index=True)
    operator_spec_id = models.CharField(max_length=192)
    operator_spec_version = models.CharField(max_length=192)
    operator_spec_hash = models.CharField(max_length=64)
    claim_kind = models.CharField(max_length=32)
    method_kind = models.CharField(max_length=32)
    research_family = models.CharField(max_length=192, db_index=True)
    governance_state = models.CharField(max_length=32)
    permission = models.CharField(max_length=32)
    evaluated_at = models.DateTimeField(db_index=True)
    valid_until = models.DateTimeField(db_index=True)
    recorded_at = models.DateTimeField(db_index=True)
    canonical_payload = models.JSONField()
    content_hash = models.CharField(max_length=64, unique=True)
    ledger_header_hash = models.CharField(max_length=64, unique=True)
    must_not_use_for_decision = models.BooleanField()
    must_not_execute = models.BooleanField()
    persisted_at = models.DateTimeField(auto_now_add=True)

    class Meta(EvidenceAppendOnlyModel.Meta):
        db_table = "research_evidence_envelope"
        indexes = [
            models.Index(
                fields=("output_artifact_id", "output_artifact_version", "recorded_at"),
                name="res_ev_env_output_pit_ix",
            )
        ]
        constraints = [
            models.UniqueConstraint(
                fields=(
                    "output_owner",
                    "output_artifact_type",
                    "output_artifact_id",
                    "output_artifact_version",
                ),
                name="res_ev_env_identity_uq",
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(evaluated_at__lte=models.F("recorded_at"))
                    & models.Q(recorded_at__lt=models.F("valid_until"))
                ),
                name="res_ev_env_clock_ck",
            ),
        ]


def _reject_evidence_pre_delete(
    sender: type[models.Model],
    instance: models.Model,
    using: str,
    origin: object,
    **kwargs: object,
) -> None:
    del sender, instance, using, origin, kwargs
    raise ValidationError("Research evidence cannot be deleted.")


for _model in (EvidenceOperatorSpecModel, EvidenceTrackRecordModel, EvidenceEnvelopeModel):
    pre_delete.connect(
        _reject_evidence_pre_delete,
        sender=_model,
        dispatch_uid=f"reject_{_model._meta.db_table}_delete",
        weak=False,
    )


__all__ = [
    "EvidenceEnvelopeModel",
    "EvidenceOperatorSpecModel",
    "EvidenceTrackRecordModel",
]
