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
from datetime import date, timedelta

from django.conf import settings
from django.db.models import Max
from django.utils import timezone

from ...domain.entities import AlphaPoolScope, AlphaResult, StockScore
from ...domain.interfaces import AlphaProviderStatus
from .base import BaseAlphaProvider, provider_safe

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
            from apps.data_center.infrastructure.models import QuoteSnapshotModel
            from apps.equity.infrastructure.models import ValuationModel

            # 检查是否有最近 7 天内的估值数据
            cutoff_date = date.today() - timedelta(days=7)
            has_data = ValuationModel._default_manager.filter(
                trade_date__gte=cutoff_date
            ).exists()
            quote_cutoff = timezone.now() - timedelta(hours=4)
            has_fresh_quotes = QuoteSnapshotModel._default_manager.filter(
                snapshot_at__gte=quote_cutoff
            ).exists()

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
        user=None,
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
            from apps.equity.infrastructure.models import ValuationModel

            if pool_scope is not None and pool_scope.instrument_codes:
                return list(pool_scope.instrument_codes)

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

    def _compute_quote_momentum_scores(
        self,
        *,
        stock_list: list[str],
        universe_id: str,
        intended_trade_date: date,
    ) -> tuple[list[StockScore], dict[str, object], int | None]:
        """Build a data-driven intraday Alpha fallback from fresh quote snapshots."""

        try:
            from apps.data_center.infrastructure.models import QuoteSnapshotModel
        except ImportError as exc:
            return [], {"quote_error": f"无法导入实时行情模型: {exc}"}, None

        quote_cutoff = timezone.now() - timedelta(hours=4)
        normalized_codes = [str(code or "").strip().upper() for code in stock_list if code]
        snapshots = (
            QuoteSnapshotModel._default_manager.filter(
                asset_code__in=normalized_codes,
                snapshot_at__gte=quote_cutoff,
            )
            .order_by("asset_code", "-snapshot_at")
        )
        latest_by_code = {}
        for snapshot in snapshots:
            code = str(snapshot.asset_code or "").upper()
            latest_by_code.setdefault(code, snapshot)

        raw_rows: list[dict[str, object]] = []
        latest_snapshot_at = None
        for code in normalized_codes:
            snapshot = latest_by_code.get(code)
            if snapshot is None:
                continue
            current_price = float(snapshot.current_price or 0.0)
            prev_close = float(snapshot.prev_close or 0.0)
            open_price = float(snapshot.open or 0.0)
            high = float(snapshot.high or 0.0)
            low = float(snapshot.low or 0.0)
            volume = float(snapshot.volume or 0.0)
            if current_price <= 0 or prev_close <= 0:
                continue

            intraday_return = (current_price - prev_close) / prev_close
            open_gap = (current_price - open_price) / open_price if open_price > 0 else 0.0
            range_position = 0.5
            if high > low:
                range_position = min(max((current_price - low) / (high - low), 0.0), 1.0)
            raw_rows.append(
                {
                    "code": code,
                    "snapshot_at": snapshot.snapshot_at,
                    "intraday_return": intraday_return,
                    "range_position": range_position,
                    "liquidity": math.log1p(max(volume, 0.0)),
                    "open_gap": open_gap,
                }
            )
            if latest_snapshot_at is None or snapshot.snapshot_at > latest_snapshot_at:
                latest_snapshot_at = snapshot.snapshot_at

        if not raw_rows:
            return [], {
                "quote_count": len(latest_by_code),
                "price_momentum_count": 0,
                "quote_error": "账户池内没有 freshness 阈值内的可评分实时行情。",
            }, None

        normalized_factors = {
            factor: self._normalize_factor_values([float(row[factor]) for row in raw_rows])
            for factor in ("intraday_return", "range_position", "liquidity", "open_gap")
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
            "pe_inv": 1 / max(data.get("pe", 50), 1),
            "pb_inv": 1 / max(data.get("pb", 5), 0.5),
            "roe": max(data.get("roe", 0.1), 0),
            "dividend_yield": max(data.get("dividend_yield", 0.02), 0),
        }
