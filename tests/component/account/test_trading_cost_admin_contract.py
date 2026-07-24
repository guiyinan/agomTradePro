"""Admin registration contracts for configurable transaction fees."""

from django.contrib import admin

from apps.account.infrastructure.models import (
    TradingCostConfigModel,
    TransactionCostConfigModel,
)
from apps.account.interface.admin import (
    TradingCostConfigModelAdmin,
    TransactionCostConfigModelAdmin,
)
from shared.infrastructure.django_admin import TypedModelAdmin


def test_transaction_fee_configs_have_typed_admin_entries() -> None:
    portfolio_admin = admin.site._registry[TradingCostConfigModel]
    market_admin = admin.site._registry[TransactionCostConfigModel]

    assert isinstance(portfolio_admin, TradingCostConfigModelAdmin)
    assert isinstance(portfolio_admin, TypedModelAdmin)
    assert isinstance(market_admin, TransactionCostConfigModelAdmin)
    assert isinstance(market_admin, TypedModelAdmin)
