from apps.data_center.infrastructure.repositories import _build_asset_code_candidates


def test_build_asset_code_candidates_infers_etf_suffixes():
    """Bare ETF codes should resolve like the unified price service."""

    assert _build_asset_code_candidates("510300") == ["510300", "510300.SH"]
    assert _build_asset_code_candidates("512100") == ["512100", "512100.SH"]
    assert _build_asset_code_candidates("159915") == ["159915", "159915.SZ"]


def test_build_asset_code_candidates_keeps_stock_suffix_inference():
    """Existing A-share suffix inference should remain intact."""

    assert _build_asset_code_candidates("000001") == ["000001", "000001.SZ"]
    assert _build_asset_code_candidates("600000") == ["600000", "600000.SH"]
    assert _build_asset_code_candidates("430047") == ["430047", "430047.BJ"]
