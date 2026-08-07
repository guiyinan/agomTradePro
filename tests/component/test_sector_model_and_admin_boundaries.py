from datetime import date
from decimal import Decimal

import pytest
from django.contrib import admin
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.test import RequestFactory

from apps.sector.infrastructure.models import (
    SectorConstituentModel,
    SectorIndexModel,
    SectorInfoModel,
    SectorPreferenceConfigModel,
    SectorRelativeStrengthModel,
)
from apps.sector.interface.admin import (
    SectorIndexAdmin,
    SectorInfoAdmin,
    SectorPreferenceConfigAdmin,
    SectorRelativeStrengthAdmin,
)


def _index(**overrides):
    values = {
        "sector_code": "801010",
        "trade_date": date(2026, 7, 29),
        "open_price": Decimal("1000"),
        "high": Decimal("1020"),
        "low": Decimal("990"),
        "close": Decimal("1010"),
        "volume": 1000,
        "amount": Decimal("1000000"),
        "change_pct": 1.0,
        "turnover_rate": 2.0,
    }
    values.update(overrides)
    return SectorIndexModel(**values)


@pytest.mark.django_db
def test_sector_hierarchy_rejects_missing_or_self_parent():
    with pytest.raises(ValidationError, match="SW2 sectors require a parent"):
        SectorInfoModel.objects.create(
            sector_code="801010.I1",
            sector_name="二级行业",
            level="SW2",
        )
    with pytest.raises(ValidationError, match="cannot be its own parent"):
        SectorInfoModel.objects.create(
            sector_code="801010.I1",
            sector_name="二级行业",
            level="SW2",
            parent_code="801010.I1",
        )
    with pytest.raises(ValidationError, match="SW1 sectors cannot have a parent"):
        SectorInfoModel.objects.create(
            sector_code="801010",
            sector_name="一级行业",
            level="SW1",
            parent_code="800000",
        )


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"close": Decimal("NaN")}, "finite and positive"),
        ({"volume": True}, "cannot be a boolean"),
        ({"amount": Decimal("-1")}, "finite and non-negative"),
        ({"turnover_rate": float("inf")}, "finite and non-negative"),
        ({"low": Decimal("1011")}, "internally inconsistent"),
        ({"high": Decimal("1005")}, "internally inconsistent"),
    ],
)
def test_sector_index_rejects_invalid_market_evidence(overrides, message):
    with pytest.raises(ValidationError, match=message):
        _index(**overrides).save()

    assert SectorIndexModel.objects.count() == 0


@pytest.mark.django_db
def test_constituent_membership_rejects_invalid_interval_and_current_flag():
    with pytest.raises(ValidationError, match="cannot precede"):
        SectorConstituentModel.objects.create(
            sector_code="801010",
            stock_code="000001.SZ",
            enter_date=date(2026, 7, 29),
            exit_date=date(2026, 7, 28),
            is_current=False,
        )
    with pytest.raises(ValidationError, match="must not have an exit date"):
        SectorConstituentModel.objects.create(
            sector_code="801010",
            stock_code="000001.SZ",
            enter_date=date(2026, 7, 1),
            exit_date=date(2026, 7, 28),
            is_current=True,
        )


@pytest.mark.django_db
def test_relative_strength_rejects_nonfinite_values_and_invalid_window():
    with pytest.raises(ValidationError, match="must be finite"):
        SectorRelativeStrengthModel.objects.create(
            sector_code="801010",
            trade_date=date(2026, 7, 29),
            relative_strength=float("nan"),
            momentum=1.0,
        )
    with pytest.raises(ValidationError, match="between 1 and 10000"):
        SectorRelativeStrengthModel.objects.create(
            sector_code="801010",
            trade_date=date(2026, 7, 29),
            relative_strength=1.0,
            momentum=1.0,
            momentum_window=0,
        )


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"regime": "Unknown"}, "regime is unsupported"),
        ({"weight": float("nan")}, "must be finite"),
        ({"weight": 1.01}, "between 0 and 1"),
        ({"weight": True}, "cannot be a boolean"),
    ],
)
def test_sector_preference_rejects_invalid_governance_values(overrides, message):
    values = {"regime": "Recovery", "sector_name": "银行", "weight": 0.8}
    values.update(overrides)

    with pytest.raises(ValidationError, match=message):
        SectorPreferenceConfigModel.objects.create(**values)


@pytest.mark.django_db
def test_sector_admin_uses_typed_contracts_and_locks_generated_evidence():
    request = RequestFactory().get("/admin/sector/")
    request.user = get_user_model().objects.create_superuser(
        username="sector_evidence_admin",
        password="testpass123",
        email="sector-evidence@example.com",
    )
    expected_admin_types = {
        SectorInfoModel: SectorInfoAdmin,
        SectorIndexModel: SectorIndexAdmin,
        SectorRelativeStrengthModel: SectorRelativeStrengthAdmin,
        SectorPreferenceConfigModel: SectorPreferenceConfigAdmin,
    }
    for model, admin_type in expected_admin_types.items():
        assert isinstance(admin.site._registry[model], admin_type)
    assert not admin.site.is_registered(SectorConstituentModel)

    for model in (
        SectorIndexModel,
        SectorRelativeStrengthModel,
    ):
        model_admin = admin.site._registry[model]
        assert model_admin.has_add_permission(request) is False
        assert model_admin.has_change_permission(request) is False
        assert model_admin.has_delete_permission(request) is False

    assert admin.site._registry[SectorInfoModel].has_change_permission(request) is True
    assert admin.site._registry[SectorPreferenceConfigModel].has_change_permission(request) is True
