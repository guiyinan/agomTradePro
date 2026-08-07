"""AI capability projection evidence for governed Risk Center scenarios."""

from agomtradepro_mcp.registry.loader import CapabilityRegistryLoader


def test_risk_center_scenario_read_catalog_projection_is_owned_and_native() -> None:
    keys = {
        "risk_center.stress_scenario.list",
        "risk_center.stress_scenario.read",
        "risk_center.stress_scenario.compare",
        "risk_center.stress_scenario.validate_revision",
        "risk_center.stress_scenario.preview_revision",
    }
    registry = CapabilityRegistryLoader().build_registry()

    assert keys <= set(registry)
    for key in keys:
        manifest = registry[key]
        assert manifest.owner_app == "risk_center"
        assert manifest.executor_kind == "internal_handler"
        assert "mcp:native" in manifest.audit_tags
