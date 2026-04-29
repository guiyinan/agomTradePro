"""
Unit tests for apps.data_center.domain.rules (Phase 2)

Tests cover:
  - normalize_currency_unit
  - normalize_asset_code
  - is_stale
"""

import pytest
from datetime import datetime, timedelta, timezone

from apps.data_center.domain.rules import (
    convert_currency_value,
    is_stale,
    normalize_asset_code,
    normalize_currency_unit,
)

# ---------------------------------------------------------------------------
# normalize_currency_unit
# ---------------------------------------------------------------------------


class TestNormalizeCurrencyUnit:
    def test_yi_yuan_to_yuan(self):
        value, unit = normalize_currency_unit(1.5, "亿元")
        assert value == pytest.approx(1.5e8)
        assert unit == "元"

    def test_wan_yuan_to_yuan(self):
        value, unit = normalize_currency_unit(2.0, "万元")
        assert value == pytest.approx(2.0e4)
        assert unit == "元"

    def test_qian_yuan_to_yuan(self):
        value, unit = normalize_currency_unit(3.0, "千元")
        assert value == pytest.approx(3.0e3)
        assert unit == "元"

    def test_wan_yi_yuan(self):
        value, unit = normalize_currency_unit(1.0, "万亿元")
        assert value == pytest.approx(1.0e12)
        assert unit == "元"

    def test_yi_usd_with_rate(self):
        value, unit = normalize_currency_unit(1.0, "亿美元", exchange_rate=7.2)
        assert value == pytest.approx(7.2e8)
        assert unit == "元"

    def test_yuan_passthrough(self):
        value, unit = normalize_currency_unit(100.0, "元")
        assert value == pytest.approx(100.0)
        assert unit == "元"

    def test_unknown_unit_passthrough(self):
        value, unit = normalize_currency_unit(42.0, "bps")
        assert value == 42.0
        assert unit == "bps"

    def test_percentage_passthrough(self):
        value, unit = normalize_currency_unit(3.5, "%")
        assert value == 3.5
        assert unit == "%"

    def test_bai_wan_usd(self):
        value, unit = normalize_currency_unit(1.0, "百万美元", exchange_rate=7.0)
        assert value == pytest.approx(7.0e6)
        assert unit == "元"

    def test_convert_currency_value_between_cny_units(self):
        value, unit = convert_currency_value(3152200000000.0, "元", "亿元")
        assert value == pytest.approx(31522.0)
        assert unit == "亿元"


# ---------------------------------------------------------------------------
# normalize_asset_code
# ---------------------------------------------------------------------------


class TestNormalizeAssetCode:
    def test_already_canonical_sh(self):
        assert normalize_asset_code("600519.SH") == "600519.SH"

    def test_already_canonical_sz(self):
        assert normalize_asset_code("000001.SZ") == "000001.SZ"

    def test_xshe_to_sz(self):
        assert normalize_asset_code("000001.XSHE") == "000001.SZ"

    def test_xshg_to_sh(self):
        assert normalize_asset_code("600519.XSHG") == "600519.SH"

    def test_ss_to_sh(self):
        assert normalize_asset_code("600519.SS") == "600519.SH"

    def test_prefix_sh_lower(self):
        assert normalize_asset_code("sh600519") == "600519.SH"

    def test_prefix_sz_lower(self):
        assert normalize_asset_code("sz000001") == "000001.SZ"

    def test_prefix_bj(self):
        assert normalize_asset_code("bj430047") == "430047.BJ"

    def test_prefix_upper(self):
        assert normalize_asset_code("SH600519") == "600519.SH"

    def test_bare_numeric_sh_heuristic(self):
        assert normalize_asset_code("600519", source_type="akshare") == "600519.SH"

    def test_bare_numeric_sz_heuristic(self):
        assert normalize_asset_code("000001", source_type="tushare") == "000001.SZ"

    def test_bare_numeric_bj_heuristic(self):
        assert normalize_asset_code("430047", source_type="akshare") == "430047.BJ"

    def test_whitespace_stripped(self):
        assert normalize_asset_code("  600519.SH  ") == "600519.SH"

    def test_unknown_suffix_passthrough(self):
        assert normalize_asset_code("600519.XYZ") == "600519.XYZ"

    def test_hk_code(self):
        assert normalize_asset_code("00700.HK") == "00700.HK"


# ---------------------------------------------------------------------------
# is_stale
# ---------------------------------------------------------------------------


class TestIsStale:
    def test_fresh_data_not_stale(self):
        fetched = datetime.now(timezone.utc) - timedelta(minutes=30)
        assert is_stale(fetched, max_age_hours=1) is False

    def test_old_data_is_stale(self):
        fetched = datetime.now(timezone.utc) - timedelta(hours=2)
        assert is_stale(fetched, max_age_hours=1) is True

    def test_exactly_at_boundary_is_stale(self):
        # Just past the boundary
        fetched = datetime.now(timezone.utc) - timedelta(hours=1, seconds=1)
        assert is_stale(fetched, max_age_hours=1) is True

    def test_naive_datetime_treated_as_utc(self):
        fetched = (datetime.now(timezone.utc) - timedelta(hours=3)).replace(tzinfo=None)
        assert is_stale(fetched, max_age_hours=2) is True

    def test_fractional_hours(self):
        fetched = datetime.now(timezone.utc) - timedelta(minutes=20)
        assert is_stale(fetched, max_age_hours=0.25) is True  # 20 min > 15 min

    def test_zero_age_threshold(self):
        fetched = datetime.now(timezone.utc) - timedelta(seconds=1)
        assert is_stale(fetched, max_age_hours=0) is True
