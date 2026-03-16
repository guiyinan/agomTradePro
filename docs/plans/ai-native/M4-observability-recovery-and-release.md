# Milestone M4: Observability, Recovery, And Release Readiness

> **Status**: COMPLETED (2026-03-16)
> **Tests**: 62 M4 tests + 193 full regression (all passing)

## Objective

Turn the L4 implementation into a releasable system with operator visibility, failure recovery, and staged validation.

This milestone is the release and hardening phase.

## In Scope

- task and proposal observability UI
- resume and handoff behavior
- regression suite completion
- UAT scripts
- staging rollout
- release checklist

## Out Of Scope

- L5 multi-agent router
- autonomous recurring task scheduler
- production auto-execution

## Deliverables

- task/proposal dashboard
- recovery flows
- full regression suite
- UAT scripts and evidence
- staging rollout guide
- release sign-off package

## Work Packages

## WP-M4-01 Operator Dashboard

Create a minimum operator view including:

- task list
- task detail
- timeline viewer
- proposal list
- proposal detail
- approval panel
- execution outcome panel
- guardrail viewer

Acceptance:

- operator can inspect any task end-to-end without database access

## WP-M4-02 Resume And Handoff

Implement:

- `POST /api/agent-runtime/tasks/{id}/resume/` full behavior
- `POST /api/agent-runtime/tasks/{id}/handoff/`

Handoff payload must include:

- current status
- completed steps
- pending steps
- latest context references
- open risks
- recommended next actor

Acceptance:

- failed task can be resumed from supported states
- task can be handed to human with complete artifact package

## WP-M4-03 Failure Classification And Recovery

Classify failures as:

- validation error
- dependency unavailable
- upstream data stale
- authorization blocked
- execution failure
- unknown system error

Each failure must return:

- `failure_type`
- `retryable`
- `recommended_action`
- `human_required`

Acceptance:

- all tested failures map to deterministic recovery output

## WP-M4-04 Regression Suite

Build milestone-complete regression suite:

- runtime unit tests
- API contract tests
- SDK contract tests
- MCP tool/resource/prompt tests
- RBAC tests
- audit trace tests
- E2E task workflows

Must run from CI with clear groups:

- `agent-runtime-unit`
- `agent-runtime-api`
- `agent-runtime-sdk`
- `agent-runtime-mcp`
- `agent-runtime-e2e`

Acceptance:

- CI groups are documented and reproducible

## WP-M4-05 UAT Pack

Prepare UAT scripts covering:

- research task lifecycle
- monitoring investigation flow
- proposal approval flow
- guarded execution flow
- failure recovery flow
- dashboard traceability flow

Deliverables:

- `docs/testing/ai-native-uat-script.md`
- sample input data
- expected outputs

Acceptance:

- UAT can be run by non-developer reviewer

## WP-M4-06 Staging Rollout

Prepare staging rollout plan:

- environment variables
- RBAC defaults
- feature flags
- migration procedure
- rollback steps
- smoke tests

Acceptance:

- staging deployment can be repeated from documented steps

## Test Plan

## UI And Operator Tests

- task detail page renders timeline
- proposal page shows approval status
- execution page shows guardrail and outcome

## Recovery Tests

- resume from failed task
- reject resume from terminal completed task
- handoff creates artifact and timeline event

## Regression Tests

- run all prior milestone suites
- verify no route drift
- verify MCP registration remains intact

## UAT Tests

- full operator walkthrough
- approval walkthrough
- blocked execution walkthrough
- degraded context walkthrough

## Performance Checks

- task detail query p95 under target
- context resource query p95 under target
- proposal precheck p95 under target

## Acceptance Criteria

M4 is accepted only if:

- operator dashboard exists and is usable
- resume and handoff work
- regression suite passes
- UAT passes on staging
- rollout and rollback docs are complete

## Release Gate

Before release sign-off:

- migrations tested on staging
- smoke tests passed
- audit traces verified
- feature flag defaults documented
- support owner identified

## Exit Artifacts

- dashboard screenshots or walkthrough evidence
- regression report
- UAT report
- staging rollout checklist
- release sign-off package
