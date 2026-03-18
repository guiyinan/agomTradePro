# Milestone M1: Agent Runtime Foundation

## Objective

Build the backend runtime foundation that all later SDK, MCP, and workflow features depend on.

This milestone must establish:

- persistent task models
- persistent proposal-adjacent entities
- task state machine services
- timeline logging
- base runtime APIs

## In Scope

- `apps/agent_runtime/` app creation
- models
- migrations
- repositories or ORM access layer
- serializers
- DTOs
- state machine service
- task CRUD and control APIs
- unit and API tests

## Out Of Scope

- context snapshot generation
- MCP task tools
- SDK task modules
- approval execution flow
- dashboard UI

## Architecture Decisions

- all task state changes go through application service
- no direct model `.save()` from views for lifecycle transitions
- every state change must create a timeline event
- request-level audit linkage is required

## Deliverables

- `apps/agent_runtime/` codebase
- initial migrations
- task APIs
- serializer and DTO layer
- runtime unit tests
- runtime API tests

## Work Packages

## WP-M1-01 App Skeleton

Create:

- `apps/agent_runtime/apps.py`
- `apps/agent_runtime/domain/`
- `apps/agent_runtime/application/`
- `apps/agent_runtime/infrastructure/`
- `apps/agent_runtime/interface/`

Acceptance:

- app loads in Django
- routes mount without conflicts

## WP-M1-02 Persistent Models

Implement models:

- `AgentTaskModel`
- `AgentTaskStepModel`
- `AgentContextSnapshotModel`
- `AgentProposalModel`
- `AgentExecutionRecordModel`
- `AgentArtifactModel`
- `AgentTimelineEventModel`
- `AgentHandoffModel`
- `AgentGuardrailDecisionModel`

Mandatory fields:

- `id`
- `request_id`
- `schema_version`
- `created_at`
- `updated_at`
- `created_by`

Task-specific fields:

- `task_domain`
- `task_type`
- `status`
- `input_payload`
- `current_step`
- `last_error`
- `requires_human`

Acceptance:

- migrations apply cleanly
- models support required indexes on `request_id`, `status`, `task_domain`

## WP-M1-03 Domain State Machine

Implement task lifecycle policy:

- allowed transitions
- rejected transitions
- terminal states
- resumable states

Must provide service methods:

- `create_task`
- `mark_context_ready`
- `mark_proposal_generated`
- `mark_awaiting_approval`
- `mark_approved`
- `mark_rejected`
- `mark_executing`
- `mark_completed`
- `mark_failed`
- `mark_needs_human`
- `cancel_task`
- `resume_task`

Acceptance:

- illegal transitions raise deterministic domain error
- legal transitions update task and timeline atomically

## WP-M1-04 Timeline And Artifacts

Implement timeline event writer with event types:

- `task_created`
- `state_changed`
- `step_started`
- `step_completed`
- `step_failed`
- `task_resumed`
- `task_cancelled`
- `task_escalated`

Acceptance:

- every task has timeline from creation
- event payloads include actor and request_id

## WP-M1-05 Base Runtime APIs

Implement:

- `POST /api/agent-runtime/tasks/`
- `GET /api/agent-runtime/tasks/`
- `GET /api/agent-runtime/tasks/{id}/`
- `GET /api/agent-runtime/tasks/{id}/timeline/`
- `GET /api/agent-runtime/tasks/{id}/artifacts/`
- `POST /api/agent-runtime/tasks/{id}/resume/`
- `POST /api/agent-runtime/tasks/{id}/cancel/`

Behavior rules:

- all responses must be structured JSON
- all error responses must return deterministic code/message
- all responses must include or map to `request_id`

Acceptance:

- all endpoints covered by contract tests
- pagination exists on list endpoint if needed

## WP-M1-06 Security And Audit Hook

Connect runtime API to existing RBAC and audit infrastructure.

Must support:

- deny access to disallowed roles
- record operation log for create/resume/cancel

Acceptance:

- RBAC tests pass
- audit trail exists for mutating runtime calls

## Test Plan

## Unit Tests

- model defaults and validation
- legal task transitions
- illegal task transitions
- resume rules
- cancel rules
- timeline event generation

## API Tests

- create task with valid payload
- create task with invalid domain
- get task by id
- list tasks filtered by status/domain
- resume task from resumable state
- reject resume from terminal state
- cancel active task
- reject cancel for completed task
- permission denied cases

## Migration Tests

- migrations run forward on clean DB
- migrations run on existing dev database

## Acceptance Criteria

M1 is accepted only if:

- all runtime models exist
- migrations pass
- all listed APIs are working
- transition logic is enforced server-side
- timeline events are written for every state change
- unit and API tests pass

## Exit Artifacts

- migration files
- API contract examples
- state machine diagram
- test report
- sample JSON request/response payloads
