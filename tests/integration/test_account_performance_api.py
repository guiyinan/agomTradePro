"""
账户业绩 API 契约测试

验证：
- 8 个端点的状态码、Content-Type、字段存在性、权限范围
- 真实盘 / 模拟盘均走同一套接口
- 观察员只读场景延续现有权限语义
- Benchmark CRUD 与权重归一化
"""
from datetime import date, timedelta
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from django.contrib.auth import get_user_model
from rest_framework import status
from rest_framework.test import APIClient

from apps.simulated_trading.infrastructure.models import (
    AccountBenchmarkComponentModel,
    AccountPositionValuationSnapshotModel,
    DailyNetValueModel,
    SimulatedAccountModel,
    UnifiedAccountCashFlowModel,
)

User = get_user_model()

pytestmark = pytest.mark.django_db


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def user(db):
    return User.objects.create_user(username="perf_tester", password="pass123")


@pytest.fixture
def other_user(db):
    return User.objects.create_user(username="other_user", password="pass456")


@pytest.fixture
def observer_user(db):
    return User.objects.create_user(username="observer_user", password="obs123")


@pytest.fixture
def observer_client(observer_user):
    c = APIClient()
    c.force_authenticate(user=observer_user)
    return c


@pytest.fixture
def observer_grant(user, observer_user):
    from apps.account.infrastructure.models import PortfolioObserverGrantModel

    grant = PortfolioObserverGrantModel(
        owner_user_id=user,
        observer_user_id=observer_user,
        status="active",
    )
    grant.save()
    return grant


@pytest.fixture
def client(user):
    c = APIClient()
    c.force_authenticate(user=user)
    return c


@pytest.fixture
def other_client(other_user):
    c = APIClient()
    c.force_authenticate(user=other_user)
    return c


@pytest.fixture
def account(user):
    return SimulatedAccountModel.objects.create(
        user=user,
        account_name="业绩测试账户",
        account_type="simulated",
        initial_capital=Decimal("100000.00"),
        current_cash=Decimal("50000.00"),
        current_market_value=Decimal("55000.00"),
        total_value=Decimal("105000.00"),
    )


@pytest.fixture
def account_with_net_values(account):
    """账户 + 7 天净值记录。"""
    start = date(2024, 1, 1)
    records = []
    for i in range(7):
        d = start + timedelta(days=i)
        total = float(account.initial_capital) * (1.0 + i * 0.001)
        records.append(
            DailyNetValueModel(
                account=account,
                record_date=d,
                net_value=Decimal(str(round(1.0 + i * 0.001, 4))),
                cash=Decimal("50000.00"),
                market_value=Decimal(str(round(total - 50000, 2))),
                daily_return=0.1,
                cumulative_return=round(i * 0.1, 2),
                drawdown=0.0,
            )
        )
    DailyNetValueModel.objects.bulk_create(records)
    return account


@pytest.fixture
def account_with_benchmarks(account):
    """账户 + 两个基准成分。"""
    AccountBenchmarkComponentModel.objects.bulk_create([
        AccountBenchmarkComponentModel(
            account=account,
            benchmark_code="000300.SH",
            weight=0.6,
            display_name="沪深300",
            sort_order=0,
        ),
        AccountBenchmarkComponentModel(
            account=account,
            benchmark_code="000905.SH",
            weight=0.4,
            display_name="中证500",
            sort_order=1,
        ),
    ])
    return account


@pytest.fixture
def account_with_cash_flows(account):
    UnifiedAccountCashFlowModel.objects.create(
        account=account,
        flow_type="initial_capital",
        amount=Decimal("100000.00"),
        flow_date=date(2024, 1, 1),
        source_app="simulated_trading",
    )
    return account


@pytest.fixture
def account_with_snapshot(account):
    AccountPositionValuationSnapshotModel.objects.create(
        account=account,
        record_date=date(2024, 6, 1),
        asset_code="000001.SZ",
        asset_name="平安银行",
        asset_type="equity",
        quantity=Decimal("1000"),
        avg_cost=Decimal("10.50"),
        close_price=Decimal("11.00"),
        market_value=Decimal("11000.00"),
        weight=0.22,
        unrealized_pnl=Decimal("500.00"),
        unrealized_pnl_pct=4.76,
    )
    return account


@pytest.fixture
def compat_portfolio(user, account):
    from apps.account.infrastructure.models import PortfolioModel
    from apps.simulated_trading.infrastructure.models import LedgerMigrationMapModel

    portfolio = PortfolioModel.objects.create(user=user, name="兼容入口组合")
    LedgerMigrationMapModel.objects.create(
        source_app="account",
        source_table="portfolio",
        source_id=portfolio.pk,
        target_table="simulated_account",
        target_id=account.pk,
    )
    return portfolio


# ---------------------------------------------------------------------------
# 辅助
# ---------------------------------------------------------------------------

BASE = "/api/simulated-trading"


def url_performance_report(account_id):
    return f"{BASE}/accounts/{account_id}/performance-report/"


def url_valuation_snapshot(account_id):
    return f"{BASE}/accounts/{account_id}/valuation-snapshot/"


def url_valuation_timeline(account_id):
    return f"{BASE}/accounts/{account_id}/valuation-timeline/"


def url_benchmarks(account_id):
    return f"{BASE}/accounts/{account_id}/benchmarks/"


def url_backfill(account_id):
    return f"{BASE}/accounts/{account_id}/backfill/"


# ---------------------------------------------------------------------------
# 公共契约：Content-Type
# ---------------------------------------------------------------------------


class TestContentType:
    def test_performance_report_returns_json(self, client, account_with_net_values):
        resp = client.get(
            url_performance_report(account_with_net_values.pk),
            {"start_date": "2024-01-01", "end_date": "2024-01-07"},
        )
        assert "application/json" in resp["Content-Type"]

    def test_valuation_snapshot_returns_json(self, client, account_with_snapshot):
        resp = client.get(
            url_valuation_snapshot(account_with_snapshot.pk),
            {"as_of_date": "2024-06-01"},
        )
        assert "application/json" in resp["Content-Type"]

    def test_valuation_timeline_returns_json(self, client, account_with_net_values):
        resp = client.get(url_valuation_timeline(account_with_net_values.pk))
        assert "application/json" in resp["Content-Type"]

    def test_benchmarks_get_returns_json(self, client, account_with_benchmarks):
        resp = client.get(url_benchmarks(account_with_benchmarks.pk))
        assert "application/json" in resp["Content-Type"]


# ---------------------------------------------------------------------------
# performance-report
# ---------------------------------------------------------------------------


class TestPerformanceReport:
    def test_200_with_valid_params(self, client, account_with_net_values):
        resp = client.get(
            url_performance_report(account_with_net_values.pk),
            {"start_date": "2024-01-01", "end_date": "2024-01-07"},
        )
        assert resp.status_code == status.HTTP_200_OK

    def test_response_has_required_fields(self, client, account_with_net_values):
        resp = client.get(
            url_performance_report(account_with_net_values.pk),
            {"start_date": "2024-01-01", "end_date": "2024-01-07"},
        )
        data = resp.json()
        for field in ["period", "returns", "risk", "ratios", "benchmark", "trade_stats", "coverage", "warnings"]:
            assert field in data, f"缺少字段: {field}"

    def test_400_missing_params(self, client, account):
        resp = client.get(url_performance_report(account.pk))
        assert resp.status_code == status.HTTP_400_BAD_REQUEST

    def test_400_bad_date_range(self, client, account):
        resp = client.get(
            url_performance_report(account.pk),
            {"start_date": "2024-12-31", "end_date": "2024-01-01"},
        )
        assert resp.status_code == status.HTTP_400_BAD_REQUEST

    def test_403_other_user_cannot_access(self, other_client, account_with_net_values):
        resp = other_client.get(
            url_performance_report(account_with_net_values.pk),
            {"start_date": "2024-01-01", "end_date": "2024-01-07"},
        )
        assert resp.status_code == status.HTTP_403_FORBIDDEN

    def test_404_nonexistent_account(self, client):
        resp = client.get(
            url_performance_report(99999),
            {"start_date": "2024-01-01", "end_date": "2024-01-07"},
        )
        assert resp.status_code == status.HTTP_404_NOT_FOUND

    def test_401_or_403_unauthenticated(self, account_with_net_values):
        c = APIClient()
        resp = c.get(
            url_performance_report(account_with_net_values.pk),
            {"start_date": "2024-01-01", "end_date": "2024-01-07"},
        )
        assert resp.status_code in (status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN)

    def test_period_fields(self, client, account_with_net_values):
        resp = client.get(
            url_performance_report(account_with_net_values.pk),
            {"start_date": "2024-01-01", "end_date": "2024-01-07"},
        )
        period = resp.json()["period"]
        assert period["start_date"] == "2024-01-01"
        assert period["end_date"] == "2024-01-07"
        assert period["days"] == 6

    def test_benchmark_metrics_are_numeric_when_market_data_available(
        self,
        client,
        account_with_net_values,
        account_with_benchmarks,
    ):
        bars = [
            SimpleNamespace(
                trade_date=date(2024, 1, 1) + timedelta(days=i),
                close=100 + i * 2,
            )
            for i in range(7)
        ]

        with patch("apps.market_data.application.registry_factory.get_registry") as mock_get_registry:
            mock_get_registry.return_value.call_with_failover.return_value = bars
            resp = client.get(
                url_performance_report(account_with_net_values.pk),
                {"start_date": "2024-01-01", "end_date": "2024-01-07"},
            )

        assert resp.status_code == status.HTTP_200_OK
        data = resp.json()
        benchmark = data["benchmark"]
        assert benchmark["benchmark_return"] is not None
        assert benchmark["beta"] is not None
        assert benchmark["alpha"] is not None
        assert benchmark["tracking_error"] is not None
        assert benchmark["information_ratio"] is not None


# ---------------------------------------------------------------------------
# valuation-snapshot
# ---------------------------------------------------------------------------


class TestValuationSnapshot:
    def test_200_with_rows(self, client, account_with_snapshot):
        resp = client.get(
            url_valuation_snapshot(account_with_snapshot.pk),
            {"as_of_date": "2024-06-01"},
        )
        assert resp.status_code == status.HTTP_200_OK
        data = resp.json()
        for field in ["as_of_date", "account_summary", "rows", "coverage"]:
            assert field in data

    def test_rows_structure(self, client, account_with_snapshot):
        resp = client.get(
            url_valuation_snapshot(account_with_snapshot.pk),
            {"as_of_date": "2024-06-01"},
        )
        rows = resp.json()["rows"]
        assert len(rows) == 1
        row = rows[0]
        for field in ["asset_code", "asset_name", "asset_type", "quantity", "avg_cost",
                       "close_price", "market_value", "weight", "unrealized_pnl", "unrealized_pnl_pct"]:
            assert field in row

    def test_empty_rows_with_warning(self, client, account):
        resp = client.get(
            url_valuation_snapshot(account.pk),
            {"as_of_date": "2024-01-01"},
        )
        assert resp.status_code == status.HTTP_200_OK
        data = resp.json()
        assert data["rows"] == []
        assert len(data["coverage"]["warnings"]) > 0

    def test_400_missing_as_of_date(self, client, account):
        resp = client.get(url_valuation_snapshot(account.pk))
        assert resp.status_code == status.HTTP_400_BAD_REQUEST

    def test_403_other_user(self, other_client, account_with_snapshot):
        resp = other_client.get(
            url_valuation_snapshot(account_with_snapshot.pk),
            {"as_of_date": "2024-06-01"},
        )
        assert resp.status_code == status.HTTP_403_FORBIDDEN


# ---------------------------------------------------------------------------
# valuation-timeline
# ---------------------------------------------------------------------------


class TestValuationTimeline:
    def test_200_with_points(self, client, account_with_net_values):
        resp = client.get(url_valuation_timeline(account_with_net_values.pk))
        assert resp.status_code == status.HTTP_200_OK
        data = resp.json()
        assert "points" in data

    def test_point_fields(self, client, account_with_net_values):
        resp = client.get(url_valuation_timeline(account_with_net_values.pk))
        points = resp.json()["points"]
        assert len(points) > 0
        pt = points[0]
        for field in ["date", "cash", "market_value", "total_value", "net_value", "twr_cumulative", "drawdown"]:
            assert field in pt, f"缺少字段: {field}"

    def test_empty_timeline_returns_empty_points(self, client, account):
        resp = client.get(url_valuation_timeline(account.pk))
        assert resp.status_code == status.HTTP_200_OK
        assert resp.json()["points"] == []

    def test_403_other_user(self, other_client, account_with_net_values):
        resp = other_client.get(url_valuation_timeline(account_with_net_values.pk))
        assert resp.status_code == status.HTTP_403_FORBIDDEN


# ---------------------------------------------------------------------------
# benchmarks GET|PUT
# ---------------------------------------------------------------------------


class TestBenchmarksGET:
    def test_200_returns_list(self, client, account_with_benchmarks):
        resp = client.get(url_benchmarks(account_with_benchmarks.pk))
        assert resp.status_code == status.HTTP_200_OK
        data = resp.json()
        assert isinstance(data, list)
        assert len(data) == 2

    def test_benchmark_fields(self, client, account_with_benchmarks):
        resp = client.get(url_benchmarks(account_with_benchmarks.pk))
        item = resp.json()[0]
        for field in ["account_id", "benchmark_code", "weight", "display_name", "sort_order", "is_active"]:
            assert field in item

    def test_empty_list_when_no_benchmarks(self, client, account):
        resp = client.get(url_benchmarks(account.pk))
        assert resp.status_code == status.HTTP_200_OK
        assert resp.json() == []


class TestBenchmarksPUT:
    def test_200_creates_benchmarks(self, client, account):
        payload = {
            "components": [
                {"benchmark_code": "000300.SH", "weight": 0.6, "display_name": "沪深300"},
                {"benchmark_code": "000905.SH", "weight": 0.4, "display_name": "中证500"},
            ]
        }
        resp = client.put(url_benchmarks(account.pk), data=payload, format="json")
        assert resp.status_code == status.HTTP_200_OK
        components = resp.json()
        assert len(components) == 2
        weights = [c["weight"] for c in components]
        assert abs(sum(weights) - 1.0) < 1e-6

    def test_weight_normalization(self, client, account):
        """权重应被归一化，原始权重 3:1 应变为 0.75:0.25"""
        payload = {
            "components": [
                {"benchmark_code": "000300.SH", "weight": 3.0},
                {"benchmark_code": "000905.SH", "weight": 1.0},
            ]
        }
        resp = client.put(url_benchmarks(account.pk), data=payload, format="json")
        assert resp.status_code == status.HTTP_200_OK
        components = {c["benchmark_code"]: c["weight"] for c in resp.json()}
        assert components["000300.SH"] == pytest.approx(0.75, abs=1e-6)
        assert components["000905.SH"] == pytest.approx(0.25, abs=1e-6)

    def test_400_empty_components(self, client, account):
        resp = client.put(url_benchmarks(account.pk), data={"components": []}, format="json")
        assert resp.status_code == status.HTTP_400_BAD_REQUEST

    def test_put_replaces_existing(self, client, account_with_benchmarks):
        """PUT 应完全替换现有配置"""
        payload = {
            "components": [
                {"benchmark_code": "000001.SH", "weight": 1.0, "display_name": "上证指数"},
            ]
        }
        resp = client.put(url_benchmarks(account_with_benchmarks.pk), data=payload, format="json")
        assert resp.status_code == status.HTTP_200_OK
        assert len(resp.json()) == 1
        assert resp.json()[0]["benchmark_code"] == "000001.SH"

    def test_403_other_user_put(self, other_client, account):
        payload = {"components": [{"benchmark_code": "000300.SH", "weight": 1.0}]}
        resp = other_client.put(url_benchmarks(account.pk), data=payload, format="json")
        assert resp.status_code == status.HTTP_403_FORBIDDEN


# ---------------------------------------------------------------------------
# backfill (admin only)
# ---------------------------------------------------------------------------


class TestBackfill:
    def test_403_for_non_staff(self, client, account):
        resp = client.post(url_backfill(account.pk))
        assert resp.status_code == status.HTTP_403_FORBIDDEN

    def test_200_for_staff(self, account):
        admin = User.objects.create_user(username="admin_bf", password="pass", is_staff=True)
        c = APIClient()
        c.force_authenticate(user=admin)
        resp = c.post(url_backfill(account.pk))
        assert resp.status_code == status.HTTP_200_OK
        data = resp.json()
        assert "account_id" in data
        assert "dnv_record_count" in data
        assert "mirrored_capital_flows" in data

    def test_404_for_nonexistent_account(self):
        admin = User.objects.create_user(username="admin_bf2", password="pass", is_staff=True)
        c = APIClient()
        c.force_authenticate(user=admin)
        resp = c.post(url_backfill(99999))
        assert resp.status_code == status.HTTP_404_NOT_FOUND


# ---------------------------------------------------------------------------
# 观察员只读访问
# ---------------------------------------------------------------------------


class TestObserverAccess:
    """
    验证持有有效 PortfolioObserverGrantModel 的观察员可以 GET 所有业绩端点，
    但不能 PUT（写操作）。
    """

    def test_observer_can_get_performance_report(
        self, observer_client, observer_grant, account_with_net_values
    ):
        resp = observer_client.get(
            url_performance_report(account_with_net_values.pk),
            {"start_date": "2024-01-01", "end_date": "2024-01-07"},
        )
        assert resp.status_code == status.HTTP_200_OK

    def test_observer_can_get_valuation_snapshot(
        self, observer_client, observer_grant, account_with_snapshot
    ):
        resp = observer_client.get(
            url_valuation_snapshot(account_with_snapshot.pk),
            {"as_of_date": "2024-06-01"},
        )
        assert resp.status_code == status.HTTP_200_OK

    def test_observer_can_get_valuation_timeline(
        self, observer_client, observer_grant, account_with_net_values
    ):
        resp = observer_client.get(url_valuation_timeline(account_with_net_values.pk))
        assert resp.status_code == status.HTTP_200_OK

    def test_observer_can_get_benchmarks(
        self, observer_client, observer_grant, account_with_benchmarks
    ):
        resp = observer_client.get(url_benchmarks(account_with_benchmarks.pk))
        assert resp.status_code == status.HTTP_200_OK

    def test_observer_cannot_put_benchmarks(
        self, observer_client, observer_grant, account
    ):
        """观察员只读，PUT 应被拒绝。"""
        payload = {"components": [{"benchmark_code": "000300.SH", "weight": 1.0}]}
        resp = observer_client.put(
            url_benchmarks(account.pk), data=payload, format="json"
        )
        assert resp.status_code == status.HTTP_403_FORBIDDEN

    def test_revoked_grant_denies_access(
        self, observer_user, user, account_with_net_values
    ):
        """已撤销的授权不应授予访问权限。"""
        from apps.account.infrastructure.models import PortfolioObserverGrantModel

        grant = PortfolioObserverGrantModel(
            owner_user_id=user,
            observer_user_id=observer_user,
            status="active",
        )
        grant.save()
        # 直接 update 绕过 save() 的 full_clean，模拟撤销
        PortfolioObserverGrantModel.objects.filter(pk=grant.pk).update(status="revoked")

        c = APIClient()
        c.force_authenticate(user=observer_user)
        resp = c.get(
            url_performance_report(account_with_net_values.pk),
            {"start_date": "2024-01-01", "end_date": "2024-01-07"},
        )
        assert resp.status_code == status.HTTP_403_FORBIDDEN


# ---------------------------------------------------------------------------
# 兼容 API（account app）
# ---------------------------------------------------------------------------


COMPAT_BASE = "/api/account"


class TestCompatAPI:
    """
    验证 /api/account/portfolios/{id}/xxx/ 兼容入口：
    未映射时应返回 404，已映射时应委托正确处理。
    """

    def test_performance_report_compat_404_when_no_mapping(self, client):
        resp = client.get(
            f"{COMPAT_BASE}/portfolios/99999/performance-report/",
            {"start_date": "2024-01-01", "end_date": "2024-01-07"},
        )
        assert resp.status_code == status.HTTP_404_NOT_FOUND

    def test_valuation_snapshot_compat_404_when_no_mapping(self, client):
        resp = client.get(
            f"{COMPAT_BASE}/portfolios/99999/valuation-snapshot/",
            {"as_of_date": "2024-01-01"},
        )
        assert resp.status_code == status.HTTP_404_NOT_FOUND

    def test_valuation_timeline_compat_404_when_no_mapping(self, client):
        resp = client.get(f"{COMPAT_BASE}/portfolios/99999/valuation-timeline/")
        assert resp.status_code == status.HTTP_404_NOT_FOUND

    def test_benchmarks_compat_404_when_no_mapping(self, client):
        resp = client.get(f"{COMPAT_BASE}/portfolios/99999/benchmarks/")
        assert resp.status_code == status.HTTP_404_NOT_FOUND

    def test_401_or_403_unauthenticated_compat(self):
        c = APIClient()
        resp = c.get(f"{COMPAT_BASE}/portfolios/1/performance-report/")
        assert resp.status_code in (status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN)

    def test_observer_can_get_performance_report_via_compat(
        self,
        observer_client,
        observer_grant,
        compat_portfolio,
        account_with_net_values,
    ):
        resp = observer_client.get(
            f"{COMPAT_BASE}/portfolios/{compat_portfolio.pk}/performance-report/",
            {"start_date": "2024-01-01", "end_date": "2024-01-07"},
        )
        assert resp.status_code == status.HTTP_200_OK

    def test_observer_can_get_valuation_snapshot_via_compat(
        self,
        observer_client,
        observer_grant,
        compat_portfolio,
        account_with_snapshot,
    ):
        resp = observer_client.get(
            f"{COMPAT_BASE}/portfolios/{compat_portfolio.pk}/valuation-snapshot/",
            {"as_of_date": "2024-06-01"},
        )
        assert resp.status_code == status.HTTP_200_OK

    def test_observer_can_get_valuation_timeline_via_compat(
        self,
        observer_client,
        observer_grant,
        compat_portfolio,
        account_with_net_values,
    ):
        resp = observer_client.get(
            f"{COMPAT_BASE}/portfolios/{compat_portfolio.pk}/valuation-timeline/"
        )
        assert resp.status_code == status.HTTP_200_OK

    def test_observer_can_get_benchmarks_via_compat(
        self,
        observer_client,
        observer_grant,
        compat_portfolio,
        account_with_benchmarks,
    ):
        resp = observer_client.get(
            f"{COMPAT_BASE}/portfolios/{compat_portfolio.pk}/benchmarks/"
        )
        assert resp.status_code == status.HTTP_200_OK

    def test_observer_cannot_put_benchmarks_via_compat(
        self,
        observer_client,
        observer_grant,
        compat_portfolio,
        account,
    ):
        payload = {"components": [{"benchmark_code": "000300.SH", "weight": 1.0}]}
        resp = observer_client.put(
            f"{COMPAT_BASE}/portfolios/{compat_portfolio.pk}/benchmarks/",
            data=payload,
            format="json",
        )
        assert resp.status_code == status.HTTP_403_FORBIDDEN
