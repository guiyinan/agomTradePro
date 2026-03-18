# Milestone M3: Proposal, Approval, And Guarded Execution

> **Status**: COMPLETED (2026-03-16)
> **Tests**: 61 unit tests (41 guardrails + 12 SDK + 8 MCP), all passing

## Objective

Introduce the controlled execution model so that high-risk actions no longer execute directly from low-level tools.

This milestone establishes the core L4 safety and workflow boundary.

## In Scope

- proposal lifecycle
- approval APIs
- execute APIs
- guardrail checks
- execution record generation
- migration of selected high-risk actions to proposal mode
- audit enrichment

## Out Of Scope

- agent dashboard UI
- advanced auto-routing
- multi-agent coordination
- autonomous production execution

## Deliverables

- proposal APIs
- approval APIs
- guarded execute APIs
- proposal SDK methods
- proposal MCP tools
- guardrail decision records
- E2E workflow tests

## Work Packages

## WP-M3-01 Proposal Lifecycle

Implement proposal APIs:

- `POST /api/agent-runtime/proposals/`
- `GET /api/agent-runtime/proposals/{id}/`
- `POST /api/agent-runtime/proposals/{id}/submit-approval/`
- `POST /api/agent-runtime/proposals/{id}/approve/`
- `POST /api/agent-runtime/proposals/{id}/reject/`
- `POST /api/agent-runtime/proposals/{id}/execute/`

Proposal states:

- `draft`
- `generated`
- `submitted`
- `approved`
- `rejected`
- `executed`
- `execution_failed`
- `expired`

Acceptance:

- transitions enforced server-side
- invalid transitions return structured errors

## WP-M3-02 Guardrail Engine

Implement guardrail checks before approval and before execution:

- role gate
- risk level gate
- approval required gate
- market readiness gate
- data freshness gate
- dependency health gate

Guardrail output must include:

- `decision`
- `reason_code`
- `message`
- `evidence`
- `requires_human`

Acceptance:

- guardrail decisions persist to `AgentGuardrailDecisionModel`
- every proposal execute call stores precheck result

## WP-M3-03 Execution Record

On successful or failed execution, create:

- execution record
- timeline events
- linked artifacts
- audit entry

Execution outcomes must distinguish:

- success
- blocked
- validation_failed
- dependency_failed
- execution_failed
- partial_failure

Acceptance:

- execution history can be queried from proposal and task

## WP-M3-04 SDK Proposal Methods

Add SDK support:

- `create_proposal`
- `get_proposal`
- `submit_proposal_for_approval`
- `approve_proposal`
- `reject_proposal`
- `execute_proposal`

Acceptance:

- endpoint contract tests pass
- SDK normalizes structured failure payloads

## WP-M3-05 MCP Proposal Tools

Add MCP tools:

- `create_agent_proposal`
- `approve_agent_proposal`
- `reject_agent_proposal`
- `execute_agent_proposal`
- `get_agent_proposal`

Rules:

- tools must return proposal IDs and statuses
- execute tool must never bypass backend guardrails

Acceptance:

- MCP execution tests cover approve and reject paths

## WP-M3-06 High-Risk Action Migration

Migrate these actions to proposal-first flow:

- signal create/update/invalidate
- strategy bind/unbind to portfolio
- simulated-trading execute-like actions with persistent effects
- policy event create
- config writes

Migration rule:

- existing low-level entrypoints may remain for compatibility
- but production-capable path must require proposal lifecycle

Acceptance:

- at least five high-risk actions have proposal-backed execution path

## WP-M3-07 Audit Enrichment

Enhance audit logs with:

- `task_id`
- `proposal_id`
- `request_id`
- `guardrail_decision`
- `approval_actor`
- `execution_result`

Acceptance:

- audit query can trace task -> proposal -> action

## Test Plan

## Unit Tests

- proposal transition rules
- guardrail allow/block paths
- execution result classification
- audit payload builder

## SDK Tests

- proposal CRUD contract
- structured failure handling
- execute after approval
- reject execute before approval

## MCP Tests

- proposal tool registration
- create/approve/reject/execute tool execution
- permission-denied cases

## End-To-End Tests

### E2E-01 Research To Approved Proposal

Steps:

- start research task
- generate proposal from task output
- submit for approval
- approve proposal
- verify timeline and audit

### E2E-02 Monitoring To Risk Proposal

Steps:

- start monitoring task
- detect anomaly
- create proposal
- reject or escalate based on guardrail

### E2E-03 Execution With Guardrail

Steps:

- create proposal requiring approval
- approve proposal
- trigger execute
- verify execution record and audit linkage

## Acceptance Criteria

M3 is accepted only if:

- proposal APIs are complete
- guardrails run before execution
- execute cannot bypass approval for high-risk actions
- at least three E2E flows pass
- audit chain is complete for proposal flows

## Exit Artifacts

- proposal lifecycle examples
- guardrail matrix
- migrated action list
- E2E test report
- sample audit traces
