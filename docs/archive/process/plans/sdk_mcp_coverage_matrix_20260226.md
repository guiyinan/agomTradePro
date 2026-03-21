# SDK / MCP Coverage Matrix (2026-02-26)

## Legend
- Y: Implemented in this repo
- P: Partial / needs endpoint-level expansion
- N: Not implemented

## Business Modules

| Module | Django App | SDK Module | MCP Tools | Status |
|---|---|---|---|---|
| Account | `apps.account` | `account` | `account_tools` | Y |
| Regime | `apps.regime` | `regime` | `regime_tools` | Y |
| Macro | `apps.macro` | `macro` | `macro_tools` | Y |
| Policy | `apps.policy` | `policy` | `policy_tools` | Y |
| Signal | `apps.signal` | `signal` | `signal_tools` | Y |
| Backtest | `apps.backtest` | `backtest` | `backtest_tools` | Y |
| Simulated Trading | `apps.simulated_trading` | `simulated_trading` | `simulated_trading_tools` | Y |
| Strategy | `apps.strategy` | `strategy` | `strategy_tools` | Y |
| Realtime | `apps.realtime` | `realtime` | `realtime_tools` | Y |
| Equity | `apps.equity` | `equity` | `equity_tools` | Y |
| Fund | `apps.fund` | `fund` | `fund_tools` | Y |
| Sector | `apps.sector` | `sector` | `sector_tools` | Y |
| Factor | `apps.factor` | `factor` | `factor_tools` | Y |
| Rotation | `apps.rotation` | `rotation` | `rotation_tools` | Y |
| Hedge | `apps.hedge` | `hedge` | `hedge_tools` | Y |
| Alpha | `apps.alpha` | `alpha` | `alpha_tools` | Y |
| Filter | `apps.filter` | `filter` | `filter_tools` | Y |
| Asset Analysis | `apps.asset_analysis` | `asset_analysis` | `asset_analysis_tools` | Y |
| Sentiment | `apps.sentiment` | `sentiment` | `sentiment_tools` | Y |

## Governance / Ops Modules

| Module | Django App | SDK Module | MCP Tools | Status |
|---|---|---|---|---|
| AI Provider | `apps.ai_provider` | `ai_provider` | `ai_provider_tools` | Y |
| Prompt | `apps.prompt` | `prompt` | `prompt_tools` | Y |
| Audit | `apps.audit` | `audit` | `audit_tools` | Y |
| Events | `apps.events` | `events` | `events_tools` | Y |
| Decision Rhythm | `apps.decision_rhythm` | `decision_rhythm` | `decision_rhythm_tools` | Y |
| Beta Gate | `apps.beta_gate` | `beta_gate` | `beta_gate_tools` | Y |
| Alpha Trigger | `apps.alpha_trigger` | `alpha_trigger` | `alpha_trigger_tools` | Y |
| Dashboard | `apps.dashboard` | `dashboard` | `dashboard_tools` | Y |
| Task Monitor | `apps.task_monitor` | `task_monitor` | `task_monitor_tools` | Y |

## OpenAI Compatibility

- Adapter: `apps.ai_provider.infrastructure.adapters.OpenAICompatibleAdapter`
- Modes:
  - `dual` (Responses first, fallback to Chat)
  - `responses_only`
  - `chat_only`
- Config fields (`AIProviderConfig`):
  - `api_mode`
  - `fallback_enabled`
- Env overrides:
  - `AGOMTRADEPRO_OPENAI_API_MODE`
  - `AGOMTRADEPRO_OPENAI_FALLBACK_ENABLED`

## Remaining Work

- SDK endpoint contract tests for新增治理模块已扩展到主要 CRUD/动作路径；后续新接口按同模板补入。
- MCP execution smoke and RBAC matrix have been expanded for newly added governance tools; keep adding cases for future tool groups.
