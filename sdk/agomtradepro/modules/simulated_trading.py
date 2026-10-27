"""
AgomTradePro SDK - Simulated Trading 模拟盘交易模块

提供模拟盘交易相关的 API 操作。
"""

import re
from datetime import date
from decimal import ROUND_HALF_EVEN, Decimal, DecimalException, localcontext
from typing import Any, cast

from requests.exceptions import RequestException

from .. import exceptions as sdk_exceptions
from ..exceptions import (
    AgomTradeProAPIError,
    ExecutionOutcomeUnknownError,
    ValidationError,
)
from .base import BaseModule
from .simulated_fee_corrections import SimulatedFeeCorrectionsModule

_CLOSE_PRICE_PATTERN = re.compile(r"^[0-9]+(?:\.[0-9]{1,4})?$")
# These are the exact storage constraints from the simulated-settlement Domain
# contract, not trade-fee rates or market configuration.
_CLOSE_SHARE_QUANTUM = Decimal("0.000001")
_CLOSE_PRICE_QUANTUM = Decimal("0.0001")
_CLOSE_MONEY_QUANTUM = Decimal("0.01")
_CLOSE_MAX_SHARE_VALUE = Decimal("100000000000000")
_CLOSE_MAX_PRICE_VALUE = Decimal("1000000")
_CLOSE_MAX_MONEY_VALUE = Decimal("10000000000000")
_CLOSE_RECEIPT_REQUIRED_FIELDS = frozenset(
    {
        "trade_id",
        "account_id",
        "idempotency_key",
        "request_payload_hash",
        "side",
        "asset_code",
        "quantity",
        "price",
        "amount",
        "commission",
        "transfer_fee",
        "stamp_duty",
        "slippage",
        "total_cost",
        "settlement_status",
        "settlement_release_date",
        "replayed",
    }
)


def _finite_decimal_string(value: Any) -> Decimal | None:
    """Parse one finite decimal string from the close response contract."""

    if type(value) is not str or not value or len(value) > 257:
        return None
    try:
        parsed = Decimal(value)
    except (DecimalException, ValueError):
        return None
    if not parsed.is_finite():
        return None
    parts = parsed.as_tuple()
    if len(parts.digits) > 64 or not isinstance(parts.exponent, int) or abs(parts.exponent) > 64:
        return None
    return parsed


def _is_ledger_storable_decimal(
    value: Decimal,
    *,
    quantum: Decimal,
    exclusive_maximum: Decimal,
    allow_zero: bool,
) -> bool:
    """Match the Domain's bounded exact-quantum storage validation."""

    parts = value.as_tuple()
    if (
        not isinstance(parts.exponent, int)
        or len(parts.digits) > 64
        or abs(parts.exponent) > 64
        or value < 0
        or (value == 0 and not allow_zero)
    ):
        return False
    try:
        with localcontext() as context:
            context.prec = 80
            quantized = value.quantize(quantum)
    except DecimalException:
        return False
    return quantized == value and value < exclusive_maximum


def _has_valid_close_response(
    response: dict[str, Any],
    *,
    account_id: int,
    asset_code: str,
    close_shares: int,
    close_price: Decimal,
    idempotency_key: str,
) -> bool:
    """Check response identity and the complete persisted close receipt contract."""

    if type(response) is not dict:
        return False
    if response.get("success") is not True or type(response.get("replayed")) is not bool:
        return False
    trade = response.get("trade")
    receipt = response.get("receipt")
    if type(trade) is not dict or type(receipt) is not dict:
        return False
    trade_id = trade.get("trade_id")
    if (
        type(trade_id) is not int
        or trade_id <= 0
        or type(trade.get("account_id")) is not int
        or trade.get("account_id") != account_id
        or trade.get("asset_code") != asset_code
        or trade.get("asset_type") != "equity"
        or trade.get("action") != "sell"
        or type(trade.get("quantity")) is not int
        or trade.get("quantity") != close_shares
        or trade.get("status") != "executed"
    ):
        return False
    trade_price = _finite_decimal_string(trade.get("price"))
    if trade_price is None or trade_price != close_price:
        return False
    if not _CLOSE_RECEIPT_REQUIRED_FIELDS.issubset(receipt):
        return False
    receipt_replayed = receipt.get("replayed")
    if (
        type(receipt.get("trade_id")) is not int
        or receipt.get("trade_id") != trade_id
        or type(receipt.get("account_id")) is not int
        or receipt.get("account_id") != account_id
        or receipt.get("idempotency_key") != idempotency_key
        or type(receipt.get("request_payload_hash")) is not str
        or re.fullmatch(r"[0-9a-f]{64}", receipt["request_payload_hash"]) is None
        or receipt.get("side") != "sell"
        or receipt.get("asset_code") != asset_code
        or type(receipt_replayed) is not bool
        or receipt_replayed is not response["replayed"]
    ):
        return False
    receipt_quantity = _finite_decimal_string(receipt.get("quantity"))
    receipt_price = _finite_decimal_string(receipt.get("price"))
    if (
        receipt_quantity is None
        or not _is_ledger_storable_decimal(
            receipt_quantity,
            quantum=_CLOSE_SHARE_QUANTUM,
            exclusive_maximum=_CLOSE_MAX_SHARE_VALUE,
            allow_zero=False,
        )
        or receipt_quantity != Decimal(close_shares)
        or receipt_price is None
        or not _is_ledger_storable_decimal(
            receipt_price,
            quantum=_CLOSE_PRICE_QUANTUM,
            exclusive_maximum=_CLOSE_MAX_PRICE_VALUE,
            allow_zero=False,
        )
        or receipt_price != close_price
    ):
        return False
    receipt_amount = _finite_decimal_string(receipt.get("amount"))
    receipt_commission = _finite_decimal_string(receipt.get("commission"))
    receipt_transfer_fee = _finite_decimal_string(receipt.get("transfer_fee"))
    receipt_stamp_duty = _finite_decimal_string(receipt.get("stamp_duty"))
    receipt_slippage = _finite_decimal_string(receipt.get("slippage"))
    receipt_total_cost = _finite_decimal_string(receipt.get("total_cost"))
    if (
        receipt_amount is None
        or not _is_ledger_storable_decimal(
            receipt_amount,
            quantum=_CLOSE_MONEY_QUANTUM,
            exclusive_maximum=_CLOSE_MAX_MONEY_VALUE,
            allow_zero=False,
        )
        or receipt_commission is None
        or not _is_ledger_storable_decimal(
            receipt_commission,
            quantum=_CLOSE_MONEY_QUANTUM,
            exclusive_maximum=_CLOSE_MAX_MONEY_VALUE,
            allow_zero=True,
        )
        or receipt_transfer_fee is None
        or not _is_ledger_storable_decimal(
            receipt_transfer_fee,
            quantum=_CLOSE_MONEY_QUANTUM,
            exclusive_maximum=_CLOSE_MAX_MONEY_VALUE,
            allow_zero=True,
        )
        or receipt_stamp_duty is None
        or not _is_ledger_storable_decimal(
            receipt_stamp_duty,
            quantum=_CLOSE_MONEY_QUANTUM,
            exclusive_maximum=_CLOSE_MAX_MONEY_VALUE,
            allow_zero=True,
        )
        or receipt_slippage is None
        or not _is_ledger_storable_decimal(
            receipt_slippage,
            quantum=_CLOSE_MONEY_QUANTUM,
            exclusive_maximum=_CLOSE_MAX_MONEY_VALUE,
            allow_zero=True,
        )
        or receipt_total_cost is None
        or not _is_ledger_storable_decimal(
            receipt_total_cost,
            quantum=_CLOSE_MONEY_QUANTUM,
            exclusive_maximum=_CLOSE_MAX_MONEY_VALUE,
            allow_zero=True,
        )
    ):
        return False
    try:
        with localcontext() as context:
            context.prec = 256
            expected_amount = (Decimal(close_shares) * close_price).quantize(
                Decimal("0.01"), rounding=ROUND_HALF_EVEN
            )
    except (DecimalException, OverflowError, ValueError):
        return False
    if receipt_amount != expected_amount:
        return False
    if any(
        value < 0
        for value in (
            receipt_commission,
            receipt_transfer_fee,
            receipt_stamp_duty,
            receipt_slippage,
        )
    ):
        return False
    try:
        with localcontext() as context:
            context.prec = 256
            expected_total_cost = (
                receipt_commission + receipt_transfer_fee + receipt_stamp_duty + receipt_slippage
            )
    except (DecimalException, OverflowError, ValueError):
        return False
    if receipt_total_cost != expected_total_cost:
        return False
    for field in ("amount", "commission", "slippage", "total_cost"):
        trade_value = _finite_decimal_string(trade.get(field))
        receipt_value = _finite_decimal_string(receipt.get(field))
        if trade_value is None or receipt_value is None or trade_value != receipt_value:
            return False
    if receipt.get("settlement_status") is not None:
        return False
    release_date = receipt.get("settlement_release_date")
    if release_date is not None:
        return False
    return True


class SimulatedTradingModule(BaseModule):
    """
    统一账户交易模块（保留 simulated_trading 名称兼容）。

    提供账户管理、交易执行、绩效查询等功能。
    """

    def __init__(self, client: Any) -> None:
        """
        初始化 SimulatedTrading 模块

        Args:
            client: AgomTradePro 客户端实例
        """
        # Canonical simulated trading endpoints are served under /api/simulated-trading/*.
        super().__init__(client, "/api/simulated-trading")
        self._fee_corrections: SimulatedFeeCorrectionsModule | None = None

    @property
    def fee_corrections(self) -> SimulatedFeeCorrectionsModule:
        """Return the owner-scoped simulated fee-correction SDK module."""

        if self._fee_corrections is None:
            self._fee_corrections = SimulatedFeeCorrectionsModule(self._client)
        return self._fee_corrections

    def list_accounts(
        self,
        status: str | None = None,
        account_type: str | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        """
        获取账户列表

        Args:
            status: 账户状态过滤（active/inactive/closed）
            account_type: 可选，real 或 simulated
            limit: 返回数量限制

        Returns:
            当前认证用户可访问的模拟账户列表

        Example:
            >>> client = AgomTradeProClient()
            >>> accounts = client.simulated_trading.list_accounts(status="active")
            >>> for account in accounts:
            ...     print(f"{account['name']}: {account['total_value']}")
        """
        params: dict[str, Any] = {"active_only": True, "limit": limit}
        if status is not None and status.lower() in {"inactive", "closed"}:
            params["active_only"] = False
        if account_type is not None:
            params["account_type"] = account_type

        response = self._get("accounts/", params=params)
        if isinstance(response, dict):
            return cast(list[dict[str, Any]], response.get("accounts", []))
        return cast(list[dict[str, Any]], response)

    def list_accounts_envelope(
        self,
        status: str | None = None,
        account_type: str | None = None,
        limit: int = 100,
    ) -> dict[str, Any]:
        """List accounts and preserve the API success/count/accounts envelope."""

        params: dict[str, Any] = {"active_only": True, "limit": limit}
        if status is not None and status.lower() in {"inactive", "closed"}:
            params["active_only"] = False
        if account_type is not None:
            params["account_type"] = account_type
        return self._get("accounts/", params=params)

    def get_account(self, account_id: int) -> dict[str, Any]:
        """
        获取单个模拟账户详情

        Args:
            account_id: 账户 ID

        Returns:
            账户详情

        Raises:
            NotFoundError: 当账户不存在时

        Example:
            >>> client = AgomTradeProClient()
            >>> account = client.simulated_trading.get_account(1)
            >>> print(f"账户名称: {account['name']}")
            >>> print(f"总市值: {account['total_value']}")
        """
        response = self._get(f"accounts/{account_id}/")
        if isinstance(response, dict):
            return cast(dict[str, Any], response.get("account", response))
        return cast(dict[str, Any], response)

    def delete_account(self, account_id: int) -> dict[str, Any]:
        """
        删除单个模拟账户。

        Args:
            account_id: 账户 ID

        Returns:
            删除结果
        """
        return self._delete(f"accounts/{account_id}/")

    def batch_delete_accounts(self, account_ids: list[int]) -> dict[str, Any]:
        """
        批量删除模拟账户。

        Args:
            account_ids: 账户 ID 列表

        Returns:
            批量删除结果
        """
        return self._post("accounts/batch-delete/", json={"account_ids": account_ids})

    def create_account(
        self,
        name: str,
        initial_capital: float,
        start_date: date | None = None,
        account_type: str = "simulated",
        max_position_pct: float = 20.0,
        stop_loss_pct: float | None = 10.0,
        commission_rate: float = 0.0003,
        slippage_rate: float = 0.001,
        *,
        idempotency_key: str,
    ) -> dict[str, Any]:
        """
        创建账户

        Args:
            name: 账户名称
            initial_capital: 初始资金
            start_date: 起始日期（当前 canonical API 不消费该字段，保留兼容）
            account_type: 账户类型，real 或 simulated
            max_position_pct: 单资产最大持仓比例
            stop_loss_pct: 止损比例
            commission_rate: 手续费率
            slippage_rate: 滑点率
            idempotency_key: 本次提交的稳定键，网络重试必须复用；新的创建使用新键。

        Returns:
            创建的账户信息

        Raises:
            ValidationError: 当参数验证失败时

        Example:
            >>> from datetime import date
            >>> client = AgomTradeProClient()
            >>> account = client.simulated_trading.create_account(
            ...     name="测试账户",
            ...     initial_capital=1000000.0,
            ...     start_date=date(2024, 1, 1),
            ...     idempotency_key="account-create-example-1"
            ... )
            >>> print(f"账户已创建: {account['id']}")
        """
        data: dict[str, Any] = {
            "account_name": name,
            "account_type": account_type,
            "initial_capital": initial_capital,
            "max_position_pct": max_position_pct,
            "stop_loss_pct": stop_loss_pct,
            "commission_rate": commission_rate,
            "slippage_rate": slippage_rate,
        }

        response = self._post("accounts/", json=data, idempotency_key=idempotency_key)
        if isinstance(response, dict):
            return cast(dict[str, Any], response.get("account", response))
        return cast(dict[str, Any], response)

    def execute_trade(
        self,
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
        执行交易

        Args:
            account_id: 账户 ID
            asset_code: 资产代码
            side: 交易方向（buy/sell）
            quantity: 数量
            price: 用户明确输入的价格；不支持省略价格的市价单。
            asset_type: 明确的资产类型，交由服务端校验。
            idempotency_key: 本次操作的稳定键；确认、重试须复用，新交易使用新键。

        Returns:
            交易执行结果

        Raises:
            ValidationError: 当参数验证失败时
            NotFoundError: 当账户不存在时

        Example:
            >>> client = AgomTradeProClient()
            >>> result = client.simulated_trading.execute_trade(
            ...     account_id=1,
            ...     asset_code="600000.SH",
            ...     side="buy",
            ...     quantity=1000,
            ...     price=10.5,
            ...     asset_type="equity",
            ...     idempotency_key="manual-trade-example-1"
            ... )
            >>> print(f"交易已执行: {result['trade']['trade_id']}")
        """
        if (
            type(idempotency_key) is not str
            or not idempotency_key
            or len(idempotency_key) > 128
            or any(character.isspace() for character in idempotency_key)
        ):
            raise ValidationError("A stable operation key of at most 128 characters is required.")
        if type(asset_type) is not str or not asset_type or asset_type.strip() != asset_type:
            raise ValidationError("An explicit asset type is required.")
        if price is None:
            raise ValidationError("An explicit manual trade price is required.")
        data: dict[str, Any] = {
            "asset_code": asset_code,
            "asset_name": asset_code,
            "asset_type": asset_type,
            "action": side.lower(),
            "quantity": quantity,
            "reason": "Manual simulated trade",
        }

        data["price"] = price
        return self._post(
            f"accounts/{account_id}/trade/", json=data, idempotency_key=idempotency_key
        )

    def get_positions(
        self,
        account_id: int,
        asset_code: str | None = None,
    ) -> list[dict[str, Any]]:
        """
        获取模拟账户持仓

        Args:
            account_id: 账户 ID
            asset_code: 资产代码过滤（可选）

        Returns:
            持仓列表

        Example:
            >>> client = AgomTradeProClient()
            >>> positions = client.simulated_trading.get_positions(account_id=1)
            >>> for pos in positions:
            ...     print(f"{pos['asset_code']}: {pos['quantity']}")
        """
        response = self._get(f"accounts/{account_id}/positions/")
        if isinstance(response, dict):
            positions = response.get("positions", [])
            if asset_code is not None:
                positions = [p for p in positions if p.get("asset_code") == asset_code]
            return cast(list[dict[str, Any]], positions)
        return cast(list[dict[str, Any]], response)

    def get_performance(
        self,
        account_id: int,
        start_date: date | None = None,
        end_date: date | None = None,
    ) -> dict[str, Any]:
        """
        获取模拟账户绩效

        Args:
            account_id: 账户 ID
            start_date: 开始日期（可选）
            end_date: 结束日期（可选）

        Returns:
            绩效数据，包括收益率、最大回撤、夏普比率等

        Example:
            >>> client = AgomTradeProClient()
            >>> perf = client.simulated_trading.get_performance(account_id=1)
            >>> print(f"总收益: {perf['total_return']:.2%}")
            >>> print(f"年化收益: {perf['annual_return']:.2%}")
        """
        response = self._get(f"accounts/{account_id}/performance/")
        if isinstance(response, dict):
            return cast(dict[str, Any], response.get("performance", response))
        return cast(dict[str, Any], response)

    def get_trade_history(
        self,
        account_id: int,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        """
        获取交易历史

        Args:
            account_id: 账户 ID
            limit: 返回数量限制

        Returns:
            交易历史列表

        Example:
            >>> client = AgomTradeProClient()
            >>> trades = client.simulated_trading.get_trade_history(account_id=1)
            >>> for trade in trades:
            ...     print(f"{trade['created_at']}: {trade['side']} {trade['asset_code']}")
        """
        params: dict[str, Any] = {"limit": limit}
        response = self._get(f"accounts/{account_id}/trades/", params=params)
        results = response.get("results", response)
        return cast(list[dict[str, Any]], results)

    def close_position(
        self,
        account_id: int,
        asset_code: str,
        close_shares: int,
        close_price: str,
        *,
        idempotency_key: str,
    ) -> dict[str, Any]:
        """Submit one exact simulated SELL close request.

        Args:
            account_id: 账户 ID
            asset_code: 资产代码
            close_shares: 用户明确输入的整数卖出数量。
            close_price: 用户明确输入的十进制字符串成交价；原字符串原样发送。
            idempotency_key: 单次操作的稳定键；超时或结果未知后必须原样复用。

        Returns:
            immutable trade、执行回执与 replayed 标志。

        Raises:
            ValidationError: 当账户、数量、价格或稳定操作键不合法时。

        Example:
            >>> client = AgomTradeProClient()
            >>> result = client.simulated_trading.close_position(
            ...     account_id=1,
            ...     asset_code="000001.SH",
            ...     close_shares=100,
            ...     close_price="12.3400",
            ...     idempotency_key="close-operation-1",
            ... )
            >>> print(f"已成交: {result['trade']['trade_id']}")
        """
        if type(account_id) is not int or account_id <= 0:
            raise ValidationError("A positive exact account ID is required.")
        if type(asset_code) is not str or not asset_code or asset_code.strip() != asset_code:
            raise ValidationError("A canonical asset code is required.")
        if type(close_shares) is not int or close_shares <= 0:
            raise ValidationError("A positive whole-share close quantity is required.")
        if close_shares >= int(_CLOSE_MAX_SHARE_VALUE):
            raise ValidationError("The close quantity exceeds the ledger storage range.")
        if (
            type(idempotency_key) is not str
            or not idempotency_key
            or len(idempotency_key) > 128
            or any(character.isspace() for character in idempotency_key)
        ):
            raise ValidationError("A stable operation key of at most 128 characters is required.")
        if (
            type(close_price) is not str
            or not _CLOSE_PRICE_PATTERN.fullmatch(close_price)
            or len(close_price.replace(".", "")) > 12
        ):
            raise ValidationError("The close price must be an exact decimal string.")
        try:
            parsed_close_price = Decimal(close_price)
        except (DecimalException, ValueError) as exc:
            raise ValidationError("The close price must be a valid decimal string.") from exc
        if not parsed_close_price.is_finite() or parsed_close_price < Decimal("0.01"):
            raise ValidationError("The close price must be at least 0.01.")
        if not _is_ledger_storable_decimal(
            parsed_close_price,
            quantum=_CLOSE_PRICE_QUANTUM,
            exclusive_maximum=_CLOSE_MAX_PRICE_VALUE,
            allow_zero=False,
        ):
            raise ValidationError("The close price exceeds the ledger storage range.")

        data: dict[str, Any] = {
            "asset_code": asset_code,
            "close_shares": close_shares,
            "close_price": close_price,
        }

        try:
            response = self._client.post_once(
                f"{self._prefix}/accounts/{account_id}/positions/close/",
                json=data,
                idempotency_key=idempotency_key,
            )
        except sdk_exceptions.TimeoutError:
            raise ExecutionOutcomeUnknownError() from None
        except AgomTradeProAPIError as exc:
            if isinstance(exc.__cause__, RequestException):
                raise ExecutionOutcomeUnknownError() from None
            raise
        try:
            has_valid_response = _has_valid_close_response(
                response,
                account_id=account_id,
                asset_code=asset_code,
                close_shares=close_shares,
                close_price=parsed_close_price,
                idempotency_key=idempotency_key,
            )
        except (DecimalException, OverflowError, ValueError):
            has_valid_response = False
        if not has_valid_response:
            raise ExecutionOutcomeUnknownError()
        return response

    def reset_account(
        self,
        account_id: int,
        new_initial_capital: float | None = None,
    ) -> dict[str, Any]:
        """
        重置模拟账户

        Args:
            account_id: 账户 ID
            new_initial_capital: 新的初始资金（None 表示使用原值）

        Returns:
            重置后的账户信息

        Example:
            >>> client = AgomTradeProClient()
            >>> account = client.simulated_trading.reset_account(account_id=1)
            >>> print(f"账户已重置")
        """
        data: dict[str, Any] = {}
        if new_initial_capital is not None:
            data["new_initial_capital"] = new_initial_capital

        return self._post(f"accounts/{account_id}/reset/", json=data)

    def run_auto_trading(
        self,
        trade_date: date | None = None,
        account_ids: list[int] | None = None,
        *,
        idempotency_key: str,
    ) -> dict[str, Any]:
        """
        手动触发模拟盘自动交易。

        Args:
            trade_date: 交易日期，None 表示今天
            account_ids: 指定本人适格模拟账户；None 由服务端选择本人活跃且
                启用自动交易的模拟账户，[] 表示空范围，不执行交易。
            idempotency_key: 调用方持有的稳定操作键；同一逻辑操作重试必须复用，
                新操作必须使用新键。

        Returns:
            服务端原始业务结果；以 outcome 判断 success/partial/noop/blocked/failed。
            confirmed_trade_count 保留已确认成交，stored 为 None 表示写入数量不明。

        Raises:
            ValidationError: 操作键缺失或格式无效时。
        """
        if (
            type(idempotency_key) is not str
            or not idempotency_key
            or len(idempotency_key) > 128
            or any(character.isspace() for character in idempotency_key)
        ):
            raise ValidationError("A stable operation key of at most 128 characters is required.")

        data: dict[str, Any] = {}
        if trade_date is not None:
            data["trade_date"] = trade_date.isoformat()
        if account_ids is not None:
            data["account_ids"] = account_ids
        return self._post(
            "auto-trading/run/",
            json=data,
            idempotency_key=idempotency_key,
        )

    def run_daily_inspection(
        self,
        account_id: int,
        strategy_id: int | None = None,
        inspection_date: date | None = None,
        auto_create_proposal: bool = False,
        *,
        temporary_target_weights: str | None = None,
    ) -> dict[str, Any]:
        """Run a daily inspection, optionally forwarding an exact temporary target."""
        data: dict[str, Any] = {}
        if strategy_id is not None:
            data["strategy_id"] = strategy_id
        if inspection_date is not None:
            data["inspection_date"] = inspection_date.isoformat()
        if auto_create_proposal:
            data["auto_create_proposal"] = auto_create_proposal
        if temporary_target_weights is not None:
            data["temporary_target_weights"] = temporary_target_weights
        return self._post(f"accounts/{account_id}/inspections/run/", json=data)

    def list_daily_inspections(
        self,
        account_id: int,
        limit: int = 20,
        inspection_date: date | None = None,
    ) -> dict[str, Any]:
        """
        查询账户日更巡检历史报告。
        """
        params: dict[str, Any] = {"limit": limit}
        if inspection_date is not None:
            params["inspection_date"] = inspection_date.isoformat()
        return self._get(f"accounts/{account_id}/inspections/", params=params)
