"""A-share universe provider resilience tests."""

from __future__ import annotations

import json
import sys
from datetime import date
from types import SimpleNamespace

import pytest

from apps.data_center.domain.entities import AssetAlias, AssetMaster, ProviderConfig
from apps.data_center.domain.enums import AssetType, MarketExchange
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
                ("ts_code", "name", "exchange", "list_status", "list_date"),
                [
                    {
                        "ts_code": code,
                        "name": "上市公司",
                        "exchange": exchange,
                        "list_status": "L",
                        "list_date": "20000101",
                    }
                ],
            )

    monkeypatch.setattr(
        "apps.data_center.infrastructure.tushare_a_share_provider.create_tushare_pro_client",
        lambda **kwargs: (assert_client_kwargs(kwargs), _Client())[1],
    )
    provider = TushareAshareCodeNameProvider(
        config_repo=SimpleNamespace(get_active_by_type=lambda _kind: [_provider_config()])
    )

    rows = provider.load_code_names()

    assert [call["exchange"] for call in calls] == ["SSE", "SZSE", "BSE"]
    assert all(call["list_status"] == "L" for call in calls)
    assert all(call["fields"] == "ts_code,name,exchange,list_status,list_date" for call in calls)
    assert rows == [
        {
            "code": code,
            "name": "上市公司",
            "list_date": "2000-01-01",
            "list_date_status": "verified",
            "list_date_source": (
                "tushare.stock_basic[provider_id=7;exchanges=SSE,SZSE,BSE;list_status=L].list_date"
            ),
        }
        for code in ("600000.SH", "000001.SZ", "430047.BJ")
    ]
    assert "provider_id=7" in provider.source_name


def assert_client_kwargs(kwargs: dict[str, object]) -> None:
    assert kwargs["provider_id"] == 7
    assert kwargs["dataset_key"] == "tushare.stock_basic"


def test_tushare_invalid_stock_basic_date_uses_new_share_issue_date_as_listing_date(
    monkeypatch,
) -> None:
    """new_share.issue_date is listing date; ipo_date is only the subscription date."""

    client_routes: list[str] = []

    class _Client:
        def stock_basic(self, **kwargs: str) -> _Frame:
            exchange = kwargs["exchange"]
            code = {"SSE": "600000.SH", "SZSE": "301716.SZ", "BSE": "920202.BJ"}[exchange]
            listing_date = "19700101" if code == "301716.SZ" else "20000101"
            return _Frame(
                ("ts_code", "name", "exchange", "list_status", "list_date"),
                [
                    {
                        "ts_code": code,
                        "name": "上市公司",
                        "exchange": exchange,
                        "list_status": "L",
                        "list_date": listing_date,
                    }
                ],
            )

        def new_share(self, **kwargs: str) -> _Frame:
            assert kwargs["fields"] == "ts_code,issue_date"
            assert len(kwargs["start_date"]) == len(kwargs["end_date"]) == 8
            return _Frame(
                ("ts_code", "ipo_date", "issue_date"),
                [
                    {
                        "ts_code": "301716.SZ",
                        "ipo_date": "20260928",
                        "issue_date": "20260929",
                    }
                ],
            )

    def create_client(**kwargs: object) -> _Client:
        client_routes.append(str(kwargs["dataset_key"]))
        return _Client()

    monkeypatch.setattr(
        "apps.data_center.infrastructure.tushare_a_share_provider.create_tushare_pro_client",
        create_client,
    )
    provider = TushareAshareCodeNameProvider(
        config_repo=SimpleNamespace(get_active_by_type=lambda _kind: [_provider_config()])
    )

    rows = provider.load_code_names()
    corrected = next(row for row in rows if row["code"] == "301716.SZ")

    assert client_routes == ["tushare.stock_basic", "tushare.new_share"]
    assert corrected["list_date"] == "2026-09-29"
    assert corrected["list_date_status"] == "verified"
    assert corrected["list_date_source"] == "tushare.new_share[provider_id=7].issue_date"
    assert provider.list_date_enrichment_status == "complete"


def test_default_tushare_fallback_and_listing_metadata_share_one_provider() -> None:
    service = AShareUniverseSyncService()

    assert service._fallback_provider is service._listing_metadata_provider


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


def test_universe_sync_preserves_existing_listing_date_when_primary_omits_it() -> None:
    class Primary:
        source_name = "akshare.stock_info"

        def load_code_names(self) -> list[dict[str, str]]:
            return [{"code": "000001.SZ", "name": "平安银行"}]

    existing = AssetMaster(
        code="000001.SZ",
        name="平安银行",
        short_name="平安银行",
        asset_type=AssetType.STOCK,
        exchange=MarketExchange.SZSE,
        list_date=date(1991, 4, 3),
        extra={
            "list_date_evidence_status": "verified",
            "list_date_source": "historical-provider.list_date",
        },
    )
    repository = _MemoryAssetRepository(set())
    repository.assets[existing.code] = existing

    report = AShareUniverseSyncService(provider=Primary(), asset_repo=repository).sync()

    persisted = repository.assets[existing.code]
    assert report.active_count == 1
    assert persisted.list_date == existing.list_date
    assert persisted.extra["list_date_source"] == "historical-provider.list_date"


def test_universe_sync_supplements_akshare_membership_with_exact_tushare_metadata_source() -> None:
    class Primary:
        source_name = "akshare.stock_info"

        def load_code_names(self) -> list[dict[str, str]]:
            return [
                {"code": "000001.SZ", "name": "平安银行"},
                {"code": "600000.SH", "name": "浦发银行"},
            ]

    class Metadata:
        source_name = "tushare.stock_basic"

        def load_code_names(self) -> list[dict[str, str]]:
            self.source_name = "tushare.stock_basic[provider_id=7;list_status=L]"
            return [
                {
                    "code": "000001.SZ",
                    "name": "平安银行",
                    "list_date": "1991-04-03",
                    "list_date_status": "verified",
                    "list_date_source": (
                        "tushare.stock_basic[provider_id=7;list_status=L].list_date"
                    ),
                }
            ]

    repository = _MemoryAssetRepository(set())
    report = AShareUniverseSyncService(
        provider=Primary(),
        listing_metadata_provider=Metadata(),
        asset_repo=repository,
    ).sync()

    assert report.active_count == 2
    assert report.source == "akshare.stock_info"
    assert report.list_date_metadata_source == "tushare.stock_basic[provider_id=7;list_status=L]"
    assert report.list_date_known_count == 1
    assert report.list_date_unknown_count == 1
    assert report.list_date_conflict_count == 0
    assert repository.assets["000001.SZ"].list_date == date(1991, 4, 3)
    assert repository.assets["600000.SH"].list_date is None


def test_universe_sync_replaces_persisted_epoch_placeholder_with_verified_listing_date() -> None:
    """A historical 1970 placeholder must not conflict with verified provider evidence."""

    existing = AssetMaster(
        code="301716.SZ",
        name="历史名称",
        short_name="历史名称",
        asset_type=AssetType.STOCK,
        exchange=MarketExchange.SZSE,
        is_active=True,
        list_date=date(1970, 1, 1),
        extra={"list_date_source": "legacy.stock_basic.list_date"},
    )

    class Primary:
        source_name = "akshare.stock_info"

        def load_code_names(self) -> list[dict[str, str]]:
            return [{"code": "301716.SZ", "name": "新股"}]

    class Metadata:
        source_name = "tushare.stock_basic"

        def load_code_names(self) -> list[dict[str, str]]:
            return [
                {
                    "code": "301716.SZ",
                    "name": "新股",
                    "list_date": "2026-09-29",
                    "list_date_status": "verified",
                    "list_date_source": "tushare.new_share[provider_id=7].issue_date",
                }
            ]

    repository = _MemoryAssetRepository(set())
    repository.assets[existing.code] = existing

    report = AShareUniverseSyncService(
        provider=Primary(),
        listing_metadata_provider=Metadata(),
        asset_repo=repository,
    ).sync()

    persisted = repository.assets[existing.code]
    assert report.list_date_known_count == 1
    assert report.list_date_unknown_count == 0
    assert persisted.list_date == date(2026, 9, 29)
    assert persisted.extra["list_date_evidence_status"] == "verified"
    assert persisted.extra["list_date_source"] == ("tushare.new_share[provider_id=7].issue_date")


def test_universe_sync_keeps_membership_writes_when_listing_metadata_provider_fails() -> None:
    class Primary:
        source_name = "akshare.stock_info"

        def load_code_names(self) -> list[dict[str, str]]:
            return [{"code": "000001.SZ", "name": "平安银行"}]

    class Metadata:
        source_name = "tushare.stock_basic"

        def load_code_names(self) -> list[dict[str, str]]:
            raise ConnectionError("metadata unavailable")

    repository = _MemoryAssetRepository(set())
    report = AShareUniverseSyncService(
        provider=Primary(),
        listing_metadata_provider=Metadata(),
        asset_repo=repository,
    ).sync()

    assert report.active_count == 1
    assert report.list_date_metadata_status == "unavailable"
    assert set(repository.assets) == {"000001.SZ"}


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
