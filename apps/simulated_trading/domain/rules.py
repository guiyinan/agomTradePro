"""
模拟盘交易规则

Domain层业务规则：
- 仓位管理规则
- 交易约束规则
- 纯Python实现，无外部依赖
"""

from .entities import Position, SimulatedAccount


class PositionSizingRule:
    """仓位管理规则"""

    @staticmethod
    def calculate_buy_quantity(
        account: SimulatedAccount,
        asset_price: float,
        asset_score: float,
        existing_positions: list[Position]
    ) -> int:
        """
        计算买入数量

        策略:
        1. 单资产持仓不超过 max_position_pct
        2. 总持仓不超过 max_total_position_pct
        3. 按评分分配权重(高分多买)

        Args:
            account: 模拟账户
            asset_price: 资产价格(元)
            asset_score: 资产评分(0-100)
            existing_positions: 现有持仓列表

        Returns:
            买入数量(100的倍数)
        """
        # 1. 计算可用资金
        available_cash = account.available_cash_for_buy()

        # 2. 计算单资产最大持仓金额
        max_single_value = account.max_position_value()

        # 3. 按评分分配(评分越高,买得越多)
        # 评分范围 60-100, 映射到 0.6-1.0 的权重
        weight = max(0.6, min(1.0, asset_score / 100.0))
        target_value = max_single_value * weight

        # 4. 不能超过可用资金
        target_value = min(target_value, available_cash)

        # 5. 计算数量(向下取整到100的倍数,A股最小单位100股)
        quantity = int(target_value / asset_price / 100) * 100

        return quantity

    @staticmethod
    def should_sell_position(
        position: Position,
        signal_valid: bool,
        regime_match: bool,
        stop_loss_pct: float | None
    ) -> bool:
        """
        判断是否应该卖出持仓

        卖出条件(满足任一):
        1. 信号失效
        2. Regime不匹配(进入禁投池)
        3. 触发止损

        Args:
            position: 持仓信息
            signal_valid: 信号是否有效
            regime_match: Regime是否匹配
            stop_loss_pct: 止损比例(%)

        Returns:
            是否应该卖出
        """
        # 条件1: 信号失效
        if not signal_valid:
            return True

        # 条件2: Regime不匹配
        if not regime_match:
            return True

        # 条件3: 止损
        if stop_loss_pct and position.unrealized_pnl_pct < -stop_loss_pct:
            return True

        return False


class TradingConstraintRule:
    """交易约束规则"""

    @staticmethod
    def validate_buy_order(
        account: SimulatedAccount,
        asset_code: str,
        quantity: int,
        price: float,
        current_position_value: float = 0.0
    ) -> tuple[bool, str]:
        """
        验证买入订单

        Args:
            account: 模拟账户
            asset_code: 资产代码
            quantity: 买入数量
            price: 买入价格
            current_position_value: 当前该资产已持仓市值(元)

        Returns:
            (是否通过, 失败原因)
        """
        # 1. 检查账户是否启用自动交易
        if not account.auto_trading_enabled:
            return False, "自动交易未启用"

        # 2. 检查账户是否激活
        if not account.is_active:
            return False, "账户未激活"

        # 3. 计算所需金额
        amount = quantity * price
        commission = amount * account.commission_rate
        slippage = amount * account.slippage_rate
        total_needed = amount + commission + slippage

        # 4. 检查现金是否足够
        if total_needed > account.current_cash:
            return False, f"现金不足(需要{total_needed:.2f},可用{account.current_cash:.2f})"

        # 5. 检查是否为100的倍数(A股)
        if quantity % 100 != 0:
            return False, "数量必须为100的倍数"

        # 6. 检查数量是否大于0
        if quantity <= 0:
            return False, "买入数量必须大于0"

        # 7. 检查单资产最大持仓比例
        max_single_value = account.max_position_value()
        new_position_value = current_position_value + amount
        if new_position_value > max_single_value:
            return (
                False,
                f"超过最大持仓比例(上限{max_single_value:.2f},买入后{new_position_value:.2f})"
            )

        return True, ""

    @staticmethod
    def validate_sell_order(
        position: Position,
        quantity: int
    ) -> tuple[bool, str]:
        """
        验证卖出订单

        Args:
            position: 持仓信息
            quantity: 卖出数量

        Returns:
            (是否通过, 失败原因)
        """
        # 1. 检查持仓数量
        if quantity > position.available_quantity:
            return False, f"可卖数量不足(需要{quantity},可用{position.available_quantity})"

        # 2. 检查是否为100的倍数
        if quantity % 100 != 0:
            return False, "数量必须为100的倍数"

        # 3. 检查数量是否大于0
        if quantity <= 0:
            return False, "卖出数量必须大于0"

        return True, ""
