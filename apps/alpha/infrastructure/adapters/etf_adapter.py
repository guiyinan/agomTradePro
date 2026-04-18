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
from decimal import Decimal, InvalidOperation
from typing import Dict, List, Optional

from django.conf import settings

from apps.data_center.infrastructure.legacy_sdk_bridge import get_akshare_module

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

    def supports(self, universe_id: str, pool_scope=None) -> bool:
        """
        检查是否支持指定的股票池

        Args:
            universe_id: 股票池标识
            pool_scope: 账户驱动候选池范围，ETF 降级 Provider 不使用

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
        top_n: int = 30,
        pool_scope=None,
        user=None,
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
            pool_scope: 账户驱动候选池范围，ETF 降级 Provider 不使用
            user: 当前用户，ETF 降级 Provider 不使用

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

        # 2. 获取 ETF 成分股（优先数据库，缺失时回退到远端）
        constituents_payload = self._get_etf_constituents(
            etf_info["etf_code"],
            intended_trade_date,
            top_n,
        )
        constituents, constituents_error, constituents_metadata = (
            self._normalize_constituents_payload(constituents_payload)
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
                **constituents_metadata,
                "fallback_reason": (
                    "所有其他 Provider 不可用"
                    if etf_info.get("report_date") or constituents_metadata.get("report_date")
                    else "所有其他 Provider 不可用，但当前 ETF 无可用持仓报告"
                ),
            }
        )

    @staticmethod
    def _normalize_constituents_payload(
        payload: object,
    ) -> tuple[list[tuple], str | None, dict[str, str]]:
        """Accept legacy 2-tuple mocks and normalize to the current 3-tuple contract."""
        if not isinstance(payload, tuple):
            return [], "ETF constituents payload is invalid", {}

        if len(payload) == 3:
            constituents, error_message, metadata = payload
        elif len(payload) == 2:
            constituents, error_message = payload
            metadata = {}
        else:
            return [], "ETF constituents payload has unsupported shape", {}

        normalized_constituents = constituents if isinstance(constituents, list) else []
        normalized_error = str(error_message) if error_message else None
        normalized_metadata = metadata if isinstance(metadata, dict) else {}
        return normalized_constituents, normalized_error, normalized_metadata

    def _get_etf_constituents(
        self,
        etf_code: str,
        intended_trade_date: date,
        top_n: int
    ) -> tuple[list[tuple], str | None, dict[str, str]]:
        """
        获取 ETF 成分股（优先本地真实数据，不足时回退远端真实数据）

        不使用静态成分股列表。
        如果本地和远端都没有真实持仓数据，返回空列表和错误信息。

        Args:
            etf_code: ETF 代码
            intended_trade_date: 计划交易日期
            top_n: 返回前 N 只

        Returns:
            (成分股列表, 错误信息, 元数据)
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
                return self._get_remote_etf_constituents(
                    etf_code,
                    intended_trade_date,
                    top_n,
                )

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
                return self._get_remote_etf_constituents(
                    etf_code,
                    intended_trade_date,
                    top_n,
                )

            result: list[tuple] = []
            for row in holdings:
                stock_code = row["stock_code"]
                ratio = row["holding_ratio"]
                ratio_value = float(ratio) if ratio is not None else 0.0
                result.append((stock_code, ratio_value))

            return result, None, {
                "holdings_source": "database",
                "report_date": latest_report.isoformat(),
            }

        except ImportError as e:
            return [], f"无法导入基金模型: {e}", {}
        except Exception as e:
            logger.warning("读取本地 ETF 持仓失败，尝试远端回退: %s", e)
            return self._get_remote_etf_constituents(
                etf_code,
                intended_trade_date,
                top_n,
            )

    def _get_remote_etf_constituents(
        self,
        etf_code: str,
        intended_trade_date: date,
        top_n: int,
    ) -> tuple[list[tuple], str | None, dict[str, str]]:
        fund_code = etf_code.split(".")[0]
        ak = get_akshare_module()

        for year in range(intended_trade_date.year, intended_trade_date.year - 3, -1):
            try:
                frame = ak.fund_portfolio_hold_em(symbol=fund_code, date=str(year))
            except Exception as exc:
                logger.warning(
                    "远端 ETF 持仓拉取失败: %s year=%s error=%s",
                    etf_code,
                    year,
                    exc,
                )
                continue

            if frame is None or frame.empty:
                continue

            period_col = "季度"
            code_col = "股票代码"
            ratio_col = "占净值比例"
            if (
                period_col not in frame.columns
                or code_col not in frame.columns
                or ratio_col not in frame.columns
            ):
                continue

            frame = frame.copy()
            frame["_period_rank"] = frame[period_col].map(self._quarter_sort_key)
            frame = frame.dropna(subset=["_period_rank"])
            if frame.empty:
                continue

            latest_period = frame.sort_values("_period_rank", ascending=False).iloc[0][period_col]
            latest_rows = frame.loc[frame[period_col] == latest_period].copy()
            self._persist_remote_holdings(fund_code, latest_period, latest_rows)
            latest_rows = latest_rows.head(top_n)

            result: list[tuple] = []
            for _, row in latest_rows.iterrows():
                stock_code = self._normalize_stock_code(row.get(code_col))
                if not stock_code:
                    continue
                try:
                    ratio_value = float(row.get(ratio_col) or 0.0)
                except (TypeError, ValueError):
                    ratio_value = 0.0
                result.append((stock_code, ratio_value))

            if result:
                return result, None, {
                    "holdings_source": "eastmoney",
                    "report_date": str(latest_period),
                }

        return [], f"ETF {etf_code} 没有持仓报告数据，请先同步基金持仓数据", {}

    def _persist_remote_holdings(
        self,
        fund_code: str,
        report_label: object,
        rows,
    ) -> None:
        report_date = self._parse_report_date(report_label)
        if report_date is None:
            return

        try:
            from apps.fund.infrastructure.models import FundHoldingModel

            for _, row in rows.iterrows():
                stock_code = self._normalize_stock_code(row.get("股票代码"))
                if not stock_code:
                    continue

                FundHoldingModel._default_manager.update_or_create(
                    fund_code=fund_code,
                    report_date=report_date,
                    stock_code=stock_code,
                    defaults={
                        "stock_name": str(row.get("股票名称") or stock_code),
                        "holding_amount": self._parse_int(row.get("持股数")),
                        "holding_value": self._parse_decimal(row.get("持仓市值")),
                        "holding_ratio": self._parse_float(row.get("占净值比例")),
                    },
                )
        except Exception as exc:
            logger.warning("写入远端 ETF 持仓到本地库失败: %s", exc)

    @staticmethod
    def _quarter_sort_key(raw_value: object) -> tuple[int, int] | None:
        if raw_value in (None, ""):
            return None
        match = re.search(r"(\d{4})年([1-4])季度", str(raw_value))
        if not match:
            return None
        return int(match.group(1)), int(match.group(2))

    @staticmethod
    def _normalize_stock_code(raw_value: object) -> str:
        if raw_value in (None, ""):
            return ""
        code = str(raw_value).strip()
        if "." in code:
            return code
        if code.startswith("6"):
            return f"{code}.SH"
        if code.startswith(("8", "4")):
            return f"{code}.BJ"
        return f"{code}.SZ"

    @staticmethod
    def _parse_report_date(raw_value: object) -> date | None:
        sort_key = ETFFallbackProvider._quarter_sort_key(raw_value)
        if sort_key is None:
            return None
        year, quarter = sort_key
        quarter_end = {
            1: (3, 31),
            2: (6, 30),
            3: (9, 30),
            4: (12, 31),
        }
        month, day = quarter_end[quarter]
        return date(year, month, day)

    @staticmethod
    def _parse_int(raw_value: object) -> int | None:
        if raw_value in (None, ""):
            return None
        try:
            return int(float(raw_value))
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _parse_float(raw_value: object) -> float | None:
        if raw_value in (None, ""):
            return None
        try:
            return float(raw_value)
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _parse_decimal(raw_value: object) -> Decimal | None:
        if raw_value in (None, ""):
            return None
        try:
            return Decimal(str(raw_value))
        except (InvalidOperation, TypeError, ValueError):
            return None

    def get_etf_for_universe(self, universe_id: str) -> dict[str, str]:
        """
        获取股票池对应的 ETF

        Args:
            universe_id: 股票池标识

        Returns:
            ETF 信息字典
        """
        return self._resolve_etf_info(universe_id) or {}

    def get_supported_universes(self) -> list[str]:
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
    ) -> dict[str, float]:
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

    def _resolve_etf_info(self, universe_id: str) -> dict[str, str] | None:
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
                from apps.fund.infrastructure.models import FundHoldingModel, FundInfoModel

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
            from apps.fund.infrastructure.models import FundHoldingModel, FundInfoModel

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

    def _get_config_map(self) -> dict[str, dict[str, str]]:
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
