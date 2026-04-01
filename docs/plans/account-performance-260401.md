# Unified Account Performance And Valuation

## Summary
- 不新拆 app。这个能力属于“账户/投资组合”的业务边界，但代码主归口放在统一账户源头 `apps/simulated_trading`，因为当前真实盘与模拟盘已经在这里汇总为 `account_type=real|simulated` 的统一账户模型；`apps/account` 只保留兼容入口和页面接入。
- 首版同时覆盖真实盘和模拟盘，统一支持：
  - 区间业绩报告
  - 持仓时点估值表
  - 账户时点净值表
  - 管理后台基准配置
- 主收益口径并列展示 `TWR` 和 `MWR/XIRR`。专业指标按账户加权组合基准计算。

## Key Changes
- 在 `apps/simulated_trading` 增加统一账户业绩域对象与用例：
  - `BenchmarkComponent`
  - `UnifiedAccountCashFlow`
  - `ValuationRow`
  - `ValuationSnapshot`
  - `PerformanceReport`
  - `GetAccountPerformanceReportUseCase`
  - `GetAccountValuationSnapshotUseCase`
  - `ListAccountValuationTimelineUseCase`
  - `BackfillUnifiedAccountHistoryUseCase`
- 新增统一持久化模型：
  - `AccountBenchmarkComponentModel`
    - 字段固定为 `account`, `benchmark_code`, `weight`, `display_name`, `sort_order`, `is_active`
    - 应用层写入时强制归一化权重，总和必须大于 0
  - `UnifiedAccountCashFlowModel`
    - 统一存账户外部现金流，字段固定为 `account`, `flow_type`, `amount`, `flow_date`, `source_app`, `source_id`, `notes`
    - 真实盘从现有 `CapitalFlowModel` 回填并持续镜像
    - 模拟盘默认写入一笔 `initial_capital` 初始入金；后续无额外入出金则只保留这一笔
  - `AccountPositionValuationSnapshotModel`
    - 字段固定为 `account`, `record_date`, `asset_code`, `asset_name`, `asset_type`, `quantity`, `avg_cost`, `close_price`, `market_value`, `weight`, `unrealized_pnl`, `unrealized_pnl_pct`
    - 用于历史某日持仓估值表和未来稳定查询
- 统一历史重建规则：
  - 真实盘账户：通过 `LedgerMigrationMap` 找到账户与 `portfolio` 的映射；账户净值优先用现有 `PortfolioDailySnapshotModel` 回填；现金流从 `CapitalFlowModel` 回填；持仓快照通过 `TransactionModel` 按日期回放并调用 `apps.market_data` 历史价格服务补齐收盘价
  - 模拟盘账户：净值优先用现有 `simulated_daily_net_value`；持仓快照通过 `SimulatedTradeModel` 回放；现金流用统一现金流表
- 统一计算口径固定如下：
  - `TWR`：按日链式收益，日收益公式为 `(V_t - V_t-1 - CF_t) / V_t-1`
  - `MWR/XIRR`：以外部现金流和期末组合价值求解
  - `annualized_twr`、`annualized_mwr`
  - `volatility`、`downside_volatility`
  - `max_drawdown`
  - `sharpe`、`sortino`、`calmar`
  - `benchmark_return`、`excess_return`
  - `beta`、`alpha`
  - `tracking_error`、`information_ratio`
  - `treynor`
  - `win_rate`、`profit_factor` 基于已闭合交易回放；若历史无法闭合则返回 `null` 并给出 warning
- 页面和入口归口：
  - `apps/account` 的组合详情页增加两个轻量区块：`区间业绩` 与 `时点估值`
  - 页面只消费统一 API，不再各自实现算法
  - admin 增加账户基准组件配置、统一现金流、估值快照只读查看

## Public APIs And Types
- 新增统一 API：
  - `GET /api/simulated-trading/accounts/{account_id}/performance-report/?start_date=YYYY-MM-DD&end_date=YYYY-MM-DD`
  - `GET /api/simulated-trading/accounts/{account_id}/valuation-snapshot/?as_of_date=YYYY-MM-DD`
  - `GET /api/simulated-trading/accounts/{account_id}/valuation-timeline/?start_date=YYYY-MM-DD&end_date=YYYY-MM-DD`
  - `GET|PUT /api/simulated-trading/accounts/{account_id}/benchmarks/`
- 新增兼容 API：
  - `GET /api/account/portfolios/{portfolio_id}/performance-report/`
  - `GET /api/account/portfolios/{portfolio_id}/valuation-snapshot/`
  - `GET /api/account/portfolios/{portfolio_id}/valuation-timeline/`
  - `GET|PUT /api/account/portfolios/{portfolio_id}/benchmarks/`
- `performance-report` 响应固定包含：
  - `period`
  - `returns`
  - `risk`
  - `ratios`
  - `benchmark`
  - `trade_stats`
  - `coverage`
  - `warnings`
- `valuation-snapshot` 响应固定包含：
  - `as_of_date`
  - `account_summary`
  - `rows`
  - `coverage`
- `valuation-timeline` 响应固定包含：
  - `points`
  - 每点字段固定为 `date`, `cash`, `market_value`, `total_value`, `net_value`, `twr_cumulative`, `drawdown`

## Test Plan
- Domain 单测：
  - TWR/MWR/XIRR 公式
  - 组合基准加权收益
  - Sharpe/Sortino/Calmar/Beta/Alpha/IR/Tracking Error/Treynor
  - 最大回撤与空样本处理
- Integration：
  - 真实盘 `portfolio -> unified account` 映射后可查询同一套业绩接口
  - 模拟盘直接走统一接口
  - `CapitalFlowModel` 回填到统一现金流
  - `TransactionModel` / `SimulatedTradeModel` 回放出历史持仓估值表
  - benchmark CRUD 与权重归一化
- API 契约：
  - 新增 8 个端点的状态码、`Content-Type`、字段存在性、权限范围
  - 观察员只读场景延续现有权限语义
- 页面/Admin：
  - 账户详情页能渲染区间业绩和估值表
  - admin 可编辑 benchmark 组件，可查看回填结果

## Assumptions And Defaults
- 不新建独立“performance app”；业务仍算账户能力。
- 技术主归口放 `apps/simulated_trading`，因为它已是统一账户源头；`apps/account` 只做兼容 API 与页面。
- 风险免费利率默认 `3.0%`，与现有 fund 计算保持一致；后续可再配置化。
- 组合基准首版必须配置至少 1 个成分，支持多个代码加权；缺失行情的日期不插值，直接记入 `coverage.warnings`。
- 历史回填采取 `best effort`：从最早可还原的交易/快照日期开始；无法可靠还原的指标返回 `null`，不伪造。
- 文档同步更新账户 API 文档、统一账户说明和开发快速参考。
