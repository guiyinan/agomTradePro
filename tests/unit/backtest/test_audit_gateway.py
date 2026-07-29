"""Behavioral contracts for the Backtest-to-Audit application gateway."""

import pytest

from apps.backtest.application import audit_gateway


def test_audit_gateway_fails_closed_without_registered_owner(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Backtests must not silently skip attribution when Audit is unavailable."""
    monkeypatch.setattr(audit_gateway, "_generator", None)

    with pytest.raises(RuntimeError, match="not registered"):
        audit_gateway.generate_attribution_report_for_backtest(backtest_id=7)


def test_audit_gateway_delegates_exact_payload_to_registered_owner(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The consumer gateway preserves the owning Audit provider contract."""
    calls: list[dict[str, object]] = []
    monkeypatch.setattr(audit_gateway, "_generator", None)
    audit_gateway.register_audit_report_generator(
        lambda **kwargs: calls.append(kwargs) or {"report_id": 17}
    )

    result = audit_gateway.generate_attribution_report_for_backtest(
        backtest_id=7,
        source="unit-test",
    )

    assert result == {"report_id": 17}
    assert calls == [{"backtest_id": 7, "source": "unit-test"}]
