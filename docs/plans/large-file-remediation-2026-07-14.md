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
- Broker Execution persistence now composes focused access, Agent runtime, management, and reconciliation owners behind the original repository class.
- Strategy interface-facing ORM queries now live in a focused repository owner while the legacy repository import remains stable.
- TUI workbench result rendering now composes collection and detail owners while preserving the public result-model mixin.
- AI Capability catalog routing services and read-only catalog queries now have focused Application owners behind the established use-case exports.
- Simulated Trading inspection persistence now has a focused Infrastructure owner while the repository/provider re-export path remains stable.
- Every remediated path was removed from both the allowance and remediation maps; both maps are now empty.

## Remaining scope

There are no tracked large-file allowances after the 2026-07-28 closure. Any production Python file that exceeds the repository-wide threshold must now be decomposed or enter a separately reviewed remediation plan; this stage must not be reopened merely to raise the machine baseline.

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
- Any future large-file split remains an independent work package with compatibility tests and a module-level rollback point.
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

## 2026-07-28 final allowance closure

### Completed

- Split `apps/broker_execution/infrastructure/repositories.py` into four bounded mixin owners for scoped access, Agent operations, management/configuration, and reconciliation/live-order creation. The original module remains the concrete compatibility class.
- Split `StrategyInterfaceRepository` into `apps/strategy/infrastructure/strategy_interface_repository.py` with an intentional legacy re-export.
- Split TUI chart/datagrid and detail/message rendering into two bounded result-model mixins while retaining `TuiWorkbenchResultModelMixin` as the public composition point.
- Split AI Capability catalog routing services and catalog query use cases into two focused Application modules while retaining symbol identity and the legacy sync-loader patch surface.
- Split `DjangoInspectionRepository` into `apps/simulated_trading/infrastructure/inspection_repository.py` and preserved both repository and provider import paths.
- Added a five-part structure contract covering symbol identity, mixin composition, one-way owner dependencies, and tighter per-file non-empty-line budgets.
- Removed the final AI Capability, Broker Execution, and Simulated Trading entries from `allowed_large_python_files` and `large_file_remediation`; the machine baseline now reports no large-file violations or allowances.

### Verified

- Structure contract: `5 passed`.
- Broker Execution, Strategy, AI Capability, and Simulated Trading focused behavior regression: `183 passed`.
- TUI result-model focused behavior regression: `11 passed`.
- Fixed high-risk regression package (`test_tui_workbench`, Terminal Agent service, SDK client, internal SSL redirect): `278 passed`.
- Incremental mypy: no issues in 15 changed production files; full mypy debt ceiling passed at the existing ceiling (`2108` errors in `478` files).
- Governance consistency: `0` violations, including `large_python_files` and `large_file_remediation`.
- `makemigrations --check --dry-run` reported no changes for Broker Execution, Strategy, and Simulated Trading.
- Django system check, Python compilation, Ruff, Black, and isort passed for the changed batch.
- Architecture guardrail selection passed `24/25`; the remaining failure is the pre-existing module-dependency budget drift (`200` observed edges versus the `196` baseline, including Terminal's existing outbound budget). This batch adds no new cross-App dependency target and does not raise that unrelated baseline.

### Unverified risks and rollback

- The full repository pytest suite was not run; verification is limited to the focused module suites, the fixed high-risk package, structure contracts, and governance/type/format gates listed above.
- The existing module-dependency budget drift requires a separate architecture-governance mainline; it must not be hidden by increasing the baseline as part of this large-file-only batch.
- Roll back each module independently by reverting its facade/owner modules and the structure contract assertions. Any rollback that reintroduces an over-limit file must also restore reviewed remediation metadata before merge; no model, migration, route, API payload, TUI key, or Celery task name changed in this batch.
