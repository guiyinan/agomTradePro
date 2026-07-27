"""Tests for the focused Account asset metadata repository."""

from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import Mock, patch

from apps.account.infrastructure.asset_metadata_repository import AssetMetadataRepository
from apps.account.infrastructure.models import PositionModel


def _position(*, shares: float = 100.0) -> SimpleNamespace:
    """Build the persisted fields required by legacy repricing."""

    return SimpleNamespace(
        id=7,
        asset_code="000001.SZ",
        shares=shares,
        avg_cost=Decimal("10"),
        current_price=Decimal("10"),
        market_value=Decimal("1000"),
        unrealized_pnl=Decimal("0"),
        unrealized_pnl_pct=0.0,
        save=Mock(),
    )


def test_update_position_prices_uses_exact_decimal_math() -> None:
    """Float share storage must not mix float and Decimal arithmetic."""

    position = _position()
    price_service = Mock()
    price_service.get_price_with_metadata.return_value = {"price": Decimal("12.5")}

    with (
        patch.object(PositionModel._default_manager, "filter", return_value=[position]),
        patch(
            "apps.account.infrastructure.market_price_service.get_market_price_service",
            return_value=price_service,
        ),
    ):
        updated_count = AssetMetadataRepository().update_position_prices(user_id=9)

    assert updated_count == 1
    assert position.current_price == Decimal("12.5")
    assert position.market_value == Decimal("1250.0")
    assert position.unrealized_pnl == Decimal("250.0")
    assert position.unrealized_pnl_pct == 25.0
    position.save.assert_called_once_with(
        update_fields=[
            "current_price",
            "market_value",
            "unrealized_pnl",
            "unrealized_pnl_pct",
        ]
    )


def test_update_position_prices_rejects_nonfinite_shares(caplog) -> None:
    """Corrupt position quantities must not be persisted into valuations."""

    position = _position(shares=float("nan"))
    price_service = Mock()
    price_service.get_price_with_metadata.return_value = {"price": Decimal("12.5")}

    with (
        patch.object(PositionModel._default_manager, "filter", return_value=[position]),
        patch(
            "apps.account.infrastructure.market_price_service.get_market_price_service",
            return_value=price_service,
        ),
    ):
        updated_count = AssetMetadataRepository().update_position_prices(user_id=9)

    assert updated_count == 0
    position.save.assert_not_called()
    assert "position_id=7" in caplog.text


def test_update_position_prices_sanitizes_row_failure(caplog) -> None:
    """Per-position failures remain isolated without logging exception details."""

    position = _position()
    price_service = Mock()
    price_service.get_price_with_metadata.side_effect = RuntimeError("token=secret-value")

    with (
        patch.object(PositionModel._default_manager, "filter", return_value=[position]),
        patch(
            "apps.account.infrastructure.market_price_service.get_market_price_service",
            return_value=price_service,
        ),
    ):
        updated_count = AssetMetadataRepository().update_position_prices(user_id=9)

    assert updated_count == 0
    assert "RuntimeError" in caplog.text
    assert "secret-value" not in caplog.text
