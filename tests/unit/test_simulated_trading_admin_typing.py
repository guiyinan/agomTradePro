from decimal import Decimal
from types import SimpleNamespace

from django.contrib import admin

from apps.simulated_trading.interface.admin import (
    FeeConfigAdmin,
    SimulatedTradingAdminSite,
)
from apps.simulated_trading.models import FeeConfigModel


def test_admin_display_metadata_uses_supported_django_decorator() -> None:
    """Display columns should publish metadata without dynamic attribute mutation."""

    assert FeeConfigAdmin.commission_rate_buy_display.short_description == "买入费率"
    assert FeeConfigAdmin.commission_rate_sell_display.short_description == "卖出费率"
    assert FeeConfigAdmin.stamp_duty_rate_display.short_description == "印花税率"


def test_fee_admin_display_methods_remain_callable() -> None:
    """Typing the admin model must not change its runtime display behavior."""

    model_admin = FeeConfigAdmin(FeeConfigModel, admin.site)
    config = SimpleNamespace(
        commission_rate_buy=Decimal("0.0003"),
        commission_rate_sell=Decimal("0.0003"),
        stamp_duty_rate=Decimal("0.001"),
    )

    assert model_admin.commission_rate_buy_display(config) == "3.0%"
    assert model_admin.commission_rate_sell_display(config) == "3.0%"
    assert model_admin.stamp_duty_rate_display(config) == "0.1%"


def test_custom_admin_site_keeps_dashboard_route() -> None:
    """The runtime-safe typed base must preserve custom AdminSite URLs."""

    site = SimulatedTradingAdminSite(name="simulated-trading-test")

    assert any(pattern.name == "dashboard" for pattern in site.get_urls())
