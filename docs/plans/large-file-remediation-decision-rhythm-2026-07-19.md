# Large-file remediation — Decision Rhythm domain services — 2026-07-19

## Stage objective

This batch continues the Decision Rhythm large-file remediation line recorded in `docs/plans/large-file-remediation-2026-07-14.md`. It splits the remaining over-threshold pure-Python module, `apps/decision_rhythm/domain/services.py`, into focused domain owners while preserving the established import and patch surface. The machine-readable source for allowances and thresholds remains `governance/governance_baseline.json`; this document intentionally does not copy live line counts.

## Completed

- Split `apps/decision_rhythm/domain/services.py` into four focused Domain owners by responsibility: rhythm/quota scheduling (`rhythm_services.py`), precheck results and workflow state machines (`workflow_services.py`), valuation pricing / recommendation consolidation / execution approval (`valuation_services.py`), and unified-recommendation model parameters / composite scoring / aggregation (`unified_services.py`).
- The original domain service module is now a thin compatibility facade with an explicit `__all__` covering every previously public symbol (23 names); all facade exports are identity-equal to their owner-module definitions, so existing import and monkeypatch paths keep working.
- `ExecutionApprovalService` depends on `ApprovalStatusStateMachine` through a one-way owner-to-owner import (`valuation_services` -> `workflow_services`); no owner imports the facade.
- Domain purity is preserved: every owner and the facade import only the Python standard library and sibling domain modules; no django/pandas/numpy/requests imports were introduced.
- The Decision Rhythm repository split (`rhythm_repositories`, `recommendation_repositories`, `unified_repositories` behind the thin `repositories.py` facade) was already closed in the previous batch and is unchanged here.
- Extended `tests/unit/test_decision_rhythm_repositories_structure.py` so one contract module now guards both splits: export identity against the facade, explicit owner export surfaces, per-module non-empty-line budgets, one-way dependency (owners must not import the facade, absolute or relative), and an AST-based ban on django/pandas/numpy/requests imports in the domain-side modules.

## Remaining

- `governance/governance_baseline.json` allowance/remediation entries for the remediated path are updated centrally by the main agent, not in this batch.
- The remaining Decision Rhythm / Data Center large-file allowances tracked in the machine baseline stay separate P1/P2 work packages with independent compatibility tests and rollback points.
- Two pre-existing Ruff I001 import-sort findings in `apps/decision_rhythm/application/query_services.py` and `apps/decision_rhythm/infrastructure/feature_providers.py` predate this batch (untouched files) and remain outside its scope.

## Regression scope

- New structure contract covering both the repository split and the domain-services split: export identity, line budgets, one-way dependency, and domain import purity.
- Focused behavior regression: `tests/unit/decision_rhythm`, `tests/unit/test_decision_rhythm_services.py`, `tests/unit/test_decision_rhythm_workflow_use_cases.py`, `tests/unit/test_decision_rhythm_reverse_dependencies.py`, and `tests/unit/test_decision_rhythm_models_structure.py`.
- Supplementary domain-service consumers: `tests/unit/test_model_param_services.py` plus the use-case and entity structure contracts.
- Django migration-state check for the `decision_rhythm` app (no model, schema, route, API, or Celery task contract changed).

## Verified

- New structure contract: `2 passed` (`tests/unit/test_decision_rhythm_repositories_structure.py`).
- Focused Decision Rhythm regression: `48 passed`.
- Supplementary model-parameter and structure contracts: `29 passed`.
- `python manage.py makemigrations decision_rhythm --check --dry-run`: `No changes detected in app 'decision_rhythm'`.
- `ruff check apps/decision_rhythm/domain tests/unit/test_decision_rhythm_repositories_structure.py`: all checks passed; the only remaining findings under `apps/decision_rhythm` are the two pre-existing I001 items listed above.

## Risks and rollback

- The main risk is import-surface drift, because Application, Interface, Infrastructure, and test modules import domain services through the legacy module path. The facade keeps the original module as the single import/patch surface, and the structure contract asserts identity equality for every export.
- The full repository test suite and strict mypy run were not executed in this batch.
- Roll back by reverting the four owner modules, the facade `services.py`, and the added structure-contract test together; no model, migration, API, route, or Celery task contract changed, so no data or deployment rollback is required.
