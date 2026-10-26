"""Database regressions for broker-fact projection cost and provenance facts."""

from __future__ import annotations

from datetime import date, datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal
from types import SimpleNamespace
from typing import Literal
from unittest.mock import Mock

import pytest
from django.contrib.auth.models import User
from django.utils import timezone

from apps.account.infrastructure.portfolio_models import (
    PortfolioModel,
)
from apps.account.infrastructure.portfolio_models import PositionModel as LegacyPositionModel
from apps.simulated_trading.application.broker_trade_projection import (
    BrokerActualFact,
    BrokerLegacyPositionSeed,
    BrokerPositionExpectation,
    BrokerTradeProjectionCommand,
)
from apps.simulated_trading.application.fee_correction import FeeCorrectionBlockedError
from apps.simulated_trading.infrastructure import models as ledger_models
from apps.simulated_trading.infrastructure.broker_trade_projection_repository import (
    DjangoBrokerTradeProjectionRepository,
)
from apps.simulated_trading.infrastructure.fee_correction_repository import (
    DjangoFeeCorrectionRepository,
)
from apps.simulated_trading.infrastructure.trade_repository import DjangoTradeRepository

pytestmark = pytest.mark.django_db

_ASSET_CODE = "000001.SZ"
_ZERO = Decimal("0")
_MONEY_QUANTUM = Decimal("0.01")
_PRICE_QUANTUM = Decimal("0.0001")


def _create_book(
    owner_suffix: str,
) -> tuple[User, PortfolioModel, ledger_models.SimulatedAccountModel]:
    """Create an exact account/portfolio source map without position mappings."""

    owner = User.objects.create_user(username=f"broker-projection-{owner_suffix}")
    portfolio = PortfolioModel.objects.create(user=owner, name="Broker projection test")
    account = ledger_models.SimulatedAccountModel._default_manager.create(
        user=owner,
        account_name=portfolio.name,
        account_type="real",
        initial_capital=_ZERO,
        current_cash=_ZERO,
        current_market_value=_ZERO,
        total_value=_ZERO,
        auto_trading_enabled=False,
    )
    ledger_models.LedgerMigrationMapModel._default_manager.create(
        source_app="account",
        source_table="portfolio",
        source_id=portfolio.pk,
        target_table="simulated_account",
        target_id=account.pk,
        notes="broker_projection_test_account_map",
    )
    return owner, portfolio, account


def _create_sim_position(
    account: ledger_models.SimulatedAccountModel,
    *,
    quantity: Decimal,
    average_cost: Decimal,
    total_cost: Decimal,
    current_price: Decimal,
    valuation_known: bool = True,
) -> ledger_models.PositionModel:
    """Create an unlinked Sim position with independently stored exact cost."""

    return ledger_models.PositionModel._default_manager.create(
        account=account,
        asset_code=_ASSET_CODE,
        asset_name="Local security",
        asset_type="equity",
        quantity=quantity,
        available_quantity=Decimal("20"),
        available_quantity_known=False,
        avg_cost=average_cost,
        total_cost=total_cost,
        current_price=current_price,
        market_value=Decimal("1900.00"),
        valuation_known=valuation_known,
        unrealized_pnl=Decimal("900.00"),
        unrealized_pnl_pct=90.0,
        first_buy_date=date(2020, 5, 19),
        first_buy_date_known=False,
    )


def _create_legacy_position(
    portfolio: PortfolioModel,
    *,
    shares: float = 100.0,
    average_cost: Decimal = Decimal("10.0000"),
    current_price: Decimal | None = Decimal("12.0000"),
) -> LegacyPositionModel:
    """Create a legacy holding whose open timestamp is not broker evidence."""

    return LegacyPositionModel._default_manager.create(
        portfolio=portfolio,
        asset_code=_ASSET_CODE,
        asset_class="equity",
        region="CN",
        cross_border="domestic",
        shares=shares,
        avg_cost=average_cost,
        current_price=current_price,
        source="manual",
    )


def _link_legacy_position(
    legacy: LegacyPositionModel,
    position: ledger_models.PositionModel,
) -> None:
    """Create an exact legacy-to-Sim provenance pair for a mapped-book test."""

    ledger_models.LedgerMigrationMapModel._default_manager.create(
        source_app="account",
        source_table="position",
        source_id=legacy.pk,
        target_table="simulated_position",
        target_id=position.pk,
        notes="broker_fact_projection_position_map",
    )


def _legacy_seed(position: LegacyPositionModel) -> BrokerLegacyPositionSeed:
    """Convert a legacy row to the existing narrow broker projection seed."""

    return BrokerLegacyPositionSeed(
        source_position_id=position.pk,
        asset_code=position.asset_code,
        asset_name="Legacy security",
        asset_type="equity",
        total_shares=Decimal(str(position.shares)),
        average_cost=Decimal(position.avg_cost),
        reference_mark=(
            Decimal(position.current_price) if position.current_price is not None else None
        ),
        valuation_known=position.current_price is not None,
        first_buy_date=position.opened_at.date(),
    )


def _expectation(
    repository: DjangoBrokerTradeProjectionRepository,
    owner: User,
    portfolio: PortfolioModel,
    *,
    legacy_position_id: int | None = None,
) -> BrokerPositionExpectation:
    """Capture the repository's real CAS and mapping identity for one asset."""

    snapshot = repository.capture_position_snapshots(
        owner_user_id=owner.pk,
        portfolio_id=portfolio.pk,
        portfolio_name=portfolio.name,
        asset_codes=(_ASSET_CODE,),
        legacy_position_ids={_ASSET_CODE: legacy_position_id},
    )[0]
    return BrokerPositionExpectation(
        account_id=snapshot.account_id,
        account_mapping_id=snapshot.account_mapping_id,
        account_mapping_count=snapshot.account_mapping_count,
        unified_position_id=snapshot.unified_position_id,
        position_map_source_id=snapshot.position_map_source_id,
        position_map_target_id=snapshot.position_map_target_id,
        total_shares=snapshot.total_shares,
        average_cost=snapshot.average_cost,
        reference_mark=snapshot.reference_mark,
        valuation_known=snapshot.valuation_known,
        available_quantity=snapshot.available_quantity,
        available_quantity_known=snapshot.available_quantity_known,
        asset_type=snapshot.asset_type,
        position_map_state=snapshot.position_map_state,
    )


def _command(
    owner: User,
    portfolio: PortfolioModel,
    *,
    action: Literal["buy", "sell"],
    shares: Decimal,
    price: Decimal,
    transaction_id: int,
    expectation: BrokerPositionExpectation,
    legacy_position: BrokerLegacyPositionSeed | None = None,
    traded_at: datetime | None = None,
) -> BrokerTradeProjectionCommand:
    """Build a typed broker fact with canonical fee-knownness flags."""

    fact = BrokerActualFact(
        transaction_id=transaction_id,
        asset_code=_ASSET_CODE,
        asset_name="Broker security",
        asset_type="equity",
        action=action,
        shares=shares,
        price=price,
        notional=(shares * price).quantize(_MONEY_QUANTUM, rounding=ROUND_HALF_UP),
        commission=Decimal("1.23"),
        commission_known=True,
        stamp_duty=Decimal("0"),
        stamp_duty_known=False,
        transfer_fee=Decimal("0.07"),
        transfer_fee_known=True,
        slippage=Decimal("0"),
        slippage_known=False,
        traded_at=traded_at or timezone.now(),
    )
    return BrokerTradeProjectionCommand(
        owner_user_id=owner.pk,
        portfolio_id=portfolio.pk,
        portfolio_name=portfolio.name,
        portfolio_is_active=portfolio.is_active,
        legacy_position=legacy_position,
        expectation=expectation,
        fact=fact,
    )


def test_existing_sim_position_with_missing_legacy_map_blocks_without_writes() -> None:
    """Same-asset similarity cannot replace a missing legacy-to-Sim map."""

    owner, portfolio, account = _create_book("missing-position-map")
    position = _create_sim_position(
        account,
        quantity=Decimal("100"),
        average_cost=Decimal("10.0000"),
        total_cost=Decimal("1000.00"),
        current_price=Decimal("19.0000"),
    )
    legacy = _create_legacy_position(portfolio)
    repository = DjangoBrokerTradeProjectionRepository()
    before_position = (
        position.pk,
        position.quantity,
        position.avg_cost,
        position.total_cost,
        position.current_price,
        position.market_value,
        position.first_buy_date,
        position.first_buy_date_known,
    )
    before_account = (account.current_cash, account.current_market_value, account.total_trades)

    result = repository.apply_actual_broker_fact(
        _command(
            owner,
            portfolio,
            action="buy",
            shares=Decimal("5"),
            price=Decimal("11.0000"),
            transaction_id=portfolio.pk * 1000 + 1,
            expectation=_expectation(repository, owner, portfolio, legacy_position_id=legacy.pk),
            legacy_position=_legacy_seed(legacy),
        )
    )

    position.refresh_from_db()
    account.refresh_from_db()
    assert result.applied is False
    assert result.reason_code == "POSITION_MAPPING_MISSING"
    assert (
        position.pk,
        position.quantity,
        position.avg_cost,
        position.total_cost,
        position.current_price,
        position.market_value,
        position.first_buy_date,
        position.first_buy_date_known,
    ) == before_position
    assert (
        account.current_cash,
        account.current_market_value,
        account.total_trades,
    ) == before_account
    assert not ledger_models.SimulatedTradeModel._default_manager.filter(account=account).exists()
    assert not ledger_models.LedgerMigrationMapModel._default_manager.filter(
        source_app="account", source_table="position", source_id=legacy.pk
    ).exists()
    assert not ledger_models.LedgerMigrationMapModel._default_manager.filter(
        source_app="account",
        source_table="transaction",
        source_id=portfolio.pk * 1000 + 1,
    ).exists()


def test_buy_adds_exact_existing_cost_and_known_fees_without_avg_cost_reconstruction() -> None:
    """A rounded unit average cannot overwrite the independently stored exact basis."""

    owner, portfolio, account = _create_book("exact-buy-cost")
    position = _create_sim_position(
        account,
        quantity=Decimal("100"),
        average_cost=Decimal("10.0000"),
        total_cost=Decimal("1000.03"),
        current_price=Decimal("19.0000"),
    )
    legacy = _create_legacy_position(portfolio, current_price=Decimal("19.0000"))
    _link_legacy_position(legacy, position)
    repository = DjangoBrokerTradeProjectionRepository()
    result = repository.apply_actual_broker_fact(
        _command(
            owner,
            portfolio,
            action="buy",
            shares=Decimal("7"),
            price=Decimal("10.1234"),
            transaction_id=portfolio.pk * 1000 + 2,
            expectation=_expectation(repository, owner, portfolio, legacy_position_id=legacy.pk),
        )
    )

    position.refresh_from_db()
    mirror = ledger_models.SimulatedTradeModel._default_manager.get(account=account)
    mapping = ledger_models.LedgerMigrationMapModel._default_manager.get(
        source_app="account",
        source_table="transaction",
        source_id=portfolio.pk * 1000 + 2,
    )
    assert result.applied is True
    assert position.quantity == Decimal("107.000000")
    assert position.total_cost == Decimal("1072.19")
    assert position.avg_cost == Decimal("10.0205")
    assert mirror.total_cost == Decimal("72.16")
    assert mirror.fee_amounts_known is False
    assert mirror.cost_basis_known is False
    assert position.cost_basis_known is False
    assert mirror.stamp_duty is None
    assert "commission_known=True" in mapping.notes
    assert "stamp_duty_known=False" in mapping.notes
    assert "transfer_fee_known=True" in mapping.notes
    assert "fee_amounts_known=False" in mapping.notes
    assert "cost_basis_known=False" in mapping.notes


def test_sell_prorates_exact_stored_total_cost_to_remaining_shares() -> None:
    """Quantity projection preserves cash values while marking them unverified."""

    owner, portfolio, account = _create_book("exact-sell-cost")
    account.current_cash = Decimal("5421.00")
    account.total_value = Decimal("7000.00")
    account.save(update_fields=["current_cash", "total_value"])
    stale_cash = account.current_cash
    stale_total_value = account.total_value
    position = _create_sim_position(
        account,
        quantity=Decimal("100"),
        average_cost=Decimal("10.0000"),
        total_cost=Decimal("1000.03"),
        current_price=Decimal("19.0000"),
    )
    legacy = _create_legacy_position(portfolio, current_price=Decimal("19.0000"))
    _link_legacy_position(legacy, position)
    repository = DjangoBrokerTradeProjectionRepository()
    result = repository.apply_actual_broker_fact(
        _command(
            owner,
            portfolio,
            action="sell",
            shares=Decimal("40"),
            price=Decimal("11.2500"),
            transaction_id=portfolio.pk * 1000 + 3,
            expectation=_expectation(repository, owner, portfolio, legacy_position_id=legacy.pk),
        )
    )

    position.refresh_from_db()
    account.refresh_from_db()
    assert result.applied is True
    assert position.quantity == Decimal("60.000000")
    assert position.total_cost == Decimal("600.02")
    assert position.avg_cost == Decimal("10.0003")
    assert account.cash_known is False
    assert account.cash_reconciliation_status == "quantity_only"
    assert account.current_cash == stale_cash
    assert account.total_value == stale_total_value
    assert position.cost_basis_known is None
    mirror = ledger_models.SimulatedTradeModel._default_manager.get(account=account)
    assert mirror.fee_amounts_known is False
    assert mirror.cost_basis_known is None
    repository = DjangoTradeRepository()
    history = repository.get_account_history(account_id=account.pk, as_of=timezone.now())
    assert len(history.trades) == 1
    assert history.trades[0].fee_amounts_known is False
    assert history.trades[0].cost_basis_known is None
    assert history.trades[0].current_realized_pnl is None
    assert history.cash_events == ()

    summary = repository.get_trade_model_summary_for_account(account.pk)
    assert summary["total_realized_pnl"] is None
    assert summary["total_realized_pnl_known"] is False
    dashboard = repository.sum_realized_pnl_for_closed_trades()
    assert dashboard["effective_realized_pnl"] is None
    assert dashboard["effective_known"] is False


def test_real_account_history_preserves_exact_known_realized_pnl() -> None:
    """Uncorrected real history retains exact broker-known closed-trade PnL."""

    _owner, _portfolio, account = _create_book("known-realized-pnl")
    traded_at = timezone.now() - timedelta(days=1)
    trade = ledger_models.SimulatedTradeModel._default_manager.create(
        account=account,
        asset_code=_ASSET_CODE,
        asset_name="Exact broker sale",
        asset_type="equity",
        action="sell",
        quantity=Decimal("5.000000"),
        price=Decimal("12.0000"),
        amount=Decimal("60.00"),
        commission=Decimal("1.00"),
        transfer_fee=Decimal("0.00"),
        stamp_duty=Decimal("0.00"),
        slippage=Decimal("0.00"),
        total_cost=Decimal("1.00"),
        fee_amounts_known=True,
        cost_basis_known=True,
        realized_pnl=Decimal("8.50"),
        realized_pnl_pct=16.8317,
        order_date=traded_at.date(),
        execution_date=traded_at.date(),
        execution_time=traded_at,
        status="executed",
    )

    history = DjangoTradeRepository().get_account_history(
        account_id=account.pk,
        as_of=traded_at + timedelta(seconds=1),
    )

    assert len(history.trades) == 1
    projected_trade = history.trades[0]
    assert projected_trade.trade_id == trade.pk
    assert projected_trade.fee_amounts_known is True
    assert projected_trade.cost_basis_known is True
    assert projected_trade.realized_pnl == 8.5
    assert projected_trade.current_realized_pnl == 8.5
    assert projected_trade.effective_realized_pnl is None
    assert history.cash_events == ()


def test_fee_correction_history_rejects_missing_account_without_fallback() -> None:
    """A missing account never receives another account's history projection."""

    reader = DjangoFeeCorrectionRepository()
    with pytest.raises(FeeCorrectionBlockedError) as failure:
        reader.get_account_history(
            account_id=2_147_483_647,
            as_of=timezone.now(),
        )

    assert failure.value.code == "SIMULATED_ACCOUNT_UNAVAILABLE"


def test_fee_correction_history_rejects_unknown_account_type_before_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Unknown legacy account types are not interpreted as real or simulated."""

    unknown_query = Mock()
    unknown_query.select_for_update.return_value = unknown_query
    unknown_query.filter.return_value = unknown_query
    unknown_query.first.return_value = SimpleNamespace(account_type="broker")
    account_manager = ledger_models.SimulatedAccountModel._base_manager
    monkeypatch.setattr(account_manager, "using", Mock(return_value=unknown_query))

    with pytest.raises(FeeCorrectionBlockedError) as failure:
        DjangoFeeCorrectionRepository().get_account_history(
            account_id=1,
            as_of=timezone.now(),
        )

    assert failure.value.code == "SIMULATED_ACCOUNT_UNAVAILABLE"


def test_legacy_opened_at_does_not_certify_first_buy_date() -> None:
    """Legacy holding creation time is retained only as an unverified date hint."""

    owner, portfolio, _account = _create_book("legacy-opened-at")
    legacy = _create_legacy_position(portfolio)
    repository = DjangoBrokerTradeProjectionRepository()
    traded_at = timezone.now() + timedelta(days=2)
    result = repository.apply_actual_broker_fact(
        _command(
            owner,
            portfolio,
            action="buy",
            shares=Decimal("5"),
            price=Decimal("11.0000"),
            transaction_id=portfolio.pk * 1000 + 4,
            expectation=_expectation(repository, owner, portfolio, legacy_position_id=legacy.pk),
            legacy_position=_legacy_seed(legacy),
            traded_at=traded_at,
        )
    )

    position = ledger_models.PositionModel._default_manager.get(account__user=owner)
    assert result.applied is True
    assert position.first_buy_date == legacy.opened_at.date()
    assert position.first_buy_date_known is False


def test_unknown_valuation_never_uses_placeholder_price_for_derived_values() -> None:
    """Unvalued holdings keep price placeholders hidden from totals and response marks."""

    owner, portfolio, account = _create_book("unknown-valuation")
    position = _create_sim_position(
        account,
        quantity=Decimal("100"),
        average_cost=Decimal("10.0000"),
        total_cost=Decimal("1000.00"),
        current_price=Decimal("88.8800"),
        valuation_known=False,
    )
    legacy = _create_legacy_position(portfolio, current_price=Decimal("88.8800"))
    _link_legacy_position(legacy, position)
    repository = DjangoBrokerTradeProjectionRepository()
    result = repository.apply_actual_broker_fact(
        _command(
            owner,
            portfolio,
            action="buy",
            shares=Decimal("5"),
            price=Decimal("11.0000"),
            transaction_id=portfolio.pk * 1000 + 5,
            expectation=_expectation(repository, owner, portfolio, legacy_position_id=legacy.pk),
        )
    )

    position.refresh_from_db()
    assert result.applied is True
    assert result.reference_mark is None
    assert position.valuation_known is False
    assert position.current_price == Decimal("88.8800")
    assert position.market_value == Decimal("0.00")
    assert position.unrealized_pnl == Decimal("0.00")
    assert position.unrealized_pnl_pct == 0.0
