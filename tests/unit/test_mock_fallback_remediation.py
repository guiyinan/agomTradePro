from __future__ import annotations

import json
import shutil
import tempfile
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path

import pytest
from django.core.cache import cache
from django.core.management.base import CommandError

from apps.account.management.commands.bootstrap_mcp_cold_start import (
    Command as BootstrapMcpColdStartCommand,
)
from apps.dashboard.application.queries import AlphaVisualizationQuery
from apps.rotation.infrastructure.adapters.price_adapter import RotationPriceDataService
from apps.sector.application.use_cases import (
    AnalyzeSectorRotationRequest,
    AnalyzeSectorRotationUseCase,
)
from apps.sector.domain.entities import SectorIndex, SectorInfo
from shared.infrastructure.config_loader import get_asset_ticker, get_indicator_config
from shared.infrastructure.models import SectorPreferenceConfigModel


class _FakeSectorRepo:
    def __init__(self, sector_code: str = "801010"):
        self._sector = SectorInfo(sector_code=sector_code, sector_name="农林牧渔", level="SW1")
        base_date = date.today()
        self._indices = [
            SectorIndex(
                sector_code=sector_code,
                trade_date=base_date - timedelta(days=1),
                open_price=Decimal("100"),
                high=Decimal("102"),
                low=Decimal("99"),
                close=Decimal("101"),
                volume=1000,
                amount=Decimal("100000"),
                change_pct=1.0,
            ),
            SectorIndex(
                sector_code=sector_code,
                trade_date=base_date,
                open_price=Decimal("101"),
                high=Decimal("103"),
                low=Decimal("100"),
                close=Decimal("102"),
                volume=1100,
                amount=Decimal("120000"),
                change_pct=0.8,
            ),
        ]

    def get_all_sectors(self, level: str):
        return [self._sector]

    def get_sector_index_range(self, sector_code: str, start_date: date, end_date: date):
        return self._indices


class _UnavailableMarketAdapter:
    def get_index_daily_returns(self, index_code: str, start_date: date, end_date: date):
        return {}


@pytest.mark.django_db
def test_alpha_visualization_query_returns_unavailable_ic_trends_without_live_models():
    data = AlphaVisualizationQuery().execute(top_n=5, ic_days=3)

    assert len(data.ic_trends) == 3
    assert all(item["ic"] is None for item in data.ic_trends)
    assert data.ic_trends_meta["status"] == "unavailable"
    assert data.ic_trends_meta["data_source"] == "fallback"
    assert data.ic_trends_meta["warning_message"] == "ic_trends_unavailable"


def test_rotation_price_service_returns_none_when_market_data_unavailable(monkeypatch):
    """RotationPriceDataService 在 market_data 数据中台全部失败时返回 None"""
    monkeypatch.setattr(
        RotationPriceDataService,
        "_fetch_from_data_center",
        staticmethod(lambda asset_code, end_date, days_back: None),
    )
    service = RotationPriceDataService()
    result = service.get_prices("510300", date.today(), 5)

    assert result is None


@pytest.mark.django_db
def test_sector_rotation_returns_unavailable_when_market_returns_missing():
    SectorPreferenceConfigModel.objects.create(
        regime="Recovery",
        sector_name="农林牧渔",
        weight=0.8,
        is_active=True,
    )
    use_case = AnalyzeSectorRotationUseCase(
        sector_repo=_FakeSectorRepo(),
        market_adapter=_UnavailableMarketAdapter(),
    )

    result = use_case.execute(
        AnalyzeSectorRotationRequest(
            regime="Recovery",
            lookback_days=5,
            top_n=5,
        )
    )

    assert result.success is False
    assert result.status == "unavailable"
    assert result.data_source == "fallback"
    assert result.warning_message == "market_returns_unavailable"
    assert "沪深300真实收益率数据" in (result.error or "")


@pytest.mark.django_db
def test_config_loader_disables_legacy_fallback_by_default_in_production_like_env(monkeypatch, settings):
    cache.clear()
    settings.DEBUG = False
    settings.ALLOW_LEGACY_CONFIG_FALLBACK = False
    monkeypatch.setenv("DJANGO_SETTINGS_MODULE", "core.settings.production")

    assert get_asset_ticker("a_share_growth") is None
    assert get_indicator_config("CN_PMI") is None


@pytest.mark.django_db
def test_config_loader_allows_legacy_fallback_in_debug(monkeypatch, settings):
    cache.clear()
    settings.DEBUG = True
    settings.ALLOW_LEGACY_CONFIG_FALLBACK = False
    monkeypatch.setenv("DJANGO_SETTINGS_MODULE", "core.settings.development")

    assert get_asset_ticker("a_share_growth") == "000300.SH"
    indicator = get_indicator_config("CN_PMI")
    assert indicator is not None
    assert indicator["threshold_bullish"] == 50


def test_bootstrap_mcp_cold_start_rejects_production_like_env(monkeypatch, settings):
    settings.DEBUG = False
    monkeypatch.setenv("DJANGO_SETTINGS_MODULE", "core.settings.production")

    command = BootstrapMcpColdStartCommand()

    with pytest.raises(CommandError):
        command._assert_dev_only_environment()


def test_bootstrap_mcp_cold_start_allows_test_env(monkeypatch, settings):
    settings.DEBUG = False
    monkeypatch.setenv("DJANGO_SETTINGS_MODULE", "core.settings.test")

    command = BootstrapMcpColdStartCommand()

    command._assert_dev_only_environment()


def test_train_command_save_model_writes_real_metrics():
    from apps.alpha.management.commands.train_qlib_model import Command

    command = Command()
    temp_dir = tempfile.mkdtemp()
    try:
        artifact_dir = command._save_model(
            model={"ok": True},
            name="demo",
            artifact_hash="abc123",
            config={"model_path": str(temp_dir), "model_type": "LGBModel"},
            metrics={"ic": None, "icir": None, "rank_ic": None},
        )

        metrics_payload = json.loads((Path(artifact_dir) / "metrics.json").read_text(encoding="utf-8"))
        assert metrics_payload == {"ic": None, "icir": None, "rank_ic": None}
    finally:
        shutil.rmtree(temp_dir)
