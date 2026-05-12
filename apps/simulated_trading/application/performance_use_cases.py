"""
统一账户业绩与估值用例

Application 层：
- 通过 Protocol 接口依赖 Infrastructure 层
- 不直接导入 ORM Model
- 调用 Domain 层服务完成金融计算
"""
from __future__ import annotations

import logging
from datetime import date
from typing import Any, Protocol

from apps.simulated_trading.domain.entities import (
    AccountValuationSummary,
    BenchmarkComponent,
    BenchmarkStats,
    CoverageInfo,
    PerformancePeriod,
    PerformanceRatios,
    PerformanceReport,
    PerformanceReturns,
    PerformanceRisk,
    TradeStats,
    ValuationRow,
    ValuationSnapshot,
    ValuationTimelinePoint,
)
from apps.simulated_trading.domain.services import PerformanceCalculatorService

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Protocols (Application 层定义，Infrastructure 层实现)
# ---------------------------------------------------------------------------


class AccountRepositoryProtocol(Protocol):
    """账户只读仓储接口。"""

    def get_by_id(self, account_id: int) -> dict[str, Any] | None:
        """返回账户字典（含 initial_capital, start_date, account_type）。"""
        ...


class BenchmarkComponentRepositoryProtocol(Protocol):
    """基准成分仓储接口。"""

    def list_active(self, account_id: int) -> list[dict[str, Any]]:
        """返回账户的所有激活基准成分 dicts。"""
        ...

    def upsert_components(self, account_id: int, components: list[dict[str, Any]]) -> None:
        """覆盖写入账户的所有基准成分（先删再插）。"""
        ...


class UnifiedCashFlowRepositoryProtocol(Protocol):
    """统一现金流仓储接口。"""

    def list_for_account(
        self,
        account_id: int,
        start_date: date | None = None,
        end_date: date | None = None,
    ) -> list[dict[str, Any]]:
        """返回账户在区间内的现金流 dicts（按 flow_date 升序）。"""
        ...

    def create_initial_capital(self, account_id: int, amount: float, flow_date: date) -> None:
        """写入初始入金流水（幂等）。"""
        ...

    def mirror_from_capital_flow(self, account_id: int, capital_flow_dict: dict[str, Any]) -> None:
        """将 CapitalFlowModel 记录镜像到统一现金流（幂等）。"""
        ...


class ValuationSnapshotRepositoryProtocol(Protocol):
    """持仓估值快照仓储接口。"""

    def get_for_date(self, account_id: int, record_date: date) -> list[dict[str, Any]]:
        """返回某日所有持仓快照 dicts。"""
        ...

    def upsert_snapshot(
        self,
        account_id: int,
        record_date: date,
        rows: list[dict[str, Any]],
    ) -> None:
        """覆盖写入某日持仓估值快照。"""
        ...


class DailyNetValueRepositoryProtocol(Protocol):
    """日净值仓储接口（只读）。"""

    def list_range(
        self,
        account_id: int,
        start_date: date | None = None,
        end_date: date | None = None,
    ) -> list[dict[str, Any]]:
        """按日期升序返回净值记录 dicts。"""
        ...

    def get_record_for_date(
        self, account_id: int, record_date: date
    ) -> dict[str, Any] | None:
        """返回某日净值记录（用于历史时点现金获取）。无则返回 None。"""
        ...


class MarketDataRepositoryProtocol(Protocol):
    """行情数据仓储接口。"""

    def get_close_price(self, asset_code: str, trade_date: date) -> float | None:
        """返回某日收盘价，无数据返回 None。"""
        ...

    def get_index_daily_returns(
        self,
        index_code: str,
        start_date: date,
        end_date: date,
    ) -> list[tuple[date, float]]:
        """返回指数日收益率序列（小数，非百分比），按日期升序。"""
        ...

    def get_index_cumulative_return(
        self,
        index_code: str,
        start_date: date,
        end_date: date,
    ) -> float | None:
        """返回指数区间累计收益率（%）。"""
        ...


class CapitalFlowRepositoryProtocol(Protocol):
    """账本现金流仓储接口（真实账户 backfill 专用）。"""

    def list_for_account_via_ledger(
        self, account_id: int
    ) -> list[dict[str, Any]]:
        """通过 LedgerMigrationMapModel 返回该账户对应的全部 CapitalFlowModel 记录。"""
        ...


class ObserverGrantRepositoryProtocol(Protocol):
    """观察员授权仓储接口。"""

    def has_valid_grant(self, owner_user_id: int, observer_user_id: int) -> bool:
        """返回观察员是否持有 owner 的有效授权。"""
        ...


class TradeHistoryRepositoryProtocol(Protocol):
    """交易历史仓储接口。"""

    def list_closed_trades(
        self,
        account_id: int,
        start_date: date | None = None,
        end_date: date | None = None,
    ) -> list[dict[str, Any]]:
        """返回区间内已实现盈亏的卖出交易 dicts（含 realized_pnl）。"""
        ...


# ---------------------------------------------------------------------------
# GetAccountPerformanceReportUseCase
# ---------------------------------------------------------------------------


class GetAccountPerformanceReportUseCase:
    """
    获取账户区间业绩报告。

    对应 GET /api/simulated-trading/accounts/{id}/performance-report/
    """

    def __init__(
        self,
        account_repo: AccountRepositoryProtocol,
        daily_net_value_repo: DailyNetValueRepositoryProtocol,
        cash_flow_repo: UnifiedCashFlowRepositoryProtocol,
        benchmark_repo: BenchmarkComponentRepositoryProtocol,
        market_data_repo: MarketDataRepositoryProtocol,
        trade_history_repo: TradeHistoryRepositoryProtocol,
    ) -> None:
        self._account_repo = account_repo
        self._dnv_repo = daily_net_value_repo
        self._cf_repo = cash_flow_repo
        self._bm_repo = benchmark_repo
        self._md_repo = market_data_repo
        self._trade_repo = trade_history_repo

    def execute(
        self,
        account_id: int,
        start_date: date,
        end_date: date,
    ) -> PerformanceReport:
        """
        计算并返回区间业绩报告。

        未能可靠计算的指标返回 None，不伪造数据。
        """
        warnings: list[str] = []

        account = self._account_repo.get_by_id(account_id)
        if account is None:
            raise ValueError(f"Account {account_id} not found")

        # 1. 获取日净值序列
        dnv_records = self._dnv_repo.list_range(account_id, start_date, end_date)
        daily_values: list[tuple[date, float]] = [
            (r["record_date"], float(r["total_value"])) for r in dnv_records
        ]

        # 2. 获取区间现金流
        cf_records = self._cf_repo.list_for_account(account_id, start_date, end_date)
        daily_cashflows: list[tuple[date, float]] = [
            (r["flow_date"], float(r["amount"])) for r in cf_records
        ]

        # 3. 计算区间天数
        days = (end_date - start_date).days
        period = PerformancePeriod(start_date=start_date, end_date=end_date, days=days)

        # 4. TWR
        twr_pct: float | None = None
        annualized_twr: float | None = None
        if len(daily_values) >= 2:
            twr_pct = PerformanceCalculatorService.calculate_twr(daily_values, daily_cashflows)
            if twr_pct is not None and days > 0:
                annualized_twr = PerformanceCalculatorService.calculate_annualized_twr(twr_pct, days)
        else:
            warnings.append("日净值数据不足（少于 2 个交易日），无法计算 TWR")

        # 5. MWR/XIRR
        mwr_pct: float | None = None
        annualized_mwr: float | None = None
        if cf_records and daily_values:
            terminal_value = daily_values[-1][1] if daily_values else 0.0
            xirr_result = PerformanceCalculatorService.calculate_xirr(
                cashflows=daily_cashflows,
                terminal_value=terminal_value,
                terminal_date=end_date,
            )
            if xirr_result is not None:
                mwr_pct = xirr_result
                annualized_mwr = xirr_result  # XIRR 本身即年化
            else:
                warnings.append("XIRR 未能收敛，MWR 返回 null")
        else:
            warnings.append("无外部现金流记录，跳过 MWR 计算")

        returns = PerformanceReturns(
            twr=twr_pct,
            mwr=mwr_pct,
            annualized_twr=annualized_twr,
            annualized_mwr=annualized_mwr,
        )

        # 6. 日收益率序列 → 风险指标
        daily_returns = PerformanceCalculatorService.build_daily_returns(daily_values, daily_cashflows)
        volatility = PerformanceCalculatorService.calculate_volatility(daily_returns)
        downside_vol = PerformanceCalculatorService.calculate_downside_volatility(daily_returns)
        max_dd = PerformanceCalculatorService.calculate_max_drawdown(daily_values)
        risk = PerformanceRisk(
            volatility=volatility,
            downside_volatility=downside_vol,
            max_drawdown=max_dd,
        )

        # 7. 比率
        ann_ret = annualized_twr  # 优先使用 TWR
        sharpe: float | None = None
        sortino: float | None = None
        calmar: float | None = None
        treynor: float | None = None

        if ann_ret is not None and volatility is not None:
            sharpe = PerformanceCalculatorService.calculate_sharpe(ann_ret, volatility)
        if ann_ret is not None and downside_vol is not None:
            sortino = PerformanceCalculatorService.calculate_sortino(ann_ret, downside_vol)
        if ann_ret is not None and max_dd is not None:
            calmar = PerformanceCalculatorService.calculate_calmar(ann_ret, max_dd)

        # 8. 基准指标
        benchmark_stats: BenchmarkStats | None = None
        bm_components = self._bm_repo.list_active(account_id)
        if bm_components:
            component_returns: list[tuple[float, float]] = []
            bm_daily_returns_combined: list[float] = []
            bm_return_missing = False

            # 获取每个成分的区间收益和日收益
            all_component_daily: list[list[float]] = []
            for comp in bm_components:
                bm_code = comp["benchmark_code"]
                weight = float(comp["weight"])
                cum_ret = self._md_repo.get_index_cumulative_return(bm_code, start_date, end_date)
                if cum_ret is None:
                    warnings.append(f"基准 {bm_code} 在区间内无行情数据，已跳过")
                    bm_return_missing = True
                    continue
                component_returns.append((weight, cum_ret))

                # 获取日收益用于 Beta/Alpha/TE/IR 计算
                idx_daily = self._md_repo.get_index_daily_returns(bm_code, start_date, end_date)
                all_component_daily.append([r for _, r in idx_daily])

            bm_return: float | None = None
            if component_returns:
                bm_return = PerformanceCalculatorService.calculate_weighted_benchmark_return(component_returns)

            # 加权合并基准日收益（简单按权重插值）
            if all_component_daily and not bm_return_missing:
                min_len = min(len(s) for s in all_component_daily)
                weights = [float(c["weight"]) for c in bm_components if c["benchmark_code"] in
                           [comp["benchmark_code"] for comp, _ in zip(bm_components, component_returns, strict=False)]]
                if min_len > 0 and weights:
                    bm_daily_returns_combined = [
                        sum(all_component_daily[i][j] * weights[i] for i in range(len(weights)))
                        for j in range(min_len)
                    ]

            excess_return: float | None = None
            if twr_pct is not None and bm_return is not None:
                excess_return = twr_pct - bm_return

            beta: float | None = None
            alpha: float | None = None
            tracking_error: float | None = None
            information_ratio: float | None = None

            if daily_returns and bm_daily_returns_combined and ann_ret is not None:
                ann_bm = PerformanceCalculatorService.calculate_annualized_twr(
                    bm_return or 0.0, days
                ) if bm_return is not None else None
                if ann_bm is not None:
                    beta, alpha = PerformanceCalculatorService.calculate_beta_alpha(
                        daily_returns, bm_daily_returns_combined, ann_ret, ann_bm
                    )
                    if beta is not None:
                        treynor = PerformanceCalculatorService.calculate_treynor(ann_ret, beta)
                tracking_error = PerformanceCalculatorService.calculate_tracking_error(
                    daily_returns, bm_daily_returns_combined
                )
                if tracking_error and excess_return is not None:
                    information_ratio = PerformanceCalculatorService.calculate_information_ratio(
                        excess_return, tracking_error
                    )

            benchmark_stats = BenchmarkStats(
                benchmark_return=bm_return,
                excess_return=excess_return,
                beta=beta,
                alpha=alpha,
                tracking_error=tracking_error,
                information_ratio=information_ratio,
            )
        else:
            warnings.append("未配置基准成分，跳过基准指标计算")

        ratios = PerformanceRatios(sharpe=sharpe, sortino=sortino, calmar=calmar, treynor=treynor)

        # 9. 交易统计
        closed_trades = self._trade_repo.list_closed_trades(account_id, start_date, end_date)
        realized_pnls = [float(t["realized_pnl"]) for t in closed_trades if t.get("realized_pnl") is not None]
        win_rate, profit_factor = PerformanceCalculatorService.calculate_win_rate_profit_factor(realized_pnls)
        if not realized_pnls:
            warnings.append("区间内无已闭合交易，win_rate 与 profit_factor 返回 null")

        trade_stats = TradeStats(
            win_rate=win_rate,
            profit_factor=profit_factor,
            total_closed_trades=len(realized_pnls),
        )

        # 10. 覆盖信息
        data_start = daily_values[0][0] if daily_values else None
        data_end = daily_values[-1][0] if daily_values else None
        coverage = CoverageInfo(data_start=data_start, data_end=data_end, warnings=warnings)

        return PerformanceReport(
            period=period,
            returns=returns,
            risk=risk,
            ratios=ratios,
            benchmark=benchmark_stats,
            trade_stats=trade_stats,
            coverage=coverage,
            warnings=warnings,
        )


# ---------------------------------------------------------------------------
# GetAccountValuationSnapshotUseCase
# ---------------------------------------------------------------------------


class GetAccountValuationSnapshotUseCase:
    """
    获取账户某日持仓估值表。

    对应 GET /api/simulated-trading/accounts/{id}/valuation-snapshot/?as_of_date=...
    优先从快照缓存读取；若无快照则返回空 rows 并记录 warning。

    现金口径：从 DailyNetValueModel 取 as_of_date 当日的历史现金，
    避免用当前现金代替历史现金导致总资产失真。
    """

    def __init__(
        self,
        account_repo: AccountRepositoryProtocol,
        valuation_snapshot_repo: ValuationSnapshotRepositoryProtocol,
        daily_net_value_repo: DailyNetValueRepositoryProtocol,
    ) -> None:
        self._account_repo = account_repo
        self._snapshot_repo = valuation_snapshot_repo
        self._dnv_repo = daily_net_value_repo

    def execute(self, account_id: int, as_of_date: date) -> ValuationSnapshot:
        warnings: list[str] = []

        account = self._account_repo.get_by_id(account_id)
        if account is None:
            raise ValueError(f"Account {account_id} not found")

        rows_dicts = self._snapshot_repo.get_for_date(account_id, as_of_date)

        rows: list[ValuationRow] = []
        total_market_value = 0.0
        total_cost = 0.0

        for r in rows_dicts:
            market_value = float(r.get("market_value", 0))
            total_market_value += market_value
            avg_cost = float(r.get("avg_cost", 0))
            quantity = float(r.get("quantity", 0))
            total_cost += avg_cost * quantity

        for r in rows_dicts:
            market_value = float(r.get("market_value", 0))
            weight = (market_value / total_market_value) if total_market_value > 0 else 0.0
            rows.append(
                ValuationRow(
                    asset_code=r["asset_code"],
                    asset_name=r.get("asset_name", ""),
                    asset_type=r.get("asset_type", "other"),
                    quantity=float(r.get("quantity", 0)),
                    avg_cost=float(r.get("avg_cost", 0)),
                    close_price=float(r.get("close_price", 0)),
                    market_value=market_value,
                    weight=weight,
                    unrealized_pnl=float(r.get("unrealized_pnl", 0)),
                    unrealized_pnl_pct=float(r.get("unrealized_pnl_pct", 0)),
                )
            )

        if not rows:
            warnings.append(f"{as_of_date} 无持仓估值快照，请先执行历史回填")

        # 优先使用 as_of_date 当日的历史现金；无记录时降级为当前现金并警告
        dnv_record = self._dnv_repo.get_record_for_date(account_id, as_of_date)
        if dnv_record is not None:
            cash = dnv_record["cash"]
        else:
            cash = float(account.get("current_cash", 0))
            warnings.append(
                f"{as_of_date} 无日净值记录，现金使用账户当前值（历史查询时可能不准确）"
            )

        total_value = cash + total_market_value
        unrealized_pnl = total_market_value - total_cost
        unrealized_pnl_pct = (unrealized_pnl / total_cost * 100.0) if total_cost > 0 else 0.0

        account_summary = AccountValuationSummary(
            total_value=total_value,
            cash=cash,
            market_value=total_market_value,
            unrealized_pnl=unrealized_pnl,
            unrealized_pnl_pct=unrealized_pnl_pct,
        )
        coverage = CoverageInfo(data_start=as_of_date, data_end=as_of_date, warnings=warnings)

        return ValuationSnapshot(
            as_of_date=as_of_date,
            account_summary=account_summary,
            rows=rows,
            coverage=coverage,
        )


# ---------------------------------------------------------------------------
# ListAccountValuationTimelineUseCase
# ---------------------------------------------------------------------------


class ListAccountValuationTimelineUseCase:
    """
    获取账户净值时间线。

    对应 GET /api/simulated-trading/accounts/{id}/valuation-timeline/
    从 DailyNetValueModel 读取，并计算 TWR 累计值。
    """

    def __init__(
        self,
        account_repo: AccountRepositoryProtocol,
        daily_net_value_repo: DailyNetValueRepositoryProtocol,
        cash_flow_repo: UnifiedCashFlowRepositoryProtocol,
    ) -> None:
        self._account_repo = account_repo
        self._dnv_repo = daily_net_value_repo
        self._cf_repo = cash_flow_repo

    def execute(
        self,
        account_id: int,
        start_date: date | None = None,
        end_date: date | None = None,
    ) -> list[ValuationTimelinePoint]:
        account = self._account_repo.get_by_id(account_id)
        if account is None:
            raise ValueError(f"Account {account_id} not found")

        dnv_records = self._dnv_repo.list_range(account_id, start_date, end_date)
        if not dnv_records:
            return []

        cf_records = self._cf_repo.list_for_account(account_id, start_date, end_date)
        cf_map: dict[date, float] = {}
        for cf in cf_records:
            d = cf["flow_date"]
            cf_map[d] = cf_map.get(d, 0.0) + float(cf["amount"])

        initial_capital = float(account.get("initial_capital", 1.0))
        if initial_capital <= 0:
            initial_capital = 1.0

        points: list[ValuationTimelinePoint] = []
        cumulative_twr = 1.0  # 累乘因子
        prev_total_value: float | None = None
        peak_value: float = 0.0

        for rec in dnv_records:
            d = rec["record_date"]
            cash = float(rec.get("cash", 0))
            market_value = float(rec.get("market_value", 0))
            total_value = float(rec.get("total_value", 0)) or (cash + market_value)
            net_value = total_value / initial_capital

            # 增量 TWR
            if prev_total_value is not None and prev_total_value > 0:
                cf = cf_map.get(d, 0.0)
                sub_r = (total_value - prev_total_value - cf) / prev_total_value
                cumulative_twr *= (1.0 + sub_r)

            twr_cumulative_pct = (cumulative_twr - 1.0) * 100.0

            # 回撤
            if total_value > peak_value:
                peak_value = total_value
            drawdown = ((peak_value - total_value) / peak_value * 100.0) if peak_value > 0 else 0.0

            points.append(
                ValuationTimelinePoint(
                    date=d,
                    cash=cash,
                    market_value=market_value,
                    total_value=total_value,
                    net_value=round(net_value, 4),
                    twr_cumulative=round(twr_cumulative_pct, 4),
                    drawdown=round(drawdown, 4),
                )
            )
            prev_total_value = total_value

        return points


# ---------------------------------------------------------------------------
# BackfillUnifiedAccountHistoryUseCase
# ---------------------------------------------------------------------------


class BackfillUnifiedAccountHistoryUseCase:
    """
    回填统一账户历史数据（best effort）。

    执行步骤：
    1. 写入初始入金现金流（幂等）
    2. 真实盘：通过 LedgerMigrationMapModel 找到对应 portfolio，
       从 CapitalFlowModel 镜像全部现金流到统一现金流表
    3. 验证日净值序列是否存在

    持仓快照的逐日回放数据量较大，由 Celery 任务异步执行，
    此用例仅做现金流回填与数据验证。
    """

    def __init__(
        self,
        account_repo: AccountRepositoryProtocol,
        cash_flow_repo: UnifiedCashFlowRepositoryProtocol,
        daily_net_value_repo: DailyNetValueRepositoryProtocol,
        capital_flow_repo: CapitalFlowRepositoryProtocol | None = None,
    ) -> None:
        self._account_repo = account_repo
        self._cf_repo = cash_flow_repo
        self._dnv_repo = daily_net_value_repo
        self._capital_flow_repo = capital_flow_repo

    def execute(self, account_id: int) -> dict[str, Any]:
        """
        Returns:
            summary dict with keys: account_id, initial_capital_written,
            mirrored_capital_flows, dnv_record_count, warnings
        """
        warnings: list[str] = []

        account = self._account_repo.get_by_id(account_id)
        if account is None:
            raise ValueError(f"Account {account_id} not found")

        # Step 1: 写入初始入金
        initial_capital = float(account.get("initial_capital", 0))
        start_date = account.get("start_date")
        if start_date is None:
            warnings.append("账户缺少 start_date，无法回填初始入金")
            initial_capital_written = False
        else:
            self._cf_repo.create_initial_capital(
                account_id=account_id,
                amount=initial_capital,
                flow_date=start_date,
            )
            initial_capital_written = True

        # Step 2: 真实盘 — 镜像 CapitalFlowModel
        mirrored_capital_flows = 0
        account_type = account.get("account_type", "simulated")
        if account_type == "real" and self._capital_flow_repo is not None:
            capital_flows = self._capital_flow_repo.list_for_account_via_ledger(account_id)
            for cf in capital_flows:
                self._cf_repo.mirror_from_capital_flow(account_id, cf)
                mirrored_capital_flows += 1
            if not capital_flows:
                warnings.append("真实盘账户：未找到对应 portfolio 映射或 CapitalFlowModel 无记录")
        elif account_type == "real" and self._capital_flow_repo is None:
            warnings.append("真实盘账户：未注入 capital_flow_repo，跳过 CapitalFlowModel 镜像")

        # Step 3: 验证净值序列
        dnv_records = self._dnv_repo.list_range(account_id)
        dnv_count = len(dnv_records)
        if dnv_count == 0:
            warnings.append("无日净值数据，业绩指标无法计算；请确认账户已有交易记录")

        return {
            "account_id": account_id,
            "initial_capital_written": initial_capital_written,
            "mirrored_capital_flows": mirrored_capital_flows,
            "dnv_record_count": dnv_count,
            "warnings": warnings,
        }


# ---------------------------------------------------------------------------
# BenchmarkCRUDUseCase
# ---------------------------------------------------------------------------


class BenchmarkCRUDUseCase:
    """
    账户基准成分 CRUD 用例。

    对应 GET|PUT /api/simulated-trading/accounts/{id}/benchmarks/
    PUT 时强制归一化权重（总和归到 1.0），总权重必须 > 0。
    """

    def __init__(self, benchmark_repo: BenchmarkComponentRepositoryProtocol) -> None:
        self._repo = benchmark_repo

    def get(self, account_id: int) -> list[BenchmarkComponent]:
        """获取账户所有激活基准成分。"""
        dicts = self._repo.list_active(account_id)
        return [
            BenchmarkComponent(
                account_id=account_id,
                benchmark_code=d["benchmark_code"],
                weight=float(d["weight"]),
                display_name=d.get("display_name", ""),
                sort_order=int(d.get("sort_order", 0)),
                is_active=bool(d.get("is_active", True)),
            )
            for d in dicts
        ]

    def put(self, account_id: int, components: list[dict[str, Any]]) -> list[BenchmarkComponent]:
        """
        覆盖写入基准成分（归一化权重）。

        Args:
            components: [{"benchmark_code": ..., "weight": ..., "display_name": ..., "sort_order": ...}, ...]

        Raises:
            ValueError: 总权重为 0 或列表为空
        """
        if not components:
            raise ValueError("至少需要配置 1 个基准成分")

        total_weight = sum(float(c.get("weight", 0)) for c in components)
        if total_weight <= 0:
            raise ValueError("所有基准成分权重之和必须大于 0")

        normalized = [
            {
                **c,
                "weight": float(c.get("weight", 0)) / total_weight,
                "is_active": True,
            }
            for c in components
        ]
        self._repo.upsert_components(account_id, normalized)
        return self.get(account_id)
