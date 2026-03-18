# AgomSAAF AI-Native Test Matrix

> **Version**: 1.1
> **Status**: FROZEN
> **Last Updated**: 2026-03-16
> **Owner**: AgomSAAF Project Team

## 1. Purpose

This document defines the required test coverage for each milestone of the AI-native L4 upgrade program.

Every implementation task must corresponding tests. No milestone may be declared complete without passing all required tests.

---

## 2. Test Types

| Type | Scope | Purpose |
|------|-------|---------|
| Unit | Single function/class | Verify isolated logic correctness |
| Model | Django Model validation | Verify database constraints, indexes, methods |
| API Contract | HTTP endpoint | Verify request/response format, status codes |
| SDK Contract | SDK method | Verify SDK method signature and error handling |
| MCP Registration | MCP tool/resource | Verify tool/resource is registered correctly |
| MCP Execution | MCP tool invocation | Verify tool returns correct structure |
| Integration | Multi-component | Verify components work together correctly |
| E2E | Full workflow | Verify complete user workflow |
| UAT | User acceptance | Verify business requirements are met |

---

## 3. Milestone Test Requirements

### 3.1 M0: Baseline Freeze

**Scope**: Documentation only

| Test Type | Requirement | Pass Criteria |
|----------|------------|---------------|
| Document Review | All freeze documents exist | Files committed to repository |
| Completeness Check | All required sections present | No missing sections |
| Consistency Check | No conflicts between documents | All cross-references valid |
| Sign-off | Internal owner approval | Written approval recorded |

**Test Files**:
- Manual review checklist (no automated tests for M0)

---

### 3.2 M1: Agent Runtime Foundation

| Backlog Items | 006-026 |
| Test Items | 027-030 |

| Test Type | Requirement | Pass Criteria |
|----------|------------|---------------|
| **Model Validation** | All models have correct fields and constraints | Migrations apply cleanly, no field errors |
| **State Machine Unit Tests** | All transitions tested | All valid transitions succeed, all invalid transitions rejected |
| **API Contract Tests** | All endpoints return correct format | Correct status codes, response shapes, error formats |
| **RBAC Integration Tests** | Permissions enforced | Unauthorized access rejected |
| **Audit Hook Tests** | All mutations logged | Audit records created correctly |

**Required Test Files**:
```
tests/unit/agent_runtime/
├── test_models.py              # Model validation (028)
├── test_state_machine.py       # State transitions (027)
├── test_timeline_service.py    # Timeline event writing
├── test_use_cases.py           # Use case unit tests
└── test_api_contract.py        # API contract tests (029)

tests/integration/agent_runtime/
├── test_task_lifecycle.py      # Full task lifecycle
└── test_api_rbac.py            # RBAC integration
```

**Coverage Requirement**: Domain layer ≥ 90%

---

### 3.3 M2: Context and Task Tools

| Backlog Items | 031-044 |
| Test Items | 045-049 |

| Test Type | Requirement | Pass Criteria |
|----------|------------|---------------|
| **Facade Unit Tests** | All facades tested with complete/partial data | Correct aggregation, graceful degradation |
| **SDK Contract Tests** | All SDK methods return correct format | Correct types, error handling |
| **MCP Registration Tests** | All tools/resources registered | Tools discoverable via list_tools() |
| **MCP Execution Tests** | All tools return structured JSON | Correct response shape |
| **Integration Tests** | Task start → context retrieval | Full flow works end-to-end |

**Required Test Files**:
```
tests/unit/agent_runtime/
├── test_research_facade.py      # ResearchTaskFacade (045)
├── test_monitoring_facade.py    # MonitoringTaskFacade (045)
├── test_decision_facade.py      # DecisionTaskFacade (045)
├── test_execution_facade.py     # ExecutionTaskFacade (045)
├── test_ops_facade.py           # OpsTaskFacade (045)
└── test_context_dtos.py         # Context DTOs

tests/sdk/
├── test_agent_runtime_sdk.py    # SDK contract tests (046)
└── test_agent_context_sdk.py    # Context SDK tests

tests/mcp/
├── test_task_tools.py           # MCP tool registration (047)
├── test_context_resources.py    # MCP resources
└── test_workflow_prompts.py     # MCP prompts

tests/integration/agent_runtime/
├── test_task_start_flow.py      # Task start integration (048)
└── test_context_retrieval.py    # Context retrieval
```

**Coverage Requirement**: Facade layer ≥ 85%

---

### 3.4 M3: Proposal-Approval-Execution

| Backlog Items | 050-064 |
| Test Items | 065-071 |

| Test Type | Requirement | Pass Criteria |
|----------|------------|---------------|
| **Proposal Transition Tests** | All status transitions tested | Valid transitions succeed, invalid rejected |
| **Guardrail Decision Tests** | All decision outcomes tested | Correct decision, evidence captured |
| **SDK Proposal Tests** | All proposal methods work | Correct return format |
| **MCP Proposal Tool Tests** | All proposal tools work | Structured responses |
| **E2E: Research Flow** | research → proposal → approval | Full flow succeeds |
| **E2E: Monitoring Flow** | monitoring → proposal → guardrail | Guardrail reject/escalate works |
| **E2E: Execution Flow** | approved → execute → record | Execution record created |

**Required Test Files**:
```
tests/unit/agent_runtime/
├── test_proposal_service.py      # Proposal lifecycle (065)
├── test_guardrail_engine.py      # Guardrail decisions (065)
├── test_execution_service.py     # Execution record creation
└── test_audit_enrichment.py      # Audit payload enrichment

tests/sdk/
└── test_proposal_sdk.py          # SDK proposal methods (066)

tests/mcp/
└── test_proposal_tools.py        # MCP proposal tools (067)

tests/e2e/
├── test_research_proposal_flow.py    # E2E: research → approval (068)
├── test_monitoring_guardrail_flow.py # E2E: monitoring → guardrail (069)
└── test_execution_flow.py            # E2E: execute → record (070)
```

**Coverage Requirement**: Service layer ≥ 85%

---

### 3.5 M4: Observability, Recovery, and Release

| Backlog Items | 072-084 |
| Test Items | 078-084 |

| Test Type | Requirement | Pass Criteria |
|----------|------------|---------------|
| **Resume Integration Tests** | Resume from failed states | Correct recovery behavior |
| **Handoff Integration Tests** | Task handoff works | Payload packaged correctly |
| **UI Smoke Tests** | All pages render | No 500 errors, correct data |
| **Full Regression Suite** | All previous tests pass | 100% pass rate |
| **UAT Scripts** | Business scenarios pass | All acceptance criteria met |

**Required Test Files**:
```
tests/integration/agent_runtime/
├── test_resume_behavior.py       # Resume tests (078)
└── test_handoff.py               # Handoff tests (078)

tests/ui/
├── test_task_pages.py            # Task list/detail pages (079)
├── test_proposal_pages.py        # Proposal pages
└── test_timeline_viewer.py       # Timeline viewer

tests/regression/
├── test_m1_regression.py         # M1 full regression (080)
├── test_m2_regression.py         # M2 full regression
├── test_m3_regression.py         # M3 full regression
└── test_full_suite.py            # Complete regression suite

tests/uat/
├── uat_research_scenario.py      # UAT: Research workflow (081)
├── uat_monitoring_scenario.py    # UAT: Monitoring workflow
├── uat_decision_scenario.py      # UAT: Decision workflow
└── uat_execution_scenario.py     # UAT: Execution workflow
```

**Coverage Requirement**: All previous tests still pass

---

## 4. Test Execution Rules

### 4.1 When to Run Tests

| Milestone | When | Tests to Run |
|-----------|------|--------------|
| M0 | After document creation | Manual review only |
| M1 | After each build task | Unit + API contract tests |
| M2 | After each build task | Unit + SDK + MCP tests |
| M3 | After each build task | Unit + E2E tests |
| M4 | After implementation | Full regression + UAT |

### 4.2 Pass Criteria

| Test Type | Pass Threshold |
|-----------|----------------|
| Unit Tests | 100% pass |
| API Contract Tests | 100% pass |
| SDK Contract Tests | 100% pass |
| MCP Tests | 100% pass |
| Integration Tests | 100% pass |
| E2E Tests | 100% pass |
| Regression Suite | 100% pass |
| UAT | All scenarios pass |

### 4.3 Failure Handling

If any test fails:

1. **Stop implementation** - Do not proceed to next task
2. **Triage failure** - Identify root cause
3. **Fix or escalate** - Fix immediately or escalate to project owner
4. **Re-run tests** - Verify fix works
5. **Document** - Update test if contract was wrong

---

## 5. Test Data Requirements

### 5.1 Test Data Principles

- Tests must not depend on production data
- Use factories or fixtures for test data
- Clean up test data after each test run
- Tests must be idempotent and repeatable

### 5.2 Required Test Fixtures

```python
# Example test fixtures structure
tests/fixtures/agent_runtime/
├── task_samples.py          # Sample task payloads
├── proposal_samples.py      # Sample proposal payloads
├── context_samples.py       # Sample context snapshots
└── guardrail_samples.py     # Sample guardrail decisions
```

---

## 6. Verification Commands

### 6.1 Per-Milestone Commands

```bash
# M1 verification
pytest tests/unit/agent_runtime/ -v --cov=apps/agent_runtime
pytest tests/integration/agent_runtime/ -v

# M2 verification
pytest tests/unit/agent_runtime/ -v --cov=apps/agent_runtime
pytest tests/sdk/ -v
pytest tests/mcp/ -v
pytest tests/integration/agent_runtime/ -v

# M3 verification
pytest tests/unit/agent_runtime/ -v --cov=apps/agent_runtime
pytest tests/sdk/ -v
pytest tests/mcp/ -v
pytest tests/e2e/ -v

# M4 verification
pytest tests/ -v --cov=apps/agent_runtime
pytest tests/regression/ -v
pytest tests/ui/ -v
```

### 6.2 Coverage Report

```bash
# Generate coverage report
pytest tests/ --cov=apps/agent_runtime --cov-report=html
```

---

## 7. Backlog-to-Test Mapping

| Backlog Range | Test Range | Milestone |
|---------------|------------|-----------|
| 006-026 | 027-030 | M1 |
| 031-044 | 045-049 | M2 |
| 050-064 | 065-071 | M3 |
| 072-077 | 078-084 | M4 |

---

## 8. Acceptance Gates

### M0 Acceptance
- [ ] `vendor-baseline-contract.md` exists and is internally approved
- [ ] State machine transitions are reviewed and confirmed by project owner
- [ ] All frozen names (entities, routes, SDK methods, MCP tools/resources) are confirmed
- [ ] `test-matrix.md` exists and coverage requirements are approved
- [ ] No conflicts exist between this document and `implementation-contract.md` or `schema-contract.md`
- [ ] Non-goals are explicitly documented
- [ ] Escalation rules are understood by vendor team

### M1 Acceptance
- [ ] All models migrated successfully
- [ ] State machine tests pass (all valid/invalid transitions)
- [ ] API contract tests pass (100% pass)
- [ ] Coverage ≥ 90% for domain layer, ≥ 85% for application layer
- [ ] RBAC integration verified
- [ ] Audit hooks verified

### M2 Acceptance
- [ ] All facades tested (complete and partial data scenarios)
- [ ] SDK contract tests pass (100% pass)
- [ ] MCP registration tests pass (all tools/resources discoverable)
- [ ] MCP execution tests pass (structured JSON responses)
- [ ] Integration tests pass (task start flow)
- [ ] Coverage ≥ 85% for facade layer

### M3 Acceptance
- [ ] Proposal lifecycle tests pass (all status transitions)
- [ ] Guardrail tests pass (all decision outcomes)
- [ ] SDK proposal tests pass (100% pass)
- [ ] MCP proposal tool tests pass (100% pass)
- [ ] E2E: Research → Proposal → Approval flow passes
- [ ] E2E: Monitoring → Proposal → Guardrail flow passes
- [ ] E2E: Approved → Execute → Record flow passes
- [ ] Coverage ≥ 85% for service layer

### M4 Acceptance
- [ ] Resume integration tests pass (all supported failed states)
- [ ] Handoff integration tests pass (payload packaging)
- [ ] UI smoke tests pass (no 500 errors)
- [ ] Full regression suite passes (100% pass)
- [ ] UAT scenarios pass (all acceptance criteria met)
- [ ] Release gate package ready
- [ ] All previous milestone tests still pass

---

*This document is frozen. Any changes require project owner approval.*
