"""AI capability catalog projection for broker execution."""

from agomtradepro_mcp.registry.loader import CapabilityRegistryLoader


def test_broker_execution_read_catalog_projection_is_owned_and_native() -> None:
    keys = {
        "broker_execution.read.overview",
        "broker_execution.read.order_catalog",
        "broker_execution.read.order_detail",
        "broker_execution.read.connection_status",
        "broker_execution.read.reconciliation_catalog",
        "broker_execution.read.audit_catalog",
    }
    registry = CapabilityRegistryLoader().build_registry()
    assert keys <= set(registry)
    for key in keys:
        manifest = registry[key]
        assert manifest.owner_app == "broker_execution"
        assert manifest.audit_tags == ("broker_execution:read", "mcp:native")


def test_broker_execution_write_catalog_projection_requires_governance() -> None:
    keys = {
        "broker_execution.approve.order",
        "broker_execution.reject.order",
        "broker_execution.request.cancel",
        "broker_execution.trigger.kill_switch",
        "broker_execution.resume.trading",
        "broker_execution.resolve.reconciliation",
    }
    registry = CapabilityRegistryLoader().build_registry()
    for key in keys:
        manifest = registry[key]
        assert manifest.requires_confirmation is True
        assert manifest.idempotency == "required"
        assert "mcp:native" in manifest.audit_tags
    assert registry["broker_execution.approve.order"].enabled is False
    assert registry["broker_execution.reject.order"].enabled is True
    assert registry["broker_execution.request.cancel"].enabled is True
