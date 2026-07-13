# AgomTradePro System Baseline Narrative Index

> **Version**: `0.8.0`
> **Baseline date**: `2026-07-05`
> **Document role**: Narrative index only; it is not a second governance baseline
> **Machine source of truth**: `governance/governance_baseline.json`
> **Authority rule**: If narrative text and machine data differ, the machine baseline and its consistency checks prevail
> **Version management**: [../VERSION.md](../VERSION.md)

---

## 1. System identity

**Name**: AgomTradePro (Agom Strategic Asset Allocation Framework)

**Positioning**: AI-native personal investment research and decision platform

**Core principle**: do not place a correct trade thesis inside the wrong macro regime.

## 2. Current baseline

| Metric | Value | Source |
|------|------|------|
| **System version** | `0.8.0` | `core/version.py` |
| **Build** | `20260705` | `core/version.py` |
| **Release state** | Formal public release | release closure `0.8.0` |
| **Repo state** | Active development continues after `0.8.0` | branch/docs posture |
| **Business modules** | See machine baseline | `governance/governance_baseline.json` |
| **MCP tools** | See machine baseline | `governance/governance_baseline.json` |
| **Static test functions** | See machine baseline | `governance/governance_baseline.json` |
| **`core/integration` app infrastructure imports** | See governance ratchet | `governance/governance_baseline.json` |
| **`core/integration` ORM access lines** | See governance ratchet | `governance/governance_baseline.json` |

### Release interpretation

- `0.8.0` means the public version line is now formally cut.
- It does **not** mean the repository is frozen.
- Local-first usage and formal production usage are deliberately separated:
  - local first-run can stay lightweight
  - production acceptance requires the full runtime posture

## 3. Module baseline

### 3.1 Category view

- **Core engines**: `macro`, `regime`, `policy`, `signal`, `filter`
- **Asset analysis**: `asset_analysis`, `equity`, `fund`, `sector`, `sentiment`
- **Decision and execution**: `beta_gate`, `alpha_trigger`, `decision_rhythm`, `strategy`, `account`, `simulated_trading`, `realtime`, `audit`, `backtest`
- **Data and AI**: `alpha`, `factor`, `rotation`, `hedge`, `data_center`, `ai_provider`, `prompt`, `terminal`, `agent_runtime`, `ai_capability`
- **Operations and product surfaces**: `dashboard`, `events`, `task_monitor`, `share`, `setup_wizard`, `pulse`

### 3.2 Governance truth source

Dynamic counts such as business-module count, MCP-tool count, MCP governed-capability rollout, static-test count, module-shape minima, large-file allowances, and bridge-debt ratchets are governed by:

- `governance/governance_baseline.json`
- `scripts/check_governance_consistency.py`

This file is the human-readable narrative layer. It must not act as an independent or fallback source of governance data. It must not derive current counts from prose, tables, ordered lists, completion logs, or historical reports. Update the JSON baseline only after code-derived checks establish the actual values, and use the consistency script output as the authoritative report.

MCP consolidation metrics are stored under `mcp_governance`; the root `mcp_tool_count` remains the total static `@server.tool()` definition count used by the repository governance checker, while `mcp_governance.legacy_capability_count` tracks the legacy catalog projection.

Do not update this document merely because a governance count changed. Update it only when the narrative structure, field-to-source mapping, or deployment posture changes.

## 4. Deployment posture

### 4.1 Local first-run / demo posture

| Concern | Default |
|------|------|
| Database | `SQLite` |
| Redis | optional |
| Celery worker/beat | optional |
| Goal | first run, local development, feature work, lightweight preview |

### 4.2 Formal production posture for 0.8.0

| Concern | Official recommendation |
|------|------|
| Primary database | `PostgreSQL` |
| Queue/cache | `Redis` |
| Task runtime | `Celery worker + Celery beat` |
| Evidence persistence | persist `var/readiness-evidence/` |
| Runtime proof | worker, beat, quote pre-refresh, daily readiness evidence, weekly advisor evidence must be inspectable |

### 4.3 Transitional / diagnostic posture

SQLite on VPS is allowed only for:

- demo environments
- explicit seed/restore workflows
- diagnostics
- legacy migration handoff

It is **not** the formal `0.8.0` production recommendation.

## 5. Operations acceptance baseline

### 5.1 Standard readiness chain

The accepted release-closure path is:

```text
quote pre-refresh -> daily readiness evidence -> readiness window validation
                 -> scheduler safety proof -> local/VPS runtime proof
```

### 5.2 Required evidence posture

- Evidence files live under `var/readiness-evidence/`
- Local strict acceptance and VPS scheduler-clean acceptance are documented runbook flows
- `task_monitor` is part of the formal release posture, not an unfinished appendix

### 5.3 Production-stability meaning

For `0.8.0`, “production ready” means:

- a recommended production stack is explicit
- readiness evidence is repeatable
- scheduler/runtime verification is operator-readable
- failures can be diagnosed from standard commands and evidence artifacts

## 6. Governance baseline

### 6.1 Architecture and dependency guardrails

- Four-layer architecture remains mandatory.
- Domain purity is enforced by CI.
- App-level cycles remain hard-locked at zero.
- `core/integration` historical bridge debt remains ratcheted by the machine baseline, while thin realtime/pulse/audit/terminal/account/sector helper shims continue to be retired in favor of owning app services. Current debt values must be read from `governance/governance_baseline.json`.

### 6.2 Large-file posture

Large historical Python files are governed by `governance_baseline.json`.

For `0.8.0`, TUI runtime metadata mutations are no longer concentrated in a single oversized repository file; runtime screen patches, injected metadata, and action patches are split into dedicated infrastructure modules.
The result-model follow-up is now split between a base helper and specialized business-facing helpers, so `apps/terminal/application/tui_workbench_result_models.py` is back under the repository large-file limit and no longer needs a temporary allowance.
The remaining identity-and-access runtime injection bundle is still temporarily governed by the machine large-file allowance while the next split step is queued. The current allowance must be read from `governance/governance_baseline.json`.

## 7. Testing posture

### 7.1 Scale baseline

- Static governed test functions: see `governance/governance_baseline.json`
- Module coverage baseline: see `governance/governance_baseline.json`
- Full `pytest` collection/execution remains a runtime fact, not a hard-coded doc number

### 7.2 Release-closure verification

The `0.8.0` closure emphasizes:

- governance consistency
- targeted TUI metadata repository regression coverage
- readiness/task-monitor acceptance commands
- release regression evidence

See:

- [../testing/0.8.0-release-regression-report-2026-07-05.md](../testing/0.8.0-release-regression-report-2026-07-05.md)
- [../operations/runbook.md](../operations/runbook.md)

---

**Maintainer**: AgomTradePro Team
**Last updated**: `2026-07-12`
