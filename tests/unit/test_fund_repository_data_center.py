from __future__ import annotations

from datetime import date
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from apps.fund.domain.entities import FundNetValue
from apps.fund.infrastructure.models import FundNetValueModel
from apps.fund.infrastructure.repositories import DjangoFundRepository


def _make_repo() -> DjangoFundRepository:
    repo = object.__new__(DjangoFundRepository)
    repo._dc_fund_nav_repo = Mock()
    repo._provider_repo = Mock()
    repo._provider_factory = Mock()
    repo._raw_audit_repo = Mock()
    return repo


@pytest.mark.django_db
def test_get_latest_nav_prefers_data_center_fact():
    repo = _make_repo()
    repo._dc_fund_nav_repo.get_latest.return_value = SimpleNamespace(
        fund_code="110011",
        nav_date=date(2026, 3, 20),
        nav=1.235,
        acc_nav=2.468,
        daily_return=0.5,
    )

    nav = repo.get_latest_nav("110011")

    assert nav is not None
    assert nav.fund_code == "110011"
    assert nav.unit_nav == Decimal("1.235")
    assert nav.accum_nav == Decimal("2.468")


@pytest.mark.django_db
def test_save_fund_nav_mirrors_to_data_center():
    repo = _make_repo()
    nav = FundNetValue(
        fund_code="110011",
        nav_date=date(2026, 3, 20),
        unit_nav=Decimal("1.235"),
        accum_nav=Decimal("2.468"),
        daily_return=0.5,
    )

    repo.save_fund_nav(nav)

    assert FundNetValueModel.objects.filter(fund_code="110011").count() == 1
    repo._dc_fund_nav_repo.bulk_upsert.assert_called_once()
