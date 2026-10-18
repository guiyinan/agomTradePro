"""Regression candidates for preserving broker executions as source facts."""

from collections.abc import Iterable
from datetime import date, datetime
from decimal import Decimal
from typing import Any

import pytest
from django.contrib.auth.models import User
from django.db.models import Model
from django.utils import timezone

from apps.account.application.manual_trade_sync import (
    BrokerTradeImportResult,
    ManualTradeImportUseCase,
)
from apps.account.infrastructure import models as account_models
from apps.account.infrastructure.models import PortfolioModel, TransactionModel
from apps.account.infrastructure.repositories import PortfolioApiRepository
from apps.simulated_trading.infrastructure import models as ledger_models
from apps.simulated_trading.infrastructure.models import SimulatedTradeModel
from core.exceptions import ExternalServiceError

LegacyPositionModel = account_models.PositionModel
UnifiedPositionModel = ledger_models.PositionModel

BROKER_NAME = "ash03-fixture-broker"
SOURCE_TIMESTAMP = "2020-05-20T10:11:12.345678+08:00"
SOURCE_DATETIME = datetime.fromisoformat(SOURCE_TIMESTAMP)
ASSET_CODE = "000001.SZ"


class NoopExecutionMatcher:
    """Satisfy the full matcher port without creating recommendation links."""

    def record_imported_execution(
        self,
        *,
        account_id: str,
        transaction_id: int,
        security_code: str,
        actual_action: str,
        traded_at: datetime,
    ) -> dict[str, Any]:
        """Accept one imported execution without matching it to a recommendation."""
        return {"match_method": "manual_only"}


class FailingExecutionMatcher:
    """Raise a recognized external-service failure after fact creation is attempted."""

    def __init__(self) -> None:
        self.calls = 0

    def record_imported_execution(
        self,
        *,
        account_id: str,
        transaction_id: int,
        security_code: str,
        actual_action: str,
        traded_at: datetime,
    ) -> dict[str, Any]:
        """Report a transient recommendation service failure."""
        self.calls += 1
        raise ExternalServiceError(
            "Recommendation matching is temporarily unavailable",
            code="RECOMMENDATION_MATCHER_UNAVAILABLE",
        )


@pytest.fixture
def owner_portfolio() -> tuple[User, PortfolioModel]:
    """Create an owned real portfolio for one database-isolated import test."""
    user = User.objects.create_user(username="ash03-broker-fact-owner")
    portfolio = PortfolioModel.objects.create(user=user, name="Broker facts")
    return user, portfolio


def _broker_csv(
    *,
    action: str,
    asset_code: str,
    shares: int,
    external_trade_id: str,
) -> bytes:
    """Build one CSV row with source timestamp and mixed known/unknown fees."""
    header = (
        "traded_at,action,asset_code,shares,price,commission,stamp_duty,"
        "transfer_fee,external_trade_id,notes\n"
    )
    row = (
        f"{SOURCE_TIMESTAMP},{action},{asset_code},{shares},11.25,1.23,,0.07,"
        f"{external_trade_id},broker fill\n"
    )
    return (header + row).encode("utf-8")


def _expected_raw_payload(
    *,
    action: str,
    asset_code: str,
    shares: int,
    external_trade_id: str,
) -> dict[str, str]:
    """Return the exact source strings emitted by the fixture CSV row."""
    return {
        "traded_at": SOURCE_TIMESTAMP,
        "action": action,
        "asset_code": asset_code,
        "shares": str(shares),
        "price": "11.25",
        "commission": "1.23",
        "stamp_duty": "",
        "transfer_fee": "0.07",
        "external_trade_id": external_trade_id,
        "notes": "broker fill",
    }


def _snapshot_model_rows(instances: Iterable[Model]) -> list[dict[str, object]]:
    """Capture every concrete database field on a sequence of model rows."""
    return [
        {
            field.attname: getattr(instance, field.attname)
            for field in instance._meta.concrete_fields
        }
        for instance in instances
    ]


def _snapshot_positions(
    *,
    account_id: int,
    portfolio_id: int,
) -> tuple[list[dict[str, object]], list[dict[str, object]]]:
    """Capture all unified and legacy position fields for the affected account."""
    unified_rows = UnifiedPositionModel._default_manager.filter(
        account_id=account_id,
    ).order_by("pk")
    legacy_rows = LegacyPositionModel._default_manager.filter(
        portfolio_id=portfolio_id,
    ).order_by("pk")
    return _snapshot_model_rows(unified_rows), _snapshot_model_rows(legacy_rows)


def _assert_import_fact_preserved(
    *,
    portfolio: PortfolioModel,
    result: BrokerTradeImportResult,
    action: str,
    asset_code: str,
    shares: int,
    external_trade_id: str,
    import_started: datetime,
    import_finished: datetime,
) -> TransactionModel:
    """Verify the complete broker fact and source-versus-recorded timestamps."""
    facts = TransactionModel._default_manager.filter(
        portfolio=portfolio,
        broker_name=BROKER_NAME,
        external_trade_id=external_trade_id,
    )
    assert facts.count() == 1
    assert result.imported_rows == 1
    assert result.valid_rows == 1
    fact = facts.get()

    assert fact.action == action
    assert fact.asset_code == asset_code
    assert fact.shares == float(shares)
    assert fact.price == Decimal("11.2500")
    assert fact.traded_at == SOURCE_DATETIME
    assert timezone.is_aware(fact.traded_at)
    assert timezone.is_aware(fact.created_at)
    assert import_started <= fact.created_at <= import_finished
    assert fact.created_at != fact.traded_at
    assert fact.created_at > SOURCE_DATETIME
    assert fact.raw_payload == _expected_raw_payload(
        action=action,
        asset_code=asset_code,
        shares=shares,
        external_trade_id=external_trade_id,
    )
    assert fact.broker_trade_key
    assert (
        TransactionModel._default_manager.filter(
            broker_trade_key=fact.broker_trade_key,
        ).count()
        == 1
    )
    assert result.batch_id is not None
    assert fact.import_batch_id == result.batch_id

    assert fact.commission == Decimal("1.23")
    assert fact.commission_known is True
    assert fact.stamp_duty == Decimal("0.00")
    assert fact.stamp_duty_known is False
    assert fact.transfer_fee == Decimal("0.07")
    assert fact.transfer_fee_known is True
    assert fact.slippage == Decimal("0.00")
    assert fact.slippage_known is False
    return fact


@pytest.mark.parametrize(
    ("sell_case", "available_quantity", "available_quantity_known"),
    [
        ("no_local_position", None, None),
        ("sellable_unknown", Decimal("80.000000"), False),
        ("sellable_insufficient", Decimal("20.000000"), True),
    ],
    ids=["no-local-position", "sellable-unknown", "sellable-insufficient"],
)
@pytest.mark.django_db
def test_actual_sell_fact_is_preserved_when_local_sellability_is_unavailable(
    owner_portfolio: tuple[User, PortfolioModel],
    sell_case: str,
    available_quantity: Decimal | None,
    available_quantity_known: bool | None,
) -> None:
    """Persist the actual sell without changing any unconfirmed local balance."""
    user, portfolio = owner_portfolio
    portfolio_repo = PortfolioApiRepository()
    account_id = portfolio_repo.ensure_real_account(portfolio)

    if available_quantity is not None and available_quantity_known is not None:
        unified_position = UnifiedPositionModel._default_manager.create(
            account_id=account_id,
            asset_code=ASSET_CODE,
            asset_name=ASSET_CODE,
            asset_type="equity",
            quantity=Decimal("100.000000"),
            available_quantity=available_quantity,
            available_quantity_known=available_quantity_known,
            avg_cost=Decimal("10.0000"),
            total_cost=Decimal("1000.00"),
            current_price=Decimal("11.2500"),
            market_value=Decimal("1125.00"),
            unrealized_pnl=Decimal("125.00"),
            unrealized_pnl_pct=12.5,
            first_buy_date=date(2020, 5, 19),
            first_buy_date_known=True,
            entry_reason="pre-existing broker position",
        )
        portfolio_repo.upsert_legacy_projection_from_unified(
            unified_position=unified_position,
            portfolio=portfolio,
            asset_class="equity",
            region="CN",
            cross_border="domestic",
            source="manual",
        )

    positions_before = _snapshot_positions(
        account_id=account_id,
        portfolio_id=portfolio.id,
    )
    import_started = timezone.now()
    result = ManualTradeImportUseCase(
        execution_matcher=NoopExecutionMatcher(),
    ).confirm(
        user_id=user.id,
        portfolio_id=portfolio.id,
        broker_name=BROKER_NAME,
        filename=f"{sell_case}.csv",
        content=_broker_csv(
            action="sell",
            asset_code=ASSET_CODE,
            shares=40,
            external_trade_id=f"actual-sell-{sell_case}",
        ),
    )
    import_finished = timezone.now()

    _assert_import_fact_preserved(
        portfolio=portfolio,
        result=result,
        action="sell",
        asset_code=ASSET_CODE,
        shares=40,
        external_trade_id=f"actual-sell-{sell_case}",
        import_started=import_started,
        import_finished=import_finished,
    )
    assert (
        _snapshot_positions(
            account_id=account_id,
            portfolio_id=portfolio.id,
        )
        == positions_before
    )
    assert not SimulatedTradeModel._default_manager.filter(
        account_id=account_id,
    ).exists()


@pytest.mark.django_db
def test_actual_broker_fact_survives_recommendation_matcher_service_failure(
    owner_portfolio: tuple[User, PortfolioModel],
) -> None:
    """Keep the broker execution fact when recommendation matching fails."""
    user, portfolio = owner_portfolio
    PortfolioApiRepository().ensure_real_account(portfolio)
    matcher = FailingExecutionMatcher()
    import_started = timezone.now()

    result = ManualTradeImportUseCase(
        execution_matcher=matcher,
    ).confirm(
        user_id=user.id,
        portfolio_id=portfolio.id,
        broker_name=BROKER_NAME,
        filename="matcher-service-failure.csv",
        content=_broker_csv(
            action="buy",
            asset_code="000002.SZ",
            shares=10,
            external_trade_id="actual-buy-matcher-failure",
        ),
    )
    import_finished = timezone.now()

    _assert_import_fact_preserved(
        portfolio=portfolio,
        result=result,
        action="buy",
        asset_code="000002.SZ",
        shares=10,
        external_trade_id="actual-buy-matcher-failure",
        import_started=import_started,
        import_finished=import_finished,
    )
    assert matcher.calls == 1
