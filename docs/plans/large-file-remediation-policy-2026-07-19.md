# Large-file risk remediation — policy batch 2026-07-19

## Completed

- Split `apps/policy/application/use_cases.py` (1566 non-empty lines) into four focused owner modules behind a bounded compatibility facade:
  - `event_use_cases.py` — policy-event command/query orchestration (`CreatePolicyEventUseCase`, `UpdatePolicyEventUseCase`, `DeletePolicyEventUseCase`, `GetCurrentPolicyUseCase`, `GetPolicyStatusUseCase`, `GetPolicyHistoryUseCase`) plus their DTOs, the dependency-injection protocols (`AlertServiceProtocol`, `EventStoreProtocol`), and the shared `RECOVERABLE_POLICY_USE_CASE_EXCEPTIONS` tuple.
  - `rss_fetch_use_cases.py` — the RSS ingestion pipeline (`FetchRSSUseCase` with two-phase raw-record persistence, AI classification with keyword fallback, content extraction, audit-queue enqueueing, alerting) plus `FetchRSSInput`/`FetchRSSOutput`/`RSSSourceDetail`.
  - `audit_use_cases.py` — human review pipeline: `GetAuditQueueUseCase`, `ReviewPolicyItemUseCase`, `BulkReviewUseCase`, `AutoAssignAuditsUseCase` plus review DTOs.
  - `workbench_use_cases.py` — policy workbench summary/items queries, approve/reject/rollback/override event actions, and the sentiment gate state query.
- The facade `apps/policy/application/use_cases.py` (104 non-empty lines) re-exports all 45 legacy public symbols through an explicit `__all__`; every name resolves to the identical owner-module object (`is` identity pinned by the structure contract).
- One-way dependency shape: `event_use_cases` owns the shared protocols/exception tuple; `rss_fetch_use_cases`, `audit_use_cases`, and `workbench_use_cases` import only from `event_use_cases`, never from the facade (mirrors the `data_center` owner-to-owner precedent).
- Verified the import surface exhaustively before splitting: 20 import sites across `apps/policy` (interface views, admin, application services/tasks), `core/views.py`, `apps/dashboard`, `apps/beta_gate`, `apps/alpha_trigger`, and the test suites — all covered by the facade `__all__`. No `import *` consumers and no test monkeypatches the facade module namespace (all policy tests inject fakes through constructors), so no runtime bridge was needed.
- Added `tests/unit/test_policy_use_cases_structure.py` structure contracts: export identity per owner module, exact facade `__all__` coverage, per-module non-empty-line budgets, and a one-way AST check banning owner imports of the aggregator (absolute and relative forms).
- No database schema, route, API payload, template key, or Celery task name changes; import graphs of all legacy consumer modules verified by direct import probes.

## Remaining

- The remediated path must be removed from `allowed_large_python_files` and `large_file_remediation` in `governance/governance_baseline.json`; the machine-baseline update is handled centrally by the main agent, not by this batch.
- The shared static test-function count baseline needs a +2 rebase for the new structure contract tests (also handled centrally).
- ~~Pre-existing Ruff findings inside `apps/policy/infrastructure/` (8 `F401` in `repositories.py`, 1 `UP045` in `workbench_repositories.py`)~~ **Closed 2026-07-19** by the dedicated lint batch: `repositories.py` now declares an explicit 7-name `__all__` re-export contract consumed via the `providers.py` star import, dead imports were removed, and the surface is locked by `tests/unit/test_policy_repositories_export_contract.py`.
- Policy P1/P2 hardening beyond file size (e.g. the generic-repository fallback branch in `GetPolicyHistoryUseCase`) remains outside this large-file-only batch.

## Regression scope

- Structure contracts: `tests/unit/test_policy_use_cases_structure.py`.
- Policy unit suites: the whole `tests/unit/policy/` package (use cases, RSS fetch two-phase persistence, tasks, notification service, rules, hedging, RSS source bootstrap) plus `tests/unit/test_policy_rules.py`.
- Policy integration suites: `tests/integration/policy/` (API contract, event lifecycle integration, workbench API) and `tests/integration/test_workbench_use_cases.py`.
- Logic guardrails exercising `FetchRSSUseCase` two-phase no-data-loss behavior: `tests/guardrails/test_logic_guardrails.py`.
- Cross-app consumer suites touching `GetCurrentPolicyUseCase`/`GetPolicyStatusUseCase`: beta-gate and alpha-trigger unit suites.
- Architecture guardrails: `test_architecture_boundaries.py`, `test_architecture_tooling.py`, `test_architecture_guard_regressions.py`.
- Migration-state check for the `policy` app and Ruff lint over `apps/policy` and the new test file.

## Verified

- Structure contracts: `2 passed`.
- Policy focused unit regression (`tests/unit/policy` + rules + structure contracts): `130 passed`.
- Policy integration + workbench regression: `55 passed`.
- Logic guardrails: `12 passed`.
- Cross-app consumer regression (beta-gate ×2, alpha-trigger ×2 suites): `35 passed`.
- Architecture guardrails: `19 passed`.
- `python manage.py makemigrations policy --check --dry-run` reported `No changes detected in app 'policy'`.
- `ruff check` on the facade, the four owner modules, and the new structure test passed; repo-wide `ruff check apps/policy` still reports 9 pre-existing infrastructure findings listed under Remaining.
- Facade size: 104 non-empty lines (budget 150); owners: `event_use_cases.py` 527 (budget 800), `rss_fetch_use_cases.py` 548 (budget 800), `audit_use_cases.py` 193 (budget 300), `workbench_use_cases.py` 388 (budget 600).
- Import probes confirmed facade identity for all 45 exported symbols and clean imports of every legacy consumer module (`query_services`, `interface_services`, `tasks`, the three interface view modules, `core/views.py`).
- `tests/test_data_simple.py` and `tests/test_data_connections.py` reference the facade only inside `manage.py shell` diagnostic scripts; they are not pytest-collected and were not executed.

## Risks and rollback

- The total non-empty line count across facade + owners (1760) exceeds the former monolith (1566) because each owner carries its own imports/docstring/`__all__`; this is the accepted trade of the established split pattern.
- Log records now carry the owner module names instead of `apps.policy.application.use_cases`; no log-name-based routing exists in the codebase.
- `rss_fetch_use_cases`, `audit_use_cases`, and `workbench_use_cases` depend on `event_use_cases` for the shared exception tuple and protocols; any future move of those shared names must update all three owners.
- The full test suite, strict mypy, and the fixed minimum regression package (TUI/terminal/SDK/SSL) were not executed; this batch does not touch those chains.
- Governance CI will report the remediated policy path as a stale large-file allowance and a static test-count mismatch until the main agent rebases the machine baseline.
- Roll back by restoring the monolithic `apps/policy/application/use_cases.py` and deleting the four owner modules together with `tests/unit/test_policy_use_cases_structure.py`, then rerunning the regression sets listed above.
