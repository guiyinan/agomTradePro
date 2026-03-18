# AgomSAAF AI-Native Schema And Interface Contract

## Purpose

This document freezes the first implementation-level schema contract for models, APIs, SDK methods, MCP tools, and MCP resources.

The implementer must follow these schemas exactly unless a project owner issues a change request.

## 1. Persistent Entities

## 1.1 AgentTask

### Logical Fields

| Field | Type | Required | Notes |
|------|------|----------|------|
| `id` | `int` | yes | primary key |
| `request_id` | `str` | yes | stable request trace id |
| `schema_version` | `str` | yes | default `v1` |
| `task_domain` | `str` | yes | one of `research/monitoring/decision/execution/ops` |
| `task_type` | `str` | yes | task subtype |
| `status` | `str` | yes | frozen status enum |
| `input_payload` | `dict` | yes | JSON payload |
| `current_step` | `str or null` | no | current step key |
| `last_error` | `dict or null` | no | structured error payload |
| `requires_human` | `bool` | yes | default `false` |
| `created_by` | `int or null` | no | user id if authenticated |
| `created_at` | `datetime` | yes | server timestamp |
| `updated_at` | `datetime` | yes | server timestamp |

### Example JSON

```json
{
  "id": 101,
  "request_id": "atr_20260316_000001",
  "schema_version": "v1",
  "task_domain": "research",
  "task_type": "macro_portfolio_review",
  "status": "draft",
  "input_payload": {
    "portfolio_id": 308,
    "target_universe": "csi300"
  },
  "current_step": null,
  "last_error": null,
  "requires_human": false,
  "created_by": 12,
  "created_at": "2026-03-16T10:00:00+08:00",
  "updated_at": "2026-03-16T10:00:00+08:00"
}
```

## 1.2 AgentProposal

| Field | Type | Required | Notes |
|------|------|----------|------|
| `id` | `int` | yes | primary key |
| `request_id` | `str` | yes | trace id |
| `schema_version` | `str` | yes | `v1` |
| `task_id` | `int` | no | linked task |
| `proposal_type` | `str` | yes | e.g. `rebalance`, `signal_write` |
| `status` | `str` | yes | frozen proposal enum |
| `risk_level` | `str` | yes | `low`, `medium`, `high`, `critical` |
| `approval_required` | `bool` | yes | server-evaluated |
| `approval_status` | `str` | yes | `not_required`, `pending`, `approved`, `rejected` |
| `proposal_payload` | `dict` | yes | execution payload |
| `approval_reason` | `str or null` | no | human/system explanation |
| `created_by` | `int or null` | no | user id |
| `created_at` | `datetime` | yes | server timestamp |
| `updated_at` | `datetime` | yes | server timestamp |

## 1.3 AgentTimelineEvent

| Field | Type | Required | Notes |
|------|------|----------|------|
| `id` | `int` | yes | primary key |
| `request_id` | `str` | yes | trace id |
| `task_id` | `int` | yes | linked task |
| `proposal_id` | `int or null` | no | linked proposal |
| `event_type` | `str` | yes | frozen event name |
| `event_source` | `str` | yes | `api`, `sdk`, `mcp`, `system`, `human` |
| `step_index` | `int or null` | no | sequence |
| `event_payload` | `dict` | yes | details |
| `created_at` | `datetime` | yes | server timestamp |

## 1.4 AgentGuardrailDecision

| Field | Type | Required | Notes |
|------|------|----------|------|
| `id` | `int` | yes | primary key |
| `request_id` | `str` | yes | trace id |
| `task_id` | `int or null` | no | optional |
| `proposal_id` | `int or null` | no | optional |
| `decision` | `str` | yes | `allowed`, `blocked`, `needs_human`, `degraded_mode` |
| `reason_code` | `str` | yes | stable machine-readable reason |
| `message` | `str` | yes | human-readable summary |
| `evidence` | `dict` | yes | supporting data |
| `requires_human` | `bool` | yes | convenience flag |
| `created_at` | `datetime` | yes | server timestamp |

## 2. API Contract

## 2.1 Create Task

### Request

`POST /api/agent-runtime/tasks/`

```json
{
  "task_domain": "research",
  "task_type": "macro_portfolio_review",
  "input_payload": {
    "portfolio_id": 308,
    "target_universe": "csi300"
  }
}
```

### Success Response

```json
{
  "request_id": "atr_20260316_000001",
  "task": {
    "id": 101,
    "request_id": "atr_20260316_000001",
    "schema_version": "v1",
    "task_domain": "research",
    "task_type": "macro_portfolio_review",
    "status": "draft",
    "input_payload": {
      "portfolio_id": 308,
      "target_universe": "csi300"
    },
    "current_step": null,
    "last_error": null,
    "requires_human": false,
    "created_by": 12,
    "created_at": "2026-03-16T10:00:00+08:00",
    "updated_at": "2026-03-16T10:00:00+08:00"
  }
}
```

### Error Response

```json
{
  "request_id": "atr_20260316_000001",
  "success": false,
  "error_code": "invalid_task_domain",
  "message": "Unsupported task_domain.",
  "details": {
    "task_domain": "foo"
  }
}
```

## 2.2 Context Snapshot

### Request

`GET /api/agent-runtime/context/research/`

### Success Response Shape

```json
{
  "request_id": "ctx_20260316_000001",
  "domain": "research",
  "generated_at": "2026-03-16T10:05:00+08:00",
  "regime_summary": {},
  "policy_summary": {},
  "portfolio_summary": {},
  "active_signals_summary": {},
  "open_decisions_summary": {},
  "risk_alerts_summary": {},
  "task_health_summary": {},
  "data_freshness_summary": {}
}
```

## 2.3 Create Proposal

### Request

`POST /api/agent-runtime/proposals/`

```json
{
  "task_id": 101,
  "proposal_type": "rebalance",
  "risk_level": "high",
  "proposal_payload": {
    "portfolio_id": 308,
    "target_weights": {
      "510300.SH": 0.5,
      "159915.SZ": 0.5
    }
  }
}
```

### Success Response

```json
{
  "request_id": "apr_20260316_000001",
  "proposal": {
    "id": 501,
    "request_id": "apr_20260316_000001",
    "schema_version": "v1",
    "task_id": 101,
    "proposal_type": "rebalance",
    "status": "generated",
    "risk_level": "high",
    "approval_required": true,
    "approval_status": "pending",
    "proposal_payload": {
      "portfolio_id": 308,
      "target_weights": {
        "510300.SH": 0.5,
        "159915.SZ": 0.5
      }
    },
    "approval_reason": null,
    "created_by": 12,
    "created_at": "2026-03-16T10:10:00+08:00",
    "updated_at": "2026-03-16T10:10:00+08:00"
  }
}
```

## 2.4 Execute Proposal

### Success Response

```json
{
  "request_id": "aex_20260316_000001",
  "success": true,
  "proposal_id": 501,
  "execution_result": {
    "status": "success",
    "execution_record_id": 801,
    "guardrail_decision_id": 901
  }
}
```

### Blocked Response

```json
{
  "request_id": "aex_20260316_000001",
  "success": false,
  "proposal_id": 501,
  "error_code": "guardrail_blocked",
  "message": "Proposal execution was blocked by guardrail.",
  "guardrail": {
    "decision": "blocked",
    "reason_code": "approval_required"
  }
}
```

## 3. SDK Contract

## 3.1 `client.agent_runtime`

Methods:

- `create_task(task_domain: str, task_type: str, input_payload: dict) -> dict`
- `get_task(task_id: int) -> dict`
- `list_tasks(status: str | None = None, task_domain: str | None = None, limit: int = 50) -> dict`
- `resume_task(task_id: int) -> dict`
- `cancel_task(task_id: int) -> dict`
- `handoff_task(task_id: int, payload: dict) -> dict`
- `get_task_timeline(task_id: int) -> list[dict]`
- `get_task_artifacts(task_id: int) -> list[dict]`

## 3.2 `client.agent_context`

Methods:

- `get_context_snapshot(domain: str) -> dict`

Valid `domain`:

- `research`
- `monitoring`
- `decision`
- `execution`
- `ops`

## 3.3 `client.agent_runtime` proposal methods

- `create_proposal(task_id: int | None, proposal_type: str, risk_level: str, proposal_payload: dict) -> dict`
- `get_proposal(proposal_id: int) -> dict`
- `submit_proposal_for_approval(proposal_id: int) -> dict`
- `approve_proposal(proposal_id: int, payload: dict | None = None) -> dict`
- `reject_proposal(proposal_id: int, payload: dict | None = None) -> dict`
- `execute_proposal(proposal_id: int) -> dict`

## 4. MCP Tool Contract

## 4.1 Task Start Tools

All start-task tools must return:

```json
{
  "request_id": "atr_20260316_000001",
  "success": true,
  "task_id": 101,
  "task_domain": "research",
  "status": "draft"
}
```

Required tools and inputs:

- `start_research_task(payload: dict)`
- `start_monitoring_task(payload: dict)`
- `start_decision_task(payload: dict)`
- `start_execution_task(payload: dict)`
- `start_ops_task(payload: dict)`

## 4.2 Proposal Tools

- `create_agent_proposal(payload: dict)`
- `get_agent_proposal(proposal_id: int)`
- `approve_agent_proposal(proposal_id: int, payload: dict | None = None)`
- `reject_agent_proposal(proposal_id: int, payload: dict | None = None)`
- `execute_agent_proposal(proposal_id: int)`

All MCP tool failures must be structured JSON and must not raise raw stack traces to the client.

## 5. MCP Resource Contract

## 5.1 Context Resources

Each context resource must render a stable human-readable summary generated from the corresponding context snapshot.

Resources:

- `agomsaaf://context/research/current`
- `agomsaaf://context/monitoring/current`
- `agomsaaf://context/decision/current`
- `agomsaaf://context/execution/current`
- `agomsaaf://context/ops/current`

## 5.2 Task Timeline Resource

`agomsaaf://task/{task_id}/timeline`

Must include:

- task id
- status
- ordered timeline events
- latest error if any

## 5.3 Proposal Summary Resource

`agomsaaf://proposal/{proposal_id}/summary`

Must include:

- proposal type
- proposal status
- approval status
- risk level
- latest guardrail summary

## 6. Error Contract

All API, SDK, and MCP structured failures must contain:

- `request_id`
- `success: false`
- `error_code`
- `message`
- `details` or equivalent payload

No public interface may return unstructured internal tracebacks as the primary response body.
