"""
基金分析模块 - Application 层用例

遵循项目架构约束：
- 用例编排，协调 Domain 和 Infrastructure 层
- 不包含业务逻辑，只负责流程控制
- 通过依赖注入使用仓储和服务
"""

import logging
import math
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Protocol

from apps.regime.application.repository_provider import get_regime_repository
from apps.regime.domain.services_v2 import RegimeType

from ..domain.entities import (
    FundHolding,
    FundInfo,
    FundNetValue,
    FundPerformance,
    FundScore,
    FundSectorAllocation,
)
from ..domain.services import FundPerformanceCalculator, FundScreener, FundStyleAnalyzer

logger = logging.getLogger(__name__)

VALID_REGIMES = frozenset(regime.value for regime in RegimeType)


class FundRepositoryProtocol(Protocol):
    """Persistence operations required by Fund application use cases."""

    def get_fund_preferences_by_regime(self, regime: str) -> list[tuple[str, str]]: ...

    def resolve_research_window(
        self, *, requested_end_date: date, lookback_days: int = 365
    ) -> tuple[date, date]: ...

    def get_persisted_funds_with_performance(
        self, start_date: date, end_date: date
    ) -> list[tuple[FundInfo, FundPerformance, list[FundSectorAllocation]]]: ...

    def get_fund_info(self, fund_code: str) -> FundInfo | None: ...

    def get_fund_holdings(
        self, fund_code: str, report_date: date | None = None
    ) -> list[FundHolding]: ...

    def get_fund_sector_allocation(
        self, fund_code: str, report_date: date | None = None
    ) -> list[FundSectorAllocation]: ...

    def get_fund_nav(
        self,
        fund_code: str,
        start_date: date | None = None,
        end_date: date | None = None,
    ) -> list[FundNetValue]: ...

    def save_fund_performance(self, performance: FundPerformance) -> None: ...

    def sync_fund_info_from_tushare(self) -> int: ...

    def sync_fund_nav_from_tushare(self, fund_code: str, start_date: str, end_date: str) -> int: ...


@dataclass
class ScreenFundsRequest:
    """筛选基金请求"""

    regime: str | None = None  # 如果为 None，自动获取最新 Regime
    custom_types: list[str] | None = None  # 自定义基金类型
    custom_styles: list[str] | None = None  # 自定义投资风格
    min_scale: Decimal | None = None  # 最低规模
    max_count: int = 30


@dataclass
class ScreenFundsResponse:
    """筛选基金响应"""

    success: bool
    regime: str
    fund_codes: list[str]
    fund_names: list[str]  # 对应的基金名称
    screening_criteria: dict[str, object]
    error: str | None = None


@dataclass
class AnalyzeFundStyleRequest:
    """分析基金风格请求"""

    fund_code: str
    report_date: date | None = None


@dataclass
class AnalyzeFundStyleResponse:
    """分析基金风格响应"""

    success: bool
    fund_code: str
    fund_name: str
    style_weights: dict[str, float]  # {风格: 权重}
    sector_concentration: dict[str, float]  # {指标: 值}
    error: str | None = None


@dataclass
class CalculateFundPerformanceRequest:
    """计算基金业绩请求"""

    fund_code: str
    start_date: date
    end_date: date


@dataclass
class CalculateFundPerformanceResponse:
    """计算基金业绩响应"""

    success: bool
    fund_code: str
    fund_name: str
    performance: FundPerformance | None = None
    error: str | None = None


class ScreenFundsUseCase:
    """筛选基金用例"""

    def __init__(self, fund_repository: FundRepositoryProtocol) -> None:
        """初始化用例

        Args:
            fund_repository: 基金数据仓储
        """
        self.fund_repo = fund_repository
        self.screener = FundScreener()

    def execute(self, request: ScreenFundsRequest) -> ScreenFundsResponse:
        """
        执行基金筛选

        流程：
        1. 获取当前 Regime（如果未指定）
        2. 加载对应的筛选偏好配置
        3. 获取全市场基金数据
        4. 应用规则筛选
        5. 返回结果
        """
        try:
            if isinstance(request.max_count, bool) or not 1 <= request.max_count <= 100:
                raise ValueError("max_count must be between 1 and 100")
            if request.min_scale is not None and (
                not request.min_scale.is_finite() or request.min_scale < 0
            ):
                raise ValueError("min_scale must be a finite non-negative number")

            # 1. 获取 Regime
            if request.regime:
                regime = request.regime
            else:
                latest_regime = get_regime_repository().get_latest_snapshot(
                    before_date=date.today()
                )
                if latest_regime is None:
                    raise ValueError(
                        "No persisted Regime snapshot is available; provide regime explicitly."
                    )
                regime = latest_regime.dominant_regime
            if regime not in VALID_REGIMES:
                raise ValueError("regime is invalid")

            # 2. 获取筛选偏好（通过 fund 仓储加载）
            configured_preferences = self.fund_repo.get_fund_preferences_by_regime(regime)
            configured_types = list(
                dict.fromkeys(fund_type for fund_type, _style in configured_preferences)
            )
            configured_styles = list(
                dict.fromkeys(style for _fund_type, style in configured_preferences if style)
            )

            # 用户自定义类型覆盖
            preferred_types = self._normalize_preferences(request.custom_types or configured_types)
            preferred_styles = self._normalize_preferences(
                request.custom_styles or configured_styles
            )
            if not preferred_types:
                raise ValueError(f"Fund screening preferences are not configured for {regime}")

            # 3. 获取全市场基金数据
            # 获取过去一年的业绩
            start_date, end_date = self.fund_repo.resolve_research_window(
                requested_end_date=date.today(),
                lookback_days=365,
            )

            all_funds = self.fund_repo.get_persisted_funds_with_performance(
                start_date,
                end_date,
            )

            # 4. 筛选（调用 Domain 服务）
            min_scale = request.min_scale if request.min_scale is not None else Decimal(0)

            fund_codes = self.screener.screen_by_regime(
                all_funds=all_funds,
                preferred_types=preferred_types,
                preferred_styles=preferred_styles,
                min_scale=min_scale,
                max_count=request.max_count,
            )

            # 获取基金名称
            fund_names: list[str] = []
            for code in fund_codes:
                fund_info = self.fund_repo.get_fund_info(code)
                fund_names.append(fund_info.fund_name if fund_info else "")

            # 5. 返回结果
            return ScreenFundsResponse(
                success=True,
                regime=regime,
                fund_codes=fund_codes,
                fund_names=fund_names,
                screening_criteria={
                    "fund_types": preferred_types,
                    "investment_styles": preferred_styles,
                    "min_scale": str(min_scale),
                },
            )

        except Exception as exc:
            logger.error("基金筛选失败: %s", type(exc).__name__)
            return ScreenFundsResponse(
                success=False,
                regime=request.regime or "",
                fund_codes=[],
                fund_names=[],
                screening_criteria={},
                error="基金筛选失败，请检查 Regime、筛选偏好和本地业绩数据",
            )

    @staticmethod
    def _normalize_preferences(values: list[str]) -> list[str]:
        """Normalize configured or caller-provided preference labels."""

        return list(dict.fromkeys(value.strip() for value in values if value.strip()))


class RankFundsUseCase:
    """基金排名用例"""

    def __init__(self, fund_repository: FundRepositoryProtocol) -> None:
        """初始化用例"""
        self.fund_repo = fund_repository
        self.screener = FundScreener()

    def execute(
        self,
        regime: str,
        max_count: int | None = 50,
        as_of_date: date | None = None,
    ) -> list[FundScore]:
        """
        执行基金排名

        Args:
            regime: Regime 名称
            max_count: 最多返回基金数量

        Returns:
            排名后的基金评分列表
        """
        if regime not in VALID_REGIMES:
            raise ValueError("regime is invalid")
        if max_count is not None and (isinstance(max_count, bool) or not 1 <= max_count <= 200):
            raise ValueError("max_count must be between 1 and 200")
        if as_of_date is not None and as_of_date > date.today():
            raise ValueError("as_of_date must not be in the future")

        # 1. 获取全市场基金数据
        start_date, end_date = self.fund_repo.resolve_research_window(
            requested_end_date=as_of_date or date.today(),
            lookback_days=365,
        )

        all_funds = self.fund_repo.get_persisted_funds_with_performance(
            start_date,
            end_date,
        )

        # 2. 获取 Regime 权重配置
        preferred_types = list(
            dict.fromkeys(
                fund_type
                for fund_type, _style in self.fund_repo.get_fund_preferences_by_regime(regime)
            )
        )
        if not preferred_types:
            raise ValueError(f"Fund ranking preferences are not configured for {regime}")
        regime_weights = dict.fromkeys(preferred_types, 1.0)

        # 3. 排名（调用 Domain 服务）
        fund_scores = self.screener.rank_funds(funds_data=all_funds, regime_weights=regime_weights)

        return fund_scores[:max_count] if max_count is not None else fund_scores


class AnalyzeFundStyleUseCase:
    """分析基金风格用例"""

    def __init__(self, fund_repository: FundRepositoryProtocol) -> None:
        """初始化用例"""
        self.fund_repo = fund_repository
        self.style_analyzer = FundStyleAnalyzer()

    def execute(self, request: AnalyzeFundStyleRequest) -> AnalyzeFundStyleResponse:
        """
        执行基金风格分析

        流程：
        1. 获取基金信息
        2. 获取基金持仓
        3. 分析持仓风格
        4. 分析行业集中度
        5. 返回结果
        """
        try:
            normalized_code = request.fund_code.strip().upper().removesuffix(".OF")
            if not normalized_code:
                raise ValueError("fund_code is required")
            # 1. 获取基金信息
            fund_info = self.fund_repo.get_fund_info(normalized_code)
            if not fund_info:
                return AnalyzeFundStyleResponse(
                    success=False,
                    fund_code=normalized_code,
                    fund_name="",
                    style_weights={},
                    sector_concentration={},
                    error=f"基金 {normalized_code} 不存在",
                )

            # 2. 获取基金持仓
            holdings = self.fund_repo.get_fund_holdings(normalized_code, request.report_date)

            if not holdings:
                return AnalyzeFundStyleResponse(
                    success=False,
                    fund_code=normalized_code,
                    fund_name=fund_info.fund_name,
                    style_weights={},
                    sector_concentration={},
                    error=f"基金 {normalized_code} 暂无持仓数据",
                )

            # 3. 分析持仓风格
            style_weights = self.style_analyzer.analyze_holding_style(holdings)

            # 4. 获取行业配置
            sector_alloc = self.fund_repo.get_fund_sector_allocation(
                normalized_code, request.report_date
            )

            # 5. 分析行业集中度
            sector_concentration = self.style_analyzer.analyze_sector_concentration(sector_alloc)

            # 6. 返回结果
            return AnalyzeFundStyleResponse(
                success=True,
                fund_code=request.fund_code,
                fund_name=fund_info.fund_name,
                style_weights=style_weights,
                sector_concentration=sector_concentration,
            )

        except Exception as exc:
            logger.error("基金风格分析失败: %s", type(exc).__name__)
            return AnalyzeFundStyleResponse(
                success=False,
                fund_code=normalized_code,
                fund_name="",
                style_weights={},
                sector_concentration={},
                error="基金风格分析失败，请检查基金与持仓数据",
            )


class CalculateFundPerformanceUseCase:
    """计算基金业绩用例"""

    def __init__(self, fund_repository: FundRepositoryProtocol) -> None:
        """初始化用例"""
        self.fund_repo = fund_repository
        self.perf_calculator = FundPerformanceCalculator()

    def execute(self, request: CalculateFundPerformanceRequest) -> CalculateFundPerformanceResponse:
        """
        执行基金业绩计算

        流程：
        1. 获取基金信息
        2. 获取净值数据
        3. 计算各项业绩指标
        4. 保存到数据库
        5. 返回结果
        """
        try:
            normalized_code = request.fund_code.strip().upper().removesuffix(".OF")
            if not normalized_code:
                raise ValueError("fund_code is required")
            if request.start_date > request.end_date:
                raise ValueError("start_date must not be after end_date")
            # 1. 获取基金信息
            fund_info = self.fund_repo.get_fund_info(normalized_code)
            if not fund_info:
                return CalculateFundPerformanceResponse(
                    success=False,
                    fund_code=request.fund_code,
                    fund_name="",
                    error=f"基金 {request.fund_code} 不存在",
                )

            # 2. 获取净值数据
            nav_series = self.fund_repo.get_fund_nav(
                normalized_code, request.start_date, request.end_date
            )

            if not nav_series or len(nav_series) < 2:
                return CalculateFundPerformanceResponse(
                    success=False,
                    fund_code=request.fund_code,
                    fund_name=fund_info.fund_name,
                    error=f"基金 {request.fund_code} 净值数据不足",
                )

            # 3. 计算业绩指标
            # 区间收益率
            total_return = self.perf_calculator.calculate_total_return(nav_series)

            # 年化收益率
            days = (nav_series[-1].nav_date - nav_series[0].nav_date).days
            annualized_return = self.perf_calculator.calculate_annualized_return(total_return, days)

            # 波动率
            daily_returns = [
                nav.daily_return
                for nav in nav_series
                if nav.daily_return is not None and math.isfinite(nav.daily_return)
            ]
            volatility = (
                self.perf_calculator.calculate_volatility(daily_returns)
                if len(daily_returns) >= 2
                else None
            )

            # 夏普比率
            sharpe_ratio = None
            if volatility and volatility > 0:
                sharpe_ratio = self.perf_calculator.calculate_sharpe_ratio(
                    annualized_return, volatility
                )

            # 最大回撤
            max_drawdown = self.perf_calculator.calculate_max_drawdown(nav_series)

            # 构造业绩实体
            performance = FundPerformance(
                fund_code=normalized_code,
                start_date=nav_series[0].nav_date,
                end_date=nav_series[-1].nav_date,
                total_return=total_return,
                annualized_return=annualized_return,
                volatility=volatility,
                sharpe_ratio=sharpe_ratio,
                max_drawdown=max_drawdown,
                beta=None,
                alpha=None,
            )

            # 4. 保存到数据库
            self.fund_repo.save_fund_performance(performance)

            # 5. 返回结果
            return CalculateFundPerformanceResponse(
                success=True,
                fund_code=normalized_code,
                fund_name=fund_info.fund_name,
                performance=performance,
            )

        except Exception as exc:
            logger.error("基金业绩计算失败: %s", type(exc).__name__)
            return CalculateFundPerformanceResponse(
                success=False,
                fund_code=request.fund_code,
                fund_name="",
                error="基金业绩计算失败，请检查日期范围和净值数据",
            )


class SyncFundDataUseCase:
    """同步基金数据用例"""

    def __init__(self, fund_repository: FundRepositoryProtocol) -> None:
        """初始化用例"""
        self.fund_repo = fund_repository

    def sync_fund_list(self) -> dict[str, int]:
        """
        同步基金列表

        Returns:
            {操作: 数量} 字典
        """
        count = self.fund_repo.sync_fund_info_from_tushare()
        return {"synced": count}

    def sync_fund_nav(self, fund_code: str, start_date: str, end_date: str) -> dict[str, int]:
        """
        同步单个基金净值

        Args:
            fund_code: 基金代码
            start_date: 开始日期（'20240101'）
            end_date: 结束日期（'20241231'）

        Returns:
            {操作: 数量} 字典
        """
        count = self.fund_repo.sync_fund_nav_from_tushare(fund_code, start_date, end_date)
        return {"synced": count}
