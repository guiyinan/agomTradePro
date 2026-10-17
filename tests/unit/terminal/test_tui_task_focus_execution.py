"""Consumer boundary drafts for scoped task reads through the real workbench.

These isolated executor tests establish parameter and projection boundaries.
They do not establish owner authorization, browser acceptance or source truth.
"""

from __future__ import annotations

from copy import deepcopy
from types import SimpleNamespace
from typing import Any

import pytest

from apps.terminal.application.tui_workbench import TuiWorkbenchService
from apps.terminal.infrastructure.tui_metadata_runtime_injection_task_focus import (
    RUNTIME_TASK_FOCUS_ACTIONS,
)


class _NoMetadataLoad:
    """Make the deliberately isolated metadata boundary explicit."""

    def load_published(self, registry_key: str = "default") -> dict[str, Any]:
        raise AssertionError("The isolated test must use its explicit action inventory")


class _Executor:
    """Record the real executor boundary without making an HTTP request."""

    def __init__(self, result: dict[str, Any]) -> None:
        self.result = result
        self.calls: list[dict[str, Any]] = []

    def execute(
        self,
        *,
        method: str,
        endpoint: str,
        params: dict[str, Any],
        body: dict[str, Any],
        user: Any,
        session: Any = None,
        idempotency_key: str | None = None,
    ) -> dict[str, Any]:
        self.calls.append(
            {
                "method": method,
                "endpoint": endpoint,
                "params": deepcopy(params),
                "body": deepcopy(body),
                "user": user,
                "session": session,
                "idempotency_key": idempotency_key,
            }
        )
        return deepcopy(self.result)


def _service(
    monkeypatch: pytest.MonkeyPatch,
    result: dict[str, Any],
) -> tuple[TuiWorkbenchService, _Executor, SimpleNamespace, dict[str, dict[str, Any]]]:
    """Use actual scope/binding/projection code with an explicit visible inventory."""

    actions = {str(action["key"]): deepcopy(action) for action in RUNTIME_TASK_FOCUS_ACTIONS}
    actor = SimpleNamespace(
        pk=1,
        id=1,
        username="task_consumer",
        is_authenticated=True,
        is_active=True,
        is_staff=False,
    )
    executor = _Executor(result)
    service = TuiWorkbenchService(
        metadata_repository=_NoMetadataLoad(),
        action_executor=executor,
    )

    def visible_action(key: str, *, user: Any = None) -> dict[str, Any] | None:
        return deepcopy(actions[key]) if key in actions else None

    monkeypatch.setattr(service, "_action_by_key", visible_action)
    monkeypatch.setattr(service, "_allowed_runtime_risks", lambda user: {"read"})
    monkeypatch.setattr(service, "_diagnostics_allowed", lambda user: False)
    monkeypatch.setattr(service, "_field_payload", lambda field, **kwargs: deepcopy(field))
    monkeypatch.setattr(
        service,
        "_action_payload",
        lambda action, **kwargs: {
            "key": action["key"],
            "label": action["label"],
            "risk": action["risk"],
        },
    )
    monkeypatch.setattr(service, "_metadata", lambda: {"screens": []})
    return service, executor, actor, actions


def _empty_facts(portfolio_id: int = 9) -> dict[str, Any]:
    """Build a shape matching the public Account recorded-facts JSON DTO."""

    clock = {
        "read_started_at": "2026-10-18T00:00:00+00:00",
        "read_finished_at": "2026-10-18T00:00:01+00:00",
        "clock_kind": "application_read_boundary",
        "source_time_status": "not_provided",
    }
    return {
        "success": True,
        "portfolio_id": portfolio_id,
        "portfolio_name": "组合甲",
        "portfolio_is_active": True,
        "owner_user_id": 1,
        "owner_username": "task_consumer",
        "access_role": "owner",
        "positions": {"count": 0, "page": 1, "page_size": 20, "has_next": False, "items": []},
        "statistics": {
            "total_value": "0",
            "total_cost": "0",
            "total_pnl": "0",
            "total_pnl_pct": 0,
            "position_count": 0,
            "asset_class_breakdown": {},
            "region_breakdown": {},
            "total_capital_inflow": "0",
            "total_capital_outflow": "0",
            "net_capital_flow": "0",
            "currency_status": "stored_values_without_fx_normalization",
        },
        "position_read_clock": deepcopy(clock),
        "statistics_read_clock": deepcopy(clock),
    }


@pytest.mark.parametrize(
    "params",
    [
        {},
        {"account_id": "default"},
        {"account_id": True},
        {"account_id": 1.0},
        {"account_id": 1, "user_id": 2},
        {"account_id": "0"},
    ],
)
def test_invalid_task_scope_never_reaches_executor_or_uses_metadata_default(
    monkeypatch: pytest.MonkeyPatch,
    params: dict[str, Any],
) -> None:
    service, executor, actor, actions = _service(monkeypatch, {"status_code": 200, "payload": {}})
    actions["today-focus.queue"]["fields"][0]["default"] = "default"

    result = service.run_action(action_key="today-focus.queue", params=params, user=actor)

    assert executor.calls == []
    assert result["outcome"] == "blocked"
    assert result["response"]["status_code"] == 400
    assert result["user_error_code"] == "TUI_TASK_SCOPE_INVALID"
    assert result["debug"] == {"raw_available": False, "raw_response": None}


def test_bound_path_scope_survives_projection_without_becoming_query_input(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service, executor, actor, _ = _service(
        monkeypatch,
        {"status_code": 200, "payload": _empty_facts()},
    )

    result = service.run_action(
        action_key="portfolio-check.recorded-facts",
        params={"pk": "9"},
        user=actor,
    )

    assert len(executor.calls) == 1
    call = executor.calls[0]
    assert call["endpoint"] == "/api/account/portfolios/9/recorded-facts/"
    assert call["params"] == {"page": 1, "page_size": 20}
    assert call["body"] == {}
    assert call["user"] is actor
    assert result["outcome"] == "success"
    assert result["view_model"]["kind"] == "detail"
    assert "组合甲" in str(result["view_model"])


@pytest.mark.parametrize("status", [None, True, "200", 0, 700])
def test_missing_or_invalid_executor_status_cannot_become_implicit_success(
    monkeypatch: pytest.MonkeyPatch,
    status: object,
) -> None:
    response: dict[str, Any] = {"payload": _empty_facts()}
    if status is not None:
        response["status_code"] = status
    service, executor, actor, _ = _service(monkeypatch, response)

    result = service.run_action(
        action_key="portfolio-check.recorded-facts",
        params={"pk": 9},
        user=actor,
    )

    assert len(executor.calls) == 1
    assert result["response"]["status_code"] == 502
    assert result["outcome"] == "failed"
    assert result["view_model"]["kind"] == "message"
    assert "组合甲" not in str(result["view_model"])


def test_malformed_owner_200_cannot_complete_the_operation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service, executor, actor, _ = _service(
        monkeypatch,
        {
            "status_code": 200,
            "payload": {"success": True, "count": 1, "accounts": []},
        },
    )

    result = service.run_action(action_key="today-focus.account-selector", params={}, user=actor)

    assert len(executor.calls) == 1
    assert result["outcome"] == "blocked"
    assert result["view_model"]["kind"] == "message"


def test_foreign_payload_is_discarded_after_correct_request_binding(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service, executor, actor, _ = _service(
        monkeypatch,
        {
            "status_code": 200,
            "payload": {**_empty_facts(10), "portfolio_name": "FOREIGN_SECRET"},
        },
    )

    result = service.run_action(
        action_key="portfolio-check.recorded-facts",
        params={"pk": 9},
        user=actor,
    )

    assert executor.calls[0]["endpoint"].endswith("/9/recorded-facts/")
    assert result["outcome"] == "blocked"
    assert result["view_model"]["kind"] == "message"
    assert "FOREIGN_SECRET" not in str(result["view_model"])
    assert result["debug"]["raw_response"] is None


def test_fresh_hidden_or_mutating_professional_target_is_not_offered(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service, executor, actor, actions = _service(
        monkeypatch,
        {"status_code": 200, "payload": _empty_facts()},
    )
    alias = actions.pop("account.portfolio-recorded-facts")
    hidden = service.run_action(
        action_key="portfolio-check.recorded-facts",
        params={"pk": 9},
        user=actor,
    )
    assert hidden["next_steps"] == []

    actions["account.portfolio-recorded-facts"] = {**alias, "method": "POST"}
    mutating = service.run_action(
        action_key="portfolio-check.recorded-facts",
        params={"pk": 9},
        user=actor,
    )
    assert mutating["next_steps"] == []
    assert len(executor.calls) == 2
    assert all(call["method"] == "GET" for call in executor.calls)


def test_known_portfolio_selector_sends_only_declared_page_and_keeps_page_two(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    rows = [
        {
            "id": i,
            "name": f"组合{i}",
            "is_active": True,
            "base_currency_code": "CNY",
            "base_currency_name": "人民币",
        }
        for i in range(21, 41)
    ]
    service, executor, actor, _ = _service(
        monkeypatch,
        {
            "status_code": 200,
            "payload": {
                "count": 45,
                "next": "https://untrusted.invalid/?page=3",
                "previous": "https://untrusted.invalid/?page=1",
                "results": rows,
            },
        },
    )

    result = service.run_action(
        action_key="portfolio-check.portfolios", params={"page": "2"}, user=actor
    )

    assert executor.calls[0]["params"] == {"page": 2}
    assert result["view_model"]["kind"] == "datagrid"
    assert result["view_model"]["pager"]["page"] == 2
    assert result["view_model"]["pager"]["has_previous"] is True
    assert {row["id"] for row in result["view_model"]["rows"]} == set(range(21, 41))
    assert "untrusted.invalid" not in str(result["view_model"])


def test_redirect_owner_response_is_blocked_and_audited_as_failed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A scoped read never records an unconsumed redirect as a successful read."""

    service, _, actor, _ = _service(monkeypatch, {"status_code": 302, "payload": _empty_facts()})
    audits: list[dict[str, Any]] = []
    monkeypatch.setattr(service, "_append_tui_audit", lambda *args, **kwargs: audits.append(kwargs))
    result = service.run_action(
        action_key="portfolio-check.recorded-facts", params={"pk": 9}, user=actor
    )
    assert result["view_model"]["kind"] == "message"
    assert result["outcome"] in {"failed", "blocked"}
    assert audits[-1]["outcome"] == "failed"


@pytest.mark.parametrize(
    ("action_key", "field"),
    [
        ("today-focus.queue", "account_id"),
        ("portfolio-check.recorded-facts", "pk"),
        ("account.portfolio-recorded-facts", "pk"),
    ],
)
def test_missing_selection_preserves_the_existing_required_field_recovery(
    monkeypatch: pytest.MonkeyPatch, action_key: str, field: str
) -> None:
    """Strict scope rejection also publishes the established missing-input contract."""

    service, executor, actor, _ = _service(monkeypatch, {"status_code": 200, "payload": {}})
    result = service.run_action(action_key=action_key, params={}, user=actor)
    assert executor.calls == []
    assert result["response"]["status_code"] == 400
    assert result["outcome"] == "blocked"
    assert result["view_model"]["status"] == "需要参数"
    assert result["user_error_code"] == "TUI_TASK_SCOPE_INVALID"
    assert [item["key"] for item in result["missing_fields"]] == [field]
