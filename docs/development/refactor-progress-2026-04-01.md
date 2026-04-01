# Refactor Progress 2026-04-01

## Completed

### policy.interface

- Split mixed `interface/views.py` into:
  - `event_api_views.py`
  - `rss_api_views.py`
  - `audit_api_views.py`
  - `workbench_api_views.py`
  - `page_views.py`
- Kept `views.py` as a compatibility re-export layer to avoid breaking existing imports.
- Updated `api_urls.py` to import API views from dedicated API modules.
- Updated `urls.py` to import HTML views from `page_views.py`.

### account.interface

- Split oversized `interface/api_views.py` into:
  - `portfolio_api_views.py`
  - `transaction_api_views.py`
  - `profile_api_views.py`
  - `observer_api_views.py`
- Kept `api_views.py` as a compatibility re-export layer to avoid breaking existing imports.
- Updated `api_urls.py` to bind routes from the new subdomain-focused modules.

### decision_rhythm.interface

- Split mixed `interface/views.py` into:
  - `core_api_views.py`
  - `workflow_api_views.py`
  - `page_views.py`
- Created `interface/api_urls.py` so API routes are no longer mixed with page routes.
- Reduced `interface/urls.py` to page routes plus `include("...api_urls")`.
- Kept `views.py` as a compatibility re-export layer to avoid breaking existing imports.

### decision_rhythm.workspace_api

- Split oversized `interface/api_views.py` into:
  - `workspace_api_support.py`
  - `valuation_api_views.py`
  - `workspace_execution_api_views.py`
  - `recommendation_api_views.py`
- Kept `api_views.py` as a compatibility re-export layer.
- Updated `decision_rhythm/interface/api_urls.py` to import concrete views from the new files.

### decision_rhythm.application cleanup

- Rewired `PrecheckDecisionView` to use existing `PrecheckDecisionUseCase` instead of duplicating checks in Interface.
- Added `CancelDecisionRequestUseCase` and `UpdateQuotaConfigUseCase` to move state transition and quota upsert logic out of Interface.
- Updated `workflow_api_views.py` to delegate cancel and quota-update flows to Application use cases.
- Added focused unit coverage in `tests/unit/test_decision_rhythm_workflow_use_cases.py`.

### decision_rhythm.submit workflows

- Added `application/submit_workflows.py` to own submit endpoint orchestration outside the Interface layer.
- Moved legacy single-submit persistence, unified recommendation sync, and candidate compaction behind `SubmitDecisionWorkflowUseCase`.
- Moved batch-submit request/response persistence behind `SubmitBatchWorkflowUseCase`.
- Simplified `interface/core_api_views.py` by delegating both submit endpoints to Application workflows and centralizing request DTO conversion.

### decision_rhythm.interface cleanup

- Added `interface/dependencies.py` to centralize use case, repository, and manager assembly for API views.
- Added `application/management_workflows.py` to move account-aware quota reset and trend-data generation out of Interface.
- Reworked `core_api_views.py` to delegate summary, reset, trend, and submit endpoints through dependency builders instead of inline assembly.
- Added dedicated request serializers for precheck, execute, cancel, quota-update, and trend query validation.
- Fixed submit request validation to accept `account_id`, matching the existing endpoint intent.

### decision_rhythm.read-side cleanup

- Added `application/query_workflows.py` to own quota/cooldown/request read orchestration outside the Interface layer.
- Added `application/page_workflows.py` to build HTML page context for quota overview and quota config pages without direct ORM access in views.
- Reworked `core_api_views.py` read-side viewsets to use query serializers plus application query workflows instead of direct repository calls.
- Reworked `page_views.py` to delegate account loading, quota aggregation, request/cooldown presentation shaping, and asset-name enrichment through application workflows.
- Added unit coverage for the new read/page workflows in `tests/unit/test_decision_rhythm_workflow_use_cases.py`.

### decision_rhythm.interface final cleanup

- Split the former `core_api_views.py` into focused modules:
  - `quota_api_views.py`
  - `cooldown_api_views.py`
  - `request_api_views.py`
  - `command_api_views.py`
  - `api_response_utils.py`
- Removed obsolete compatibility layers:
  - `apps/decision_rhythm/interface/core_api_views.py`
  - `apps/decision_rhythm/interface/views.py`
  - `apps/decision_rhythm/interface/api_views.py`
  - `apps/account/interface/api_views.py`
  - `apps/policy/interface/views.py`
- Updated tests to import the concrete decision-rhythm API modules directly instead of the deleted compatibility layer.
- Replaced `workspace_execution_api_views.py` and `valuation_api_views.py` star imports with explicit imports so private support helpers are no longer relied on implicitly.

### setup_wizard routing cleanup

- Kept both setup wizard API entry paths for compatibility (`/setup/api/` and `/api/setup/`).
- Changed the legacy `/api/setup/` include to use a distinct namespace so Django no longer reports duplicate `setup_wizard_api` namespaces during `manage.py check`.

### post-commit compatibility cleanup

- Updated non-simulated-trading frontends to use canonical unified account routes (`/api/account/accounts/*`) instead of the module-native simulated-trading alias.
- Fixed the dashboard main workflow account selector to read the current account-list response shape (`accounts`, `account_name`, `account_id`) while remaining tolerant of legacy payload keys.
- Synced the decision workspace guardrail tests with the canonical account route contract.

## Verification

- `python -m py_compile` on newly created interface modules
- `python manage.py check`
- `pytest tests/guardrails/test_no_501_on_primary_paths.py -q`
- `pytest tests/integration/policy/test_policy_api_contract.py -q`
- `pytest tests/integration/policy/test_policy_workbench_api.py -q`
- `pytest tests/integration/test_unified_account_api.py -q`
- `pytest tests/integration/simulated_trading/test_account_api_scope.py -q`
- `pytest tests/guardrails/test_decision_rhythm_api_error_mapping.py -q`
- `pytest tests/unit/test_decision_rhythm_workflow_use_cases.py -q`
- `pytest tests/unit/test_route_name_compatibility.py -q`
- `pytest tests/guardrails/test_decision_rhythm_api_error_mapping.py -q` (post submit-workflow refactor)
- `python manage.py check` (post submit-workflow refactor)
- `python -m py_compile apps/decision_rhythm/application/management_workflows.py apps/decision_rhythm/interface/dependencies.py apps/decision_rhythm/interface/core_api_views.py apps/decision_rhythm/interface/workflow_api_views.py apps/decision_rhythm/interface/serializers.py tests/unit/test_decision_rhythm_workflow_use_cases.py`
- `pytest tests/unit/test_decision_rhythm_workflow_use_cases.py -q` (post interface cleanup)
- `pytest tests/guardrails/test_decision_rhythm_api_error_mapping.py -q` (post interface cleanup)
- `pytest tests/integration/test_decision_execution_integration.py -q` (post interface cleanup)
- `python manage.py check` (post interface cleanup)
- `python -m py_compile apps/decision_rhythm/application/query_workflows.py apps/decision_rhythm/application/page_workflows.py apps/decision_rhythm/interface/dependencies.py apps/decision_rhythm/interface/core_api_views.py apps/decision_rhythm/interface/page_views.py apps/decision_rhythm/interface/serializers.py tests/unit/test_decision_rhythm_workflow_use_cases.py`
- `pytest tests/unit/test_decision_rhythm_workflow_use_cases.py -q` (post read-side cleanup)
- `pytest tests/guardrails/test_decision_rhythm_api_error_mapping.py -q` (post read-side cleanup)
- `pytest tests/integration/decision_platform/test_workflow.py -q` (post read-side cleanup)
- `python manage.py check` (post read-side cleanup)
- `pytest tests/integration/test_setup_wizard_api.py -q` (post setup-wizard namespace cleanup)
- `pytest tests/integration/test_decision_execution_approval_chain.py -q` (post concrete decision-rhythm import cleanup)
- `pytest tests/integration/test_transition_plan_api.py -q` (post explicit workspace support imports)
- `pytest tests/unit/test_route_name_compatibility.py -q`
- `python manage.py check` (final cleanup)

## Next Slice

- `decision_rhythm`
  - Consider reducing `workspace_api_support.py` by splitting valuation and transition-plan helpers into narrower support modules
