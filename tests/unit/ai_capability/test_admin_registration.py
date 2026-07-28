"""AI Capability Admin typing and governance boundary regressions."""

from __future__ import annotations

from types import SimpleNamespace
from typing import cast

from django.contrib import admin

from apps.ai_capability.interface.admin import (
    CapabilityCatalogAdmin,
    CapabilityRoutingLogAdmin,
    CapabilitySemanticAuditAdmin,
    CapabilitySemanticOverrideAdmin,
    CapabilitySyncLogAdmin,
)
from apps.ai_capability.models import (
    CapabilityCatalogModel,
    CapabilityRoutingLogModel,
    CapabilitySemanticAuditModel,
    CapabilitySemanticOverrideModel,
    CapabilitySyncLogModel,
)
from shared.infrastructure.django_admin import TypedModelAdmin


def test_capability_models_are_registered_once_through_typed_admins() -> None:
    """Django autodiscovery retains one typed owner per capability model."""

    expected = {
        CapabilityCatalogModel: CapabilityCatalogAdmin,
        CapabilityRoutingLogModel: CapabilityRoutingLogAdmin,
        CapabilitySyncLogModel: CapabilitySyncLogAdmin,
        CapabilitySemanticOverrideModel: CapabilitySemanticOverrideAdmin,
        CapabilitySemanticAuditModel: CapabilitySemanticAuditAdmin,
    }
    for model, admin_class in expected.items():
        assert admin.site.is_registered(model)
        assert isinstance(admin.site._registry[model], admin_class)
        assert issubclass(admin_class, TypedModelAdmin)


def test_generated_capability_evidence_is_fully_immutable() -> None:
    """Routing, sync, override, and audit evidence cannot be mutated in Admin."""

    evidence_models = (
        CapabilityRoutingLogModel,
        CapabilitySyncLogModel,
        CapabilitySemanticOverrideModel,
        CapabilitySemanticAuditModel,
    )
    for model in evidence_models:
        evidence_admin = admin.site._registry[model]
        assert evidence_admin.has_add_permission(None) is False
        assert evidence_admin.has_change_permission(None) is False
        assert evidence_admin.has_delete_permission(None) is False
        assert set(evidence_admin.readonly_fields) == {field.name for field in model._meta.fields}


def test_catalog_semantic_identity_is_readonly_but_governance_fields_remain_editable() -> None:
    """Semantic corrections use the audited workflow without locking risk controls."""

    catalog_admin = admin.site._registry[CapabilityCatalogModel]
    assert catalog_admin.has_delete_permission(None) is False
    readonly_fields = set(catalog_admin.readonly_fields)
    assert {"semantic_key", "collected_semantic_key"} <= readonly_fields
    assert {
        "risk_level",
        "requires_confirmation",
        "enabled_for_routing",
        "review_status",
    }.isdisjoint(readonly_fields)


def test_catalog_risk_badge_escapes_labels_and_publishes_ordering() -> None:
    """Risk presentation cannot inject markup and retains sortable metadata."""

    catalog_admin = cast(
        CapabilityCatalogAdmin,
        admin.site._registry[CapabilityCatalogModel],
    )
    capability = cast(
        CapabilityCatalogModel,
        SimpleNamespace(
            risk_level="critical",
            get_risk_level_display=lambda: "<critical>",
        ),
    )

    assert "&lt;critical&gt;" in str(catalog_admin.colored_risk_level(capability))
    assert CapabilityCatalogAdmin.colored_risk_level.admin_order_field == "risk_level"
