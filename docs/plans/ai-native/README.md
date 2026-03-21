# AgomTradePro AI-Native Milestone Delivery Pack

## Purpose

This folder contains the execution-ready milestone plans for the AI-native L4 upgrade program.

These files are intended for:

- outsourcing delivery teams
- internal reviewers
- QA and UAT owners
- project managers tracking milestone acceptance

## Milestones

- [M0-baseline-freeze.md](./M0-baseline-freeze.md) - project kickoff, scope freeze, interface freeze
- [M1-agent-runtime-foundation.md](./M1-agent-runtime-foundation.md) - runtime data model, state machine, base APIs
- [M2-context-and-task-tools.md](./M2-context-and-task-tools.md) - context snapshots, facades, SDK and MCP task entrypoints
- [M3-proposal-approval-execution.md](./M3-proposal-approval-execution.md) - proposal lifecycle, approval gates, guarded execution
- [M4-observability-recovery-and-release.md](./M4-observability-recovery-and-release.md) - dashboard, recovery, regression, staging release

## Execution Pack

- [implementation-contract.md](./implementation-contract.md) - hard constraints, frozen names, forbidden implementation patterns
- [schema-contract.md](./schema-contract.md) - model, API, SDK, MCP, and error contracts
- [execution-backlog.md](./execution-backlog.md) - execution-order backlog for vendor teams or coding agents
- [glm-execution-prompt-template.md](./glm-execution-prompt-template.md) - ready-to-send implementation prompt for GLM or similar coding agents
- [vendor-baseline-contract.md](./vendor-baseline-contract.md) - vendor baseline, scope, ownership, state machine, freeze rules
- [test-matrix.md](./test-matrix.md) - test requirements per milestone

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
