# AgomTradePro System Baseline

> **Version**: `0.8.0`
> **Baseline date**: `2026-07-05`
> **Document role**: Single narrative source of truth
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
| **Business modules** | `37` | `governance/governance_baseline.json` |
| **MCP tools** | `368` | `governance/governance_baseline.json` |
| **Static test functions** | `6,241` | `governance/governance_baseline.json` |
| **`core/integration` app infrastructure imports** | `0` | governance ratchet |
| **`core/integration` ORM access lines** | `0` | governance ratchet |

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

Dynamic counts such as business-module count, MCP-tool count, static-test count, module-shape minima, large-file allowances, and bridge-debt ratchets are governed by:

- `governance/governance_baseline.json`
- `scripts/check_governance_consistency.py`

This file is the human-readable narrative layer; the JSON baseline remains the machine truth source.

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
- `core/integration` historical bridge debt remains ratcheted and is currently zero on both tracked counters, while thin realtime/pulse/audit/terminal/account/sector helper shims continue to be retired in favor of owning app services.

### 6.2 Large-file posture

Large historical Python files are governed by `governance_baseline.json`.

For `0.8.0`, TUI runtime metadata mutations are no longer concentrated in a single oversized repository file; runtime screen patches, injected metadata, and action patches are split into dedicated infrastructure modules.
The result-model follow-up is now split between a base helper and specialized business-facing helpers, so `apps/terminal/application/tui_workbench_result_models.py` is back under the repository large-file limit and no longer needs a temporary allowance.
The remaining identity-and-access runtime injection bundle is still temporarily allowlisted at `1,441` non-empty lines in `apps/terminal/infrastructure/tui_metadata_runtime_injection_identity_access.py` while the next split step is queued.

## 7. Testing posture

### 7.1 Scale baseline

- Static governed test functions: `6,241`
- Module coverage baseline: `37/37`
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
**Last updated**: `2026-07-09`
