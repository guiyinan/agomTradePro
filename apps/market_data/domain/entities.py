"""
Market Data 模块 - Domain 层实体

定义标准化的领域数据对象，业务层只依赖这些 DTO，不依赖任何外部数据源字段。
Domain 层不依赖任何外部框架，只使用 Python 标准库。
"""

from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal
from typing import Dict, List, Optional


@dataclass(frozen=True)
class QuoteSnapshot:
    """实时行情快照

    标准化的行情数据，屏蔽不同数据源的字段差异。
    """

    stock_code: str
    price: Decimal
    change: Optional[Decimal] = None
    change_pct: Optional[float] = None
    volume: Optional[int] = None
    amount: Optional[Decimal] = None
    turnover_rate: Optional[float] = None
    volume_ratio: Optional[float] = None
    high: Optional[Decimal] = None
    low: Optional[Decimal] = None
    open: Optional[Decimal] = None
    pre_close: Optional[Decimal] = None
    source: str = ""
    fetched_at: datetime = field(default_factory=lambda: datetime.now())

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
    fetched_at: datetime = field(default_factory=lambda: datetime.now())

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
    published_at: datetime = field(default_factory=lambda: datetime.now())
    url: Optional[str] = None
    source: str = ""
    fetched_at: datetime = field(default_factory=lambda: datetime.now())

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
    ma5: Optional[Decimal] = None
    ma20: Optional[Decimal] = None
    ma60: Optional[Decimal] = None
    macd: Optional[float] = None
    macd_signal: Optional[float] = None
    macd_hist: Optional[float] = None
    rsi: Optional[float] = None
    kdj_k: Optional[float] = None
    kdj_d: Optional[float] = None
    kdj_j: Optional[float] = None
    boll_upper: Optional[float] = None
    boll_mid: Optional[float] = None
    boll_lower: Optional[float] = None
    turnover_rate: Optional[float] = None
    volume_ratio: Optional[float] = None
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
class ProviderStatus:
    """Provider 状态快照

    用于健康检查和熔断判定。
    """

    provider_name: str
    capability: str
    is_healthy: bool
    last_success_at: Optional[datetime] = None
    consecutive_failures: int = 0
    circuit_open_until: Optional[datetime] = None
    avg_latency_ms: Optional[float] = None

    def to_dict(self) -> dict:
        """转换为字典"""
        return {
            "provider_name": self.provider_name,
            "capability": self.capability,
            "is_healthy": self.is_healthy,
            "last_success_at": (
                self.last_success_at.isoformat()
                if self.last_success_at
                else None
            ),
            "consecutive_failures": self.consecutive_failures,
            "circuit_open_until": (
                self.circuit_open_until.isoformat()
                if self.circuit_open_until
                else None
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
    payload: Dict
    parse_status: str = "success"
    error_message: str = ""
    fetched_at: datetime = field(default_factory=lambda: datetime.now())
