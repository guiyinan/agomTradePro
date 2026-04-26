"""
Data Center 网关层标准实体

定义标准化的市场数据 DTO，调用方只依赖这些对象，不依赖任何外部数据源字段。
"""

from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Dict, List, Optional


@dataclass(frozen=True)
class QuoteSnapshot:
    """实时行情快照

    标准化的行情数据，屏蔽不同数据源的字段差异。
    """

    stock_code: str
    price: Decimal
    change: Decimal | None = None
    change_pct: float | None = None
    volume: int | None = None
    amount: Decimal | None = None
    turnover_rate: float | None = None
    volume_ratio: float | None = None
    high: Decimal | None = None
    low: Decimal | None = None
    open: Decimal | None = None
    pre_close: Decimal | None = None
    source: str = ""
    fetched_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def __post_init__(self) -> None:
        if not self.stock_code:
            raise ValueError("stock_code 不能为空")
        if self.price < 0:
            raise ValueError(f"price 不能为负数: {self.price}")

    def to_dict(self) -> dict:
        """转换为字典"""
        return {
            "stock_code": self.stock_code,
            "price": str(self.price),
            "change": str(self.change) if self.change is not None else None,
            "change_pct": self.change_pct,
            "volume": self.volume,
            "amount": str(self.amount) if self.amount is not None else None,
            "turnover_rate": self.turnover_rate,
            "volume_ratio": self.volume_ratio,
            "high": str(self.high) if self.high is not None else None,
            "low": str(self.low) if self.low is not None else None,
            "open": str(self.open) if self.open is not None else None,
            "pre_close": str(self.pre_close) if self.pre_close is not None else None,
            "source": self.source,
            "fetched_at": self.fetched_at.isoformat(),
        }


@dataclass(frozen=True)
class CapitalFlowSnapshot:
    """资金流向快照

    标准化的主力资金/散户资金净流入数据。
    """

    stock_code: str
    trade_date: date
    main_net_inflow: float
    main_net_ratio: float
    super_large_net_inflow: float = 0.0
    large_net_inflow: float = 0.0
    medium_net_inflow: float = 0.0
    small_net_inflow: float = 0.0
    source: str = ""
    fetched_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def __post_init__(self) -> None:
        if not self.stock_code:
            raise ValueError("stock_code 不能为空")

    def to_dict(self) -> dict:
        """转换为字典"""
        return {
            "stock_code": self.stock_code,
            "trade_date": self.trade_date.isoformat(),
            "main_net_inflow": self.main_net_inflow,
            "main_net_ratio": self.main_net_ratio,
            "super_large_net_inflow": self.super_large_net_inflow,
            "large_net_inflow": self.large_net_inflow,
            "medium_net_inflow": self.medium_net_inflow,
            "small_net_inflow": self.small_net_inflow,
            "source": self.source,
            "fetched_at": self.fetched_at.isoformat(),
        }


@dataclass(frozen=True)
class StockNewsItem:
    """股票新闻条目

    标准化的新闻数据，供情绪分析使用。
    """

    stock_code: str
    news_id: str
    title: str
    content: str = ""
    published_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    url: str | None = None
    source: str = ""
    fetched_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def __post_init__(self) -> None:
        if not self.stock_code:
            raise ValueError("stock_code 不能为空")
        if not self.news_id:
            raise ValueError("news_id 不能为空")
        if not self.title:
            raise ValueError("title 不能为空")

    def to_text(self) -> str:
        """转换为文本用于情绪分析"""
        if self.content:
            return f"{self.title}\n{self.content}"
        return self.title

    def to_dict(self) -> dict:
        """转换为字典"""
        return {
            "stock_code": self.stock_code,
            "news_id": self.news_id,
            "title": self.title,
            "content": self.content,
            "published_at": self.published_at.isoformat(),
            "url": self.url,
            "source": self.source,
            "fetched_at": self.fetched_at.isoformat(),
        }


@dataclass(frozen=True)
class TechnicalSnapshot:
    """技术指标快照

    标准化的扩展技术指标，补充 KDJ/BOLL 等。
    """

    stock_code: str
    trade_date: date
    close: Decimal
    ma5: Decimal | None = None
    ma20: Decimal | None = None
    ma60: Decimal | None = None
    macd: float | None = None
    macd_signal: float | None = None
    macd_hist: float | None = None
    rsi: float | None = None
    kdj_k: float | None = None
    kdj_d: float | None = None
    kdj_j: float | None = None
    boll_upper: float | None = None
    boll_mid: float | None = None
    boll_lower: float | None = None
    turnover_rate: float | None = None
    volume_ratio: float | None = None
    source: str = ""

    def __post_init__(self) -> None:
        if not self.stock_code:
            raise ValueError("stock_code 不能为空")

    def to_dict(self) -> dict:
        """转换为字典"""
        return {
            "stock_code": self.stock_code,
            "trade_date": self.trade_date.isoformat(),
            "close": str(self.close),
            "ma5": str(self.ma5) if self.ma5 is not None else None,
            "ma20": str(self.ma20) if self.ma20 is not None else None,
            "ma60": str(self.ma60) if self.ma60 is not None else None,
            "macd": self.macd,
            "macd_signal": self.macd_signal,
            "macd_hist": self.macd_hist,
            "rsi": self.rsi,
            "kdj_k": self.kdj_k,
            "kdj_d": self.kdj_d,
            "kdj_j": self.kdj_j,
            "boll_upper": self.boll_upper,
            "boll_mid": self.boll_mid,
            "boll_lower": self.boll_lower,
            "turnover_rate": self.turnover_rate,
            "volume_ratio": self.volume_ratio,
            "source": self.source,
        }


@dataclass(frozen=True)
class HistoricalPriceBar:
    """历史价格 K 线

    标准化的 OHLCV 数据，适用于股票、ETF、指数等各类资产。
    """

    asset_code: str
    trade_date: date
    open: float
    high: float
    low: float
    close: float
    volume: int | None = None
    amount: float | None = None
    source: str = ""

    def __post_init__(self) -> None:
        if not self.asset_code:
            raise ValueError("asset_code 不能为空")
        if self.close < 0:
            raise ValueError(f"close 不能为负数: {self.close}")

    def to_dict(self) -> dict:
        """转换为字典"""
        return {
            "asset_code": self.asset_code,
            "trade_date": self.trade_date.isoformat(),
            "open": self.open,
            "high": self.high,
            "low": self.low,
            "close": self.close,
            "volume": self.volume,
            "amount": self.amount,
            "source": self.source,
        }


@dataclass(frozen=True)
class ProviderStatus:
    """Provider 状态快照

    用于健康检查和熔断判定。
    """

    provider_name: str
    capability: str
    is_healthy: bool
    last_success_at: datetime | None = None
    consecutive_failures: int = 0
    circuit_open_until: datetime | None = None
    avg_latency_ms: float | None = None

    def to_dict(self) -> dict:
        """转换为字典"""
        return {
            "provider_name": self.provider_name,
            "capability": self.capability,
            "is_healthy": self.is_healthy,
            "last_success_at": (self.last_success_at.isoformat() if self.last_success_at else None),
            "consecutive_failures": self.consecutive_failures,
            "circuit_open_until": (
                self.circuit_open_until.isoformat() if self.circuit_open_until else None
            ),
            "avg_latency_ms": self.avg_latency_ms,
        }


@dataclass(frozen=True)
class RawPayload:
    """原始数据载荷

    保留外部源的原始响应，便于排查站点字段变更。
    """

    request_type: str
    stock_code: str
    provider_name: str
    payload: dict
    parse_status: str = "success"
    error_message: str = ""
    fetched_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
