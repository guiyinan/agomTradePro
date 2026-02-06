"""
ETF Fallback Alpha Provider

使用 ETF 成分股作为最后防线的 Provider。
当所有其他 Provider 都不可用时，使用 ETF 持仓作为推荐。
优先级为 1000（最低）。
"""

import logging
from datetime import date
from typing import Dict, List

from ...domain.entities import AlphaResult, StockScore
from ...domain.interfaces import AlphaProviderStatus
from .base import BaseAlphaProvider, create_stock_score, provider_safe


logger = logging.getLogger(__name__)


class ETFFallbackProvider(BaseAlphaProvider):
    """
    ETF 降级 Provider

    使用 ETF 成分股作为推荐，作为最后的降级方案。
    优先级为 1000（最低），仅在其他所有 Provider 都不可用时使用。

    逻辑：
    - 根据 universe_id 匹配对应的 ETF
    - 使用 ETF 前十大重仓股
    - 按权重分配评分

    Attributes:
        priority: 1000（最低优先级）
        max_staleness_days: 30 天（ETF 成分变化不频繁）

    Example:
        >>> provider = ETFFallbackProvider()
        >>> result = provider.get_stock_scores("csi300", date.today())
        >>> if result.success:
        ...     print(f"Using ETF fallback, got {len(result.scores)} stocks")
    """

    # Universe 到 ETF 的映射
    UNIVERSE_ETF_MAP = {
        "csi300": {
            "etf_code": "510300.SH",
            "etf_name": "沪深300ETF",
            "index_code": "000300.SH",
        },
        "csi500": {
            "etf_code": "510500.SH",
            "etf_name": "中证500ETF",
            "index_code": "000905.SH",
        },
        "sse50": {
            "etf_code": "510050.SH",
            "etf_name": "上证50ETF",
            "index_code": "000016.SH",
        },
        "csi1000": {
            "etf_code": "512100.SH",
            "etf_name": "中证1000ETF",
            "index_code": "000852.SH",
        },
        "cyb": {
            "etf_code": "159915.SZ",
            "etf_name": "创业板ETF",
            "index_code": "399006.SZ",
        },
    }

    def __init__(self):
        """初始化 ETF Provider"""
        super().__init__()

    @property
    def name(self) -> str:
        """Provider 名称"""
        return "etf"

    @property
    def priority(self) -> int:
        """优先级"""
        return 1000

    @property
    def max_staleness_days(self) -> int:
        """最大陈旧天数"""
        return 30

    def supports(self, universe_id: str) -> bool:
        """
        检查是否支持指定的股票池

        Args:
            universe_id: 股票池标识

        Returns:
            是否支持
        """
        return universe_id in self.UNIVERSE_ETF_MAP

    @provider_safe(default_success=False)
    def health_check(self) -> AlphaProviderStatus:
        """
        健康检查

        ETF Provider 总是可用，因为它使用静态配置。

        Returns:
            Provider 状态
        """
        return AlphaProviderStatus.AVAILABLE

    @provider_safe()
    def get_stock_scores(
        self,
        universe_id: str,
        intended_trade_date: date,
        top_n: int = 30
    ) -> AlphaResult:
        """
        获取 ETF 成分股评分

        1. 查找对应的 ETF
        2. 获取成分股和权重
        3. 按权重分配评分

        Args:
            universe_id: 股票池标识
            intended_trade_date: 计划交易日期
            top_n: 返回前 N 只

        Returns:
            AlphaResult
        """
        if not self.supports(universe_id):
            return self._create_error_result(
                f"不支持的股票池: {universe_id}",
                status="unavailable"
            )

        # 1. 获取 ETF 信息
        etf_info = self.UNIVERSE_ETF_MAP[universe_id]

        # 2. 获取成分股（模拟数据）
        constituents = self._get_etf_constituents(
            etf_info["etf_code"],
            top_n
        )

        if not constituents:
            return self._create_error_result(
                f"无法获取 ETF {etf_info['etf_code']} 的成分股"
            )

        # 3. 创建评分
        scores = []
        for i, (stock_code, weight) in enumerate(constituents, 1):
            # 评分与权重成正比
            score = weight * 100

            scores.append(create_stock_score(
                code=stock_code,
                score=score,
                rank=i,
                source="etf",
                factors={"etf_weight": weight},
                confidence=0.4,  # 低置信度，因为是降级方案
                asof_date=intended_trade_date,
                intended_trade_date=intended_trade_date,
                universe_id=universe_id,
            ))

        return self._create_success_result(
            scores=scores,
            metadata={
                "etf_code": etf_info["etf_code"],
                "etf_name": etf_info["etf_name"],
                "index_code": etf_info["index_code"],
                "fallback_reason": "所有其他 Provider 不可用",
            }
        )

    def _get_etf_constituents(
        self,
        etf_code: str,
        top_n: int
    ) -> List[tuple]:
        """
        获取 ETF 成分股

        返回 (股票代码, 权重) 的列表

        Args:
            etf_code: ETF 代码
            top_n: 返回前 N 只

        Returns:
            (股票代码, 权重) 列表
        """
        # 模拟数据 - 实际实现中应该从数据库或 API 获取
        mock_constituents = {
            "510300.SH": [  # 沪深300ETF
                ("600519.SH", 4.5),  # 贵州茅台
                ("000333.SH", 3.2),  # 美的集团
                ("600036.SH", 2.8),  # 招商银行
                ("601318.SH", 2.5),  # 中国平安
                ("000858.SH", 2.1),  # 五粮液
                ("600887.SH", 1.9),  # 伊利股份
                ("000002.SH", 1.8),  # 万科A
                ("600000.SH", 1.7),  # 浦发银行
                ("601012.SH", 1.6),  # 隆基绿能
                ("000001.SH", 1.5),  # 平安银行
            ],
            "510500.SH": [  # 中证500ETF
                ("000063.SH", 1.2),
                ("002475.SZ", 1.1),
                ("600276.SH", 1.0),
                ("002594.SZ", 0.9),
                ("603259.SH", 0.8),
            ],
            "510050.SH": [  # 上证50ETF
                ("600519.SH", 8.5),
                ("601318.SH", 6.2),
                ("600036.SH", 5.1),
                ("000333.SH", 4.8),
                ("601012.SH", 4.2),
            ],
        }

        constituents = mock_constituents.get(etf_code, [])

        # 确保按权重降序排列
        constituents.sort(key=lambda x: x[1], reverse=True)

        return constituents[:top_n]

    def get_etf_for_universe(self, universe_id: str) -> Dict[str, str]:
        """
        获取股票池对应的 ETF

        Args:
            universe_id: 股票池标识

        Returns:
            ETF 信息字典
        """
        return self.UNIVERSE_ETF_MAP.get(universe_id, {})

    def get_supported_universes(self) -> List[str]:
        """
        获取支持的股票池列表

        Returns:
            股票池标识列表
        """
        return list(self.UNIVERSE_ETF_MAP.keys())

    def get_factor_exposure(
        self,
        stock_code: str,
        trade_date: date
    ) -> Dict[str, float]:
        """
        获取因子暴露

        ETF Provider 不提供因子暴露，返回空字典。

        Args:
            stock_code: 股票代码
            trade_date: 交易日期

        Returns:
            空字典
        """
        return {}
