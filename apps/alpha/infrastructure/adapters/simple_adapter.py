"""
Simple Alpha Provider

使用简单财务因子（PE/PB/ROE）计算股票评分的 Provider。
作为 Qlib 降级方案，优先级为 100。

重构说明 (2026-03-15):
- 删除伪随机数据生成，从真实数据源获取基本面数据
- 如果获取不到数据，返回空并给出错误提示
"""

import logging
from datetime import date, timedelta
from decimal import Decimal
from typing import Dict, List, Optional

from django.conf import settings
from django.db.models import Max, Q

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

    数据来源：
    - PE、PB、股息率：equity.ValuationModel（估值数据表）
    - ROE：equity.FinancialDataModel（财务数据表）

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
            from apps.equity.infrastructure.models import ValuationModel

            # 检查是否有最近 7 天内的估值数据
            cutoff_date = date.today() - timedelta(days=7)
            has_data = ValuationModel._default_manager.filter(
                trade_date__gte=cutoff_date
            ).exists()

            if has_data:
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
        # 1. 获取股票池（从数据库获取有估值数据的股票）
        stock_list = self._get_universe_stocks(universe_id, intended_trade_date)
        if not stock_list:
            return self._create_error_result(
                f"股票池 {universe_id} 中没有可用的估值数据，请先同步估值数据"
            )

        # 2. 获取基本面数据
        fundamental_data, data_quality = self._get_fundamental_data(
            stock_list,
            intended_trade_date
        )

        if not fundamental_data:
            return self._create_error_result(
                f"无法获取基本面数据: {data_quality.get('error', '未知错误')}。"
                f"请确保已运行估值数据同步命令: python manage.py sync_equity_valuation"
            )

        # 3. 计算评分
        scores = self._compute_scores(fundamental_data, universe_id, intended_trade_date)

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
                universe_id=universe_id,
            )

        return self._create_success_result(
            scores=top_scores,
            metadata={
                "universe_size": len(stock_list),
                "scored_count": len(scores),
                "factor_weights": self._factor_weights,
                "data_quality": data_quality,
            }
        )

    def _get_universe_stocks(
        self,
        universe_id: str,
        trade_date: date
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
            from apps.equity.infrastructure.models import ValuationModel

            # 优先使用配置的股票池映射
            configured = getattr(settings, "ALPHA_SIMPLE_UNIVERSE_MAP", {}) or {}
            if universe_id in configured and configured[universe_id]:
                # 过滤出有估值数据的股票
                configured_stocks = list(configured[universe_id])
                available_stocks = list(
                    ValuationModel._default_manager.filter(
                        stock_code__in=configured_stocks,
                        trade_date__lte=trade_date
                    )
                    .values_list('stock_code', flat=True)
                    .distinct()
                )
                return available_stocks

            # 从数据库获取有估值数据的所有股票
            # 查找最近的估值数据日期
            latest_date = ValuationModel._default_manager.aggregate(
                max_date=Max('trade_date')
            ).get('max_date')

            if not latest_date:
                logger.warning("数据库中没有估值数据")
                return []

            # 获取该日期有估值数据的所有股票
            stocks = list(
                ValuationModel._default_manager.filter(
                    trade_date=latest_date
                )
                .values_list('stock_code', flat=True)
                .order_by('stock_code')
            )

            logger.info(
                f"SimpleAlphaProvider 从数据库获取股票池: "
                f"universe={universe_id}, date={latest_date}, count={len(stocks)}"
            )
            return stocks

        except Exception as e:
            logger.error(f"获取股票池失败: {e}")
            return []

    def _get_fundamental_data(
        self,
        stock_list: list[str],
        trade_date: date
    ) -> tuple[dict[str, dict[str, float]], dict[str, any]]:
        """
        从数据库获取真实的基本面数据。

        数据来源：
        - PE、PB、股息率：ValuationModel
        - ROE：FinancialDataModel

        Args:
            stock_list: 股票列表
            trade_date: 交易日期

        Returns:
            (基本面数据字典, 数据质量信息)
        """
        fundamentals: dict[str, dict[str, float]] = {}
        data_quality = {
            "valuation_count": 0,
            "financial_count": 0,
            "complete_count": 0,
            "partial_count": 0,
            "missing_count": 0,
            "error": None,
        }

        try:
            from apps.equity.infrastructure.models import (
                FinancialDataModel,
                ValuationModel,
            )

            # 1. 获取最近的估值数据
            latest_valuation_date = ValuationModel._default_manager.aggregate(
                max_date=Max('trade_date')
            ).get('max_date')

            if not latest_valuation_date:
                data_quality["error"] = "估值数据表中没有任何数据"
                return {}, data_quality

            # 获取估值数据
            valuations = {
                v.stock_code: v
                for v in ValuationModel._default_manager.filter(
                    stock_code__in=stock_list,
                    trade_date=latest_valuation_date
                )
            }
            data_quality["valuation_count"] = len(valuations)

            # 2. 获取最新的财务数据（ROE）
            # 使用子查询获取每只股票的最新财务数据
            financials = {}
            for stock_code in stock_list:
                latest_financial = FinancialDataModel._default_manager.filter(
                    stock_code=stock_code
                ).order_by('-report_date').first()

                if latest_financial:
                    financials[stock_code] = latest_financial

            data_quality["financial_count"] = len(financials)

            # 3. 合并数据
            for stock_code in stock_list:
                valuation = valuations.get(stock_code)
                financial = financials.get(stock_code)

                # 检查数据完整性
                has_valuation = valuation is not None
                has_financial = financial is not None
                has_pe = has_valuation and valuation.pe is not None and valuation.pe > 0
                has_pb = has_valuation and valuation.pb is not None and valuation.pb > 0
                has_dividend = has_valuation and valuation.dividend_yield is not None
                has_roe = has_financial and financial.roe is not None

                # 至少需要 PE 或 PB 才能计算评分
                if not has_pe and not has_pb:
                    data_quality["missing_count"] += 1
                    continue

                # 提取数据
                pe = float(valuation.pe) if has_pe else None
                pb = float(valuation.pb) if has_pb else None
                dividend_yield = float(valuation.dividend_yield) if has_dividend else 0.0
                roe = float(financial.roe) if has_roe else None

                # 使用默认值填充缺失的数据
                fundamentals[stock_code] = {
                    "pe": pe if pe is not None else 50.0,  # 默认中等 PE
                    "pb": pb if pb is not None else 3.0,   # 默认中等 PB
                    "roe": roe if roe is not None else 0.08,  # 默认 8% ROE
                    "dividend_yield": dividend_yield if dividend_yield > 0 else 0.02,  # 默认 2% 股息率
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
                    f"估值数据日期: {latest_valuation_date}, "
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
        fundamental_data: dict[str, dict[str, float]],
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
        scores = []

        # 1. 提取因子值
        factor_values = {name: [] for name in self._factor_weights}
        stock_list = list(fundamental_data.keys())

        for stock in stock_list:
            data = fundamental_data[stock]
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
        for i, stock in enumerate(stock_list):
            data = fundamental_data[stock]
            data_quality = data.get("_data_quality", {})

            factor_scores = {}
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
            "pe_inv": 1 / max(data.get("pe", 50), 1),
            "pb_inv": 1 / max(data.get("pb", 5), 0.5),
            "roe": max(data.get("roe", 0.1), 0),
            "dividend_yield": max(data.get("dividend_yield", 0.02), 0),
        }
