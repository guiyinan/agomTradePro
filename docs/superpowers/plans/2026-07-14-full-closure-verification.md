# Full MCP Closure Verification Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Prove every design acceptance criterion, update authoritative governance/docs, and deliver one green pull request.

**Architecture:** Verification proceeds from focused tests to architecture/governance guards, complete Nightly-equivalent suites, browser journeys, and CI. Evidence is recorded against all thirteen acceptance criteria before the branch is declared complete.

**Tech Stack:** pytest, Django test runner, Channels communicator, Playwright/in-app browser, GitHub Actions, governance scripts, Git/GitHub CLI.

**Execution status (2026-07-14):** Tasks 1-5 are complete. The checklist below is retained as the original execution script; the criterion-by-criterion final record is `docs/development/mcp-full-closure-evidence-2026-07-14.md`.

## Global Constraints

- No required acceptance item may remain unverified.
- The machine baseline in governance/governance_baseline.json is authoritative.
- Default top-level MCP tool count stays seven.
- Python 3.11 and 3.13 selected regressions must pass.
- Complete unit, API/migration, integration, app-local, guardrail, architecture, and Playwright stages must pass.
- No Docker files are created or changed.

---

### Task 1: Focused high-risk regression

**Files:**
- Modify only files proven necessary by failing tests.

- [ ] **Step 1: Run exact historical failures**

Run the Backtest audit, paired production settings, and realtime route compatibility tests. Expected: all pass.

- [ ] **Step 2: Run fixed minimum package**

~~~powershell
python -m pytest tests/unit/test_tui_workbench.py tests/unit/test_terminal_agent_service.py sdk/tests/test_sdk/test_client.py tests/unit/test_internal_ssl_redirect.py -q
~~~

Expected: all pass.

- [ ] **Step 3: Run new subsystem suites**

Run all semantic governance, realtime/Channels, event replay, migration, SDK stream, and MCP replacement tests. Expected: all pass.

### Task 2: Governance and architecture evidence

**Files:**
- Modify: governance/governance_baseline.json
- Modify: docs/governance/SYSTEM_BASELINE.md only if its narrative index needs a new link.

- [ ] **Step 1: Discover authoritative scripts**

Use rg to identify the existing baseline generation and verification commands referenced by CI workflows; run those exact commands rather than hand-editing dynamic counts.

- [ ] **Step 2: Regenerate and verify**

Regenerate governance_baseline.json, run manifest/schema/tool-budget/read-write/confirmation/preview/audit/catalog-dedup/unsupported-contract guards, and assert top-level tool count equals seven and unsupported contract count equals zero.

- [ ] **Step 3: Run architecture audit**

Run the repository Architecture workflow command and direct scans for Domain external imports, Application ORM/infrastructure imports or .objects, Interface Infrastructure imports, and app dependency cycles. Expected: zero new violations.

### Task 3: Complete local Nightly equivalent

- [ ] **Step 1: Read current workflow commands**

Open .github/workflows/nightly.yml and related reusable workflows at current HEAD. Record each executable stage and environment requirement.

- [ ] **Step 2: Run every locally reproducible stage**

Run unit, API/migration, integration, app-local, guardrail, and Playwright suites with the same markers/options as CI. Run selected regression commands under both Python 3.11 and 3.13 environments when available.

- [ ] **Step 3: Run Redis smoke**

With a reachable local Redis, configure the production channel layer, connect an authenticated client, publish a polling snapshot, receive price.update and exactly one alert.triggered, and verify readiness fails when Redis becomes unavailable while the feature flag is enabled.

### Task 4: Browser acceptance

**Files:**
- Test: existing Playwright smoke location selected from repository conventions.

- [ ] **Step 1: Invoke browser skill**

Read browser:control-in-app-browser before browser actions. Start the local application with migrations applied and a staff plus ordinary test user.

- [ ] **Step 2: Verify semantic governance**

As staff, open Capability Gateway, preview/apply/remove a correction, verify sync survival and audit history. As ordinary user, verify controls and API are denied.

- [ ] **Step 3: Verify realtime primary task**

As a user, create an alert and subscription through the user-facing Realtime surface, connect the stream, trigger a polling update, and observe one price plus one alert notification without implementation-path leakage.

- [ ] **Step 4: Verify replay primary task**

As staff, preview a registered target, confirm commit, and inspect a completed or intentionally partial result. As ordinary user, verify denial.

- [ ] **Step 5: Save automated smoke coverage**

Encode the successful journeys in the repository Playwright suite and rerun it headlessly.

### Task 5: Documentation, commit, push, PR, and CI

**Files:**
- Modify: docs/INDEX.md
- Modify: docs/development/quick-reference.md
- Modify: relevant MCP/SDK/realtime/events operations documents discovered through docs/INDEX.md.
- Modify: docs/superpowers/specs/2026-07-14-mcp-full-closure-design.md status only after all local evidence passes.

- [ ] **Step 1: Document operations and rollback**

Record dependency installation, migrations, Redis channel-layer requirement, ASGI start command, feature flags, authenticated WebSocket smoke, replay enable order, rollback behavior, completed items, verified tests, and any non-required environment limitations.

- [ ] **Step 2: Audit acceptance criteria**

Create a 13-row evidence table matching design section 14. Each row links a test output, source artifact, browser evidence, or CI check; none may say pending or unverified.

- [ ] **Step 3: Run clean-tree verification**

Run git diff --check, formatting/lint/type commands scoped per repository CI, the full Nightly-equivalent suite, and git status. Commit governance/docs separately as docs: close MCP delivery evidence.

- [ ] **Step 4: Push and create one PR**

Push dev/feat-mcp-full-closure, create one ready-for-review PR to main with focused commit summary, migrations/rollback, tests, and risk notes.

- [ ] **Step 5: Wait for required checks**

Inspect every required check. Fix failures on the same branch, rerun local evidence, push, and wait again until Architecture, Fast Feedback, Consistency, Logic Guardrails, Security, and full Nightly are green.
