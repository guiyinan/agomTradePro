# Milestone M2: Context Snapshots And Task Entry Tools

> **Status**: COMPLETED (2026-03-16)
> **Tests**: 55 unit tests (16 facade + 18 SDK + 21 MCP), all passing

## Objective

Make the runtime usable by adding context aggregation, task facades, SDK access, and MCP entrypoints.

This milestone turns the system from "task store" into "task-capable AI interface".

## In Scope

- context snapshot generation
- domain-specific facades
- runtime SDK module
- context SDK module
- first task-oriented MCP tools
- first context MCP resources
- integration tests for task start flow

## Out Of Scope

- proposal approval lifecycle
- guarded execution
- dashboard UI
- multi-agent orchestration

## Deliverables

- context APIs
- facade layer
- SDK runtime/context modules
- MCP task tools
- MCP resources
- contract and integration tests

## Work Packages

## WP-M2-01 Context Snapshot API

Implement context endpoints:

- `GET /api/agent-runtime/context/research/`
- `GET /api/agent-runtime/context/monitoring/`
- `GET /api/agent-runtime/context/decision/`
- `GET /api/agent-runtime/context/execution/`
- `GET /api/agent-runtime/context/ops/`

Each snapshot must return:

- `request_id`
- `domain`
- `generated_at`
- `regime_summary`
- `policy_summary`
- `portfolio_summary`
- `active_signals_summary`
- `open_decisions_summary`
- `risk_alerts_summary`
- `task_health_summary`
- `data_freshness_summary`

Acceptance:

- all five domains resolve successfully
- missing underlying data returns degraded but structured snapshot

## WP-M2-02 Domain Facade Layer

Implement facades:

- `ResearchTaskFacade`
- `MonitoringTaskFacade`
- `DecisionTaskFacade`
- `ExecutionTaskFacade`
- `OpsTaskFacade`

Responsibilities:

- read from multiple existing apps
- normalize to fixed DTOs
- centralize cross-domain orchestration
- isolate MCP and SDK from raw app internals

Acceptance:

- no MCP tool directly aggregates multiple apps without going through facade

## WP-M2-03 SDK Modules

Add SDK modules:

- `sdk/agomsaaf/modules/agent_runtime.py`
- `sdk/agomsaaf/modules/agent_context.py`

Public methods:

- `create_task`
- `get_task`
- `list_tasks`
- `resume_task`
- `cancel_task`
- `get_task_timeline`
- `get_context_snapshot`

Acceptance:

- module endpoints align with runtime APIs
- unit tests cover endpoint contracts

## WP-M2-04 MCP Task Tools

Add MCP tool file:

- `sdk/agomsaaf_mcp/tools/agent_task_tools.py`

Must provide:

- `start_research_task`
- `start_monitoring_task`
- `start_decision_task`
- `start_execution_task`
- `start_ops_task`
- `resume_agent_task`
- `cancel_agent_task`

Behavior rules:

- tools return structured JSON
- tools create runtime task records
- task start tools include linked context snapshot reference

Acceptance:

- tools are visible in MCP registration tests
- tools execute via mocked SDK and real local runtime API

## WP-M2-05 MCP Context Resources

Add resources:

- `agomsaaf://context/research/current`
- `agomsaaf://context/monitoring/current`
- `agomsaaf://context/decision/current`
- `agomsaaf://context/execution/current`
- `agomsaaf://context/ops/current`

Behavior rules:

- resources summarize latest context snapshot
- resources must not mutate state
- resources remain readable under permitted RBAC roles

Acceptance:

- resource listing and reading tests pass

## WP-M2-06 Workflow Guide Prompts

Add prompts:

- `run_research_workflow`
- `run_monitoring_workflow`
- `run_decision_workflow`
- `run_execution_workflow`
- `run_ops_workflow`

Rules:

- prompts are guidance only
- prompts may reference tools/resources
- prompts must not encode security logic

Acceptance:

- prompt listing tests pass

## Test Plan

## Unit Tests

- facade aggregation with complete data
- facade aggregation with partial data
- context DTO formatting

## SDK Tests

- runtime module endpoint contract
- context module endpoint contract
- structured error handling

## MCP Tests

- tool registration
- resource registration
- prompt registration
- task start execution using mocked SDK client

## Integration Tests

- generate research context
- generate monitoring context
- start research task and retrieve created task
- start ops task and retrieve timeline
- degraded snapshot when one upstream module is unavailable

## Acceptance Criteria

M2 is accepted only if:

- all five context endpoints work
- all five facades exist and are covered by tests
- SDK modules are available and tested
- MCP task tools are available and tested
- MCP resources are available and tested
- at least two start-task integration scenarios pass end-to-end

## Exit Artifacts

- context API examples
- facade dependency map
- SDK usage examples
- MCP tool and resource list
- integration test report
