"""
个股分析模块 Domain 层筛选规则定义

遵循四层架构规范：
- Domain 层禁止导入 django.*、pandas、numpy、requests
- 只使用 Python 标准库和 dataclasses
"""

from dataclasses import dataclass
from decimal import Decimal


@dataclass
class StockScreeningRule:
    """个股筛选规则（值对象）

    ⚠️ 规则库从数据库加载，不在此处硬编码
    使用 apps.equity.infrastructure.config_loader.get_stock_screening_rule(regime) 获取规则

    Attributes:
        regime: 适用的 Regime（Recovery/Overheat/Stagflation/Deflation）
        name: 规则名称

        财务指标阈值:
        min_roe: 最低 ROE（%）
        min_revenue_growth: 最低营收增长率（%）
        min_profit_growth: 最低净利润增长率（%）
        max_debt_ratio: 最高资产负债率（%）

        估值指标阈值:
        max_pe: 最高 PE
        max_pb: 最高 PB
        min_market_cap: 最低市值（元）

        行业偏好:
        sector_preference: 偏好行业列表

        筛选数量:
        max_count: 最多返回个股数量
    """
    # 基础信息
    regime: str
    name: str

    # 财务指标要求
    min_roe: float = 0.0
    min_revenue_growth: float = 0.0
    min_profit_growth: float = 0.0
    max_debt_ratio: float = 100.0

    # 估值指标要求
    max_pe: float = 999.0
    max_pb: float = 999.0
    min_market_cap: Decimal = Decimal(0)

    # 行业偏好
    sector_preference: list[str] | None = None

    # 筛选数量
    max_count: int = 50
