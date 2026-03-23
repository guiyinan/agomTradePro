"""
估值修复跟踪 Application 层用例

遵循四层架构规范：
- Application 层负责用例编排
- 通过依赖注入使用 Infrastructure 层
- 调用 Domain 层的业务逻辑
"""

import logging
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Dict, List, Optional

from apps.equity.application.config import get_valuation_repair_config
from apps.equity.domain.entities_valuation_repair import (
    PercentilePoint,
    ValuationRepairPhase,
    ValuationRepairStatus,
)
from apps.equity.domain.services_valuation_repair import (
    InsufficientHistoryError,
    InvalidValuationDataError,
    analyze_repair_status,
    build_percentile_series,
)

logger = logging.getLogger(__name__)


# ============== 请求/响应 DTO ==============

@dataclass
class GetValuationRepairStatusRequest:
    """获取估值修复状态请求"""
    stock_code: str
    lookback_days: int = 756


@dataclass
class GetValuationRepairStatusResponse:
    """获取估值修复状态响应"""
    success: bool
    stock_code: str
    data: dict | None = None
    error: str | None = None


@dataclass
class GetValuationPercentileHistoryRequest:
    """获取百分位历史请求"""
    stock_code: str
    lookback_days: int = 252


@dataclass
class GetValuationPercentileHistoryResponse:
    """获取百分位历史响应"""
    success: bool
    stock_code: str
    data: list[dict]
    error: str | None = None


@dataclass
class ScanValuationRepairsRequest:
    """扫描估值修复请求"""
    universe: str = "all_active"
    lookback_days: int = 756
    limit: int | None = None


@dataclass
class ScanValuationRepairsResponse:
    """扫描估值修复响应"""
    success: bool
    universe: str
    as_of_date: date
    scanned_count: int
    saved_count: int
    failed_count: int
    phase_counts: dict[str, int]
    error: str | None = None


@dataclass
class ListValuationRepairsRequest:
    """列出估值修复请求"""
    universe: str = "all_active"
    phase: str | None = None
    limit: int = 50


@dataclass
class ListValuationRepairsResponse:
    """列出估值修复响应"""
    success: bool
    universe: str
    count: int
    data: list[dict]
    error: str | None = None


# ============== 用例实现 ==============

class GetValuationRepairStatusUseCase:
    """获取估值修复状态用例（实时计算，不依赖快照表）"""

    def __init__(self, stock_repository, valuation_repair_repository=None, valuation_quality_repository=None):
        """
        初始化用例

        Args:
            stock_repository: 股票数据仓储
            valuation_repair_repository: 估值修复仓储（可选，用于缓存）
        """
        self.stock_repo = stock_repository
        self.repair_repo = valuation_repair_repository
        self.quality_repo = valuation_quality_repository

    def execute(self, request: GetValuationRepairStatusRequest) -> GetValuationRepairStatusResponse:
        """
        执行获取估值修复状态

        流程：
        1. 获取股票信息
        2. 获取估值历史数据
        3. 调用 Domain 层 analyze_repair_status
        4. 返回结果
        """
        try:
            # 1. 获取股票信息
            stock_info = self.stock_repo.get_stock_info(request.stock_code)
            if not stock_info:
                raise ValueError(f"未找到股票 {request.stock_code}")

            # 2. 获取估值历史数据
            # 计算足够长的日期范围以获取所需的交易日样本
            end_date = date.today()
            start_date = end_date - timedelta(days=request.lookback_days * 2)  # 粗略估计

            valuation_history = self.stock_repo.get_valuation_history(
                request.stock_code,
                start_date,
                end_date
            )

            if not valuation_history:
                raise ValueError(f"未找到股票 {request.stock_code} 的估值数据")

            # 3. 转换为 Domain 层期望的格式
            history_dicts = [
                {
                    "trade_date": v.trade_date,
                    "pe": float(v.pe) if v.pe else None,
                    "pb": float(v.pb) if v.pb else None,
                }
                for v in valuation_history
            ]

            # 4. 调用 Domain 层分析
            status = analyze_repair_status(
                stock_code=request.stock_code,
                stock_name=stock_info.name,
                history=history_dicts,
                lookback_days=request.lookback_days,
                config=get_valuation_repair_config(),
            )

            # 5. 转换为字典返回
            return GetValuationRepairStatusResponse(
                success=True,
                stock_code=request.stock_code,
                data=self._status_to_dict(status)
            )

        except InsufficientHistoryError as e:
            return GetValuationRepairStatusResponse(
                success=False,
                stock_code=request.stock_code,
                error=f"历史数据不足: {str(e)}"
            )
        except InvalidValuationDataError as e:
            return GetValuationRepairStatusResponse(
                success=False,
                stock_code=request.stock_code,
                error=f"估值数据无效: {str(e)}"
            )
        except Exception as e:
            logger.exception(f"获取估值修复状态失败: {request.stock_code}")
            return GetValuationRepairStatusResponse(
                success=False,
                stock_code=request.stock_code,
                error=str(e)
            )

    def _status_to_dict(self, status: ValuationRepairStatus) -> dict:
        """将 ValuationRepairStatus 转换为字典"""
        return {
            "stock_code": status.stock_code,
            "stock_name": status.stock_name,
            "as_of_date": status.as_of_date.isoformat(),
            "phase": status.phase,
            "signal": status.signal,
            "current_pe": status.current_pe,
            "current_pb": status.current_pb,
            "pe_percentile": status.pe_percentile,
            "pb_percentile": status.pb_percentile,
            "composite_percentile": status.composite_percentile,
            "composite_method": status.composite_method,
            "repair_start_date": status.repair_start_date.isoformat() if status.repair_start_date else None,
            "repair_start_percentile": status.repair_start_percentile,
            "lowest_percentile": status.lowest_percentile,
            "lowest_percentile_date": status.lowest_percentile_date.isoformat(),
            "repair_progress": status.repair_progress,
            "target_percentile": status.target_percentile,
            "repair_speed_per_30d": status.repair_speed_per_30d,
            "estimated_days_to_target": status.estimated_days_to_target,
            "is_stalled": status.is_stalled,
            "stall_start_date": status.stall_start_date.isoformat() if status.stall_start_date else None,
            "stall_duration_trading_days": status.stall_duration_trading_days,
            "repair_duration_trading_days": status.repair_duration_trading_days,
            "lookback_trading_days": status.lookback_trading_days,
            "confidence": status.confidence,
            "description": status.description,
            "data_quality_flag": self._get_latest_quality_flag(status.as_of_date),
            "data_source_provider": "local_db",
            "data_as_of_date": status.as_of_date.isoformat(),
        }

    def _get_latest_quality_flag(self, as_of_date: date) -> str | None:
        if not self.quality_repo:
            return None
        snapshot = self.quality_repo.get_snapshot(as_of_date)
        if snapshot:
            return "ok" if snapshot.is_gate_passed else "gate_failed"
        return None


class GetValuationPercentileHistoryUseCase:
    """获取百分位历史序列用例（实时计算，不依赖快照表）"""

    def __init__(self, stock_repository):
        """
        初始化用例

        Args:
            stock_repository: 股票数据仓储
        """
        self.stock_repo = stock_repository

    def execute(self, request: GetValuationPercentileHistoryRequest) -> GetValuationPercentileHistoryResponse:
        """
        执行获取百分位历史

        流程：
        1. 获取估值历史数据
        2. 调用 Domain 层 build_percentile_series
        3. 转换为字典列表返回
        """
        try:
            # 1. 获取估值历史数据
            end_date = date.today()
            start_date = end_date - timedelta(days=request.lookback_days * 2)

            valuation_history = self.stock_repo.get_valuation_history(
                request.stock_code,
                start_date,
                end_date
            )

            if not valuation_history:
                raise ValueError(f"未找到股票 {request.stock_code} 的估值数据")

            # 2. 转换为 Domain 层期望的格式
            history_dicts = [
                {
                    "trade_date": v.trade_date,
                    "pe": float(v.pe) if v.pe else None,
                    "pb": float(v.pb) if v.pb else None,
                }
                for v in valuation_history
            ]

            # 3. 调用 Domain 层构建百分位序列
            series = build_percentile_series(
                history_dicts,
                lookback_days=request.lookback_days,
                config=get_valuation_repair_config(),
            )

            # 4. 转换为字典列表
            data = [
                {
                    "trade_date": point.trade_date.isoformat(),
                    "pe_percentile": point.pe_percentile,
                    "pb_percentile": point.pb_percentile,
                    "composite_percentile": point.composite_percentile,
                    "composite_method": point.composite_method,
                }
                for point in series
            ]

            return GetValuationPercentileHistoryResponse(
                success=True,
                stock_code=request.stock_code,
                data=data
            )

        except InsufficientHistoryError as e:
            return GetValuationPercentileHistoryResponse(
                success=False,
                stock_code=request.stock_code,
                data=[],
                error=f"历史数据不足: {str(e)}"
            )
        except InvalidValuationDataError as e:
            return GetValuationPercentileHistoryResponse(
                success=False,
                stock_code=request.stock_code,
                data=[],
                error=f"估值数据无效: {str(e)}"
            )
        except Exception as e:
            logger.exception(f"获取百分位历史失败: {request.stock_code}")
            return GetValuationPercentileHistoryResponse(
                success=False,
                stock_code=request.stock_code,
                data=[],
                error=str(e)
            )


class ScanValuationRepairsUseCase:
    """批量扫描估值修复并保存快照用例"""

    # Active phases: 需要保存到快照表的阶段
    ACTIVE_PHASES = {
        ValuationRepairPhase.UNDERVALUED.value,
        ValuationRepairPhase.REPAIR_STARTED.value,
        ValuationRepairPhase.REPAIRING.value,
        ValuationRepairPhase.NEAR_TARGET.value,
        ValuationRepairPhase.STALLED.value,
    }

    # Inactive phases: 不需要追踪的阶段
    INACTIVE_PHASES = {
        ValuationRepairPhase.NO_REPAIR_NEEDED.value,
        ValuationRepairPhase.COMPLETED.value,
        ValuationRepairPhase.OVERSHOOTING.value,
    }

    def __init__(
        self,
        stock_repository,
        valuation_repair_repository,
        stock_pool_adapter=None,
        valuation_quality_repository=None
    ):
        """
        初始化用例

        Args:
            stock_repository: 股票数据仓储
            valuation_repair_repository: 估值修复仓储
            stock_pool_adapter: 股票池适配器（可选，用于 current_pool universe）
        """
        self.stock_repo = stock_repository
        self.repair_repo = valuation_repair_repository
        self.pool_adapter = stock_pool_adapter
        self.quality_repo = valuation_quality_repository

    def execute(self, request: ScanValuationRepairsRequest) -> ScanValuationRepairsResponse:
        """
        执行批量扫描

        流程：
        1. 解析 universe 获取股票列表
        2. 对每只股票实时计算 repair status
        3. 对 active phases 调用 upsert_snapshot
        4. 对 inactive phases 调用 deactivate_snapshot
        5. 返回统计信息
        """
        try:
            if self.quality_repo:
                snapshot = self.quality_repo.get_latest_gate_passed_snapshot()
                if not snapshot:
                    raise ValueError("valuation data quality gate not passed")

            # 1. 解析 universe
            stock_codes = self._resolve_universe(request.universe, request.limit)

            if not stock_codes:
                raise ValueError(f"未找到股票池: {request.universe}")

            # 2. 批量扫描
            as_of_date = snapshot.as_of_date if self.quality_repo else date.today()
            scanned_count = 0
            saved_count = 0
            failed_count = 0
            phase_counts = {}

            for stock_code in stock_codes:
                scanned_count += 1

                try:
                    # 实时计算 repair status
                    status = self._calculate_status(stock_code, request.lookback_days, as_of_date)

                    # 统计阶段
                    phase_counts[status.phase] = phase_counts.get(status.phase, 0) + 1

                    # 根据阶段决定操作
                    if status.phase in self.ACTIVE_PHASES:
                        # Active: 保存或更新快照
                        self.repair_repo.upsert_snapshot(
                            status=status,
                            source_universe=request.universe
                        )
                        saved_count += 1

                    elif status.phase in self.INACTIVE_PHASES:
                        # Inactive: 停用快照
                        self.repair_repo.deactivate_snapshot(
                            stock_code=stock_code,
                            source_universe=request.universe
                        )

                except Exception as e:
                    failed_count += 1
                    logger.warning(f"扫描股票 {stock_code} 失败: {e}")
                    continue

            return ScanValuationRepairsResponse(
                success=True,
                universe=request.universe,
                as_of_date=as_of_date,
                scanned_count=scanned_count,
                saved_count=saved_count,
                failed_count=failed_count,
                phase_counts=phase_counts
            )

        except Exception as e:
            logger.exception(f"批量扫描失败: {request.universe}")
            return ScanValuationRepairsResponse(
                success=False,
                universe=request.universe,
                as_of_date=date.today(),
                scanned_count=0,
                saved_count=0,
                failed_count=0,
                phase_counts={},
                error=str(e)
            )

    def _resolve_universe(self, universe: str, limit: int | None) -> list[str]:
        """
        解析 universe 获取股票列表

        Args:
            universe: 股票池标识
            limit: 数量限制

        Returns:
            股票代码列表
        """
        if universe == "all_active":
            # 获取所有活跃股票
            if hasattr(self.stock_repo, "list_active_stock_codes"):
                return self.stock_repo.list_active_stock_codes(limit=limit)
            else:
                # 降级方案
                stocks = self.stock_repo.get_all_stocks_with_fundamentals()
                codes = [s.stock_code for s, f, v in stocks]
                return codes[:limit] if limit else codes

        elif universe == "current_pool":
            # 获取当前股票池
            if self.pool_adapter:
                return self.pool_adapter.get_current_pool(limit=limit)
            else:
                raise ValueError("未配置 stock_pool_adapter")

        else:
            # 假设是预定义的股票池名称
            raise ValueError(f"不支持的 universe: {universe}")

    def _calculate_status(self, stock_code: str, lookback_days: int, as_of_date: date | None = None) -> ValuationRepairStatus:
        """
        计算单只股票的估值修复状态

        Args:
            stock_code: 股票代码
            lookback_days: 回看窗口

        Returns:
            ValuationRepairStatus
        """
        # 获取股票信息
        stock_info = self.stock_repo.get_stock_info(stock_code)
        if not stock_info:
            raise ValueError(f"未找到股票 {stock_code}")

        # 获取估值历史
        end_date = as_of_date or date.today()
        start_date = end_date - timedelta(days=lookback_days * 2)

        valuation_history = self.stock_repo.get_valuation_history(
            stock_code,
            start_date,
            end_date
        )

        if not valuation_history:
            raise ValueError(f"未找到股票 {stock_code} 的估值数据")

        # 转换格式
        history_dicts = [
            {
                "trade_date": v.trade_date,
                "pe": float(v.pe) if v.pe else None,
                "pb": float(v.pb) if v.pb else None,
            }
            for v in valuation_history
        ]

        # 调用 Domain 层分析
        return analyze_repair_status(
            stock_code=stock_code,
            stock_name=stock_info.name,
            history=history_dicts,
            lookback_days=lookback_days,
            config=get_valuation_repair_config(),
        )


class ListValuationRepairsUseCase:
    """列出估值修复快照用例（不触发实时重算）"""

    def __init__(self, valuation_repair_repository):
        """
        初始化用例

        Args:
            valuation_repair_repository: 估值修复仓储
        """
        self.repair_repo = valuation_repair_repository

    def execute(self, request: ListValuationRepairsRequest) -> ListValuationRepairsResponse:
        """
        执行列出估值修复

        直接读取快照表，不触发实时重算。

        流程：
        1. 调用 valuation_repair_repository.list_active_snapshots
        2. 转换为字典列表返回
        """
        try:
            snapshots = self.repair_repo.list_active_snapshots(
                source_universe=request.universe,
                phase=request.phase,
                limit=request.limit
            )

            data = [self._snapshot_to_dict(s) for s in snapshots]

            return ListValuationRepairsResponse(
                success=True,
                universe=request.universe,
                count=len(data),
                data=data
            )

        except Exception as e:
            logger.exception(f"列出估值修复失败: {request.universe}")
            return ListValuationRepairsResponse(
                success=False,
                universe=request.universe,
                count=0,
                data=[],
                error=str(e)
            )

    def _snapshot_to_dict(self, snapshot) -> dict:
        """将快照对象转换为字典"""
        # 支持两种类型：ValuationRepairStatus 或 ORM Model
        if isinstance(snapshot, ValuationRepairStatus):
            return {
                "stock_code": snapshot.stock_code,
                "stock_name": snapshot.stock_name,
                "as_of_date": snapshot.as_of_date.isoformat(),
                "phase": snapshot.phase,
                "signal": snapshot.signal,
                "composite_percentile": snapshot.composite_percentile,
                "repair_progress": snapshot.repair_progress,
                "repair_speed_per_30d": snapshot.repair_speed_per_30d,
                "repair_duration_trading_days": snapshot.repair_duration_trading_days,
                "estimated_days_to_target": snapshot.estimated_days_to_target,
                "is_stalled": snapshot.is_stalled,
                "confidence": snapshot.confidence,
            }
        else:
            # ORM Model
            return {
                "stock_code": snapshot.stock_code,
                "stock_name": snapshot.stock_name,
                "as_of_date": snapshot.as_of_date.isoformat(),
                "phase": snapshot.current_phase,
                "signal": snapshot.signal,
                "composite_percentile": snapshot.composite_percentile,
                "repair_progress": snapshot.repair_progress,
                "repair_speed_per_30d": snapshot.repair_speed_per_30d,
                "repair_duration_trading_days": snapshot.repair_duration_trading_days,
                "estimated_days_to_target": snapshot.estimated_days_to_target,
                "is_stalled": snapshot.is_stalled,
                "confidence": snapshot.confidence,
            }
