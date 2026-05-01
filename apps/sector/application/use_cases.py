"""
板块分析模块 - Application 层用例

遵循项目架构约束：
- 编排 Domain 层服务
- 通过依赖注入使用 Infrastructure 层
- 不包含业务逻辑
"""

import logging
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal
from typing import Dict, List, Optional

from core.integration.market_index_returns import fetch_index_daily_returns

from .repository_provider import DjangoSectorRepository
from ..domain.entities import SectorIndex, SectorInfo, SectorRelativeStrength, SectorScore
from ..domain.services import SectorRotationAnalyzer

logger = logging.getLogger(__name__)


@dataclass
class AnalyzeSectorRotationRequest:
    """分析板块轮动请求

    Attributes:
        regime: Regime 名称（Recovery/Overheat/Stagflation/Deflation）
        lookback_days: 回看天数（用于计算动量）
        momentum_weight: 动量评分权重
        rs_weight: 相对强弱评分权重
        regime_weight: Regime 适配度权重
        level: 板块级别（SW1/SW2/SW3）
        top_n: 返回前 N 个板块
    """
    regime: str | None = None  # 如果为 None，自动获取最新 Regime
    lookback_days: int = 20
    momentum_weight: float = 0.3
    rs_weight: float = 0.4
    regime_weight: float = 0.3
    level: str = 'SW1'
    top_n: int = 10


@dataclass
class SectorRotationResult:
    """板块轮动分析结果

    Attributes:
        success: 是否成功
        regime: Regime 名称
        analysis_date: 分析日期
        top_sectors: 推荐板块列表（按评分降序）
        error: 错误信息（如果失败）
    """
    success: bool
    regime: str
    analysis_date: date
    top_sectors: list[SectorScore]
    error: str | None = None
    status: str = "available"
    data_source: str = "live"
    warning_message: str | None = None
    warning_detail: str | None = None


class AnalyzeSectorRotationUseCase:
    """分析板块轮动用例

    职责：
    1. 获取当前 Regime
    2. 加载对应的板块权重配置
    3. 计算板块动量和相对强弱
    4. 生成板块推荐排名
    """

    def __init__(
        self,
        sector_repo: DjangoSectorRepository,
        regime_repo=None,
        market_adapter=None,
    ):
        """初始化用例

        Args:
            sector_repo: 板块数据仓储
            regime_repo: Regime 数据仓储（可选，用于自动获取当前 Regime）
            market_adapter: 市场数据适配器（可选，用于获取大盘收益率）
        """
        self.sector_repo = sector_repo
        self.regime_repo = regime_repo
        self.market_adapter = market_adapter
        self.analyzer = SectorRotationAnalyzer()

    def execute(
        self,
        request: AnalyzeSectorRotationRequest
    ) -> SectorRotationResult:
        """执行板块轮动分析

        Args:
            request: 分析请求

        Returns:
            分析结果
        """
        try:
            market_returns_fallback = False
            market_returns_cache: dict[int, list[float]] = {}
            # 1. 获取 Regime
            if request.regime:
                regime = request.regime
            else:
                # 自动获取最新 Regime（统一 V2 链路）
                from apps.regime.application.current_regime import resolve_current_regime
                regime = resolve_current_regime(as_of_date=date.today()).dominant_regime

            # 2. 加载板块权重配置
            regime_weights = self.sector_repo.get_sector_weights_by_regime(regime)
            if not regime_weights:
                return SectorRotationResult(
                    success=False,
                    regime=regime,
                    analysis_date=date.today(),
                    top_sectors=[],
                    error=f"未找到 Regime '{regime}' 的板块权重配置，请在 Django Admin 中配置",
                    status="unavailable",
                    data_source="fallback",
                    warning_message="sector_weights_unavailable",
                    warning_detail="当前 Regime 的板块权重配置缺失，需先在系统配置中补齐。",
                )

            # 3. 获取所有板块信息
            all_sectors = self.sector_repo.get_all_sectors(level=request.level)
            if not all_sectors:
                return SectorRotationResult(
                    success=False,
                    regime=regime,
                    analysis_date=date.today(),
                    top_sectors=[],
                    error=f"未找到级别为 {request.level} 的板块数据",
                    status="unavailable",
                    data_source="fallback",
                    warning_message="sector_data_unavailable",
                    warning_detail=f"{request.level} 板块基础信息尚未初始化，系统将尝试自动同步。",
                )

            # 4. 计算每个板块的动量和相对强弱
            sectors_data = []
            end_date = date.today()
            start_date = end_date - timedelta(days=request.lookback_days * 2)  # 多取一些数据以确保足够

            for sector_info in all_sectors:
                # 获取板块指数数据
                indices = self.sector_repo.get_sector_index_range(
                    sector_code=sector_info.sector_code,
                    start_date=start_date,
                    end_date=end_date
                )

                if not indices:
                    continue

                # 获取最新指数
                latest_index = indices[-1]

                # 计算收益率序列
                returns = [idx.change_pct / 100 for idx in indices]

                # 计算动量
                momentum = self.analyzer.calculate_momentum(
                    returns,
                    lookback_days=min(request.lookback_days, len(returns))
                )

                # 获取大盘指数收益率（沪深300）
                expected_length = len(returns)
                market_returns = market_returns_cache.get(expected_length)
                if market_returns is None:
                    market_returns = self._get_market_returns(
                        start_date,
                        end_date,
                        expected_length,
                    )
                    if market_returns is None:
                        market_returns = [0.0] * expected_length
                        market_returns_fallback = True
                    market_returns_cache[expected_length] = market_returns

                # 计算相对强弱（简化版）
                relative_strength = momentum - sum(market_returns) / len(market_returns) * 100

                # 创建相对强弱实体
                sector_rs = SectorRelativeStrength(
                    sector_code=sector_info.sector_code,
                    trade_date=latest_index.trade_date,
                    relative_strength=relative_strength,
                    momentum=momentum,
                    beta=None
                )

                sectors_data.append((sector_info, latest_index, sector_rs))

            if not sectors_data:
                return SectorRotationResult(
                    success=False,
                    regime=regime,
                    analysis_date=date.today(),
                    top_sectors=[],
                    error="没有足够的板块指数数据进行分析",
                    status="unavailable",
                    data_source="fallback",
                    warning_message="sector_indices_insufficient",
                    warning_detail="板块指数历史数据不足，无法计算动量与相对强弱。",
                )

            # 5. 使用 Domain 层服务进行评分排名
            sector_scores = self.analyzer.rank_sectors_by_regime(
                sectors_data=sectors_data,
                regime_weights=regime_weights,
                momentum_weight=request.momentum_weight,
                rs_weight=request.rs_weight,
                regime_weight=request.regime_weight
            )

            # 6. 返回前 N 个板块
            top_sectors = sector_scores[:request.top_n]

            return SectorRotationResult(
                success=True,
                regime=regime,
                analysis_date=date.today(),
                top_sectors=top_sectors,
                status="degraded" if market_returns_fallback else "available",
                data_source="fallback" if market_returns_fallback else "live",
                warning_message=(
                    "market_returns_fallback"
                    if market_returns_fallback
                    else None
                ),
                warning_detail=(
                    "沪深300 基准收益率暂不可用，本次相对强弱采用无基准近似值；建议补齐指数行情缓存。"
                    if market_returns_fallback
                    else None
                ),
            )

        except Exception as e:
            return SectorRotationResult(
                success=False,
                regime=regime if request.regime else '',
                analysis_date=date.today(),
                top_sectors=[],
                error=str(e),
                status="degraded",
                data_source="fallback",
                warning_message="sector_rotation_failed",
                warning_detail="板块轮动分析执行异常，请检查板块指数与基准行情数据。",
            )

    def _get_market_returns(
        self, start_date: date, end_date: date, expected_length: int
    ) -> list | None:
        """获取大盘指数收益率（沪深300）

        Args:
            start_date: 起始日期
            end_date: 结束日期
            expected_length: 期望的收益率序列长度

        Returns:
            收益率列表
        """
        if self.market_adapter is None:
            try:
                self.market_adapter = fetch_index_daily_returns
            except Exception:
                logger.warning("无法初始化市场数据适配器，大盘收益率 unavailable")
                return None

        try:
            if hasattr(self.market_adapter, "get_index_daily_returns"):
                returns_dict = self.market_adapter.get_index_daily_returns(
                    index_code='000300.SH',
                    start_date=start_date,
                    end_date=end_date,
                )
            elif callable(self.market_adapter):
                returns_dict = self.market_adapter(
                    index_code='000300.SH',
                    start_date=start_date,
                    end_date=end_date,
                )
            else:
                logger.warning("市场数据适配器不支持 index returns，大盘收益率 unavailable")
                return None
            if not returns_dict:
                logger.warning("沪深300 收益率数据为空，大盘收益率 unavailable")
                return None

            # 按日期排序并提取收益率
            sorted_returns = [v for _, v in sorted(returns_dict.items())]

            # 对齐到 expected_length
            if len(sorted_returns) >= expected_length:
                return sorted_returns[-expected_length:]
            if len(sorted_returns) + 1 == expected_length:
                return [0.0] + sorted_returns

            logger.warning(
                "沪深300 收益率数据不足: expected=%s actual=%s",
                expected_length,
                len(sorted_returns),
            )
            return None

        except Exception as e:
            logger.warning(f"获取大盘收益率失败: {e}，大盘收益率 unavailable")
            return None


@dataclass
class UpdateSectorDataRequest:
    """更新板块数据请求

    Attributes:
        level: 板块级别（SW1/SW2/SW3）
        start_date: 开始日期
        end_date: 结束日期
        force_update: 是否强制更新
    """
    level: str = 'SW1'
    start_date: str | None = None
    end_date: str | None = None
    force_update: bool = False


@dataclass
class UpdateSectorDataResult:
    """更新板块数据结果

    Attributes:
        success: 是否成功
        updated_count: 更新的记录数
        error: 错误信息
    """
    success: bool
    updated_count: int
    error: str | None = None


class UpdateSectorDataUseCase:
    """更新板块数据用例

    职责：
    1. 从数据源获取板块分类
    2. 从数据源获取板块指数数据
    3. 保存到数据库
    """

    def __init__(
        self,
        sector_repo: DjangoSectorRepository,
        adapter=None
    ):
        """初始化用例

        Args:
            sector_repo: 板块数据仓储
            adapter: 数据适配器（Tushare 或 AKShare）
        """
        self.sector_repo = sector_repo
        self.adapter = adapter

    def execute(
        self,
        request: UpdateSectorDataRequest
    ) -> UpdateSectorDataResult:
        """执行板块数据更新

        Args:
            request: 更新请求

        Returns:
            更新结果
        """
        try:
            if self.adapter is None:
                return UpdateSectorDataResult(
                    success=False,
                    updated_count=0,
                    error="未提供数据适配器"
                )

            # 1. 获取板块分类
            classify_df = self.adapter.fetch_sw_industry_classify(level=request.level)

            if classify_df.empty:
                return UpdateSectorDataResult(
                    success=False,
                    updated_count=0,
                    error=f"获取 {request.level} 板块分类失败"
                )

            # 2. 保存板块分类
            saved_count = 0
            for _, row in classify_df.iterrows():
                sector_info = SectorInfo(
                    sector_code=row['sector_code'],
                    sector_name=row['sector_name'],
                    level=row['level'],
                    parent_code=row.get('parent_code')
                )
                if self.sector_repo.save_sector_info(sector_info):
                    saved_count += 1

            # 3. 获取板块指数数据
            # 如果未指定日期范围，默认获取最近一年
            if not request.start_date:
                end_date = date.today()
                start_date = end_date - timedelta(days=365)
            else:
                start_date = date.fromisoformat(request.start_date)
                end_date = date.fromisoformat(request.end_date) if request.end_date else date.today()

            start_str = start_date.strftime('%Y%m%d')
            end_str = end_date.strftime('%Y%m%d')

            # 批量获取板块指数数据
            sector_codes = classify_df['sector_code'].tolist()
            indices_df = self.adapter.fetch_all_sector_index_daily(
                sector_codes=sector_codes,
                start_date=start_str,
                end_date=end_str
            )

            # 4. 保存板块指数数据
            updated_count = self.sector_repo.batch_save_sector_indices(indices_df)

            return UpdateSectorDataResult(
                success=True,
                updated_count=updated_count + saved_count
            )

        except Exception as e:
            return UpdateSectorDataResult(
                success=False,
                updated_count=0,
                error=str(e)
            )
