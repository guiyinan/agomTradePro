"""
个股分析模块 Domain 层实体定义

遵循四层架构规范：
- Domain 层禁止导入 django.*、pandas、numpy、requests
- 只使用 Python 标准库和 dataclasses
"""

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from typing import Optional, Dict


@dataclass(frozen=True)
class StockInfo:
    """个股基本信息（值对象）

    Attributes:
        stock_code: 股票代码（如 '000001.SZ'）
        name: 股票名称
        sector: 所属行业（申万一级行业）
        market: 交易市场（SH/SZ/BJ）
        list_date: 上市日期
    """
    stock_code: str
    name: str
    sector: str
    market: str
    list_date: date


@dataclass(frozen=True)
class FinancialData:
    """财务数据（值对象）

    Attributes:
        stock_code: 股票代码
        report_date: 报告期

        利润表（单位：元）:
        revenue: 营业收入
        net_profit: 净利润

        增长率（%）:
        revenue_growth: 营收增长率
        net_profit_growth: 净利润增长率

        资产负债表（单位：元）:
        total_assets: 总资产
        total_liabilities: 总负债
        equity: 股东权益

        财务指标（%）:
        roe: 净资产收益率
        roa: 总资产收益率
        debt_ratio: 资产负债率
    """
    stock_code: str
    report_date: date

    # 利润表（单位：元）
    revenue: Decimal
    net_profit: Decimal

    # 增长率（%）
    revenue_growth: float
    net_profit_growth: float

    # 资产负债表（单位：元）
    total_assets: Decimal
    total_liabilities: Decimal
    equity: Decimal

    # 财务指标（%）
    roe: float
    roa: float
    debt_ratio: float


@dataclass(frozen=True)
class ValuationMetrics:
    """估值指标（值对象）

    Attributes:
        stock_code: 股票代码
        trade_date: 交易日期

        估值指标:
        pe: 市盈率（动态）
        pb: 市净率
        ps: 市销率

        市值（单位：元）:
        total_mv: 总市值
        circ_mv: 流通市值

        其他指标:
        dividend_yield: 股息率（%）
    """
    stock_code: str
    trade_date: date

    pe: float
    pb: float
    ps: float
    total_mv: Decimal
    circ_mv: Decimal
    dividend_yield: float


@dataclass(frozen=True)
class TechnicalIndicators:
    """技术指标（值对象）

    Attributes:
        stock_code: 股票代码
        trade_date: 交易日期

        价格（元）:
        close: 收盘价

        均线:
        ma5: 5日均线
        ma20: 20日均线
        ma60: 60日均线

        MACD:
        macd: MACD 指标
        macd_signal: MACD 信号线
        macd_hist: MACD 柱状图

        其他:
        rsi: RSI（14日）
    """
    stock_code: str
    trade_date: date

    close: Decimal
    ma5: Optional[Decimal]
    ma20: Optional[Decimal]
    ma60: Optional[Decimal]

    macd: Optional[float]
    macd_signal: Optional[float]
    macd_hist: Optional[float]

    rsi: Optional[float]


# ==================== 通用资产分析框架集成 ====================


@dataclass(frozen=True)
class EquityAssetScore:
    """
    个股资产评分实体（集成通用资产分析框架）

    遵循组合模式（非继承），因为 Domain 层不能跨 App 依赖。
    包含个股特有的维度得分。
    """

    # ========== 个股基本信息 ==========
    stock_code: str                                # 股票代码
    stock_name: str                                # 股票名称
    sector: str                                    # 所属行业
    market: str                                    # 交易市场（SH/SZ/BJ）
    list_date: date                                # 上市日期

    # ========== 估值指标 ==========
    pe_ratio: Optional[float] = None               # 市盈率
    pb_ratio: Optional[float] = None               # 市净率
    ps_ratio: Optional[float] = None               # 市销率
    market_cap: Optional[Decimal] = None           # 总市值（元）
    dividend_yield: Optional[float] = None         # 股息率

    # ========== 财务指标 ==========
    roe: Optional[float] = None                    # 净资产收益率
    revenue_growth: Optional[float] = None         # 营收增长率
    net_profit_growth: Optional[float] = None      # 净利润增长率
    debt_ratio: Optional[float] = None             # 资产负债率

    # ========== 技术指标 ==========
    current_price: Optional[Decimal] = None        # 当前价格
    ma5: Optional[Decimal] = None                  # 5日均线
    ma20: Optional[Decimal] = None                 # 20日均线
    ma60: Optional[Decimal] = None                 # 60日均线
    rsi: Optional[float] = None                    # RSI指标

    # ========== 通用维度得分（来自 asset_analysis） ==========
    asset_type: str = "equity"                     # 固定为 "equity"
    style: Optional[str] = None                    # growth/value/blend/defensive
    size: Optional[str] = None                     # large/mid/small

    # 四大维度得分（0-100）
    regime_score: float = 0.0                      # 宏观环境得分
    policy_score: float = 0.0                      # 政策档位得分
    sentiment_score: float = 0.0                   # 舆情情绪得分
    signal_score: float = 0.0                      # 投资信号得分

    # ========== 个股特有维度得分 ==========
    # 这些维度在 custom_scores 中存储
    technical_score: float = 0.0                   # 技术面评分
    fundamental_score: float = 0.0                 # 基本面评分
    valuation_score: float = 0.0                   # 估值评分

    # ========== 综合评分 ==========
    total_score: float = 0.0                       # 综合得分
    rank: int = 0                                  # 排名

    # ========== 推荐信息 ==========
    allocation_percent: float = 0.0                # 推荐配置比例
    risk_level: str = "未知"                       # 风险等级

    # ========== 元信息 ==========
    score_date: date = field(default_factory=date.today)
    context: Optional[Dict] = None                 # 评分上下文

    def __post_init__(self):
        """初始化后处理"""
        # 1. 根据 PE 和 ROE 推断风格
        if not self.style:
            if self.pe_ratio and self.roe:
                if self.pe_ratio < 15 and self.roe > 15:
                    style = "value"  # 低PE高ROE = 价值
                elif self.pe_ratio > 30 and self.revenue_growth and self.revenue_growth > 20:
                    style = "growth"  # 高PE高增长 = 成长
                else:
                    style = "blend"
                object.__setattr__(self, 'style', style)

        # 2. 根据市值推断规模
        if not self.size and self.market_cap:
            cap = float(self.market_cap)
            if cap >= 200_000_000_000:  # 2000亿以上
                size = "large"
            elif cap >= 50_000_000_000:  # 500亿以上
                size = "mid"
            else:
                size = "small"
            object.__setattr__(self, 'size', size)

    def get_custom_scores(self) -> Dict[str, float]:
        """获取个股特有得分（用于传递给通用框架）"""
        return {
            "technical": self.technical_score,
            "fundamental": self.fundamental_score,
            "valuation": self.valuation_score,
        }

    def to_dict(self) -> dict:
        """转换为字典"""
        return {
            # 基本信息
            "stock_code": self.stock_code,
            "stock_name": self.stock_name,
            "sector": self.sector,
            "market": self.market,
            "list_date": self.list_date.isoformat(),

            # 估值指标
            "pe_ratio": self.pe_ratio,
            "pb_ratio": self.pb_ratio,
            "ps_ratio": self.ps_ratio,
            "market_cap": f"{float(self.market_cap)/100000000:.2f}亿" if self.market_cap else None,
            "dividend_yield": self.dividend_yield,

            # 财务指标
            "roe": self.roe,
            "revenue_growth": self.revenue_growth,
            "net_profit_growth": self.net_profit_growth,
            "debt_ratio": self.debt_ratio,

            # 技术指标
            "current_price": f"{float(self.current_price):.2f}" if self.current_price else None,
            "ma5": f"{float(self.ma5):.2f}" if self.ma5 else None,
            "ma20": f"{float(self.ma20):.2f}" if self.ma20 else None,
            "rsi": self.rsi,

            # 通用维度得分
            "style": self.style,
            "size": self.size,
            "regime_score": self.regime_score,
            "policy_score": self.policy_score,
            "sentiment_score": self.sentiment_score,
            "signal_score": self.signal_score,

            # 个股特有维度得分
            "technical_score": self.technical_score,
            "fundamental_score": self.fundamental_score,
            "valuation_score": self.valuation_score,

            # 综合评分
            "total_score": self.total_score,
            "rank": self.rank,

            # 推荐信息
            "allocation": f"{self.allocation_percent:.1f}%",
            "risk_level": self.risk_level,
        }

    @classmethod
    def from_stock_info(
        cls,
        stock_info: 'StockInfo',
        valuation: Optional['ValuationMetrics'] = None,
        financial: Optional['FinancialData'] = None,
        technical: Optional['TechnicalIndicators'] = None,
    ) -> 'EquityAssetScore':
        """
        从 StockInfo 创建 EquityAssetScore

        Args:
            stock_info: 个股基本信息实体
            valuation: 估值指标（可选）
            financial: 财务数据（可选）
            technical: 技术指标（可选）

        Returns:
            EquityAssetScore 实例
        """
        return cls(
            stock_code=stock_info.stock_code,
            stock_name=stock_info.name,
            sector=stock_info.sector,
            market=stock_info.market,
            list_date=stock_info.list_date,

            # 估值指标
            pe_ratio=valuation.pe if valuation else None,
            pb_ratio=valuation.pb if valuation else None,
            ps_ratio=valuation.ps if valuation else None,
            market_cap=valuation.total_mv if valuation else None,
            dividend_yield=valuation.dividend_yield if valuation else None,

            # 财务指标
            roe=financial.roe if financial else None,
            revenue_growth=financial.revenue_growth if financial else None,
            net_profit_growth=financial.net_profit_growth if financial else None,
            debt_ratio=financial.debt_ratio if financial else None,

            # 技术指标
            current_price=technical.close if technical else None,
            ma5=technical.ma5 if technical else None,
            ma20=technical.ma20 if technical else None,
            ma60=technical.ma60 if technical else None,
            rsi=technical.rsi if technical else None,
        )


@dataclass(frozen=True)
class ScoringWeightConfig:
    """股票筛选评分权重配置（值对象）

    定义股票筛选时各评分维度的权重分配。
    从数据库加载，支持通过 Django Admin 动态调整。

    Attributes:
        name: 配置名称（用于标识不同的配置方案）
        description: 配置描述
        is_active: 是否启用（当前使用的配置）

        评分权重（总和应为 1.0）:
        growth_weight: 成长性评分权重（营收增长率 + 净利润增长率）
        profitability_weight: 盈利能力评分权重（ROE）
        valuation_weight: 估值评分权重（PE 反向分位数）

        成长性内部权重:
        revenue_growth_weight: 营收增长率在成长性评分中的权重
        profit_growth_weight: 净利润增长率在成长性评分中的权重
    """
    name: str
    description: str = "默认评分权重配置"
    is_active: bool = True

    # 评分维度权重（总和应为 1.0）
    growth_weight: float = 0.4
    profitability_weight: float = 0.4
    valuation_weight: float = 0.2

    # 成长性内部权重（总和应为 1.0）
    revenue_growth_weight: float = 0.5
    profit_growth_weight: float = 0.5

    def __post_init__(self):
        """验证权重配置的合法性"""
        # 检查维度权重总和
        total_dimension_weight = (
            self.growth_weight +
            self.profitability_weight +
            self.valuation_weight
        )
        if abs(total_dimension_weight - 1.0) > 0.01:
            raise ValueError(
                f"评分维度权重总和必须为 1.0，当前为 {total_dimension_weight}"
            )

        # 检查成长性内部权重总和
        total_growth_weight = (
            self.revenue_growth_weight +
            self.profit_growth_weight
        )
        if abs(total_growth_weight - 1.0) > 0.01:
            raise ValueError(
                f"成长性内部权重总和必须为 1.0，当前为 {total_growth_weight}"
            )

        # 检查权重范围
        for weight_name, weight_value in [
            ("growth_weight", self.growth_weight),
            ("profitability_weight", self.profitability_weight),
            ("valuation_weight", self.valuation_weight),
            ("revenue_growth_weight", self.revenue_growth_weight),
            ("profit_growth_weight", self.profit_growth_weight),
        ]:
            if not (0.0 <= weight_value <= 1.0):
                raise ValueError(
                    f"{weight_name} 必须在 [0.0, 1.0] 范围内，当前为 {weight_value}"
                )

    def get_total_score(
        self,
        revenue_growth_percentile: float,
        profit_growth_percentile: float,
        roe_percentile: float,
        pe_percentile: float
    ) -> float:
        """
        根据配置计算综合评分

        Args:
            revenue_growth_percentile: 营收增长率分位数
            profit_growth_percentile: 净利润增长率分位数
            roe_percentile: ROE 分位数
            pe_percentile: PE 分位数

        Returns:
            综合评分（0-1 之间）
        """
        # 成长性评分（内部加权）
        growth_percentile = (
            revenue_growth_percentile * self.revenue_growth_weight +
            profit_growth_percentile * self.profit_growth_weight
        )

        # 估值评分（PE 反向）
        valuation_percentile = 1 - pe_percentile

        # 综合评分
        total_score = (
            growth_percentile * self.growth_weight +
            roe_percentile * self.profitability_weight +
            valuation_percentile * self.valuation_weight
        )

        return total_score
