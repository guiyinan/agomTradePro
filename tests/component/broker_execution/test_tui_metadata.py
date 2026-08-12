"""Published TUI coverage for QMT live execution tasks."""

import pytest

from apps.terminal.application.tui_metadata import validate_tui_metadata
from apps.terminal.infrastructure.tui_metadata_repository import (
    PublishedTuiMetadataRepository,
)


@pytest.mark.django_db
def test_broker_execution_actions_and_p0_panels_are_published() -> None:
    metadata = PublishedTuiMetadataRepository().load_published()
    validate_tui_metadata(metadata)
    actions = {item["key"]: item for item in metadata["actions"]}
    screens = {item["key"]: item for item in metadata["screens"]}
    expected = {
        "broker-execution.overview",
        "broker-execution.order-list",
        "broker-execution.order-detail",
        "broker-execution.approval-preview",
        "broker-execution.reject-preview",
        "broker-execution.reject-order",
        "broker-execution.cancel-preview",
        "broker-execution.request-cancel",
        "broker-execution.connection-status",
        "broker-execution.reconciliation-list",
        "broker-execution.audit-list",
        "broker-execution.kill-switch-preview",
        "broker-execution.trigger-kill-switch",
        "broker-execution.resume-preview",
        "broker-execution.resume-trading",
    }
    assert expected <= set(actions)
    assert "broker-execution.approve-order" not in actions
    assert "broker-execution.advisor-draft-preview" in actions
    assert "broker-execution.advisor-draft" not in actions
    assert actions["broker-execution.trigger-kill-switch"]["confirmation_required"] is True
    assert actions["broker-execution.resume-trading"]["requires_password"] is True
    account_panels = {
        panel["key"]: panel for panel in screens["execution.accounts"].get("dashboard_panels", [])
    }
    audit_panels = {
        panel["key"]: panel for panel in screens["execution.audit"].get("dashboard_panels", [])
    }
    assert account_panels["broker-execution-readiness"]["user_priority"] == "p0"
    assert account_panels["broker-execution-orders"]["user_priority"] == "p0"
    assert audit_panels["broker-execution-reconciliation"]["user_priority"] == "p0"
    setup_panels = {
        panel["key"]: panel
        for panel in screens["broker-execution.qmt-setup"].get("dashboard_panels", [])
    }
    assert setup_panels["qmt-setup-guide"]["presentation_semantic"] == "setup_guide"
    assert setup_panels["qmt-current-settings"]["user_priority"] == "p0"
    assert actions["broker-execution.qmt-onboarding-guide"]["result_semantics"] == [
        "primary_status",
        "setup_guide",
    ]


@pytest.mark.django_db
def test_broker_execution_tui_uses_canonical_human_screens() -> None:
    metadata = PublishedTuiMetadataRepository().load_published()
    actions = {
        item["key"]: item
        for item in metadata["actions"]
        if item["key"].startswith("broker-execution.")
    }
    assert {item["screen_key"] for item in actions.values()} <= {
        "execution.accounts",
        "execution.audit",
        "broker-execution.qmt-setup",
    }
    ordinary_copy = " ".join(
        str(item.get("description") or "") + str(item.get("label") or "")
        for item in actions.values()
    )
    assert "Agent Token" not in ordinary_copy
    assert "userdata_mini" not in ordinary_copy
