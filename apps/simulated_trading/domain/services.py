"""
模拟盘领域服务

Domain层:
- 封装不依赖 Django 的持仓成本算法
- 统一买入成本和持仓成本摊销逻辑
- 统一账户业绩计算（TWR、MWR/XIRR、风险指标）
"""
import math
from datetime import date
from decimal import Decimal
from typing import List, Optional, Tuple


def _to_decimal(value: float | int | str | Decimal) -> Decimal:
    """统一 Decimal 转换，避免二进制浮点误差。"""
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


class PositionCostBasisService:
    """持仓成本服务。"""

    @staticmethod
    def calculate_lot_cost(
        quantity: int,
        price: float,
        commission: float,
        slippage: float,
    ) -> tuple[float, float]:
        """
        计算单笔买入的总成本与摊薄成本价。

        Returns:
            (avg_cost, total_cost)
        """
        if quantity <= 0:
            raise ValueError("quantity must be positive")

        gross_amount = _to_decimal(quantity) * _to_decimal(price)
        total_cost = gross_amount + _to_decimal(commission) + _to_decimal(slippage)
        avg_cost = total_cost / _to_decimal(quantity)
        return float(avg_cost), float(total_cost)

    @staticmethod
    def merge_position_cost(
        existing_quantity: int,
        existing_total_cost: float,
        added_quantity: int,
        added_total_cost: float,
    ) -> tuple[float, float]:
        """
        合并现有持仓和新增买入批次的成本。

        Returns:
            (avg_cost, total_cost)
        """
        new_quantity = existing_quantity + added_quantity
        if new_quantity <= 0:
            raise ValueError("merged quantity must be positive")

        new_total_cost = _to_decimal(existing_total_cost) + _to_decimal(added_total_cost)
        new_avg_cost = new_total_cost / _to_decimal(new_quantity)
        return float(new_avg_cost), float(new_total_cost)


# ============================================================================
# 账户业绩计算服务
# ============================================================================

def _safe_mean(values: List[float]) -> Optional[float]:
    """安全均值计算，空列表返回 None。"""
    if not values:
        return None
    return sum(values) / len(values)


def _safe_std(values: List[float]) -> Optional[float]:
    """安全标准差（总体），少于 2 个点返回 None。"""
    n = len(values)
    if n < 2:
        return None
    mean = sum(values) / n
    variance = sum((v - mean) ** 2 for v in values) / (n - 1)
    return math.sqrt(variance)


class PerformanceCalculatorService:
    """
    统一账户业绩计算服务（纯算法，不依赖任何外部库）

    所有方法均为静态方法，可在 Domain 层直接调用。
    口径固定如下（对应计划文档）：
      - TWR：按日链式收益，日收益 = (V_t - V_{t-1} - CF_t) / V_{t-1}
      - MWR/XIRR：以外部现金流和期末组合价值求解内部收益率
      - 年化：以 365 天为基准
      - 风险免费利率：3.0%（与现有 fund 模块保持一致）
    """

    RISK_FREE_RATE: float = 0.03  # 年化无风险利率（3%）
    TRADING_DAYS_PER_YEAR: int = 252

    # ------------------------------------------------------------------
    # TWR
    # ------------------------------------------------------------------

    @staticmethod
    def calculate_twr(
        daily_values: List[Tuple[date, float]],
        daily_cashflows: Optional[List[Tuple[date, float]]] = None,
    ) -> Optional[float]:
        """
        计算时间加权收益率（TWR，%）。

        Args:
            daily_values: [(date, total_value), ...] 按日期升序排列
            daily_cashflows: [(date, cashflow), ...] 当日外部现金流（正=入金）

        Returns:
            TWR (%) 或 None（数据不足）
        """
        if len(daily_values) < 2:
            return None

        cf_map: dict[date, float] = {}
        if daily_cashflows:
            for d, cf in daily_cashflows:
                cf_map[d] = cf_map.get(d, 0.0) + cf

        cumulative = 1.0
        for i in range(1, len(daily_values)):
            d_curr, v_curr = daily_values[i]
            _, v_prev = daily_values[i - 1]
            cf = cf_map.get(d_curr, 0.0)
            if v_prev <= 0:
                continue
            sub_period_return = (v_curr - v_prev - cf) / v_prev
            cumulative *= 1.0 + sub_period_return

        return (cumulative - 1.0) * 100.0

    @staticmethod
    def calculate_annualized_twr(twr_pct: float, days: int) -> Optional[float]:
        """
        将 TWR 年化（%）。

        Args:
            twr_pct: TWR (%)
            days: 统计区间天数（日历日）
        """
        if days <= 0:
            return None
        r = twr_pct / 100.0
        annualized = (1.0 + r) ** (365.0 / days) - 1.0
        return annualized * 100.0

    # ------------------------------------------------------------------
    # MWR / XIRR
    # ------------------------------------------------------------------

    @staticmethod
    def calculate_xirr(
        cashflows: List[Tuple[date, float]],
        terminal_value: float,
        terminal_date: date,
    ) -> Optional[float]:
        """
        计算资金加权收益率（XIRR，%）。

        使用 Newton-Raphson 迭代求解。

        Args:
            cashflows: [(date, amount), ...] 外部现金流（入金为正，出金为负）
            terminal_value: 期末组合总价值（作为一笔出金处理）
            terminal_date: 期末日期

        Returns:
            年化 XIRR (%) 或 None（无法收敛）
        """
        # 将期末价值视为负现金流（出金）
        all_flows: List[Tuple[date, float]] = list(cashflows) + [(terminal_date, -terminal_value)]
        if not all_flows:
            return None

        # 时间以年为单位（相对于第一笔现金流）
        t0 = all_flows[0][0]
        times = [(d - t0).days / 365.0 for d, _ in all_flows]
        amounts = [amt for _, amt in all_flows]

        def npv(rate: float) -> float:
            total = 0.0
            for t, cf in zip(times, amounts):
                denom = (1.0 + rate) ** t
                if denom == 0:
                    return float("inf")
                total += cf / denom
            return total

        def npv_derivative(rate: float) -> float:
            total = 0.0
            for t, cf in zip(times, amounts):
                denom = (1.0 + rate) ** (t + 1)
                if denom == 0:
                    return float("inf")
                total += -t * cf / denom
            return total

        rate = 0.1  # 初始猜测 10%
        for _ in range(200):
            f = npv(rate)
            fp = npv_derivative(rate)
            if fp == 0 or not math.isfinite(f) or not math.isfinite(fp):
                return None
            new_rate = rate - f / fp
            if abs(new_rate - rate) < 1e-8:
                return new_rate * 100.0
            rate = new_rate
            if rate <= -1.0:
                return None
        return None  # 未收敛

    # ------------------------------------------------------------------
    # 日收益率序列
    # ------------------------------------------------------------------

    @staticmethod
    def build_daily_returns(
        daily_values: List[Tuple[date, float]],
        daily_cashflows: Optional[List[Tuple[date, float]]] = None,
    ) -> List[float]:
        """
        构造日收益率序列（用于风险指标计算）。

        Returns:
            list of daily returns（小数，非百分比）
        """
        if len(daily_values) < 2:
            return []

        cf_map: dict[date, float] = {}
        if daily_cashflows:
            for d, cf in daily_cashflows:
                cf_map[d] = cf_map.get(d, 0.0) + cf

        returns: List[float] = []
        for i in range(1, len(daily_values)):
            d_curr, v_curr = daily_values[i]
            _, v_prev = daily_values[i - 1]
            cf = cf_map.get(d_curr, 0.0)
            if v_prev <= 0:
                continue
            r = (v_curr - v_prev - cf) / v_prev
            returns.append(r)
        return returns

    # ------------------------------------------------------------------
    # 风险指标
    # ------------------------------------------------------------------

    @staticmethod
    def calculate_max_drawdown(daily_values: List[Tuple[date, float]]) -> Optional[float]:
        """
        计算最大回撤（%，正数表示回撤幅度）。
        """
        if len(daily_values) < 2:
            return None
        peak = daily_values[0][1]
        max_dd = 0.0
        for _, v in daily_values[1:]:
            if v > peak:
                peak = v
            elif peak > 0:
                dd = (peak - v) / peak * 100.0
                if dd > max_dd:
                    max_dd = dd
        return max_dd

    @staticmethod
    def calculate_volatility(daily_returns: List[float]) -> Optional[float]:
        """
        年化波动率（%）。
        """
        std = _safe_std(daily_returns)
        if std is None:
            return None
        return std * math.sqrt(PerformanceCalculatorService.TRADING_DAYS_PER_YEAR) * 100.0

    @staticmethod
    def calculate_downside_volatility(daily_returns: List[float]) -> Optional[float]:
        """
        下行波动率（%），仅统计负收益日。
        """
        negatives = [r for r in daily_returns if r < 0]
        std = _safe_std(negatives)
        if std is None:
            return None
        return std * math.sqrt(PerformanceCalculatorService.TRADING_DAYS_PER_YEAR) * 100.0

    # ------------------------------------------------------------------
    # 风险调整后收益比率
    # ------------------------------------------------------------------

    @staticmethod
    def calculate_sharpe(annualized_return_pct: float, annualized_vol_pct: float) -> Optional[float]:
        """夏普比率（年化收益超过无风险利率之后除以年化波动率）。"""
        rf = PerformanceCalculatorService.RISK_FREE_RATE * 100.0
        if annualized_vol_pct <= 0:
            return None
        return (annualized_return_pct - rf) / annualized_vol_pct

    @staticmethod
    def calculate_sortino(annualized_return_pct: float, annualized_downside_vol_pct: float) -> Optional[float]:
        """索提诺比率。"""
        rf = PerformanceCalculatorService.RISK_FREE_RATE * 100.0
        if annualized_downside_vol_pct <= 0:
            return None
        return (annualized_return_pct - rf) / annualized_downside_vol_pct

    @staticmethod
    def calculate_calmar(annualized_return_pct: float, max_drawdown_pct: float) -> Optional[float]:
        """卡玛比率（年化收益 / 最大回撤）。"""
        if max_drawdown_pct <= 0:
            return None
        return annualized_return_pct / max_drawdown_pct

    # ------------------------------------------------------------------
    # 基准相关指标
    # ------------------------------------------------------------------

    @staticmethod
    def calculate_beta_alpha(
        portfolio_returns: List[float],
        benchmark_returns: List[float],
        annualized_portfolio_pct: float,
        annualized_benchmark_pct: float,
    ) -> Tuple[Optional[float], Optional[float]]:
        """
        计算 Beta 和 Alpha。

        Returns:
            (beta, alpha)
        """
        n = min(len(portfolio_returns), len(benchmark_returns))
        if n < 2:
            return None, None

        p = portfolio_returns[:n]
        b = benchmark_returns[:n]
        mean_p = sum(p) / n
        mean_b = sum(b) / n

        cov = sum((p[i] - mean_p) * (b[i] - mean_b) for i in range(n)) / (n - 1)
        var_b = sum((b[i] - mean_b) ** 2 for i in range(n)) / (n - 1)

        if var_b <= 0:
            return None, None

        beta = cov / var_b
        rf = PerformanceCalculatorService.RISK_FREE_RATE * 100.0
        alpha = annualized_portfolio_pct - rf - beta * (annualized_benchmark_pct - rf)
        return beta, alpha

    @staticmethod
    def calculate_tracking_error(
        portfolio_returns: List[float],
        benchmark_returns: List[float],
    ) -> Optional[float]:
        """跟踪误差（年化，%）。"""
        n = min(len(portfolio_returns), len(benchmark_returns))
        if n < 2:
            return None
        diffs = [portfolio_returns[i] - benchmark_returns[i] for i in range(n)]
        std = _safe_std(diffs)
        if std is None:
            return None
        return std * math.sqrt(PerformanceCalculatorService.TRADING_DAYS_PER_YEAR) * 100.0

    @staticmethod
    def calculate_information_ratio(
        excess_return_pct: float,
        tracking_error_pct: float,
    ) -> Optional[float]:
        """信息比率 = 超额收益 / 跟踪误差。"""
        if tracking_error_pct <= 0:
            return None
        return excess_return_pct / tracking_error_pct

    @staticmethod
    def calculate_treynor(annualized_return_pct: float, beta: float) -> Optional[float]:
        """特雷诺比率 = (年化收益 - 无风险) / Beta。"""
        if beta == 0:
            return None
        rf = PerformanceCalculatorService.RISK_FREE_RATE * 100.0
        return (annualized_return_pct - rf) / beta

    # ------------------------------------------------------------------
    # 交易统计
    # ------------------------------------------------------------------

    @staticmethod
    def calculate_win_rate_profit_factor(
        realized_pnls: List[float],
    ) -> Tuple[Optional[float], Optional[float]]:
        """
        基于已闭合交易的胜率与盈利因子。

        Args:
            realized_pnls: 每笔已实现盈亏列表（元）

        Returns:
            (win_rate_pct, profit_factor) 或 (None, None)
        """
        if not realized_pnls:
            return None, None

        wins = [p for p in realized_pnls if p > 0]
        losses = [p for p in realized_pnls if p < 0]
        total = len(realized_pnls)
        win_rate = len(wins) / total * 100.0

        total_profit = sum(wins) if wins else 0.0
        total_loss = abs(sum(losses)) if losses else 0.0
        profit_factor = (total_profit / total_loss) if total_loss > 0 else None

        return win_rate, profit_factor

    # ------------------------------------------------------------------
    # 加权基准收益
    # ------------------------------------------------------------------

    @staticmethod
    def calculate_weighted_benchmark_return(
        component_returns: List[Tuple[float, float]],
    ) -> Optional[float]:
        """
        计算加权组合基准收益（%）。

        Args:
            component_returns: [(weight, return_pct), ...] 权重已归一化

        Returns:
            加权基准收益（%）或 None
        """
        if not component_returns:
            return None
        total_weight = sum(w for w, _ in component_returns)
        if total_weight <= 0:
            return None
        return sum(w * r for w, r in component_returns) / total_weight
