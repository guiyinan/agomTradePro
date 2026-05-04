"""
基金分析模块 - 数据仓储实现

遵循项目架构约束：
- 实现 Domain 层定义的接口（如果需要）
- 封装 Django ORM 操作
- 提供数据访问方法
"""

import math
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Dict, List, Optional, Tuple

from django.db.models import Avg, Max, Min, Q, Sum
from django.utils import timezone

from apps.data_center.application.dtos import SyncFundNavRequest
from apps.data_center.application.use_cases import SyncFundNavUseCase
from apps.data_center.infrastructure.provider_factory import UnifiedProviderFactory
from apps.data_center.infrastructure.repositories import (
    FundNavRepository as DataCenterFundNavRepository,
)
from apps.data_center.infrastructure.repositories import ProviderConfigRepository
from apps.data_center.infrastructure.repositories import RawAuditRepository
from ..domain.entities import (
    FundAssetScore,
    FundHolding,
    FundInfo,
    FundManager,
    FundNetValue,
    FundPerformance,
    FundSectorAllocation,
)
from ..domain.services import FundPerformanceCalculator
from .models import (
    FundHoldingModel,
    FundInfoModel,
    FundManagerModel,
    FundNetValueModel,
    FundPerformanceModel,
    FundSectorAllocationModel,
    FundTypePreferenceConfigModel,
)

# ==================== 通用资产分析框架集成 ====================
# 实现 AssetRepositoryProtocol 接口以支持通用资产分析


class DjangoFundAssetRepository:
    """
    基金资产仓储（实现 AssetRepositoryProtocol）

    为通用资产分析框架提供基金数据访问接口。
    """

    def __init__(self):
        """初始化仓储"""
        self.fund_repo = DjangoFundRepository()

    def get_assets_by_filter(
        self, asset_type: str, filters: dict, max_count: int = 100
    ) -> list[FundAssetScore]:
        """
        根据过滤条件获取资产列表

        Args:
            asset_type: 资产类型（应为 "fund"）
            filters: 过滤条件字典
                - fund_type: 基金类型
                - investment_style: 投资风格
                - min_scale: 最小规模（元）
                - max_scale: 最大规模（元）
                - fund_company: 基金公司
            max_count: 最大返回数量

        Returns:
            FundAssetScore 实体列表
        """
        if asset_type != "fund":
            return []

        # 构建查询
        queryset = FundInfoModel._default_manager.filter(is_active=True)

        # 应用过滤条件
        fund_type = filters.get("fund_type")
        if fund_type:
            queryset = queryset.filter(fund_type=fund_type)

        investment_style = filters.get("investment_style")
        if investment_style:
            queryset = queryset.filter(investment_style=investment_style)

        min_scale = filters.get("min_scale")
        if min_scale is not None:
            queryset = queryset.filter(fund_scale__gte=min_scale)

        max_scale = filters.get("max_scale")
        if max_scale is not None:
            queryset = queryset.filter(fund_scale__lte=max_scale)

        fund_company = filters.get("fund_company")
        if fund_company:
            queryset = queryset.filter(management_company__icontains=fund_company)

        # 限制数量并排序
        models = queryset.order_by("-fund_scale")[:max_count]

        # 转换为 FundAssetScore 实体
        return [
            FundAssetScore.from_fund_info(self.fund_repo._model_to_entity_info(m)) for m in models
        ]

    def get_asset_by_code(self, asset_type: str, asset_code: str) -> FundAssetScore | None:
        """
        根据代码获取资产

        Args:
            asset_type: 资产类型（应为 "fund"）
            asset_code: 基金代码

        Returns:
            FundAssetScore 实体，不存在则返回 None
        """
        if asset_type != "fund":
            return None

        try:
            model = FundInfoModel._default_manager.get(fund_code=asset_code, is_active=True)
            fund_info = self.fund_repo._model_to_entity_info(model)
            return FundAssetScore.from_fund_info(fund_info)
        except FundInfoModel.DoesNotExist:
            return None


class DjangoFundRepository:
    """Django ORM 基金数据仓储

    职责：
    1. 提供基金数据的 CRUD 操作
    2. 封装复杂查询逻辑
    3. 处理数据同步
    """

    def __init__(self):
        """初始化仓储"""
        from .adapters.akshare_fund_adapter import AkShareFundAdapter
        from .adapters.tushare_fund_adapter import TushareFundAdapter

        self.tushare_adapter = TushareFundAdapter()
        self.akshare_adapter = AkShareFundAdapter()
        self._dc_fund_nav_repo = DataCenterFundNavRepository()
        self._provider_repo = ProviderConfigRepository()
        self._provider_factory = UnifiedProviderFactory(self._provider_repo)
        self._raw_audit_repo = RawAuditRepository()
        self._perf_calculator = FundPerformanceCalculator()

    # ==================== 基金信息 ====================

    def get_fund_info(self, fund_code: str) -> FundInfo | None:
        """获取单个基金信息

        Args:
            fund_code: 基金代码

        Returns:
            FundInfo 或 None
        """
        try:
            model = FundInfoModel._default_manager.get(fund_code=fund_code, is_active=True)
            return self._model_to_entity_info(model)
        except FundInfoModel.DoesNotExist:
            return None

    def resolve_fund_names(self, codes: list[str]) -> dict[str, str]:
        """批量解析基金名称。"""
        normalized_codes = [str(code).upper() for code in codes if code]
        if not normalized_codes:
            return {}

        code_to_fund_code = {code: code.split(".")[0] for code in normalized_codes}
        models = FundInfoModel._default_manager.filter(
            fund_code__in=list(set(code_to_fund_code.values())),
            is_active=True,
        )
        name_map = {model.fund_code: model.fund_name for model in models if model.fund_name}
        return {
            code: name_map[fund_code]
            for code, fund_code in code_to_fund_code.items()
            if fund_code in name_map
        }

    def get_all_funds(self, fund_type: str | None = None) -> list[FundInfo]:
        """获取所有基金信息

        Args:
            fund_type: 基金类型过滤

        Returns:
            基金信息列表
        """
        queryset = FundInfoModel._default_manager.filter(is_active=True)

        if fund_type:
            queryset = queryset.filter(fund_type=fund_type)

        models = queryset.all()
        return [self._model_to_entity_info(m) for m in models]

    def get_fund_type_preferences_by_regime(self, regime: str) -> list[str]:
        """Return preferred fund types for one regime ordered by priority."""

        return list(
            FundTypePreferenceConfigModel._default_manager.filter(
                regime=regime,
                is_active=True,
            )
            .order_by("-priority")
            .values_list("fund_type", flat=True)
        )

    def save_fund_info(self, fund_info: FundInfo) -> None:
        """保存或更新基金信息

        Args:
            fund_info: 基金信息实体
        """
        FundInfoModel._default_manager.update_or_create(
            fund_code=fund_info.fund_code,
            defaults={
                "fund_name": fund_info.fund_name,
                "fund_type": fund_info.fund_type,
                "investment_style": fund_info.investment_style,
                "setup_date": fund_info.setup_date,
                "management_company": fund_info.management_company,
                "custodian": fund_info.custodian,
                "fund_scale": fund_info.fund_scale,
                "is_active": True,
            },
        )

    # ==================== 基金净值 ====================

    def get_fund_nav(
        self, fund_code: str, start_date: date | None = None, end_date: date | None = None
    ) -> list[FundNetValue]:
        """获取基金净值数据

        Args:
            fund_code: 基金代码
            start_date: 起始日期
            end_date: 结束日期

        Returns:
            净值数据列表
        """
        dc_facts = self._dc_fund_nav_repo.get_series(
            fund_code=fund_code,
            start=start_date,
            end=end_date,
        )
        if dc_facts:
            return [self._dc_fact_to_entity_nav(fact) for fact in reversed(dc_facts)]

        queryset = FundNetValueModel._default_manager.filter(fund_code=fund_code)

        if start_date:
            queryset = queryset.filter(nav_date__gte=start_date)
        if end_date:
            queryset = queryset.filter(nav_date__lte=end_date)

        queryset = queryset.order_by("nav_date")

        models = queryset.all()
        return [self._model_to_entity_nav(m) for m in models]

    def get_latest_nav(self, fund_code: str) -> FundNetValue | None:
        """获取最新净值

        Args:
            fund_code: 基金代码

        Returns:
            最新净值或 None
        """
        latest_fact = self._dc_fund_nav_repo.get_latest(fund_code)
        if latest_fact is not None:
            return self._dc_fact_to_entity_nav(latest_fact)

        try:
            model = (
                FundNetValueModel._default_manager.filter(fund_code=fund_code)
                .order_by("-nav_date")
                .first()
            )

            if model:
                return self._model_to_entity_nav(model)
            return None
        except Exception:
            return None

    def save_fund_nav(self, nav: FundNetValue) -> None:
        """保存或更新基金净值

        Args:
            nav: 净值实体
        """
        FundNetValueModel._default_manager.update_or_create(
            fund_code=nav.fund_code,
            nav_date=nav.nav_date,
            defaults={
                "unit_nav": nav.unit_nav,
                "accum_nav": nav.accum_nav,
                "daily_return": nav.daily_return,
            },
        )
        self._dc_fund_nav_repo.bulk_upsert([self._entity_nav_to_dc_fact(nav)])

    def save_fund_nav_batch(self, nav_list: list[FundNetValue]) -> None:
        """批量保存基金净值

        Args:
            nav_list: 净值实体列表
        """
        for nav in nav_list:
            self.save_fund_nav(nav)

    # ==================== 基金持仓 ====================

    def get_fund_holdings(
        self, fund_code: str, report_date: date | None = None
    ) -> list[FundHolding]:
        """获取基金持仓数据

        Args:
            fund_code: 基金代码
            report_date: 报告期（None 表示最新）

        Returns:
            持仓数据列表
        """
        queryset = FundHoldingModel._default_manager.filter(fund_code=fund_code)

        if report_date:
            queryset = queryset.filter(report_date=report_date)
        else:
            # 获取最新报告期
            latest_date = queryset.aggregate(Max("report_date"))["report_date__max"]
            if latest_date:
                queryset = queryset.filter(report_date=latest_date)

        queryset = queryset.order_by("-holding_ratio")

        models = queryset.all()
        return [self._model_to_entity_holding(m) for m in models]

    def resolve_stock_names_from_holdings(self, codes: list[str]) -> dict[str, str]:
        """从基金持仓回填股票名称。"""
        normalized_codes = [str(code).upper() for code in codes if code]
        if not normalized_codes:
            return {}

        code_to_base = {code: code.split(".")[0] for code in normalized_codes}
        resolved: dict[str, str] = {}

        rows = (
            FundHoldingModel._default_manager.filter(stock_code__in=normalized_codes)
            .order_by("stock_code", "-report_date")
            .values("stock_code", "stock_name")
        )
        seen_codes: set[str] = set()
        for row in rows:
            stock_code = row["stock_code"]
            stock_name = row["stock_name"]
            if not stock_code or not stock_name or stock_code in seen_codes:
                continue
            seen_codes.add(stock_code)
            resolved[str(stock_code).upper()] = stock_name

        if len(resolved) == len(normalized_codes):
            return resolved

        base_rows = (
            FundHoldingModel._default_manager.filter(
                stock_code__in=list(set(code_to_base.values()))
            )
            .order_by("stock_code", "-report_date")
            .values("stock_code", "stock_name")
        )
        base_name_map: dict[str, str] = {}
        for row in base_rows:
            stock_code = row["stock_code"]
            stock_name = row["stock_name"]
            if stock_code and stock_name and stock_code not in base_name_map:
                base_name_map[str(stock_code).upper()] = stock_name

        for code, base_code in code_to_base.items():
            if code not in resolved and base_code.upper() in base_name_map:
                resolved[code] = base_name_map[base_code.upper()]

        return resolved

    def save_fund_holding(self, holding: FundHolding) -> None:
        """保存或更新基金持仓

        Args:
            holding: 持仓实体
        """
        FundHoldingModel._default_manager.update_or_create(
            fund_code=holding.fund_code,
            report_date=holding.report_date,
            stock_code=holding.stock_code,
            defaults={
                "stock_name": holding.stock_name,
                "holding_amount": holding.holding_amount,
                "holding_value": holding.holding_value,
                "holding_ratio": holding.holding_ratio,
            },
        )

    # ==================== 行业配置 ====================

    def get_fund_sector_allocation(
        self, fund_code: str, report_date: date | None = None
    ) -> list[FundSectorAllocation]:
        """获取基金行业配置

        Args:
            fund_code: 基金代码
            report_date: 报告期

        Returns:
            行业配置列表
        """
        queryset = FundSectorAllocationModel._default_manager.filter(fund_code=fund_code)

        if report_date:
            queryset = queryset.filter(report_date=report_date)
        else:
            # 获取最新报告期
            latest_date = queryset.aggregate(Max("report_date"))["report_date__max"]
            if latest_date:
                queryset = queryset.filter(report_date=latest_date)

        queryset = queryset.order_by("-allocation_ratio")

        models = queryset.all()
        return [self._model_to_entity_sector_alloc(m) for m in models]

    def save_fund_sector_allocation(self, allocation: FundSectorAllocation) -> None:
        """保存或更新基金行业配置

        Args:
            allocation: 行业配置实体
        """
        FundSectorAllocationModel._default_manager.update_or_create(
            fund_code=allocation.fund_code,
            report_date=allocation.report_date,
            sector_name=allocation.sector_name,
            defaults={"allocation_ratio": allocation.allocation_ratio},
        )

    # ==================== 基金业绩 ====================

    def get_fund_performance(
        self, fund_code: str, start_date: date, end_date: date
    ) -> FundPerformance | None:
        """获取基金业绩指标

        Args:
            fund_code: 基金代码
            start_date: 起始日期
            end_date: 结束日期

        Returns:
            业绩指标或 None
        """
        try:
            model = FundPerformanceModel._default_manager.get(
                fund_code=fund_code, start_date=start_date, end_date=end_date
            )
            return self._model_to_entity_performance(model)
        except FundPerformanceModel.DoesNotExist:
            return None

    def get_nearest_fund_performance(
        self,
        fund_code: str,
        start_date: date,
        end_date: date,
        tolerance_days: int = 31,
    ) -> FundPerformance | None:
        """Return a nearby stored performance snapshot when exact dates are absent."""

        window_start = start_date - timedelta(days=tolerance_days)
        window_end = end_date + timedelta(days=tolerance_days)

        model = (
            FundPerformanceModel._default_manager.filter(
                fund_code=fund_code,
                start_date__gte=window_start,
                start_date__lte=start_date + timedelta(days=tolerance_days),
                end_date__gte=end_date - timedelta(days=tolerance_days),
                end_date__lte=window_end,
            )
            .order_by("-end_date", "start_date")
            .first()
        )
        if model is None:
            return None
        return self._model_to_entity_performance(model)

    def save_fund_performance(self, performance: FundPerformance) -> None:
        """保存或更新基金业绩

        Args:
            performance: 业绩实体
        """
        FundPerformanceModel._default_manager.update_or_create(
            fund_code=performance.fund_code,
            start_date=performance.start_date,
            end_date=performance.end_date,
            defaults={
                "total_return": performance.total_return,
                "annualized_return": performance.annualized_return,
                "volatility": performance.volatility,
                "sharpe_ratio": performance.sharpe_ratio,
                "max_drawdown": performance.max_drawdown,
                "beta": performance.beta,
                "alpha": performance.alpha,
            },
        )

    def ensure_fund_universe_seeded(self) -> int:
        """Seed fund master data when the local fund universe is empty."""

        if FundInfoModel._default_manager.filter(is_active=True).exists():
            return 0
        return self.sync_fund_info_from_tushare()

    def resolve_research_window(
        self,
        *,
        requested_end_date: date,
        lookback_days: int = 365,
    ) -> tuple[date, date]:
        """Anchor research windows to the latest locally available fund dataset."""

        latest_performance_end = FundPerformanceModel._default_manager.aggregate(
            latest=Max("end_date")
        )["latest"]
        latest_nav_date = FundNetValueModel._default_manager.aggregate(latest=Max("nav_date"))["latest"]
        latest_available = latest_performance_end or latest_nav_date or requested_end_date
        resolved_end_date = min(requested_end_date, latest_available)
        resolved_start_date = resolved_end_date - timedelta(days=lookback_days)
        return resolved_start_date, resolved_end_date

    def get_or_build_fund_performance(
        self,
        fund_code: str,
        start_date: date,
        end_date: date,
        *,
        allow_remote_sync: bool = False,
    ) -> FundPerformance | None:
        """Resolve one fund performance snapshot from stored data or local NAV history."""

        exact = self.get_fund_performance(fund_code, start_date, end_date)
        if exact is not None:
            return exact

        nearby = self.get_nearest_fund_performance(fund_code, start_date, end_date)
        if nearby is not None:
            return nearby

        built = self.build_and_store_fund_performance(
            fund_code=fund_code,
            start_date=start_date,
            end_date=end_date,
        )
        if built is not None:
            return built

        if not allow_remote_sync:
            return None

        synced_count = self.sync_fund_nav_from_tushare(
            fund_code=fund_code,
            start_date=start_date.strftime("%Y%m%d"),
            end_date=end_date.strftime("%Y%m%d"),
        )
        if synced_count <= 0:
            return None

        return self.build_and_store_fund_performance(
            fund_code=fund_code,
            start_date=start_date,
            end_date=end_date,
        )

    def build_and_store_fund_performance(
        self,
        *,
        fund_code: str,
        start_date: date,
        end_date: date,
    ) -> FundPerformance | None:
        """Calculate one performance snapshot from NAV data and persist it."""

        nav_series = self.get_fund_nav(fund_code, start_date, end_date)
        if len(nav_series) < 2:
            return None

        total_return = self._perf_calculator.calculate_total_return(nav_series)
        days = (nav_series[-1].nav_date - nav_series[0].nav_date).days
        annualized_return = self._perf_calculator.calculate_annualized_return(total_return, days)

        daily_returns = [
            nav.daily_return
            for nav in nav_series
            if nav.daily_return is not None
        ]
        if len(daily_returns) < 2:
            daily_returns = self._derive_daily_returns(nav_series)

        volatility = (
            self._perf_calculator.calculate_volatility(daily_returns)
            if len(daily_returns) >= 2
            else None
        )
        sharpe_ratio = (
            self._perf_calculator.calculate_sharpe_ratio(annualized_return, volatility)
            if volatility and volatility > 0
            else None
        )
        max_drawdown = self._perf_calculator.calculate_max_drawdown(nav_series)

        performance = FundPerformance(
            fund_code=fund_code,
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
        self.save_fund_performance(performance)
        return performance

    # ==================== 综合查询 ====================

    def get_funds_with_performance(
        self, start_date: date, end_date: date
    ) -> list[tuple[FundInfo, FundPerformance, list[FundSectorAllocation]]]:
        """获取基金及其业绩和行业配置

        Args:
            start_date: 业绩计算起始日期
            end_date: 业绩计算结束日期

        Returns:
            [(基金信息, 业绩, 行业配置)] 列表
        """
        result = []
        self.ensure_fund_universe_seeded()

        # 获取所有基金
        funds = self.get_all_funds()

        for fund in funds:
            # 获取业绩
            perf = self.get_or_build_fund_performance(
                fund.fund_code,
                start_date,
                end_date,
                allow_remote_sync=False,
            )

            if not perf:
                continue  # 没有业绩数据的基金跳过

            # 获取行业配置
            sector_alloc = self.get_fund_sector_allocation(fund.fund_code)

            result.append((fund, perf, sector_alloc))

        return result

    # ==================== 数据同步 ====================

    def sync_fund_info_from_tushare(self) -> int:
        """从 Tushare 同步基金信息

        Returns:
            同步的基金数量
        """
        count = 0
        seen_codes: set[str] = set()
        for market in ("O", "E"):
            df = self.tushare_adapter.fetch_fund_list(market=market)
            if df is None or df.empty:
                continue

            for _, row in df.iterrows():
                fund_code = self._normalize_fund_code(str(row.get("ts_code", "")))
                if not fund_code or fund_code in seen_codes:
                    continue

                fund_info = FundInfo(
                    fund_code=fund_code,
                    fund_name=self._clean_optional_text(row.get("name")) or fund_code,
                    fund_type=self._normalize_fund_type(str(row.get("fund_type", "")), market),
                    setup_date=self._coerce_date(row.get("setup_date")),
                    management_company=self._clean_optional_text(row.get("management")),
                    custodian=self._clean_optional_text(row.get("custodian")),
                    fund_scale=self._coerce_issue_amount(row.get("issue_amount")),
                )

                self.save_fund_info(fund_info)
                seen_codes.add(fund_code)
                count += 1

        return count

    def sync_fund_nav_from_tushare(self, fund_code: str, start_date: str, end_date: str) -> int:
        """从 Tushare 同步基金净值

        Args:
            fund_code: 基金代码
            start_date: 开始日期（'20240101'）
            end_date: 结束日期（'20241231'）

        Returns:
            同步的记录数
        """
        start = datetime.strptime(start_date, "%Y%m%d").date()
        end = datetime.strptime(end_date, "%Y%m%d").date()
        active_configs = self._provider_repo.get_active_by_type("tushare")
        if active_configs:
            try:
                use_case = SyncFundNavUseCase(
                    provider_repo=self._provider_repo,
                    provider_factory=self._provider_factory,
                    fact_repo=self._dc_fund_nav_repo,
                    raw_audit_repo=self._raw_audit_repo,
                )
                result = use_case.execute(
                    SyncFundNavRequest(
                        provider_id=active_configs[0].id,
                        fund_code=fund_code,
                        start=start,
                        end=end,
                    )
                )
                if result.stored_count > 0:
                    facts = self._dc_fund_nav_repo.get_series(fund_code, start=start, end=end)
                    for fact in facts:
                        self._mirror_dc_nav_fact(fact)
                    return result.stored_count
            except Exception:
                pass

        # Tushare 需要带 .OF 后缀
        ts_code = f"{fund_code}.OF"

        df = self.tushare_adapter.fetch_fund_daily(ts_code, start_date, end_date)

        if df is None or df.empty:
            return 0

        count = 0
        for _, row in df.iterrows():
            nav = FundNetValue(
                fund_code=fund_code,
                nav_date=row["trade_date"].date(),
                unit_nav=Decimal(str(row["unit_nav"])),
                accum_nav=Decimal(str(row["accum_nav"])),
            )

            self.save_fund_nav(nav)
            count += 1

        return count

    # ==================== 私有方法 ====================

    def _entity_nav_to_dc_fact(self, nav: FundNetValue):
        from apps.data_center.domain.entities import FundNavFact

        return FundNavFact(
            fund_code=nav.fund_code,
            nav_date=nav.nav_date,
            nav=float(nav.unit_nav),
            acc_nav=float(nav.accum_nav),
            daily_return=nav.daily_return,
            source="fund_legacy_repo",
        )

    def _dc_fact_to_entity_nav(self, fact) -> FundNetValue:
        accum_nav = fact.acc_nav if fact.acc_nav is not None else fact.nav
        return FundNetValue(
            fund_code=fact.fund_code,
            nav_date=fact.nav_date,
            unit_nav=Decimal(str(fact.nav)),
            accum_nav=Decimal(str(accum_nav)),
            daily_return=fact.daily_return,
        )

    def _mirror_dc_nav_fact(self, fact) -> None:
        accum_nav = fact.acc_nav if fact.acc_nav is not None else fact.nav
        FundNetValueModel._default_manager.update_or_create(
            fund_code=fact.fund_code,
            nav_date=fact.nav_date,
            defaults={
                "unit_nav": Decimal(str(fact.nav)),
                "accum_nav": Decimal(str(accum_nav)),
                "daily_return": fact.daily_return,
            },
        )

    def _model_to_entity_info(self, model: FundInfoModel) -> FundInfo:
        """ORM 模型转换为实体（基金信息）"""
        return FundInfo(
            fund_code=model.fund_code,
            fund_name=model.fund_name,
            fund_type=model.fund_type,
            investment_style=model.investment_style,
            setup_date=model.setup_date,
            management_company=model.management_company,
            custodian=model.custodian,
            fund_scale=model.fund_scale,
        )

    def _model_to_entity_nav(self, model: FundNetValueModel) -> FundNetValue:
        """ORM 模型转换为实体（净值）"""
        return FundNetValue(
            fund_code=model.fund_code,
            nav_date=model.nav_date,
            unit_nav=model.unit_nav,
            accum_nav=model.accum_nav,
            daily_return=model.daily_return,
        )

    def _model_to_entity_holding(self, model: FundHoldingModel) -> FundHolding:
        """ORM 模型转换为实体（持仓）"""
        return FundHolding(
            fund_code=model.fund_code,
            report_date=model.report_date,
            stock_code=model.stock_code,
            stock_name=model.stock_name,
            holding_amount=model.holding_amount,
            holding_value=model.holding_value,
            holding_ratio=model.holding_ratio,
        )

    def _model_to_entity_sector_alloc(
        self, model: FundSectorAllocationModel
    ) -> FundSectorAllocation:
        """ORM 模型转换为实体（行业配置）"""
        return FundSectorAllocation(
            fund_code=model.fund_code,
            report_date=model.report_date,
            sector_name=model.sector_name,
            allocation_ratio=model.allocation_ratio,
        )

    def _model_to_entity_performance(self, model: FundPerformanceModel) -> FundPerformance:
        """ORM 模型转换为实体（业绩）"""
        return FundPerformance(
            fund_code=model.fund_code,
            start_date=model.start_date,
            end_date=model.end_date,
            total_return=model.total_return,
            annualized_return=model.annualized_return,
            volatility=model.volatility,
            sharpe_ratio=model.sharpe_ratio,
            max_drawdown=model.max_drawdown,
            beta=model.beta,
            alpha=model.alpha,
        )

    def _derive_daily_returns(self, nav_series: list[FundNetValue]) -> list[float]:
        """Derive daily returns from NAV series when provider payload omitted them."""

        returns: list[float] = []
        for previous, current in zip(nav_series, nav_series[1:]):
            prev_nav = float(previous.unit_nav)
            curr_nav = float(current.unit_nav)
            if prev_nav <= 0:
                continue
            returns.append((curr_nav / prev_nav - 1) * 100)
        return returns

    def _normalize_fund_code(self, ts_code: str) -> str:
        """Normalize Tushare fund codes to local base codes."""

        return ts_code.split(".")[0].strip().upper()

    def _normalize_fund_type(self, raw_type: str, market: str) -> str:
        """Map external fund type labels into the local canonical set."""

        normalized = raw_type.strip()
        if "股票" in normalized:
            return "股票型"
        if "债" in normalized:
            return "债券型"
        if "货币" in normalized:
            return "货币型"
        if "QDII" in normalized.upper():
            return "QDII"
        if "商品" in normalized:
            return "商品型"
        if "ETF" in normalized.upper() or "LOF" in normalized.upper() or "指数" in normalized:
            return "指数型"
        if "混合" in normalized:
            return "混合型"
        if normalized in {"开放式", "封闭式"}:
            return "混合型" if market == "O" else "指数型"
        return "混合型"

    def _coerce_date(self, value) -> date | None:
        """Convert provider date values to ``date`` when possible."""

        if value is None:
            return None
        if isinstance(value, datetime):
            return value.date()
        if isinstance(value, date):
            return value
        return None

    def _coerce_issue_amount(self, value) -> Decimal | None:
        """Convert issue amount in 亿份 to yuan-like storage used by the fund module."""

        if self._is_empty_like(value):
            return None
        try:
            return Decimal(str(value)) * Decimal("100000000")
        except ArithmeticError:
            return None

    def _clean_optional_text(self, value) -> str | None:
        """Normalize provider text fields and drop NaN-like placeholders."""

        if self._is_empty_like(value):
            return None
        return str(value).strip() or None

    def _is_empty_like(self, value) -> bool:
        """Return True when provider data is empty, null, or NaN-like."""

        if value is None:
            return True
        if isinstance(value, str):
            return value.strip() == "" or value.strip().lower() == "nan"
        if isinstance(value, float):
            return math.isnan(value) or value == 0.0
        return value == 0
