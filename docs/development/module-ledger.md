# Module Ledger

> Rules version: `2026-03-28.v1`
> Generated at: `2026-03-28`
> Boundary rules: `4`
> Violations: `0`
> Business Modules: `35`

## Boundary Baseline

| Rule ID | Source | Layers | Forbidden Imports | Rationale |
|---------|--------|--------|-------------------|-----------|
| `regime_runtime_no_macro_impl_imports` | `regime` | `application, interface, management` | `apps.macro.application.tasks, apps.macro.infrastructure.models, apps.macro.infrastructure.repositories` | Use MacroSyncTaskGateway, MacroSourceConfigGateway, and MacroRepositoryAdapter. |
| `strategy_no_simulated_trading_orm_imports` | `strategy` | `application, domain, interface, management` | `apps.simulated_trading.infrastructure.models` | Use SimulatedTradingFacade or gateway contracts. |
| `simulated_trading_no_strategy_orm_imports` | `simulated_trading` | `application, domain, interface, management` | `apps.strategy.infrastructure.models` | Use StrategyExecutionGateway or strategy-side contracts. |
| `events_no_direct_downstream_models_or_handlers` | `events` | `application, domain, infrastructure, interface, management` | `apps.alpha_trigger.application.handlers, apps.alpha_trigger.infrastructure.models, apps.decision_rhythm.application.handlers, apps.decision_rhythm.infrastructure.models` | Delegate via EventSubscriberRegistry and downstream repositories/gateways. |

## Module Summary

| Module | Role | Outbound | Inbound | Patterns | Note |
|--------|------|----------|---------|----------|------|
| `account` |  | 6 | 7 |  | out: audit, backtest, events, regime, signal, simulated_trading; in: backtest, dashboard, decision_rhythm, equity, factor, macro, strategy |
| `ai_provider` |  | 0 | 7 |  | in: beta_gate, dashboard, policy, prompt, sentiment, simulated_trading, strategy |
| `alpha` |  | 1 | 4 |  | out: fund; in: backtest, dashboard, decision_rhythm, signal |
| `alpha_trigger` |  | 5 | 3 |  | out: decision_rhythm, events, macro, policy, regime; in: dashboard, decision_rhythm, events |
| `asset_analysis` |  | 6 | 5 |  | out: equity, fund, policy, regime, sentiment, signal; in: decision_rhythm, equity, fund, simulated_trading, strategy |
| `audit` |  | 3 | 2 |  | out: backtest, macro, regime; in: account, backtest |
| `backtest` |  | 5 | 2 |  | out: account, alpha, audit, equity, regime; in: account, audit |
| `beta_gate` |  | 4 | 2 |  | out: ai_provider, events, policy, regime; in: dashboard, decision_rhythm |
| `dashboard` | aggregation | 13 | 0 | Query Service | out: account, ai_provider, alpha, alpha_trigger, beta_gate, decision_rhythm, equity, fund, ...; Dashboard keeps cross-module reads in query/DTO boundaries. |
| `decision_rhythm` |  | 12 | 3 |  | out: account, alpha, alpha_trigger, asset_analysis, beta_gate, equity, events, policy, ...; in: alpha_trigger, dashboard, events |
| `equity` |  | 5 | 9 |  | out: account, asset_analysis, macro, regime, signal; in: asset_analysis, backtest, dashboard, decision_rhythm, factor, data_center, realtime, simulated_trading, ... |
| `events` | integration | 2 | 4 | Registry, Repository wrapper | out: alpha_trigger, decision_rhythm; in: account, alpha_trigger, beta_gate, decision_rhythm; Event fan-out should stop at registry/repository boundaries. |
| `factor` |  | 3 | 1 |  | out: account, equity, rotation; in: signal |
| `filter` |  | 1 | 0 |  | out: macro |
| `fund` |  | 5 | 5 |  | out: asset_analysis, policy, regime, sentiment, signal; in: alpha, asset_analysis, dashboard, simulated_trading, strategy |
| `hedge` |  | 0 | 1 |  | in: signal |
| `macro` | core | 1 | 10 | Orchestration | out: account; in: alpha_trigger, audit, dashboard, equity, filter, prompt, regime, signal, ...; Macro sync is invoked through regime orchestration boundaries. |
| `data_center` | core | 4 | 12 | Query Service, Gateway | out: equity, fund, macro, sector; in: backtest, equity, factor, fund, hedge, macro, realtime, regime, rotation, setup_wizard, signal, simulated_trading; Unified data-center boundaries replace the legacy market_data facade. |
| `policy` |  | 3 | 8 |  | out: ai_provider, regime, signal; in: alpha_trigger, asset_analysis, beta_gate, dashboard, decision_rhythm, fund, sentiment, simulated_trading |
| `prompt` |  | 3 | 2 |  | out: ai_provider, macro, regime; in: simulated_trading, strategy |
| `realtime` |  | 4 | 3 |  | out: data_center, equity, regime, simulated_trading; in: data_center, decision_rhythm, simulated_trading |
| `regime` | core | 1 | 18 | Protocol, Adapter, Gateway | out: macro; in: account, alpha_trigger, asset_analysis, audit, backtest, beta_gate, dashboard, decision_rhythm, ...; Runtime access to macro is mediated by regime-owned abstractions. |
| `rotation` |  | 2 | 2 |  | out: regime, simulated_trading; in: factor, signal |
| `sector` |  | 1 | 0 |  | out: regime |
| `sentiment` |  | 2 | 3 |  | out: ai_provider, policy; in: asset_analysis, decision_rhythm, fund |
| `signal` |  | 6 | 8 |  | out: alpha, factor, hedge, macro, regime, rotation; in: account, asset_analysis, dashboard, equity, fund, policy, simulated_trading, strategy |
| `simulated_trading` | business | 11 | 5 | Facade, Gateway | out: ai_provider, asset_analysis, equity, fund, macro, policy, prompt, realtime, ...; in: account, decision_rhythm, realtime, rotation, strategy; Simulated trading should not reach strategy ORM directly. |
| `strategy` | business | 10 | 2 | Facade, Gateway | out: account, ai_provider, asset_analysis, equity, fund, macro, prompt, regime, ...; in: dashboard, simulated_trading; Strategy should not reach simulated_trading ORM directly. |
| `task_monitor` |  | 0 | 0 |  |  |
| `agent_runtime` |  | 0 | 0 |  | Terminal AI backend, supports task orchestration and Facade pattern |
| `share` |  | 2 | 0 |  | out: decision_rhythm, simulated_trading; Decision sharing module |
| `terminal` |  | 1 | 0 |  | out: prompt; Terminal CLI, AI interaction interface |
| `ai_capability` |  | 1 | 0 |  | out: terminal; AI Capability Catalog, unified routing |
| `setup_wizard` |  | 0 | 0 |  | System initialization wizard, first-time setup guide |
| `pulse` |  | 2 | 3 |  | out: macro, regime; in: decision_rhythm, dashboard, regime; Pulse tactical layer — indicator aggregation and transition warning |

## Violations

No boundary violations detected.
