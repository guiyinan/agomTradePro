# Milestone M0: Baseline Freeze And Delivery Setup

## Objective

Freeze the implementation baseline before coding begins so the outsourcing team works against a stable contract.

This milestone exists to prevent:

- state machine drift
- API naming drift
- MCP/SDK/backend contract mismatch
- uncontrolled scope expansion
- ambiguous acceptance criteria

## In Scope

- freeze architecture boundaries
- freeze milestone scope
- freeze entity names and lifecycle states
- freeze API route naming
- freeze SDK and MCP naming conventions
- freeze acceptance test matrix
- freeze delivery workflow and review rules

## Out Of Scope

- writing production code
- database migrations
- SDK implementation
- MCP implementation
- UI implementation

## Required Inputs

- [AI-native blueprint](/abs/path/D:/githv/agomSAAF/docs/plans/AI-native-blueprint-260315.md)
- [AI-native implementation plan](/abs/path/D:/githv/agomSAAF/docs/plans/AI-Native-upgrade-implement-plan-260315.md)
- [API/MCP/SDK alignment](/abs/path/D:/githv/agomSAAF/docs/development/api-mcp-sdk-alignment-2026-03-14.md)

## Work Packages

## WP-M0-01 Project Baseline Document

Create a single baseline document for the vendor team that includes:

- target scope for M1 to M4
- frozen module ownership
- frozen naming conventions
- non-goals
- mandatory coding and review rules

Deliverable:

- `docs/plans/ai-native/vendor-baseline-contract.md`

Acceptance:

- reviewed by internal owner
- accepted as the only baseline reference for vendor questions

## WP-M0-02 Domain And Ownership Freeze

Freeze the implementation ownership map:

- `apps/agent_runtime/` for runtime entities, state machine, proposal lifecycle
- existing domain apps remain source of business truth
- `sdk/agomsaaf/modules/agent_runtime.py` for task/proposal SDK
- `sdk/agomsaaf/modules/agent_context.py` for context SDK
- `sdk/agomsaaf_mcp/tools/agent_task_tools.py` for task-oriented tools

Deliverable:

- ownership table in baseline document

Acceptance:

- each directory has one owning workstream
- no overlapping ownership remains unresolved

## WP-M0-03 State Machine Freeze

Freeze `AgentTask.status` values:

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

Freeze `AgentProposal.status` values:

- `draft`
- `generated`
- `submitted`
- `approved`
- `rejected`
- `executed`
- `execution_failed`
- `expired`

Deliverable:

- state machine section with allowed transitions

Acceptance:

- every transition has a clear allowed-from list
- every invalid transition is explicitly rejected

## WP-M0-04 API Contract Freeze

Freeze canonical API roots:

- `/api/agent-runtime/tasks/`
- `/api/agent-runtime/proposals/`
- `/api/agent-runtime/context/{domain}/`

Freeze first public SDK methods:

- `create_task`
- `get_task`
- `list_tasks`
- `resume_task`
- `cancel_task`
- `get_task_timeline`
- `get_context_snapshot`
- `create_proposal`
- `approve_proposal`
- `reject_proposal`
- `execute_proposal`

Freeze first MCP task tools:

- `start_research_task`
- `start_monitoring_task`
- `start_decision_task`
- `start_execution_task`
- `start_ops_task`
- `resume_agent_task`
- `cancel_agent_task`
- `approve_agent_proposal`
- `reject_agent_proposal`
- `execute_agent_proposal`

Deliverable:

- `api-contract-freeze.md`

Acceptance:

- internal owner signs off all names
- no later milestone may rename these without change approval

## WP-M0-05 Test Matrix Freeze

Create a test matrix covering:

- unit tests
- API contract tests
- SDK contract tests
- MCP registration and execution tests
- integration tests
- E2E/UAT tests

Deliverable:

- `docs/plans/ai-native/test-matrix.md`

Acceptance:

- each milestone has explicit pass criteria
- each deliverable maps to at least one test class

## WP-M0-06 Delivery And Review Workflow

Freeze execution rules for vendor team:

- one milestone branch or PR batch at a time
- no formatter rewrites outside touched files
- every PR must include test evidence
- every PR must include scope statement
- every blocked question must reference exact frozen doc section

Deliverable:

- `vendor-delivery-rules.md`

Acceptance:

- PM and internal reviewer agree on review workflow

## Implementation Checklist

- create baseline contract document
- create state transition table
- create API/SDK/MCP contract table
- create test matrix
- create vendor review rules
- publish milestone acceptance template

## Test And Validation

M0 is document-only, but must still be validated through review.

Validation checklist:

- baseline package exists
- all milestone names and dates are filled
- all APIs are named
- all task domains are named
- all status fields are named
- all non-goals are explicit

## Acceptance Gate

M0 passes only when:

- all freeze documents are committed
- all unresolved naming questions are closed
- internal owner signs off
- vendor acknowledges frozen scope in writing

## Risks

- vendor starts coding before freeze complete
- key lifecycle names change after M1 starts
- test scope is not frozen and drifts later

Mitigation:

- do not approve any implementation PR before M0 sign-off

## Outputs Required For Next Milestone

- baseline contract
- API freeze
- state machine freeze
- test matrix
- delivery rules
