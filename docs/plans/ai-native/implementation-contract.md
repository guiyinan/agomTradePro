# AgomSAAF AI-Native Implementation Contract

## Purpose

This document is the execution control contract for external vendors or implementation agents.

It exists to remove design ambiguity during execution.

If a requirement is defined here, the implementer must follow it exactly.

## Contract Priority

Priority order for this program:

1. This implementation contract
2. Milestone files under `docs/plans/ai-native/`
3. Canonical API alignment document
4. Existing codebase patterns

If there is a conflict, this document wins unless explicitly superseded by project owner approval.

## Non-Negotiable Rules

The implementer must not make independent design decisions in the following areas.

### Names That Must Not Change

- `AgentTask`
- `AgentTaskStep`
- `AgentContextSnapshot`
- `AgentProposal`
- `AgentExecutionRecord`
- `AgentArtifact`
- `AgentTimelineEvent`
- `AgentHandoff`
- `AgentGuardrailDecision`

- task domains:
  - `research`
  - `monitoring`
  - `decision`
  - `execution`
  - `ops`

- task statuses:
  - `draft`
  - `context_ready`
  - `proposal_generated`
  - `awaiting_approval`
  - `approved`
  - `rejected`
  - `executing`
  - `completed`
  - `failed`
  - `needs_human`
  - `cancelled`

- proposal statuses:
  - `draft`
  - `generated`
  - `submitted`
  - `approved`
  - `rejected`
  - `executed`
  - `execution_failed`
  - `expired`

### Routes That Must Not Change

- `/api/agent-runtime/tasks/`
- `/api/agent-runtime/tasks/{id}/`
- `/api/agent-runtime/tasks/{id}/timeline/`
- `/api/agent-runtime/tasks/{id}/artifacts/`
- `/api/agent-runtime/tasks/{id}/resume/`
- `/api/agent-runtime/tasks/{id}/cancel/`
- `/api/agent-runtime/tasks/{id}/handoff/`
- `/api/agent-runtime/proposals/`
- `/api/agent-runtime/proposals/{id}/`
- `/api/agent-runtime/proposals/{id}/submit-approval/`
- `/api/agent-runtime/proposals/{id}/approve/`
- `/api/agent-runtime/proposals/{id}/reject/`
- `/api/agent-runtime/proposals/{id}/execute/`
- `/api/agent-runtime/context/research/`
- `/api/agent-runtime/context/monitoring/`
- `/api/agent-runtime/context/decision/`
- `/api/agent-runtime/context/execution/`
- `/api/agent-runtime/context/ops/`

### SDK Public Methods That Must Not Change

- `create_task`
- `get_task`
- `list_tasks`
- `resume_task`
- `cancel_task`
- `handoff_task`
- `get_task_timeline`
- `get_task_artifacts`
- `get_context_snapshot`
- `create_proposal`
- `get_proposal`
- `submit_proposal_for_approval`
- `approve_proposal`
- `reject_proposal`
- `execute_proposal`

### MCP Tools That Must Not Change

- `start_research_task`
- `start_monitoring_task`
- `start_decision_task`
- `start_execution_task`
- `start_ops_task`
- `resume_agent_task`
- `cancel_agent_task`
- `handoff_agent_task`
- `create_agent_proposal`
- `get_agent_proposal`
- `approve_agent_proposal`
- `reject_agent_proposal`
- `execute_agent_proposal`

### MCP Resources That Must Not Change

- `agomsaaf://context/research/current`
- `agomsaaf://context/monitoring/current`
- `agomsaaf://context/decision/current`
- `agomsaaf://context/execution/current`
- `agomsaaf://context/ops/current`
- `agomsaaf://task/{task_id}/timeline`
- `agomsaaf://proposal/{proposal_id}/summary`

## Forbidden Implementation Patterns

The implementer must not:

- move workflow state logic into MCP tool files
- bypass backend state machine checks
- bypass backend guardrails with prompt instructions
- let MCP directly call raw HTTP routes instead of going through SDK without owner approval
- add alternate route names for the same capability
- mutate task or proposal state directly from views
- make high-risk actions executable without proposal lifecycle
- return unstructured exceptions to MCP clients
- use prompt text as a security mechanism

## Required Structural Rules

### Backend Rules

- lifecycle transitions must be implemented in application/domain services
- every state transition must emit a timeline event
- every mutating call must be auditable
- every response must include or map to `request_id`

### SDK Rules

- SDK is the canonical Python entrypoint
- SDK must normalize structured errors
- SDK method names must remain stable once introduced

### MCP Rules

- MCP must be task-oriented for new capabilities
- MCP tools must return structured JSON
- MCP resources must be read-only
- MCP prompts are workflow guides only

## Required Questions Escalation

The implementer must stop and ask for approval if any of these happen:

- a needed field is missing from the contract
- an existing business module cannot provide required source data
- a proposed execution action would bypass approval
- a route conflict exists with current canonical API
- an existing SDK or MCP name appears incompatible with contract

## Completion Definition

A task is not complete unless all are true:

- implementation code exists
- automated tests exist
- milestone acceptance criteria are satisfied
- public contract examples are updated
- no forbidden pattern was introduced

## Scope Exclusions

The implementer must not add:

- custom orchestration DSL
- third-party workflow engine
- autonomous production trading
- uncontrolled multi-agent planner
- model-driven direct writes to production actions

## Delivery Quality Bar

All code submitted under this contract must be:

- deterministic
- test-covered
- auditable
- contract-aligned
- rollback-friendly
