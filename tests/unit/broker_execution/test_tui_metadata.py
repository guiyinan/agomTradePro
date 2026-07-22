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
        "broker-execution.approve-order",
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
    assert actions["broker-execution.approve-order"]["risk"] == "write"
    assert actions["broker-execution.approve-order"]["confirmation_required"] is True
    assert actions["broker-execution.trigger-kill-switch"]["confirmation_required"] is True
    assert actions["broker-execution.resume-trading"]["requires_password"] is True
    account_panels = {
        panel["key"]: panel
        for panel in screens["execution.accounts"].get("dashboard_panels", [])
    }
    audit_panels = {
        panel["key"]: panel
        for panel in screens["execution.audit"].get("dashboard_panels", [])
    }
    assert account_panels["broker-execution-readiness"]["user_priority"] == "p0"
    assert account_panels["broker-execution-orders"]["user_priority"] == "p0"
    assert audit_panels["broker-execution-reconciliation"]["user_priority"] == "p0"


@pytest.mark.django_db
def test_broker_execution_tui_uses_canonical_human_screens() -> None:
    metadata = PublishedTuiMetadataRepository().load_published()
    actions = {
        item["key"]: item for item in metadata["actions"] if item["key"].startswith("broker-execution.")
    }
    assert {item["screen_key"] for item in actions.values()} <= {
        "execution.accounts",
        "execution.audit",
    }
    ordinary_copy = " ".join(
        str(item.get("description") or "") + str(item.get("label") or "")
        for item in actions.values()
    )
    assert "Agent Token" not in ordinary_copy
    assert "userdata_mini" not in ordinary_copy
