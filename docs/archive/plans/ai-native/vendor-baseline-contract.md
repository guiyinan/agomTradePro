# AgomTradePro AI-Native Vendor Baseline Contract

> **Version**: 1.1
> **Status**: FROZEN
> **Last Updated**: 2026-03-16
> **Owner**: AgomTradePro Project Team

## 1. Purpose

This document is the single baseline reference for all implementation work on the AI-native L4 upgrade program.

All vendor teams and implementation agents must follow this contract exactly.

If there is a conflict between this document and any other reference, this document wins unless explicitly superseded by project owner approval.

---

## 2. Program Scope

### 2.1 Target Milestones

| Milestone | Name | Scope |
|-----------|------|-------|
| M0 | Baseline Freeze | Document freeze, no production code |
| M1 | Agent Runtime Foundation | Runtime data model, state machine, base APIs |
| M2 | Context and Task Tools | Context snapshots, facades, SDK and MCP task entrypoints |
| M3 | Proposal-Approval-Execution | Proposal lifecycle, approval gates, guarded execution |
| M4 | Observability, Recovery, Release | Dashboard, recovery, regression, staging release |

### 2.2 Target Capabilities

- Task lifecycle management (create, resume, cancel, handoff)
- Context aggregation for five task domains
- Proposal generation and approval workflow
- Guarded execution with policy checks
- Timeline and artifact tracking
- Audit trail for all mutations

### 2.3 Non-Goals

The vendor must NOT implement:

- Custom orchestration DSL
- Third-party workflow engine integration
- Autonomous production trading
- Uncontrolled multi-agent planner
- Model-driven direct writes to production actions
- Any feature outside the frozen backlog

---

## 3. Module Ownership

| Directory | Owner | Responsibility |
|-----------|-------|----------------|
| `apps/agent_runtime/` | Backend Team | Runtime entities, state machine, proposal lifecycle |
| `apps/regime/` | Existing | Regime data and logic (source of truth) |
| `apps/policy/` | Existing | Policy data and logic (source of truth) |
| `apps/signal/` | Existing | Signal data and logic (source of truth) |
| `apps/account/` | Existing | Portfolio data and logic (source of truth) |
| `sdk/agomtradepro/modules/agent_runtime.py` | SDK Team | Task/proposal SDK methods |
| `sdk/agomtradepro/modules/agent_context.py` | SDK Team | Context SDK methods |
| `sdk/agomtradepro_mcp/tools/agent_task_tools.py` | MCP Team | Task-oriented MCP tools |

### 3.1 Dependency Direction

```
MCP Tools → SDK → Backend API → Application Services → Domain Layer
```

The vendor must NOT:
- Call raw HTTP routes from MCP without going through SDK
- Bypass application services from views
- Put business logic in MCP tool files

---

## 4. Frozen Names

### 4.1 Entity Names (DO NOT CHANGE)

- `AgentTask`
- `AgentTaskStep`
- `AgentContextSnapshot`
- `AgentProposal`
- `AgentExecutionRecord`
- `AgentArtifact`
- `AgentTimelineEvent`
- `AgentHandoff`
- `AgentGuardrailDecision`

### 4.2 Task Domains (DO NOT CHANGE)

- `research`
- `monitoring`
- `decision`
- `execution`
- `ops`

### 4.3 Routes (DO NOT CHANGE)

All routes use canonical `/api/` prefix:

**Task Routes:**
- `/api/agent-runtime/tasks/`
- `/api/agent-runtime/tasks/{id}/`
- `/api/agent-runtime/tasks/{id}/timeline/`
- `/api/agent-runtime/tasks/{id}/artifacts/`
- `/api/agent-runtime/tasks/{id}/resume/`
- `/api/agent-runtime/tasks/{id}/cancel/`
- `/api/agent-runtime/tasks/{id}/handoff/`

**Proposal Routes:**
- `/api/agent-runtime/proposals/`
- `/api/agent-runtime/proposals/{id}/`
- `/api/agent-runtime/proposals/{id}/submit-approval/`
- `/api/agent-runtime/proposals/{id}/approve/`
- `/api/agent-runtime/proposals/{id}/reject/`
- `/api/agent-runtime/proposals/{id}/execute/`

**Context Routes:**
- `/api/agent-runtime/context/research/`
- `/api/agent-runtime/context/monitoring/`
- `/api/agent-runtime/context/decision/`
- `/api/agent-runtime/context/execution/`
- `/api/agent-runtime/context/ops/`

### 4.4 SDK Methods (DO NOT CHANGE)

**Task Methods:**
- `create_task(task_domain, task_type, input_payload)`
- `get_task(task_id)`
- `list_tasks(status, task_domain, limit)`
- `resume_task(task_id)`
- `cancel_task(task_id)`
- `handoff_task(task_id, payload)`
- `get_task_timeline(task_id)`
- `get_task_artifacts(task_id)`

**Context Methods:**
- `get_context_snapshot(domain)`

**Proposal Methods:**
- `create_proposal(task_id, proposal_type, risk_level, proposal_payload)`
- `get_proposal(proposal_id)`
- `submit_proposal_for_approval(proposal_id)`
- `approve_proposal(proposal_id, payload)`
- `reject_proposal(proposal_id, payload)`
- `execute_proposal(proposal_id)`

### 4.5 MCP Tools (DO NOT CHANGE)

**Task Start Tools:**
- `start_research_task(payload)`
- `start_monitoring_task(payload)`
- `start_decision_task(payload)`
- `start_execution_task(payload)`
- `start_ops_task(payload)`

**Task Control Tools:**
- `resume_agent_task(task_id)`
- `cancel_agent_task(task_id)`
- `handoff_agent_task(task_id, payload)`

**Proposal Tools:**
- `create_agent_proposal(payload)`
- `get_agent_proposal(proposal_id)`
- `approve_agent_proposal(proposal_id, payload)`
- `reject_agent_proposal(proposal_id, payload)`
- `execute_agent_proposal(proposal_id)`

### 4.6 MCP Resources (DO NOT CHANGE)

**Context Resources:**
- `agomtradepro://context/research/current`
- `agomtradepro://context/monitoring/current`
- `agomtradepro://context/decision/current`
- `agomtradepro://context/execution/current`
- `agomtradepro://context/ops/current`

**Task Resources:**
- `agomtradepro://task/{task_id}/timeline`

**Proposal Resources:**
- `agomtradepro://proposal/{proposal_id}/summary`

---

## 5. State Machine Definitions

### 5.1 AgentTask Status Transitions

**Status Values:**
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

**Allowed Transitions:**

| From Status | To Status | Trigger | Notes |
|-------------|-----------|---------|-------|
| `draft` | `context_ready` | Context aggregation complete | System transition |
| `draft` | `cancelled` | User cancellation | Terminal state |
| `context_ready` | `proposal_generated` | Proposal created | System transition |
| `context_ready` | `needs_human` | Context requires review | Human intervention needed |
| `context_ready` | `cancelled` | User cancellation | Terminal state |
| `proposal_generated` | `awaiting_approval` | Proposal submitted for approval | Pending approval |
| `proposal_generated` | `needs_human` | Proposal requires review | Human intervention needed |
| `proposal_generated` | `cancelled` | User cancellation | Terminal state |
| `awaiting_approval` | `approved` | Approval granted | Ready for execution |
| `awaiting_approval` | `rejected` | Approval denied | May retry or cancel |
| `awaiting_approval` | `needs_human` | Escalation required | Human intervention needed |
| `approved` | `executing` | Execution started | In progress |
| `approved` | `cancelled` | User cancellation | Terminal state |
| `rejected` | `proposal_generated` | Retry with new proposal | Loop back |
| `rejected` | `cancelled` | User cancellation | Terminal state |
| `executing` | `completed` | Execution successful | Terminal state |
| `executing` | `failed` | Execution failed | May retry |
| `executing` | `needs_human` | Execution blocked | Human intervention needed |
| `failed` | `draft` | **Human Retry** - Requires explicit human action; does NOT auto-transition |
| `failed` | `cancelled` | User cancellation | Terminal state |
| `needs_human` | `draft` | **Human Reset** - Requires explicit human action; does NOT auto-transition |
| `needs_human` | `context_ready` | **Human Continue** - Requires explicit human action; does NOT auto-transition |
| `needs_human` | `proposal_generated` | **Human Continue** - Requires explicit human action; does NOT auto-transition |
| `needs_human` | `cancelled` | User cancellation | Terminal state |

**Important**: These transitions (`failed → draft`, `needs_human → *`) require explicit human intervention through API/SDK calls. They are NOT automatic state changes. The application service must validate that the caller has appropriate permissions before allowing these transitions.

**Invalid Transitions (Explicitly Rejected):**
- Any transition to `draft` from terminal states (`completed`, `cancelled`)
- Any transition to `executing` without `approved` status
- Any transition to `completed` without `executing` status
- Direct jump from `draft` to `executing` (must go through proposal flow)

### 5.2 AgentProposal Status Transitions

**Status Values:**
- `draft`
- `generated`
- `submitted`
- `approved`
- `rejected`
- `executed`
- `execution_failed`
- `expired`

**Allowed Transitions:**

| From Status | To Status | Trigger | Notes |
|-------------|-----------|---------|-------|
| `draft` | `generated` | Proposal created | Initial creation |
| `draft` | `expired` | Timeout | Auto-expire |
| `generated` | `submitted` | Submitted for approval | Pending review |
| `generated` | `expired` | Timeout | Auto-expire |
| `submitted` | `approved` | Approval granted | Ready for execution |
| `submitted` | `rejected` | Approval denied | May retry |
| `submitted` | `expired` | Timeout | Auto-expire |
| `approved` | `executed` | Execution successful | Terminal state |
| `approved` | `execution_failed` | Execution failed | May retry |
| `approved` | `expired` | Timeout | Auto-expire |
| `rejected` | `draft` | **Retry with Modification** - Creates a NEW proposal draft derived from rejected proposal; the rejected proposal is NOT modified in-place. This is a CREATE operation, not an UPDATE. |
| `rejected` | `expired` | Timeout | Auto-expire |
| `execution_failed` | `approved` | **Retry Execution** - Returns to approved state for re-execution; does NOT automatically re-execute. Requires explicit trigger. |
| `execution_failed` | `expired` | Timeout | Auto-expire |

**Semantic Clarifications**:
- `rejected → draft`: This transition creates a **new** `AgentProposal` record in `draft` status, copying relevant context from the rejected proposal. The rejected proposal remains unchanged for audit trail. Implementation must use `create_proposal` with reference to thetask_id`, not an in-place update of the rejected proposal's status.
- `execution_failed → approved`: This transition allows re-execution after failure. The proposal returns to `approved` state but **Actual re-execution requires a separate `execute_proposal` call**. This is NOT automatic retry.

**Invalid Transitions (Explicitly Rejected):**
- Any transition from terminal states (`executed`, `expired`)
- Direct jump from `draft` to `approved` (must go through submission)
- Direct jump from `submitted` to `executed` (must go through approval)

### 5.3 Approval Status Values

For `AgentProposal.approval_status`:
- `not_required` - No approval needed (low risk)
- `pending` - Waiting for approval
- `approved` - Approval granted
- `rejected` - Approval denied

---

## 6. Coding and Review Rules

### 6.1 Mandatory Rules

1. **Follow four-layer architecture**: Domain → Application → Infrastructure → Interface
2. **State transitions in services only**: Never mutate state directly in views or MCP tools
3. **Every mutation must be auditable**: All state changes must emit timeline events
4. **Every response must include request_id**: For traceability
5. **Use timezone-aware datetime**: `datetime.now(timezone.utc)` or `timezone.now()`
6. **Tests are mandatory**: No implementation without tests

### 6.2 Forbidden Patterns

The vendor must NOT:

- Move workflow state logic into MCP tool files
- Bypass backend state machine checks
- Bypass backend guardrails with prompt instructions
- Let MCP directly call raw HTTP routes instead of SDK
- Add alternate route names for the same capability
- Mutate task or proposal state directly from views
- Make high-risk actions executable without proposal lifecycle
- Return unstructured exceptions to MCP clients
- Use prompt text as a security mechanism

### 6.3 PR Requirements

Every PR must include:

- Scope statement referencing specific backlog item(s)
- Test evidence (test file paths and pass results)
- No formatter rewrites outside touched files
- No scope expansion beyond assigned backlog

---

## 7. Escalation Rules

The vendor must stop and ask for approval if:

1. A needed field is missing from the contract
2. An existing business module cannot provide required source data
3. A proposed execution action would bypass approval
4. A route conflict exists with current canonical API
5. An existing SDK or MCP name appears incompatible with contract
6. Multiple implementation paths exist with different public behavior

When escalating, provide:

- Exact conflict description
- File(s) involved
- Blocked backlog item(s)
- Minimum decision needed
- Recommended option

---

## 8. M0 Acceptance Checklist

Before proceeding to M1, the following must be verified:

- [ ] `vendor-baseline-contract.md` exists and is internally approved
- [ ] State machine transitions are reviewed and confirmed by project owner
- [ ] All frozen names (entities, routes, SDK methods, MCP tools/resources) are confirmed
- [ ] `test-matrix.md` exists and coverage requirements are approved
- [ ] No conflicts exist between this document and `implementation-contract.md` or `schema-contract.md`
- [ ] Non-goals are explicitly documented
- [ ] Escalation rules are understood by vendor team

## 9. Milestone Acceptance Criteria

A milestone (M1-M4) is not complete unless:

- All frozen documents are committed
- All implementation code exists
- All automated tests exist and pass
- All public contract examples are updated
- No forbidden pattern was introduced
- Internal owner signs off

---

## 9. Document References

| Document | Purpose |
|----------|---------|
| `implementation-contract.md` | Hard constraints, frozen names, forbidden patterns |
| `schema-contract.md` | Model, API, SDK, MCP, error contracts |
| `execution-backlog.md` | Ordered backlog for implementation |
| `test-matrix.md` | Test requirements per milestone |
| `M0-baseline-freeze.md` | M0 milestone definition |
| `M1-agent-runtime-foundation.md` | M1 milestone definition |
| `M2-context-and-task-tools.md` | M2 milestone definition |
| `M3-proposal-approval-execution.md` | M3 milestone definition |
| `M4-observability-recovery-and-release.md` | M4 milestone definition |

---

## 10. Sign-Off

| Role | Name | Date | Status |
|------|------|------|--------|
| Project Owner | | | PENDING |
| Technical Lead | | | PENDING |
| Vendor Representative | | | PENDING |

---

*This document is FROZEN. Any changes require project owner approval.*
