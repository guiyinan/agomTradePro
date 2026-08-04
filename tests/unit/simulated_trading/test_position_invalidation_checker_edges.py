"""Boundary and failure contracts for simulated-position invalidation checks."""

from __future__ import annotations

import json
from dataclasses import replace
from datetime import date
from types import SimpleNamespace

from apps.simulated_trading.application import decision_rhythm_exit_gateway
from apps.simulated_trading.application import position_invalidation_checker as checker_module
from apps.simulated_trading.application.position_invalidation_checker import (
    PositionInvalidationChecker,
    _DataCenterMacroGateway,
    _MacroObservation,
)
from apps.simulated_trading.domain.entities import Position
from apps.simulated_trading.infrastructure.price_provider import DataCenterPriceProvider


def _position(rule: str | None = None) -> Position:
    return Position(
        account_id=1,
        asset_code="000001.SZ",
        asset_name="Ping An",
        asset_type="equity",
        quantity=100,
        available_quantity=100,
        avg_cost=10,
        total_cost=1000,
        current_price=9,
        market_value=900,
        unrealized_pnl=-100,
        unrealized_pnl_pct=-10,
        first_buy_date=date(2026, 7, 1),
        last_update_date=date(2026, 7, 24),
        invalidation_rule_json=rule,
    )


def _rule() -> str:
    return json.dumps(
        {
            "conditions": [
                {
                    "indicator_code": "CN_PMI",
                    "indicator_type": "macro",
                    "operator": "lt",
                    "threshold": 50,
                    "duration": None,
                    "compare_with": None,
                },
                {
                    "indicator_code": "CN_PMI",
                    "indicator_type": "macro",
                    "operator": "lt",
                    "threshold": 49,
                    "duration": None,
                    "compare_with": None,
                },
            ],
            "logic": "AND",
        }
    )


class _Repo:
    def __init__(self, position: Position | None) -> None:
        self.position = position
        self.checked = 0

    def get_pending_invalidation_positions(self) -> list[Position]:
        return [self.position] if self.position else []

    def get_position_by_id(self, position_id: int) -> Position | None:
        return self.position

    def mark_invalidation_checked(self, **kwargs: object) -> bool:
        self.checked += 1
        return False

    def mark_invalidated(self, **kwargs: object) -> bool:
        return True

    def count_positions_with_invalidation_rules(self) -> int:
        return 1

    def get_invalidated_position_summaries(self) -> list[dict[str, object]]:
        return [{"asset_code": "000001.SZ"}]


class _Macro:
    def __init__(self, mode: str) -> None:
        self.mode = mode
        self.latest_calls = 0

    def get_latest_by_code(self, code: str):
        self.latest_calls += 1
        if self.mode == "error":
            raise RuntimeError("macro unavailable")
        if self.mode == "missing":
            return None
        return _MacroObservation(48.0, "index", date(2026, 7, 24))

    def get_history_by_code(self, code: str, periods: int = 12):
        return [_MacroObservation(49.0, "index", date(2026, 6, 30))]


def test_single_position_rejects_absent_invalid_and_already_invalidated_rules() -> None:
    """Single-position checks fail closed before any macro read."""
    repo = _Repo(None)
    service = PositionInvalidationChecker(macro_repo=_Macro("value"), position_repo=repo)
    assert service.check_position(99) is None

    repo.position = _position()
    assert service.check_position(1) is None
    assert service._check_position(repo.position) is None
    repo.position = _position("{")
    assert service.check_position(1) is None
    repo.position = _position("[]")
    assert service.check_position(1) is None
    repo.position = replace(_position(_rule()), is_invalidated=True)
    assert service.check_position(1) is None


def test_indicator_fetch_deduplicates_and_fails_closed_on_missing_or_error() -> None:
    """Each indicator is fetched once and missing provider data stays non-triggering."""
    position = _position(_rule())
    for mode in ("missing", "error", "value"):
        macro = _Macro(mode)
        repo = _Repo(position)
        service = PositionInvalidationChecker(macro_repo=macro, position_repo=repo)
        result = service.check_position(1)
        assert result is not None
        assert macro.latest_calls == 1
        assert repo.checked == 1
        if mode == "value":
            assert result.is_invalidated is True
        else:
            assert result.is_invalidated is False
    assert service.get_positions_to_close() == [{"asset_code": "000001.SZ"}]

    high_macro = _Macro("value")
    high_macro.get_latest_by_code = lambda code: _MacroObservation(
        55.0,
        "index",
        date(2026, 7, 24),
    )
    assert (
        PositionInvalidationChecker(
            macro_repo=high_macro,
            position_repo=_Repo(position),
        ).check_all_positions()
        == []
    )


def test_data_center_gateway_and_exported_helpers(monkeypatch) -> None:
    """The compatibility gateway maps facts and exported task helpers retain shape."""
    facts = [
        SimpleNamespace(
            value=49.0,
            unit="index",
            reporting_period=date(2026, 6, 30),
        ),
        SimpleNamespace(
            value=48.0,
            unit="index",
            reporting_period=date(2026, 7, 24),
        ),
    ]
    monkeypatch.setattr(
        checker_module,
        "get_published_macro_fact_series",
        lambda code, limit: {
            "rows": [
                {
                    "indicator_code": code,
                    "reporting_period": item.reporting_period.isoformat(),
                    "value": item.value,
                    "unit": item.unit,
                }
                for item in facts
            ]
            if code == "CN_PMI"
            else [],
            "must_not_use_for_decision": False,
        },
    )
    gateway = _DataCenterMacroGateway()
    assert gateway.get_latest_by_code("missing") is None
    assert gateway.get_latest_by_code("CN_PMI").value == 48.0
    assert [item.value for item in gateway.get_history_by_code("CN_PMI")] == [48.0, 49.0]

    class _Checker:
        position_repo = SimpleNamespace(count_positions_with_invalidation_rules=lambda: 2)

        def check_all_positions(self):
            return [{"asset_code": "000001.SZ"}]

        def get_positions_to_close(self):
            return [{"asset_code": "600000.SH"}]

    monkeypatch.setattr(checker_module, "PositionInvalidationChecker", _Checker)
    assert checker_module.check_and_invalidate_positions() == {
        "checked": 2,
        "invalidated": 1,
        "positions": [{"asset_code": "000001.SZ"}],
    }
    assert checker_module.get_invalidated_positions_summary() == [{"asset_code": "600000.SH"}]

    monkeypatch.setattr(checker_module, "_DataCenterMacroGateway", lambda: object())
    monkeypatch.setattr(
        checker_module,
        "get_simulated_position_repository",
        lambda: object(),
    )
    default_checker = PositionInvalidationChecker()
    assert default_checker.macro_repo is not None
    assert default_checker.position_repo is not None


def test_exit_gateway_and_price_provider_delegate_without_hidden_state(monkeypatch) -> None:
    """Optional exit advice fails safe and all price operations delegate consistently."""
    monkeypatch.setattr(decision_rhythm_exit_gateway, "_builder", None)
    fallback = decision_rhythm_exit_gateway.build_decision_rhythm_exit_advisor()
    assert fallback.get_exit_advices(1, [], date(2026, 7, 24)) == []
    advisor = object()
    decision_rhythm_exit_gateway.register_decision_rhythm_exit_advisor_builder(lambda: advisor)
    assert decision_rhythm_exit_gateway.build_decision_rhythm_exit_advisor() is advisor

    provider = DataCenterPriceProvider.__new__(DataCenterPriceProvider)
    provider._price_service = SimpleNamespace(
        get_price=lambda **kwargs: 10.0,
        get_latest_price=lambda **kwargs: 11.0,
        require_price=lambda **kwargs: 12.0,
        require_latest_price=lambda **kwargs: 13.0,
    )
    assert provider.get_price("000001.SZ", date(2026, 7, 24)) == 10.0
    assert provider.get_latest_price("000001.SZ") == 11.0
    assert provider.require_price("000001.SZ") == 12.0
    assert provider.require_latest_price("000001.SZ") == 13.0
    assert provider.get_batch_prices(["000001.SZ", "600000.SH"]) == {
        "000001.SZ": 10.0,
        "600000.SH": 10.0,
    }
    assert provider.clear_cache() is None
