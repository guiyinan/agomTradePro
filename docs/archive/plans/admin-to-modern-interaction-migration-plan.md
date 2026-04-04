# Admin to Modern Interaction Migration Plan

## Objective

Reduce operational dependency on Django Admin by moving high-frequency workflows to productized UI pages and Streamlit-assisted operational interfaces.

## Implemented in this iteration

### 1. Unified operations entry

- Added `Settings Center` page:
  - Route: `/settings/`
  - View: `core.views.settings_center_view`
  - Template: `core/templates/ops/center.html`

### 2. Policy workflows migrated from Admin links

- New non-admin pages:
  - `/policy/events/new/`
  - `/policy/rss/manage/new/`
  - `/policy/rss/manage/<id>/edit/`
  - `/policy/rss/keywords/new/`
  - `/policy/rss/keywords/<id>/edit/`
- Replaced policy template admin links with above routes.

### 3. Macro datasource workflows migrated

- New non-admin pages:
  - `/macro/datasources/new/`
  - `/macro/datasources/<id>/edit/`
- Replaced datasource configuration page admin links.

### 4. Beta Gate and dashboard navigation de-adminized

- Replaced direct `/admin/beta_gate/...` links with product routes (`/beta-gate/version/`, `/beta-gate/test/`).
- Replaced global/nav admin links with `Settings Center`.

### 5. Beta Gate config edit loop completed

- Added non-admin create/edit/activate flows:
  - `/beta-gate/config/new/`
  - `/beta-gate/config/<config_id>/edit/`
  - `/beta-gate/config/<config_id>/activate/`
- Added JSON-form based `GateConfigForm` and product template `beta_gate/config_form.html`.
- Linked config/version pages to create/edit/activate actions.
- Fixed version compare page/API compatibility (`version1/version2` and `config_id` lookup fallback).

### 6. AI Provider detail edit loop completed

- Added non-admin edit page:
  - `/ai/detail/<provider_id>/edit/`
- Added form `AIProviderConfigForm` with JSON validation for `extra_config`.
- Added edit entry from provider detail page.
- Fixed provider detail template block syntax issue.

### 7. Validation and manager compatibility hardening

- Added integration tests:
  - `tests/integration/decision_platform/test_ops_modernized_flows.py`
  - Covers `ai_provider` edit form and `beta_gate` create/edit/activate + compare API path.
- Fixed `beta_gate` custom manager binding using standard model-level manager declaration (`objects = GateConfigManager()` / `objects = GateDecisionManager()`), and unified query usage to `.objects`:
  - `apps/beta_gate/infrastructure/models.py`
  - `apps/beta_gate/interface/forms.py`
  - `apps/beta_gate/interface/views.py`
- Unified active config query style in cross-module call sites to `GateConfigModel._default_manager.active().first()`:
  - `core/context_processors.py`
  - `core/views.py`
  - `apps/dashboard/interface/views.py`

## Remaining work (next iteration)

1. Add end-to-end/browser tests for newly introduced create/edit pages (policy + macro + beta_gate + ai_provider).
2. Update all documentation sections that still instruct users to operate via `/admin/`.

## Acceptance baseline

- High-frequency ops for Policy + Macro can be completed without entering Django Admin.
- Global user-facing templates no longer contain direct `/admin/` links except admin-doc management pages.
