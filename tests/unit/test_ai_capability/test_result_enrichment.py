"""Regression tests for security-name enrichment in capability results."""

from unittest.mock import patch

from apps.ai_capability.application.result_enrichment import enrich_security_names


def test_enrich_security_names_adds_type_specific_names_recursively():
    payload = {
        "funds": [{"fund_code": "000001", "rank": 1}],
        "holdings": [{"stock_code": "600519.SH", "stock_name": ""}],
        "signals": [{"asset_code": "510300.SH"}],
        "request": {"security_code": "000001.SZ"},
        "provider_code": "tushare",
    }

    with patch(
        "apps.ai_capability.application.result_enrichment.resolve_asset_names_read_only",
        return_value={
            "000001": "华夏成长",
            "600519.SH": "贵州茅台",
            "510300.SH": "沪深300ETF",
            "000001.SZ": "平安银行",
        },
    ) as resolver:
        enriched = enrich_security_names(payload)

    assert enriched == {
        "funds": [{"fund_code": "000001", "fund_name": "华夏成长", "rank": 1}],
        "holdings": [{"stock_code": "600519.SH", "stock_name": "贵州茅台"}],
        "signals": [{"asset_code": "510300.SH", "asset_name": "沪深300ETF"}],
        "request": {"security_code": "000001.SZ", "security_name": "平安银行"},
        "provider_code": "tushare",
    }
    assert payload["funds"][0] == {"fund_code": "000001", "rank": 1}
    resolver.assert_called_once_with(["000001", "000001.SZ", "510300.SH", "600519.SH"])


def test_enrich_security_names_preserves_existing_names_and_omits_unresolved_names():
    payload = {
        "funds": [
            {"fund_code": "000001", "fund_name": "已有简称"},
            {"fund_code": "999999"},
        ]
    }

    with patch(
        "apps.ai_capability.application.result_enrichment.resolve_asset_names_read_only",
        return_value={"000001": "不应覆盖"},
    ):
        enriched = enrich_security_names(payload)

    assert enriched == {
        "funds": [
            {"fund_code": "000001", "fund_name": "已有简称"},
            {"fund_code": "999999"},
        ]
    }


def test_enrich_security_names_skips_lookup_when_no_security_codes_are_present():
    payload = {"provider_code": "tushare", "count": 1}

    with patch(
        "apps.ai_capability.application.result_enrichment.resolve_asset_names_read_only"
    ) as resolver:
        enriched = enrich_security_names(payload)

    assert enriched == payload
    resolver.assert_not_called()


def test_enrich_security_names_keeps_business_result_when_name_lookup_fails():
    payload = {"funds": [{"fund_code": "000001", "rank": 1}]}

    with patch(
        "apps.ai_capability.application.result_enrichment.resolve_asset_names_read_only",
        side_effect=RuntimeError("resolver unavailable"),
    ):
        enriched = enrich_security_names(payload)

    assert enriched == payload
