"""Dashboard mutation reachability follows the entity's immediate collection."""

from typing import Any

import pytest

from apps.terminal.application.tui_metadata import _validate_dashboard_collection_actionability
from apps.terminal.application.tui_metadata_filter_validation import TuiMetadataValidationError


def test_account_panel_does_not_claim_nested_trade_mutations() -> None:
    """Trade selection is a child-list task; account mutations still need a row link."""

    source = {
        "key": "accounts.list",
        "screen_key": "execution.accounts",
        "method": "GET",
        "endpoint": "/api/accounts/",
    }
    mutation: dict[str, Any] = {
        "key": "trades.preview",
        "screen_key": "execution.accounts",
        "method": "POST",
        "endpoint": "/api/accounts/<int:account_id>/trades/<int:trade_id>/preview/",
        "fields": [
            {"key": key, "required": True, "binding": "path"} for key in ("account_id", "trade_id")
        ],
    }
    screen = {
        "key": "execution.accounts",
        "dashboard_panels": [
            {
                "key": "accounts",
                "kind": "datagrid",
                "action_key": source["key"],
                "row_actions": [],
            }
        ],
    }
    actions = {source["key"]: source, mutation["key"]: mutation}
    _validate_dashboard_collection_actionability(screen=screen, action_by_key=actions)

    mutation["endpoint"] = "/api/accounts/<int:account_id>/preferences/"
    mutation["fields"] = [{"key": "account_id", "required": True, "binding": "path"}]
    with pytest.raises(TuiMetadataValidationError, match="unreachable collection mutation"):
        _validate_dashboard_collection_actionability(screen=screen, action_by_key=actions)
