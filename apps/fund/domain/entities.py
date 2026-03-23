"""
基金分析模块 - Domain 层实体定义

遵循项目架构约束：
- 使用 dataclasses 定义值对象
- 不依赖任何外部库（pandas、numpy、django等）
- 只使用 Python 标准库
"""

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from typing import Dict, List, Optional


@dataclass(frozen=True)
class FundInfo:
    """基金基本信息（值对象）

    Attributes:
        fund_code: 基金代码（如 '110011'）
        fund_name: 基金名称
        fund_type: 基金类型（股票型/债券型/混合型/指数型/货币型/QDII等）
        investment_style: 投资风格（成长/价值/平衡/商品等）
        setup_date: 成立日期
        management_company: 管理人
        custodian: 托管人
        fund_scale: 基金规模（元）
    """
    fund_code: str
    fund_name: str
    fund_type: str  # '股票型', '债券型', '混合型', '指数型', '货币型', 'QDII', '商品型'
    investment_style: str | None = None  # '成长', '价值', '平衡', '商品', '稳健'
    setup_date: date | None = None
    management_company: str | None = None
    custodian: str | None = None
    fund_scale: Decimal | None = None  # 单位：元


@dataclass(frozen=True)
class FundManager:
    """基金经理信息（值对象）

    Attributes:
        fund_code: 基金代码
        manager_name: 经理姓名
        tenure_start: 任职开始日期
        tenure_end: 任职结束日期（None 表示在任）
        total_tenure_days: 任期天数
        fund_return: 任期期间基金收益率
    """
    fund_code: str
    manager_name: str
    tenure_start: date
    tenure_end: date | None = None
    total_tenure_days: int | None = None
    fund_return: float | None = None  # %


@dataclass(frozen=True)
class FundNetValue:
    """基金净值数据（值对象）

    Attributes:
        fund_code: 基金代码
        nav_date: 净值日期
        unit_nav: 单位净值
        accum_nav: 累计净值
        daily_return: 日收益率（%）
        daily_return_optional: 可选的日收益率（某些情况下可能为空）
    """
    fund_code: str
    nav_date: date
    unit_nav: Decimal
    accum_nav: Decimal
    daily_return: float | None = None


@dataclass(frozen=True)
class FundHolding:
    """基金持仓数据（值对象）

    Attributes:
        fund_code: 基金代码
        report_date: 报告期
        stock_code: 股票代码
        stock_name: 股票名称
        holding_amount: 持有数量（股）
        holding_value: 持有市值（元）
        holding_ratio: 占净值比例（%）
    """
    fund_code: str
    report_date: date
    stock_code: str
    stock_name: str
    holding_amount: int | None = None
    holding_value: Decimal | None = None
    holding_ratio: float | None = None


@dataclass(frozen=True)
class FundSectorAllocation:
    """基金行业配置（值对象）

    Attributes:
        fund_code: 基金代码
        report_date: 报告期
        sector_name: 行业名称
        allocation_ratio: 配置比例（%）
    """
    fund_code: str
    report_date: date
    sector_name: str
    allocation_ratio: float


@dataclass(frozen=True)
class FundPerformance:
    """基金业绩指标（值对象）

    Attributes:
        fund_code: 基金代码
        start_date: 计算起始日期
        end_date: 计算结束日期
        total_return: 区间收益率（%）
        annualized_return: 年化收益率（%）
        volatility: 波动率（%）
        sharpe_ratio: 夏普比率
        max_drawdown: 最大回撤（%）
        beta: 贝塔系数
        alpha: 阿尔法（%）
    """
    fund_code: str
    start_date: date
    end_date: date
    total_return: float
    annualized_return: float | None = None
    volatility: float | None = None
    sharpe_ratio: float | None = None
    max_drawdown: float | None = None
    beta: float | None = None
    alpha: float | None = None


@dataclass(frozen=True)
class FundScore:
    """基金综合评分（值对象）

    Attributes:
        fund_code: 基金代码
        fund_name: 基金名称
        score_date: 评分日期
        performance_score: 业绩评分（0-100）
        regime_fit_score: Regime 适配度评分（0-100）
        risk_score: 风险评分（0-100）
        scale_score: 规模评分（0-100）
        total_score: 综合评分（0-100）
        rank: 排名
    """
    fund_code: str
    fund_name: str
    score_date: date
    performance_score: float
    regime_fit_score: float
    risk_score: float
    scale_score: float
    total_score: float
    rank: int


# ==================== 通用资产分析框架集成 ====================
# 以下实体继承自 apps.asset_analysis 的通用实体


@dataclass(frozen=True)
class FundAssetScore:
    """
    基金资产评分实体（继承自通用资产评分）

    继承关系：FundAssetScore -> AssetScore (来自 asset_analysis)
    包含基金特有的维度得分。

    注意：这是 Fund 模块对通用资产分析的扩展实现。
    由于 Domain 层不能跨 App 依赖，这里使用组合而非继承。
    """

    # ========== 基金基本信息 ==========
    fund_code: str                                 # 基金代码
    fund_name: str                                 # 基金名称
    fund_type: str                                 # 基金类型
    investment_style: str | None = None         # 投资风格
    fund_company: str | None = None             # 基金公司
    fund_manager: str | None = None             # 基金经理
    establishment_date: date | None = None      # 成立日期
    fund_scale: Decimal | None = None           # 基金规模

    # ========== 通用维度得分（来自 asset_analysis） ==========
    # 这些维度由通用框架计算
    asset_type: str = "fund"                       # 固定为 "fund"
    style: str | None = None                    # 映射到通用风格
    size: str | None = None                     # 大盘/中盘/小盘
    sector: str | None = None                   # 行业（对基金不适用）

    # 四大维度得分（0-100）
    regime_score: float = 0.0                      # 宏观环境得分
    policy_score: float = 0.0                      # 政策档位得分
    sentiment_score: float = 0.0                   # 舆情情绪得分
    signal_score: float = 0.0                      # 投资信号得分

    # ========== 基金特有维度得分 ==========
    # 这些维度在 custom_scores 中存储
    manager_score: float = 0.0                     # 基金经理评分
    fund_flow_score: float = 0.0                   # 资金流向评分
    fund_size_score: float = 0.0                   # 基金规模评分
    performance_score: float = 0.0                 # 历史业绩评分

    # ========== 综合评分 ==========
    total_score: float = 0.0                       # 综合得分
    rank: int = 0                                  # 排名

    # ========== 推荐信息 ==========
    allocation_percent: float = 0.0                # 推荐配置比例
    risk_level: str = "未知"                       # 风险等级

    # ========== 元信息 ==========
    score_date: date = field(default_factory=date.today)
    context: dict | None = None                 # 评分上下文

    def __post_init__(self):
        """初始化后处理"""
        # 映射 investment_style 到通用 style
        if not self.style and self.investment_style:
            style_mapping = {
                "成长": "growth",
                "价值": "value",
                "平衡": "blend",
                "稳健": "defensive",
            }
            style = style_mapping.get(self.investment_style)
            if style:
                object.__setattr__(self, 'style', style)

        # 映射 fund_scale 到通用 size
        if not self.size and self.fund_scale:
            scale = float(self.fund_scale)
            if scale >= 50_000_000_000:  # 500亿以上
                size = "large"
            elif scale >= 10_000_000_000:  # 100亿以上
                size = "mid"
            else:
                size = "small"
            object.__setattr__(self, 'size', size)

    def get_custom_scores(self) -> dict[str, float]:
        """获取基金特有得分（用于传递给通用框架）"""
        return {
            "manager": self.manager_score,
            "flow": self.fund_flow_score,
            "size": self.fund_size_score,
            "performance": self.performance_score,
        }

    def to_dict(self) -> dict:
        """转换为字典"""
        return {
            # 基本信息
            "fund_code": self.fund_code,
            "fund_name": self.fund_name,
            "fund_type": self.fund_type,
            "investment_style": self.investment_style,
            "fund_company": self.fund_company,
            "fund_manager": self.fund_manager,
            "establishment_date": (
                self.establishment_date.isoformat() if self.establishment_date else None
            ),

            # 通用维度得分
            "regime_score": self.regime_score,
            "policy_score": self.policy_score,
            "sentiment_score": self.sentiment_score,
            "signal_score": self.signal_score,

            # 基金特有维度得分
            "manager_score": self.manager_score,
            "fund_flow_score": self.fund_flow_score,
            "fund_size_score": self.fund_size_score,
            "performance_score": self.performance_score,

            # 综合评分
            "total_score": self.total_score,
            "rank": self.rank,

            # 推荐信息
            "allocation": f"{self.allocation_percent:.1f}%",
            "risk_level": self.risk_level,
        }

    @classmethod
    def from_fund_info(cls, fund_info: 'FundInfo') -> 'FundAssetScore':
        """
        从 FundInfo 创建 FundAssetScore

        Args:
            fund_info: 基金基本信息实体

        Returns:
            FundAssetScore 实例
        """
        return cls(
            fund_code=fund_info.fund_code,
            fund_name=fund_info.fund_name,
            fund_type=fund_info.fund_type,
            investment_style=fund_info.investment_style,
            establishment_date=fund_info.setup_date,
            fund_company=fund_info.management_company,
            fund_scale=fund_info.fund_scale,
        )
