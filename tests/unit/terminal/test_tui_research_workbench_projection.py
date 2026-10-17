"""Workbench projection and live-target permission contracts for research tasks."""

from __future__ import annotations

from copy import deepcopy
from types import SimpleNamespace
from typing import Any

from apps.terminal.application.tui_workbench import TuiWorkbenchService

_RESEARCH_PAYLOAD: dict[str, Any] = {
    "status": "fresh",
    "outcome": "success",
    "stock_code": "600000.SH",
    "identity": {
        "status": "fresh",
        "required": True,
        "data": {
            "asset_type": "stock",
            "code": "600000.SH",
            "name": "示例股份",
            "currency": "CNY",
        },
        "must_not_use_for_decision": False,
        "block_reason_code": "",
    },
    "sections": {
        key: {
            "status": "fresh",
            "required": key not in {"news", "capital_flows"},
            "data": {},
            "must_not_use_for_decision": False,
            "block_reason_code": "",
        }
        for key in (
            "latest_quote",
            "price_history",
            "valuation",
            "financials",
            "news",
            "capital_flows",
        )
    },
    "reliability": {
        "status": "fresh",
        "source": "agomtradepro_api",
        "must_not_use_for_decision": False,
    },
    "must_not_use_for_decision": False,
}


class _Metadata:
    def __init__(self, *, include_target: bool = True, target_audience: str = "authenticated"):
        actions: list[dict[str, Any]] = [
            {
                "key": "equity.research-snapshot",
                "label": "单标的研究快照",
                "screen_key": "task.asset-research",
                "module_key": "investment-research",
                "intent": "research_single_equity_snapshot",
                "method": "GET",
                "endpoint": "/api/equity/research-snapshot/<str:stock_code>/",
                "risk": "read",
                "audience": "authenticated",
                "view_type": "detail",
                "raw_debug": False,
                "fields": [
                    {
                        "key": "stock_code",
                        "label": "股票名称或代码",
                        "binding": "path",
                        "required": True,
                        "value_type": "string",
                    }
                ],
                "view_model": {"kind": "detail"},
            },
        ]
        if include_target:
            actions.append(
                {
                    "key": "equity.valuation-overview",
                    "label": "个股估值与财务摘要",
                    "screen_key": "research.asset-lab",
                    "module_key": "investment-research",
                    "intent": "inspect_equity_valuation_overview",
                    "method": "GET",
                    "endpoint": "/api/equity/valuation/<str:stock_code>/",
                    "risk": "read",
                    "audience": target_audience,
                    "view_type": "detail",
                    "fields": [
                        {
                            "key": "stock_code",
                            "label": "股票代码",
                            "binding": "path",
                            "required": True,
                            "value_type": "string",
                        }
                    ],
                    "view_model": {"kind": "detail"},
                }
            )
        self.payload = {
            "version": "tui-workbench.v2",
            "registry_key": "default",
            "default_screen": "task.asset-research",
            "groups": [{"key": "research", "label": "研究"}],
            "modules": [
                {
                    "key": "investment-research",
                    "label": "投资研究",
                    "group": "research",
                    "summary": "研究",
                }
            ],
            "screens": [
                {
                    "key": "task.asset-research",
                    "label": "研究标的",
                    "module_key": "investment-research",
                    "group": "research",
                    "audience": "authenticated",
                    "summary": "单标的研究",
                    "view_type": "detail",
                    "default_action_key": "equity.research-snapshot",
                    "user_experience": {
                        "empty_state_hint": "输入股票名称或代码，按“开始研究”读取材料。",
                        "next_step_hint": "展开证据核对来源和时间。",
                    },
                },
                {
                    "key": "research.asset-lab",
                    "label": "资产研究",
                    "module_key": "investment-research",
                    "group": "research",
                    "audience": "authenticated",
                    "summary": "专业研究",
                    "view_type": "datagrid",
                    "default_action_key": "equity.valuation-overview",
                },
            ],
            "actions": actions,
            "principles": [],
        }

    def load_published(self, registry_key: str = "default") -> dict[str, Any]:
        del registry_key
        return deepcopy(self.payload)


class _Executor:
    def __init__(self, payload: dict[str, Any], status_code: int = 200) -> None:
        self.payload = payload
        self.status_code = status_code
        self.before_return: Any = None

    def execute(self, **_: Any) -> dict[str, Any]:
        if callable(self.before_return):
            self.before_return()
        return {"status_code": self.status_code, "payload": deepcopy(self.payload)}


def _user(*, admin: bool = False) -> SimpleNamespace:
    return SimpleNamespace(
        id=1,
        pk=1,
        is_authenticated=True,
        is_active=True,
        is_staff=admin,
        is_superuser=admin,
        rbac_role="admin" if admin else "user",
    )


def _service(metadata: _Metadata, executor: _Executor) -> TuiWorkbenchService:
    return TuiWorkbenchService(
        metadata_repository=metadata,
        action_executor=executor,
    )


def test_research_action_projects_owner_outcome_and_canonical_next_step() -> None:
    metadata = _Metadata()
    executor = _Executor(_RESEARCH_PAYLOAD)
    result = _service(metadata, executor).run_action(
        action_key="equity.research-snapshot",
        params={"stock_code": "request-path-value"},
        user=_user(),
    )

    assert result["outcome"] == "success"
    assert result["view_model"]["owner_status"] == "fresh"
    assert result["view_model"]["outcome"] == "success"
    assert result["view_model"]["next_steps"][0]["params"] == {"stock_code": "600000.SH"}
    assert "_research_professional_target" not in result["action"]


def test_transport_failure_uses_bounded_generic_projection() -> None:
    result = _service(
        _Metadata(), _Executor({"detail": "strict gate unavailable"}, 503)
    ).run_action(
        action_key="equity.research-snapshot",
        params={"stock_code": "600000.SH"},
        user=_user(),
    )

    assert result["response"]["status_code"] == 503
    assert result["outcome"] == "failed"
    assert result["view_model"]["kind"] == "detail"
    assert result["view_model"]["next_steps"] == []


def test_research_action_preserves_restrictions_and_original_source_time() -> None:
    """Consume owner outcomes without promoting stale or partial evidence."""

    for status, outcome, restricted in (
        ("partial", "partial", False),
        ("blocked", "blocked", True),
    ):
        payload = deepcopy(_RESEARCH_PAYLOAD)
        payload.update(status=status, outcome=outcome, must_not_use_for_decision=restricted)
        payload["sections"]["latest_quote"].update(
            status="blocked" if restricted else "fresh",
            must_not_use_for_decision=restricted,
            data={
                "current_price": 0,
                "currency": "CNY",
                "snapshot_at": "2001-01-01T00:00:00+00:00",
            },
        )
        result = _service(_Metadata(), _Executor(payload)).run_action(
            action_key="equity.research-snapshot",
            params={"stock_code": "600000.SH"},
            user=_user(),
        )
        view = result["view_model"]
        assert result["outcome"] == view["outcome"] == outcome
        assert view["must_not_use_for_decision"] is restricted
        quote = next(section for section in view["sections"] if section["key"] == "latest_quote")
        assert quote["must_not_use_for_decision"] is restricted
        assert any(
            time["field"] == "snapshot_at" and time["value"] == "2001-01-01T00:00:00+00:00"
            for time in quote["source_times"]
        )


def test_target_absent_or_forbidden_has_no_professional_link() -> None:
    absent = _service(_Metadata(include_target=False), _Executor(_RESEARCH_PAYLOAD)).run_action(
        action_key="equity.research-snapshot",
        params={"stock_code": "600000.SH"},
        user=_user(),
    )
    forbidden = _service(
        _Metadata(target_audience="admin"), _Executor(_RESEARCH_PAYLOAD)
    ).run_action(
        action_key="equity.research-snapshot",
        params={"stock_code": "600000.SH"},
        user=_user(),
    )

    assert absent["view_model"]["next_steps"] == []
    assert forbidden["view_model"]["next_steps"] == []


def test_target_requires_an_active_authenticated_actor() -> None:
    anonymous = _user()
    anonymous.is_authenticated = False
    inactive = _user()
    inactive.is_active = False

    for actor in (None, anonymous, inactive):
        result = _service(_Metadata(), _Executor(_RESEARCH_PAYLOAD)).run_action(
            action_key="equity.research-snapshot",
            params={"stock_code": "600000.SH"},
            user=actor,
        )
        assert result["view_model"]["next_steps"] == []


def test_target_rejects_unsafe_action_and_field_metadata() -> None:
    unsafe_actions = (
        {"method": "POST"},
        {"risk": "write"},
        {"confirmation_required": True},
        {"requires_password": True},
        {"sensitive_level": "high"},
    )
    for override in unsafe_actions:
        metadata = _Metadata()
        target = metadata.payload["actions"][1]
        target.update(override)
        result = _service(metadata, _Executor(_RESEARCH_PAYLOAD)).run_action(
            action_key="equity.research-snapshot",
            params={"stock_code": "600000.SH"},
            user=_user(),
        )
        assert result["view_model"]["next_steps"] == []

    for input_type in ("hidden", "password", "file"):
        metadata = _Metadata()
        metadata.payload["actions"][1]["fields"][0]["input_type"] = input_type
        result = _service(metadata, _Executor(_RESEARCH_PAYLOAD)).run_action(
            action_key="equity.research-snapshot",
            params={"stock_code": "600000.SH"},
            user=_user(),
        )
        assert result["view_model"]["next_steps"] == []


def test_target_does_not_copy_unsafe_owner_codes_into_next_steps() -> None:
    for stock_code in ("../secret", "600000.SH?x=1", "600 000.SH", "600000.SH/"):
        payload = deepcopy(_RESEARCH_PAYLOAD)
        payload["stock_code"] = stock_code
        result = _service(_Metadata(), _Executor(payload)).run_action(
            action_key="equity.research-snapshot",
            params={"stock_code": "600000.SH"},
            user=_user(),
        )
        assert result["view_model"]["next_steps"] == []


def test_target_revoked_before_projection_is_not_exposed() -> None:
    metadata = _Metadata()
    executor = _Executor(_RESEARCH_PAYLOAD)
    service = _service(metadata, executor)

    def revoke_target() -> None:
        if service._action_index is not None:
            service._action_index.pop("equity.valuation-overview", None)

    executor.before_return = revoke_target
    result = service.run_action(
        action_key="equity.research-snapshot",
        params={"stock_code": "600000.SH"},
        user=_user(),
    )

    assert result["view_model"]["next_steps"] == []


def test_nonresearch_action_does_not_receive_research_projection() -> None:
    metadata = _Metadata()
    metadata.payload["actions"].append(
        {
            "key": "other.read-only",
            "label": "其他读取",
            "screen_key": "research.asset-lab",
            "module_key": "investment-research",
            "intent": "other",
            "method": "GET",
            "endpoint": "/api/other/",
            "risk": "read",
            "audience": "authenticated",
            "view_type": "detail",
            "fields": [],
            "view_model": {"kind": "detail"},
        }
    )
    result = _service(metadata, _Executor({"value": "unchanged"})).run_action(
        action_key="other.read-only",
        params={},
        user=_user(),
    )

    assert result["view_model"]["next_steps"] == []
    assert result["view_model"]["fields"]
