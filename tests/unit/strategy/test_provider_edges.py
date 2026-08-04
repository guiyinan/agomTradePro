"""Strategy provider fallback and normalization contracts."""

from __future__ import annotations

from datetime import date
from types import SimpleNamespace

import pytest

from apps.strategy.infrastructure.providers import (
    BrokerExecutionAdapter,
    DjangoAssetNameResolver,
    DjangoMacroDataProvider,
    DjangoPortfolioDataProvider,
    DjangoRegimeProvider,
    ExecutionAdapterFactory,
    PaperExecutionAdapter,
    _to_legacy_regime_code,
)


def test_macro_and_regime_providers_normalize_application_payloads(monkeypatch) -> None:
    """Macro and Regime providers convert values and preserve fail-safe defaults."""
    from apps.regime.application import current_regime

    monkeypatch.setattr(
        "apps.strategy.infrastructure.providers.get_macro_indicator_value",
        lambda code: 50.2 if code == "PMI" else None,
    )
    monkeypatch.setattr(
        "apps.strategy.infrastructure.providers.list_latest_published_macro_values",
        lambda limit: [{"indicator_code": "PMI", "value": 50.2}],
    )
    macro = DjangoMacroDataProvider()
    assert macro.get_indicator("PMI") == 50.2
    assert macro.get_indicator("MISSING") is None
    assert macro.get_all_indicators() == {"PMI": 50.2}

    monkeypatch.setattr(
        current_regime,
        "resolve_current_regime",
        lambda: SimpleNamespace(
            dominant_regime="Overheat",
            confidence=0.8,
            observed_at=date(2026, 7, 24),
        ),
    )
    regime = DjangoRegimeProvider().get_current_regime()
    assert regime["dominant_regime_code"] == "HG"
    assert regime["date"] == "2026-07-24"
    assert _to_legacy_regime_code("Custom") == "Custom"

    monkeypatch.setattr(
        current_regime,
        "resolve_current_regime",
        lambda: (_ for _ in ()).throw(RuntimeError("offline")),
    )
    assert DjangoRegimeProvider().get_current_regime()["dominant_regime"] == "Recovery"


def test_portfolio_and_asset_name_providers_convert_and_fail_closed(monkeypatch) -> None:
    """Portfolio numbers normalize to floats and name resolution ignores empty codes."""
    position = SimpleNamespace(
        asset_code="000001.SZ",
        asset_name="平安银行",
        quantity=100,
        avg_cost="10.5",
        current_price="11.0",
        market_value="1100",
        asset_type="equity",
    )
    facade = SimpleNamespace(
        get_positions=lambda portfolio_id: [position],
        get_cash=lambda portfolio_id: "9000.5",
    )
    provider = DjangoPortfolioDataProvider()
    provider._facade = facade
    assert provider.get_positions(1)[0]["market_value"] == 1100.0
    assert provider.get_cash(1) == 9000.5

    provider._facade = SimpleNamespace(
        get_positions=lambda portfolio_id: (_ for _ in ()).throw(RuntimeError("offline")),
        get_cash=lambda portfolio_id: (_ for _ in ()).throw(RuntimeError("offline")),
    )
    assert provider.get_positions(1) == []
    assert provider.get_cash(1) == 0.0

    resolver = DjangoAssetNameResolver()
    assert resolver.resolve_asset_names([]) == {}
    from apps.asset_analysis.application import asset_name_service

    monkeypatch.setattr(
        asset_name_service,
        "resolve_asset_names",
        lambda codes: {code: f"name-{code}" for code in codes},
    )
    assert resolver.resolve_asset_names(["000001.SZ"]) == {"000001.SZ": "name-000001.SZ"}


def test_execution_adapter_factory_enforces_mode_and_broker_requirements() -> None:
    """Execution mode factory returns explicit paper/broker adapters and rejects ambiguity."""
    paper = ExecutionAdapterFactory.create_adapter("paper", portfolio_id=1)
    assert isinstance(paper, PaperExecutionAdapter)
    assert paper.get_name() == "paper" and not paper.is_live()
    assert paper.query_order_status("missing")["status"] == "not_found"
    assert paper.cancel_order("missing") is False

    with pytest.raises(ValueError, match="broker_config"):
        ExecutionAdapterFactory.create_adapter("broker", portfolio_id=1)
    broker = ExecutionAdapterFactory.create_adapter(
        "broker",
        portfolio_id=1,
        broker_config={"broker_type": "qmt", "sandbox": False},
    )
    assert isinstance(broker, BrokerExecutionAdapter)
    assert broker.get_name() == "broker_qmt" and broker.is_live()
    with pytest.raises(NotImplementedError):
        broker.query_order_status("order")
    with pytest.raises(NotImplementedError):
        broker.cancel_order("order")
    with pytest.raises(ValueError, match="Unknown execution mode"):
        ExecutionAdapterFactory.create_adapter("unknown", portfolio_id=1)
