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

## Completed batch 2

- `equity -> sector` was removed. Sector owns the market-returns gateway; Equity registers the index-return adapter while the existing Sector use case remains the consumer-facing entry point.
- `prompt -> strategy` was removed. Prompt owns the strategy-provider gateway; Strategy registers its provider builder and the original Prompt monkeypatch surface remains available.
- `events -> alpha_trigger` was removed. A `core.integration` registry holds the Alpha candidate repository factory; Alpha Trigger registers the provider during app startup and Events keeps its existing local compatibility proxy.
- The graph baseline was tightened by three edges and the three resolved bidirectional pairs were deleted from the allowlist.

## Completed batch 3

- `alpha -> decision_rhythm` was removed. Alpha owns a workspace-refresh gateway; Decision Rhythm registers the default-workspace refresh adapter while the existing workspace service remains the implementation owner.
- `alpha_trigger -> decision_rhythm` was removed. Alpha Trigger resolves execution references through its own gateway, backed by a Decision Rhythm adapter.
- `events -> decision_rhythm` was removed. Events retains its repository compatibility proxy while an app-neutral registry receives the Decision Rhythm repository factory at startup.
- `simulated_trading -> decision_rhythm` was removed. Simulated Trading owns the exit-advisor builder gateway and preserves the original task monkeypatch surface; Decision Rhythm registers its existing advisor implementation.
- Events exited the remaining cycle component, and all four resolved pairs and graph budgets were tightened in the same batch.

## Completed batch 4

- `data_center -> alpha` was removed. Data Center owns the Alpha runtime gateway; Alpha registers scope resolution and prediction task adapters while original Celery names and test patch paths remain unchanged.
- `data_center -> dashboard` was removed. Dashboard registers the Alpha homepage query adapter without exposing Dashboard internals to Data Center.
- `data_center -> pulse` was removed. Pulse registers its snapshot refresher, including the management-command path.
- `data_center -> realtime` was removed. Realtime registers latest-price fallback access, preserving the existing Data Center helper and Realtime monkeypatch surfaces.
- The former large cycle component split: Data Center, Dashboard, Config Center, Macro, Prompt, and Sector left all cycle components; the remaining debt is one smaller main component plus the isolated `pulse <-> regime` pair.

## Completed batch 5

- `pulse -> regime` was removed. Pulse owns a current-Regime gateway and Regime registers its existing resolver during startup, preserving the Pulse monkeypatch surface.
- The isolated `pulse <-> regime` component and its pair allowance were deleted; only the account-centered main cycle component remains.
- The total edge, Pulse outbound, Regime inbound, and global maximum inbound budgets were tightened together.

## Completed batch 6

- Account no longer imports Audit, Backtest, Equity, Factor, or Policy implementations. Account-owned gateways receive Backtest repositories, Equity market adapters, Audit logging, and Policy readiness providers from the owning apps.
- Cross-app cold-start model access now uses Django's app registry. Factor gained a standard `models.py` discovery bridge so its models are registered by the owning app instead of incidentally through Account imports.
- Alpha Trigger now registers its repository before Events initializes the event bus, removing the startup-order error exposed by the stricter provider registries.
- Five Account-centered pair allowances and their graph budgets were removed. The remaining Audit/Backtest pair split into a separate two-module component.

## Next batches

1. Remove the isolated `audit <-> backtest` pair and the remaining Policy/Signal and trading pairs.
2. Separate Account identity from the remaining Simulated Trading compatibility surface.
3. Empty both cycle allowlists and run `check_module_cycles.py --fail-on-cycles` without an allowlist.

## Regression and rollback

- Each dependency pair is independently revertible together with its exact allowlist and graph-budget reduction.
- Gateway fallbacks are side-effect free and preserve importability when the provider app is absent.
- Required checks include focused owner/consumer tests, architecture and governance audits, module-cycle checks, test collection, and the full unit suite before merge.
