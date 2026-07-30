"""Safety coverage for Prompt Agent tool-provider execution."""

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from apps.prompt.application.tool_execution import create_agent_tool_registry
from apps.prompt.domain.function_registry import create_builtin_tools
from apps.prompt.infrastructure.adapters import regime_adapter as regime_adapter_module
from apps.prompt.infrastructure.adapters.regime_adapter import RegimeDataAdapter


class _FailingPortfolioProvider:
    def get_portfolio_snapshot(self, portfolio_id: int) -> object:
        del portfolio_id
        raise RuntimeError("database password=must-not-leak")


def test_provider_failure_is_redacted_before_agent_runtime_consumes_it() -> None:
    registry = create_agent_tool_registry(portfolio_provider=_FailingPortfolioProvider())

    result = registry.execute("get_portfolio_snapshot", {"portfolio_id": 7})

    assert result == {
        "error": "Tool provider call failed",
        "error_code": "TOOL_PROVIDER_CALL_FAILED",
        "method": "get_portfolio_snapshot",
        "exception_type": "RuntimeError",
    }
    assert "must-not-leak" not in str(result)


def test_regime_failure_does_not_fabricate_recovery_state(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def _fail_regime(*args: object, **kwargs: object) -> object:
        del args, kwargs
        raise RuntimeError("database password=must-not-leak")

    monkeypatch.setattr(regime_adapter_module, "resolve_current_regime", _fail_regime)
    adapter = RegimeDataAdapter()
    registry = create_builtin_tools(MagicMock(), adapter)

    assert adapter.get_current_regime() is None
    result = registry.execute("get_regime_status", {})
    assert result == {
        "error": "Regime unavailable",
        "error_code": "REGIME_UNAVAILABLE",
        "tool": "get_regime_status",
    }
    assert "Recovery" not in str(result)
    assert "must-not-leak" not in str(result)


def test_regime_adapter_preserves_missing_observation_and_decision_block(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Prompt context must not convert a missing source date into request time."""
    monkeypatch.setattr(
        regime_adapter_module,
        "resolve_current_regime",
        lambda **kwargs: SimpleNamespace(
            observed_at=None,
            dominant_regime="Unknown",
            confidence=0.0,
            must_not_use_for_decision=True,
            blocked_reason="regime_data_unavailable",
        ),
    )

    result = RegimeDataAdapter().get_current_regime()

    assert result is not None
    assert result["as_of_date"] is None
    assert result["must_not_use_for_decision"] is True
    assert result["blocked_reason"] == "regime_data_unavailable"
