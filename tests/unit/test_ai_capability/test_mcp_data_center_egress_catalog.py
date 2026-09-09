"""Native data egress capabilities remain part of the shared governed catalog."""

from agomtradepro_mcp.registry.loader import CapabilityRegistryLoader


def test_data_center_egress_native_catalog_covers_configuration_and_diagnostics():
    read_keys = {
        "data_center.read.egress_endpoints",
        "data_center.read.egress_endpoint",
        "data_center.read.egress_rules",
        "data_center.read.egress_rule",
        "data_center.read.egress_route_preview",
    }
    write_keys = {
        "data_center.create.egress_endpoint",
        "data_center.update.egress_endpoint",
        "data_center.create.egress_rule",
        "data_center.update.egress_rule",
        "data_center.run.egress_endpoint_test",
        "data_center.run.egress_diagnostics",
    }
    registry = CapabilityRegistryLoader().build_registry()
    for key in read_keys | write_keys:
        manifest = registry[key]
        assert manifest.owner_app == "data_center"
        assert manifest.required_roles == ("staff",)
        assert "mcp:native" in manifest.audit_tags
        assert manifest.executor_kind == "internal_handler"
        assert manifest.requires_confirmation is (key in write_keys)
        assert manifest.idempotency == ("required" if key in write_keys else "none")
