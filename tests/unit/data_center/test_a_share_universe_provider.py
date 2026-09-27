"""A-share universe provider resilience tests."""

from __future__ import annotations

import json
import sys
from types import SimpleNamespace

import pytest

from apps.data_center.domain.entities import AssetAlias, AssetMaster, ProviderConfig
from apps.data_center.infrastructure.a_share_universe_sync import (
    AkshareAshareCodeNameProvider,
    AShareUniverseSyncError,
    AShareUniverseSyncService,
    TushareAshareCodeNameProvider,
)


class _Frame:
    """Small DataFrame-shaped test fixture with provider-native columns."""

    def __init__(self, columns: tuple[str, ...], rows: list[dict[str, object]]) -> None:
        self.columns = columns
        self.rows = rows
        self.empty = not rows

    def to_dict(self, orient: str) -> list[dict[str, object]]:
        assert orient == "records"
        return self.rows


def _akshare_endpoint(
    code_column: str,
    name_column: str,
    code: str,
    name: str,
):
    def load(*, symbol: str = "") -> _Frame:
        del symbol
        return _Frame((code_column, name_column), [{code_column: code, name_column: name}])

    load.clear_count = 0
    load.cache_clear = lambda: setattr(load, "clear_count", load.clear_count + 1)
    return load


def test_akshare_universe_provider_retries_transient_failure(monkeypatch) -> None:
    """Connection and JSON failures retry one category after clearing its cache."""

    attempts = 0

    def load_sh(*, symbol: str) -> _Frame:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise ConnectionError("temporary upstream connection")
        if attempts == 2:
            raise json.JSONDecodeError("temporary malformed response", "", 0)
        assert symbol == "主板A股"
        return _Frame(("证券代码", "证券简称"), [{"证券代码": "600000", "证券简称": "浦发银行"}])

    load_sh.clear_count = 0
    load_sh.cache_clear = lambda: setattr(load_sh, "clear_count", load_sh.clear_count + 1)
    sh_star = _akshare_endpoint("证券代码", "证券简称", "688001", "华兴源创")
    sz_main = _akshare_endpoint("A股代码", "A股简称", "000001", "平安银行")
    bj = _akshare_endpoint("证券代码", "证券简称", "430047", "诺思兰德")

    # The SH endpoint is selected twice with different category symbols.
    original_sh_loader = load_sh

    def sh_loader(*, symbol: str) -> _Frame:
        if symbol == "科创板":
            return sh_star()
        return original_sh_loader(symbol=symbol)

    sh_loader.cache_clear = load_sh.cache_clear
    monkeypatch.setitem(
        sys.modules,
        "akshare",
        SimpleNamespace(
            stock_info_sh_name_code=sh_loader,
            stock_info_sz_name_code=sz_main,
            stock_info_bj_name_code=bj,
        ),
    )

    rows = AkshareAshareCodeNameProvider().load_code_names()

    assert attempts == 3
    assert load_sh.clear_count == 4  # three retries plus the STAR category call
    assert sz_main.clear_count == 1
    assert bj.clear_count == 1
    assert rows == [
        {"code": "600000", "name": "浦发银行"},
        {"code": "000001", "name": "平安银行"},
        {"code": "688001", "name": "华兴源创"},
        {"code": "430047", "name": "诺思兰德"},
    ]


def _provider_config() -> ProviderConfig:
    return ProviderConfig(
        id=7,
        name="market-fallback",
        source_type="tushare",
        is_active=True,
        priority=1,
        api_key="test-token",
        api_secret="",
        http_url="https://provider.invalid",
        api_endpoint="",
        extra_config={"tushare_request_mode": "sdk_path"},
        description="test",
    )


def test_tushare_stock_basic_uses_exchange_scopes_and_current_listing_contract(monkeypatch):
    calls: list[dict[str, str]] = []

    class _Client:
        def stock_basic(self, **kwargs: str) -> _Frame:
            calls.append(kwargs)
            exchange = kwargs["exchange"]
            code = {"SSE": "600000.SH", "SZSE": "000001.SZ", "BSE": "430047.BJ"}[exchange]
            return _Frame(
                ("ts_code", "name", "exchange", "list_status"),
                [{"ts_code": code, "name": "上市公司", "exchange": exchange, "list_status": "L"}],
            )

    monkeypatch.setattr(
        "apps.data_center.infrastructure.a_share_universe_sync.create_tushare_pro_client",
        lambda **kwargs: (assert_client_kwargs(kwargs), _Client())[1],
    )
    provider = TushareAshareCodeNameProvider(
        config_repo=SimpleNamespace(get_active_by_type=lambda _kind: [_provider_config()])
    )

    rows = provider.load_code_names()

    assert [call["exchange"] for call in calls] == ["SSE", "SZSE", "BSE"]
    assert all(call["list_status"] == "L" for call in calls)
    assert all(call["fields"] == "ts_code,name,exchange,list_status" for call in calls)
    assert rows == [
        {"code": "600000.SH", "name": "上市公司"},
        {"code": "000001.SZ", "name": "上市公司"},
        {"code": "430047.BJ", "name": "上市公司"},
    ]
    assert "provider_id=7" in provider.source_name


def assert_client_kwargs(kwargs: dict[str, object]) -> None:
    assert kwargs["provider_id"] == 7
    assert kwargs["dataset_key"] == "tushare.stock_basic"


class _MemoryAssetRepository:
    def __init__(self, active_codes: set[str]) -> None:
        self._active_codes = active_codes
        self.assets: dict[str, AssetMaster] = {}
        self.aliases: list[AssetAlias] = []

    def list_active_stock_codes(self) -> set[str]:
        return self._active_codes

    def get_by_code(self, code: str) -> AssetMaster | None:
        return self.assets.get(code)

    def upsert(self, asset: AssetMaster) -> AssetMaster:
        self.assets[asset.code] = asset
        return asset

    def upsert_alias(self, alias: AssetAlias) -> AssetAlias:
        self.aliases.append(alias)
        return alias


def test_universe_failover_accepts_consistent_fresh_provider_and_reports_source():
    class Primary:
        source_name = "akshare.stock_info_[sh_main,sz_main,sh_star,bj]"

        def load_code_names(self) -> list[dict[str, str]]:
            raise ConnectionError("upstream unavailable")

    class Fallback:
        source_name = "tushare.stock_basic[provider_id=7;list_status=L]"

        def load_code_names(self) -> list[dict[str, str]]:
            return [
                {"code": "600000.SH", "name": "浦发银行"},
                {"code": "000001.SZ", "name": "平安银行"},
            ]

    repository = _MemoryAssetRepository({"600000.SH", "000001.SZ"})
    report = AShareUniverseSyncService(
        provider=Primary(), fallback_provider=Fallback(), asset_repo=repository
    ).sync()

    assert report.source == "tushare.stock_basic[provider_id=7;list_status=L]"
    assert report.failover_from == "akshare.stock_info_[sh_main,sz_main,sh_star,bj]"
    assert report.failover_difference_ratio == 0
    assert report.failover_tolerance == 0.01
    assert set(repository.assets) == repository._active_codes
    assert all(alias.provider_name == "tushare" for alias in repository.aliases)


def test_universe_failover_blocks_scope_drift_before_any_write():
    class Primary:
        source_name = "akshare"

        def load_code_names(self) -> list[dict[str, str]]:
            raise ConnectionError("upstream unavailable")

    class Fallback:
        source_name = "tushare.stock_basic[provider_id=7]"

        def load_code_names(self) -> list[dict[str, str]]:
            return [{"code": "000001.SZ", "name": "平安银行"}]

    repository = _MemoryAssetRepository({"000001.SZ", "000002.SZ", "000003.SZ"})
    service = AShareUniverseSyncService(
        provider=Primary(), fallback_provider=Fallback(), asset_repo=repository
    )

    with pytest.raises(AShareUniverseSyncError) as caught:
        service.sync()

    assert caught.value.code == "A_SHARE_UNIVERSE_FAILOVER_INCONSISTENT"
    assert caught.value.details["difference_ratio"] > 0.01
    assert repository.assets == {}
    assert repository.aliases == []
