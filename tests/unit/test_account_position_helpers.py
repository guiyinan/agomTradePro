from decimal import Decimal
from types import SimpleNamespace

from apps.decision_rhythm.application.use_cases import update_or_create_account_position
from apps.policy.application.hedging_use_cases import list_portfolio_position_weights


class _FakePositionRepository:
    def update_or_create_position(self, **payload):
        return SimpleNamespace(id=17, payload=payload)

    def list_portfolio_position_weights(self, portfolio_id: int):
        return [{"portfolio_id": portfolio_id, "weight": 0.6}]


def test_update_or_create_account_position_uses_account_repository(monkeypatch):
    monkeypatch.setattr(
        "apps.decision_rhythm.application.use_cases.get_account_position_repository",
        lambda: _FakePositionRepository(),
    )

    result = update_or_create_account_position(
        portfolio_id=3,
        asset_code="000001.SZ",
        shares=100,
        avg_cost=Decimal("10.00"),
        current_price=Decimal("11.00"),
        source="decision",
    )

    assert result.id == 17
    assert result.payload["asset_code"] == "000001.SZ"


def test_list_portfolio_position_weights_uses_account_repository(monkeypatch):
    monkeypatch.setattr(
        "apps.policy.application.hedging_use_cases._get_account_position_repository",
        lambda: _FakePositionRepository(),
    )

    assert list_portfolio_position_weights(9) == [{"portfolio_id": 9, "weight": 0.6}]

