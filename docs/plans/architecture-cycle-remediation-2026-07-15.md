# Architecture cycle remediation — 2026-07-15

## Objective

Eliminate the app-level bidirectional dependencies that regrew after the 2026-04-26 remediation. The machine-readable dependency graph and remaining accepted debt live in `governance/module_cycle_allowlist.json`; this plan records decisions and completed batches without duplicating changing counters.

## Dependency rule

- Cross-app runtime calls must have one owning direction.
- A consumer-facing Protocol or gateway belongs to the consumer; the provider app registers its adapter during `AppConfig.ready()`.
- Application and Interface code must not import another app's Infrastructure models or repositories.
- Removing a dependency edge requires tightening the total and per-app graph budgets in the same commit.
- No dynamic import, string import, or allowlist increase may be used to hide a cycle.

## Completed batch 1

- `ai_capability -> terminal` was removed. AI Capability owns a neutral Terminal gateway; Terminal registers repository, runtime-setting, and command-execution adapters. The product-facing `terminal -> ai_capability` direction remains.
- `asset_analysis -> signal` was removed. Asset Analysis owns a screening-context gateway; Signal registers the active-signal adapter. Asset-name resolution remains owned by Asset Analysis.
- `share -> simulated_trading` was removed. Share repositories receive a Share-owned account snapshot gateway; Simulated Trading registers the ORM-backed adapter. Share no longer imports simulated account models.

## Next batches

1. Remove leaf infrastructure/model reversals such as `equity <-> sector`, `prompt <-> strategy`, and `alpha_trigger <-> events`.
2. Remove event/repository reversals around Decision Rhythm.
3. Replace Data Center reverse calls to Alpha, Dashboard, Pulse, and Realtime with provider registries or owner facades.
4. Separate account identity from portfolio/trading dependencies and remove the account-centered cycle cluster.
5. Empty both cycle allowlists and run `check_module_cycles.py --fail-on-cycles` without an allowlist.

## Regression and rollback

- Each dependency pair is independently revertible together with its exact allowlist and graph-budget reduction.
- Gateway fallbacks are side-effect free and preserve importability when the provider app is absent.
- Required checks include focused owner/consumer tests, architecture and governance audits, module-cycle checks, test collection, and the full unit suite before merge.
