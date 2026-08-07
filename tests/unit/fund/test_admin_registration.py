"""Fund Admin discovery and display regressions."""

from __future__ import annotations

from decimal import Decimal
from types import SimpleNamespace
from typing import cast

from django.contrib import admin

from apps.fund.interface.admin import (
    FundHoldingAdmin,
    FundInfoAdmin,
    FundManagerAdmin,
    FundPerformanceAdmin,
    FundSectorAllocationAdmin,
)
from apps.fund.models import (
    FundHoldingModel,
    FundInfoModel,
    FundManagerModel,
    FundNetValueModel,
    FundPerformanceModel,
    FundSectorAllocationModel,
)
from shared.infrastructure.django_admin import TypedModelAdmin


def test_fund_models_are_registered_by_the_interface_admin() -> None:
    """Django autodiscovery exposes every Fund model through one typed owner."""

    expected = {
        FundInfoModel: FundInfoAdmin,
        FundManagerModel: FundManagerAdmin,
        FundHoldingModel: FundHoldingAdmin,
        FundSectorAllocationModel: FundSectorAllocationAdmin,
        FundPerformanceModel: FundPerformanceAdmin,
    }
    for model, admin_class in expected.items():
        assert admin.site.is_registered(model)
        assert isinstance(admin.site._registry[model], admin_class)
        assert issubclass(admin_class, TypedModelAdmin)
    assert not admin.site.is_registered(FundNetValueModel)


def test_fund_amount_displays_keep_canonical_yuan_scaling() -> None:
    """Admin formatting preserves the stored-yuan unit contract."""

    info_admin = cast(FundInfoAdmin, admin.site._registry[FundInfoModel])
    holding_admin = cast(FundHoldingAdmin, admin.site._registry[FundHoldingModel])

    assert (
        info_admin.fund_scale_display(
            cast(FundInfoModel, SimpleNamespace(fund_scale=Decimal("250000000")))
        )
        == "2.50亿"
    )
    assert (
        holding_admin.holding_value_display(
            cast(FundHoldingModel, SimpleNamespace(holding_value=Decimal("350000")))
        )
        == "35万"
    )
    assert (
        info_admin.fund_scale_display(cast(FundInfoModel, SimpleNamespace(fund_scale=None))) == "-"
    )
