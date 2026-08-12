# Large-file risk remediation — strategy interface views batch 2026-07-19

## Completed

- Split `apps/strategy/interface/views.py` (1294 non-empty lines) into six focused owner modules behind a bounded compatibility facade (75 non-empty lines):
  - `page_views.py` (444 non-empty lines) — HTML page flow: script/AI/position-rule form constants, private form parsing/building/saving helpers, and the five page endpoints (`strategy_list`, `strategy_create`, `strategy_detail`, `strategy_edit`, `strategy_toggle_status`).
  - `execution_views.py` (366 non-empty lines) — execution and sandbox-testing JSON endpoints (`strategy_execute`, `execution_evaluate`, `test_script`, `test_strategy`).
  - `strategy_api_views.py` (234 non-empty lines) — strategy aggregate DRF viewsets (`StrategyViewSet` including the SDK-contract mixin composition, `ScriptConfigViewSet`, `AIStrategyConfigViewSet`).
  - `assignment_api_views.py` (170 non-empty lines) — `PortfolioStrategyAssignmentViewSet` plus the `bind_strategy`/`unbind_strategy` JSON endpoints.
  - `rule_api_views.py` (109 non-empty lines) — `PositionManagementRuleViewSet` and `RuleConditionViewSet`.
  - `execution_log_api_views.py` (88 non-empty lines) — read-only `StrategyExecutionLogViewSet`.
- Preserved every established import and monkeypatch path:
  - `apps.strategy.interface.views` re-exports all 18 legacy public symbols (7 DRF viewsets, 5 HTML page views, `strategy_execute`, `test_strategy`, `execution_evaluate`, `test_script`, `bind_strategy`, `unbind_strategy`) with object identity to the owner modules; `urls.py` and `api_urls.py` are unchanged.
  - The facade keeps all seven `django_apps.get_model` ORM aliases (`StrategyModel`, `PortfolioStrategyAssignmentModel`, …) so the legacy patch path `apps.strategy.interface.views.PortfolioStrategyAssignmentModel._default_manager.select_for_update` used by the binding-consistency integration suite keeps resolving; the patched attribute is on the globally shared model class, so behavior is identical.
  - The facade docstring records that the strategy create/edit bind paths still wrap their multi-save blocks in `with transaction.atomic()` in the owner modules, keeping the static write-path guardrail input stable.
- Added `tests/unit/test_strategy_views_structure.py` structure contracts: export identity to owner modules, explicit facade `__all__` set, ORM-alias identity plus the exact legacy dotted patch path, per-module non-empty-line budgets, and one-way dependency checks (owner modules must not import the facade, including relative-import forms).
- No database schema, route, API payload, template key, or Celery task name changes. The full URL table for the `strategy/` and `api/strategy/` trees (86 routes: URL paths plus route names) was captured before and after the split and is byte-identical.
- Owner modules import no `infrastructure` symbol and contain no direct `.objects.` ORM access; the interface-layer architecture red line is preserved.

## Remaining

- The remediated path must be removed from `allowed_large_python_files` and `large_file_remediation` in `governance/governance_baseline.json`; the machine-baseline update is handled centrally by the main agent, not by this batch.
- The shared static test-function count baseline needs a +3 rebase for the new structure contract tests (also handled centrally).
- Pre-existing code smells inside the moved bodies (duplicate `@login_required` on `strategy_list`, redundant in-function `import json` style, broad `except Exception` handlers) were moved verbatim and remain out of scope for this large-file-only batch.

## Regression scope

- Structure contracts: `tests/unit/test_strategy_views_structure.py`.
- Strategy unit suites: `tests/unit/strategy/` (allocation service, external providers, order-intent repository, order state machine) and `tests/unit/test_prompt_strategy_dependency.py`.
- Strategy integration suites: `tests/integration/strategy/` (binding consistency including the legacy facade patch path, execute flow, page save flow) and `tests/integration/test_strategy_auto_trading_integration.py`.
- Strategy API edge suite: `tests/api/test_strategy_api_edges.py` (SDK contract actions, bind/unbind, execution evaluate).
- Static guardrails reading `apps/strategy/interface/views.py`: `tests/guardrails/test_consistency_write_guardrails.py`, `tests/guardrails/test_no_501_on_primary_paths.py`, plus `tests/unit/ci/test_select_tests.py` which references the path.
- Migration-state check for the `strategy` app, Ruff lint over `apps/strategy`, and a full before/after URL-table diff.

## Verified

- Structure contracts: `3 passed` (re-confirmed after lint fixes).
- Strategy focused unit regression: `20 passed`.
- Strategy integration + API-edge regression: `40 passed`.
- Static guardrails + CI test-selection suite: `57 passed`.
- Post-lint-fix combined re-run (structure + integration/strategy + API edges): `34 passed`; post-lint-fix re-run of the unit, auto-trading integration, guardrail, and CI test-selection suites: `86 passed`.
- `python manage.py makemigrations strategy --check --dry-run` reported `No changes detected in app 'strategy'`.
- `ruff check apps/strategy tests/unit/test_strategy_views_structure.py` passed (`All checks passed!`); the only fixes applied were import sorting and removal of redundant in-function `import json` re-imports in the newly created owner modules.
- Facade size: 75 non-empty lines (budget 150); every owner module is within its budget (largest owner: `page_views.py` at 444 non-empty lines, budget 600).
- URL-table probe: 86 strategy routes identical before and after the split.

## Risks and rollback

- `assignment_api_views.py` imports the private `_json_error` helper from the sibling owner `page_views.py` to avoid duplicating the shared JSON error shape; the one-way rule (no owner imports the facade) is enforced by the structure contracts, and sibling imports do not create a cycle.
- The facade keeps the seven ORM model aliases purely as a monkeypatch surface; new code must not import models from the facade for real data access (the interface-layer guard forbids infrastructure imports, and the aliases resolve through `django_apps.get_model` exactly as before).
- Incidental names previously importable from `apps.strategy.interface.views` (e.g. `json`, `logging`, DRF helpers) are no longer re-exported; a full-repo grep confirmed no consumer relied on them.
- The full repository test suite, strict mypy, and the fixed minimum regression package (TUI/terminal/SDK/SSL) were not executed; this batch does not touch those chains.
- Governance CI will report the remediated strategy path as a stale large-file allowance and a static test-count mismatch until the main agent rebases the machine baseline.
- Roll back by reverting the facade and all six owner modules together with `tests/unit/test_strategy_views_structure.py`, then rerunning the regression sets listed above.
