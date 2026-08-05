"""Append-only ORM models for Sector-owned industry operating templates."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable
from typing import Any, NoReturn

from django.core.exceptions import ValidationError
from django.db import models
from django.db.models.base import ModelBase

from apps.sector.domain.industry_operating_template import (
    ImmutableTemplateRunEvidence,
    TemplateLifecycle,
    TemplateRunStatus,
)
from shared.infrastructure.django_append_only import AppendOnlyManager


def _payload_hash(payload: object) -> str:
    """Return the canonical JSON digest used by Domain evidence."""

    return hashlib.sha256(
        json.dumps(
            payload,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    ).hexdigest()


class ImmutableIndustryTemplateModel(models.Model):
    """Reject updates and deletes for versioned template evidence."""

    objects = AppendOnlyManager()

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
        """Insert once and reject mutation of an existing row."""

        if self.pk and type(self)._default_manager.filter(pk=self.pk).exists():
            raise ValidationError("industry operating-template evidence is immutable")
        super().save(
            force_insert=force_insert,
            force_update=force_update,
            using=using,
            update_fields=update_fields,
        )

    def delete(self, *args: Any, **kwargs: Any) -> NoReturn:
        """Reject deletion of append-only template evidence."""

        raise ValidationError("industry operating-template evidence cannot be deleted")


class IndustryOperatingTemplateVersionModel(ImmutableIndustryTemplateModel):
    """One immutable, hash-sealed and unseeded industry template version."""

    LIFECYCLE_CHOICES = [(item.value, item.value) for item in TemplateLifecycle]

    template_code = models.CharField(max_length=80, db_index=True)
    template_version = models.PositiveIntegerField()
    industry_code = models.CharField(max_length=80, db_index=True)
    name = models.CharField(max_length=160)
    methodology_ref = models.CharField(max_length=300)
    effective_at = models.DateTimeField(db_index=True)
    effective_to = models.DateTimeField(null=True, blank=True, db_index=True)
    lifecycle = models.CharField(max_length=16, choices=LIFECYCLE_CHOICES, db_index=True)
    lifecycle_reason = models.CharField(max_length=500, blank=True)
    supersedes_version = models.PositiveIntegerField(null=True, blank=True)
    content_hash = models.CharField(max_length=64, unique=True)
    payload = models.JSONField()
    research_only = models.BooleanField(default=True, editable=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "sector_industry_operating_template"
        base_manager_name = "objects"
        default_manager_name = "objects"
        ordering = ["template_code", "template_version"]
        constraints = [
            models.UniqueConstraint(
                fields=["template_code", "template_version"],
                name="sector_industry_template_version_unique",
            ),
            models.CheckConstraint(
                condition=models.Q(effective_to__isnull=True)
                | models.Q(effective_to__gt=models.F("effective_at")),
                name="sector_industry_template_interval_valid",
            ),
            models.CheckConstraint(
                condition=models.Q(research_only=True),
                name="sector_industry_template_research_only",
            ),
        ]
        indexes = [
            models.Index(
                fields=["industry_code", "lifecycle", "-template_version"],
                name="sector_industry_tpl_state_idx",
            ),
            models.Index(
                fields=["template_code", "-template_version"],
                name="sector_industry_tpl_code_idx",
            ),
        ]

    def clean(self) -> None:
        """Verify research scope and payload integrity before insertion."""

        super().clean()
        if not self.research_only:
            raise ValidationError("industry templates must remain research-only")
        if not isinstance(self.payload, dict) or _payload_hash(self.payload) != self.content_hash:
            raise ValidationError("industry template payload hash mismatch")


class IndustryTemplateRunEvidenceModel(ImmutableIndustryTemplateModel):
    """One immutable, research-only execution evidence version."""

    STATUS_CHOICES = [(item.value, item.value) for item in TemplateRunStatus]

    run_key = models.CharField(max_length=128, db_index=True)
    run_version = models.PositiveIntegerField()
    template_code = models.CharField(max_length=80, db_index=True)
    template_version = models.PositiveIntegerField()
    template_content_hash = models.CharField(max_length=64, blank=True)
    as_of_time = models.DateTimeField(db_index=True)
    status = models.CharField(max_length=16, choices=STATUS_CHOICES, db_index=True)
    content_hash = models.CharField(max_length=64, unique=True)
    payload = models.JSONField()
    research_only = models.BooleanField(default=True, editable=False)
    must_not_use_for_decision = models.BooleanField(default=True, editable=False)
    must_not_execute = models.BooleanField(default=True, editable=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "sector_industry_template_run_evidence"
        base_manager_name = "objects"
        default_manager_name = "objects"
        ordering = ["run_key", "run_version"]
        constraints = [
            models.UniqueConstraint(
                fields=["run_key", "run_version"],
                name="sector_industry_run_version_unique",
            ),
            models.CheckConstraint(
                condition=models.Q(research_only=True),
                name="sector_industry_run_research_only",
            ),
            models.CheckConstraint(
                condition=models.Q(must_not_use_for_decision=True),
                name="sector_industry_run_no_decision",
            ),
            models.CheckConstraint(
                condition=models.Q(must_not_execute=True),
                name="sector_industry_run_no_execute",
            ),
        ]
        indexes = [
            models.Index(
                fields=["template_code", "template_version", "-as_of_time"],
                name="sector_industry_run_tpl_idx",
            ),
            models.Index(
                fields=["status", "-as_of_time"],
                name="sector_industry_run_state_idx",
            ),
        ]

    def clean(self) -> None:
        """Verify non-decision flags and reconstruct hash-sealed evidence."""

        super().clean()
        if not isinstance(self.payload, dict):
            raise ValidationError("industry template run payload must be an object")
        ImmutableTemplateRunEvidence(
            run_key=self.run_key,
            run_version=self.run_version,
            template_code=self.template_code,
            template_version=self.template_version,
            template_content_hash=self.template_content_hash,
            as_of_time=self.as_of_time,
            status=TemplateRunStatus(self.status),
            content_hash=self.content_hash,
            payload_json=json.dumps(
                self.payload,
                ensure_ascii=False,
                separators=(",", ":"),
                sort_keys=True,
            ),
            research_only=self.research_only,
            must_not_use_for_decision=self.must_not_use_for_decision,
            must_not_execute=self.must_not_execute,
        )


__all__ = [
    "IndustryOperatingTemplateVersionModel",
    "IndustryTemplateRunEvidenceModel",
]
