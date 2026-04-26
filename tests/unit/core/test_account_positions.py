from types import SimpleNamespace
from decimal import Decimal

from core.integration.account_positions import update_or_create_account_position


class _FakePositionRepository:
    def update_or_create_position(self, **payload):
        return SimpleNamespace(id=17, payload=payload)


def test_update_or_create_account_position_uses_account_repository(monkeypatch):
    monkeypatch.setattr(
        "core.integration.account_positions.PositionRepository",
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
