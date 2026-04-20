from apps.alpha.infrastructure.cache_code_parser import (
    collect_cached_score_codes,
    extract_cached_score_code,
    normalize_cached_stock_code,
)


def test_normalize_cached_stock_code_supports_canonical_codes():
    assert normalize_cached_stock_code("000001.SZ") == "000001.SZ"
    assert normalize_cached_stock_code("600519.SH") == "600519.SH"


def test_normalize_cached_stock_code_supports_prefixed_legacy_codes():
    assert normalize_cached_stock_code("SH600519") == "600519.SH"
    assert normalize_cached_stock_code("SZ002493") == "002493.SZ"


def test_extract_cached_score_code_supports_tuple_like_cache_strings():
    score_item = {"code": "(Timestamp('2026-04-03 00:00:00'), 'SH600048')"}

    assert extract_cached_score_code(score_item) == "600048.SH"


def test_collect_cached_score_codes_deduplicates_and_skips_invalid_items():
    scores = [
        {"code": "000001.SZ"},
        {"code": "(Timestamp('2026-04-03 00:00:00'), 'SH600048')"},
        {"code": "SH600048"},
        {"code": ""},
        "SZ300750",
    ]

    assert collect_cached_score_codes(scores) == [
        "000001.SZ",
        "600048.SH",
        "300750.SZ",
    ]
