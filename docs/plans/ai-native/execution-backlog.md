# AgomSAAF AI-Native Execution Backlog

## Purpose

This file is the implementation backlog that can be assigned directly to an outsourcing team or execution agent.

Backlog rules:

- complete tasks strictly in order unless marked parallel-safe
- do not skip test tasks
- do not mark any development task complete without its matching verification task

## Legend

- `Seq`: sequence number
- `MS`: milestone
- `Track`: workstream
- `Type`: build, test, doc, review
- `Parallel`: yes/no

## Backlog

| Seq | MS | Track | Type | Parallel | Task |
|----|----|------|------|----------|------|
| 001 | M0 | PM | doc | no | Create `vendor-baseline-contract.md` with scope, ownership, non-goals, freeze rules. |
| 002 | M0 | Arch | doc | no | Create state machine transition table for `AgentTask` and `AgentProposal`. |
| 003 | M0 | Arch | doc | no | Create API/SDK/MCP naming freeze table. |
| 004 | M0 | QA | doc | yes | Create milestone test matrix covering unit/API/SDK/MCP/E2E. |
| 005 | M0 | PM | review | no | Run internal sign-off review and freeze M0 package. |
| 006 | M1 | Backend | build | no | Create `apps/agent_runtime/` Django app skeleton and register it. |
| 007 | M1 | Backend | build | no | Implement `AgentTaskModel` with required fields and indexes. |
| 008 | M1 | Backend | build | no | Implement `AgentTaskStepModel`. |
| 009 | M1 | Backend | build | no | Implement `AgentContextSnapshotModel`. |
| 010 | M1 | Backend | build | no | Implement `AgentProposalModel`. |
| 011 | M1 | Backend | build | no | Implement `AgentExecutionRecordModel`. |
| 012 | M1 | Backend | build | no | Implement `AgentArtifactModel`. |
| 013 | M1 | Backend | build | no | Implement `AgentTimelineEventModel`. |
| 014 | M1 | Backend | build | no | Implement `AgentHandoffModel`. |
| 015 | M1 | Backend | build | no | Implement `AgentGuardrailDecisionModel`. |
| 016 | M1 | Backend | build | no | Generate and verify initial migrations for `agent_runtime`. |
| 017 | M1 | Backend | build | no | Implement domain/application state machine service for task transitions. |
| 018 | M1 | Backend | build | no | Implement timeline event writer service. |
| 019 | M1 | Backend | build | no | Implement serializers/DTOs for task list/detail/timeline/artifacts. |
| 020 | M1 | Backend | build | no | Implement `CreateTaskUseCase`. |
| 021 | M1 | Backend | build | no | Implement `GetTaskUseCase`. |
| 022 | M1 | Backend | build | no | Implement `ListTasksUseCase`. |
| 023 | M1 | Backend | build | no | Implement `ResumeTaskUseCase`. |
| 024 | M1 | Backend | build | no | Implement `CancelTaskUseCase`. |
| 025 | M1 | Backend | build | no | Implement task API endpoints under `/api/agent-runtime/tasks/`. |
| 026 | M1 | Backend | build | no | Connect runtime task APIs to RBAC and audit hooks. |
| 027 | M1 | QA | test | no | Add unit tests for task state machine transitions. |
| 028 | M1 | QA | test | yes | Add model validation and index tests. |
| 029 | M1 | QA | test | yes | Add API contract tests for task create/get/list/resume/cancel. |
| 030 | M1 | QA | review | no | Produce M1 test report and sample payloads. |
| 031 | M2 | Backend | build | no | Implement context aggregation DTOs for five task domains. |
| 032 | M2 | Backend | build | no | Implement `ResearchTaskFacade`. |
| 033 | M2 | Backend | build | yes | Implement `MonitoringTaskFacade`. |
| 034 | M2 | Backend | build | yes | Implement `DecisionTaskFacade`. |
| 035 | M2 | Backend | build | yes | Implement `ExecutionTaskFacade`. |
| 036 | M2 | Backend | build | yes | Implement `OpsTaskFacade`. |
| 037 | M2 | Backend | build | no | Implement context APIs for `research/monitoring/decision/execution/ops`. |
| 038 | M2 | SDK | build | no | Add `sdk/agomsaaf/modules/agent_runtime.py`. |
| 039 | M2 | SDK | build | no | Add `sdk/agomsaaf/modules/agent_context.py`. |
| 040 | M2 | SDK | build | no | Register new SDK modules in `client.py`. |
| 041 | M2 | MCP | build | no | Add `sdk/agomsaaf_mcp/tools/agent_task_tools.py`. |
| 042 | M2 | MCP | build | no | Register task tools in MCP server. |
| 043 | M2 | MCP | build | no | Add context resources in MCP server for five domains. |
| 044 | M2 | MCP | build | yes | Add workflow-guide prompts for the five domains. |
| 045 | M2 | QA | test | no | Add facade unit tests with complete and partial upstream data. |
| 046 | M2 | QA | test | no | Add SDK contract tests for runtime/context modules. |
| 047 | M2 | QA | test | no | Add MCP registration tests for task tools/resources/prompts. |
| 048 | M2 | QA | test | no | Add integration tests for task start flow and context retrieval. |
| 049 | M2 | QA | review | no | Produce M2 contract alignment report for API/SDK/MCP. |
| 050 | M3 | Backend | build | no | Implement proposal lifecycle service and allowed transitions. |
| 051 | M3 | Backend | build | no | Implement proposal API endpoints. |
| 052 | M3 | Backend | build | no | Implement approval submit/approve/reject endpoints. |
| 053 | M3 | Backend | build | no | Implement guarded execution endpoint. |
| 054 | M3 | Backend | build | no | Implement guardrail engine with frozen decision output schema. |
| 055 | M3 | Backend | build | no | Persist guardrail decisions to runtime storage. |
| 056 | M3 | Backend | build | no | Implement execution record creation and linking to proposal/task. |
| 057 | M3 | Backend | build | no | Enrich audit payloads with task/proposal/guardrail linkage. |
| 058 | M3 | Backend | build | no | Migrate `signal` write path to proposal-backed execution flow. |
| 059 | M3 | Backend | build | no | Migrate `strategy bind/unbind` to proposal-backed execution flow. |
| 060 | M3 | Backend | build | no | Migrate selected `simulated_trading` write path to proposal-backed execution flow. |
| 061 | M3 | Backend | build | no | Migrate `policy event create` to proposal-backed execution flow. |
| 062 | M3 | Backend | build | no | Migrate selected config write path to proposal-backed execution flow. |
| 063 | M3 | SDK | build | no | Add proposal methods to runtime SDK module. |
| 064 | M3 | MCP | build | no | Add MCP proposal tools and register them. |
| 065 | M3 | QA | test | no | Add unit tests for proposal transitions and guardrail decisions. |
| 066 | M3 | QA | test | no | Add SDK contract tests for proposal methods. |
| 067 | M3 | QA | test | no | Add MCP proposal tool tests. |
| 068 | M3 | QA | test | no | Add E2E flow: research -> proposal -> approval. |
| 069 | M3 | QA | test | no | Add E2E flow: monitoring -> proposal -> guardrail reject/escalate. |
| 070 | M3 | QA | test | no | Add E2E flow: approved proposal -> execute -> execution record. |
| 071 | M3 | QA | review | no | Produce migrated action matrix and E2E evidence. |
| 072 | M4 | Backend | build | no | Implement task handoff endpoint and payload packaging. |
| 073 | M4 | Backend | build | no | Finalize resume behavior for supported failed states. |
| 074 | M4 | Backend | build | no | Implement deterministic failure classification and recovery output. |
| 075 | M4 | Frontend | build | no | Build task list and task detail operator screens. |
| 076 | M4 | Frontend | build | yes | Build proposal list/detail/approval screens. |
| 077 | M4 | Frontend | build | yes | Build timeline and guardrail viewer components. |
| 078 | M4 | QA | test | no | Add resume and handoff integration tests. |
| 079 | M4 | QA | test | no | Add UI smoke tests for task/proposal pages. |
| 080 | M4 | QA | test | no | Build full regression suite groups for runtime/API/SDK/MCP/E2E. |
| 081 | M4 | QA | test | no | Prepare UAT scripts and expected outputs. |
| 082 | M4 | DevOps | doc | no | Produce staging rollout, migration, smoke, and rollback guide. |
| 083 | M4 | PM | review | no | Run staging UAT and collect sign-off evidence. |
| 084 | M4 | PM | review | no | Produce final release gate package. |

## Completion Rules

For every backlog item:

- implementation task must link to changed files
- test task must identify exact test file(s)
- review task must attach evidence artifact

## Required Verification Mapping

- Tasks `006-026` must be paired with tests `027-030`
- Tasks `031-044` must be paired with tests `045-049`
- Tasks `050-064` must be paired with tests `065-071`
- Tasks `072-077` must be paired with tests `078-084`

## What The Vendor Must Not Do

- do not reorder milestones
- do not rename frozen APIs
- do not skip test tasks
- do not collapse proposal flow into direct execution
- do not push workflow logic into MCP-only code
