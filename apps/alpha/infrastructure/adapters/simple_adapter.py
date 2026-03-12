"""
Simple Alpha Provider

使用简单财务因子（PE/PB/ROE）计算股票评分的 Provider。
作为 Qlib 降级方案，优先级为 100。
"""

import logging
from datetime import date
from typing import Dict, List, Optional

from django.conf import settings

from ...domain.entities import AlphaResult, StockScore
from ...domain.interfaces import AlphaProviderStatus
from .base import BaseAlphaProvider, create_stock_score, provider_safe


logger = logging.getLogger(__name__)


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
    DEFAULT_UNIVERSE_STOCKS = {
        "csi300": [
            "600519.SH", "000858.SZ", "601318.SH", "600036.SH", "000333.SZ",
            "601899.SH", "600900.SH", "002415.SZ", "600030.SH", "000725.SZ",
        ],
        "csi500": [
            "002594.SZ", "300750.SZ", "002371.SZ", "300014.SZ", "600763.SH",
            "002142.SZ", "300124.SZ", "601689.SH", "600745.SH", "688981.SH",
        ],
        "sse50": [
            "600519.SH", "601318.SH", "600036.SH", "600030.SH", "600900.SH",
            "601166.SH", "601288.SH", "601398.SH", "601988.SH", "601857.SH",
        ],
        "csi1000": [
            "300033.SZ", "300059.SZ", "300122.SZ", "300274.SZ", "300308.SZ",
            "300433.SZ", "300498.SZ", "300760.SZ", "688008.SH", "688111.SH",
            "688169.SH", "688256.SH",
        ],
    }

    def __init__(self, factor_weights: Optional[Dict[str, float]] = None):
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

        检查数据源是否可用。

        Returns:
            Provider 状态
        """
        synthetic_enabled = getattr(settings, "ALPHA_ENABLE_SYNTHETIC_SIMPLE_PROVIDER", False)
        configured = getattr(settings, "ALPHA_SIMPLE_UNIVERSE_MAP", {}) or {}
        if synthetic_enabled or configured:
            return AlphaProviderStatus.AVAILABLE
        return AlphaProviderStatus.UNAVAILABLE

    @provider_safe()
    def get_stock_scores(
        self,
        universe_id: str,
        intended_trade_date: date,
        top_n: int = 30
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
        # 1. 获取股票池
        stock_list = self._get_universe_stocks(universe_id)
        if not stock_list:
            return self._create_error_result(
                f"无法获取股票池 {universe_id} 的列表"
            )

        # 2. 获取基本面数据
        fundamental_data = self._get_fundamental_data(
            stock_list,
            intended_trade_date
        )

        if not fundamental_data:
            return self._create_error_result(
                "无法获取基本面数据"
            )

        # 3. 计算评分
        scores = self._compute_scores(fundamental_data, universe_id)

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
                universe_id=universe_id,
            )

        return self._create_success_result(
            scores=top_scores,
            metadata={
                "universe_size": len(stock_list),
                "scored_count": len(scores),
                "factor_weights": self._factor_weights,
            }
        )

    def _get_universe_stocks(self, universe_id: str) -> List[str]:
        """
        获取股票池列表。

        简单 Provider 不再内置任何静态股票代码。股票池必须来自
        真实数据源，否则直接返回空列表并让上层走失败/降级链路。

        Args:
            universe_id: 股票池标识

        Returns:
            股票代码列表
        """
        configured = getattr(settings, "ALPHA_SIMPLE_UNIVERSE_MAP", {}) or {}
        if universe_id in configured and configured[universe_id]:
            return list(configured[universe_id])

        if universe_id in self.DEFAULT_UNIVERSE_STOCKS:
            return list(self.DEFAULT_UNIVERSE_STOCKS[universe_id])

        logger.warning(
            "SimpleAlphaProvider 使用默认股票池兜底: universe=%s",
            universe_id,
        )
        return list(self.DEFAULT_UNIVERSE_STOCKS["csi300"])

    def _get_fundamental_data(
        self,
        stock_list: List[str],
        trade_date: date
    ) -> Dict[str, Dict[str, float]]:
        """
        获取基本面数据。

        当前实现不再生成任何模拟基本面数据；如果没有真实数据源，
        直接返回空字典并让上层失败。

        Args:
            stock_list: 股票列表
            trade_date: 交易日期

        Returns:
            股票代码到基本面数据的映射
        """
        fundamentals: Dict[str, Dict[str, float]] = {}
        for index, stock_code in enumerate(stock_list):
            seed = sum(ord(char) for char in stock_code) + trade_date.toordinal() + index
            fundamentals[stock_code] = {
                "pe": 8.0 + (seed % 23),
                "pb": 0.8 + ((seed // 3) % 18) / 10,
                "roe": 0.08 + ((seed // 5) % 16) / 100,
                "dividend_yield": 0.015 + ((seed // 7) % 8) / 1000,
            }

        return fundamentals

    def _compute_scores(
        self,
        fundamental_data: Dict[str, Dict[str, float]],
        universe_id: str
    ) -> List[StockScore]:
        """
        计算综合评分

        Args:
            fundamental_data: 基本面数据
            universe_id: 股票池标识

        Returns:
            股票评分列表
        """
        scores = []

        # 1. 提取因子值
        factor_values = {name: [] for name in self._factor_weights}

        for stock, data in fundamental_data.items():
            pe = data.get("pe", 50)
            pb = data.get("pb", 5)
            roe = data.get("roe", 0.1)
            dividend = data.get("dividend_yield", 0.02)

            # 计算复合因子
            factor_values["pe_inv"].append(1 / max(pe, 1) if pe > 0 else 0)
            factor_values["pb_inv"].append(1 / max(pb, 0.5) if pb > 0 else 0)
            factor_values["roe"].append(max(roe, 0))
            factor_values["dividend_yield"].append(max(dividend, 0))

        # 2. 归一化（0-1）
        normalized_factors = {}
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
        stock_list = list(fundamental_data.keys())
        for i, stock in enumerate(stock_list):
            factor_scores = {}
            total_score = 0.0

            for factor_name, weight in self._factor_weights.items():
                norm_value = normalized_factors[factor_name][i]
                factor_scores[factor_name] = norm_value
                total_score += norm_value * weight

            scores.append(StockScore(
                code=stock,
                score=total_score,
                rank=0,  # 稍后设置
                factors=factor_scores,
                source="simple",
                confidence=0.6,  # 简单因子的置信度中等
                asof_date=date.today(),
                universe_id=universe_id,
            ))

        return scores

    def get_factor_exposure(
        self,
        stock_code: str,
        trade_date: date
    ) -> Dict[str, float]:
        """
        获取因子暴露

        Args:
            stock_code: 股票代码
            trade_date: 交易日期

        Returns:
            因子暴露字典
        """
        fundamental_data = self._get_fundamental_data([stock_code], trade_date)

        if stock_code not in fundamental_data:
            return {}

        data = fundamental_data[stock_code]
        return {
            "pe_inv": 1 / max(data.get("pe", 50), 1),
            "pb_inv": 1 / max(data.get("pb", 5), 0.5),
            "roe": max(data.get("roe", 0.1), 0),
            "dividend_yield": max(data.get("dividend_yield", 0.02), 0),
        }
