from __future__ import annotations

from datetime import date
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from apps.fund.domain.entities import FundNetValue
from apps.fund.domain.services import FundPerformanceCalculator
from apps.fund.infrastructure.models import FundInfoModel, FundPerformanceModel
from apps.fund.infrastructure.repositories import DjangoFundRepository


def _make_repo() -> DjangoFundRepository:
    repo = object.__new__(DjangoFundRepository)
    repo._dc_fund_nav_repo = Mock()
    repo._dc_fund_nav_repo.get_series.return_value = []
    repo._provider_repo = Mock()
    repo._provider_repo.get_active_by_type.return_value = []
    repo._provider_registry = Mock()
    repo._raw_audit_repo = Mock()
    repo._perf_calculator = FundPerformanceCalculator()
    return repo


@pytest.mark.django_db
def test_get_latest_nav_uses_published_fund_nav(monkeypatch):
    repo = _make_repo()
    monkeypatch.setattr(
        "apps.fund.infrastructure.repositories.get_published_fund_nav_series",
        lambda *args, **kwargs: {
            "rows": [
                {
                    "fund_code": "110011",
                    "nav_date": "2026-03-20",
                    "nav": 1.235,
                    "acc_nav": 2.468,
                    "daily_return": 0.5,
                }
            ],
            "must_not_use_for_decision": False,
        },
    )

    nav = repo.get_latest_nav("110011")

    assert nav is not None
    assert nav.fund_code == "110011"
    assert nav.unit_nav == Decimal("1.235")
    assert nav.accum_nav == Decimal("2.468")
    repo._dc_fund_nav_repo.get_latest.assert_not_called()


@pytest.mark.django_db
def test_get_latest_nav_blocks_rows_when_publication_is_unusable(monkeypatch):
    repo = _make_repo()
    monkeypatch.setattr(
        "apps.fund.infrastructure.repositories.get_published_fund_nav_series",
        lambda *args, **kwargs: {
            "rows": [
                {
                    "fund_code": "110011",
                    "nav_date": "2026-03-20",
                    "nav": 1.235,
                    "acc_nav": 2.468,
                }
            ],
            "must_not_use_for_decision": True,
            "blocked_reason": "publication_stale",
        },
    )

    assert repo.get_latest_nav("110011") is None
    repo._dc_fund_nav_repo.get_latest.assert_not_called()


@pytest.mark.django_db
def test_save_fund_nav_writes_only_to_data_center():
    repo = _make_repo()
    nav = FundNetValue(
        fund_code="110011",
        nav_date=date(2026, 3, 20),
        unit_nav=Decimal("1.235"),
        accum_nav=Decimal("2.468"),
        daily_return=0.5,
    )

    repo.save_fund_nav(nav)

    repo._dc_fund_nav_repo.bulk_upsert.assert_called_once()


@pytest.mark.django_db
def test_get_or_build_fund_performance_builds_from_local_nav_and_persists():
    repo = _make_repo()
    repo.sync_fund_nav_from_tushare = Mock(return_value=0)

    repo._dc_fund_nav_repo.get_series.return_value = [
        SimpleNamespace(
            fund_code="110011",
            nav_date=date(2026, 3, 20),
            nav=1.1,
            acc_nav=1.1,
            daily_return=None,
        ),
        SimpleNamespace(
            fund_code="110011",
            nav_date=date(2026, 3, 19),
            nav=1.0,
            acc_nav=1.0,
            daily_return=None,
        ),
    ]

    performance = repo.get_or_build_fund_performance(
        "110011",
        start_date=date(2026, 3, 1),
        end_date=date(2026, 3, 31),
        allow_remote_sync=False,
    )

    assert performance is not None
    assert performance.fund_code == "110011"
    assert round(performance.total_return, 2) == 10.00
    assert FundPerformanceModel.objects.filter(fund_code="110011").count() == 1


@pytest.mark.django_db
def test_get_or_build_fund_performance_reuses_nearby_snapshot():
    repo = _make_repo()

    FundPerformanceModel.objects.create(
        fund_code="110011",
        start_date=date(2025, 5, 5),
        end_date=date(2026, 5, 3),
        total_return=12.5,
        annualized_return=12.1,
        volatility=8.5,
        sharpe_ratio=1.1,
        max_drawdown=4.0,
    )

    performance = repo.get_or_build_fund_performance(
        "110011",
        start_date=date(2025, 5, 4),
        end_date=date(2026, 5, 4),
        allow_remote_sync=False,
    )

    assert performance is not None
    assert performance.start_date == date(2025, 5, 5)
    assert performance.end_date == date(2026, 5, 3)


@pytest.mark.django_db
def test_ensure_fund_universe_seeded_syncs_when_local_master_is_empty():
    repo = _make_repo()
    repo.sync_fund_info_from_tushare = Mock(return_value=42)

    synced_count = repo.ensure_fund_universe_seeded()

    assert synced_count == 42
    repo.sync_fund_info_from_tushare.assert_called_once()


@pytest.mark.django_db
def test_ensure_fund_universe_seeded_skips_when_local_master_exists():
    repo = _make_repo()
    repo.sync_fund_info_from_tushare = Mock(return_value=42)
    FundInfoModel.objects.create(
        fund_code="110011",
        fund_name="示例基金",
        fund_type="混合型",
        fund_scale=Decimal("100000000"),
    )

    synced_count = repo.ensure_fund_universe_seeded()

    assert synced_count == 0
    repo.sync_fund_info_from_tushare.assert_not_called()


@pytest.mark.django_db
def test_resolve_research_window_anchors_to_latest_available_performance_end_date():
    repo = _make_repo()
    FundPerformanceModel.objects.create(
        fund_code="110011",
        start_date=date(2024, 1, 1),
        end_date=date(2024, 12, 31),
        total_return=8.0,
        annualized_return=8.0,
        volatility=5.0,
        sharpe_ratio=1.0,
        max_drawdown=2.0,
    )

    start_date, end_date = repo.resolve_research_window(
        requested_end_date=date(2026, 5, 4),
        lookback_days=365,
    )

    assert end_date == date(2024, 12, 31)
    assert start_date == date(2024, 1, 1)
