"""User-task contracts for staff-managed regional data exits."""

from pathlib import Path

from apps.terminal.infrastructure.tui_metadata_repository import PublishedTuiMetadataRepository
from apps.terminal.infrastructure.tui_metadata_runtime_injection_egress import (
    RUNTIME_EGRESS_ACTIONS,
)


def test_egress_tasks_support_full_configuration_and_do_not_expose_secrets() -> None:
    actions = {a["key"]: a for a in RUNTIME_EGRESS_ACTIONS}
    assert len(actions) == 9
    for action in actions.values():
        assert action["audience"] == "admin"
        assert action["screen_key"] == "api-library.data-center"
        assert "/api/" not in action["label"] + action["description"]
        if action["method"] != "GET" and action["key"] != "data-center.egress-preview":
            assert action["confirmation_required"] and action["audit_required"]
    create = actions["data-center.egress-endpoint-create"]
    fields = {f["key"]: f for f in create["fields"]}
    assert fields["password"]["input_type"] == "password"
    assert "default" not in fields["password"]
    assert fields["enabled"]["default"] is False
    update = actions["data-center.egress-endpoint-update"]
    assert update["method"] == "PATCH"
    assert all("default" not in f for f in update["fields"])
    rule = actions["data-center.egress-rule-create"]
    strategy = next(f for f in rule["fields"] if f["key"] == "strategy")
    assert {o["value"] for o in strategy["options"]} == {"direct", "fixed", "direct_fallback"}


def test_egress_panels_bind_row_actions_and_diagnostic_receipts() -> None:
    path = (
        Path(__file__).resolve().parents[3]
        / "config/tui/published/tui_operation_graph.published.json"
    )
    runtime = PublishedTuiMetadataRepository(published_path=path)._load_published_file()
    screen = next(s for s in runtime["screens"] if s["key"] == "api-library.data-center")
    panels = {p["key"]: p for p in screen["dashboard_panels"]}
    assert panels["egress-endpoints"]["action_key"] == "data-center.egress-endpoints"
    assert panels["egress-rules"]["action_key"] == "data-center.egress-rules"
    for key in ("egress-endpoints", "egress-rules"):
        for action in panels[key]["row_actions"]:
            assert action["result_panel_key"] == "egress-receipt"
    registered = {a["key"] for a in runtime["actions"]}
    assert {a["key"] for a in RUNTIME_EGRESS_ACTIONS} <= registered
