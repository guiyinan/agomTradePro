"""Safety coverage for the cross-module asset display-name resolver."""

import logging
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from apps.asset_analysis.infrastructure import asset_name_resolver
from apps.asset_analysis.infrastructure.asset_name_resolver import (
    AssetNameResolver,
    resolve_asset_names,
    resolve_asset_names_read_only,
)
from apps.data_center import composition as data_center_composition
from apps.equity.infrastructure.stock_repository import DjangoStockRepository


class _Registry:
    def __init__(self, resolver: object, *, expected_source: str | None = None) -> None:
        self._resolver = resolver
        self._expected_source = expected_source

    def get_name_resolver(self, source_name: str) -> object:
        if self._expected_source is not None:
            assert source_name == self._expected_source
        return self._resolver


class _AssetRepository:
    """Minimal mutable canonical repository used by name-resolution tests."""

    def __init__(self, assets: dict[str, object] | None = None) -> None:
        self.assets = dict(assets or {})

    def get_by_code(self, code: str) -> object | None:
        return self.assets.get(code)


def test_provider_results_are_normalized_bounded_and_request_scoped() -> None:
    def _resolve(codes: list[str]) -> dict[str, object]:
        assert codes
        return {
            " 000001.sz ": " 平安银行 ",
            "510300.of": "沪深300ETF",
            "EXTRA.SZ": "injected",
            "EMPTY.SZ": "",
        }

    with patch.object(
        asset_name_resolver,
        "get_asset_analysis_market_registry",
        return_value=_Registry(_resolve),
    ):
        result = AssetNameResolver().resolve_asset_names([" 000001.sz ", "510300.of", "000001.SZ"])

    assert result == {
        "000001.SZ": "平安银行",
        "510300.OF": "沪深300ETF",
    }


def test_corrupt_or_wrong_scope_cache_payload_is_never_trusted() -> None:
    fresh = {"000001.SZ": "平安银行"}
    corrupt_payloads = [
        fresh,
        {"version": 1, "scope": ["OTHER.SZ"], "names": fresh},
        {
            "version": 1,
            "scope": ["000001.SZ"],
            "names": {"000001.SZ": "平安银行", "EXTRA.SZ": "injected"},
        },
    ]

    for payload in corrupt_payloads:
        with (
            patch.object(asset_name_resolver.cache, "get", return_value=payload),
            patch.object(asset_name_resolver.cache, "set") as cache_set,
            patch.object(
                AssetNameResolver,
                "resolve_asset_names",
                return_value=fresh,
            ) as resolver,
        ):
            assert resolve_asset_names(["000001.SZ"]) == fresh
        resolver.assert_called_once_with(["000001.SZ"])
        cache_set.assert_called_once()


def test_populated_cache_records_exact_normalized_scope() -> None:
    with (
        patch.object(asset_name_resolver.cache, "get", return_value=None),
        patch.object(asset_name_resolver.cache, "set") as cache_set,
        patch.object(
            AssetNameResolver,
            "resolve_asset_names",
            return_value={"000001.SZ": "平安银行"},
        ),
    ):
        result = resolve_asset_names([" 000001.sz ", "000001.SZ"])

    assert result == {"000001.SZ": "平安银行"}
    payload = cache_set.call_args.args[1]
    assert payload == {
        "version": 1,
        "scope": ["000001.SZ"],
        "names": {"000001.SZ": "平安银行"},
    }


def test_read_only_miss_is_canonical_only_without_cache_or_backfill() -> None:
    with (
        patch.object(
            asset_name_resolver,
            "get_asset_analysis_market_registry",
            return_value=_Registry(
                lambda codes: {},
                expected_source="canonical_asset",
            ),
        ),
        patch.object(asset_name_resolver.cache, "get") as cache_get,
        patch(
            "apps.equity.infrastructure.stock_info_repository." "backfill_asset_master_codes_port"
        ) as backfill,
    ):
        result = resolve_asset_names_read_only(["000001.SZ"])

    assert result == {}
    cache_get.assert_not_called()
    backfill.assert_not_called()


def test_read_only_canonical_hit_returns_asset_master_name() -> None:
    with patch.object(
        asset_name_resolver,
        "get_asset_analysis_market_registry",
        return_value=_Registry(
            lambda codes: {"000001.SZ": "平安银行"},
            expected_source="canonical_asset",
        ),
    ):
        result = resolve_asset_names_read_only(["000001.SZ"])

    assert result == {"000001.SZ": "平安银行"}


def test_data_center_canonical_resolver_reads_all_asset_types_without_hydration() -> None:
    canonical_repository = _AssetRepository(
        {
            "000001.SZ": SimpleNamespace(
                is_active=True,
                short_name="平安银行",
                name="平安银行股份有限公司",
            ),
            "510300.SH": SimpleNamespace(
                is_active=True,
                short_name="沪深300ETF",
                name="华泰柏瑞沪深300ETF",
            ),
        }
    )

    with patch.object(
        data_center_composition,
        "get_asset_repository",
        return_value=canonical_repository,
    ):
        result = data_center_composition.resolve_canonical_asset_names(
            ["000001.SZ", "510300.SH", "MISSING.OF"]
        )

    assert result == {
        "000001.SZ": "平安银行",
        "510300.SH": "沪深300ETF",
    }


def test_normal_equity_resolver_retains_explicit_backfill_on_miss() -> None:
    canonical_repository = _AssetRepository()
    repository = object.__new__(DjangoStockRepository)
    repository._dc_asset_repo = canonical_repository

    def _hydrate(codes: list[str], *, include_remote: bool) -> None:
        assert "000001.SZ" in codes
        assert include_remote is True
        canonical_repository.assets["000001.SZ"] = SimpleNamespace(
            is_active=True,
            short_name="平安银行",
            name="平安银行股份有限公司",
        )

    with patch(
        "apps.equity.infrastructure.stock_info_repository.backfill_asset_master_codes_port",
        side_effect=_hydrate,
    ) as backfill:
        result = repository.resolve_stock_names(["000001.SZ"])

    assert result == {"000001.SZ": "平安银行"}
    backfill.assert_called_once()


def test_provider_exception_log_does_not_include_sensitive_detail(
    caplog: pytest.LogCaptureFixture,
) -> None:
    def _fail(codes: list[str]) -> dict[str, str]:
        del codes
        raise RuntimeError("database password=must-not-leak")

    with (
        patch.object(
            asset_name_resolver,
            "get_asset_analysis_market_registry",
            return_value=_Registry(_fail),
        ),
        caplog.at_level(logging.WARNING),
    ):
        assert AssetNameResolver().resolve_asset_names(["000001.SZ"]) == {}

    assert "RuntimeError" in caplog.text
    assert "must-not-leak" not in caplog.text
