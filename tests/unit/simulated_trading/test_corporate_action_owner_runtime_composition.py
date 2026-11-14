"""Owner workflow routing is explicit configuration, never source or write authority."""

from datetime import UTC, datetime
from pathlib import Path

import pytest

from apps.simulated_trading import corporate_action_owner_runtime_composition as module
from core.exceptions import BusinessLogicError

_NOW = datetime(2026, 11, 14, tzinfo=UTC)


@pytest.mark.parametrize(
    "failure", [None, "missing", "provider_bool", "relative_root", "unknown", "changed"]
)
def test_runtime_requires_a_complete_stable_explicit_package(
    monkeypatch, tmp_path: Path, failure: str | None
) -> None:
    value = {
        "schema": "simulated.corporate_action.owner_workflow_runtime.v1",
        "calendar_dataset_key": "explicit.calendar",
        "statutory_provider_id": 7,
        "statutory_body_store_root": str(tmp_path),
        "deployment_region": "test",
    }
    if failure == "missing":
        value = None
    elif failure == "provider_bool":
        value["statutory_provider_id"] = True
    elif failure == "relative_root":
        value["statutory_body_store_root"] = "relative/body"
    elif failure == "unknown":
        value["implicit_tax_approval"] = True
    calls = []

    def read(**kwargs):
        assert kwargs == {
            "environment": "test",
            "definition_key": module.OWNER_CORPORATE_ACTION_WORKFLOW_RUNTIME_KEY,
            "as_of": _NOW,
        }
        calls.append(kwargs)
        return value if failure != "changed" or len(calls) == 1 else None

    monkeypatch.setattr(module, "get_active_runtime_value", read)
    monkeypatch.setattr(module.timezone, "now", lambda: _NOW)
    if failure:
        with pytest.raises(BusinessLogicError):
            module.read_owner_corporate_action_workflow_runtime(environment="test", as_of=_NOW)
    else:
        settings = module.read_owner_corporate_action_workflow_runtime(
            environment="test", as_of=_NOW
        )
        assert settings.calendar_dataset_key == "explicit.calendar"
        assert settings.statutory_provider_id == 7
        assert settings.statutory_body_store_root == tmp_path
        assert settings.deployment_region == "test"
        assert len(calls) == 2
