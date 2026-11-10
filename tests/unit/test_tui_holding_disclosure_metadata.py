"""Runtime action metadata for the held-security disclosure read."""

from __future__ import annotations

from copy import deepcopy
from types import SimpleNamespace
from typing import Any

from rest_framework.test import APIRequestFactory, force_authenticate

import apps.terminal.interface.api_views as tui_api_views
from apps.terminal.application.tui_metadata import validate_tui_metadata
from apps.terminal.application.tui_workbench import TuiWorkbenchService
from apps.terminal.infrastructure.tui_metadata_runtime_injection_simulated_trading import (
    RUNTIME_SIMULATED_TRADING_ACTIONS,
)

_ACTION_KEY = "simulated-trading.holding-disclosures"


def test_holding_disclosure_action_is_explicitly_scoped_and_read_only() -> None:
    action = next(item for item in RUNTIME_SIMULATED_TRADING_ACTIONS if item["key"] == _ACTION_KEY)
    fields = action["fields"]
    fields_by_key = {field["key"]: field for field in fields}

    assert action["endpoint"] == (
        "/api/simulated-trading/accounts/<int:account_id>/holding-disclosures/"
    )
    assert action["method"] == "GET"
    assert action["intent"] == "read_owned_holding_financial_disclosures"
    assert action["risk"] == "read"
    assert action["effect"] == "read"
    assert action["audience"] == "authenticated"
    assert action["screen_key"] == "execution.accounts"
    assert action["raw_debug"] is False
    assert action["session_auth_required"] is True
    assert fields_by_key["account_id"]["binding"] == "path"
    assert fields_by_key["account_id"]["required"] is True
    assert fields_by_key["asset_code"]["binding"] == "query"
    assert fields_by_key["asset_code"]["required"] is True
    assert fields_by_key["asset_code"]["label"] == "持仓证券代码"
    assert action["view_model"]["kind"] == "detail"


def test_holding_disclosure_action_copy_stays_user_facing() -> None:
    action = next(item for item in RUNTIME_SIMULATED_TRADING_ACTIONS if item["key"] == _ACTION_KEY)
    copy = " ".join([action["label"], action["description"]])
    field_copy = " ".join(str(field.get("label") or "") for field in action["fields"])

    assert "/api/" not in copy
    assert "GET" not in copy
    assert "端点" not in copy
    assert "只读" in copy
    assert "本人有权查看的模拟账户" in copy
    assert "不用于投资决策" in copy
    assert "有效" not in copy
    assert "不会计算、分配或入账现金" in copy
    assert "持仓证券代码" in field_copy


def test_holding_disclosure_runtime_action_fields_are_typed() -> None:
    action = next(item for item in RUNTIME_SIMULATED_TRADING_ACTIONS if item["key"] == _ACTION_KEY)
    fields_by_key: dict[str, dict[str, Any]] = {
        str(field["key"]): field for field in action["fields"]
    }

    assert fields_by_key["account_id"]["value_type"] == "integer"
    assert fields_by_key["asset_code"]["value_type"] == "string"
    assert fields_by_key["asset_code"]["input_type"] == "text"


def test_disclosure_action_run_rejects_non_session_auth_before_executor(
    monkeypatch: Any,
) -> None:
    """A token-style authenticator cannot start this session-only disclosure read."""

    action = deepcopy(
        next(item for item in RUNTIME_SIMULATED_TRADING_ACTIONS if item["key"] == _ACTION_KEY)
    )
    payload = validate_tui_metadata(
        {
            "version": "tui-workbench.v2",
            "default_screen": "execution.accounts",
            "groups": [{"key": "daily", "label": "日常任务"}],
            "modules": [
                {
                    "key": "daily-decisions",
                    "label": "账户与持仓",
                    "group": "daily",
                    "summary": "账户和持仓任务。",
                }
            ],
            "screens": [
                {
                    "key": "execution.accounts",
                    "label": "账户与持仓",
                    "module_key": "daily-decisions",
                    "group": "daily",
                    "summary": "查看本人有权查看的账户与持仓。",
                    "view_type": "datagrid",
                    "default_action_key": _ACTION_KEY,
                }
            ],
            "actions": [action],
        }
    )
    repository = SimpleNamespace(load_published=lambda _registry_key: payload)
    executor_factory_calls: list[bool] = []
    executor_calls: list[dict[str, object]] = []

    class RecordingExecutor:
        def execute(self, **kwargs: object) -> dict[str, object]:
            executor_calls.append(kwargs)
            return {"status_code": 200, "payload": {"outcome": "blocked"}}

    def build_executor() -> RecordingExecutor:
        executor_factory_calls.append(True)
        return RecordingExecutor()

    monkeypatch.setattr(tui_api_views, "get_tui_metadata_repository", lambda: repository)
    monkeypatch.setattr(tui_api_views, "get_tui_action_executor", build_executor)
    monkeypatch.setattr(tui_api_views, "get_terminal_audit_repository", lambda: None)
    monkeypatch.setattr(
        TuiWorkbenchService,
        "_field_payload",
        lambda _self, field, **_kwargs: dict(field),
    )
    request = APIRequestFactory().post(
        f"/api/terminal/tui/actions/{_ACTION_KEY}/run/",
        {"params": {"account_id": 41, "asset_code": "600000.SH"}},
        format="json",
    )
    force_authenticate(
        request,
        user=SimpleNamespace(
            pk=73,
            id=73,
            username="disclosure-reader",
            is_authenticated=True,
            is_active=True,
            is_staff=False,
            is_superuser=False,
        ),
    )

    response = tui_api_views.TuiWorkbenchActionRunView.as_view()(
        request,
        action_key=_ACTION_KEY,
    )

    assert response.status_code == 403
    assert response.data["error_code"] == "tui_session_auth_required"
    assert executor_factory_calls == []
    assert executor_calls == []
