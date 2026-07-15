# TUI Capability Access Redesign Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox items and must be completed in order.

**Goal:** Make the TUI capability router feel like a user-facing MCP access product: ordinary users can obtain and verify a complete connection package from one screen, while administrators get separate governance and debugging workspaces with explicit authorization and recovery behavior.

**Architecture:** Keep all business data access behind the existing Account and AI Capability application services. Extend published TUI metadata with explicit screen audiences, field presentations, and row actions; then make the workbench service, API boundary, and browser renderer enforce those contracts. Preserve every existing screen key while splitting the navigation modules into user access, admin governance, and admin debugging.

**Tech Stack:** Django 5, Django REST Framework, Python 3.11, JSON Schema, vanilla JavaScript/CSS, pytest, Playwright.

**Authoritative design:** `docs/superpowers/specs/2026-07-14-tui-capability-access-redesign.md`

**Execution status (2026-07-14):** Tasks 1-7 have been implemented and verified. The checklists below are retained as the original execution script; exact automated results, browser evidence, and remaining risks are recorded in `output/playwright/tui-capability-router-audit/audit-report.md`.

---

## Task 1: Publish explicit audiences, modules, and independent journeys

**Files:**

- Modify: `tests/unit/test_tui_metadata_compiler.py`
- Modify: `tests/unit/test_tui_workbench.py`
- Modify: `config/tui/schema/tui_metadata.schema.v3.json`
- Modify: `apps/terminal/application/tui_metadata.py`
- Modify: `apps/terminal/infrastructure/tui_metadata_runtime_injection_capability_router.py`
- Modify: `apps/terminal/infrastructure/tui_metadata_runtime_injection_identity_access.py`
- Modify: `apps/terminal/infrastructure/tui_metadata_runtime_injection_registry.py`

- [ ] **Step 1: Write failing metadata contract tests**

Add tests proving:

- `screen.audience` is required and accepts only `authenticated` or `admin`.
- The runtime registry publishes `mcp-access`, `mcp-governance`, and `capability-router-debug` with the labels and screen membership defined in the design.
- `capability-router.self-service` has an independent self-service journey and no shared step/total workflow.
- Governance and debug screens do not link to one another as numbered workflow steps.
- An authenticated non-admin catalog contains only the self-service screen from these modules; an admin catalog contains all four existing screen keys.

- [ ] **Step 2: Run the focused tests and confirm RED**

Run:

```powershell
pytest tests/unit/test_tui_metadata_compiler.py tests/unit/test_tui_workbench.py -q -k "audience or capability_router_modules or independent_journey"
```

Expected: failures because `audience` is not part of schema/validation and the four screens still share one module/workflow.

- [ ] **Step 3: Extend schema and Python metadata validation**

In both the JSON schema and `tui_metadata.py`:

- Add required `audience` to screen contracts.
- Restrict values to `authenticated` and `admin`.
- Ensure the compiler/defaulting path gives existing non-special screens an explicit safe value during migration, while emitted runtime metadata always contains the field.
- Keep audience independent from action-level risk and permission metadata.

- [ ] **Step 4: Split runtime navigation without renaming screens**

Publish these module assignments:

```text
mcp-access              -> capability-router.self-service
mcp-governance          -> capability-router.mcp-center, capability-router.admin-access
capability-router-debug -> capability-router.gateway
```

Set self-service to `authenticated`; set gateway, MCP center, and admin access to `admin`. Remove the shared 1/3, 2/3, 3/3 workflow sequence and retain only meaningful same-journey links.

- [ ] **Step 5: Run focused metadata tests and confirm GREEN**

Run the Step 2 command again. Expected: all selected tests pass.

- [ ] **Step 6: Commit the metadata contract slice**

```powershell
git add config/tui/schema/tui_metadata.schema.v3.json apps/terminal/application/tui_metadata.py apps/terminal/infrastructure/tui_metadata_runtime_injection_capability_router.py apps/terminal/infrastructure/tui_metadata_runtime_injection_identity_access.py apps/terminal/infrastructure/tui_metadata_runtime_injection_registry.py tests/unit/test_tui_metadata_compiler.py tests/unit/test_tui_workbench.py
git commit -m "refactor: separate tui capability access journeys"
```

## Task 2: Enforce screen authorization and bounded navigation errors

**Files:**

- Create: `apps/terminal/application/tui_errors.py`
- Modify: `apps/terminal/application/tui_workbench_catalog.py`
- Modify: `apps/terminal/application/tui_workbench.py`
- Modify: `apps/terminal/interface/api_views.py`
- Modify: `static/js/tui-workbench.js`
- Modify: `tests/unit/test_tui_workbench.py`

- [ ] **Step 1: Write failing service and API tests**

Cover:

- Unknown screen key raises a typed not-found error and the API returns HTTP 404.
- Published admin screen requested by a normal user raises a typed forbidden error and the API returns HTTP 403.
- Both API errors use the bounded payload:

```json
{
  "error_code": "tui_screen_not_found",
  "title": "页面不存在",
  "detail": "这个工作区没有发布，或已被移除。",
  "recovery_actions": [{"label": "返回首页", "screen_key": "home"}],
  "trace_id": "..."
}
```

- Valid screens include metadata `version` and `registry_key` in their contract.
- Browser source no longer retries an invalid manual navigation by loading the default screen.

- [ ] **Step 2: Run the focused tests and confirm RED**

```powershell
pytest tests/unit/test_tui_workbench.py -q -k "screen_not_found or screen_forbidden or bounded_error or registry_identity"
```

Expected: the current service silently substitutes `default_screen`, and the API has no typed mapping.

- [ ] **Step 3: Add application errors and audience checks**

Create framework-free exceptions carrying `screen_key` and stable `error_code`. Update catalog helpers so:

- unknown keys fail before module/action lookup;
- published screens are checked against `screen.audience` and `user.is_staff`/`user.is_superuser`;
- catalog filtering and direct screen authorization use the same helper;
- screen responses expose `registry_key` beside `version`.

- [ ] **Step 4: Map errors at the DRF boundary**

Catch only the new application errors in `TuiWorkbenchScreenView`. Build user-facing 404/403 payloads with a request trace ID and safe recovery action. Do not expose paths, methods, stack traces, database names, or internal exception text.

- [ ] **Step 5: Stop browser fallback for direct navigation**

Update `fetchJson`, `loadScreen`, and bootstrap behavior so manual navigation preserves and renders the structured error. A stale resume key may show one notification and intentionally return home, but an explicit current request must not silently become another screen.

- [ ] **Step 6: Run focused tests and confirm GREEN**

Run the Step 2 command again.

- [ ] **Step 7: Commit the navigation/error slice**

```powershell
git add apps/terminal/application/tui_errors.py apps/terminal/application/tui_workbench_catalog.py apps/terminal/application/tui_workbench.py apps/terminal/interface/api_views.py static/js/tui-workbench.js tests/unit/test_tui_workbench.py
git commit -m "fix: enforce tui screen access boundaries"
```

## Task 3: Produce one canonical self-service access package and verification action

**Files:**

- Modify: `tests/api/test_account_api_edges.py`
- Modify: `tests/unit/test_tui_workbench.py`
- Modify: `apps/account/application/interface_services.py`
- Modify: `apps/account/interface/serializers.py`
- Modify: `apps/account/interface/mcp_api_views.py`
- Modify: `apps/account/interface/api_urls.py`
- Modify: `apps/terminal/infrastructure/tui_metadata_runtime_injection_identity_access.py`
- Modify: `apps/terminal/application/tui_workbench_result_models_specialized.py`

- [ ] **Step 1: Write failing API and result-model tests**

Assert that the self-service payload contains:

- one canonical state: `disabled`, `no_token`, `ready`, or `unavailable`;
- one `access_package` containing token, route endpoint, capability catalog endpoint, minimal agent prompt, and environment statement;
- `same_machine_only=true` and an explicit localhost warning when the base URL is loopback;
- exactly one recommended active token;
- token history rows without plaintext or full display token;
- a read-only verification result covering token ownership/active state, routing readiness, and catalog readability;
- verification does not create/revoke/rotate a token or call an AI model.

Also assert the TUI result model exposes the access package as the dominant P0 model and never reintroduces a history token value.

- [ ] **Step 2: Run focused tests and confirm RED**

```powershell
pytest tests/api/test_account_api_edges.py tests/unit/test_tui_workbench.py -q -k "access_package or self_service_state or verify_mcp_access or token_history"
```

- [ ] **Step 3: Build the canonical application payload**

Refactor `build_self_mcp_api_payload()` around small typed helper functions that:

- select at most one recommended active token;
- derive the four-state machine from system setting, user setting, token availability, and routing/catalog readiness;
- build a minimal prompt without exposing irrelevant endpoint variants;
- label loopback URLs as same-machine-only without inventing a public URL;
- serialize history as ID, name, preview, access level, created/last-used timestamps only.

Keep repositories and ORM access behind existing Account application facades/providers.

- [ ] **Step 4: Add a read-only verification endpoint**

Add an authenticated GET endpoint and application service that checks the current user's effective token and the published routing/catalog configuration. Return bounded check rows and a summary state. The operation must have no writes and no downstream AI invocation.

- [ ] **Step 5: Publish the TUI action and result model**

Add a same-screen `capability-router.verify-my-mcp-access` action. Replace the three fragmented status/endpoints/prompt P0 concepts with one access-package P0 panel plus a P1 verification panel and collapsed P2 history panel. Preserve old action keys when needed for compatibility, but do not make them competing primary tasks.

- [ ] **Step 6: Run focused tests and confirm GREEN**

Run the Step 2 command again.

- [ ] **Step 7: Commit the self-service backend slice**

```powershell
git add apps/account/application/interface_services.py apps/account/interface/serializers.py apps/account/interface/mcp_api_views.py apps/account/interface/api_urls.py apps/terminal/infrastructure/tui_metadata_runtime_injection_identity_access.py apps/terminal/application/tui_workbench_result_models_specialized.py tests/api/test_account_api_edges.py tests/unit/test_tui_workbench.py
git commit -m "feat: add canonical mcp access package"
```

## Task 4: Render explicit field presentations and secret controls

**Files:**

- Modify: `config/tui/schema/tui_metadata.schema.v3.json`
- Modify: `apps/terminal/application/tui_metadata.py`
- Modify: `apps/terminal/application/tui_workbench_result_models.py`
- Modify: `apps/terminal/application/tui_workbench_result_models_specialized.py`
- Modify: `static/js/tui-workbench.js`
- Modify: `static/css/tui-workbench.css`
- Modify: `tests/unit/test_tui_metadata_compiler.py`
- Modify: `tests/unit/test_tui_workbench.py`

- [ ] **Step 1: Write failing presentation tests**

Require every result field to declare one of `secret`, `copyable`, `multiline`, or `metadata`. Assert:

- only `secret` and `copyable` render copy controls;
- token-level metadata never renders a copy button;
- a secret has show/hide and copy controls;
- one dominant “复制完整接入包” control exists;
- history is collapsed by default;
- the JavaScript no longer contains `fieldLooksLikeCopyable` or label regex inference.

- [ ] **Step 2: Run focused tests and confirm RED**

```powershell
pytest tests/unit/test_tui_metadata_compiler.py tests/unit/test_tui_workbench.py -q -k "field_presentation or copyable_secret or access_package_control"
```

- [ ] **Step 3: Extend result-field contracts**

Add explicit presentation validation to schema/compiler and emit it from generic and specialized result-model builders. Reject missing/unknown presentations for structured detail fields covered by the new contract.

- [ ] **Step 4: Replace heuristic rendering**

Delete label/field-name guessing. Render controls solely from `field.presentation`. Implement accessible show/hide/copy behavior for secrets, copy behavior for explicit copyables, multiline prompt formatting, and metadata-only display.

- [ ] **Step 5: Implement access-package composition in the browser**

Render the server-produced package in a stable order and copy it with one action. Refresh the package, verification, and history panels after token mutation. Keep destructive confirmation/reauth behavior intact.

- [ ] **Step 6: Run focused tests and confirm GREEN**

Run the Step 2 command again, then syntax-check JavaScript:

```powershell
node --check static/js/tui-workbench.js
```

- [ ] **Step 7: Commit the explicit-presentation slice**

```powershell
git add config/tui/schema/tui_metadata.schema.v3.json apps/terminal/application/tui_metadata.py apps/terminal/application/tui_workbench_result_models.py apps/terminal/application/tui_workbench_result_models_specialized.py static/js/tui-workbench.js static/css/tui-workbench.css tests/unit/test_tui_metadata_compiler.py tests/unit/test_tui_workbench.py
git commit -m "feat: render explicit tui copy presentations"
```

## Task 5: Add validated row actions for governance tables

**Files:**

- Modify: `config/tui/schema/tui_metadata.schema.v3.json`
- Modify: `apps/terminal/application/tui_metadata.py`
- Modify: `apps/terminal/infrastructure/tui_metadata_runtime_injection_capability_router.py`
- Modify: `apps/terminal/infrastructure/tui_metadata_runtime_injection_identity_access.py`
- Modify: `static/js/tui-workbench.js`
- Modify: `static/css/tui-workbench.css`
- Modify: `tests/unit/test_tui_metadata_compiler.py`
- Modify: `tests/unit/test_tui_workbench.py`

- [ ] **Step 1: Write failing row-action tests**

Cover valid descriptor shape and reject:

- unknown action keys;
- action keys from another screen;
- missing row-to-parameter mappings;
- mappings that reference absent row fields.

Assert visible native buttons exist for tool enable/disable and user detail/token/governance actions, with accessible row-specific labels.

- [ ] **Step 2: Run focused tests and confirm RED**

```powershell
pytest tests/unit/test_tui_metadata_compiler.py tests/unit/test_tui_workbench.py -q -k "row_action"
```

- [ ] **Step 3: Add schema/compiler validation**

Add `dashboardPanel.row_actions` descriptors containing action key, label template, and row field mappings. Validate action existence, same-screen ownership, required parameter coverage, and referenced columns.

- [ ] **Step 4: Publish governance row actions**

Attach descriptors to MCP tool rows and user rows. Keep risk confirmation and backend authorization unchanged.

- [ ] **Step 5: Render native row buttons**

Render `<button>` controls in a dedicated action column. Map row values into action parameters, provide visible keyboard focus, and refresh affected panels after success.

- [ ] **Step 6: Run focused tests and confirm GREEN**

Run the Step 2 command and `node --check static/js/tui-workbench.js`.

- [ ] **Step 7: Commit the row-action slice**

```powershell
git add config/tui/schema/tui_metadata.schema.v3.json apps/terminal/application/tui_metadata.py apps/terminal/infrastructure/tui_metadata_runtime_injection_capability_router.py apps/terminal/infrastructure/tui_metadata_runtime_injection_identity_access.py static/js/tui-workbench.js static/css/tui-workbench.css tests/unit/test_tui_metadata_compiler.py tests/unit/test_tui_workbench.py
git commit -m "feat: add tui governance row actions"
```

## Task 6: Complete layout, recovery, and accessibility behavior

**Files:**

- Modify: `static/js/tui-workbench.js`
- Modify: `static/css/tui-workbench.css`
- Modify: `apps/terminal/interface/api_views.py`
- Modify: `tests/unit/test_tui_workbench.py`

- [ ] **Step 1: Write failing browser-source contract tests**

Assert:

- self-service uses at most two columns at 1440px;
- P2 panels are collapsed initially;
- status uses text plus visual styling;
- panel errors render a concise message, trace ID when present, and retry/recovery buttons;
- raw HTTP/database/migration exception text is not directly inserted into ordinary-user UI;
- interactive panel elements are native buttons, not `section role=button`;
- all new controls have visible `:focus-visible` styles and minimum practical hit targets.

- [ ] **Step 2: Run focused tests and confirm RED**

```powershell
pytest tests/unit/test_tui_workbench.py -q -k "two_column or panel_recovery or accessible_controls or bounded_panel_error"
```

- [ ] **Step 3: Implement layout and accessible interaction**

Add screen/priority-aware grid classes, collapsed P2 details, readable typography, text status labels, native buttons, focus rings, and reduced nested scrolling. Do not claim full WCAG conformance.

- [ ] **Step 4: Implement contextual panel recovery**

Normalize 404/403/502/503/migration-mismatch responses into concise title/detail/recovery data. Panel failures keep successful sibling panels visible and offer retry; page failures show a bounded application error.

- [ ] **Step 5: Run focused tests and confirm GREEN**

Run Step 2 plus:

```powershell
node --check static/js/tui-workbench.js
```

- [ ] **Step 6: Commit the UX hardening slice**

```powershell
git add static/js/tui-workbench.js static/css/tui-workbench.css apps/terminal/interface/api_views.py tests/unit/test_tui_workbench.py
git commit -m "fix: harden tui recovery and accessibility"
```

## Task 7: Run regression, browser acceptance, and close the audit

**Files:**

- Modify: `docs/development/tui-user-facing-design-standard.md`
- Modify: `output/playwright/tui-capability-router-audit/audit-report.md`
- Add/update: `output/playwright/tui-capability-router-audit/` acceptance screenshots

- [ ] **Step 1: Update the user-facing standard**

Document explicit screen audiences, no direct-navigation fallback, explicit field presentations, canonical MCP access packages, row actions, and bounded error payloads. Keep the design document as rationale and the standard as the reusable rule set.

- [ ] **Step 2: Run focused and fixed regression packages**

```powershell
pytest tests/unit/test_tui_metadata_compiler.py -q
pytest tests/api/test_account_api_edges.py -q
pytest tests/unit/test_tui_workbench.py -q
pytest tests/unit/test_terminal_agent_service.py -q
pytest sdk/tests/test_sdk/test_client.py -q
pytest tests/unit/test_internal_ssl_redirect.py -q
node --check static/js/tui-workbench.js
python manage.py makemigrations --check --dry-run
python manage.py check
```

Record exact pass/fail counts. Diagnose any failure before changing implementation.

- [ ] **Step 3: Verify the real browser flow**

Start the current Django application on an unused local port with the current migrations applied to a disposable/local development database. With Playwright:

- sign in as the provided admin account without recording credentials in artifacts;
- verify admin navigation shows access, governance, and debug modules;
- capture the self-service screen at 1440px and confirm Token, route, catalog, prompt, environment warning, one bundle-copy action, verify action, and collapsed history;
- verify show/hide/copy controls and no copy button on token-level metadata;
- exercise a safe read-only verification action;
- verify visible governance row actions;
- verify an unknown screen produces 404 UI and does not become home;
- verify ordinary-user 403 behavior using a temporary test user or a request-level authenticated fixture;
- inspect browser console/network logs for unexpected errors.

Mask all secret values in screenshots and saved traces.

- [ ] **Step 4: Close the audit report**

For each original finding, add status, implementation evidence, automated-test evidence, and screenshot reference. Explicitly list any remaining risk rather than marking it fixed without evidence.

- [ ] **Step 5: Review the diff boundary**

```powershell
git status --short
git diff --check
git diff --stat HEAD~6..HEAD
```

Confirm unrelated `governance/governance_baseline.json` changes remain untouched and unstaged unless they were independently required and reviewed.

- [ ] **Step 6: Commit documentation and acceptance evidence**

```powershell
git add docs/development/tui-user-facing-design-standard.md output/playwright/tui-capability-router-audit/audit-report.md output/playwright/tui-capability-router-audit
git commit -m "docs: close tui capability access audit"
```

- [ ] **Step 7: Final verification-before-completion gate**

Re-run any test affected after the final documentation/evidence update, inspect `git status`, and report:

- completed items;
- incomplete items;
- tests run with exact results;
- unverified risks;
- commits created;
- browser evidence locations.

Do not mark the goal complete until all 12 acceptance criteria in the authoritative design have direct evidence.
