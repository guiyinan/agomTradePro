"""
AgomTradePro MCP Tools - Simulated Trading 模拟盘交易工具

提供模拟盘交易相关的 MCP 工具。
"""

import re
from copy import deepcopy
from datetime import date
from typing import Any

from mcp.server.fastmcp import FastMCP

from agomtradepro import AgomTradeProClient
from agomtradepro.exceptions import AgomTradeProAPIError
from agomtradepro.exceptions import ConnectionError as SDKConnectionError
from agomtradepro.exceptions import ExecutionOutcomeUnknownError as SDKExecutionOutcomeUnknownError
from agomtradepro.exceptions import TimeoutError as SDKTimeoutError

_SAFE_UPSTREAM_ERROR_CODE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$")
_SAFE_INDETERMINATE_RESPONSE_KEYS = frozenset(
    {
        "code",
        "error_code",
        "success",
        "error",
        "message",
        "detail",
        "effects_indeterminate",
        "retry_with_same_idempotency_key",
        "request_id",
        "trace_id",
    }
)


def _stable_upstream_error_code(response: dict[str, Any] | None) -> str | None:
    """Return a bounded stable code from a structured upstream error body."""

    if type(response) is not dict:
        return None
    for field in ("code", "error_code"):
        value = response.get(field)
        if type(value) is str:
            normalized = value.strip().lower()
            if _SAFE_UPSTREAM_ERROR_CODE.fullmatch(normalized):
                return normalized
    return None


def _is_safe_indeterminate_response(response: dict[str, Any] | None) -> bool:
    """Allow only bounded structured error fields to cross the MCP boundary."""

    if type(response) is not dict or response.get("effects_indeterminate") is not True:
        return False
    for key, value in response.items():
        if type(key) is not str or key not in _SAFE_INDETERMINATE_RESPONSE_KEYS:
            return False
        if key == "success" and value is not False:
            return False
        if key == "error" and (type(value) is not str or not value.strip()):
            return False
        if key in {"code", "error_code"} and (
            type(value) is not str or not _SAFE_UPSTREAM_ERROR_CODE.fullmatch(value.strip().lower())
        ):
            return False
        if type(value) is str:
            normalized = value.lower()
            if (
                len(value) > 240
                or ("<" in normalized and ">" in normalized)
                or "traceback" in normalized
                or "password" in normalized
                or "passwd" in normalized
                or "secret" in normalized
                or "authorization" in normalized
                or "bearer " in normalized
                or "api_key=" in normalized
                or "access_key=" in normalized
                or "credential" in normalized
                or "token=" in normalized
                or "://" in normalized
            ):
                return False
        elif type(value) not in {bool, int}:
            return False
    return True


def _indeterminate_close_result(
    error: AgomTradeProAPIError,
    *,
    idempotency_key: str,
) -> dict[str, Any] | None:
    """Return a safe uncertain outcome for close transport, redirect, or HTTP 5xx errors."""

    if isinstance(error, SDKExecutionOutcomeUnknownError):
        error_code = error.code
        upstream_response = None
    elif isinstance(error, SDKTimeoutError):
        error_code = "transport_timeout"
        upstream_response = None
    elif isinstance(error, SDKConnectionError):
        error_code = "transport_connection_failed"
        upstream_response = None
    elif type(error.status_code) is int and 300 <= error.status_code <= 399:
        error_code = "upstream_http_redirect"
        upstream_response = None
    elif type(error.status_code) is int and 500 <= error.status_code <= 599:
        marked_response = error.status_code == 503 and _is_safe_indeterminate_response(
            error.response
        )
        error_code = _stable_upstream_error_code(error.response) or (
            "upstream_indeterminate" if marked_response else "upstream_http_5xx"
        )
        upstream_response = deepcopy(error.response) if marked_response else None
    else:
        return None

    result: dict[str, Any] = {
        "success": False,
        "status": "unknown",
        "effects_indeterminate": True,
        "retry_with_same_idempotency_key": True,
        "idempotency_key": idempotency_key,
        "error": {
            "code": error_code,
            "message": "结果尚未核实；请使用完全相同的请求和幂等键重试。",
        },
    }
    if upstream_response is not None:
        result["upstream_response"] = upstream_response
    if type(error.status_code) is int and 300 <= error.status_code <= 399:
        result["error"]["upstream_status_code"] = error.status_code
    elif type(error.status_code) is int and 500 <= error.status_code <= 599:
        result["error"]["upstream_status_code"] = error.status_code
    return result


def register_simulated_trading_tools(server: FastMCP) -> None:
    """注册 SimulatedTrading 相关的 MCP 工具"""

    @server.tool()
    def list_accounts(
        account_type: str | None = None,
        status: str | None = None,
        limit: int = 20,
    ) -> list[dict[str, Any]]:
        """
        获取统一账户列表。

        Args:
            account_type: 可选，real 或 simulated
            status: 账户状态过滤（active/inactive/closed）
            limit: 返回数量限制
        """
        client = AgomTradeProClient()
        return client.account.list_accounts(
            account_type=account_type,
            active_only=status not in {"inactive", "closed"},
            limit=limit,
        )

    @server.tool()
    def get_account(account_id: int) -> dict[str, Any]:
        """
        获取统一账户详情。
        """
        client = AgomTradeProClient()
        return client.account.get_account(account_id)

    @server.tool()
    def create_account(
        name: str,
        initial_capital: float,
        idempotency_key: str,
        account_type: str = "simulated",
    ) -> dict[str, Any]:
        """
        创建统一账户；同一次提交的重试必须复用 idempotency_key。
        """
        client = AgomTradeProClient()
        try:
            return client.account.create_account(
                name=name,
                initial_capital=initial_capital,
                account_type=account_type,
                idempotency_key=idempotency_key,
            )
        except Exception as exc:
            return {
                "success": False,
                "error": str(exc),
                "payload": {
                    "name": name,
                    "initial_capital": initial_capital,
                    "account_type": account_type,
                },
            }

    @server.tool()
    def get_account_positions(account_id: int) -> list[dict[str, Any]]:
        """
        获取统一账户持仓。
        """
        client = AgomTradeProClient()
        return client.account.get_account_positions(account_id)

    @server.tool()
    def get_account_performance(
        account_id: int,
        start_date: str | None = None,
        end_date: str | None = None,
    ) -> dict[str, Any]:
        """
        获取统一账户绩效。
        """
        client = AgomTradeProClient()
        return client.account.get_account_performance(
            account_id=account_id,
            start_date=start_date,
            end_date=end_date,
        )

    @server.tool()
    def list_simulated_accounts(
        status: str | None = None,
        limit: int = 20,
    ) -> list[dict[str, Any]]:
        """
        获取模拟账户列表

        Args:
            status: 账户状态过滤（active/inactive/closed）
            limit: 返回数量限制

        Returns:
            模拟账户列表

        Example:
            >>> accounts = list_simulated_accounts(status="active")
        """
        client = AgomTradeProClient()
        return client.simulated_trading.list_accounts(
            status=status,
            account_type="simulated",
            limit=limit,
        )

    @server.tool()
    def get_simulated_account(account_id: int) -> dict[str, Any]:
        """
        获取模拟账户详情

        Args:
            account_id: 账户 ID

        Returns:
            账户详情

        Example:
            >>> account = get_simulated_account(1)
        """
        client = AgomTradeProClient()
        return client.account.get_account(account_id)

    @server.tool()
    def delete_simulated_account(account_id: int) -> dict[str, Any]:
        """
        删除单个模拟账户。

        Args:
            account_id: 账户 ID

        Returns:
            删除结果
        """
        client = AgomTradeProClient()
        return client.simulated_trading.delete_account(account_id)

    @server.tool()
    def batch_delete_simulated_accounts(account_ids: list[int]) -> dict[str, Any]:
        """
        批量删除模拟账户。

        Args:
            account_ids: 账户 ID 列表

        Returns:
            批量删除结果
        """
        client = AgomTradeProClient()
        return client.simulated_trading.batch_delete_accounts(account_ids)

    @server.tool()
    def create_simulated_account(
        name: str,
        initial_capital: float,
        start_date: str,
        idempotency_key: str,
    ) -> dict[str, Any]:
        """
        创建模拟账户

        Args:
            name: 账户名称
            initial_capital: 初始资金
            start_date: 兼容参数（ISO 日期），不改变服务端账户创建时间。
            idempotency_key: 本次提交的稳定键，重试复用，新提交使用新键。

        Returns:
            创建的账户信息

        Example:
            >>> account = create_simulated_account(
            ...     name="测试账户",
            ...     initial_capital=1000000.0,
            ...     start_date="2024-01-01",
            ...     idempotency_key="create-test-account-1"
            ... )
        """
        client = AgomTradeProClient()
        parsed_date = date.fromisoformat(start_date)
        try:
            return client.simulated_trading.create_account(
                name,
                initial_capital,
                parsed_date,
                account_type="simulated",
                idempotency_key=idempotency_key,
            )
        except Exception as exc:
            return {
                "success": False,
                "error": str(exc),
                "payload": {
                    "name": name,
                    "initial_capital": initial_capital,
                    "start_date": start_date,
                },
            }

    @server.tool()
    def execute_simulated_trade(
        account_id: int,
        asset_code: str,
        side: str,
        quantity: float,
        price: float | None = None,
        *,
        asset_type: str,
        idempotency_key: str,
    ) -> dict[str, Any]:
        """
        执行模拟交易。

        Args:
            account_id: 账户 ID。
            asset_code: 资产代码。
            side: 交易方向（buy/sell）。
            quantity: 数量。
            price: 调用方明确提供的价格；None 或省略不支持市价单。
            asset_type: 调用方明确选择、由服务端校验的资产类型；不猜测默认值。
            idempotency_key: 本次操作的稳定键；确认和重试复用，新操作使用新键。

        Returns:
            交易执行结果。

        Example:
            以下为普通 A 股模拟交易示例，需先配置相应参考和结算依据::

                execute_simulated_trade(
                    account_id=1,
                    asset_code="600000.SH",
                    side="buy",
                    quantity=1000,
                    price=10.5,
                    asset_type="equity",
                    idempotency_key="manual-trade-example-1",
                )
        """
        client = AgomTradeProClient()
        return client.simulated_trading.execute_trade(
            account_id=account_id,
            asset_code=asset_code,
            side=side,
            quantity=quantity,
            price=price,
            asset_type=asset_type,
            idempotency_key=idempotency_key,
        )

    @server.tool()
    def get_simulated_positions(account_id: int) -> list[dict[str, Any]]:
        """
        获取模拟账户持仓

        Args:
            account_id: 账户 ID

        Returns:
            持仓列表

        Example:
            >>> positions = get_simulated_positions(account_id=1)
        """
        client = AgomTradeProClient()
        return client.account.get_account_positions(account_id)

    @server.tool()
    def get_simulated_performance(account_id: int) -> dict[str, Any]:
        """
        获取模拟账户绩效

        Args:
            account_id: 账户 ID

        Returns:
            绩效数据

        Example:
            >>> perf = get_simulated_performance(account_id=1)
            >>> print(f"总收益: {perf['total_return']:.2%}")
        """
        client = AgomTradeProClient()
        return client.account.get_account_performance(account_id)

    @server.tool()
    def reset_simulated_account(
        account_id: int,
        new_initial_capital: float | None = None,
    ) -> dict[str, Any]:
        """
        重置模拟账户

        Args:
            account_id: 账户 ID
            new_initial_capital: 新的初始资金（可选）

        Returns:
            重置后的账户信息

        Example:
            >>> account = reset_simulated_account(account_id=1)
        """
        client = AgomTradeProClient()
        try:
            return client.simulated_trading.reset_account(account_id, new_initial_capital)
        except Exception as exc:
            return {
                "success": False,
                "account_id": account_id,
                "new_initial_capital": new_initial_capital,
                "error": str(exc),
            }

    @server.tool()
    def run_simulated_auto_trading(
        trade_date: str | None = None,
        account_ids: list[int] | None = None,
        *,
        idempotency_key: str,
    ) -> dict[str, Any]:
        """
        手动触发模拟盘自动交易。

        Args:
            trade_date: 可选的业务交易日。
            account_ids: 可选的已确认模拟账户范围。
            idempotency_key: 调用方提供的稳定操作键；确认与重试必须复用。

        Notes:
            若账户已绑定激活策略，自动交易会走 StrategyExecutionGateway；
            未绑定策略的账户继续使用兼容的旧自动交易逻辑。缺少键时不会生成新键。
        """
        if (
            type(idempotency_key) is not str
            or not idempotency_key
            or len(idempotency_key) > 128
            or any(character.isspace() for character in idempotency_key)
        ):
            return {
                "success": False,
                "trade_date": trade_date,
                "account_ids": account_ids,
                "error": "A stable operation key of at most 128 characters is required.",
            }
        client = AgomTradeProClient()
        parsed_date = date.fromisoformat(trade_date) if trade_date else None
        try:
            return client.simulated_trading.run_auto_trading(
                trade_date=parsed_date,
                account_ids=account_ids,
                idempotency_key=idempotency_key,
            )
        except Exception as exc:
            return {
                "success": False,
                "trade_date": trade_date,
                "account_ids": account_ids,
                "error": str(exc),
            }

    @server.tool()
    def close_simulated_position(
        account_id: int,
        asset_code: str,
        close_shares: int,
        close_price: str,
        idempotency_key: str,
    ) -> dict[str, Any]:
        """
        平仓

        Args:
            account_id: 账户 ID
            asset_code: 资产代码
            close_shares: 明确要卖出的整数股数
            close_price: 调用者明确输入的十进制字符串价格
            idempotency_key: 同一操作重试时复用的稳定键

        Returns:
            平仓结果

        Example:
            >>> result = close_simulated_position(
            ...     account_id=1,
            ...     asset_code="000001.SH",
            ...     close_shares=100,
            ...     close_price="12.3400",
            ...     idempotency_key="close-operation-1",
            ... )
        """
        client = AgomTradeProClient()
        try:
            return client.simulated_trading.close_position(
                account_id=account_id,
                asset_code=asset_code,
                close_shares=close_shares,
                close_price=close_price,
                idempotency_key=idempotency_key,
            )
        except AgomTradeProAPIError as exc:
            uncertain_result = _indeterminate_close_result(
                exc,
                idempotency_key=idempotency_key,
            )
            if uncertain_result is None:
                raise
            return uncertain_result

    @server.tool()
    def run_simulated_daily_inspection(
        account_id: int,
        strategy_id: int | None = None,
        inspection_date: str | None = None,
        auto_create_proposal: bool = False,
    ) -> dict[str, Any]:
        """
        执行指定账户的日更巡检并落库。
        """
        client = AgomTradeProClient()
        parsed_date = date.fromisoformat(inspection_date) if inspection_date else None
        try:
            return client.simulated_trading.run_daily_inspection(
                account_id=account_id,
                strategy_id=strategy_id,
                inspection_date=parsed_date,
                auto_create_proposal=auto_create_proposal,
            )
        except Exception as exc:
            return {
                "success": False,
                "account_id": account_id,
                "strategy_id": strategy_id,
                "inspection_date": inspection_date,
                "auto_create_proposal": auto_create_proposal,
                "error": str(exc),
            }

    @server.tool()
    def list_simulated_daily_inspections(
        account_id: int,
        limit: int = 20,
        inspection_date: str | None = None,
    ) -> dict[str, Any]:
        """
        查询指定账户的日更巡检历史。
        """
        client = AgomTradeProClient()
        parsed_date = date.fromisoformat(inspection_date) if inspection_date else None
        return client.simulated_trading.list_daily_inspections(
            account_id=account_id,
            limit=limit,
            inspection_date=parsed_date,
        )
