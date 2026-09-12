"""A confirmed TUI action forwards one transport identity outside business fields."""

from types import SimpleNamespace

import pytest

from apps.terminal.application.tui_workbench import TuiWorkbenchService
from tests.unit.test_tui_workbench import (
    FakeAuditRepository,
    FakeMetadataRepository,
    _metadata_payload,
)


def test_confirmed_action_keeps_key_outside_params_and_body():
    payload = _metadata_payload()
    action = payload["actions"][0]
    action.update(
        method="POST",
        risk="write",
        effect="create",
        confirmation_required=True,
        audit_required=True,
    )
    calls = []

    class Executor:
        def execute(self, **kwargs):
            calls.append(kwargs)
            return {"status_code": 201, "payload": {"success": True, "items": []}}

    user = SimpleNamespace(
        is_authenticated=True, is_superuser=True, is_staff=True, pk=1, username="owner"
    )
    service = TuiWorkbenchService(
        metadata_repository=FakeMetadataRepository(payload),
        action_executor=Executor(),
        audit_repository=FakeAuditRepository(),
    )
    first = service.run_action(
        action_key=action["key"], params={}, user=user, idempotency_key="submission-1"
    )
    assert first["confirmation_required"] is True
    assert calls == []
    service.run_action(
        action_key=action["key"],
        params={},
        user=user,
        confirmed=True,
        idempotency_key="submission-1",
    )
    assert len(calls) == 1
    assert calls[0]["idempotency_key"] == "submission-1"
    assert calls[0]["params"] == {}
    assert calls[0]["body"] == {}


@pytest.mark.parametrize("key", ["", "two words", "a" * 193])
def test_action_rejects_invalid_identity_at_application_entry(key):
    service = TuiWorkbenchService(metadata_repository=FakeMetadataRepository())
    with pytest.raises(ValueError, match="idempotency"):
        service.run_action(action_key="sample.list", params={}, user=None, idempotency_key=key)
