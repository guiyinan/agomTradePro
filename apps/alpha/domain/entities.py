"""
Alpha Domain Entities

定义 Alpha 信号的核心数据实体。
仅使用 Python 标准库，不依赖 Django 或外部库。
"""

import re
from hashlib import sha1
from dataclasses import dataclass, field
from datetime import date
from enum import Enum
from typing import Any, Dict, List, Optional


_SUFFIX_STOCK_CODE_PATTERN = re.compile(r"\b(?P<code>\d{6})\.(?P<exchange>SH|SZ|BJ)\b", re.IGNORECASE)
_PREFIX_STOCK_CODE_PATTERN = re.compile(r"\b(?P<exchange>SH|SZ|BJ)(?P<code>\d{6})\b", re.IGNORECASE)
_PLAIN_STOCK_CODE_PATTERN = re.compile(r"\b(?P<code>\d{6})\b")


def normalize_stock_code(raw_value: object) -> str:
    """Normalize legacy / tuple-serialized stock codes into canonical tushare format."""
    if raw_value in (None, ""):
        return ""

    raw_text = str(raw_value).strip().upper()
    if not raw_text:
        return ""

    suffix_match = _SUFFIX_STOCK_CODE_PATTERN.search(raw_text)
    if suffix_match:
        return f"{suffix_match.group('code')}.{suffix_match.group('exchange')}"

    prefix_match = _PREFIX_STOCK_CODE_PATTERN.search(raw_text)
    if prefix_match:
        return f"{prefix_match.group('code')}.{prefix_match.group('exchange')}"

    plain_match = _PLAIN_STOCK_CODE_PATTERN.search(raw_text)
    if not plain_match:
        return raw_text

    code = plain_match.group("code")
    if code.startswith(("4", "8")):
        exchange = "BJ"
    elif code.startswith(("5", "6", "9")):
        exchange = "SH"
    else:
        exchange = "SZ"
    return f"{code}.{exchange}"


class InvalidationType(Enum):
    """
    证伪类型枚举

    定义 Alpha 信号证伪的不同类型。
    """

    THRESHOLD_CROSS = "threshold_cross"
    """阈值穿越：指标穿越阈值时证伪"""

    TIME_DECAY = "time_decay"
    """时间衰减：超过最大持仓时间"""

    REGIME_MISMATCH = "regime_mismatch"
    """Regime 不匹配：当前 Regime 与要求不符"""

    MODEL_DRIFT = "model_drift"
    """模型漂移：模型性能显著下降"""

    MANUAL = "manual"
    """手动证伪：人工手动证伪"""


@dataclass(frozen=True)
class InvalidationCondition:
    """
    证伪条件

    定义 Alpha 信号的证伪规则，支持多种条件类型。

    Attributes:
        condition_type: 条件类型
        threshold_value: 阈值（用于 THRESHOLD_CROSS）
        cross_direction: 穿越方向 ("above", "below")
        max_holding_days: 最大持仓天数（用于 TIME_DECAY）
        required_regime: 要求的 Regime（用于 REGIME_MISMATCH）
        min_ic: 最小 IC 值（用于 MODEL_DRIFT）
        description: 条件描述

    Example:
        >>> condition = InvalidationCondition(
        ...     condition_type=InvalidationType.THRESHOLD_CROSS,
        ...     threshold_value=50.0,
        ...     cross_direction="below",
        ...     description="PMI 跌破 50"
        ... )
    """

    condition_type: InvalidationType
    threshold_value: float | None = None
    cross_direction: str | None = None
    max_holding_days: int | None = None
    required_regime: str | None = None
    min_ic: float | None = None
    description: str = ""

    def to_dict(self) -> dict[str, Any]:
        """转换为字典"""
        return {
            "condition_type": self.condition_type.value,
            "threshold_value": self.threshold_value,
            "cross_direction": self.cross_direction,
            "max_holding_days": self.max_holding_days,
            "required_regime": self.required_regime,
            "min_ic": self.min_ic,
            "description": self.description,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "InvalidationCondition":
        """从字典创建"""
        return cls(
            condition_type=InvalidationType(data.get("condition_type", "manual")),
            threshold_value=data.get("threshold_value"),
            cross_direction=data.get("cross_direction"),
            max_holding_days=data.get("max_holding_days"),
            required_regime=data.get("required_regime"),
            min_ic=data.get("min_ic"),
            description=data.get("description", ""),
        )


@dataclass(frozen=True)
class StockScore:
    """
    股票评分实体（含审计字段）

    定义单个股票的评分结果，包含完整的审计追踪信息。

    Attributes:
        code: 股票代码
        score: 评分（-1 到 1，正数看多，负数看空）
        rank: 排名（1 为最高）
        factors: 因子暴露度字典
        source: 评分来源（qlib/cache/simple/etf）
        confidence: 置信度（0-1）
        model_id: 模型标识
        model_artifact_hash: 模型文件哈希（用于追溯）
        asof_date: 信号真实生成日期（重要：避免前视偏差）
        intended_trade_date: 计划执行交易的日期
        universe_id: 股票池标识
        feature_set_id: 特征集标识
        label_id: 标签标识
        data_version: 数据版本标识

    Example:
        >>> score = StockScore(
        ...     code="000001.SH",
        ...     score=0.75,
        ...     rank=1,
        ...     factors={"momentum": 0.8, "value": 0.6},
        ...     source="qlib",
        ...     confidence=0.85,
        ...     asof_date=date(2026, 2, 5),
        ...     intended_trade_date=date(2026, 2, 6)
        ... )
    """

    code: str
    score: float
    rank: int
    factors: dict[str, float]
    source: str
    confidence: float

    # 审计字段（复现/排障必需）
    model_id: str | None = None
    model_artifact_hash: str | None = None
    asof_date: date | None = None
    intended_trade_date: date | None = None
    universe_id: str | None = None
    feature_set_id: str | None = None
    label_id: str | None = None
    data_version: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """转换为字典"""
        return {
            "code": self.code,
            "score": self.score,
            "rank": self.rank,
            "factors": self.factors,
            "source": self.source,
            "confidence": self.confidence,
            "model_id": self.model_id,
            "model_artifact_hash": self.model_artifact_hash,
            "asof_date": self.asof_date.isoformat() if self.asof_date else None,
            "intended_trade_date": self.intended_trade_date.isoformat() if self.intended_trade_date else None,
            "universe_id": self.universe_id,
            "feature_set_id": self.feature_set_id,
            "label_id": self.label_id,
            "data_version": self.data_version,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "StockScore":
        """从字典创建"""
        factors = data.get("factors", {})
        asof_date = data.get("asof_date")
        intended_trade_date = data.get("intended_trade_date")

        return cls(
            code=data["code"],
            score=float(data["score"]),
            rank=int(data["rank"]),
            factors=factors if isinstance(factors, dict) else {},
            source=data["source"],
            confidence=float(data.get("confidence", 0.5)),
            model_id=data.get("model_id"),
            model_artifact_hash=data.get("model_artifact_hash"),
            asof_date=date.fromisoformat(asof_date) if asof_date else None,
            intended_trade_date=date.fromisoformat(intended_trade_date) if intended_trade_date else None,
            universe_id=data.get("universe_id"),
            feature_set_id=data.get("feature_set_id"),
            label_id=data.get("label_id"),
            data_version=data.get("data_version"),
        )


@dataclass(frozen=True)
class AlphaPoolScope:
    """账户驱动 Alpha 股票池定义。"""

    pool_type: str
    market: str
    instrument_codes: tuple[str, ...]
    selection_reason: str
    trade_date: date
    display_label: str = ""
    portfolio_id: int | None = None
    portfolio_name: str | None = None

    def __post_init__(self) -> None:
        canonical_codes = tuple(
            code
            for code in (normalize_stock_code(raw_code) for raw_code in self.instrument_codes)
            if code
        )
        unique_codes = tuple(dict.fromkeys(canonical_codes))
        object.__setattr__(self, "instrument_codes", unique_codes)

    @property
    def pool_size(self) -> int:
        """返回池子内股票数量。"""
        return len(self.instrument_codes)

    @property
    def scope_hash(self) -> str:
        """返回稳定的 scope hash，用于缓存和历史追踪。"""
        basis = "|".join(
            [
                self.pool_type,
                self.market,
                self.trade_date.isoformat(),
                ",".join(self.instrument_codes),
                str(self.portfolio_id or ""),
            ]
        )
        return sha1(basis.encode("utf-8")).hexdigest()[:16]

    @property
    def universe_id(self) -> str:
        """返回兼容旧接口的 synthetic universe id。"""
        if self.portfolio_id is not None:
            return f"portfolio-{self.portfolio_id}-{self.scope_hash}"
        return f"{self.market.lower()}-{self.pool_type}-{self.scope_hash}"

    def to_dict(self) -> dict[str, Any]:
        """转换为 JSON-safe 字典。"""
        return {
            "pool_type": self.pool_type,
            "market": self.market,
            "instrument_codes": list(self.instrument_codes),
            "pool_size": self.pool_size,
            "selection_reason": self.selection_reason,
            "trade_date": self.trade_date.isoformat(),
            "display_label": self.display_label,
            "portfolio_id": self.portfolio_id,
            "portfolio_name": self.portfolio_name,
            "scope_hash": self.scope_hash,
            "universe_id": self.universe_id,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "AlphaPoolScope":
        """从字典重建股票池定义。"""
        trade_date_raw = data.get("trade_date")
        return cls(
            pool_type=str(data.get("pool_type") or "portfolio_market"),
            market=str(data.get("market") or "CN"),
            instrument_codes=tuple(data.get("instrument_codes") or ()),
            selection_reason=str(data.get("selection_reason") or ""),
            trade_date=date.fromisoformat(trade_date_raw) if trade_date_raw else date.today(),
            display_label=str(data.get("display_label") or ""),
            portfolio_id=data.get("portfolio_id"),
            portfolio_name=data.get("portfolio_name"),
        )


@dataclass
class AlphaResult:
    """
    Alpha 计算结果

    封装一次 Alpha 计算的完整结果，包括评分列表和元数据。

    Attributes:
        success: 是否成功获取评分
        scores: 股票评分列表
        source: 数据来源（Provider 名称）
        timestamp: 结果时间戳
        error_message: 错误信息（如果失败）
        status: 状态（available/degraded/unavailable）
        latency_ms: 延迟（毫秒）
        staleness_days: 数据陈旧天数
        invalidation_conditions: 证伪条件列表
        metadata: 额外元数据

    Example:
        >>> result = AlphaResult(
        ...     success=True,
        ...     scores=[score1, score2],
        ...     source="qlib",
        ...     timestamp="2026-02-05T10:30:00",
        ...     status="available"
        ... )
    """

    success: bool
    scores: list[StockScore]
    source: str
    timestamp: str
    error_message: str | None = None
    status: str = "available"
    latency_ms: int | None = None
    staleness_days: int | None = None
    invalidation_conditions: list[InvalidationCondition] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """转换为字典"""
        return {
            "success": self.success,
            "source": self.source,
            "timestamp": self.timestamp,
            "status": self.status,
            "latency_ms": self.latency_ms,
            "staleness_days": self.staleness_days,
            "error_message": self.error_message,
            "stocks": [s.to_dict() for s in self.scores],
            "invalidation_conditions": [ic.to_dict() for ic in self.invalidation_conditions],
            "metadata": self.metadata,
        }


@dataclass(frozen=True)
class AlphaProviderConfig:
    """
    Alpha Provider 配置

    定义 Provider 的全局配置参数。

    Attributes:
        max_staleness_days: 默认最大数据陈旧天数
        max_latency_ms: 默认最大延迟
        enable_cache: 是否启用缓存
        cache_ttl_seconds: 缓存过期时间（秒）
        retry_attempts: 失败重试次数
        retry_delay_seconds: 重试延迟（秒）
        timeout_seconds: 请求超时时间（秒）

    Example:
        >>> config = AlphaProviderConfig(
        ...     max_staleness_days=2,
        ...     max_latency_ms=1500
        ... )
    """

    max_staleness_days: int = 2
    max_latency_ms: int = 1500
    enable_cache: bool = True
    cache_ttl_seconds: int = 3600
    retry_attempts: int = 3
    retry_delay_seconds: int = 5
    timeout_seconds: int = 30

    def to_dict(self) -> dict[str, Any]:
        """转换为字典"""
        return {
            "max_staleness_days": self.max_staleness_days,
            "max_latency_ms": self.max_latency_ms,
            "enable_cache": self.enable_cache,
            "cache_ttl_seconds": self.cache_ttl_seconds,
            "retry_attempts": self.retry_attempts,
            "retry_delay_seconds": self.retry_delay_seconds,
            "timeout_seconds": self.timeout_seconds,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "AlphaProviderConfig":
        """从字典创建"""
        return cls(
            max_staleness_days=data.get("max_staleness_days", 2),
            max_latency_ms=data.get("max_latency_ms", 1500),
            enable_cache=data.get("enable_cache", True),
            cache_ttl_seconds=data.get("cache_ttl_seconds", 3600),
            retry_attempts=data.get("retry_attempts", 3),
            retry_delay_seconds=data.get("retry_delay_seconds", 5),
            timeout_seconds=data.get("timeout_seconds", 30),
        )


@dataclass(frozen=True)
class UniverseDefinition:
    """
    股票池定义

    定义一个股票池的构成和属性。

    Attributes:
        universe_id: 股票池唯一标识
        name: 股票池名称
        description: 描述
        stock_codes: 包含的股票代码列表
        index_code: 对应指数代码（如果有）
        weight_method: 加权方法（equal_weight/market_cap）
        rebalance_frequency: 再平衡频率

    Example:
        >>> universe = UniverseDefinition(
        ...     universe_id="csi300",
        ...     name="沪深300",
        ...     stock_codes=["000001.SH", "000002.SH", ...]
        ... )
    """

    universe_id: str
    name: str
    description: str = ""
    stock_codes: list[str] = field(default_factory=list)
    index_code: str | None = None
    weight_method: str = "equal_weight"
    rebalance_frequency: str = "monthly"

    def to_dict(self) -> dict[str, Any]:
        """转换为字典"""
        return {
            "universe_id": self.universe_id,
            "name": self.name,
            "description": self.description,
            "stock_codes": self.stock_codes,
            "index_code": self.index_code,
            "weight_method": self.weight_method,
            "rebalance_frequency": self.rebalance_frequency,
        }
