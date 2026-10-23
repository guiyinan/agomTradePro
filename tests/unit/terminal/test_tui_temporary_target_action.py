"""Keep target text inside the confirmed, idempotent account-preview action."""

from __future__ import annotations

from copy import deepcopy
from types import SimpleNamespace
from typing import Any

import pytest

from apps.terminal.application.tui_workbench import TuiWorkbenchService
from apps.terminal.infrastructure.tui_metadata_runtime_injection_task_focus import (
    RUNTIME_TASK_FOCUS_ACTIONS,
)


class _MetadataFixture:
    """Provide the owning screen needed for the post-confirmation result context."""

    def load_published(self, registry_key: str = "default") -> dict[str, Any]:
        assert registry_key == "default"
        return {
            "screens": [
                {
                    "key": "task.account-inspection",
                    "user_experience": {
                        "empty_state_hint": "选择本人账户并填写可选目标。",
                        "next_step_hint": "核对只读预览结果。",
                    },
                }
            ]
        }


class _Executor:
    """Record the actual executor request and its separate idempotency identity."""

    def __init__(self) -> None:
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
        return {"status_code": 400, "payload": {"success": False, "error": "fixture"}}


def test_temporary_target_uses_existing_confirmation_and_idempotency_boundary(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    action = deepcopy(
        next(item for item in RUNTIME_TASK_FOCUS_ACTIONS if item["key"] == "account-inspection.run")
    )
    actor = SimpleNamespace(
        pk=1,
        id=1,
        username="temporary-target-owner",
        is_authenticated=True,
        is_active=True,
        is_staff=False,
    )
    executor = _Executor()
    service = TuiWorkbenchService(
        metadata_repository=_MetadataFixture(),
        action_executor=executor,
    )
    monkeypatch.setattr(service, "_action_by_key", lambda key, *, user=None: deepcopy(action))
    monkeypatch.setattr(service, "_allowed_runtime_risks", lambda _user: {"read", "write"})
    monkeypatch.setattr(service, "_ensure_tui_audit_sink", lambda _action: None)
    monkeypatch.setattr(service, "_append_tui_audit", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        service,
        "_action_payload",
        lambda selected, **kwargs: {
            "key": selected["key"],
            "label": selected["label"],
            "risk": selected["risk"],
        },
    )
    target_text = "600000.SH,0\n000001.SZ,90.000001"
    params = {"account_id": 8, "temporary_target_weights": target_text}

    confirmation = service.run_action(
        action_key="account-inspection.run",
        params=params,
        user=actor,
        idempotency_key="temporary-preview-8-1",
    )
    assert confirmation["confirmation_required"] is True
    assert executor.calls == []

    service.run_action(
        action_key="account-inspection.run",
        params=params,
        user=actor,
        confirmed=True,
        idempotency_key="temporary-preview-8-1",
    )

    assert len(executor.calls) == 1
    call = executor.calls[0]
    assert call["method"] == "POST"
    assert call["endpoint"] == "/api/account/accounts/8/inspections/run/"
    assert call["params"] == {}
    assert call["body"] == {"temporary_target_weights": target_text}
    assert call["idempotency_key"] == "temporary-preview-8-1"
