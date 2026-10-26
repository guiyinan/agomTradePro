"""Static and pure view-model checks for the M1 owner support actions."""

from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import pytest

from apps.terminal.application.tui_m1_risk_policy_result import (
    project_m1_risk_policy_mutation_result,
)
from apps.terminal.application.tui_workbench import TuiWorkbenchService
from apps.terminal.application.tui_workbench_catalog import TuiWorkbenchCatalogMixin
from apps.terminal.domain.interfaces import TuiActionExecutor, TuiMetadataRepository
from apps.terminal.infrastructure.tui_metadata_runtime_injection_task_focus import (
    RUNTIME_TASK_FOCUS_ACTIONS,
)


class _AccountOptionCatalog(TuiWorkbenchCatalogMixin):
    """Provide deterministic options when exercising the existing account picker."""

    def __init__(self, options: list[dict[str, Any]]) -> None:
        self.options = options

    def _account_options_for_user(self, user: Any | None) -> list[dict[str, Any]]:
        return list(self.options)


def _action_map() -> dict[str, dict[str, Any]]:
    return {str(action["key"]): action for action in RUNTIME_TASK_FOCUS_ACTIONS}


def _publish_payload(*, strategy_binding: dict[str, object]) -> dict[str, object]:
    return {
        "risk_policy_version": "a146184d-4f6e-42f2-b0e7-d20a80c8a92c",
        "account_id": 8,
        "effective_from": "2027-02-01T09:00:00+08:00",
        "effective_until": "2027-03-01T09:00:00+08:00",
        "known_at": "2027-01-30T08:10:00+08:00",
        "legacy_rule_version": None,
        "publication_status": "published",
        "source_binding": strategy_binding,
        "risk_falsification": {
            "schema_version": "m1-risk-falsification.v1",
            "status": "not_evaluated",
            "conditions": [
                {
                    "dimension": "max_single_position",
                    "applicability": "applicable",
                    "threshold_pct": "20.000",
                    "owner_reason": None,
                    "predicate": "target_single_position_pct <= limit_pct",
                },
                {
                    "dimension": "max_total_position",
                    "applicability": "not_applicable",
                    "threshold_pct": None,
                    "owner_reason": "账户没有统一估值口径",
                    "predicate": "internal",
                },
                {
                    "dimension": "max_stop_loss",
                    "applicability": "unknown",
                    "threshold_pct": None,
                    "owner_reason": None,
                    "predicate": "internal",
                },
            ],
        },
    }


def test_mutations_are_confirmed_support_actions_on_existing_preview_task() -> None:
    actions = _action_map()
    publish = actions["account-inspection.m1-risk-policy.publish"]
    revoke = actions["account-inspection.m1-risk-policy.revoke"]
    preview = actions["account-inspection.run"]

    assert preview["screen_key"] == "task.account-inspection"
    assert preview["task_tier"] == "primary"
    primary_keys = [
        str(action["key"])
        for action in RUNTIME_TASK_FOCUS_ACTIONS
        if action.get("screen_key") == "task.account-inspection"
        and action.get("task_tier") == "primary"
    ]
    assert primary_keys == ["account-inspection.run"]
    ia_registry = json.loads(
        Path("config/tui/ia/tui_information_architecture.v1.json").read_text(encoding="utf-8")
    )
    configured_screens = [
        screen
        for screen in [*ia_registry["published_screens"], *ia_registry["runtime_screens"]]
        if screen["key"] == "task.account-inspection"
    ]
    assert len(configured_screens) == 1
    assert configured_screens[0]["default_action_key"] == "account-inspection.run"
    for action in (publish, revoke):
        assert action["screen_key"] == "task.account-inspection"
        assert action["task_tier"] == "support"
        assert action["method"] == "POST"
        assert action["risk"] == "write"
        assert action["confirmation_required"] is True
        assert action["audit_required"] is True
        assert action["session_auth_required"] is True
        assert action["raw_debug"] is False

    assert "当前可核验的策略和仓位规则" in publish["description"]
    assert "账户通用" not in publish["description"]
    assert publish["endpoint"] == (
        "/api/account/accounts/<int:account_id>/m1-risk-policy-revisions/"
    )
    assert revoke["endpoint"].endswith("<uuid:risk_policy_version>/revoke/")


def test_mutations_reuse_the_existing_authenticated_owner_account_picker() -> None:
    actions = _action_map()
    options = [
        {
            "value": 8,
            "label": "本人模拟账户 · simulated · #8",
            "account_name": "本人模拟账户",
        }
    ]
    catalog = _AccountOptionCatalog(options)

    for action_key in (
        "account-inspection.m1-risk-policy.publish",
        "account-inspection.m1-risk-policy.revoke",
    ):
        action = actions[action_key]
        field = deepcopy(next(field for field in action["fields"] if field["key"] == "account_id"))
        catalog._decorate_dynamic_field_options(field, action=action, user=object())
        assert field["input_type"] == "select"
        assert field["options"] == [
            {"value": "", "label": "请选择本人账户"},
            *options,
        ]


def test_publish_controls_are_flat_explicit_and_have_no_business_defaults() -> None:
    action = _action_map()["account-inspection.m1-risk-policy.publish"]
    fields = {str(field["key"]): field for field in action["fields"]}

    for dimension in ("max_single_position", "max_total_position", "max_stop_loss"):
        state = fields[f"{dimension}_applicability"]
        limit = fields[f"{dimension}_limit_pct"]
        not_applicable_reason = fields[f"{dimension}_not_applicable_reason"]
        assert state["input_type"] == "select"
        assert state["required"] is True
        assert "default" not in state
        assert [option["value"] for option in state["options"]] == [
            "",
            "applicable",
            "not_applicable",
            "unknown",
        ]
        assert limit["input_type"] == "text"
        assert limit["value_type"] == "decimal"
        assert limit["unit"] == "%"
        assert "default" not in limit
        assert not_applicable_reason["required"] is False
        assert "default" not in not_applicable_reason

    assert fields["effective_from"]["value_type"] == "datetime"
    assert fields["effective_until"]["value_type"] == "datetime"
    assert "时区" in fields["effective_from"]["label"]
    assert "strategy_id" not in fields
    assert all(field.get("value_type") != "object" for field in action["fields"])


def test_publish_projection_shows_server_times_and_exact_strategy_binding() -> None:
    payload = _publish_payload(
        strategy_binding={
            "strategy_selection_state": "configured",
            "strategy_id": 3,
            "strategy_version": 8,
            "position_rule_id": 12,
        }
    )
    result = project_m1_risk_policy_mutation_result(
        "account-inspection.m1-risk-policy.publish",
        payload,
        http_status=201,
    )
    fields = {field["key"]: field for field in result["fields"]}

    assert result["status"] == "已发布"
    assert fields["risk_policy_version"]["presentation"] == "copyable"
    assert fields["effective_from"]["value"] == "2027-02-01T09:00:00+08:00"
    assert fields["effective_until"]["value"] == "2027-03-01T09:00:00+08:00"
    assert fields["known_at"]["value"] == "2027-01-30T08:10:00+08:00"
    assert fields["strategy_context"]["value"] == (
        "当前策略已识别（策略编号 3；策略版本 8；仓位规则编号 12）"
    )
    assert fields["max_single_position"]["value"] == "适用：20%"
    assert fields["max_total_position"]["value"] == "不适用：账户没有统一估值口径"
    assert fields["max_stop_loss"]["value"] == "未知（当前将阻止买入）"
    assert "source_binding" not in str(result)
    assert "predicate" not in str(result)
    assert "m1-risk-falsification.v1" not in str(result)


def test_actual_workbench_result_branch_uses_the_owner_projection() -> None:
    service = TuiWorkbenchService(metadata_repository=cast(TuiMetadataRepository, object()))
    payload = _publish_payload(
        strategy_binding={
            "strategy_selection_state": "configured",
            "strategy_id": 3,
            "strategy_version": 8,
            "position_rule_id": 12,
        }
    )

    result = service._to_view_model(
        action={
            "key": "account-inspection.m1-risk-policy.publish",
            "label": "发布账户风险约束",
            "screen_key": "task.account-inspection",
        },
        payload=payload,
        status_code=201,
    )

    assert result["kind"] == "detail"
    assert result["status"] == "已发布"
    assert "source_binding" not in str(result)


def test_publish_projection_names_confirmed_unconfigured_strategy_state() -> None:
    payload = _publish_payload(
        strategy_binding={
            "strategy_selection_state": "confirmed_unconfigured",
            "strategy_id": None,
            "strategy_version": None,
            "position_rule_id": None,
        }
    )
    result = project_m1_risk_policy_mutation_result(
        "account-inspection.m1-risk-policy.publish",
        payload,
        http_status=201,
    )
    fields = {field["key"]: field for field in result["fields"]}

    assert result["outcome"] == "success"
    assert fields["strategy_context"]["value"] == "提交时已核验：当前账户未配置策略"


def test_publish_projection_does_not_invent_strategy_name_when_source_is_unavailable() -> None:
    payload = _publish_payload(
        strategy_binding={
            "strategy_selection_state": "unavailable",
            "strategy_id": None,
            "strategy_version": None,
            "position_rule_id": None,
        }
    )
    result = project_m1_risk_policy_mutation_result(
        "account-inspection.m1-risk-policy.publish",
        payload,
        http_status=201,
    )
    fields = {field["key"]: field for field in result["fields"]}

    assert result["outcome"] == "partial"
    assert fields["strategy_context"]["value"] == "提交时无法核验当前策略或仓位规则"
    assert "strategy_name" not in str(result)
    assert result["next_steps"]


def test_publish_projection_blocks_naive_times_and_malformed_binding() -> None:
    payload = _publish_payload(
        strategy_binding={
            "strategy_selection_state": "configured",
            "strategy_id": None,
            "strategy_version": 8,
            "position_rule_id": 12,
        }
    )
    payload["effective_from"] = "2027-02-01T09:00:00"
    result = project_m1_risk_policy_mutation_result(
        "account-inspection.m1-risk-policy.publish",
        payload,
        http_status=201,
    )

    assert result["outcome"] == "blocked"
    assert result["fields"] == []


def test_revoke_projection_shows_exact_version_time_and_reason() -> None:
    payload = {
        "risk_policy_version": "a146184d-4f6e-42f2-b0e7-d20a80c8a92c",
        "account_id": 8,
        "revoked_at": "2027-02-02T10:00:00+08:00",
        "revoked_by_user_id": 44,
        "revocation_reason": "账户风险偏好发生变化",
        "revocation_status": "revoked",
    }
    result = project_m1_risk_policy_mutation_result(
        "account-inspection.m1-risk-policy.revoke",
        payload,
        http_status=200,
        requested_params={
            "account_id": 8,
            "risk_policy_version": "a146184d-4f6e-42f2-b0e7-d20a80c8a92c",
        },
    )
    fields = {field["key"]: field for field in result["fields"]}

    assert result["status"] == "已撤销"
    assert fields["risk_policy_version"]["presentation"] == "copyable"
    assert fields["revoked_at"]["value"] == "2027-02-02T10:00:00+08:00"
    assert fields["revocation_reason"]["value"] == "账户风险偏好发生变化"
    assert "revoked_by_user_id" not in str(result)


@pytest.mark.parametrize(
    "failure",
    (
        "missing_version",
        "missing_account",
        "missing_time",
        "missing_actor",
        "missing_reason",
        "missing_status",
        "bad_uuid",
        "naive_time",
        "boolean_actor",
        "zero_account",
        "zero_actor",
        "wrong_status",
        "version_mismatch",
        "account_mismatch",
        "empty_reason",
        "unsafe_reason",
        "missing_requested_params",
        "missing_requested_account",
        "missing_requested_version",
        "bad_requested_uuid",
        "non_success_status",
    ),
)
def test_revoke_projection_blocks_incomplete_invalid_or_mismatched_receipts(
    failure: str,
) -> None:
    payload: dict[str, object] = {
        "risk_policy_version": "a146184d-4f6e-42f2-b0e7-d20a80c8a92c",
        "account_id": 8,
        "revoked_at": "2027-02-02T10:00:00+08:00",
        "revoked_by_user_id": 44,
        "revocation_reason": "账户风险偏好发生变化",
        "revocation_status": "revoked",
    }
    requested_params: dict[str, object] | None = {
        "account_id": "8",
        "risk_policy_version": "a146184d-4f6e-42f2-b0e7-d20a80c8a92c",
    }
    http_status = 200
    if failure.startswith("missing_") and not failure.startswith("missing_requested_"):
        field_name = {
            "missing_version": "risk_policy_version",
            "missing_account": "account_id",
            "missing_time": "revoked_at",
            "missing_actor": "revoked_by_user_id",
            "missing_reason": "revocation_reason",
            "missing_status": "revocation_status",
        }[failure]
        payload.pop(field_name)
    elif failure == "bad_uuid":
        payload["risk_policy_version"] = "not-a-uuid"
    elif failure == "naive_time":
        payload["revoked_at"] = "2027-02-02T10:00:00"
    elif failure == "boolean_actor":
        payload["revoked_by_user_id"] = True
    elif failure == "zero_account":
        payload["account_id"] = 0
    elif failure == "zero_actor":
        payload["revoked_by_user_id"] = 0
    elif failure == "wrong_status":
        payload["revocation_status"] = "published"
    elif failure == "version_mismatch":
        payload["risk_policy_version"] = "b146184d-4f6e-42f2-b0e7-d20a80c8a92c"
    elif failure == "account_mismatch":
        payload["account_id"] = 9
    elif failure == "empty_reason":
        payload["revocation_reason"] = "   "
    elif failure == "unsafe_reason":
        payload["revocation_reason"] = "撤销失败\ninternal error: hidden"
    elif failure == "missing_requested_params":
        requested_params = None
    elif failure == "missing_requested_account" and requested_params is not None:
        requested_params.pop("account_id")
    elif failure == "missing_requested_version" and requested_params is not None:
        requested_params.pop("risk_policy_version")
    elif failure == "bad_requested_uuid" and requested_params is not None:
        requested_params["risk_policy_version"] = "not-a-uuid"
    elif failure == "non_success_status":
        http_status = 409

    result = project_m1_risk_policy_mutation_result(
        "account-inspection.m1-risk-policy.revoke",
        payload,
        http_status=http_status,
        requested_params=requested_params,
    )

    assert result["outcome"] == "blocked"
    assert result["fields"] == []
    assert "revoked_by_user_id" not in str(result)
    assert "账户风险偏好发生变化" not in str(result)
    assert "internal error: hidden" not in str(result)


_M1_REVOKE_ACTION_KEY = "account-inspection.m1-risk-policy.revoke"
_M1_REVOKE_VERSION = "a146184d-4f6e-42f2-b0e7-d20a80c8a92c"
_M1_REVOKE_REASON = "风险边界调整"


def _run_m1_risk_action(
    payload: dict[str, Any],
    *,
    action_key: str = _M1_REVOKE_ACTION_KEY,
    status_code: int = 200,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    action = deepcopy(_action_map()[action_key])

    class FakeMetadataRepository:
        def load_published(self, registry_key: str = "default") -> dict[str, Any]:
            return {
                "actions": [deepcopy(action)],
                "screens": [{"key": action["screen_key"]}],
            }

    class RecordingExecutor:
        def __init__(self) -> None:
            self.calls: list[dict[str, Any]] = []

        def execute(self, **kwargs: Any) -> dict[str, Any]:
            self.calls.append(dict(kwargs))
            return {"status_code": status_code, "payload": deepcopy(payload)}

    executor = RecordingExecutor()
    service = TuiWorkbenchService(
        metadata_repository=cast(TuiMetadataRepository, FakeMetadataRepository()),
        action_executor=cast(TuiActionExecutor, executor),
    )
    params: dict[str, Any] = {
        "account_id": "8",
        "reason": _M1_REVOKE_REASON,
    }
    if action_key == _M1_REVOKE_ACTION_KEY:
        params["risk_policy_version"] = _M1_REVOKE_VERSION
    else:
        params.update(
            effective_from="2027-02-01T09:00:00+08:00",
            effective_until="2027-03-01T09:00:00+08:00",
            max_single_position_applicability="unknown",
            max_total_position_applicability="unknown",
            max_stop_loss_applicability="unknown",
        )
    result = service.run_action(
        action_key=action_key,
        params=params,
        user=SimpleNamespace(id=None, is_authenticated=True, is_active=True),
        confirmed=True,
    )
    return result, executor.calls


def _m1_revoke_receipt() -> dict[str, Any]:
    return {
        "risk_policy_version": _M1_REVOKE_VERSION,
        "account_id": 8,
        "revoked_at": "2027-02-02T10:00:00+08:00",
        "revoked_by_user_id": 44,
        "revocation_reason": _M1_REVOKE_REASON,
        "revocation_status": "revoked",
    }


def test_run_action_projects_a_revoke_receipt_against_the_bound_target() -> None:
    result, calls = _run_m1_risk_action(_m1_revoke_receipt())

    assert calls[0]["method"] == "POST"
    assert calls[0]["endpoint"] == (
        f"/api/account/accounts/8/m1-risk-policy-revisions/{_M1_REVOKE_VERSION}/revoke/"
    )
    assert calls[0]["params"] == {}
    assert calls[0]["body"] == {"reason": _M1_REVOKE_REASON}
    assert result["outcome"] == "success"
    assert result["view_model"]["outcome"] == "success"
    assert result["view_model"]["status"] == "已撤销"


@pytest.mark.parametrize(
    "receipt_change",
    ("different_account", "different_version", "missing_actor"),
)
def test_run_action_keeps_mismatched_or_incomplete_revoke_receipts_blocked(
    receipt_change: str,
) -> None:
    receipt = _m1_revoke_receipt()
    if receipt_change == "different_account":
        receipt["account_id"] = 9
    elif receipt_change == "different_version":
        receipt["risk_policy_version"] = "b146184d-4f6e-42f2-b0e7-d20a80c8a92c"
    else:
        receipt.pop("revoked_by_user_id")

    result, _calls = _run_m1_risk_action(receipt)

    assert result["outcome"] == "blocked"
    assert result["view_model"]["outcome"] == "blocked"
    assert result["view_model"]["fields"] == []
    assert result["view_model"]["status"] != "已撤销"


def test_run_action_does_not_report_an_invalid_publish_receipt_as_success() -> None:
    result, calls = _run_m1_risk_action(
        {}, action_key="account-inspection.m1-risk-policy.publish", status_code=201
    )

    assert len(calls) == 1
    assert calls[0]["method"] == "POST"
    assert calls[0]["endpoint"] == "/api/account/accounts/8/m1-risk-policy-revisions/"
    assert result["outcome"] == "blocked"
    assert result["view_model"]["outcome"] == "blocked"
    assert result["view_model"]["fields"] == []


def test_run_action_retains_partial_publish_when_strategy_cannot_be_verified() -> None:
    payload = _publish_payload(
        strategy_binding={
            "strategy_selection_state": "unavailable",
            "strategy_id": None,
            "strategy_version": None,
            "position_rule_id": None,
        }
    )
    result, calls = _run_m1_risk_action(
        payload, action_key="account-inspection.m1-risk-policy.publish", status_code=201
    )

    assert len(calls) == 1
    assert result["outcome"] == "partial"
    assert result["view_model"]["outcome"] == "partial"
    assert result["view_model"]["fields"]


def test_run_action_reports_a_complete_publish_receipt_as_success() -> None:
    payload = _publish_payload(
        strategy_binding={
            "strategy_selection_state": "confirmed_unconfigured",
            "strategy_id": None,
            "strategy_version": None,
            "position_rule_id": None,
        }
    )
    result, calls = _run_m1_risk_action(
        payload, action_key="account-inspection.m1-risk-policy.publish", status_code=201
    )

    assert len(calls) == 1
    assert result["outcome"] == "success"
    assert result["view_model"]["outcome"] == "success"


@pytest.mark.parametrize(
    "action_key",
    ("account-inspection.m1-risk-policy.publish", _M1_REVOKE_ACTION_KEY),
)
@pytest.mark.parametrize("status_code", (403, 500))
def test_run_action_preserves_transport_failure_for_m1_mutations(
    action_key: str, status_code: int
) -> None:
    result, calls = _run_m1_risk_action(
        {"detail": "hidden server detail"}, action_key=action_key, status_code=status_code
    )

    assert len(calls) == 1
    assert result["response"]["status_code"] == status_code
    assert result["outcome"] == "failed"
    assert result["view_model"]["outcome"] == "blocked"
    assert result["view_model"]["fields"] == []
    assert "hidden server detail" not in str(result["view_model"])


@pytest.mark.parametrize(
    "action_key",
    ("account-inspection.m1-risk-policy.publish", _M1_REVOKE_ACTION_KEY),
)
@pytest.mark.parametrize("owner_outcome", ("blocked", "failed"))
def test_run_action_preserves_owner_failure_for_m1_mutations(
    action_key: str, owner_outcome: str
) -> None:
    result, calls = _run_m1_risk_action({"outcome": owner_outcome}, action_key=action_key)

    assert len(calls) == 1
    assert result["outcome"] == owner_outcome
    assert result["view_model"]["outcome"] == "blocked"
