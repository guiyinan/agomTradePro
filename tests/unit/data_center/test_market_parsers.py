"""
Data Center Parser 测试

测试东方财富数据解析器的字段映射和容错。
"""

from datetime import UTC, date, datetime, timedelta, timezone
from decimal import Decimal

import pandas as pd

from apps.data_center.infrastructure.parsers.eastmoney_capital_flow_parser import (
    parse_akshare_capital_flow_row,
)
from apps.data_center.infrastructure.parsers.eastmoney_news_parser import (
    _clean_content,
    _generate_news_id,
    parse_akshare_news_rows,
)
from apps.data_center.infrastructure.parsers.eastmoney_quote_parser import (
    _safe_decimal,
    _safe_int,
    parse_akshare_spot_row,
)
from shared.numeric import safe_float


class TestSafeConversions:
    """安全类型转换函数测试"""

    def test_safe_decimal_valid(self):
        assert _safe_decimal("15.50") == Decimal("15.50")
        assert _safe_decimal(15.5) == Decimal("15.5")

    def test_safe_decimal_none(self):
        assert _safe_decimal(None) is None

    def test_safe_decimal_nan(self):
        assert _safe_decimal(float("nan")) is None
        assert _safe_decimal(float("inf")) is None

    def test_safe_decimal_invalid(self):
        assert _safe_decimal("abc") is None

    def test_safe_float_valid(self):
        assert safe_float("1.5") == 1.5
        assert safe_float(1.5) == 1.5

    def test_safe_float_none(self):
        assert safe_float(None) is None

    def test_safe_float_nan(self):
        assert safe_float(float("nan")) is None

    def test_safe_int_valid(self):
        assert _safe_int("100") == 100
        assert _safe_int(100.7) == 100

    def test_safe_int_none(self):
        assert _safe_int(None) is None

    def test_safe_int_rejects_nonfinite_and_bool(self):
        assert _safe_int(float("inf")) is None
        assert _safe_int(float("nan")) is None
        assert _safe_int(True) is None


class TestQuoteParser:
    """行情解析器测试"""

    def test_parse_valid_row(self):
        row = pd.Series(
            {
                "最新价": 15.50,
                "涨跌额": 0.30,
                "涨跌幅": 1.97,
                "成交量": 1000000,
                "成交额": 15500000.0,
                "换手率": 2.5,
                "量比": 1.2,
                "最高": 15.80,
                "最低": 15.10,
                "今开": 15.20,
                "昨收": 15.20,
            }
        )
        snap = parse_akshare_spot_row(row, "000001.SZ")
        assert snap is not None
        assert snap.stock_code == "000001.SZ"
        assert snap.price == Decimal("15.5")
        assert snap.change == Decimal("0.3")
        assert snap.change_pct == 1.97
        assert snap.volume == 1000000
        assert snap.source == "eastmoney"

    def test_parse_missing_price_returns_none(self):
        row = pd.Series({"涨跌额": 0.30})
        snap = parse_akshare_spot_row(row, "000001.SZ")
        assert snap is None

    def test_parse_zero_price_returns_none(self):
        row = pd.Series({"最新价": 0})
        snap = parse_akshare_spot_row(row, "000001.SZ")
        assert snap is None

    def test_parse_nan_values(self):
        row = pd.Series(
            {
                "最新价": 15.50,
                "涨跌额": float("nan"),
                "成交量": float("nan"),
            }
        )
        snap = parse_akshare_spot_row(row, "000001.SZ")
        assert snap is not None
        assert snap.change is None
        assert snap.volume is None

    def test_parse_rejects_infinite_price_and_drops_negative_totals(self):
        assert parse_akshare_spot_row(pd.Series({"最新价": float("inf")}), "000001.SZ") is None
        snap = parse_akshare_spot_row(
            pd.Series({"最新价": 15.5, "成交量": -1, "成交额": -10}),
            "000001.SZ",
        )
        assert snap is not None
        assert snap.volume is None
        assert snap.amount is None


class TestCapitalFlowParser:
    """资金流向解析器测试"""

    def test_parse_valid_row(self):
        row = pd.Series(
            {
                "日期": "2026-03-01",
                "主力净流入-净额": 50000000.0,
                "主力净流入-净占比": 5.5,
                "超大单净流入-净额": 30000000.0,
                "大单净流入-净额": 20000000.0,
                "中单净流入-净额": -10000000.0,
                "小单净流入-净额": -40000000.0,
            }
        )
        snap = parse_akshare_capital_flow_row(row, "000001.SZ")
        assert snap is not None
        assert snap.stock_code == "000001.SZ"
        assert snap.trade_date == date(2026, 3, 1)
        assert snap.main_net_inflow == 50000000.0

    def test_parse_missing_date_returns_none(self):
        row = pd.Series({"主力净流入-净额": 100})
        snap = parse_akshare_capital_flow_row(row, "000001.SZ")
        assert snap is None

    def test_datetime_is_normalized_to_plain_trade_date(self):
        row = pd.Series(
            {
                "日期": datetime(2026, 3, 1, 15, 30),
                "主力净流入-净额": 1.0,
                "主力净流入-净占比": 2.0,
            }
        )
        snap = parse_akshare_capital_flow_row(row, "000001.SZ")
        assert snap is not None
        assert type(snap.trade_date) is date

    def test_invalid_required_flow_values_fail_closed(self):
        row = pd.Series(
            {
                "日期": "2026-03-01",
                "主力净流入-净额": float("inf"),
                "主力净流入-净占比": 2.0,
            }
        )
        assert parse_akshare_capital_flow_row(row, "000001.SZ") is None


class TestNewsParser:
    """新闻解析器测试"""

    def test_parse_valid_dataframe(self):
        df = pd.DataFrame(
            [
                {
                    "新闻标题": "平安银行发布年报",
                    "新闻内容": "净利润同比增长 10%",
                    "发布时间": "2026-03-01 10:00:00",
                    "新闻链接": "https://example.com/1",
                },
                {
                    "新闻标题": "另一条新闻",
                    "新闻内容": "内容",
                    "发布时间": "2026-03-01 11:00:00",
                    "新闻链接": "https://example.com/2",
                },
            ]
        )
        items = parse_akshare_news_rows(df, "000001.SZ", limit=10)
        assert len(items) == 2
        assert items[0].title == "平安银行发布年报"
        assert items[0].source == "eastmoney"

    def test_parse_empty_dataframe(self):
        df = pd.DataFrame()
        items = parse_akshare_news_rows(df, "000001.SZ")
        assert items == []

    def test_parse_none_dataframe(self):
        items = parse_akshare_news_rows(None, "000001.SZ")
        assert items == []

    def test_dedup_same_title_time(self):
        df = pd.DataFrame(
            [
                {
                    "新闻标题": "重复新闻",
                    "新闻内容": "内容A",
                    "发布时间": "2026-03-01 10:00:00",
                    "新闻链接": "",
                },
                {
                    "新闻标题": "重复新闻",
                    "新闻内容": "内容B",
                    "发布时间": "2026-03-01 10:00:00",
                    "新闻链接": "",
                },
            ]
        )
        items = parse_akshare_news_rows(df, "000001.SZ")
        assert len(items) == 1

    def test_limit_respected(self):
        rows = [
            {
                "新闻标题": f"新闻 {i}",
                "新闻内容": f"内容 {i}",
                "发布时间": f"2026-03-01 {10+i}:00:00",
                "新闻链接": "",
            }
            for i in range(10)
        ]
        df = pd.DataFrame(rows)
        items = parse_akshare_news_rows(df, "000001.SZ", limit=3)
        assert len(items) == 3

    def test_nonpositive_limit_returns_no_items(self):
        df = pd.DataFrame(
            [
                {
                    "新闻标题": "不应返回",
                    "发布时间": "2026-03-01 10:00:00",
                }
            ]
        )
        assert parse_akshare_news_rows(df, "000001.SZ", limit=0) == []
        assert parse_akshare_news_rows(df, "000001.SZ", limit=-1) == []

    def test_news_url_rejects_credentials_and_non_http_schemes(self):
        df = pd.DataFrame(
            [
                {
                    "新闻标题": "凭据 URL",
                    "发布时间": "2026-03-01 10:00:00",
                    "新闻链接": "https://user:secret@example.com/news",
                },
                {
                    "新闻标题": "脚本 URL",
                    "发布时间": "2026-03-01 11:00:00",
                    "新闻链接": "javascript:alert(1)",
                },
            ]
        )
        items = parse_akshare_news_rows(df, "000001.SZ")
        assert [item.url for item in items] == [None, None]

    def test_aware_news_timestamp_is_normalized_to_utc(self):
        published_at = datetime(
            2026,
            3,
            1,
            18,
            0,
            tzinfo=timezone(timedelta(hours=8)),
        )
        df = pd.DataFrame(
            [
                {
                    "新闻标题": "时区新闻",
                    "发布时间": published_at,
                }
            ]
        )
        items = parse_akshare_news_rows(df, "000001.SZ")
        assert items[0].published_at == datetime(2026, 3, 1, 10, 0, tzinfo=UTC)

    def test_clean_content(self):
        text = "正常内容。免责声明：投资有风险"
        cleaned = _clean_content(text)
        assert "免责声明" not in cleaned
        assert "正常内容" in cleaned

    def test_news_id_deterministic(self):
        id1 = _generate_news_id("000001.SZ", "title", "2026-03-01")
        id2 = _generate_news_id("000001.SZ", "title", "2026-03-01")
        assert id1 == id2

    def test_skip_empty_title(self):
        df = pd.DataFrame(
            [
                {
                    "新闻标题": "",
                    "新闻内容": "有内容但无标题",
                    "发布时间": "2026-03-01 10:00:00",
                    "新闻链接": "",
                },
            ]
        )
        items = parse_akshare_news_rows(df, "000001.SZ")
        assert len(items) == 0
