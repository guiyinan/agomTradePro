"""
ETF Fallback Alpha Provider

使用 ETF 成分股作为最后防线的 Provider。
当所有其他 Provider 都不可用时，使用 ETF 持仓作为推荐。
优先级为 1000（最低）。

重构说明 (2026-03-15):
- 删除静态持仓兜底，不再使用硬编码的成分股数据
- 必须从数据库 FundHoldingModel 获取真实持仓数据
- 如果没有真实数据，返回错误而不是使用假数据
"""

import logging
import re
from datetime import date
from typing import Dict, List, Optional

from django.conf import settings
from ...domain.entities import AlphaResult, StockScore
from ...domain.interfaces import AlphaProviderStatus
from .base import BaseAlphaProvider, create_stock_score, provider_safe


logger = logging.getLogger(__name__)


class ETFFallbackProvider(BaseAlphaProvider):
    """
    ETF 降级 Provider

    使用 ETF 成分股作为推荐，作为最后的降级方案。
    优先级为 1000（最低），仅在其他所有 Provider 都不可用时使用。

    数据来源：
    - 必须从 FundHoldingModel 获取真实持仓数据
    - 不再使用硬编码的静态成分股列表

    Attributes:
        priority: 1000（最低优先级）
        max_staleness_days: 30 天（ETF 成分变化不频繁）

    Example:
        >>> provider = ETFFallbackProvider()
        >>> result = provider.get_stock_scores("csi300", date.today())
        >>> if result.success:
        ...     print(f"Using ETF fallback, got {len(result.scores)} stocks")
    """

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
        return self._resolve_etf_info(universe_id) is not None

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
        etf_info = self._resolve_etf_info(universe_id)
        if not etf_info:
            return self._create_error_result(
                f"无法为股票池 {universe_id} 解析可用 ETF（请在 ALPHA_UNIVERSE_ETF_MAP 中配置）",
                status="unavailable",
            )

        # 2. 获取 ETF 成分股（数据库）
        constituents, constituents_error = self._get_etf_constituents(
            etf_info["etf_code"],
            top_n
        )

        if not constituents:
            error_msg = constituents_error or f"无法获取 ETF {etf_info['etf_code']} 的真实成分股"
            return self._create_error_result(
                f"{error_msg}。请先同步 ETF 持仓数据: python manage.py sync_fund_holdings --fund-code {etf_info['etf_code'].split('.')[0]}"
            )

        # 3. 创建评分
        scores = []
        for i, (stock_code, holding_ratio_pct) in enumerate(constituents, 1):
            # 直接使用持仓占比(%)作为降级评分，范围 0~100
            score = max(0.0, min(100.0, float(holding_ratio_pct)))

            scores.append(create_stock_score(
                code=stock_code,
                score=score,
                rank=i,
                source="etf",
                factors={"holding_ratio_pct": float(holding_ratio_pct)},
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
                "report_date": etf_info.get("report_date"),
                "fallback_reason": (
                    "所有其他 Provider 不可用"
                    if etf_info.get("report_date")
                    else "所有其他 Provider 不可用，但当前 ETF 无可用持仓报告"
                ),
            }
        )

    def _get_etf_constituents(
        self,
        etf_code: str,
        top_n: int
    ) -> tuple[List[tuple], Optional[str]]:
        """
        获取 ETF 成分股（仅从真实数据源）

        不再使用静态成分股列表作为兜底。
        如果没有真实持仓数据，返回空列表和错误信息。

        Args:
            etf_code: ETF 代码
            top_n: 返回前 N 只

        Returns:
            (成分股列表, 错误信息)
            成分股列表格式: [(股票代码, 权重), ...]
        """
        try:
            from apps.fund.infrastructure.models import FundHoldingModel

            fund_code = etf_code.split(".")[0]

            # 获取最新报告日期
            latest_report = (
                FundHoldingModel._default_manager.filter(fund_code=fund_code)
                .order_by("-report_date")
                .values_list("report_date", flat=True)
                .first()
            )

            if not latest_report:
                return [], f"ETF {etf_code} 没有持仓报告数据，请先同步基金持仓数据"

            # 获取持仓数据
            holdings = list(
                FundHoldingModel._default_manager.filter(
                    fund_code=fund_code,
                    report_date=latest_report,
                ).order_by("-holding_ratio", "-holding_value").values(
                    "stock_code", "holding_ratio"
                )[:top_n]
            )

            if not holdings:
                return [], f"ETF {etf_code} 报告日期 {latest_report} 没有持仓记录"

            result: List[tuple] = []
            for row in holdings:
                stock_code = row["stock_code"]
                ratio = row["holding_ratio"]
                ratio_value = float(ratio) if ratio is not None else 0.0
                result.append((stock_code, ratio_value))

            return result, None

        except ImportError as e:
            return [], f"无法导入基金模型: {e}"
        except Exception as e:
            return [], f"获取 ETF {etf_code} 持仓时发生错误: {e}"

    def get_etf_for_universe(self, universe_id: str) -> Dict[str, str]:
        """
        获取股票池对应的 ETF

        Args:
            universe_id: 股票池标识

        Returns:
            ETF 信息字典
        """
        return self._resolve_etf_info(universe_id) or {}

    def get_supported_universes(self) -> List[str]:
        """
        获取支持的股票池列表

        Returns:
            股票池标识列表
        """
        config_map = self._get_config_map()
        return sorted(list(config_map.keys()))

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

    def _resolve_etf_info(self, universe_id: str) -> Optional[Dict[str, str]]:
        """优先使用 settings 映射，再尝试根据 universe_id 自动发现 ETF。"""
        config_map = self._get_config_map()
        mapped = config_map.get(universe_id)
        if mapped:
            mapped_code = mapped.get("etf_code", "")
            resolved_code = mapped_code if "." in mapped_code else f"{mapped_code}.SH"
            etf_info = {
                "etf_code": resolved_code,
                "etf_name": mapped.get("etf_name", resolved_code),
                "report_date": None,
            }
            try:
                from apps.fund.infrastructure.models import FundInfoModel, FundHoldingModel

                fund_code = resolved_code.split(".")[0]
                fund = FundInfoModel._default_manager.filter(fund_code=fund_code).first()
                latest_report = (
                    FundHoldingModel._default_manager.filter(fund_code=fund_code)
                    .order_by("-report_date")
                    .values_list("report_date", flat=True)
                    .first()
                )
                if fund:
                    etf_info["etf_name"] = fund.fund_name
                if latest_report:
                    etf_info["report_date"] = latest_report.isoformat()
            except Exception:
                pass
            return etf_info

        # 自动发现：在指数/ETF基金中找名字最匹配且有持仓数据的基金
        digits = "".join(re.findall(r"\d+", universe_id))
        if not digits:
            return None
        try:
            from apps.fund.infrastructure.models import FundInfoModel, FundHoldingModel

            query = FundInfoModel._default_manager.filter(is_active=True).filter(fund_name__icontains="ETF")
            if digits:
                query = query.filter(fund_name__icontains=digits)

            candidates = list(query.order_by("-fund_scale", "fund_code")[:30])
            for fund in candidates:
                latest_report = (
                    FundHoldingModel._default_manager.filter(fund_code=fund.fund_code)
                    .order_by("-report_date")
                    .values_list("report_date", flat=True)
                    .first()
                )
                if latest_report:
                    market_suffix = ".SZ" if fund.fund_code.startswith(("15", "16")) else ".SH"
                    return {
                        "etf_code": f"{fund.fund_code}{market_suffix}",
                        "etf_name": fund.fund_name,
                        "report_date": latest_report.isoformat(),
                    }
        except Exception:
            pass
        return None

    def _get_config_map(self) -> Dict[str, Dict[str, str]]:
        """获取股票池到 ETF 的映射配置"""
        config_map = getattr(settings, "ALPHA_UNIVERSE_ETF_MAP", {}) or {}
        merged = self.DEFAULT_UNIVERSE_ETF_MAP.copy()
        merged.update(config_map)
        return merged

    # 股票池到 ETF 的默认映射（不含成分股数据）
    # 成分股数据必须从 FundHoldingModel 获取
    DEFAULT_UNIVERSE_ETF_MAP = {
        "csi300": {"etf_code": "510300.SH", "etf_name": "沪深300ETF"},
        "csi500": {"etf_code": "510500.SH", "etf_name": "中证500ETF"},
        "sse50": {"etf_code": "510050.SH", "etf_name": "上证50ETF"},
        "csi1000": {"etf_code": "512100.SH", "etf_name": "中证1000ETF"},
    }
