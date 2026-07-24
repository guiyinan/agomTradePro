"""Tests for simulated-position invalidation checks."""

import json
from datetime import date, datetime

from apps.simulated_trading.application.position_invalidation_checker import (
    PositionInvalidationChecker,
    _MacroObservation,
)
from apps.simulated_trading.domain.entities import Position


class _MacroGateway:
    def get_latest_by_code(self, code: str) -> _MacroObservation | None:
        return _MacroObservation(
            value=49.0,
            unit="指数",
            observed_at=date(2026, 7, 24),
        )

    def get_history_by_code(
        self,
        code: str,
        periods: int = 12,
    ) -> list[_MacroObservation]:
        return [
            _MacroObservation(
                value=49.0,
                unit="指数",
                observed_at=date(2026, 7, 24),
            )
        ]


class _PositionRepository:
    def __init__(self, position: Position, *, mark_result: bool = True) -> None:
        self.position = position
        self.mark_result = mark_result
        self.checked = False
        self.marked = False

    def get_pending_invalidation_positions(self) -> list[Position]:
        return [self.position]

    def get_position_by_id(self, position_id: int) -> Position | None:
        return self.position

    def mark_invalidation_checked(
        self,
        account_id: int,
        asset_code: str,
        checked_at: datetime,
    ) -> bool:
        self.checked = True
        return True

    def mark_invalidated(
        self,
        account_id: int,
        asset_code: str,
        reason: str,
        checked_at: datetime,
    ) -> bool:
        self.marked = True
        return self.mark_result

    def count_positions_with_invalidation_rules(self) -> int:
        return 1

    def get_invalidated_position_summaries(self) -> list[dict[str, object]]:
        return []


def _build_position() -> Position:
    rule = {
        "conditions": [
            {
                "indicator_code": "CN_PMI",
                "indicator_type": "macro",
                "operator": "lt",
                "threshold": 50.0,
                "duration": None,
                "compare_with": None,
            }
        ],
        "logic": "AND",
    }
    return Position(
        account_id=1,
        asset_code="000001.SZ",
        asset_name="平安银行",
        asset_type="equity",
        quantity=100,
        available_quantity=100,
        avg_cost=10.0,
        total_cost=1000.0,
        current_price=9.0,
        market_value=900.0,
        unrealized_pnl=-100.0,
        unrealized_pnl_pct=-10.0,
        first_buy_date=date(2026, 7, 1),
        last_update_date=date(2026, 7, 24),
        invalidation_rule_json=json.dumps(rule),
    )


def test_json_rule_is_evaluated_and_persisted() -> None:
    position = _build_position()
    position_repo = _PositionRepository(position)
    checker = PositionInvalidationChecker(
        macro_repo=_MacroGateway(),
        position_repo=position_repo,
    )

    invalidated = checker.check_all_positions()

    assert len(invalidated) == 1
    assert invalidated[0]["asset_code"] == "000001.SZ"
    assert position_repo.checked is True
    assert position_repo.marked is True


def test_failed_invalidation_write_is_not_reported_as_success() -> None:
    position = _build_position()
    position_repo = _PositionRepository(position, mark_result=False)
    checker = PositionInvalidationChecker(
        macro_repo=_MacroGateway(),
        position_repo=position_repo,
    )

    invalidated = checker.check_all_positions()

    assert invalidated == []
    assert position_repo.checked is True
    assert position_repo.marked is True
