"""T5 contracts for Dashboard Alpha exit-watch construction."""

from __future__ import annotations

from datetime import UTC, date, datetime
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from apps.dashboard.application import alpha_homepage_exit_watch as exit_watch
from apps.dashboard.application.alpha_homepage_exit_watch import AlphaExitWatchMixin


class _Harness(AlphaExitWatchMixin):
    """Concrete harness exposing the mixin's repository collaborators."""

    def __init__(self) -> None:
        self.unified_recommendation_repo = MagicMock()
        self.transition_plan_repo = MagicMock()


def _position(**overrides: object) -> dict[str, object]:
    """Build a representative simulated position."""
    payload: dict[str, object] = {
        "account_id": 7,
        "account_name": "main",
        "asset_code": "a",
        "asset_name": "Asset A",
        "shares": 10,
        "market_value": 100,
        "avg_cost": 9,
        "current_price": 10,
        "unrealized_pnl_pct": 0.1,
        "opened_at": "2026-07-01",
        "signal_id": 11,
        "is_invalidated": False,
    }
    payload.update(overrides)
    return payload


def _recommendation(**overrides: object) -> SimpleNamespace:
    """Build a recommendation contract used by exit-watch branches."""
    payload = {
        "security_code": "A",
        "recommendation_id": "rec-1",
        "side": "HOLD",
        "status": SimpleNamespace(value="ACTIVE"),
        "user_action": SimpleNamespace(value="ADOPTED"),
        "source_signal_ids": [12],
        "confidence": 0.8,
        "composite_score": 0.7,
        "alpha_model_score": 0.6,
        "human_rationale": "track",
        "reason_codes": ["QUALITY"],
        "target_price_low": 11,
        "target_price_high": 13,
        "stop_loss_price": 8,
        "created_at": datetime(2026, 7, 24, tzinfo=UTC),
        "updated_at": datetime(2026, 7, 25, tzinfo=UTC),
    }
    payload.update(overrides)
    return SimpleNamespace(**payload)


def _order(**overrides: object) -> SimpleNamespace:
    """Build a transition order contract."""
    payload = {
        "security_code": "A",
        "action": "REDUCE",
        "is_ready_for_approval": True,
        "delta_qty": -3,
        "current_qty": 10,
        "target_qty": 7,
        "stop_loss_price": 8,
        "price_band_low": 9,
        "price_band_high": 11,
        "invalidation_description": "break support",
        "invalidation_rule": {"conditions": ["close below support", ""]},
        "notes": ["rebalance", ""],
    }
    payload.update(overrides)
    return SimpleNamespace(**payload)


def test_exit_watch_item_prioritizes_invalidation_transition_and_recommendation() -> None:
    """Exit decisions must follow invalidation, plan, recommendation, then hold priority."""
    harness = _Harness()
    recommendation = _recommendation(side="SELL", human_rationale="exit signal")
    order = _order()
    common = {
        "recommendation_map": {"A": recommendation},
        "transition_order_map": {
            "A": {"order": order, "plan_id": "plan-1"},
        },
        "signal_payloads": {
            "11": {
                "invalidation_logic": "signal invalid",
                "invalidation_rule_json": {"conditions": ["signal condition"]},
            }
        },
    }

    invalidated = harness._build_exit_watch_item(
        position=_position(
            is_invalidated=True,
            invalidation_reason="thesis broken",
            invalidation_description="position rule",
        ),
        **common,
    )
    assert invalidated["exit_action"] == "SELL"
    assert invalidated["exit_source"] == "simulated_trading.position_invalidation"
    assert invalidated["priority_rank"] == 0
    assert invalidated["contract_ready"] is True
    assert invalidated["recommendation_snapshot"]["is_processed"] is True
    assert invalidated["transition_plan_snapshot"]["delta_qty"] == -3

    reduced = harness._build_exit_watch_item(position=_position(), **common)
    assert reduced["exit_action"] == "REDUCE"
    assert reduced["reduce_quantity"] == 3
    assert reduced["transition_plan_id"] == "plan-1"

    sold = harness._build_exit_watch_item(
        position=_position(signal_id=""),
        recommendation_map={"A": recommendation},
        transition_order_map={},
        signal_payloads={"12": {"invalidation_description": "recommendation invalid"}},
    )
    assert sold["exit_action"] == "SELL"
    assert sold["signal_id"] == 12
    assert sold["exit_source"] == "decision_rhythm.recommendation"

    held = harness._build_exit_watch_item(
        position=_position(signal_id=None, account_id=None),
        recommendation_map={},
        transition_order_map={},
        signal_payloads={},
    )
    assert held["exit_action"] == "HOLD"
    assert held["contract_ready"] is False
    assert held["account_detail_url"] == ""


def test_exit_watchlist_groups_accounts_loads_signals_and_sorts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Watchlist assembly must skip malformed accounts and sort urgent value first."""
    harness = _Harness()
    recommendation = _recommendation(source_signal_ids=["12", "bad"])
    harness.unified_recommendation_repo.get_by_account.return_value = [recommendation]
    plan = SimpleNamespace(
        plan_id="plan-1",
        as_of=datetime(2026, 7, 25, tzinfo=UTC),
        orders=[_order()],
    )
    harness.transition_plan_repo.get_latest_for_account.return_value = plan
    monkeypatch.setattr(
        exit_watch,
        "list_user_position_payloads",
        lambda **_kwargs: [
            _position(asset_code="A", market_value=100),
            _position(asset_code="B", market_value=200, is_invalidated=True),
            _position(account_id="bad", asset_code="SKIP"),
        ],
    )
    signal_repository = MagicMock()
    signal_repository.get_invalidation_payloads.return_value = {
        "11": {"invalidation_description": "rule"}
    }
    monkeypatch.setattr(exit_watch, "get_signal_repository", lambda: signal_repository)

    watchlist = harness._build_exit_watchlist(
        user_id=5,
        trade_date=date(2026, 7, 25),
    )

    assert [item["asset_code"] for item in watchlist] == ["B", "A"]
    signal_repository.get_invalidation_payloads.assert_called_once_with([11, 12])
    assert harness._build_exit_watch_summary(watchlist) == {
        "total": 2,
        "urgent_count": 1,
        "sell_count": 1,
        "reduce_count": 1,
        "hold_count": 0,
    }

    monkeypatch.setattr(
        exit_watch,
        "list_user_position_payloads",
        lambda **_kwargs: [],
    )
    assert harness._build_exit_watchlist(user_id=5, trade_date=date.today()) == []


def test_exit_watch_repository_failures_are_isolated(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Optional recommendation, plan, and signal sources must fail closed."""
    harness = _Harness()
    harness.unified_recommendation_repo.get_by_account.side_effect = RuntimeError("offline")
    assert harness._load_unified_recommendations(7) == []

    harness.transition_plan_repo.get_latest_for_account.side_effect = RuntimeError("offline")
    assert harness._load_transition_orders(account_id=7, trade_date=date.today()) == {}
    harness.transition_plan_repo.get_latest_for_account.side_effect = None
    harness.transition_plan_repo.get_latest_for_account.return_value = None
    assert harness._load_transition_orders(account_id=7, trade_date=date.today()) == {}
    harness.transition_plan_repo.get_latest_for_account.return_value = SimpleNamespace(
        as_of=datetime(2026, 7, 24, tzinfo=UTC),
        orders=[],
    )
    assert (
        harness._load_transition_orders(
            account_id=7,
            trade_date=date(2026, 7, 25),
        )
        == {}
    )

    assert harness._load_signal_invalidation_payloads([]) == {}
    repository = MagicMock()
    repository.get_invalidation_payloads.side_effect = RuntimeError("offline")
    monkeypatch.setattr(exit_watch, "get_signal_repository", lambda: repository)
    assert harness._load_signal_invalidation_payloads([1]) == {}


def test_exit_watch_utilities_handle_duplicates_and_malformed_values() -> None:
    """Utility contracts must select latest records and reject unsafe conversions."""
    harness = _Harness()
    older = _recommendation(updated_at=datetime(2026, 7, 23, tzinfo=UTC))
    newer = _recommendation(updated_at=datetime(2026, 7, 25, tzinfo=UTC))
    blank = _recommendation(security_code="")
    selected = harness._latest_recommendations_by_security([older, blank, newer])
    assert selected == {"A": newer}

    assert harness._safe_int(None) is None
    assert harness._safe_int("bad") is None
    assert harness._safe_int("7") == 7
    assert harness._normalize_decimal_string(0) is None
    assert harness._normalize_decimal_string("bad") is None
    assert harness._normalize_decimal_string(-1) is None
    assert harness._normalize_decimal_string("1.234") == "1.23"
