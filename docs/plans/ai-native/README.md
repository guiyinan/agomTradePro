# AgomTradePro AI-Native Milestone Delivery Pack

## Purpose

This folder contains the execution-ready milestone plans for the AI-native L4 upgrade program.

These files are intended for:

- outsourcing delivery teams
- internal reviewers
- QA and UAT owners
- project managers tracking milestone acceptance

## Milestones

- [M0-baseline-freeze.md](../../archive/plans/ai-native/M0-baseline-freeze.md) - project kickoff, scope freeze, interface freeze
- [M1-agent-runtime-foundation.md](../../archive/plans/ai-native/M1-agent-runtime-foundation.md) - runtime data model, state machine, base APIs
- [M2-context-and-task-tools.md](../../archive/plans/ai-native/M2-context-and-task-tools.md) - context snapshots, facades, SDK and MCP task entrypoints
- [M3-proposal-approval-execution.md](../../archive/plans/ai-native/M3-proposal-approval-execution.md) - proposal lifecycle, approval gates, guarded execution
- [M4-observability-recovery-and-release.md](../../archive/plans/ai-native/M4-observability-recovery-and-release.md) - dashboard, recovery, regression, staging release

## Execution Pack

- [implementation-contract.md](../../archive/plans/ai-native/implementation-contract.md) - hard constraints, frozen names, forbidden implementation patterns
- [schema-contract.md](../../archive/plans/ai-native/schema-contract.md) - model, API, SDK, MCP, and error contracts
- [execution-backlog.md](./execution-backlog.md) - execution-order backlog for vendor teams or coding agents
- [glm-execution-prompt-template.md](../../archive/plans/ai-native/glm-execution-prompt-template.md) - ready-to-send implementation prompt for GLM or similar coding agents
- [vendor-baseline-contract.md](../../archive/plans/ai-native/vendor-baseline-contract.md) - vendor baseline, scope, ownership, state machine, freeze rules
- [test-matrix.md](../../archive/plans/ai-native/test-matrix.md) - test requirements per milestone

## P1 Release Gate (2026-08-14)

The local machine gate is frozen in [`config/ai_native/ai_native_release_gate.v1.json`](../../../config/ai_native/ai_native_release_gate.v1.json) and evaluated by [`scripts/check_ai_native_release_gate.py`](../../../scripts/check_ai_native_release_gate.py). It checks that the current API, SDK, MCP, TUI provenance, migration, and verification assets are present and marker-aligned.

The gate deliberately remains `DENY` until a real staging evidence package and independent owner/reviewer sign-off are supplied for the same candidate commit. A local fake, fixture, or passing unit test cannot satisfy those two external gates. This is a machine-guard closure, not a P1 release approval.

## How To Use This Pack

1. Complete milestones strictly in order.
2. Do not change milestone scope without written approval from the project owner.
3. Treat each milestone file as the authoritative implementation and acceptance contract.
4. Do not merge the next milestone until the current milestone has passed its acceptance gate.

## Delivery Rules

- All new APIs must use canonical `/api/...` routes.
- All high-risk write actions must be guarded by backend policy, not prompt text.
- All MCP additions must remain aligned with SDK and backend APIs.
- All milestone deliverables must include automated tests.
- All test failures must be triaged before milestone sign-off.

## Required Cross-Milestone Standards

- Every API response must include or trace to a `request_id`.
- Every task/proposal/action must be auditable.
- Every state change must be recorded in a timeline/event log.
- Every milestone must produce both implementation artifacts and verification artifacts.

## File Naming Convention

- `M0-...` through `M4-...` are implementation contracts.
- Additional supporting docs may be added later, but these files are the milestone baseline.
