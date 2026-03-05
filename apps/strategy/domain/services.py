"""
Domain 层服务

遵循项目架构约束：
- 只使用 Python 标准库
- 不依赖 Django 或其他外部库
- 实现纯算法和业务规则
"""
from typing import Dict, Tuple, Optional

from apps.strategy.domain.entities import (
    OrderStatus,
    OrderEvent,
)


# ========================================================================
# 订单状态机
# ========================================================================

# 状态转换表：(当前状态, 事件) -> 新状态
_ORDER_TRANSITIONS: Dict[Tuple[OrderStatus, OrderEvent], OrderStatus] = {
    # DRAFT 状态的转换
    (OrderStatus.DRAFT, OrderEvent.SUBMIT): OrderStatus.PENDING_APPROVAL,

    # PENDING_APPROVAL 状态的转换
    (OrderStatus.PENDING_APPROVAL, OrderEvent.APPROVE): OrderStatus.APPROVED,
    (OrderStatus.PENDING_APPROVAL, OrderEvent.REJECT): OrderStatus.REJECTED,

    # APPROVED 状态的转换
    (OrderStatus.APPROVED, OrderEvent.SEND): OrderStatus.SENT,
    (OrderStatus.APPROVED, OrderEvent.CANCEL): OrderStatus.CANCELED,

    # SENT 状态的转换
    (OrderStatus.SENT, OrderEvent.PARTIAL_FILL): OrderStatus.PARTIAL_FILLED,
    (OrderStatus.SENT, OrderEvent.FILL): OrderStatus.FILLED,
    (OrderStatus.SENT, OrderEvent.CANCEL): OrderStatus.CANCELED,
    (OrderStatus.SENT, OrderEvent.FAIL): OrderStatus.FAILED,

    # PARTIAL_FILLED 状态的转换
    (OrderStatus.PARTIAL_FILLED, OrderEvent.FILL): OrderStatus.FILLED,
    (OrderStatus.PARTIAL_FILLED, OrderEvent.CANCEL): OrderStatus.CANCELED,
}


class OrderStateMachine:
    """订单状态机"""

    # 定义允许的终态
    TERMINAL_STATES = {
        OrderStatus.FILLED,
        OrderStatus.CANCELED,
        OrderStatus.REJECTED,
        OrderStatus.FAILED,
    }

    @classmethod
    def can_transition(
        cls,
        from_status: OrderStatus,
        event: OrderEvent
    ) -> bool:
        """
        检查是否可以从当前状态通过指定事件转换

        Args:
            from_status: 当前状态
            event: 触发事件

        Returns:
            是否允许转换
        """
        return (from_status, event) in _ORDER_TRANSITIONS

    @classmethod
    def transition(
        cls,
        from_status: OrderStatus,
        event: OrderEvent
    ) -> OrderStatus:
        """
        执行状态转换

        Args:
            from_status: 当前状态
            event: 触发事件

        Returns:
            新状态

        Raises:
            ValueError: 如果转换不允许
        """
        key = (from_status, event)
        if key not in _ORDER_TRANSITIONS:
            raise ValueError(
                f"Invalid transition: cannot apply {event.value} to status {from_status.value}"
            )
        return _ORDER_TRANSITIONS[key]

    @classmethod
    def is_terminal(cls, status: OrderStatus) -> bool:
        """
        检查是否是终态

        Args:
            status: 订单状态

        Returns:
            是否是终态
        """
        return status in cls.TERMINAL_STATES

    @classmethod
    def get_valid_events(cls, status: OrderStatus) -> list[OrderEvent]:
        """
        获取当前状态可以触发的事件

        Args:
            status: 订单状态

        Returns:
            可触发的事件列表
        """
        return [
            event for (s, event) in _ORDER_TRANSITIONS.keys()
            if s == status
        ]

    @classmethod
    def validate_transition_path(cls, path: list[Tuple[OrderStatus, OrderEvent]]) -> bool:
        """
        验证状态转换路径是否有效

        Args:
            path: 状态转换路径 [(status, event), ...]

        Returns:
            路径是否有效
        """
        if not path:
            return False

        current_status = path[0][0]
        for _, event in path:
            if not cls.can_transition(current_status, event):
                return False
            current_status = cls.transition(current_status, event)

        return True


# ========================================================================
# 决策策略引擎
# ========================================================================

class DecisionPolicyEngine:
    """
    决策策略引擎 - 决定"何时下单"

    输入：
    - 信号（强度/方向/置信度）
    - 市场状态（regime/波动率）
    - 账户状态（现金、持仓、当日交易次数）

    输出：
    - ALLOW / DENY / WATCH
    - reason_codes（可审计）
    - valid_until（触发有效期）
    """

    # 决策原因码
    REASON_CODES = {
        # 允许原因
        'SIGNAL_STRONG': '信号强度足够',
        'REGIME_ALIGNED': 'Regime 对齐',
        'LIQUIDITY_OK': '流动性充足',

        # 拒绝原因
        'SIGNAL_WEAK': '信号强度不足',
        'REGIME_MISMATCH': 'Regime 不匹配',
        'DAILY_LOSS_LIMIT': '触发日亏损限制',
        'DAILY_TRADE_LIMIT': '触发日交易次数限制',
        'POSITION_LIMIT': '持仓比例超限',
        'LOW_LIQUIDITY': '流动性不足',
        'VOLATILITY_TOO_HIGH': '波动率过高',

        # 观察原因
        'LOW_CONFIDENCE': '置信度较低，需人工确认',
        'UNUSUAL_VOLATILITY': '异常波动，需人工确认',
    }

    def __init__(
        self,
        signal_threshold: float = 0.6,
        confidence_threshold: float = 0.7,
        regime_alignment_required: bool = True,
        max_daily_loss_pct: float = 5.0,
        max_daily_trades: int = 10,
        max_volatility: float = 3.0,
    ):
        """
        初始化决策引擎

        Args:
            signal_threshold: 信号强度阈值
            confidence_threshold: 置信度阈值
            regime_alignment_required: 是否要求 Regime 对齐
            max_daily_loss_pct: 日最大亏损百分比
            max_daily_trades: 日最大交易次数
            max_volatility: 最大波动率（标准差倍数）
        """
        self.signal_threshold = signal_threshold
        self.confidence_threshold = confidence_threshold
        self.regime_alignment_required = regime_alignment_required
        self.max_daily_loss_pct = max_daily_loss_pct
        self.max_daily_trades = max_daily_trades
        self.max_volatility = max_volatility

    def evaluate(
        self,
        signal_strength: float,
        signal_direction: str,
        signal_confidence: float,
        regime: str,
        regime_confidence: float,
        daily_pnl_pct: float,
        daily_trade_count: int,
        volatility_z: Optional[float] = None,
        target_regime: Optional[str] = None,
    ) -> Tuple[str, list[str], str, Optional[float]]:
        """
        评估是否应该执行交易

        Args:
            signal_strength: 信号强度 (0-1)
            signal_direction: 信号方向 (bullish/bearish/neutral)
            signal_confidence: 信号置信度 (0-1)
            regime: 当前 Regime
            regime_confidence: Regime 置信度
            daily_pnl_pct: 当日盈亏百分比
            daily_trade_count: 当日交易次数
            volatility_z: 波动率 Z 分数
            target_regime: 目标 Regime（如果信号针对特定 Regime）

        Returns:
            (action, reason_codes, reason_text, valid_until)
            - action: allow/deny/watch
            - reason_codes: 原因码列表
            - reason_text: 人类可读的原因描述
            - valid_until: 决策有效期（秒）
        """
        from datetime import datetime, timezone, timedelta
        from apps.strategy.domain.entities import DecisionAction

        reason_codes: list[str] = []

        # 1. 检查日亏损限制
        if daily_pnl_pct <= -self.max_daily_loss_pct:
            reason_codes.append('DAILY_LOSS_LIMIT')
            return (
                DecisionAction.DENY.value,
                reason_codes,
                self.REASON_CODES['DAILY_LOSS_LIMIT'],
                None
            )

        # 2. 检查日交易次数限制
        if daily_trade_count >= self.max_daily_trades:
            reason_codes.append('DAILY_TRADE_LIMIT')
            return (
                DecisionAction.DENY.value,
                reason_codes,
                self.REASON_CODES['DAILY_TRADE_LIMIT'],
                None
            )

        # 3. 检查波动率
        if volatility_z is not None and volatility_z > self.max_volatility:
            reason_codes.append('VOLATILITY_TOO_HIGH')
            return (
                DecisionAction.DENY.value,
                reason_codes,
                self.REASON_CODES['VOLATILITY_TOO_HIGH'],
                None
            )

        # 4. 检查信号强度
        if signal_strength < self.signal_threshold:
            reason_codes.append('SIGNAL_WEAK')
            return (
                DecisionAction.DENY.value,
                reason_codes,
                self.REASON_CODES['SIGNAL_WEAK'],
                None
            )

        # 5. 检查 Regime 对齐（如果要求）
        if self.regime_alignment_required and target_regime:
            if regime != target_regime:
                reason_codes.append('REGIME_MISMATCH')
                return (
                    DecisionAction.DENY.value,
                    reason_codes,
                    self.REASON_CODES['REGIME_MISMATCH'],
                    None
                )

        # 6. 检查置信度 - 决定是 ALLOW 还是 WATCH
        if signal_confidence < self.confidence_threshold:
            reason_codes.append('LOW_CONFIDENCE')
            return (
                DecisionAction.WATCH.value,
                reason_codes,
                self.REASON_CODES['LOW_CONFIDENCE'],
                300  # 5分钟有效期
            )

        # 7. 检查 Regime 置信度
        if regime_confidence < 0.5:
            reason_codes.append('LOW_CONFIDENCE')
            return (
                DecisionAction.WATCH.value,
                reason_codes,
                f"{self.REASON_CODES['LOW_CONFIDENCE']} (Regime 置信度: {regime_confidence:.2f})",
                300
            )

        # 所有检查通过，允许交易
        reason_codes.append('SIGNAL_STRONG')
        if self.regime_alignment_required:
            reason_codes.append('REGIME_ALIGNED')

        reason_text = f"信号强度 {signal_strength:.2f}, 置信度 {signal_confidence:.2f}"
        valid_until = 3600  # 1小时有效期

        return (
            DecisionAction.ALLOW.value,
            reason_codes,
            reason_text,
            valid_until
        )


# ========================================================================
# 仓位引擎
# ========================================================================

class SizingEngine:
    """
    仓位引擎 - 决定"下多少单"

    支持多种仓位计算方法：
    - fixed_fraction: 固定风险比例
    - atr_risk: 基于 ATR 的风险仓位
    """

    def __init__(
        self,
        default_method: str = 'fixed_fraction',
        risk_per_trade_pct: float = 1.0,
        max_position_pct: float = 20.0,
        min_qty: int = 1,
    ):
        """
        初始化仓位引擎

        Args:
            default_method: 默认计算方法
            risk_per_trade_pct: 每笔交易风险比例 (%)
            max_position_pct: 单资产最大持仓比例 (%)
            min_qty: 最小交易数量
        """
        self.default_method = default_method
        self.risk_per_trade_pct = risk_per_trade_pct
        self.max_position_pct = max_position_pct
        self.min_qty = min_qty

    def calculate(
        self,
        method: str,
        account_equity: float,
        current_price: float,
        stop_loss_price: Optional[float] = None,
        atr: Optional[float] = None,
        current_position_value: float = 0.0,
        atr_risk_multiplier: float = 2.0,
    ) -> Tuple[float, int, float, str, str]:
        """
        计算仓位

        Args:
            method: 计算方法 (fixed_fraction, atr_risk)
            account_equity: 账户权益
            current_price: 当前价格
            stop_loss_price: 止损价
            atr: ATR 值
            current_position_value: 当前持仓市值
            atr_risk_multiplier: ATR 风险倍数

        Returns:
            (target_notional, qty, expected_risk_pct, sizing_method, sizing_explain)
        """
        if method == 'fixed_fraction':
            return self._fixed_fraction(
                account_equity, current_price, stop_loss_price
            )
        elif method == 'atr_risk':
            return self._atr_risk(
                account_equity, current_price, atr, atr_risk_multiplier
            )
        else:
            # 默认使用固定比例
            return self._fixed_fraction(
                account_equity, current_price, stop_loss_price
            )

    def _fixed_fraction(
        self,
        account_equity: float,
        current_price: float,
        stop_loss_price: Optional[float],
    ) -> Tuple[float, int, float, str, str]:
        """
        固定风险比例仓位计算

        公式: qty = (equity * risk_pct) / |entry - stop_loss|

        Args:
            account_equity: 账户权益
            current_price: 当前价格
            stop_loss_price: 止损价

        Returns:
            (target_notional, qty, expected_risk_pct, sizing_method, sizing_explain)
        """
        # 计算最大目标名义金额
        max_notional = account_equity * self.max_position_pct / 100

        # 计算基于风险的仓位
        if stop_loss_price and stop_loss_price != current_price:
            # 有止损价时，根据风险计算仓位
            risk_per_share = abs(current_price - stop_loss_price)
            risk_amount = account_equity * self.risk_per_trade_pct / 100
            risk_based_qty = int(risk_amount / risk_per_share)

            # 限制在最大持仓内
            qty = min(risk_based_qty, int(max_notional / current_price))
            expected_risk_pct = self.risk_per_trade_pct

            sizing_explain = (
                f"固定风险比例: 权益 {account_equity:.0f} × {self.risk_per_trade_pct}% / "
                f"风险 {risk_per_share:.2f} = {risk_based_qty} 股"
            )
        else:
            # 无止损价时，使用最大持仓比例
            qty = int(max_notional / current_price)
            expected_risk_pct = self.max_position_pct

            sizing_explain = (
                f"无止损价，使用最大持仓: 权益 {account_equity:.0f} × {self.max_position_pct}% = "
                f"{max_notional:.0f} / {current_price:.2f} = {qty} 股"
            )

        # 确保最小数量
        qty = max(qty, self.min_qty)
        target_notional = qty * current_price

        return target_notional, qty, expected_risk_pct, 'fixed_fraction', sizing_explain

    def _atr_risk(
        self,
        account_equity: float,
        current_price: float,
        atr: Optional[float],
        atr_risk_multiplier: float = 2.0,
    ) -> Tuple[float, int, float, str, str]:
        """
        基于 ATR 的风险仓位计算

        公式: qty = (equity * risk_pct) / (atr * multiplier)

        Args:
            account_equity: 账户权益
            current_price: 当前价格
            atr: ATR 值
            atr_risk_multiplier: ATR 风险倍数

        Returns:
            (target_notional, qty, expected_risk_pct, sizing_method, sizing_explain)
        """
        if atr is None or atr <= 0:
            # ATR 无效时回退到固定比例
            return self._fixed_fraction(account_equity, current_price, None)

        # 计算最大目标名义金额
        max_notional = account_equity * self.max_position_pct / 100

        # 计算基于 ATR 的仓位
        risk_per_share = atr * atr_risk_multiplier
        risk_amount = account_equity * self.risk_per_trade_pct / 100
        risk_based_qty = int(risk_amount / risk_per_share)

        # 限制在最大持仓内
        qty = min(risk_based_qty, int(max_notional / current_price))
        qty = max(qty, self.min_qty)

        target_notional = qty * current_price
        expected_risk_pct = (risk_per_share * qty / account_equity) * 100

        sizing_explain = (
            f"ATR 风险仓位: 权益 {account_equity:.0f} × {self.risk_per_trade_pct}% / "
            f"(ATR {atr:.2f} × {atr_risk_multiplier}) = {risk_based_qty} 股"
        )

        return target_notional, qty, expected_risk_pct, 'atr_risk', sizing_explain


# ========================================================================
# 预交易风控门
# ========================================================================

class PreTradeRiskGate:
    """
    预交易风控门 - 硬风控规则

    在下单前执行硬性风控检查：
    - 单标的仓位上限
    - 单日最大交易次数
    - 单日最大亏损阈值
    - 流动性检查
    """

    def __init__(
        self,
        max_single_position_pct: float = 20.0,
        max_daily_trades: int = 10,
        max_daily_loss_pct: float = 5.0,
        min_volume: int = 100000,  # 最小成交量
    ):
        """
        初始化风控门

        Args:
            max_single_position_pct: 单标的最大持仓比例
            max_daily_trades: 单日最大交易次数
            max_daily_loss_pct: 单日最大亏损比例
            min_volume: 最小成交量要求
        """
        self.max_single_position_pct = max_single_position_pct
        self.max_daily_trades = max_daily_trades
        self.max_daily_loss_pct = max_daily_loss_pct
        self.min_volume = min_volume

    def check(
        self,
        symbol: str,
        side: str,
        qty: int,
        price: float,
        account_equity: float,
        current_position_value: float,
        daily_trade_count: int,
        daily_pnl_pct: float,
        avg_volume: Optional[float] = None,
    ) -> Tuple[bool, list[str], list[str], dict]:
        """
        执行风控检查

        Args:
            symbol: 资产代码
            side: 买卖方向
            qty: 数量
            price: 价格
            account_equity: 账户权益
            current_position_value: 当前持仓市值
            daily_trade_count: 当日交易次数
            daily_pnl_pct: 当日盈亏比例
            avg_volume: 平均成交量

        Returns:
            (passed, violations, warnings, details)
            - passed: 是否通过
            - violations: 违规列表（阻止交易）
            - warnings: 警告列表（不阻止但需注意）
            - details: 检查详情
        """
        violations: list[str] = []
        warnings: list[str] = []
        details: dict = {}

        # 计算新订单的名义金额
        order_notional = qty * price

        # 1. 检查单标的仓位上限
        new_position_value = current_position_value + (order_notional if side == 'buy' else -order_notional)
        new_position_pct = (new_position_value / account_equity) * 100 if account_equity > 0 else 0

        details['position_check'] = {
            'current_position_pct': (current_position_value / account_equity * 100) if account_equity > 0 else 0,
            'new_position_pct': new_position_pct,
            'limit': self.max_single_position_pct,
        }

        if new_position_pct > self.max_single_position_pct:
            violations.append(
                f"单标的仓位超限: {new_position_pct:.1f}% > {self.max_single_position_pct}%"
            )

        # 2. 检查单日交易次数
        details['trade_count_check'] = {
            'current': daily_trade_count,
            'limit': self.max_daily_trades,
        }

        if daily_trade_count >= self.max_daily_trades:
            violations.append(
                f"单日交易次数超限: {daily_trade_count} >= {self.max_daily_trades}"
            )

        # 3. 检查单日亏损
        details['daily_loss_check'] = {
            'current_pnl_pct': daily_pnl_pct,
            'limit': -self.max_daily_loss_pct,
        }

        if daily_pnl_pct <= -self.max_daily_loss_pct:
            violations.append(
                f"触发日亏损限制: {daily_pnl_pct:.2f}% <= -{self.max_daily_loss_pct}%"
            )

        # 4. 检查流动性
        if avg_volume is not None:
            details['liquidity_check'] = {
                'avg_volume': avg_volume,
                'min_volume': self.min_volume,
            }

            if avg_volume < self.min_volume:
                violations.append(
                    f"流动性不足: 成交量 {avg_volume:.0f} < {self.min_volume}"
                )
        else:
            warnings.append("无法获取成交量数据，跳过流动性检查")

        # 5. 检查大单警告
        if order_notional > account_equity * 0.1:  # 超过权益 10%
            warnings.append(
                f"大单警告: 订单金额 {order_notional:.0f} > 权益 10%"
            )

        passed = len(violations) == 0
        return passed, violations, warnings, details
