"""Append-only DB-owned financial numeric qualifications and capture metadata.

These models deliberately do not store a publisher-native document
version, an ``approved`` flag, or business metric/unit defaults. A qualification
becomes resolvable only through an authenticated Owner event and independent
retained-body, egress-audit, provider-identity, and clock checks in the
repository. PostgreSQL triggers and ORM guards preserve append-only history.
"""

from __future__ import annotations

from typing import Self
from uuid import uuid4

from django.conf import settings
from django.db import models

from apps.data_center.domain.provider_document_response import PUBLIC_DOCUMENT_SOURCE_TYPE
from apps.data_center.infrastructure.statutory_source_models import (
    _StatutorySourceImmutableModel,
    _StatutorySourceManager,
)


class FinancialNumericSourceDocumentCaptureModel(_StatutorySourceImmutableModel):
    """One exact raw public-document body capture with controlled-egress metadata.

    ``capture_id`` is a local request/capture UUID. No publisher-native source
    version exists in this table or is inferred from this identifier.
    """

    capture_id = models.UUIDField(primary_key=True, editable=False)
    provider = models.ForeignKey(
        "data_center.ProviderConfigModel",
        on_delete=models.PROTECT,
        related_name="financial_numeric_source_document_captures",
    )
    provider_name_snapshot = models.CharField(max_length=100)
    provider_source_type_snapshot = models.CharField(max_length=20)
    dataset_key = models.CharField(max_length=120)
    deployment_region = models.CharField(max_length=40)
    issuer = models.CharField(max_length=240)
    document_id = models.CharField(max_length=240)
    canonical_url = models.TextField()
    target_url_sha256 = models.CharField(max_length=64)
    target_host = models.CharField(max_length=253)
    request_attempt = models.PositiveSmallIntegerField()
    egress_id = models.PositiveBigIntegerField(null=True, blank=True)
    transport = models.CharField(max_length=16)
    status_code = models.PositiveSmallIntegerField()
    content_type = models.CharField(max_length=200)
    response_completed_at = models.DateTimeField()
    body_sha256 = models.CharField(max_length=64)
    body_size_bytes = models.PositiveBigIntegerField()
    body_reference = models.CharField(max_length=1024)
    objects: _StatutorySourceManager[Self] = _StatutorySourceManager()

    class Meta:
        db_table = "data_center_fin_numeric_doc_capture"
        base_manager_name = "objects"
        default_manager_name = "objects"
        ordering = ("response_completed_at", "capture_id")
        indexes = [
            models.Index(
                fields=("provider", "dataset_key", "response_completed_at"),
                name="dc_fin_num_doc_scope_idx",
            ),
            models.Index(fields=("body_sha256",), name="dc_fin_num_doc_body_idx"),
        ]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(provider_source_type_snapshot=PUBLIC_DOCUMENT_SOURCE_TYPE),
                name="dc_fin_num_doc_provider_ck",
            ),
            models.CheckConstraint(
                condition=models.Q(transport="egress"),
                name="dc_fin_num_doc_transport_ck",
            ),
            models.CheckConstraint(
                condition=models.Q(status_code__gte=200, status_code__lt=300),
                name="dc_fin_num_doc_status_ck",
            ),
            models.CheckConstraint(
                condition=models.Q(request_attempt__gte=1, body_size_bytes__gt=0),
                name="dc_fin_num_doc_size_ck",
            ),
            models.CheckConstraint(
                condition=models.Q(
                    recorded_at__gte=models.F("response_completed_at"),
                    target_url_sha256__regex=r"^[0-9a-f]{64}$",
                    body_sha256__regex=r"^[0-9a-f]{64}$",
                ),
                name="dc_fin_num_doc_integrity_ck",
            ),
        ]


class FinancialMetricSourceCatalogEntryModel(_StatutorySourceImmutableModel):
    """One immutable exact qualification revision tied to a retained document capture."""

    entry_id = models.UUIDField(primary_key=True, default=uuid4, editable=False)
    qualification_identity = models.CharField(max_length=256, unique=True)
    qualification_sha256 = models.CharField(max_length=64)
    contract_identity = models.CharField(max_length=160, db_index=True)
    contract_sha256 = models.CharField(max_length=64)
    contract_provider = models.CharField(max_length=128)
    dataset_key = models.CharField(max_length=160)
    metric_code = models.CharField(max_length=128)
    qualification = models.JSONField()
    document_capture = models.ForeignKey(
        FinancialNumericSourceDocumentCaptureModel,
        on_delete=models.PROTECT,
        related_name="catalog_entries",
    )
    effective_from = models.DateTimeField()
    effective_until = models.DateTimeField(null=True, blank=True)
    objects: _StatutorySourceManager[Self] = _StatutorySourceManager()

    class Meta:
        db_table = "data_center_fin_metric_source_entry"
        base_manager_name = "objects"
        default_manager_name = "objects"
        ordering = ("recorded_at", "entry_id")
        indexes = [
            models.Index(
                fields=("contract_identity", "effective_from", "effective_until"),
                name="dc_fin_metric_scope_idx",
            ),
            models.Index(
                fields=("dataset_key", "metric_code"),
                name="dc_fin_metric_code_idx",
            ),
        ]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(
                    qualification_sha256__regex=r"^[0-9a-f]{64}$",
                    contract_sha256__regex=r"^[0-9a-f]{64}$",
                ),
                name="dc_fin_metric_hashes_ck",
            ),
            models.CheckConstraint(
                condition=models.Q(effective_until__isnull=True)
                | models.Q(effective_until__gt=models.F("effective_from")),
                name="dc_fin_metric_effective_ck",
            ),
        ]


class FinancialMetricSourceCatalogOwnerEventModel(_StatutorySourceImmutableModel):
    """One append-only authenticated Owner apply or revoke for an exact entry hash."""

    event_id = models.UUIDField(primary_key=True, default=uuid4, editable=False)
    entry = models.ForeignKey(
        FinancialMetricSourceCatalogEntryModel,
        on_delete=models.PROTECT,
        related_name="owner_events",
    )
    action = models.CharField(
        max_length=8,
        choices=(("apply", "Apply"), ("revoke", "Revoke")),
    )
    qualification_identity = models.CharField(max_length=256)
    qualification_sha256 = models.CharField(max_length=64)
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="financial_metric_source_catalog_events",
    )
    actor_username_snapshot = models.CharField(max_length=150)
    event_at = models.DateTimeField()
    objects: _StatutorySourceManager[Self] = _StatutorySourceManager()

    class Meta:
        db_table = "data_center_fin_metric_source_owner_event"
        base_manager_name = "objects"
        default_manager_name = "objects"
        ordering = ("recorded_at", "event_id")
        indexes = [
            models.Index(fields=("entry", "recorded_at"), name="dc_fin_metric_event_idx"),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=("entry", "action"),
                name="dc_fin_metric_event_once_uniq",
            ),
            models.CheckConstraint(
                condition=models.Q(action__in=("apply", "revoke")),
                name="dc_fin_metric_action_ck",
            ),
            models.CheckConstraint(
                condition=models.Q(
                    recorded_at__gte=models.F("event_at"),
                    qualification_sha256__regex=r"^[0-9a-f]{64}$",
                ),
                name="dc_fin_metric_event_clock_ck",
            ),
        ]


__all__ = [
    "FinancialMetricSourceCatalogEntryModel",
    "FinancialMetricSourceCatalogOwnerEventModel",
    "FinancialNumericSourceDocumentCaptureModel",
]
