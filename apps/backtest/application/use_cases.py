"""
Use Cases for Backtest Module.

Application layer orchestrating the workflow of backtesting operations.
"""

import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, time
from typing import Any, Protocol

from apps.backtest.application.audit_gateway import (
    generate_attribution_report_for_backtest,
)

from ..domain.entities import BacktestConfig
from ..domain.services import BacktestEngine
from .repository_provider import DjangoBacktestRepository

logger = logging.getLogger(__name__)


class PITDataView(Protocol):
    """Structural boundary implemented by the data-center PIT view."""

    def query(
        self, dataset: str, as_of_time: datetime, knowledge_scope: str, filters: dict[str, Any]
    ) -> list[Any]: ...


@dataclass
class RunBacktestRequest:
    """运行回测的请求 DTO"""

    name: str
    start_date: date
    end_date: date
    initial_capital: float
    rebalance_frequency: str = "monthly"
    use_pit_data: bool = False
    transaction_cost_bps: float = 10.0
    trust_status: str = "exploratory"
    data_manifest_id: str | None = None
    pit_coverage: dict[str, float] = field(default_factory=dict)
    config_hash: str = ""
    code_commit: str = ""
    engine_version: str = "backtest-v1"
    research_trial_id: str | None = None
    decision_snapshot_id: str | None = None


@dataclass
class RunBacktestResponse:
    """运行回测的响应 DTO"""

    backtest_id: int | None
    status: str
    result: dict[str, Any] | None
    errors: list[str]
    warnings: list[str]
    audit_status: str = "pending"  # 'pending', 'success', 'failed', 'skipped'
    audit_error: str | None = None
    audit_report_id: int | None = None


class RunBacktestUseCase:
    """
    运行回测的用例

    职责：
    1. 创建回测配置
    2. 获取必要的数据（Regime、资产价格）
    3. 运行回测引擎
    4. 保存结果
    """

    def __init__(
        self,
        repository: DjangoBacktestRepository,
        get_regime_func: Callable[[date], dict | None],
        get_asset_price_func: Callable[[str, date], float | None],
        pit_data_view: PITDataView | None = None,
        get_decision_snapshot_func: Callable[[str], Any] | None = None,
    ):
        """
        Args:
            repository: 回测仓储
            get_regime_func: 获取 Regime 的函数 (date) -> Dict
            get_asset_price_func: 获取资产价格的函数 (asset_class, date) -> float
        """
        self.repository = repository
        self.get_regime = get_regime_func
        self.get_price = get_asset_price_func
        self.pit_data_view = pit_data_view
        self.get_decision_snapshot = get_decision_snapshot_func

    def execute(self, request: RunBacktestRequest) -> RunBacktestResponse:
        """
        执行回测

        Args:
            request: 回测请求

        Returns:
            RunBacktestResponse: 回测结果
        """
        errors = []
        warnings = []
        backtest_id = None  # 初始化以避免异常处理时 UnboundLocalError

        try:
            # 1. 创建配置
            config = BacktestConfig(
                start_date=request.start_date,
                end_date=request.end_date,
                initial_capital=request.initial_capital,
                rebalance_frequency=request.rebalance_frequency,
                use_pit_data=request.use_pit_data,
                transaction_cost_bps=request.transaction_cost_bps,
                trust_status=request.trust_status,
                data_manifest_id=request.data_manifest_id,
                pit_coverage=request.pit_coverage,
                config_hash=request.config_hash,
                code_commit=request.code_commit,
                engine_version=request.engine_version,
                research_trial_id=request.research_trial_id,
                decision_snapshot_id=request.decision_snapshot_id,
            )

            # 2. 创建回测记录
            backtest_model = self.repository.create_backtest(request.name, config)
            backtest_id = backtest_model.id

            # 3. 标记为运行中
            self.repository.update_status(backtest_id, "running")

            # 4. Trusted runs fail closed unless a canonical PIT view is injected.
            regime_reader = self.get_regime
            price_reader = self.get_price
            if request.trust_status == "pit_verified":
                if self.pit_data_view is None:
                    raise ValueError("pit_verified execution requires a canonical PITDataView")
                if self.get_decision_snapshot is None:
                    raise ValueError(
                        "pit_verified execution requires a canonical decision snapshot reader"
                    )
                snapshot = self.get_decision_snapshot(request.decision_snapshot_id or "")
                if snapshot is None:
                    raise ValueError("decision input snapshot not found")
                regime_reader, price_reader = self._build_pit_readers(self.pit_data_view)

            # 5. 创建并运行回测引擎
            engine = BacktestEngine(
                config=config,
                get_regime_func=regime_reader,
                get_asset_price_func=price_reader,
                pit_processor=None,
            )

            result = engine.run()
            warnings.extend(result.warnings)

            # 6. 保存结果
            self.repository.save_result(backtest_id, result)

            # ========== 自动触发审计分析 ==========
            audit_status = "skipped"
            audit_error = None
            audit_report_id = None

            try:
                logger.info(f"Backtest {backtest_id} 完成，触发审计分析...")
                audit_status = "pending"

                audit_response = generate_attribution_report_for_backtest(
                    backtest_id=backtest_id,
                    backtest_repository=self.repository,
                )

                if audit_response.success:
                    audit_status = "success"
                    audit_report_id = audit_response.report_id
                    logger.info(f"审计分析完成: report_id={audit_response.report_id}")
                else:
                    audit_status = "failed"
                    audit_error = audit_response.error
                    logger.warning(f"审计分析失败: {audit_response.error}")

            except Exception as audit_exc:
                # 审计失败不影响回测结果，但记录状态
                audit_status = "failed"
                audit_error = str(audit_exc)
                logger.warning(f"审计分析异常: {audit_error}", exc_info=True)
            # ============================================

            logger.info(f"Backtest {backtest_id} completed successfully")

            return RunBacktestResponse(
                backtest_id=backtest_id,
                status="completed",
                result=result.to_summary_dict(),
                errors=errors,
                warnings=warnings,
                audit_status=audit_status,
                audit_error=audit_error,
                audit_report_id=audit_report_id,
            )

        except Exception as e:
            logger.exception(f"Backtest failed: {e}")

            # 如果已经创建了记录，标记为失败
            if backtest_id:
                self.repository.update_status(backtest_id, "failed", str(e))

            return RunBacktestResponse(
                backtest_id=backtest_id if "backtest_id" in locals() else None,
                status="failed",
                result=None,
                errors=[str(e)],
                warnings=warnings,
                audit_status="skipped",  # 回测失败时审计被跳过
            )

    @staticmethod
    def _build_pit_readers(
        pit_data_view: PITDataView,
    ) -> tuple[Callable[[date], dict | None], Callable[[str, date], float | None]]:
        """Adapt the canonical PIT view to the legacy engine callback contract."""

        def as_of(day: date) -> datetime:
            return datetime.combine(day, time.max, tzinfo=UTC)

        def get_regime(day: date) -> dict | None:
            rows = pit_data_view.query("regime_state", as_of(day), "public", {})
            return dict(rows[0].payload) if rows else None

        def get_price(asset_code: str, day: date) -> float | None:
            rows = pit_data_view.query(
                "price_bar",
                as_of(day),
                "public",
                {"business_key": asset_code},
            )
            if not rows:
                return None
            value = rows[0].payload.get("close")
            return float(value) if value is not None else None

        return get_regime, get_price


@dataclass
class GetBacktestResultRequest:
    """获取回测结果的请求 DTO"""

    backtest_id: int


@dataclass
class GetBacktestResultResponse:
    """获取回测结果的响应 DTO"""

    backtest_id: int | None
    name: str | None
    status: str | None
    result: dict[str, Any] | None
    error: str | None


class GetBacktestResultUseCase:
    """
    获取回测结果的用例
    """

    def __init__(self, repository: DjangoBacktestRepository):
        """
        Args:
            repository: 回测仓储
        """
        self.repository = repository

    def execute(self, request: GetBacktestResultRequest) -> GetBacktestResultResponse:
        """
        执行获取回测结果

        Args:
            request: 请求

        Returns:
            GetBacktestResultResponse: 回测结果
        """
        backtest = self.repository.get_backtest_by_id(request.backtest_id)

        if not backtest:
            return GetBacktestResultResponse(
                backtest_id=None,
                name=None,
                status=None,
                result=None,
                error=f"Backtest with id {request.backtest_id} not found",
            )

        # 如果已完成，返回详细结果
        if backtest.status == "completed":
            domain_result = DjangoBacktestRepository.to_domain_entity(backtest)
            return GetBacktestResultResponse(
                backtest_id=backtest.id,
                name=backtest.name,
                status=backtest.status,
                result=domain_result.to_summary_dict(),
                error=None,
            )
        else:
            # 返回基本信息
            return GetBacktestResultResponse(
                backtest_id=backtest.id,
                name=backtest.name,
                status=backtest.status,
                result=None,
                error=None,
            )


@dataclass
class ListBacktestsRequest:
    """列出回测的请求 DTO"""

    status: str | None = None
    limit: int | None = None


@dataclass
class ListBacktestsResponse:
    """列出回测的响应 DTO"""

    backtests: list[dict[str, Any]]
    total_count: int


class ListBacktestsUseCase:
    """
    列出回测的用例
    """

    def __init__(self, repository: DjangoBacktestRepository):
        """
        Args:
            repository: 回测仓储
        """
        self.repository = repository

    def execute(self, request: ListBacktestsRequest) -> ListBacktestsResponse:
        """
        执行列出回测

        Args:
            request: 请求

        Returns:
            ListBacktestsResponse: 回测列表
        """
        if request.status:
            backtests = self.repository.get_backtests_by_status(request.status)
        else:
            backtests = self.repository.get_all_backtests(request.limit)

        return ListBacktestsResponse(
            backtests=[
                {
                    "id": b.id,
                    "name": b.name,
                    "status": b.status,
                    "start_date": b.start_date.isoformat(),
                    "end_date": b.end_date.isoformat(),
                    "total_return": b.total_return,
                    "created_at": b.created_at.isoformat(),
                }
                for b in backtests
            ],
            total_count=len(backtests),
        )


@dataclass
class DeleteBacktestRequest:
    """删除回测的请求 DTO"""

    backtest_id: int


@dataclass
class DeleteBacktestResponse:
    """删除回测的响应 DTO"""

    success: bool
    error: str | None


class DeleteBacktestUseCase:
    """
    删除回测的用例
    """

    def __init__(self, repository: DjangoBacktestRepository):
        """
        Args:
            repository: 回测仓储
        """
        self.repository = repository

    def execute(self, request: DeleteBacktestRequest) -> DeleteBacktestResponse:
        """
        执行删除回测

        Args:
            request: 请求

        Returns:
            DeleteBacktestResponse: 删除结果
        """
        success = self.repository.delete_backtest(request.backtest_id)

        if not success:
            return DeleteBacktestResponse(
                success=False, error=f"Backtest with id {request.backtest_id} not found"
            )

        return DeleteBacktestResponse(success=True, error=None)


@dataclass
class GetBacktestStatisticsResponse:
    """获取回测统计的响应 DTO"""

    total: int
    by_status: dict[str, dict]
    avg_return: float
    max_return: float
    min_return: float


class GetBacktestStatisticsUseCase:
    """
    获取回测统计的用例
    """

    def __init__(self, repository: DjangoBacktestRepository):
        """
        Args:
            repository: 回测仓储
        """
        self.repository = repository

    def execute(self) -> GetBacktestStatisticsResponse:
        """
        执行获取统计

        Returns:
            GetBacktestStatisticsResponse: 统计数据
        """
        stats = self.repository.get_statistics()

        return GetBacktestStatisticsResponse(
            total=stats["total"],
            by_status=stats["by_status"],
            avg_return=stats["avg_return"],
            max_return=stats["max_return"],
            min_return=stats["min_return"],
        )
