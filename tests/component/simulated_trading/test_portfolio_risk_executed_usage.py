"""Database-boundary tests for exact and incomplete execution-capacity reads."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from uuid import uuid4

import pytest
from django.db import transaction

from apps.simulated_trading.infrastructure.execution_settlement_uow_repository import (
    DjangoSimulatedTradeExecutionRepository,
)
from apps.simulated_trading.infrastructure.portfolio_risk_resource_repository import (
    DjangoPortfolioRiskResourceRepository,
)
from apps.simulated_trading.infrastructure.simulated_account_trade_models import (
    SimulatedAccountModel,
    SimulatedTradeModel,
)
from tests.component.simulated_trading.test_execution_settlement_uow import (
    AS_OF,
    _Clock,
    _current_v3_plan,
)
from tests.component.simulated_trading.test_execution_settlement_uow import ledger as ledger
from tests.component.simulated_trading.test_order_reservation_repository import (
    _bundle_for_security,
    _Harness,
    _intent_for,
)
from tests.component.simulated_trading.test_order_reservation_repository import (
    reservation_harness as reservation_harness,
)

pytestmark = pytest.mark.django_db(
    transaction=True,
    available_apps=[
        "apps.simulated_trading",
        "django.contrib.auth",
        "django.contrib.contenttypes",
    ],
)


class _NoObserverGrants:
    """No observer lookup is needed by the repository usage query under test."""

    def has_valid_grant(self, owner_user_id: int, observer_user_id: int) -> bool:
        """Keep this fixture closed to delegated users."""

        del owner_user_id, observer_user_id
        return False


def _create_legacy_trade(
    *,
    account: SimulatedAccountModel,
    asset_code: str,
    session: date,
    security_id: str | None,
    settlement_session: date | None,
) -> SimulatedTradeModel:
    """Persist a synthetic legacy row with incomplete settlement scope."""

    return SimulatedTradeModel._default_manager.create(
        account=account,
        asset_code=asset_code,
        asset_name=asset_code,
        asset_type="equity",
        action="buy",
        quantity=Decimal("10"),
        price=Decimal("10"),
        amount=Decimal("100"),
        total_cost=Decimal("100"),
        order_date=session,
        execution_date=session,
        status="executed",
        settlement_security_id=security_id,
        settlement_market_session=settlement_session,
    )


def _create_exact_trade(
    harness: _Harness,
    *,
    key: str,
) -> SimulatedTradeModel:
    """Create one synthetic exact execution through the current-purpose trade UoW."""

    repository = DjangoSimulatedTradeExecutionRepository(using="default")
    intent = _intent_for(
        harness,
        key=key,
        quantity=Decimal("10"),
        price=Decimal("10"),
        security_id="SSE:601398",
        asset_code="601398",
    )
    source_bundle = _bundle_for_security("SSE:601398")
    plan, bundle, _identity = _current_v3_plan(
        repository=repository,
        intent=intent,
        as_of=AS_OF,
        source_exchange="SH",
        bundle=source_bundle,
    )
    result = repository.execute_trade(
        plan=plan,
        execution_bundle=bundle,
        clock=_Clock(AS_OF),
    )
    row = SimulatedTradeModel.objects.get(pk=result.trade_id)
    assert row.settlement_plan_binding_version == 3
    return row


def test_repository_retains_identifiable_legacy_usage_as_asset_scoped_incomplete(
    reservation_harness: _Harness,
) -> None:
    """The ORM reader retains a legacy row beside a complete UoW-backed trade."""

    account = reservation_harness.account
    exact = _create_exact_trade(
        reservation_harness,
        key=f"risk-usage-exact-{uuid4().hex}",
    )
    session = exact.execution_date
    assert exact.settlement_market_session == session
    legacy = _create_legacy_trade(
        account=account,
        asset_code="600036",
        session=session,
        security_id=None,
        settlement_session=None,
    )
    repository = DjangoPortfolioRiskResourceRepository(
        observer_grant_repository=_NoObserverGrants(),
        using="default",
    )

    with transaction.atomic():
        usage, complete = repository._read_executed_usage(
            account_id=account.pk,
            execution_session=session,
        )

    by_asset = {item.asset_code: item for item in usage}
    assert complete is False
    assert set(by_asset) == {"600036", "601398"}
    assert by_asset[legacy.asset_code].security_id is None
    assert by_asset[legacy.asset_code].execution_session is None
    assert by_asset[legacy.asset_code].quantity == Decimal("10")
    assert by_asset[legacy.asset_code].amount == Decimal("100")
    assert by_asset[legacy.asset_code].complete is False
    assert by_asset[exact.asset_code].security_id == "SSE:601398"
    assert by_asset[exact.asset_code].execution_session == session
    assert by_asset[exact.asset_code].quantity == Decimal("10")
    assert by_asset[exact.asset_code].amount == Decimal("100")
    assert by_asset[exact.asset_code].complete is True
