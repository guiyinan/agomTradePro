"""
Simple Alpha Provider

使用简单财务因子（PE/PB/ROE）计算股票评分的 Provider。
作为 Qlib 降级方案，优先级为 100。

重构说明 (2026-03-15):
- 删除伪随机数据生成，从真实数据源获取基本面数据
- 如果获取不到数据，返回空并给出错误提示
"""

import logging
import math
from datetime import date, datetime, timedelta
from typing import Any, TypedDict

from django.conf import settings
from django.utils import timezone

from apps.data_center.application.public import (
    get_financial_facts,
    get_latest_quote_payloads,
    get_valuation_facts,
    list_active_stock_codes,
    list_valuation_covered_codes,
)
from shared.numeric import safe_float

from ...domain.entities import AlphaPoolScope, AlphaResult, StockScore
from ...domain.interfaces import AlphaProviderStatus
from .base import BaseAlphaProvider, provider_safe

logger = logging.getLogger(__name__)


class _FundamentalQuality(TypedDict):
    has_pe: bool
    has_pb: bool
    has_roe: bool
    has_dividend: bool


class _FundamentalRecord(TypedDict):
    pe: float
    pb: float
    roe: float
    dividend_yield: float
    _data_quality: _FundamentalQuality


class _FundamentalDataQuality(TypedDict):
    valuation_count: int
    financial_count: int
    complete_count: int
    partial_count: int
    missing_count: int
    error: str | None


class _QuoteMomentumRow(TypedDict):
    code: str
    snapshot_at: datetime
    intraday_return: float
    range_position: float
    liquidity: float
    open_gap: float


class SimpleAlphaProvider(BaseAlphaProvider):
    """
    简单 Alpha 提供者

    使用基本面因子（PE、PB、ROE、股息率等）计算股票评分。
    优先级为 100，作为 Cache 和 Qlib 之后的降级方案。

    评分逻辑：
    - 低 PE、低 PB → 高分（价值因子）
    - 高 ROE → 高分（质量因子）
    - 高股息率 → 高分（红利因子）
    - 综合得分 = 归一化后的因子加权平均

    数据来源：
    - PE、PB、股息率、ROE：Data Center canonical facts

    Attributes:
        priority: 100
        max_staleness_days: 7 天（基本面数据可以接受更旧）

    Example:
        >>> provider = SimpleAlphaProvider()
        >>> result = provider.get_stock_scores("csi300", date.today())
        >>> if result.success:
        ...     for score in result.scores[:5]:
        ...         print(f"{score.code}: {score.score:.3f}")
    """

    # 因子权重配置
    DEFAULT_FACTOR_WEIGHTS = {
        "pe_inv": 0.25,      # PE 倒数（越小越好，所以用倒数）
        "pb_inv": 0.25,      # PB 倒数
        "roe": 0.30,         # ROE（越大越好）
        "dividend_yield": 0.20,  # 股息率（越大越好）
    }

    def __init__(self, factor_weights: dict[str, float] | None = None):
        """
        初始化简单 Provider

        Args:
            factor_weights: 自定义因子权重
        """
        super().__init__()
        self._factor_weights = factor_weights or self.DEFAULT_FACTOR_WEIGHTS.copy()

    @property
    def name(self) -> str:
        """Provider 名称"""
        return "simple"

    @property
    def priority(self) -> int:
        """优先级"""
        return 100

    @property
    def max_staleness_days(self) -> int:
        """最大陈旧天数"""
        return 7

    @provider_safe(default_success=False)
    def health_check(self) -> AlphaProviderStatus:
        """
        健康检查

        检查数据库中是否有可用的估值数据。

        Returns:
            Provider 状态
        """
        try:
            # 检查是否有最近 7 天内的估值数据
            has_data = bool(list_valuation_covered_codes(as_of=date.today()))
            quote_cutoff = timezone.now() - timedelta(hours=4)
            active_codes = list_active_stock_codes()[:100]
            has_fresh_quotes = bool(
                get_latest_quote_payloads(active_codes, observed_after=quote_cutoff)
            )

            if has_data or has_fresh_quotes:
                return AlphaProviderStatus.AVAILABLE
            return AlphaProviderStatus.UNAVAILABLE
        except Exception as e:
            logger.warning(f"SimpleAlphaProvider health check failed: {e}")
            return AlphaProviderStatus.UNAVAILABLE

    @provider_safe()
    def get_stock_scores(
        self,
        universe_id: str,
        intended_trade_date: date,
        top_n: int = 30,
        pool_scope: AlphaPoolScope | None = None,
        user: Any | None = None,
    ) -> AlphaResult:
        """
        计算股票评分

        1. 获取股票池列表
        2. 获取基本面数据
        3. 计算因子得分
        4. 归一化并加权汇总
        5. 排序返回

        Args:
            universe_id: 股票池标识
            intended_trade_date: 计划交易日期
            top_n: 返回前 N 只

        Returns:
            AlphaResult
        """
        # 1. 获取股票池（从数据库获取有估值数据的股票）
        stock_list = self._get_universe_stocks(
            universe_id,
            intended_trade_date,
            pool_scope=pool_scope,
        )
        if not stock_list:
            return self._create_error_result(
                f"股票池 {universe_id} 中没有可用的估值数据，请先同步估值数据"
            )
        score_universe_id = pool_scope.universe_id if pool_scope is not None else universe_id

        # 2. 获取基本面数据
        fundamental_data, data_quality = self._get_fundamental_data(
            stock_list,
            intended_trade_date
        )

        min_usable_fundamental_count = min(top_n, max(3, int(len(stock_list) * 0.3)))
        if not fundamental_data or len(fundamental_data) < min_usable_fundamental_count:
            quote_scores, quote_quality, staleness_days = self._compute_quote_momentum_scores(
                stock_list=stock_list,
                universe_id=score_universe_id,
                intended_trade_date=intended_trade_date,
            )
            if quote_scores and len(quote_scores) > len(fundamental_data):
                return self._create_success_result(
                    scores=quote_scores[:top_n],
                    staleness_days=staleness_days,
                    metadata={
                        "provider_source": "simple",
                        "universe_size": len(stock_list),
                        "scored_count": len(quote_scores),
                        "data_quality": {
                            **data_quality,
                            **quote_quality,
                            "fundamental_coverage_too_low": bool(fundamental_data),
                            "min_usable_fundamental_count": min_usable_fundamental_count,
                        },
                        "factor_basis": "quote_momentum",
                        "factor_weights": {
                            "intraday_return": 0.45,
                            "range_position": 0.25,
                            "liquidity": 0.20,
                            "open_gap": 0.10,
                        },
                        "scope_hash": pool_scope.scope_hash if pool_scope else None,
                        "scope_label": pool_scope.display_label if pool_scope else None,
                        "scope_metadata": pool_scope.to_dict() if pool_scope else {},
                    },
                )

            return self._create_error_result(
                f"无法获取基本面或实时价格数据: {data_quality.get('error', '未知错误')}。"
                "请先同步估值数据或实时行情。"
            )

        # 3. 计算评分
        scores = self._compute_scores(fundamental_data, score_universe_id, intended_trade_date)

        if not scores:
            return self._create_error_result(
                "计算评分失败：所有股票的基本面数据不完整"
            )

        # 4. 排序并取前 N
        scores.sort(key=lambda s: s.score, reverse=True)
        top_scores = scores[:top_n]

        # 更新排名
        for i, score in enumerate(top_scores, 1):
            # 创建新的 StockScore 实例以更新排名（因为是 frozen）
            top_scores[i - 1] = StockScore(
                code=score.code,
                score=score.score,
                rank=i,
                factors=score.factors,
                source=score.source,
                confidence=score.confidence,
                asof_date=intended_trade_date,
                intended_trade_date=intended_trade_date,
                universe_id=score_universe_id,
            )

        return self._create_success_result(
            scores=top_scores,
            metadata={
                "provider_source": "simple",
                "universe_size": len(stock_list),
                "scored_count": len(scores),
                "factor_weights": self._factor_weights,
                "data_quality": data_quality,
                "scope_hash": pool_scope.scope_hash if pool_scope else None,
                "scope_label": pool_scope.display_label if pool_scope else None,
                "scope_metadata": pool_scope.to_dict() if pool_scope else {},
            }
        )

    def _get_universe_stocks(
        self,
        universe_id: str,
        trade_date: date,
        pool_scope: AlphaPoolScope | None = None,
    ) -> list[str]:
        """
        获取股票池列表（从数据库获取有估值数据的股票）。

        Args:
            universe_id: 股票池标识
            trade_date: 交易日期

        Returns:
            股票代码列表
        """
        try:
            if pool_scope is not None and pool_scope.instrument_codes:
                return list(pool_scope.instrument_codes)

            # 优先使用配置的股票池映射
            configured = getattr(settings, "ALPHA_SIMPLE_UNIVERSE_MAP", {}) or {}
            if universe_id in configured and configured[universe_id]:
                # 过滤出有估值数据的股票
                configured_stocks = list(configured[universe_id])
                available_stocks = set(list_valuation_covered_codes(as_of=trade_date))
                return [code for code in configured_stocks if code in available_stocks]

            stocks = list_valuation_covered_codes(as_of=trade_date)
            if not stocks:
                logger.warning("数据库中没有估值数据")
                return []

            logger.info(
                f"SimpleAlphaProvider 从数据库获取股票池: "
                f"universe={universe_id}, date<={trade_date}, count={len(stocks)}"
            )
            return stocks

        except Exception as e:
            logger.error(f"获取股票池失败: {e}")
            return []

    def _get_fundamental_data(
        self,
        stock_list: list[str],
        trade_date: date
    ) -> tuple[dict[str, _FundamentalRecord], _FundamentalDataQuality]:
        """
        从数据库获取真实的基本面数据。

        数据来源：Data Center canonical valuation/financial facts。

        Args:
            stock_list: 股票列表
            trade_date: 交易日期

        Returns:
            (基本面数据字典, 数据质量信息)
        """
        fundamentals: dict[str, _FundamentalRecord] = {}
        data_quality: _FundamentalDataQuality = {
            "valuation_count": 0,
            "financial_count": 0,
            "complete_count": 0,
            "partial_count": 0,
            "missing_count": 0,
            "error": None,
        }

        try:
            for stock_code in stock_list:
                valuation_rows = get_valuation_facts(stock_code, as_of=trade_date, limit=1)
                valuation = valuation_rows[0] if valuation_rows else None
                financial_rows = get_financial_facts(stock_code, limit=100)
                latest_period = max(
                    (str(row.get("period_end")) for row in financial_rows if row.get("period_end")),
                    default="",
                )
                metrics = {
                    str(row.get("metric_code")): row.get("value")
                    for row in financial_rows
                    if str(row.get("period_end")) == latest_period
                }

                if valuation is not None:
                    data_quality["valuation_count"] += 1
                if metrics:
                    data_quality["financial_count"] += 1

                pe_value = (
                    valuation.get("pe_ttm")
                    if valuation is not None and valuation.get("pe_ttm") is not None
                    else (valuation.get("pe_static") if valuation is not None else None)
                )
                pb_value = valuation.get("pb") if valuation is not None else None
                dividend_value = valuation.get("dv_ratio") if valuation is not None else None
                roe_value = metrics.get("roe")
                pe = safe_float(pe_value)
                pb = safe_float(pb_value)
                dividend_yield = safe_float(dividend_value)
                roe = safe_float(roe_value)
                has_pe = pe is not None and pe > 0
                has_pb = pb is not None and pb > 0
                has_dividend = dividend_value is not None
                has_roe = roe is not None

                # Missing data must remain missing; never substitute guessed values.
                if not has_pe or not has_pb or not has_roe or not has_dividend:
                    data_quality["missing_count"] += 1
                    continue

                if pe is None or pb is None or dividend_yield is None or roe is None:
                    continue

                fundamentals[stock_code] = {
                    "pe": pe,
                    "pb": pb,
                    "roe": roe,
                    "dividend_yield": dividend_yield,
                    "_data_quality": {
                        "has_pe": has_pe,
                        "has_pb": has_pb,
                        "has_roe": has_roe,
                        "has_dividend": has_dividend,
                    }
                }

                if has_pe and has_pb and has_roe and has_dividend:
                    data_quality["complete_count"] += 1
                else:
                    data_quality["partial_count"] += 1

            if not fundamentals:
                data_quality["error"] = (
                    f"没有找到有效的基本面数据。"
                    f"估值数据日期上限: {trade_date}, "
                    f"请求股票数: {len(stock_list)}"
                )

            return fundamentals, data_quality

        except ImportError as e:
            data_quality["error"] = f"无法导入数据模型: {e}"
            logger.error(data_quality["error"])
            return {}, data_quality
        except Exception as e:
            data_quality["error"] = f"获取基本面数据时发生错误: {e}"
            logger.error(data_quality["error"])
            return {}, data_quality

    def _compute_scores(
        self,
        fundamental_data: dict[str, _FundamentalRecord],
        universe_id: str,
        trade_date: date
    ) -> list[StockScore]:
        """
        计算综合评分

        Args:
            fundamental_data: 基本面数据
            universe_id: 股票池标识
            trade_date: 交易日期

        Returns:
            股票评分列表
        """
        scores: list[StockScore] = []

        # 1. 提取因子值
        factor_values: dict[str, list[float]] = {
            name: [] for name in self._factor_weights
        }
        stock_list = list(fundamental_data.keys())

        for stock in stock_list:
            data = fundamental_data[stock]
            pe = data["pe"]
            pb = data["pb"]
            roe = data["roe"]
            dividend = data["dividend_yield"]

            # 计算复合因子
            factor_values["pe_inv"].append(1 / max(pe, 1) if pe > 0 else 0)
            factor_values["pb_inv"].append(1 / max(pb, 0.5) if pb > 0 else 0)
            factor_values["roe"].append(max(roe, 0))
            factor_values["dividend_yield"].append(max(dividend, 0))

        # 2. 归一化（0-1）
        normalized_factors: dict[str, list[float]] = {}
        for factor_name, values in factor_values.items():
            if values:
                min_val = min(values)
                max_val = max(values)
                range_val = max_val - min_val

                if range_val > 0:
                    normalized_factors[factor_name] = [
                        (v - min_val) / range_val for v in values
                    ]
                else:
                    normalized_factors[factor_name] = [0.5] * len(values)

        # 3. 计算加权得分
        for i, stock in enumerate(stock_list):
            data = fundamental_data[stock]
            data_quality = data["_data_quality"]

            factor_scores: dict[str, float] = {}
            total_score = 0.0

            for factor_name, weight in self._factor_weights.items():
                norm_value = normalized_factors[factor_name][i]
                factor_scores[factor_name] = norm_value
                total_score += norm_value * weight

            # 根据数据完整性调整置信度
            complete_fields = sum([
                data_quality.get("has_pe", False),
                data_quality.get("has_pb", False),
                data_quality.get("has_roe", False),
                data_quality.get("has_dividend", False),
            ])
            confidence = 0.4 + (complete_fields / 4) * 0.4  # 0.4 - 0.8

            scores.append(StockScore(
                code=stock,
                score=total_score,
                rank=0,  # 稍后设置
                factors=factor_scores,
                source="simple",
                confidence=confidence,
                asof_date=trade_date,
                universe_id=universe_id,
            ))

        return scores

    def _compute_quote_momentum_scores(
        self,
        *,
        stock_list: list[str],
        universe_id: str,
        intended_trade_date: date,
    ) -> tuple[list[StockScore], dict[str, object], int | None]:
        """Build a data-driven intraday Alpha fallback from fresh quote snapshots."""

        quote_cutoff = timezone.now() - timedelta(hours=4)
        normalized_codes = [str(code or "").strip().upper() for code in stock_list if code]
        latest_by_code = {
            str(snapshot.get("asset_code") or "").upper(): snapshot
            for snapshot in get_latest_quote_payloads(
                normalized_codes,
                observed_after=quote_cutoff,
            )
        }

        raw_rows: list[_QuoteMomentumRow] = []
        latest_snapshot_at: datetime | None = None
        for code in normalized_codes:
            quote = latest_by_code.get(code)
            if quote is None:
                continue
            current_price_raw = quote.get("current_price")
            prev_close_raw = quote.get("prev_close")
            if current_price_raw is None or prev_close_raw is None:
                continue
            current_price = safe_float(current_price_raw)
            prev_close = safe_float(prev_close_raw)
            if current_price is None or prev_close is None:
                continue
            open_price_raw = quote.get("open")
            high_raw = quote.get("high")
            low_raw = quote.get("low")
            volume_raw = quote.get("volume")
            open_price = safe_float(open_price_raw)
            high = safe_float(high_raw)
            low = safe_float(low_raw)
            volume = safe_float(volume_raw)
            if current_price <= 0 or prev_close <= 0:
                continue

            intraday_return = (current_price - prev_close) / prev_close
            open_gap = (
                (current_price - open_price) / open_price
                if open_price is not None and open_price > 0
                else 0.0
            )
            range_position = 0.5
            if high is not None and low is not None and high > low:
                range_position = min(max((current_price - low) / (high - low), 0.0), 1.0)
            raw_rows.append(
                {
                    "code": code,
                    "snapshot_at": datetime.fromisoformat(str(quote["snapshot_at"])),
                    "intraday_return": intraday_return,
                    "range_position": range_position,
                    "liquidity": math.log1p(max(volume, 0.0)) if volume is not None else 0.0,
                    "open_gap": open_gap,
                }
            )
            snapshot_at = datetime.fromisoformat(str(quote["snapshot_at"]))
            if latest_snapshot_at is None or snapshot_at > latest_snapshot_at:
                latest_snapshot_at = snapshot_at

        if not raw_rows:
            return [], {
                "quote_count": len(latest_by_code),
                "price_momentum_count": 0,
                "quote_error": "账户池内没有 freshness 阈值内的可评分实时行情。",
            }, None

        normalized_factors = {
            "intraday_return": self._normalize_factor_values(
                [row["intraday_return"] for row in raw_rows]
            ),
            "range_position": self._normalize_factor_values(
                [row["range_position"] for row in raw_rows]
            ),
            "liquidity": self._normalize_factor_values(
                [row["liquidity"] for row in raw_rows]
            ),
            "open_gap": self._normalize_factor_values([row["open_gap"] for row in raw_rows]),
        }
        weights = {
            "intraday_return": 0.45,
            "range_position": 0.25,
            "liquidity": 0.20,
            "open_gap": 0.10,
        }

        scores: list[StockScore] = []
        asof_date = timezone.localtime(latest_snapshot_at).date() if latest_snapshot_at else intended_trade_date
        staleness_days = max((intended_trade_date - asof_date).days, 0)
        for index, row in enumerate(raw_rows):
            factors = {
                factor: normalized_factors[factor][index]
                for factor in weights
            }
            total_score = sum(factors[factor] * weight for factor, weight in weights.items())
            confidence = 0.65
            if float(row["liquidity"]) > 0:
                confidence += 0.15
            if float(row["range_position"]) not in (0.0, 0.5, 1.0):
                confidence += 0.10
            scores.append(
                StockScore(
                    code=str(row["code"]),
                    score=total_score,
                    rank=0,
                    factors=factors,
                    source="simple",
                    confidence=min(confidence, 0.9),
                    asof_date=asof_date,
                    intended_trade_date=intended_trade_date,
                    universe_id=universe_id,
                )
            )

        scores.sort(key=lambda score: score.score, reverse=True)
        ranked_scores = [
            StockScore(
                code=score.code,
                score=score.score,
                rank=index,
                factors=score.factors,
                source=score.source,
                confidence=score.confidence,
                asof_date=score.asof_date,
                intended_trade_date=score.intended_trade_date,
                universe_id=score.universe_id,
            )
            for index, score in enumerate(scores, start=1)
        ]
        return ranked_scores, {
            "quote_count": len(latest_by_code),
            "price_momentum_count": len(ranked_scores),
            "latest_snapshot_at": latest_snapshot_at.isoformat() if latest_snapshot_at else None,
            "quote_cutoff": quote_cutoff.isoformat(),
        }, staleness_days

    @staticmethod
    def _normalize_factor_values(values: list[float]) -> list[float]:
        if not values:
            return []
        min_value = min(values)
        max_value = max(values)
        range_value = max_value - min_value
        if range_value == 0:
            return [0.5] * len(values)
        return [(value - min_value) / range_value for value in values]

    def get_factor_exposure(
        self,
        stock_code: str,
        trade_date: date
    ) -> dict[str, float]:
        """
        获取因子暴露

        Args:
            stock_code: 股票代码
            trade_date: 交易日期

        Returns:
            因子暴露字典
        """
        fundamental_data, _ = self._get_fundamental_data([stock_code], trade_date)

        if stock_code not in fundamental_data:
            return {}

        data = fundamental_data[stock_code]
        return {
            "pe_inv": 1 / max(data["pe"], 1),
            "pb_inv": 1 / max(data["pb"], 0.5),
            "roe": max(data["roe"], 0),
            "dividend_yield": max(data["dividend_yield"], 0),
        }
