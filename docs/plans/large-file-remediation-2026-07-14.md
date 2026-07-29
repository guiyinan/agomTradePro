# Large-file risk remediation — 2026-07-14

## Stage objective

This stage applies behavior-preserving refactoring to the initial four highest-risk large-file allowances and separately accepted P1 continuations. The machine-readable source for current allowances, ownership, priorities, targets, and review dates remains `governance/governance_baseline.json`; this document intentionally does not copy live line counts.

## Completed scope

- Terminal identity/access runtime metadata now uses MCP, current-user AI provider, system AI provider, and quota owner shards. The original module is a compatibility aggregator.
- Dashboard Alpha homepage behavior is divided into exit-watch, runtime/readiness, candidate mapping, and history collaborators while `AlphaHomepageQuery` remains the public entry point.
- Dashboard HTTP views retain page orchestration and compatibility exports; Regime/Pulse, Alpha, and navigation/empty-state context helpers live in focused modules.
- Dashboard compatibility proxies preserve the original HTMX/history entries, query-factory and `AsyncResult` monkeypatch paths, factor-panel score loader, sizing-use-case patch surface, and decision-workspace URL helper without moving implementation back into `views.py`.
- Alpha Qlib Celery task definitions and aliases remain in Application. Initialization, prediction/cache, and artifact/training runtime work is delegated through the Application provider factory to Infrastructure modules.
- Account repositories now have focused profile/classification, portfolio, position, portfolio API, registration/profile, portfolio-access, and administration owners. The original repository module remains the compatibility export surface.
- Auto-advisor services now have focused serialization, contract, intent, execution, performance, provider, and decision-sheet owners. The original service module remains a controlled compatibility export surface.
- Decision Rhythm application use cases now have focused quota/submission, execution, workspace approval, model-parameter, and unified-recommendation owners. The original use-case module retains compatibility exports and its repository-provider monkeypatch surface.
- Decision Rhythm domain entities now have focused rhythm/quota, valuation/approval, portfolio-transition, unified-recommendation, and model-parameter owners. The original entity module remains the stable import surface.
- Decision Rhythm ORM models now have focused rhythm/request, valuation/approval, portfolio-transition, unified-recommendation/execution-link, and model-parameter owners. The original model module remains the stable Django import and patch surface, with no schema migration.
- Decision Rhythm repositories now have focused quota/request, valuation/recommendation/approval, and unified-recommendation/model-parameter owners. The original repository module is a thin stable import surface.
- Data Center application use cases now have focused provider/catalog, read-query, decision-reliability, fact-query, macro-governance, and provider-sync owners. The original use-case module is an explicit compatibility aggregator with bounded exports.
- Every remediated path was removed from both the allowance and remediation maps. Every remaining allowance has an owner, rationale, priority, target, review date, and this plan path.

## Remaining scope

The remaining allowances are not refactored in this stage. Their authoritative backlog is `large_file_remediation` in the governance baseline:

- AI Capability application orchestration is the only remaining allowance. It entered the P1 backlog on 2026-07-23 and requires responsibility-based decomposition that preserves its current public use-case facade.
- P1 items must be reviewed by 2026-09-30.
- P2 items must be reviewed by 2026-12-31.
- A reached review date fails governance CI until the file is remediated or its metadata is deliberately revised through review.
- Targets cannot exceed the repository-wide large-file threshold.

## Regression coverage

- Terminal metadata composition, TUI workbench, terminal service, SDK, and SSL redirect checks.
- Dashboard API edges, market thermometer, regression guardrails, Alpha end-to-end, and Regime/Pulse integration.
- Dashboard Alpha view/query suites exercise the original import and monkeypatch paths after the split, including refresh locking, history APIs, readiness, factor panels, and page-level query reuse.
- Qlib prediction, cache fallback, training, integration, and Celery registration aliases.
- Account registration, profile, portfolio, position, observer grant, sizing, Dashboard dependency, and API edge contracts.
- Auto-advisor decision-sheet, execution plan, recommendation attribution, Dashboard console, UI, weekly task, and API guardrail contracts.
- Decision Rhythm submission, execution, quota, model-parameter, unified-recommendation, workspace API, guardrail, and end-to-end contracts.
- Decision Rhythm entity construction, transition planning, approval chains, recommendation models, today queue ordering, and domain-service contracts.
- Decision Rhythm model registration, legacy imports, repositories, model-parameter initialization, transition persistence, and migration-state checks.
- Data Center provider/catalog management, canonical macro queries, quote freshness, decision-data repair, fact queries, macro governance, and all provider synchronization families.
- The managed live-server Playwright smoke suite runs against Chromium. A test-only Windows runtime guard ensures Playwright uses a subprocess-capable event-loop policy before pytest session fixtures start.
- Local structure contracts preserve the tighter stage-specific file budgets and reject reverse imports from extracted modules back to their compatibility entrypoints.
- Architecture rules, module cycles, governance consistency, formatting, import sorting, and test collection.

## Risks and rollback points

- Runtime imports and compatibility exports are the main risk because tests and adjacent interface modules patch legacy paths. Each original module therefore retains thin exports or aggregators.
- Celery task registration is kept in the original module; Infrastructure modules contain implementation only.
- Further large-file splits remain separate P1/P2 work packages and must retain independent compatibility tests and rollback points.
- Each responsibility split is independently revertible. If a regression is found, revert the corresponding split together with its baseline removal so governance remains internally consistent.
- No database schema, route, API payload, template key, TUI key, or Celery task name changes are part of this stage.

## 2026-07-18 P1 closure evidence

### Completed

- Split `apps/data_center/application/use_cases.py` into six focused Application owners while preserving the original import surface and public symbol identity.
- Split `apps/decision_rhythm/infrastructure/models.py` into five focused ORM owners while preserving Django app/model registration, table metadata, repository imports, and patch paths.
- Added one-way dependency and non-empty-line budget contracts for both compatibility aggregators and all new owner modules.
- Removed both remediated paths from `allowed_large_python_files` and `large_file_remediation` in the machine baseline.
- Split `apps/data_center/infrastructure/provider_adapters.py` into four bounded implementation owners behind a 26-line stable facade, added a structural size contract, and removed its P1 large-file exemption.

### Remaining

- Data Center provider-adapter convergence, legacy Macro adapter retirement, and the remaining Data Center/Decision Rhythm P1 allowances are separate work packages.
- Shared numeric parsing, dependency-source convergence, repository hygiene, documentation alignment, and mypy-debt reduction remain outside this large-file-only batch.

### Verified

- `ruff check` passed for all new aggregators, owner modules, and structure contracts.
- Python compilation passed for the affected Application and Infrastructure packages.
- Data Center focused behavior and structure regression: `38 passed`.
- Data Center unit, reverse-dependency, architecture, and governance run: `293 passed`; the only failure was the unrelated shared-worktree static test-count baseline mismatch described below.
- Decision Rhythm model/repository regression: `31 passed`.
- Decision Rhythm broader domain, application, persistence, API-edge, and guardrail regression: `101 passed`.
- `python manage.py makemigrations decision_rhythm --check --dry-run` reported no changes.
- Required minimum regression package passed: TUI workbench `218`, terminal agent service `11`, SDK client `22`, internal SSL redirect `2`.

### Unverified risks and rollback

- The full repository test suite and strict mypy run were not executed in this batch.
- This batch initially left the concurrent static-test count untouched; the later 2026-07-19 repository-governance batch audited the full working tree and rebased the shared count to `6969`.
- Roll back either split by reverting its aggregator and owner modules together, restoring its two machine-baseline entries, and rerunning the corresponding focused regression set.

## 2026-07-19 Decision Rhythm repository closure

### Completed

- Split `apps/decision_rhythm/infrastructure/repositories.py` into three responsibility owners behind a 50-non-empty-line compatibility facade.
- Preserved every existing repository class and convenience-factory import from the legacy module.
- Added one-way dependency, symbol-identity, and owner-size contracts; removed the remediated path from both machine-baseline maps.

### Verified

- Python compilation and Ruff passed for the facade and all three owners.
- Decision Rhythm model, repository, parameter, unified-recommendation, workspace, and execution-approval regression: `52 passed`.
- Fixed minimum regression package: TUI workbench, terminal agent service, SDK client, and SSL redirect, `253 passed`.

### Rollback

- Revert the facade, three owner modules, structural contract, and the paired baseline removal together. No model, migration, API, or task contract changed.

## 2026-07-19 P1/P2 closure evidence (equity, decision rhythm, data center)

### Completed

- Split `apps/equity/infrastructure/repositories.py` into eight focused owners (stock info, fundamentals, market data, intraday, asset, config, valuation repair, composition) and `apps/equity/interface/views.py` into six focused owners (page views, analysis actions, pool actions, valuation actions, multidim screen, valuation config); both originals stay bounded compatibility facades with explicit `__all__` and preserved patch surfaces. Details: `docs/plans/large-file-remediation-equity-2026-07-19.md`.
- Split `apps/decision_rhythm/domain/services.py` into four focused owners (rhythm, workflow, valuation, unified); the original module stays a pure-Python compatibility facade. Details: `docs/plans/large-file-remediation-decision-rhythm-2026-07-19.md`.
- Split `apps/data_center/infrastructure/repositories.py` into eight focused owners (catalog, macro fact, fundamental fact, market data, market breadth, provider state, thermometer, helpers) and `apps/data_center/application/market_thermometer.py` into six focused owners (specs, config, import, sync, calculate, runtime bridge). The macro-fact projection repository read/write split was evaluated and rejected (46 non-empty lines; split would add indirection without reducing complexity). Details: `docs/plans/large-file-remediation-data-center-2026-07-19.md`.
- Added structure contracts: `tests/unit/test_equity_structure.py`, `tests/unit/test_data_center_repositories_structure.py`, and domain-services assertions in `tests/unit/test_decision_rhythm_repositories_structure.py`.
- Removed all five remediated paths from `allowed_large_python_files` and `large_file_remediation` in the machine baseline.

### Verified

- Structure contracts: equity `4 passed`, data center `4 passed`, decision rhythm `2 passed`.
- Focused regressions: equity unit `177 passed`, equity integration/API `91 passed`, architecture guardrails `22 passed`; decision rhythm `48 passed` plus `29 passed`; data center `266 passed` plus reverse-dependency/architecture/patch-surface `40 passed` and thermometer API `7 passed`.
- `makemigrations --check --dry-run` for equity, decision_rhythm, data_center: no changes.
- `ruff check` passes for all three modules (two pre-existing I001 in decision_rhythm and one in a data_center migration fixed as whitespace-only).

### Unverified risks

- Full repository test suite and strict mypy were not run in this batch.
- Roll back each module split together with its structure contract, plan doc, and paired baseline entries.

## 2026-07-19 P1/P2 closure evidence (policy, account, audit, strategy) — final batch

### Completed

- Split `apps/policy/application/use_cases.py` (1567 non-empty lines) into four focused owners (event, RSS fetch, audit queue, workbench); original module stays a 104-line compatibility facade with 45 public symbols preserved. Details: `docs/plans/large-file-remediation-policy-2026-07-19.md`.
- Split `apps/account/infrastructure/models.py` (1389 non-empty lines) into five focused ORM owners (identity, classification, portfolio, trading config, documentation); all 22 Django model registrations and the `SystemSettingsModel` re-export preserved with zero migration drift. Details: `docs/plans/large-file-remediation-account-2026-07-19.md`.
- Split `apps/audit/application/use_cases.py`, `apps/audit/infrastructure/repositories.py`, and `apps/audit/domain/services.py` into eleven focused owners across the three layers; domain stays pure Python (AST-enforced), the repository facade composes the original class from four mixins with all 53 legacy methods bound. Details: `docs/plans/large-file-remediation-audit-2026-07-19.md`.
- Split `apps/strategy/interface/views.py` (1294 non-empty lines) into six focused owners (page, execution, strategy/assignment/rule/log APIs); the 86-route URL table is byte-identical and ORM-alias patch surfaces preserved. Details: `docs/plans/large-file-remediation-strategy-2026-07-19.md`.
- Added structure contracts: `tests/unit/test_policy_use_cases_structure.py`, `tests/unit/test_account_models_structure.py`, `tests/unit/test_audit_structure.py`, `tests/unit/test_strategy_views_structure.py`.
- Removed the final six paths from `allowed_large_python_files` and `large_file_remediation`; **the large-file allowance list is now empty**.

### Verified

- Structure contracts: policy `2 passed`, account `3 passed`, audit `5 passed`, strategy `3 passed`.
- Focused regressions: policy unit `130 passed` + integration `55 passed` + guardrails/cross-app `66 passed`; account unit `301 passed` + integration/API `253 passed`; audit unit `288 passed` + integration `81 passed` + consumers `90 passed`; strategy unit/API/guardrails `120 passed` with route-table diff empty.
- `makemigrations --check --dry-run` for all four modules: no changes.
- `ruff check` passes for account, audit, strategy module batches.

### Remaining and unverified risks

- ~~`apps/policy/infrastructure/repositories.py` retains 9 pre-existing ruff findings~~ **Closed 2026-07-19** by the dedicated lint batch (explicit `__all__` re-export contract + export contract test).
- `apps/audit/infrastructure/metrics.py` pre-existing I001 fixed as whitespace-only.
- Full repository test suite and strict mypy were not run in this batch.
- Roll back each module split together with its structure contract, plan doc, and paired baseline entries.

## 2026-07-25 Broker Execution and Strategy recurrence closure

### Why large files recurred

- The repository-wide 1200-line check detected debt only after a file crossed the hard limit. It provided no headroom signal for files already approaching the limit.
- Broker Execution kept one public repository class for authentication, access control, order lifecycle, Agent administration, reconciliation, and reporting. Successive contract fixes correctly stayed behind that repository boundary but continued appending unrelated responsibilities to one implementation file.
- Strategy retained a compatibility repository module and later appended `StrategyInterfaceRepository` to the same aggregator. The public import contract remained stable, but the implementation owner stopped being a bounded facade.
- Large-file allowances made debt visible and ratcheted growth, but they did not prevent a newly remediated file from approaching the threshold again. A red governance result also cannot substitute for protected-branch enforcement.

### Completed

- Split `DjangoBrokerExecutionRepository` into access, order-control, Agent runtime, Agent administration, and reconciliation/reporting mixins. The original module remains the stable public repository and retains `create_live_order`.
- Split `StrategyInterfaceRepository` into a focused module and explicitly re-exported it from the original Strategy repository module.
- Preserved all 46 Broker repository methods and all 41 Strategy interface methods; method ASTs remain behavior-equivalent to their pre-split definitions.
- Removed the resolved Broker Execution allowance and remediation entry. Ratcheted the remaining Simulated Trading allowance to its current non-empty line count.
- Added `scripts/check_changed_python_file_size.py` to reject production Python files that grow beyond 1000 non-empty lines. Existing large files may shrink, and renames compare against their original path.
- Wired the incremental headroom check into CI Fast Feedback before lint and mypy.

### Verification and rollback

- Focused Broker Execution and Strategy repository tests, architecture/governance checks, incremental mypy, formatting, and import sorting are required before merge.
- The full repository test suite remains outside this responsibility-only refactor.
- Roll back the Broker and Strategy splits together with the CI headroom guard and paired machine-baseline update. No model, migration, API, route, or payload change is intended.

## 2026-07-26 Simulated Trading repository closure

### Completed

- Replaced the unified simulated-ledger repository file with a bounded compatibility facade.
- Moved account, position/mutation, trade, daily-net-value, fee-config, and inspection persistence into six focused owner modules, with one small shared persistence helper.
- Preserved the ten legacy repository and Mapper exports by object identity through the original `repositories` module and the existing wildcard provider surface.
- Preserved all original class and helper ASTs, including transaction boundaries, QuerySet ordering, Decimal handling, and ORM conversion behavior.
- Added owner-specific line budgets and reverse-import checks.
- Removed the Simulated Trading allowance and remediation metadata from the machine baseline. AI Capability is now the only remaining approved large Python file.

### Verification and rollback

- Focused integration coverage includes account, position, trade, fee, daily-net-value, performance-curve, and strategy auto-trading consumers.
- Formatting, import sorting, architecture/governance checks, and incremental mypy are required before merge.
- Roll back the facade and all owner modules together with the structure contract and paired baseline removal. No model, migration, API, route, or payload change is part of this split.
