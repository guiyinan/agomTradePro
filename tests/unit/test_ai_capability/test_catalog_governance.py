"""Tests for AI capability catalog governance."""

import pytest

from apps.ai_capability.application.governance_services import (
    CapabilityCatalogGovernanceService,
)
from apps.ai_capability.domain.entities import CapabilityDefinition, SourceType
from apps.ai_capability.infrastructure.models import CapabilityCatalogModel
from apps.ai_capability.infrastructure.repositories import DjangoCapabilityRepository


def _create_capability(**overrides):
    data = {
        "capability_key": "api.get.api.market.status",
        "source_type": "api",
        "source_ref": "GET api/market/status/",
        "name": "Get Market Status",
        "summary": "Read market status",
        "route_group": "read_api",
        "category": "market",
        "execution_target": {
            "type": "api",
            "method": "GET",
            "path": "api/market/status/",
        },
        "risk_level": "safe",
        "requires_confirmation": True,
        "enabled_for_routing": False,
        "enabled_for_terminal": True,
        "enabled_for_chat": False,
        "enabled_for_agent": True,
        "visibility": "internal",
        "auto_collected": True,
        "review_status": "auto",
    }
    data.update(overrides)
    return CapabilityCatalogModel.objects.create(**data)


@pytest.mark.django_db
def test_capability_governance_dry_run_does_not_mutate_catalog():
    _create_capability()

    result = CapabilityCatalogGovernanceService().execute(
        apply=False,
        current_keys_by_source={
            "api": {"api.get.api.market.status"},
            "mcp_tool": set(),
        },
    )

    capability = CapabilityCatalogModel.objects.get(
        capability_key="api.get.api.market.status",
    )
    assert result.changed_count == 1
    assert capability.enabled_for_routing is False
    assert capability.review_status == "auto"


@pytest.mark.django_db
def test_capability_governance_enables_safe_reads_and_purges_stale_entries():
    _create_capability()
    _create_capability(
        capability_key="api.get.api.legacy.status",
        source_ref="GET api/legacy/status/",
        name="Legacy Status",
        execution_target={"type": "api", "method": "GET", "path": "api/legacy/status/"},
    )

    result = CapabilityCatalogGovernanceService().execute(
        apply=True,
        current_keys_by_source={
            "api": {"api.get.api.market.status"},
            "mcp_tool": set(),
        },
    )

    capability = CapabilityCatalogModel.objects.get(
        capability_key="api.get.api.market.status",
    )
    assert result.stale_deleted_count == 1
    assert capability.enabled_for_routing is True
    assert capability.requires_confirmation is False
    assert capability.review_status == "approved"
    assert not CapabilityCatalogModel.objects.filter(
        capability_key="api.get.api.legacy.status",
    ).exists()


@pytest.mark.django_db
def test_capability_governance_rejects_unsafe_and_mutating_tools():
    _create_capability(
        capability_key="api.delete.api.runtime.reset",
        source_ref="DELETE api/runtime/reset/",
        name="Delete Runtime Reset",
        route_group="unsafe_api",
        risk_level="critical",
        execution_target={"type": "api", "method": "DELETE", "path": "api/runtime/reset/"},
    )
    _create_capability(
        capability_key="mcp_tool.update_portfolio_config",
        source_type="mcp_tool",
        source_ref="update_portfolio_config",
        name="update_portfolio_config",
        summary="Update portfolio config",
        route_group="tool",
        category="mcp",
        execution_target={"type": "mcp_tool", "tool_name": "update_portfolio_config"},
        risk_level="high",
        requires_mcp=True,
    )

    result = CapabilityCatalogGovernanceService().execute(
        apply=True,
        current_keys_by_source={
            "api": {"api.delete.api.runtime.reset"},
            "mcp_tool": {"mcp_tool.update_portfolio_config"},
        },
    )

    unsafe_api = CapabilityCatalogModel.objects.get(
        capability_key="api.delete.api.runtime.reset",
    )
    mcp_tool = CapabilityCatalogModel.objects.get(
        capability_key="mcp_tool.update_portfolio_config",
    )
    assert result.routing_disabled_count == 2
    assert unsafe_api.enabled_for_routing is False
    assert unsafe_api.requires_confirmation is True
    assert unsafe_api.review_status == "rejected"
    assert mcp_tool.enabled_for_routing is False
    assert mcp_tool.requires_confirmation is True
    assert mcp_tool.review_status == "rejected"


@pytest.mark.django_db
def test_capability_governance_approves_reviewed_read_like_mcp_tools():
    _create_capability(
        capability_key="mcp_tool.get_asset_info",
        source_type="mcp_tool",
        source_ref="get_asset_info",
        name="get_asset_info",
        summary="Read asset information",
        route_group="tool",
        category="mcp",
        execution_target={"type": "mcp_tool", "tool_name": "get_asset_info"},
        risk_level="high",
        requires_mcp=True,
    )
    _create_capability(
        capability_key="mcp_tool.export_positions_json",
        source_type="mcp_tool",
        source_ref="export_positions_json",
        name="export_positions_json",
        summary="Export positions as JSON",
        route_group="tool",
        category="mcp",
        execution_target={"type": "mcp_tool", "tool_name": "export_positions_json"},
        risk_level="high",
        requires_mcp=True,
    )

    CapabilityCatalogGovernanceService().execute(
        apply=True,
        current_keys_by_source={
            "api": set(),
            "mcp_tool": {
                "mcp_tool.get_asset_info",
                "mcp_tool.export_positions_json",
            },
        },
    )

    asset_tool = CapabilityCatalogModel.objects.get(capability_key="mcp_tool.get_asset_info")
    export_tool = CapabilityCatalogModel.objects.get(
        capability_key="mcp_tool.export_positions_json"
    )
    assert asset_tool.enabled_for_routing is True
    assert asset_tool.risk_level == "low"
    assert asset_tool.review_status == "approved"
    assert export_tool.enabled_for_routing is True
    assert export_tool.risk_level == "medium"
    assert export_tool.requires_confirmation is True
    assert export_tool.review_status == "approved"


@pytest.mark.django_db
def test_capability_sync_preserves_reviewed_governance_fields():
    _create_capability(
        capability_key="mcp_tool.get_asset_info",
        source_type="mcp_tool",
        source_ref="get_asset_info",
        name="get_asset_info",
        summary="Reviewed summary",
        route_group="tool",
        category="mcp",
        execution_target={"type": "mcp_tool", "tool_name": "get_asset_info"},
        risk_level="low",
        requires_mcp=True,
        requires_confirmation=True,
        enabled_for_routing=True,
        review_status="approved",
    )

    incoming = CapabilityDefinition(
        capability_key="mcp_tool.get_asset_info",
        source_type=SourceType.MCP_TOOL,
        source_ref="get_asset_info",
        name="get_asset_info",
        summary="Fresh SDK summary",
        route_group="tool",
        category="mcp",
        execution_target={"type": "mcp_tool", "tool_name": "get_asset_info"},
        risk_level="high",
        requires_mcp=True,
        requires_confirmation=True,
        enabled_for_routing=False,
        review_status="auto",
    )

    DjangoCapabilityRepository().bulk_upsert([incoming])

    capability = CapabilityCatalogModel.objects.get(capability_key="mcp_tool.get_asset_info")
    assert capability.summary == "Fresh SDK summary"
    assert capability.risk_level == "low"
    assert capability.enabled_for_routing is True
    assert capability.requires_confirmation is True
    assert capability.review_status == "approved"


@pytest.mark.django_db
def test_catalog_save_preserves_the_collected_semantic_key():
    model = _create_capability(
        semantic_key="semantic.market.status",
        collected_semantic_key="legacy.market.status",
    )

    DjangoCapabilityRepository().save(model.to_entity())

    model.refresh_from_db()
    assert model.semantic_key == "semantic.market.status"
    assert model.collected_semantic_key == "legacy.market.status"


@pytest.mark.django_db
def test_catalog_model_from_entity_initializes_collected_semantic_key():
    model = _create_capability(
        semantic_key="semantic.market.status",
    )
    entity = model.to_entity()

    unsaved = CapabilityCatalogModel.from_entity(entity)

    assert unsaved.collected_semantic_key == "semantic.market.status"
