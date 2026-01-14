"""
指标定义和映射

统一管理所有指标代码，避免重复定义。

架构说明：
- IndicatorDefinition: 指标定义（代码、名称、类别、单位、别名等）
- INDICATOR_REGISTRY: 指标注册表（所有可用指标的字典）
- get_indicator(): 通过代码获取指标
- find_indicator_by_alias(): 通过别名查找指标
"""

from dataclasses import dataclass
from enum import Enum
from typing import Dict, List, Optional


class IndicatorCategory(Enum):
    """指标类别"""
    GROWTH = "growth"      # 增长指标
    INFLATION = "inflation" # 通胀指标
    INTEREST = "interest"   # 利率指标
    MARKET = "market"      # 市场指标


@dataclass(frozen=True)
class IndicatorDefinition:
    """指标定义

    包含指标的基本信息和元数据。
    """
    code: str                     # 标准代码
    name: str                     # 中文名称
    category: IndicatorCategory   # 类别
    unit: str                     # 单位
    aliases: List[str]            # 别名（用于解析自然语言）
    suggested_threshold: Optional[float] = None  # 建议阈值


# 指标注册表
# 所有指标定义的单一事实来源
INDICATOR_REGISTRY: Dict[str, IndicatorDefinition] = {
    # ==================== 增长指标 ====================
    "CN_PMI_MANUFACTURING": IndicatorDefinition(
        code="CN_PMI_MANUFACTURING",
        name="制造业PMI",
        category=IndicatorCategory.GROWTH,
        unit="指数",
        aliases=["pmi", "制造业pmi", "采购经理指数", "非制造业pmi"],
        suggested_threshold=50.0,
    ),
    "CN_PMI_NON_MANUFACTURING": IndicatorDefinition(
        code="CN_PMI_NON_MANUFACTURING",
        name="非制造业PMI",
        category=IndicatorCategory.GROWTH,
        unit="指数",
        aliases=["非制造业pmi", "服务业pmi"],
        suggested_threshold=50.0,
    ),
    "CN_GDP_YOY": IndicatorDefinition(
        code="CN_GDP_YOY",
        name="GDP同比",
        category=IndicatorCategory.GROWTH,
        unit="%",
        aliases=["gdp", "国内生产总值", "经济增速"],
    ),
    "CN_INDUSTRIAL_PRODUCTION_YOY": IndicatorDefinition(
        code="CN_INDUSTRIAL_PRODUCTION_YOY",
        name="工业增加值同比",
        category=IndicatorCategory.GROWTH,
        unit="%",
        aliases=["工业增加值", "工业产出"],
    ),

    # ==================== 通胀指标 ====================
    "CN_CPI_YOY": IndicatorDefinition(
        code="CN_CPI_YOY",
        name="CPI同比",
        category=IndicatorCategory.INFLATION,
        unit="%",
        aliases=["cpi", "消费者物价指数", "通胀", "物价"],
        suggested_threshold=2.0,
    ),
    "CN_CPI_MOY": IndicatorDefinition(
        code="CN_CPI_MOY",
        name="CPI环比",
        category=IndicatorCategory.INFLATION,
        unit="%",
        aliases=["cpi环比", "消费者物价环比"],
    ),
    "CN_PPI_YOY": IndicatorDefinition(
        code="CN_PPI_YOY",
        name="PPI同比",
        category=IndicatorCategory.INFLATION,
        unit="%",
        aliases=["ppi", "生产者物价指数", "出厂价格"],
    ),
    "CN_PPI_MOY": IndicatorDefinition(
        code="CN_PPI_MOY",
        name="PPI环比",
        category=IndicatorCategory.INFLATION,
        unit="%",
        aliases=["ppi环比", "生产者物价环比"],
    ),

    # ==================== 利率指标 ====================
    "SHIBOR_O_N": IndicatorDefinition(
        code="SHIBOR_O_N",
        name="SHIBOR隔夜",
        category=IndicatorCategory.INTEREST,
        unit="%",
        aliases=["shibor隔夜", "隔夜shibor"],
    ),
    "SHIBOR_1M": IndicatorDefinition(
        code="SHIBOR_1M",
        name="SHIBOR 1月",
        category=IndicatorCategory.INTEREST,
        unit="%",
        aliases=["shibor", "shibor1月", "银行间利率", "拆借利率"],
    ),
    "CN_LPR_1Y": IndicatorDefinition(
        code="CN_LPR_1Y",
        name="LPR 1年",
        category=IndicatorCategory.INTEREST,
        unit="%",
        aliases=["lpr", "lpr1年", "贷款利率", "市场利率"],
    ),

    # ==================== 货币供应量 ====================
    "CN_M2_YOY": IndicatorDefinition(
        code="CN_M2_YOY",
        name="M2同比",
        category=IndicatorCategory.GROWTH,
        unit="%",
        aliases=["m2", "m2同比", "货币供应量", "广义货币"],
    ),

    # ==================== 市场指标 ====================
    "000001.SH": IndicatorDefinition(
        code="000001.SH",
        name="上证指数",
        category=IndicatorCategory.MARKET,
        unit="点",
        aliases=["上证", "上证指数", "大盘", "沪深"],
    ),
    "399001.SZ": IndicatorDefinition(
        code="399001.SZ",
        name="深证成指",
        category=IndicatorCategory.MARKET,
        unit="点",
        aliases=["深证", "深证成指"],
    ),
    "399006.SZ": IndicatorDefinition(
        code="399006.SZ",
        name="创业板指",
        category=IndicatorCategory.MARKET,
        unit="点",
        aliases=["创业板", "创业板指"],
    ),

    # ==================== 汇率指标 ====================
    "USDCNY": IndicatorDefinition(
        code="USDCNY",
        name="美元人民币",
        category=IndicatorCategory.MARKET,
        unit="",
        aliases=["美元人民币", "usdcny", "人民币汇率", "汇率"],
    ),

    # ==================== 商品指标 ====================
    "AU9999.SGE": IndicatorDefinition(
        code="AU9999.SGE",
        name="黄金现货",
        category=IndicatorCategory.MARKET,
        unit="元/g",
        aliases=["黄金", "金价", "黄金现货"],
    ),
}


# ==================== 公共函数 ====================

def get_indicator(code: str) -> Optional[IndicatorDefinition]:
    """获取指标定义

    Args:
        code: 指标代码

    Returns:
        IndicatorDefinition 或 None
    """
    return INDICATOR_REGISTRY.get(code)


def find_indicator_by_alias(alias: str) -> Optional[IndicatorDefinition]:
    """通过别名查找指标

    支持模糊匹配，用于解析自然语言输入。

    优先匹配最长匹配的指标（避免"PMI"匹配到"PMI_NON_MANUFACTURING"）

    Args:
        alias: 别名或部分名称（可以是完整句子）

    Returns:
        IndicatorDefinition 或 None
    """
    alias_lower = alias.lower()
    best_match = None
    best_match_length = 0

    # 检查所有指标的别名和名称
    for indicator in INDICATOR_REGISTRY.values():
        # 检查别名（从长到短检查，优先匹配更具体的）
        for a in sorted(indicator.aliases, key=len, reverse=True):
            if a.lower() in alias_lower:
                # 找到匹配，记录最长的匹配
                if len(a) > best_match_length:
                    best_match = indicator
                    best_match_length = len(a)
                break

        # 检查代码
        if alias_lower == indicator.code.lower():
            return indicator

        # 检查名称
        if indicator.name.lower() in alias_lower:
            if len(indicator.name) > best_match_length:
                best_match = indicator
                best_match_length = len(indicator.name)

    return best_match


def get_all_indicators() -> List[IndicatorDefinition]:
    """获取所有指标

    Returns:
        List[IndicatorDefinition]: 所有指标定义
    """
    return list(INDICATOR_REGISTRY.values())


def get_indicators_by_category(category: IndicatorCategory) -> List[IndicatorDefinition]:
    """按类别获取指标

    Args:
        category: 指标类别

    Returns:
        List[IndicatorDefinition]: 该类别的所有指标
    """
    return [
        ind for ind in INDICATOR_REGISTRY.values()
        if ind.category == category
    ]


def register_indicator(indicator: IndicatorDefinition) -> None:
    """注册新指标

    用于动态添加指标定义。

    Args:
        indicator: 指标定义
    """
    global INDICATOR_REGISTRY
    INDICATOR_REGISTRY = {**INDICATOR_REGISTRY, indicator.code: indicator}
