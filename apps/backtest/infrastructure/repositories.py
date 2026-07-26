"""
Repositories for Backtest Module.

Infrastructure layer implementation using Django ORM.
"""

from datetime import date, datetime
from typing import Any

from django.db.models import Avg

from ..domain.entities import BacktestConfig, BacktestResult, Trade
from .models import BacktestResultModel, BacktestTradeModel


class BacktestRepositoryError(Exception):
    """回测仓储异常"""

    pass


class DjangoBacktestRepository:
    """
    Django ORM 实现的回测仓储

    提供回测结果和配置的增删改查操作。
    """

    def __init__(self) -> None:
        self._model = BacktestResultModel
        self._trade_model = BacktestTradeModel

    def create_backtest(
        self,
        name: str,
        config: BacktestConfig,
        *,
        user_id: int | None = None,
    ) -> BacktestResultModel:
        """
        创建回测记录

        Args:
            name: 回测名称
            config: 回测配置

        Returns:
            BacktestResultModel: 创建的 ORM 模型实例
        """
        return self._model.objects.create(
            user_id=user_id,
            name=name,
            status="pending",
            start_date=config.start_date,
            end_date=config.end_date,
            initial_capital=config.initial_capital,
            rebalance_frequency=config.rebalance_frequency,
            use_pit_data=config.use_pit_data,
            transaction_cost_bps=config.transaction_cost_bps,
            data_manifest_id=config.data_manifest_id,
            pit_coverage=config.pit_coverage,
            trust_status=config.trust_status,
            config_hash=config.config_hash,
            code_commit=config.code_commit,
            engine_version=config.engine_version,
            research_trial_id=config.research_trial_id,
            decision_snapshot_id=config.decision_snapshot_id,
        )

    def get_backtest_by_id(
        self,
        backtest_id: int,
        *,
        user_id: int | None = None,
    ) -> BacktestResultModel | None:
        """
        按 ID 获取回测记录

        Args:
            backtest_id: 回测 ID

        Returns:
            Optional[BacktestResultModel]: 回测 ORM 模型，不存在则返回 None
        """
        try:
            filters: dict[str, int] = {"id": backtest_id}
            if user_id is not None:
                filters["user_id"] = user_id
            return self._model.objects.get(**filters)
        except self._model.DoesNotExist:
            return None

    def get_backtests_by_status(
        self,
        status: str,
        *,
        user_id: int | None = None,
    ) -> list[BacktestResultModel]:
        """
        按状态获取回测列表

        Args:
            status: 状态（pending, running, completed, failed）

        Returns:
            List[BacktestResultModel]: 回测 ORM 模型列表
        """
        queryset = self._model.objects.filter(status=status)
        if user_id is not None:
            queryset = queryset.filter(user_id=user_id)
        return list(queryset.order_by("-created_at"))

    def get_all_backtests(
        self,
        limit: int | None = None,
        *,
        user_id: int | None = None,
    ) -> list[BacktestResultModel]:
        """
        获取所有回测记录

        Args:
            limit: 限制返回数量

        Returns:
            List[BacktestResultModel]: 回测 ORM 模型列表
        """
        query = self._model.objects.all()
        if user_id is not None:
            query = query.filter(user_id=user_id)
        query = query.order_by("-created_at")
        if limit:
            return list(query[:limit])
        return list(query)

    def update_status(
        self, backtest_id: int, status: str, error_message: str | None = None
    ) -> bool:
        """
        更新回测状态

        Args:
            backtest_id: 回测 ID
            status: 新状态
            error_message: 错误信息（仅失败时）

        Returns:
            bool: 是否成功更新
        """
        try:
            orm_obj = self._model.objects.get(id=backtest_id)
            orm_obj.status = status

            if status == "failed" and error_message:
                orm_obj.mark_failed(error_message)
            else:
                # 对于所有状态（除了 failed），都需要保存
                orm_obj.save()

            return True
        except self._model.DoesNotExist:
            return False

    def save_result(self, backtest_id: int, result: BacktestResult) -> bool:
        """
        保存回测结果

        Args:
            backtest_id: 回测 ID
            result: Domain 层的回测结果实体

        Returns:
            bool: 是否成功保存
        """
        try:
            orm_obj = self._model.objects.get(id=backtest_id)

            # 转换交易记录为可序列化格式
            trades_data = [
                {
                    "trade_date": t.trade_date.isoformat(),
                    "asset_class": t.asset_class,
                    "action": t.action,
                    "shares": t.shares,
                    "price": t.price,
                    "notional": t.notional,
                    "cost": t.cost,
                }
                for t in result.trades
            ]

            # 转换权益曲线
            equity_curve_data = [
                {"date": d.isoformat(), "value": v} for d, v in result.equity_curve
            ]

            result_data = {
                "total_return": result.total_return,
                "annualized_return": result.annualized_return,
                "max_drawdown": result.max_drawdown,
                "sharpe_ratio": result.sharpe_ratio,
                "equity_curve": equity_curve_data,
                "regime_history": result.regime_history,
                "trades": trades_data,
                "warnings": result.warnings,
            }

            orm_obj.mark_completed(result.final_value, result_data)
            return True

        except self._model.DoesNotExist:
            return False

    def delete_backtest(
        self,
        backtest_id: int,
        *,
        user_id: int | None = None,
    ) -> bool:
        """
        删除回测记录

        Args:
            backtest_id: 回测 ID

        Returns:
            bool: 是否成功删除
        """
        queryset = self._model.objects.filter(id=backtest_id)
        if user_id is not None:
            queryset = queryset.filter(user_id=user_id)
        count, _ = queryset.delete()
        return count > 0

    def delete_completed_before(self, cutoff: datetime) -> int:
        """Bulk-delete completed backtests older than the aware cutoff."""

        queryset = self._model.objects.filter(
            status="completed",
            created_at__lt=cutoff,
        )
        backtest_count = queryset.count()
        queryset.delete()
        return backtest_count

    def get_statistics(self, *, user_id: int | None = None) -> dict[str, Any]:
        """
        获取回测统计信息

        Returns:
            Dict: 统计信息字典
        """
        queryset = self._model.objects.all()
        if user_id is not None:
            queryset = queryset.filter(user_id=user_id)
        total = queryset.count()

        # 按状态统计
        status_stats = {}
        for status_choice in self._model.STATUS_CHOICES:
            status_value = status_choice[0]
            count = queryset.filter(status=status_value).count()
            status_stats[status_value] = {
                "count": count,
                "percentage": count / total if total > 0 else 0,
            }

        # 计算平均收益率（仅针对已完成的回测）
        completed = queryset.filter(status="completed", total_return__isnull=False)
        if completed.exists():
            avg_result = completed.aggregate(avg=Avg("total_return"))
            avg_return = avg_result["avg"] or 0
            max_obj = completed.order_by("-total_return").first()
            max_return = max_obj.total_return if max_obj else 0
            min_obj = completed.order_by("total_return").first()
            min_return = min_obj.total_return if min_obj else 0
        else:
            avg_return = 0
            max_return = 0
            min_return = 0

        return {
            "total": total,
            "by_status": status_stats,
            "avg_return": avg_return,
            "max_return": max_return,
            "min_return": min_return,
        }

    def get_recent_results(self, limit: int = 10) -> list[dict[str, Any]]:
        """
        获取最近的回测结果摘要

        Args:
            limit: 返回数量限制

        Returns:
            List[Dict]: 回测摘要列表
        """
        results = self._model.objects.filter(status="completed").order_by("-created_at")[:limit]

        return [
            {
                "id": r.id,
                "name": r.name,
                "start_date": r.start_date.isoformat(),
                "end_date": r.end_date.isoformat(),
                "total_return": r.total_return,
                "annualized_return": r.annualized_return,
                "max_drawdown": r.max_drawdown,
                "sharpe_ratio": r.sharpe_ratio,
                "completed_at": r.completed_at.isoformat() if r.completed_at else None,
            }
            for r in results
        ]

    @staticmethod
    def to_domain_entity(orm_obj: BacktestResultModel) -> BacktestResult:
        """
        将 ORM 对象转换为 Domain 实体

        Args:
            orm_obj: ORM 模型实例

        Returns:
            BacktestResult: Domain 层的回测结果实体
        """
        from ..domain.entities import BacktestConfig

        config = BacktestConfig(
            start_date=orm_obj.start_date,
            end_date=orm_obj.end_date,
            initial_capital=float(orm_obj.initial_capital),
            rebalance_frequency=orm_obj.rebalance_frequency,
            use_pit_data=orm_obj.use_pit_data,
            transaction_cost_bps=orm_obj.transaction_cost_bps,
            trust_status=orm_obj.trust_status,
            data_manifest_id=orm_obj.data_manifest_id,
            pit_coverage=dict(orm_obj.pit_coverage or {}),
            config_hash=orm_obj.config_hash,
            code_commit=orm_obj.code_commit,
            engine_version=orm_obj.engine_version,
            research_trial_id=orm_obj.research_trial_id,
            decision_snapshot_id=orm_obj.decision_snapshot_id,
        )

        # 转换交易记录
        trades = [
            Trade(
                trade_date=date.fromisoformat(t["trade_date"]),
                asset_class=t["asset_class"],
                action=t["action"],
                shares=t["shares"],
                price=t["price"],
                notional=t["notional"],
                cost=t["cost"],
            )
            for t in orm_obj.trades
        ]

        # 转换权益曲线
        equity_curve = [(date.fromisoformat(e["date"]), e["value"]) for e in orm_obj.equity_curve]

        return BacktestResult(
            config=config,
            final_value=float(orm_obj.final_capital) if orm_obj.final_capital else 0.0,
            total_return=orm_obj.total_return or 0.0,
            annualized_return=orm_obj.annualized_return or 0.0,
            sharpe_ratio=orm_obj.sharpe_ratio,
            max_drawdown=orm_obj.max_drawdown or 0.0,
            trades=trades,
            equity_curve=equity_curve,
            regime_history=orm_obj.regime_history,
            warnings=orm_obj.warnings or [],
        )
