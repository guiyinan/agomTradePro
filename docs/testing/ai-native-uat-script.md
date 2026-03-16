# AI-Native Agent Runtime - UAT Script

> **Version**: M4 Release
> **Date**: 2026-03-16
> **Reviewer**: Non-developer operator

## Prerequisites

- Django dev server running (`python manage.py runserver`)
- API token available (use admin or staff user)
- curl or httpie installed

## UAT-01: Research Task Lifecycle

**Goal**: Verify a research task can be created, inspected, and completed.

### Steps

1. **Create task**
```bash
curl -X POST http://127.0.0.1:8000/api/agent-runtime/tasks/ \
  -H "Authorization: Token YOUR_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"task_domain":"research","task_type":"macro_portfolio_review","input_payload":{"focus":"regime_change"}}'
```
**Expected**: 201, response has `request_id` and `task.status == "draft"`

2. **Retrieve task**
```bash
curl http://127.0.0.1:8000/api/agent-runtime/tasks/{TASK_ID}/ \
  -H "Authorization: Token YOUR_TOKEN"
```
**Expected**: 200, task details match creation

3. **View timeline**
```bash
curl http://127.0.0.1:8000/api/agent-runtime/tasks/{TASK_ID}/timeline/ \
  -H "Authorization: Token YOUR_TOKEN"
```
**Expected**: 200, at least one `task_created` event

## UAT-02: Proposal Approval Flow

**Goal**: Verify proposal lifecycle from creation to approval.

### Steps

1. **Create proposal**
```bash
curl -X POST http://127.0.0.1:8000/api/agent-runtime/proposals/ \
  -H "Authorization: Token YOUR_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"proposal_type":"signal_create","risk_level":"high","proposal_payload":{"asset":"000001.SH","direction":"long"}}'
```
**Expected**: 201, `proposal.status == "generated"`, `approval_required == true`

2. **Submit for approval**
```bash
curl -X POST http://127.0.0.1:8000/api/agent-runtime/proposals/{ID}/submit-approval/ \
  -H "Authorization: Token YOUR_TOKEN"
```
**Expected**: 200, `proposal.status == "submitted"`, `guardrail_decision` present

3. **Approve proposal**
```bash
curl -X POST http://127.0.0.1:8000/api/agent-runtime/proposals/{ID}/approve/ \
  -H "Authorization: Token YOUR_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"reason":"Risk acceptable after review"}'
```
**Expected**: 200, `proposal.status == "approved"`

## UAT-03: Guarded Execution Flow

**Goal**: Verify execution runs guardrails and creates execution record.

### Steps

1. Complete UAT-02 to get an approved proposal
2. **Execute proposal**
```bash
curl -X POST http://127.0.0.1:8000/api/agent-runtime/proposals/{ID}/execute/ \
  -H "Authorization: Token YOUR_TOKEN"
```
**Expected**: 200, `proposal.status == "executed"`, `execution_record_id` present, `guardrail_decision.decision == "allowed"`

## UAT-04: Failure Recovery Flow

**Goal**: Verify failed task can be resumed.

### Steps

1. Create a task (UAT-01 step 1)
2. Set task to `failed` state (via admin or direct DB)
3. **Resume task**
```bash
curl -X POST http://127.0.0.1:8000/api/agent-runtime/tasks/{ID}/resume/ \
  -H "Authorization: Token YOUR_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"reason":"Fixed data issue"}'
```
**Expected**: 200, `task.status == "draft"`

4. **Attempt resume on completed task**
```bash
# First cancel or complete a task, then try resume
```
**Expected**: 400, `error_code == "invalid_state_transition"` or `"validation_error"`

## UAT-05: Dashboard Traceability Flow

**Goal**: Verify operator can inspect any task end-to-end.

### Steps

1. **View dashboard summary**
```bash
curl http://127.0.0.1:8000/api/agent-runtime/dashboard/summary/ \
  -H "Authorization: Token YOUR_TOKEN"
```
**Expected**: 200, `task_counts_by_status`, `proposal_counts_by_status`, `total_tasks`

2. **View full task detail**
```bash
curl http://127.0.0.1:8000/api/agent-runtime/dashboard/task/{TASK_ID}/ \
  -H "Authorization: Token YOUR_TOKEN"
```
**Expected**: 200, response includes `task`, `timeline`, `proposals`, `guardrail_decisions`, `execution_records`

3. **View proposals list**
```bash
curl http://127.0.0.1:8000/api/agent-runtime/dashboard/proposals/ \
  -H "Authorization: Token YOUR_TOKEN"
```
**Expected**: 200, `proposals` list with `total_count`

## UAT-06: Handoff Flow

**Goal**: Verify task can be handed to another agent/human.

### Steps

1. Create a task (UAT-01 step 1)
2. **Handoff task**
```bash
curl -X POST http://127.0.0.1:8000/api/agent-runtime/tasks/{ID}/handoff/ \
  -H "Authorization: Token YOUR_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"to_agent":"human_operator","handoff_reason":"Needs domain expertise","open_risks":["regime data stale"]}'
```
**Expected**: 200, `handoff_payload` includes `current_status`, `completed_steps`, `pending_steps`, `open_risks`

## Sign-Off

| UAT | Pass/Fail | Reviewer | Date |
|-----|-----------|----------|------|
| UAT-01 | | | |
| UAT-02 | | | |
| UAT-03 | | | |
| UAT-04 | | | |
| UAT-05 | | | |
| UAT-06 | | | |
