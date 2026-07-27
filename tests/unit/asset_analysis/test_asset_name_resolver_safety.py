"""Safety coverage for the cross-module asset display-name resolver."""

import logging
from unittest.mock import patch

import pytest

from apps.asset_analysis.infrastructure import asset_name_resolver
from apps.asset_analysis.infrastructure.asset_name_resolver import (
    AssetNameResolver,
    resolve_asset_names,
    resolve_asset_names_read_only,
)


class _Registry:
    def __init__(self, resolver: object) -> None:
        self._resolver = resolver

    def get_name_resolver(self, source_name: str) -> object:
        del source_name
        return self._resolver


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
            assert resolve_asset_names_read_only(["000001.SZ"]) == fresh
        resolver.assert_called_once_with(["000001.SZ"])
        cache_set.assert_not_called()


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
