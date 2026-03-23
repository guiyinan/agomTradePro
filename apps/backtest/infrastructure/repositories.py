"""
Repositories for Backtest Module.

Infrastructure layer implementation using Django ORM.
"""

from datetime import date
from typing import Any, Dict, List, Optional

from django.db import transaction
from django.db.models import Avg
from django.utils import timezone

from ..domain.entities import (
    BacktestConfig,
    BacktestStatus,
    Trade,
)
from ..domain.entities import (
    BacktestResult as DomainBacktestResult,
)
from .models import BacktestResultModel, BacktestTradeModel


class BacktestRepositoryError(Exception):
    """回测仓储异常"""

    pass


class DjangoBacktestRepository:
    """
    Django ORM 实现的回测仓储

    提供回测结果和配置的增删改查操作。
    """

    def __init__(self):
        self._model = BacktestResultModel
        self._trade_model = BacktestTradeModel

    def create_backtest(self, name: str, config: BacktestConfig) -> BacktestResultModel:
        """
        创建回测记录

        Args:
            name: 回测名称
            config: 回测配置

        Returns:
            BacktestResultModel: 创建的 ORM 模型实例
        """
        return self._model.objects.create(
            name=name,
            status="pending",
            start_date=config.start_date,
            end_date=config.end_date,
            initial_capital=config.initial_capital,
            rebalance_frequency=config.rebalance_frequency,
            use_pit_data=config.use_pit_data,
            transaction_cost_bps=config.transaction_cost_bps,
        )

    def get_backtest_by_id(self, backtest_id: int) -> BacktestResultModel | None:
        """
        按 ID 获取回测记录

        Args:
            backtest_id: 回测 ID

        Returns:
            Optional[BacktestResultModel]: 回测 ORM 模型，不存在则返回 None
        """
        try:
            return self._model.objects.get(id=backtest_id)
        except self._model.DoesNotExist:
            return None

    def get_backtests_by_status(self, status: str) -> list[BacktestResultModel]:
        """
        按状态获取回测列表

        Args:
            status: 状态（pending, running, completed, failed）

        Returns:
            List[BacktestResultModel]: 回测 ORM 模型列表
        """
        return list(self._model.objects.filter(status=status).order_by("-created_at"))

    def get_all_backtests(self, limit: int | None = None) -> list[BacktestResultModel]:
        """
        获取所有回测记录

        Args:
            limit: 限制返回数量

        Returns:
            List[BacktestResultModel]: 回测 ORM 模型列表
        """
        query = self._model.objects.all().order_by("-created_at")
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

    def save_result(self, backtest_id: int, result: DomainBacktestResult) -> bool:
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

    def delete_backtest(self, backtest_id: int) -> bool:
        """
        删除回测记录

        Args:
            backtest_id: 回测 ID

        Returns:
            bool: 是否成功删除
        """
        count, _ = self._model.objects.filter(id=backtest_id).delete()
        return count > 0

    def get_statistics(self) -> dict[str, Any]:
        """
        获取回测统计信息

        Returns:
            Dict: 统计信息字典
        """
        total = self._model.objects.count()

        # 按状态统计
        status_stats = {}
        for status_choice in self._model.STATUS_CHOICES:
            status_value = status_choice[0]
            count = self._model.objects.filter(status=status_value).count()
            status_stats[status_value] = {
                "count": count,
                "percentage": count / total if total > 0 else 0,
            }

        # 计算平均收益率（仅针对已完成的回测）
        completed = self._model.objects.filter(status="completed", total_return__isnull=False)
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
    def to_domain_entity(orm_obj: BacktestResultModel) -> DomainBacktestResult:
        """
        将 ORM 对象转换为 Domain 实体

        Args:
            orm_obj: ORM 模型实例

        Returns:
            DomainBacktestResult: Domain 层的回测结果实体
        """
        from ..domain.entities import BacktestConfig

        config = BacktestConfig(
            start_date=orm_obj.start_date,
            end_date=orm_obj.end_date,
            initial_capital=float(orm_obj.initial_capital),
            rebalance_frequency=orm_obj.rebalance_frequency,
            use_pit_data=orm_obj.use_pit_data,
            transaction_cost_bps=orm_obj.transaction_cost_bps,
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

        return DomainBacktestResult(
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
