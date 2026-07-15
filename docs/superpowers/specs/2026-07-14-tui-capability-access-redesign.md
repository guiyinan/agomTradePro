# TUI Capability Access Redesign

> Approved design for turning the TUI capability-router area into distinct user, administrator, and developer journeys, with an actionable MCP access package and recoverable error states.

**Date:** 2026-07-14  
**Status:** Approved for implementation  
**Delivery branch:** `dev/feat-mcp-full-closure`

## 1. Goal

Repair every actionable finding in `output/playwright/tui-capability-router-audit/audit-report.md` so that an ordinary user can open one clearly named entry, obtain one recommended MCP token, copy one complete connection package, verify the connection, and manage their own token lifecycle without understanding routing internals. Administrators must have separate, explicit tool-governance and user-credential workflows. Developer routing diagnostics must not be part of the ordinary-user onboarding path.

The redesign preserves the existing TUI rendering system and existing screen keys. It changes module ownership, screen visibility, result semantics, error contracts, task affordances, and presentation. It does not replace the workbench or introduce a separate frontend framework.

## 2. Current Problems

The audited runtime and current code expose six connected defects:

1. The running preview can publish only `capability-router.gateway` while newer code contains four screens; requesting an unknown screen silently returns the default home screen.
2. Ordinary users encounter route debugging before the MCP access material they actually need.
3. Gateway, personal access, tool governance, and user governance use contradictory shared workflow progress values.
4. The self-service screen displays several token-like fields and token history at equal visual priority, so the user cannot identify the recommended credential.
5. Copyable fields are inferred from labels and keys, causing metadata such as token access level to be rendered as a secret.
6. Admin operations and errors are hidden behind generic task panels and raw HTTP-style messages, leaving no obvious recovery path.

## 3. Architecture and Module Boundaries

Existing screen keys remain stable:

- `capability-router.self-service`
- `capability-router.mcp-center`
- `capability-router.admin-access`
- `capability-router.gateway`

They move into three focused modules:

### 3.1 `mcp-access`

Label: `我的 MCP 接入`

Visible to every authenticated user. Its default and only primary screen is `capability-router.self-service`. It owns personal access status, recommended token selection, the complete access package, connection verification, token creation/rotation/revocation, and token history.

### 3.2 `mcp-governance`

Label: `MCP 管理`

Visible only to administrators. It contains `capability-router.mcp-center` and `capability-router.admin-access`. It owns MCP tool synchronization/routing governance and user credential governance.

### 3.3 `capability-router-debug`

Label: `能力路由调试`

Visible only to administrators. It contains `capability-router.gateway`. It validates route selection and catalog coverage but is not an onboarding step.

Screen visibility is explicit metadata, not an accidental consequence of whether at least one action is visible. The metadata schema accepts an `audience` value of `authenticated` or `admin`. The application catalog and screen APIs enforce that audience. Existing action-risk checks remain an independent second authorization layer.

The global TUI default screen remains the operator home. Within the related module area, ordinary users see `我的 MCP 接入` as the only capability-access entry. Administrators see all three modules.

## 4. Navigation and Screen Resolution

`TuiWorkbenchService.get_screen()` no longer substitutes the default screen for unknown keys.

- Unknown published screen: raise a screen-not-found application error and return HTTP 404.
- Published but audience-forbidden screen: raise a screen-forbidden application error and return HTTP 403.
- Visible screen: return its contract normally.

The frontend displays an explicit error state for direct navigation failures. A stale resume target may return the user to the home screen only after showing a one-time message naming the unavailable workspace. Manual location entry never silently falls back.

The workbench chrome exposes the metadata version and registry key in operator-facing language. Internal screen/action addresses remain available only in the location control and debug surfaces; ordinary help copy must not teach implementation keys.

Cross-role `step` and `total` workflow progress is removed from these four screens. Each screen publishes an independent journey name, primary task, primary outcome, and next-step hint. No ordinary-user journey points to an admin-only screen.

## 5. Personal MCP Access Screen

The screen uses a maximum two-column layout with one P0 recommended-access card and one P0 complete-package card. Supporting connection details are P1. Token history and advanced explanation are P2 and collapsed by default.

### 5.1 State model

The status action produces one of four explicit states:

- `disabled`: MCP access is not enabled; show the reason and administrator contact guidance.
- `no_token`: MCP is enabled but no usable token exists; make `创建只读令牌` the primary action.
- `ready`: one recommended usable token and a complete package are available.
- `unavailable`: tokens exist but plaintext cannot be recovered or the required endpoint configuration is invalid; explain the cause and offer rotation or configuration guidance.

Recommended-token selection remains server-side and deterministic. It prefers a usable plaintext-capable active token according to the existing account application service. The TUI displays only that single recommendation at P0.

### 5.2 Explicit field presentation

Result fields carry presentation metadata rather than relying on key/label regular expressions:

- `presentation: secret` for the token value;
- `presentation: copyable` for an endpoint;
- `presentation: multiline` for the complete access package or prompt;
- `presentation: metadata` for name, access level, environment, timestamps, and counts.

Only `secret`, `copyable`, and `multiline` fields receive copy controls. Token level, count, role, and plaintext-policy labels never become secret controls. Legacy result fields without presentation metadata continue to use safe non-secret rendering unless their panel already declares a specialized endpoint or prompt semantic.

### 5.3 Recommended token card

The ready state shows:

- token name;
- access level in text;
- complete token value;
- show/hide control;
- copy control;
- rotate control.

The token is visible when plaintext display is allowed, satisfying the P0 credential requirement. The user can hide it before sharing the screen. Token values are never written to logs, status messages, analytics, audit summaries, screenshots, or error details.

### 5.4 Complete access package

One server-produced `access_package` contains:

- the recommended token;
- Route Endpoint;
- Capability Catalog Endpoint;
- a minimal agent instruction;
- an environment statement explaining whether the address is local-machine, LAN, or public.

`复制完整接入包` is the dominant action. Individual token and endpoint copy actions remain secondary.

When the base host is loopback or `localhost`, the environment statement explicitly says that only a process on the same machine can use it. The system does not invent a public address. A configured external base URL, when available through the existing application configuration contract, is preferred.

### 5.5 Connection verification

The self-service module exposes a read-only verification action that checks:

1. the selected token can be resolved as active for the current user;
2. the routing entrypoint is configured and reachable through the application service;
3. the capability catalog can be read for the current identity.

It returns per-check status and a single overall outcome. It does not reveal the token, perform an AI request, or mutate user data.

### 5.6 Token history and lifecycle

History is collapsed by default and displays name, access level, created time, last-used time, and state. It does not display complete token values. Row actions are `轮换` and `撤销`; both use the existing confirmation, password reauthentication, and audit pipeline. Successful mutations refresh the recommended card, access package, and history.

## 6. Administrator MCP Management

### 6.1 Tool governance

The tool list prioritizes synchronization failures, routing-disabled tools, and high-risk tools. Each row provides visible controls for details, routing enable/disable, and terminal enable/disable. Mutation controls continue to require the metadata-defined confirmation policy and produce an audit outcome.

### 6.2 User and credential governance

The user list provides visible controls for details, MCP enable/disable, token creation, and token revocation. Selecting a user opens an in-screen action area populated from the selected row. The administrator does not need to discover the generic support-task list to act.

After an operation, the affected row refreshes and displays the new MCP state and active-token count. The result includes a human-readable confirmation and an audit reference, without returning secrets except during the one-time token-creation response.

### 6.3 Row-action metadata

Dashboard datagrid panels may publish bounded `row_actions`. Each descriptor references an action already attached to the same screen and maps declared action fields to row keys. The metadata schema and validator reject unknown actions, cross-screen actions, and missing row mappings. The frontend renders real buttons with accessible labels and uses the existing action form/confirmation pipeline.

## 7. Error and Recovery Contract

TUI API errors use a bounded structure:

```json
{
  "error_code": "screen_not_found",
  "title": "工作区未发布",
  "detail": "当前运行版本没有发布该工作区。",
  "recovery_actions": [
    {"label": "返回首页", "screen_key": "command-center.overview"}
  ],
  "trace_id": "..."
}
```

The ordinary-user copy never exposes stack traces, Python class names, database table names, raw paths, or API implementation details.

- 404: identify the unavailable workspace and offer a visible safe destination.
- 403: state that the current role lacks access and offer the personal-access module or home.
- 502/503: explain which business capability is unavailable, whether the rest of the screen remains usable, and offer retry/diagnostics/home actions.
- Database schema mismatch: application readiness converts known missing-column or unapplied-migration evidence into `运行版本与数据库结构不一致`; administrators get migration guidance, ordinary users get service-unavailable guidance.

Dashboard panels show one contextual error card per failed action with a retry button. The screen avoids three identical raw HTTP error messages when one shared dependency is unavailable.

## 8. Presentation and Accessibility

- Personal access uses at most two content columns at a 1440-pixel desktop viewport.
- Advanced explanation and token history are collapsed until requested.
- Body and table text meet the workbench's readable-size token; line height and hit targets increase without changing the terminal visual language.
- Status uses text plus color. Color is never the only carrier of meaning.
- Every row operation is a native button with an action-specific accessible label.
- `:focus-visible` is obvious on navigation, copy controls, disclosure controls, and row actions.
- Panel headings preserve semantic heading order.
- The page avoids nested independent scroll containers where the content can instead use the main workspace scroll.

This work improves the audited accessibility failures but does not claim full WCAG conformance.

## 9. Metadata and Documentation Synchronization

The change updates together:

- `config/tui/schema/tui_metadata.schema.v3.json`;
- `apps/terminal/application/tui_metadata.py`;
- runtime metadata injection modules and registry;
- compiler/validator behavior;
- TUI result-model contracts;
- workbench JavaScript and CSS;
- unit, API contract, and browser tests;
- `docs/development/tui-user-facing-design-standard.md`;
- `output/playwright/tui-capability-router-audit/audit-report.md` with final evidence.

No user-facing copy teaches `/api/`, `auto.api`, `param.api`, HTTP methods, path placeholders, or internal routing implementation keys.

## 10. Test Strategy

Every behavior change follows red-green-refactor.

### 10.1 Metadata and catalog

- schema accepts valid audience and row actions and rejects invalid values/references;
- ordinary-user catalog contains `mcp-access` and excludes governance/debug modules;
- administrator catalog contains all three modules;
- the four screens have independent user journeys and no contradictory shared progress;
- published-file, database-published, and runtime-injected metadata produce the same module/screen contract.

### 10.2 Screen and error APIs

- visible screen returns 200 with the requested key;
- unknown screen returns 404 structured error;
- forbidden screen returns 403 structured error;
- stale resume fallback is visible to the user and manual navigation never falls back;
- registry version and key appear in the chrome contract.

### 10.3 Self service

- disabled, no-token, ready, and unavailable states;
- exactly one recommended token at P0;
- explicit field presentation keeps token level non-secret;
- complete access package contains the selected token, route, catalog, prompt, and environment statement;
- localhost warning and configured external-address preference;
- connection verification success and partial failure;
- history omits complete token values;
- lifecycle operations refresh all dependent panels.

### 10.4 Administration and frontend

- row actions map selected rows to existing action fields;
- unknown/cross-screen row actions fail metadata validation;
- confirmation, reauthentication, audit, and post-mutation refresh remain enforced;
- structured panel errors render recovery actions;
- show/hide, copy, disclosure, retry, and row-action controls are keyboard reachable;
- JavaScript syntax and relevant static contract tests pass.

### 10.5 Required regression and browser evidence

Run:

- `pytest tests/unit/test_tui_workbench.py -q`
- `pytest tests/unit/test_terminal_agent_service.py -q`
- `pytest sdk/tests/test_sdk/test_client.py -q`
- `pytest tests/unit/test_internal_ssl_redirect.py -q`
- focused metadata compiler, architecture guard, migration, and JavaScript checks

Browser acceptance uses one ordinary user and one administrator. It proves the personal access journey, administrator tool/user actions, 404, 403, service failure, stale-version visibility, keyboard focus, and absence of raw tokens in screenshots/logs.

## 11. Acceptance Criteria

The redesign is complete only when all conditions below have direct evidence:

1. Ordinary users see `我的 MCP 接入` as the only capability-access module and can complete the journey without visiting routing diagnostics.
2. Administrators see separate `MCP 管理` and `能力路由调试` modules.
3. Unknown and forbidden screens return 404 and 403 respectively; no manual navigation silently returns home.
4. The self-service first screen presents exactly one recommended token or one clear create-token action.
5. A complete access package can be copied in one action and contains valid environment guidance.
6. Connection verification returns bounded per-check evidence without exposing the token.
7. Token history does not display complete token values, and lifecycle actions refresh the screen.
8. Tool and user lists expose visible, accessible row actions with confirmation and audit behavior preserved.
9. Business errors have recovery actions and do not lead with raw HTTP codes or stack/database details.
10. The self-service desktop layout uses at most two columns, avoids unnecessary nested scrolling, and has visible keyboard focus.
11. Schema, metadata, runtime injection, frontend, tests, documentation, and the audit report are synchronized.
12. All required regression commands pass, and browser evidence proves both primary user roles.

## 12. Non-Goals

- Replacing the global TUI home or the workbench framework.
- Renaming existing screen keys or breaking stored deep links.
- Inventing public addresses when the system is configured only for localhost.
- Returning token plaintext in logs, diagnostics, audit summaries, or screenshots.
- Adding new top-level MCP tools.
- Changing Docker or production deployment topology.
- Claiming full WCAG compliance.

