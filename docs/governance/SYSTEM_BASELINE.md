# AgomTradePro System Baseline Narrative Index

> **Version**: `0.8.0`
> **Release baseline date**: `2026-07-05`
> **Narrative reviewed**: `2026-10-14`
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
| **Build** | See version metadata | [../VERSION.md](../VERSION.md) / `core/version.py` |
| **Release state** | Formal public release | release closure `0.8.0` |
| **Repo state** | Active development continues after `0.8.0` | branch/docs posture |
| **Business modules** | See machine baseline and generated module map | `governance/governance_baseline.json` / `governance/module_map.json` |
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

The `0.8.0` release defines the recommended stack, repeatable readiness evidence,
operator-readable scheduler/runtime verification and diagnostic commands. These
are release capabilities, not acceptance of a currently deployed environment.

Production acceptance requires evidence bound to the actual candidate,
configuration, environment and observation window. Readiness and decision gates
must be assessed independently; passing health or repository CI does not clear
DATA, Evidence, Audit, TUI or execution blockers. Current closure-unit status and
the repository execution focus are read from
[active_plan_registry.json](../../governance/active_plan_registry.json), with
observations retained under [deployment evidence](../deployment/README.md).

## 6. Governance baseline

### 6.1 Architecture and dependency guardrails

- Four-layer architecture remains mandatory.
- Domain purity is enforced by CI.
- App-level cycles remain hard-locked at zero.
- `core/integration` historical bridge debt remains ratcheted by the machine baseline, while thin realtime/pulse/audit/terminal/account/sector helper shims continue to be retired in favor of owning app services. Current debt values must be read from `governance/governance_baseline.json`.

### 6.2 Large-file posture

The non-empty line limit, permitted exceptions and any remediation metadata are
read from `governance/governance_baseline.json`. An older narrative describing a
temporary allowance cannot grant one after the machine registry removes it.

TUI runtime metadata was split during release and follow-up remediation; those
records explain the history. Current file size and exception validity are
established by the governance checker, not a retained prose list of pending splits.

## 7. Testing posture

### 7.1 Scale baseline

- Static governed test functions: see `governance/governance_baseline.json`
- Line/branch coverage thresholds and governed scopes: see [testing_quality_baseline.json](../../governance/testing_quality_baseline.json) and [coverage governance](../development/ci/coverage-governance.md)
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
**Last updated**: `2026-10-14`
