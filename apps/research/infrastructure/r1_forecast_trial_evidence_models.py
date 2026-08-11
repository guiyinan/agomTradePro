"""Append-only ORM ledger for Research R1 trial preregistration evidence."""

from __future__ import annotations

from collections.abc import Collection, Iterable, Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from typing import NoReturn

from django.core.exceptions import ValidationError
from django.db import models
from django.db.models.base import ModelBase
from django.db.models.signals import pre_delete
from django.dispatch import receiver

from shared.infrastructure.django_append_only import (
    AppendOnlyManager,
    AppendOnlyQuerySet,
)

_ACTIVE_INSERT_TOKEN: ContextVar[object | None] = ContextVar(
    "active_r1_forecast_trial_evidence_insert", default=None
)


@contextmanager
def _claim_r1_forecast_trial_evidence_insert(token: object) -> Iterator[None]:
    """Privately authorize one repository-controlled insert scope."""

    reset_token = _ACTIVE_INSERT_TOKEN.set(token)
    try:
        yield
    finally:
        _ACTIVE_INSERT_TOKEN.reset(reset_token)


def _require_insert_claim() -> None:
    if _ACTIVE_INSERT_TOKEN.get() is None:
        raise ValidationError("R1 trial evidence insert capability is private.")


class _R1TrialEvidenceQuerySet(AppendOnlyQuerySet["R1ForecastTrialEvidenceLedgerModel"]):
    def bulk_create(
        self,
        objs: Iterable[R1ForecastTrialEvidenceLedgerModel],
        batch_size: int | None = None,
        ignore_conflicts: bool = False,
        update_conflicts: bool = False,
        update_fields: Collection[str] | None = None,
        unique_fields: Collection[str] | None = None,
    ) -> list[R1ForecastTrialEvidenceLedgerModel]:
        """Reject public bulk inserts while retaining a private claimed path."""

        _require_insert_claim()
        return super().bulk_create(
            objs,
            batch_size=batch_size,
            ignore_conflicts=ignore_conflicts,
            update_conflicts=update_conflicts,
            update_fields=update_fields,
            unique_fields=unique_fields,
        )


class _R1TrialEvidenceManager(AppendOnlyManager["R1ForecastTrialEvidenceLedgerModel"]):
    def get_queryset(self) -> _R1TrialEvidenceQuerySet:
        """Expose insert/update/delete guards through every manager path."""

        return _R1TrialEvidenceQuerySet(self.model, using=self._db)


class R1ForecastTrialEvidenceLedgerModel(models.Model):
    """One immutable Research-owned preregistration receipt."""

    evidence_id = models.CharField(max_length=192)
    evidence_version = models.CharField(max_length=192)
    definition_id = models.CharField(max_length=192)
    definition_version = models.CharField(max_length=192)
    definition_content_hash = models.CharField(max_length=64)
    baseline_spec_id = models.CharField(max_length=192)
    baseline_spec_version = models.CharField(max_length=192)
    baseline_spec_content_hash = models.CharField(max_length=64)
    baseline_artifact_id = models.CharField(max_length=192)
    baseline_artifact_version = models.CharField(max_length=192)
    baseline_artifact_content_hash = models.CharField(max_length=64)
    baseline_spec_approved_at = models.DateTimeField()
    activated_at = models.DateTimeField()
    recorded_at = models.DateTimeField(db_index=True)
    forecast_origin_at = models.DateTimeField()
    valid_until = models.DateTimeField()
    canonical_payload = models.JSONField()
    content_hash = models.CharField(max_length=64, unique=True)
    research_only = models.BooleanField(default=True)
    must_not_use_for_decision = models.BooleanField(default=True)
    must_not_execute = models.BooleanField(default=True)
    persisted_at = models.DateTimeField(auto_now_add=True)

    objects = _R1TrialEvidenceManager()
    all_objects = _R1TrialEvidenceManager()

    class Meta:
        db_table = "research_r1_forecast_trial_evidence"
        base_manager_name = "all_objects"
        default_manager_name = "objects"
        constraints = [
            models.UniqueConstraint(
                fields=("evidence_id", "evidence_version"),
                name="res_r1_trial_ev_ident_uq",
            ),
            models.UniqueConstraint(
                fields=("definition_id", "definition_version"),
                name="res_r1_trial_def_ident_uq",
            ),
            models.CheckConstraint(
                condition=models.Q(
                    baseline_spec_approved_at__lte=models.F("activated_at"),
                    activated_at__lte=models.F("recorded_at"),
                    recorded_at__lte=models.F("forecast_origin_at"),
                    forecast_origin_at__lt=models.F("valid_until"),
                ),
                name="res_r1_trial_ev_clock_ck",
            ),
            models.CheckConstraint(
                condition=models.Q(
                    research_only=True,
                    must_not_use_for_decision=True,
                    must_not_execute=True,
                ),
                name="res_r1_trial_ev_safe_ck",
            ),
        ]
        indexes = [
            models.Index(
                fields=("evidence_id", "evidence_version", "recorded_at"),
                name="res_r1_trial_ev_pit_ix",
            )
        ]

    def save(
        self,
        *,
        force_insert: bool | tuple[ModelBase, ...] = False,
        force_update: bool = False,
        using: str | None = None,
        update_fields: Iterable[str] | None = None,
    ) -> None:
        """Allow inserts while rejecting every update-shaped save."""

        _require_insert_claim()
        if self.pk is not None or force_update or update_fields is not None:
            raise ValidationError("R1 trial evidence is append-only.")
        super().save(
            force_insert=force_insert,
            force_update=force_update,
            using=using,
            update_fields=update_fields,
        )

    def save_base(
        self,
        raw: bool = False,
        force_insert: bool | tuple[ModelBase, ...] = False,
        force_update: bool = False,
        using: str | None = None,
        update_fields: Iterable[str] | None = None,
    ) -> None:
        """Reject public and update-shaped save_base bypasses."""

        _require_insert_claim()
        if self.pk is not None or force_update or update_fields is not None:
            raise ValidationError("R1 trial evidence is append-only.")
        super().save_base(
            raw=raw,
            force_insert=force_insert,
            force_update=force_update,
            using=using,
            update_fields=update_fields,
        )

    def delete(
        self,
        using: str | None = None,
        keep_parents: bool = False,
    ) -> NoReturn:
        """Reject instance deletion."""

        raise ValidationError("R1 trial evidence cannot be deleted.")


@receiver(pre_delete, sender=R1ForecastTrialEvidenceLedgerModel, weak=False)
def _reject_r1_forecast_trial_evidence_delete(
    *,
    sender: type[models.Model],
    instance: models.Model,
    using: str,
    origin: object | None,
    **kwargs: object,
) -> NoReturn:
    """Reject Collector, cascade, and direct deletion paths."""

    raise ValidationError("R1 trial evidence cannot be deleted by Collector.")


__all__ = ["R1ForecastTrialEvidenceLedgerModel"]
