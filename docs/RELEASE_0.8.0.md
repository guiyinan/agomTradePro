# AgomTradePro 0.8.0 Release Notes

> **Version**: `0.8.0`
> **Build**: `20260705`
> **Release date**: `2026-07-05`

## Summary

`0.8.0` is the release-closure version for the long post-`0.7.0` development snapshot line.

This release does not add a new major business module. It formalizes the current platform into a public release by closing version drift, operations drift, and one major TUI runtime debt hotspot.

## What changed

### 1. Release baseline

- Unified runtime version to `0.8.0-build.20260705`
- Aligned `core/version.py`, `pyproject.toml`, `AGENTS.md`, `README*`, `docs/INDEX.md`, `docs/VERSION.md`, and `docs/governance/SYSTEM_BASELINE.md`

### 2. Operations closure

- `task_monitor` is no longer tracked as an unfinished capability
- Standardized readiness commands, evidence paths, and pass criteria
- Documented both local strict acceptance and VPS scheduler-clean acceptance

### 3. Production posture

- Formal production database recommendation is now explicitly `PostgreSQL`
- `SQLite` remains the lightweight local/demo/migration path, not the formal production default

### 4. Architecture debt reduction

- Split runtime TUI metadata responsibilities out of `apps/terminal/infrastructure/tui_metadata_repository.py`
- Continued the split by moving runtime injection constants into feature-scoped modules plus a bundle registry
- Continued again by moving runtime screen patches and action patches into feature-scoped modules plus structured registries
- Split `apps/terminal/application/tui_workbench.py` into a thinner service shell plus dedicated constants, catalog helpers, and result-model helpers
- Split personal readiness status/window management commands into thinner wrappers plus focused management helpers
- Continued shrinking `core/integration` after the `0.8.0` cut by retiring strategy/simulated-trading-only bridges such as `simulated_trading_facade`, `decision_exit_advisor`, `share_context`, `rotation_accounts`, `watchlist_assets`, `asset_names`, `runtime_benchmarks`, `current_regime`, `decision_data_reliability`, `strategy_prompt_providers`, `alpha_homepage`, `alpha_runtime`, `realtime_polling`, `realtime_prices`, `pulse_refresh`, `audit_reports`, `factor_runtime`, `akshare_sdk`, `user_lookup`, `capability_routing`, `asset_proxy_map`, `market_index_returns`, `alpha_triggers`, `signal_reevaluation`, `alpha_scores`, `decision_requests`, `manual_trade_sync`, `alpha_candidates`, and `account_positions` in favor of direct owning-app application/query services
- Removed the historical large-file governance exception for `apps/terminal/application/tui_workbench.py` after it dropped below the 1200-line limit
- Removed the historical large-file governance exceptions for the two readiness command files after the split
- Preserved the runtime repository contract while reducing the central file size and risk concentration
- Kept `core/integration` bridge-debt counters at zero under governance ratchets

## Upgrade note

Local-first usage is unchanged:

- setup wizard still works
- SQLite local development still works
- lightweight preview still works

The main release difference is the **formal production recommendation and acceptance posture**, not a removal of the lightweight local path.

## Related docs

- [VERSION.md](VERSION.md)
- [governance/SYSTEM_BASELINE.md](governance/SYSTEM_BASELINE.md)
- [operations/runbook.md](operations/runbook.md)
- [testing/0.8.0-release-regression-report-2026-07-05.md](testing/0.8.0-release-regression-report-2026-07-05.md)
