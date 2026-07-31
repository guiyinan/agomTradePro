"""Shared constants for market thermometer use-case owners."""

from __future__ import annotations

from typing import Any

MARKET_COMPONENT_SPECS: dict[str, dict[str, Any]] = {
    "new_investor_accounts": {
        "label": "新增开户",
        "indicator_code": "CN_A_NEW_INVESTOR_ACCOUNTS",
        "frequency": "M",
    },
    "turnover": {
        "label": "全市场成交额",
        "indicator_code": "CN_A_TOTAL_TURNOVER",
        "frequency": "D",
    },
    "margin_balance": {
        "label": "融资余额",
        "indicator_code": "CN_A_MARGIN_BALANCE",
        "frequency": "D",
    },
    "etf_net_flow": {
        "label": "ETF 资金净流入",
        "indicator_code": "CN_A_ETF_NET_FLOW",
        "frequency": "D",
    },
    "market_news_count": {
        "label": "市场新闻热度",
        "indicator_code": "CN_A_MARKET_NEWS_COUNT",
        "frequency": "D",
    },
    "market_news_sentiment": {
        "label": "市场新闻情绪",
        "indicator_code": "CN_A_MARKET_NEWS_SENTIMENT",
        "frequency": "D",
    },
}
MARKET_BEHAVIOR_COLLECTION_SPECS: dict[str, dict[str, Any]] = {
    "advance_count": {
        "label": "上涨家数",
        "indicator_code": "CN_A_ADVANCE_COUNT",
        "frequency": "D",
    },
    "decline_count": {
        "label": "下跌家数",
        "indicator_code": "CN_A_DECLINE_COUNT",
        "frequency": "D",
    },
    "limit_up_count": {
        "label": "涨停家数",
        "indicator_code": "CN_A_LIMIT_UP_COUNT",
        "frequency": "D",
    },
    "limit_down_count": {
        "label": "跌停家数",
        "indicator_code": "CN_A_LIMIT_DOWN_COUNT",
        "frequency": "D",
    },
}
MARKET_NEWS_POSITIVE_RATIO_CODE = "CN_A_MARKET_NEWS_POSITIVE_RATIO"
ETF_MAIN_FLOW_CODE = "CN_A_ETF_NET_FLOW_MAIN"
ETF_SIZE_FLOW_CODE = "CN_A_ETF_SIZE_FLOW"
DEFAULT_MARKET_DATA_SOURCE_TYPES = ("akshare", "eastmoney", "tushare")
DEFAULT_NEWS_SOURCE_TYPES = ("akshare", "eastmoney")
MARKET_THERMOMETER_PROVIDER_TIMEOUT_SECONDS = 4
ETF_NET_FLOW_PROVIDER_TIMEOUT_SECONDS = 35.0
MARKET_THERMOMETER_PROVIDER_TIMEOUT_OVERRIDES = {
    "new_investor_accounts": 25.0,
    # Five daily full-market calls plus the trading calendar take 20-40s on
    # production Tushare-compatible endpoints. Keep a bounded but realistic budget.
    "turnover": 45.0,
    "etf_net_flow": ETF_NET_FLOW_PROVIDER_TIMEOUT_SECONDS,
}
RECOVERABLE_THERMOMETER_EXCEPTIONS = (
    AttributeError,
    ConnectionError,
    LookupError,
    OSError,
    RuntimeError,
    TimeoutError,
    TypeError,
    ValueError,
)
RECOVERABLE_THERMOMETER_EXCEPTION_NAMES = {
    "DataSourceUnavailableError",
    "DataValidationError",
}
MARKET_THERMOMETER_CONSENSUS_SOURCE = "data_center_consensus"
MARKET_THERMOMETER_SOURCE_TOLERANCE = 0.01
