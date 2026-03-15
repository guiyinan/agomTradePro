from typing import TYPE_CHECKING
"""
AgomSAAF SDK - Backtest 回测引擎模块

提供回测相关的 API 操作。
"""

from datetime import date
from typing import Any, Optional

from .base import BaseModule
from ..types import BacktestParams, BacktestResult


class BacktestModule(BaseModule):
    """
    回测引擎模块

    提供回测运行、结果查询等功能。
    """

    def __init__(self, client: Any) -> None:
        """
        初始化 Backtest 模块

        Args:
            client: AgomSAAF 客户端实例
        """
        super().__init__(client, "/api/backtest")

    def run(
        self,
        strategy_name: str,
        start_date: date,
        end_date: date,
        initial_capital: float = 1000000.0,
        params: Optional[dict[str, Any]] = None,
    ) -> BacktestResult:
        """
        运行回测

        Args:
            strategy_name: 策略名称
            start_date: 回测开始日期
            end_date: 回测结束日期
            initial_capital: 初始资金（默认 100 万）
            params: 策略参数（可选）

        Returns:
            回测结果

        Raises:
            ValidationError: 当参数验证失败时
            ServerError: 当回测执行失败时

        Example:
            >>> from datetime import date
            >>> client = AgomSAAFClient()
            >>> result = client.backtest.run(
            ...     strategy_name="momentum",
            ...     start_date=date(2023, 1, 1),
            ...     end_date=date(2024, 12, 31),
            ...     initial_capital=1000000.0
            ... )
            >>> print(f"年化收益: {result.annual_return:.2%}")
            >>> print(f"最大回撤: {result.max_drawdown:.2%}")
        """
        data: dict[str, Any] = {
            "name": strategy_name,
            "start_date": start_date.isoformat(),
            "end_date": end_date.isoformat(),
            "initial_capital": initial_capital,
        }

        if params is not None:
            data["params"] = params

        response = self._post("run/", json=data)
        return self._parse_result(response)

    def get_result(self, backtest_id: int) -> BacktestResult:
        """
        获取回测结果详情

        Args:
            backtest_id: 回测 ID

        Returns:
            回测结果详情

        Raises:
            NotFoundError: 当回测不存在时

        Example:
            >>> client = AgomSAAFClient()
            >>> result = client.backtest.get_result(123)
            >>> print(f"状态: {result.status}")
            >>> print(f"总收益: {result.total_return:.2%}")
        """
        response = self._get(f"backtests/{backtest_id}/")
        return self._parse_result(response)

    def list_backtests(
        self,
        strategy_name: Optional[str] = None,
        status: Optional[str] = None,
        limit: int = 100,
    ) -> list[BacktestResult]:
        """
        获取回测列表

        Args:
            strategy_name: 策略名称过滤（可选）
            status: 状态过滤（可选）
            limit: 返回数量限制

        Returns:
            回测结果列表

        Example:
            >>> client = AgomSAAFClient()
            >>> results = client.backtest.list_backtests(
            ...     strategy_name="momentum",
            ...     status="completed"
            ... )
            >>> for result in results:
            ...     print(f"{result.id}: {result.annual_return:.2%}")
        """
        params: dict[str, Any] = {"limit": limit}

        if strategy_name is not None:
            params["strategy_name"] = strategy_name
        if status is not None:
            params["status"] = status

        response = self._get("backtests/", params=params)
        results = response.get("backtests", response.get("results", response))
        return [self._parse_result(item) for item in results]

    def delete_result(self, backtest_id: int) -> None:
        """
        删除回测结果

        Args:
            backtest_id: 回测 ID

        Raises:
            NotFoundError: 当回测不存在时

        Example:
            >>> client = AgomSAAFClient()
            >>> client.backtest.delete_result(123)
            >>> print("回测结果已删除")
        """
        self._delete(f"backtests/{backtest_id}/")

    def get_equity_curve(self, backtest_id: int) -> list[dict[str, Any]]:
        """
        获取回测净值曲线

        Args:
            backtest_id: 回测 ID

        Returns:
            净值曲线数据，每个元素包含 date 和 value 字段

        Raises:
            NotFoundError: 当回测不存在时

        Example:
            >>> client = AgomSAAFClient()
            >>> curve = client.backtest.get_equity_curve(123)
            >>> for point in curve:
            ...     print(f"{point['date']}: {point['value']:.2f}")
        """
        response = self._get(f"backtests/{backtest_id}/equity-curve/")
        return response.get("curve", response)

    def _parse_result(self, data: dict[str, Any]) -> BacktestResult:
        """
        解析回测结果数据

        Args:
            data: API 返回的 JSON 数据

        Returns:
            BacktestResult 对象
        """
        result = data.get("result", {}) if isinstance(data, dict) else {}
        backtest_id = data.get("id", data.get("backtest_id", 0))
        return BacktestResult(
            id=backtest_id,
            status=data.get("status", "unknown"),
            total_return=result.get("total_return", data.get("total_return", 0.0)),
            annual_return=result.get("annual_return", data.get("annual_return", 0.0)),
            max_drawdown=result.get("max_drawdown", data.get("max_drawdown", 0.0)),
            sharpe_ratio=result.get("sharpe_ratio", data.get("sharpe_ratio")),
        )
