"""
数据交叉校验

在多个数据源之间比对数据，大偏差时告警而非静默切换。
遵循 CLAUDE.md: "切换前必须校验数据一致性（容差 1%）"。
"""

import logging
from decimal import Decimal
from typing import Dict, List, Optional, Tuple

from apps.market_data.domain.entities import QuoteSnapshot
from apps.market_data.domain.enums import DataCapability
from apps.market_data.infrastructure.registries.source_registry import SourceRegistry

logger = logging.getLogger(__name__)

# 价格偏差容差：超过此比例视为异常
PRICE_TOLERANCE_PCT = 1.0
# 严重偏差阈值：超过此比例直接告警
PRICE_ALERT_THRESHOLD_PCT = 5.0


def _pct_diff(a: Decimal, b: Decimal) -> float:
    """计算两个价格之间的百分比偏差"""
    if a == 0 and b == 0:
        return 0.0
    base = max(a, b)
    if base == 0:
        return 100.0
    return float(abs(a - b) / base * 100)


class CrossValidationResult:
    """交叉校验结果"""

    def __init__(self) -> None:
        self.matches: List[str] = []       # 一致的股票
        self.deviations: List[Dict] = []   # 有偏差的股票
        self.alerts: List[Dict] = []       # 严重偏差需告警
        self.missing_in_primary: List[str] = []   # 主源缺失
        self.missing_in_secondary: List[str] = []  # 备源缺失

    @property
    def total_checked(self) -> int:
        return len(self.matches) + len(self.deviations) + len(self.alerts)

    @property
    def is_clean(self) -> bool:
        return len(self.alerts) == 0 and len(self.deviations) == 0

    def to_dict(self) -> dict:
        return {
            "total_checked": self.total_checked,
            "matches": len(self.matches),
            "deviations": self.deviations,
            "alerts": self.alerts,
            "missing_in_primary": self.missing_in_primary,
            "missing_in_secondary": self.missing_in_secondary,
            "is_clean": self.is_clean,
        }


def cross_validate_quotes(
    primary: List[QuoteSnapshot],
    secondary: List[QuoteSnapshot],
    tolerance_pct: float = PRICE_TOLERANCE_PCT,
    alert_threshold_pct: float = PRICE_ALERT_THRESHOLD_PCT,
) -> CrossValidationResult:
    """交叉校验两组行情数据

    Args:
        primary: 主数据源的行情
        secondary: 备数据源的行情
        tolerance_pct: 正常容差百分比
        alert_threshold_pct: 告警阈值百分比

    Returns:
        CrossValidationResult
    """
    result = CrossValidationResult()

    primary_map: Dict[str, QuoteSnapshot] = {s.stock_code: s for s in primary}
    secondary_map: Dict[str, QuoteSnapshot] = {s.stock_code: s for s in secondary}

    all_codes = set(primary_map.keys()) | set(secondary_map.keys())

    for code in all_codes:
        p = primary_map.get(code)
        s = secondary_map.get(code)

        if p is None:
            result.missing_in_primary.append(code)
            continue
        if s is None:
            result.missing_in_secondary.append(code)
            continue

        diff = _pct_diff(p.price, s.price)

        if diff <= tolerance_pct:
            result.matches.append(code)
        elif diff <= alert_threshold_pct:
            result.deviations.append({
                "stock_code": code,
                "primary_price": str(p.price),
                "primary_source": p.source,
                "secondary_price": str(s.price),
                "secondary_source": s.source,
                "diff_pct": round(diff, 3),
            })
            logger.warning(
                "价格偏差: %s primary=%s(%s) secondary=%s(%s) diff=%.3f%%",
                code, p.price, p.source, s.price, s.source, diff,
            )
        else:
            result.alerts.append({
                "stock_code": code,
                "primary_price": str(p.price),
                "primary_source": p.source,
                "secondary_price": str(s.price),
                "secondary_source": s.source,
                "diff_pct": round(diff, 3),
            })
            logger.error(
                "严重价格偏差告警: %s primary=%s(%s) secondary=%s(%s) diff=%.3f%%",
                code, p.price, p.source, s.price, s.source, diff,
            )

    return result


def validate_and_select(
    registry: SourceRegistry,
    stock_codes: List[str],
) -> Tuple[List[QuoteSnapshot], Optional[CrossValidationResult]]:
    """获取行情并做交叉校验

    1. 从最高优先级 provider 获取数据
    2. 如果有备用 provider，取部分样本做交叉校验
    3. 大偏差时记录告警，但仍返回主源数据（不静默切换）

    Returns:
        (行情列表, 校验结果 or None)
    """
    providers = registry.get_providers(DataCapability.REALTIME_QUOTE)
    if not providers:
        return [], None

    # 主源获取
    primary_provider = providers[0]
    primary_data = primary_provider.get_quote_snapshots(stock_codes)

    if not primary_data:
        # 主源失败，尝试备用
        for fallback in providers[1:]:
            fallback_data = fallback.get_quote_snapshots(stock_codes)
            if fallback_data:
                logger.warning(
                    "主源 %s 失败，回退到 %s",
                    primary_provider.provider_name(),
                    fallback.provider_name(),
                )
                return fallback_data, None
        return [], None

    # 如果有备用源，抽样交叉校验
    if len(providers) >= 2:
        secondary_provider = providers[1]
        # 只抽样校验前 5 只，避免对备用源造成压力
        sample_codes = [s.stock_code for s in primary_data[:5]]
        try:
            secondary_data = secondary_provider.get_quote_snapshots(sample_codes)
            if secondary_data:
                sample_primary = [s for s in primary_data if s.stock_code in set(sample_codes)]
                validation = cross_validate_quotes(sample_primary, secondary_data)
                if validation.alerts:
                    logger.error(
                        "交叉校验发现 %d 个严重偏差 (%s vs %s)",
                        len(validation.alerts),
                        primary_provider.provider_name(),
                        secondary_provider.provider_name(),
                    )
                return primary_data, validation
        except Exception:
            logger.warning("交叉校验备用源失败，跳过校验", exc_info=True)

    return primary_data, None
