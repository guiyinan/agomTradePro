# Regime 链路统一说明（2026-03-02）

## 目标

避免不同页面、接口、异步任务使用不同 Regime 计算口径，消除“同一时点显示不同象限”的问题。

## 统一实现

统一入口：

- `apps/regime/application/current_regime.py::resolve_current_regime`

统一规则：

- 使用 `CalculateRegimeV2UseCase`
- `growth_indicator=PMI`
- `inflation_indicator=CPI`
- `use_pit=True`（除显式传参外）
- 数据源来自 `DataSourceConfig` 的激活优先级首项
- `apps/regime/infrastructure/macro_data_provider.py` 从 2026-04-05 起统一读取 `apps/data_center` 的 `MacroFact` / `IndicatorCatalog`，不再直连 legacy `apps.macro` ORM 仓储
- 失败时回退到 `get_latest_snapshot()`，再失败返回 `Unknown`

## 已切换模块（主流程）

- `core/views.py`（决策工作台、资产筛选页）
- `apps/dashboard/application/use_cases.py`
- `apps/regime/interface/api_views.py`
- `apps/alpha_trigger/interface/views.py`
- `apps/beta_gate/interface/views.py`
- `apps/asset_analysis/interface/views.py`
- `apps/asset_analysis/interface/pool_views.py`
- `apps/signal/interface/views.py`
- `apps/signal/interface/api_views.py`
- `apps/fund/interface/views.py`
- `apps/equity/interface/views.py`
- `apps/account/application/use_cases.py`
- `apps/fund/application/use_cases.py`
- `apps/equity/application/use_cases.py`
- `apps/sector/application/use_cases.py`
- `apps/policy/application/tasks.py`
- `apps/macro/application/tasks.py`
- `apps/realtime/interface/__init__.py`
- `apps/regime/application/tasks.py`
- `apps/strategy/infrastructure/providers.py`
- `apps/simulated_trading/application/daily_inspection_service.py`
- `apps/prompt/infrastructure/adapters/regime_adapter.py`

## 旧链路状态

- `GetCurrentRegimeUseCase` 已标注 deprecated，仅保留兼容。
- 旧版 `CalculateRegimeUseCase` 保留在 `apps/regime/application/use_cases.py`，仅用于历史兼容与离线回算，不作为主流程入口。
