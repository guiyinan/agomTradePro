"""Audit Admin typing and evidence immutability regressions."""

from __future__ import annotations

from django.contrib import admin

from apps.audit.interface.admin import (
    AttributionReportAdmin,
    AuditReportAdmin,
    ExperienceSummaryAdmin,
    IndicatorPerformanceModelAdmin,
    IndicatorThresholdConfigModelAdmin,
    LossAnalysisAdmin,
    ValidationSummaryModelAdmin,
)
from apps.audit.models import (
    AttributionReport,
    AuditReport,
    ExperienceSummary,
    IndicatorPerformanceModel,
    IndicatorThresholdConfigModel,
    LossAnalysis,
    ValidationSummaryModel,
)
from shared.infrastructure.django_admin import TypedModelAdmin


def test_audit_models_are_registered_once_through_typed_admins() -> None:
    """Django autodiscovery retains one typed Admin owner per Audit model."""

    expected = {
        AuditReport: AuditReportAdmin,
        AttributionReport: AttributionReportAdmin,
        LossAnalysis: LossAnalysisAdmin,
        ExperienceSummary: ExperienceSummaryAdmin,
        IndicatorThresholdConfigModel: IndicatorThresholdConfigModelAdmin,
        IndicatorPerformanceModel: IndicatorPerformanceModelAdmin,
        ValidationSummaryModel: ValidationSummaryModelAdmin,
    }
    for model, admin_class in expected.items():
        assert admin.site.is_registered(model)
        assert isinstance(admin.site._registry[model], admin_class)
        assert issubclass(admin_class, TypedModelAdmin)


def test_generated_audit_evidence_is_fully_immutable() -> None:
    """Admin cannot fabricate, alter, or delete generated audit evidence."""

    evidence_models = (
        AuditReport,
        AttributionReport,
        LossAnalysis,
        IndicatorPerformanceModel,
        ValidationSummaryModel,
    )
    for model in evidence_models:
        evidence_admin = admin.site._registry[model]
        assert evidence_admin.has_add_permission(None) is False
        assert evidence_admin.has_change_permission(None) is False
        assert evidence_admin.has_delete_permission(None) is False
        assert set(evidence_admin.readonly_fields) == {field.name for field in model._meta.fields}


def test_experience_summary_only_exposes_application_tracking_fields() -> None:
    """Generated lessons stay immutable while operators may track adoption."""

    summary_admin = admin.site._registry[ExperienceSummary]
    assert summary_admin.has_add_permission(None) is False
    assert summary_admin.has_delete_permission(None) is False
    editable_fields = {field.name for field in ExperienceSummary._meta.fields} - set(
        summary_admin.readonly_fields
    )
    assert editable_fields == {"is_applied", "applied_at"}
