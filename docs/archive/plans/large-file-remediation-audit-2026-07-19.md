# Large-file risk remediation — audit batch 2026-07-19

## Completed

- Split `apps/audit/domain/services.py` (1299 non-empty lines) into four pure-Python owner modules behind a bounded compatibility facade:
  - `attribution_services.py` — heuristic attribution pipeline (`analyze_attribution` and its private helpers) plus the `AttributionAnalyzer` class.
  - `brinson_services.py` — standard Brinson attribution (`calculate_brinson_attribution`, weighted/average return helpers, monthly period breakdown).
  - `performance_services.py` — indicator performance evaluation (`IndicatorPerformanceAnalyzer`) and batch `ThresholdValidator`.
  - `operation_log_services.py` — `OperationLogFactory` for MCP/API operation audit log entities.
- Split `apps/audit/infrastructure/repositories.py` (1357 non-empty lines) into four mixin owner modules behind a bounded compatibility facade; the facade composes the mixins into the legacy `DjangoAuditRepository` class:
  - `attribution_repositories.py` — `AttributionRepositoryMixin`: attribution reports, loss analyses, experience summaries, and the database health probe.
  - `indicator_repositories.py` — `IndicatorRepositoryMixin`: indicator performance records, threshold configs, and cross-module read wrappers (macro facts, regime logs).
  - `validation_repositories.py` — `ValidationRepositoryMixin`: threshold validation summary records.
  - `operation_log_repositories.py` — `OperationLogRepositoryMixin`: operation logs, statistics, retention cleanup, and decision-trace aggregation.
- Split `apps/audit/application/use_cases.py` (1382 non-empty lines) into three owner modules behind a bounded compatibility facade:
  - `attribution_use_cases.py` — attribution report generation and audit summary use cases, owning the shared `RECOVERABLE_AUDIT_USE_CASE_EXCEPTIONS` tuple.
  - `indicator_use_cases.py` — indicator performance evaluation, threshold validation, and dynamic weight adjustment use cases.
  - `operation_log_use_cases.py` — MCP/SDK operation log write/query/detail/export/stats use cases.
- Preserved every established import and monkeypatch path:
  - `apps.audit.domain.services` re-exports all service classes/functions, the twelve entity re-exports (e.g. `AttributionConfig`, `SignalEvent`), and the eleven private helpers imported by `tests/unit/domain/audit/test_attribution_services.py`.
  - `apps.audit.infrastructure.repositories` keeps `DjangoAuditRepository` at the legacy path as the composition of the four mixins, so the `apps.audit.infrastructure.providers` star-import and all class-attribute patches keep working; all 53 legacy methods verified bound.
  - `apps.audit.application.use_cases` re-exports all 30 request/response/use-case classes plus `RECOVERABLE_AUDIT_USE_CASE_EXCEPTIONS`; the class-method patch path `apps.audit.application.use_cases.GenerateAttributionReportUseCase._build_asset_returns` (used by `tests/integration/audit/test_api_endpoints.py`) resolves to the same class object.
- Added `tests/unit/test_audit_structure.py` structure contracts: export identity against owner modules, explicit facade `__all__` coverage, repository mixin composition/MRO and the full 53-method legacy surface, AST assertions that the domain facade and owners import zero `django`/`pandas`/`numpy`/`requests`, per-module non-empty-line budgets, and one-way dependency checks (owners must not import their facades, absolute or relative forms).
- Extraction was mechanical: every top-level block was cut from the originals and re-joined unchanged; a script verified each function/class/constant source segment is byte-identical to `HEAD` (single intentional exception below). No database schema, route, API payload, or Celery task name changes.

## Remaining

- The three remediated paths must be removed from `allowed_large_python_files` / `large_file_remediation` in `governance/governance_baseline.json`; the machine-baseline update is handled centrally by the main agent, not by this batch (batch instructions forbid editing it).
- The shared static test-function count baseline needs a rebase for the five new structure contract tests (also handled centrally).
- One intentional content delta: `_build_decision_trace_summary` now references `OperationLogRepositoryMixin._build_step_summary` instead of `DjangoAuditRepository._build_step_summary` (static method, same code, keeps the one-way rule — owners must not import the facade).
- The interleaved method order of the legacy repository class changed (methods regrouped by mixin); method resolution and signatures are unchanged.

## Regression scope

- Structure contracts: `tests/unit/test_audit_structure.py`.
- Audit unit suites: `test_audit_domain.py`, `test_audit_failure_counter.py`, `test_audit_health_check.py`, `test_audit_permissions.py`, `test_check_mcp_write_audit.py`, `tests/unit/application/audit/`, `tests/unit/domain/audit/`.
- Cross-module consumer suites: `tests/unit/domain/simulated_trading/` (imports `ThresholdValidator`), `tests/unit/core/test_decision_context.py` (lazy use-case import), agent-runtime audit-service consumers (`test_agent_runtime_m2_mcp.py`, `test_agent_runtime_m2_sdk.py`, `test_agent_runtime_m4_regression.py`, `test_mcp_proposal_execution.py`).
- Audit integration suites: `tests/integration/audit/` (6 files, including the API-endpoint suite that patches the legacy use-case path), `tests/integration/test_audit_api.py`, `tests/integration/test_audit_internal_ingest.py`, and `tests/integration/backtest/test_backtest_execution.py` (imports `GenerateAttributionReportResponse`).
- Architecture layer guard: `tests/unit/test_architecture_guard_regressions.py`.
- Migration-state check for the `audit` app and Ruff lint over `apps/audit`.

## Verified

- Structure contracts: `5 passed`.
- Audit + consumer unit regression: `288 passed` (includes the 5 structure contracts; `test_audit_failure_counter.py` re-run separately after the facade lint fix: `20 passed`).
- Domain/application/structure re-run after the Ruff-driven facade reformat: `204 passed`.
- Audit integration regression: `81 passed`; backtest-execution + agent-runtime consumers: `90 passed`.
- Architecture guard: `1 passed`.
- `python manage.py makemigrations audit --check --dry-run` reported `No changes detected in app 'audit'`.
- `ruff check apps/audit tests/unit/test_audit_structure.py` — all batch files clean; one pre-existing, unrelated failure remains in `apps/audit/infrastructure/metrics.py:26` (`I001` import sorting; file untouched by this batch, confirmed via `git status`).
- Facade sizes (non-empty lines): domain services 86, repositories 27, use cases 77. Largest owner: `attribution_use_cases.py` at 521 (budget 650); every owner within its budget.
- Manual runtime probes confirmed: the legacy class-method patch path resolves, `apps.audit.infrastructure.providers` star-import exposes the same composed class object, domain facade private-helper imports work, and all spot-checked legacy repository methods are bound.
- Split fidelity: an AST segment-by-segment comparison against `HEAD` reported `OK: all top-level segments identical to HEAD` for all three files (with the single documented mixin-reference exception).

## Risks and rollback

- The repositories facade defines the composed `DjangoAuditRepository` directly (a new class object at the legacy path). Code holding a reference to the pre-split class object across the refactor would see a different identity, but no such long-lived references exist in the codebase; all imports resolve the current object.
- `apps.audit.infrastructure.providers` (`from .repositories import *`) now re-exports only `DjangoAuditRepository` via the explicit facade `__all__`; previously leaked incidental names (`logging`, `date`, ORM model classes) are no longer re-exported. The sole consumer (`repository_provider.py`) imports exactly `DjangoAuditRepository`.
- The pre-existing `I001` in `apps/audit/infrastructure/metrics.py` is reported but intentionally not fixed (out of batch scope).
- The full repository test suite, strict mypy, and the fixed minimum regression package (TUI/terminal/SDK/SSL) were not executed; this batch does not touch those chains.
- Governance CI will report the three remediated audit paths as stale large-file allowances and a static test-count mismatch until the main agent rebases the machine baseline.
- Roll back by reverting the three facades and all eleven owner modules together with `tests/unit/test_audit_structure.py`, then rerunning the audit focused regression sets listed above.
