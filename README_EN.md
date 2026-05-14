<div align="center">

**[English](README_EN.md) | [中文](README.md)**

# AgomTradePro

### Stop Trading Against the Macro. Start Trading With Discipline.

**An AI-native personal research foundation that gives AI a data foundation and decision framework, bringing macro judgment, strategy discipline, agent capabilities, and execution workflows into one system.**

[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/downloads/)
[![Django 5.x](https://img.shields.io/badge/django-5.x-green.svg)](https://www.djangoproject.com/)
[![Tests](https://img.shields.io/badge/tests-5%2C655-brightgreen.svg)](#testing)
[![Modules](https://img.shields.io/badge/business_modules-36-purple.svg)](#architecture)
[![MCP Tools](https://img.shields.io/badge/MCP_tools-326-orange.svg)](#ai-native-integration)
[![Status](https://img.shields.io/badge/status-active_development-yellow.svg)](#project-status)
[![License](https://img.shields.io/badge/license-Apache%202.0-blue.svg)](LICENSE)

[Quick Start](#quick-start) · [Why This Exists](#why-this-exists) · [Why Fork / Star](#why-fork--star) · [Architecture](#architecture) · [AI Integration](#ai-native-integration) · [Screenshots](#screenshots) · [Docs](docs/INDEX.md)

</div>

---

## What's New

> This section is maintained day by day and should focus on user-visible changes from the last 1-7 days.

### 2026-05-14

- Equity Detail chart defaults are now derived from real market sessions, so intraday, post-close, and non-trading-time visits all fall back to the correct completed trading day instead of a not-yet-closed or future date

### 2026-05-13

- A dedicated `config_center` module and Qlib training console are now in place, consolidating training config, runtime summaries, management entrypoints, and related API/SDK/MCP capabilities into one configuration surface
- Qlib token permissions were tightened, with matching updates across the MCP guide, config-center pages, and access control; the equity detail loading path was also unblocked so the page degrades more safely when some local context is missing

### 2026-05-12

- Data Center now supports on-demand hydration, giving equity and related read paths a clearer fetch-and-audit route when canonical source data is missing locally
- Pulse macro freshness repair and Factor calculation-result page cleanup landed in the same pass, improving reliability across research-facing screens

### 2026-05-10

- Workspace Snapshot and Task Monitor scheduler-console pages are now available, making periodic jobs, snapshot refreshes, and scheduler state easier to inspect after setup
- MCP onboarding and startup welcome context are now built in, so first-time AI-agent integration surfaces available capabilities, config entrypoints, and usage hints earlier

### 2026-05-02

- Another architecture-governance pass is now closed out: remaining cross-module `infrastructure` reach-through in paths such as `ai_provider`, `data_center`, `equity`, and `policy` has been pushed further behind app-owned providers and `core/integration/*`
- Runtime bridges and test-safe provider paths are stable again, so `runtime_settings`, `runtime_benchmarks`, and related `signal` reads no longer depend on brittle legacy bridge wiring in test or degraded environments
- CI quality gates were tightened again: the repo now includes `ci-fast-feedback.yml`, `scripts/select_quality_targets.py`, and `.pre-commit-config.yaml`, with the `rc-gate` and architecture-guardrail rules/docs updated in the same pass; the GitHub Actions Node 20 shim warnings were removed too

### 2026-05-01

- The Alpha exit loop backend is now in place, giving decision-rhythm, signal-query, auto-trading execution, and task-dispatch flows one end-to-end exit-advice path backed by new regression coverage
- Dashboard exit-chain entry points are now unified: the homepage workflow, Decision Workspace sidebar, Alpha history/detail panel, and metrics/stock APIs all route through consistent query and interface-service boundaries instead of oversized mixed views
- Workspace compatibility also improved in this pass: non-numeric workspace account ids no longer break the flow, the Decision/Simulated Trading module cycle has been split, and production static-asset handling is more robust after cleaning out redundant vendored frontend bundles

### 2026-04-30

- `main` is aligned again with the latest CI-green development line, so the public branch now includes the async task-visibility fixes across Alpha, Dashboard, Policy, and Data Center flows
- Key async entrypoints that already return a `task_id` now write an early `task_monitor` record before the worker actually picks the task up, removing the "task was queued but temporarily invisible" blind spot
- A focused regression entrypoint, `python scripts/run_alpha_ops_regression.py`, now covers Alpha ops, Dashboard Alpha refresh, Policy RSS fetch, and Data Center decision reliability repair for task visibility and provider-alert semantics
- Nightly/default integration regression is now explicitly split from `live_required`, `optional_runtime`, and `diagnostic` suites, so contributors can run the default automated path without accidentally pulling in live-server, worker, or script-style diagnostics

### 2026-04-29

- Macro MCP/SDK access is now officially consolidated under `data_center`: the public macro tool family is `data_center_*`, and indicator/unit-rule governance is directly exposed through MCP/HTTP
- Macro-governance and MCP docs are now aligned with the current local snapshot of `326` registered MCP tools

### 2026-04-28

- Alpha / Qlib Ops Console V1 is now in place: there are dedicated inference-management and Qlib runtime-data pages, with read access for staff and manual actions reserved for superusers
- This ops-console pass and the CI-stability fixes did not change the external MCP contract: SDK / MCP tool names, parameter schemas, canonical API paths, and RBAC semantics remain unchanged
- `tests/integration/test_alpha_stress.py` now runs offline by default so ETF fallback no longer drifts into live `akshare` requests on GitHub Actions; the latest push CI and Nightly are green again

### 2026-04-27

- The final cross-app cleanup around `strategy` and `asset_analysis` is now closed out: asset-pool lookup, name resolution, and screening assembly now flow through application facades and the shared registry instead of a bridge module plus cross-app ORM reach-through
- A batch of silent Domain / Application fallback branches now emits explicit logs, so the system can keep its degraded-path behavior without hiding operational failures
- GitHub Actions Nightly is green again; this pass fixed the duplicate `tests/unit` collection conflict, Strategy execution behavior when the investable pool has not been prewarmed yet, and the outdated parameter signature used by the Decision Workspace AI invalidation-draft endpoint
- `main` and `dev/next-development` are aligned again to the same commit, so the public branch and active development branch now reflect the same state

### 2026-04-24

- Repository-wide governance checks are now in place: `governance/governance_baseline.json`, `scripts/check_governance_consistency.py`, and the CI workflow now lock historical debt while blocking regressions in module shape, MCP counts, docs links, AppConfig placement, and Application-layer pandas/numpy imports
- The architecture-debt remediation line has landed on `main`: multiple Interface / Application hot paths now route through application interface services, repository providers, and infrastructure repositories instead of touching ORM or infrastructure directly
- Contract drift in Alpha recommendations, Decision readiness, Data Center sync, and Share snapshot JSON serialization has been repaired, and the related guardrail and integration tests now match the current implementation
- `main` and `dev/next-development` are aligned to the same commit, with the latest push CI and Nightly green across unit, API, integration, app-local, guardrail, architecture report, and Playwright smoke stages

### 2026-04-05

- The financial datasource page has been consolidated into a unified datasource center, so public providers, licensed providers, local-terminal providers, and pending configs now live in one workbench
- Macro datasource management now includes built-in connection testing, with page-level probes and log output for sources such as Tushare, AKShare, and QMT
- The old `market_data` provider surface has been folded back into the unified datasource center, keeping config-center and provider-inventory views aligned
- The `macro` layer-boundary regressions have been repaired, and GitHub Actions is back to green on both `Architecture Layer Guard` and `Logic Guardrails`

### 2026-04-04

- The equity detail page now includes a technical-chart surface with daily/intraday data support and matching API contracts
- Equity detail context is richer than before, with clearer market-state, source, and technical context alongside valuation and fundamentals
- When the local Qlib runtime is unavailable, the Alpha path now reuses the latest valid cache instead of collapsing to an empty result
- The settings center, admin-facing surfaces, MCP tools page, docs management, and server-log views have been visually unified into a more consistent management shell

### 2026-04-03

- RSS fetching no longer hangs on uncontrolled timeouts, and RSS source configuration now exposes timeout / retry / RSSHub / proxy fields in the UI
- Default RSS seed sources have been refreshed to working feed URLs, so demo environments no longer depend on broken `rsshub.app` defaults
- Development `runserver` logs are now persisted to files, making local startup/debug review much easier

### 2026-03-30

- Alpha reliability is now explicit end to end: Dashboard, API, and MCP all surface whether the current recommendation uses cached data, whether it was forward-filled, and which signal date is actually being shown
- When local Qlib data is stale, the system no longer pretends the result is fresh; it returns a clear `degraded` state with a user-visible reliability notice
- The Qlib runtime soft switch remains database-driven, and the live database path settings have now been written back explicitly instead of relying only on runtime fallback
- The pytest collection baseline now covers both `tests/` and `apps/*/tests`, and UAT summary generation is based on real JUnit XML instead of placeholder parsing
- Playwright regression now supports a "production DB snapshot + isolated server" path so real-data browser verification can run without writing into the live `db.sqlite3`

### 2026-03-24

- The full Regime Navigator + Pulse redesign rollout is now closed out across Dashboard, Decision Workspace, and the Regime page
- Dashboard navigation has been tightened, and `beta_gate`, `alpha_trigger`, and `decision_rhythm` are no longer exposed as standalone primary homepage entries
- The Regime page now includes a historical `Regime + Pulse + Action` layered time-series chart
- The Dashboard now supports optional browser-level Pulse transition notifications
- SDK, MCP, and docs are aligned around `decision_workflow.get_funnel_context(trade_id, backtest_id)` and `client.pulse.*`

### Maintenance Rule

- Only record changes that matter to users, integrators, or fork maintainers
- Keep the same-day updates under the same date instead of creating noise
- Anything important beyond one week should be moved into [`CHANGELOG.md`](CHANGELOG.md)

---

> **Disclaimer**  
> This project is for **personal research and system experimentation only**. It does not represent the investment views of any institution and **does not constitute investment advice**.

---

## The Core Difference

AgomTradePro is not trying to be just another quant dashboard, AI stock demo, or market data UI. It is built as a way to **construct your own AI-native research foundation**.

- **AI-native, not AI-added-later**: MCP, Terminal CLI, Agent Runtime, and Capability Catalog are built into the system
- **Not a single-purpose tool, but a research and decision substrate**: macro, policy, signal, approval, execution, and audit are connected end to end
- **Designed to be extended**: you can fork it into your own macro lab, agent-driven research platform, or strategy infrastructure
- **Built with agentic coding workflows**: a meaningful part of the project was shaped using **Claude Code and Codex** as part of the actual development loop

If what you want is not “another dashboard” but “a base for building your own AI research stack,” this project is aimed at that problem.

---

## Project Status

> This project is already runnable and demo-ready, but it is **still under active development**.  
> The current repository's **frontend presentation and parts of the operational flow are still being revised**.  
> The more accurate way to read it right now is as a system that is gradually becoming a **data foundation and decision framework for AI**, rather than a frozen SaaS product; public updates will continue refining the UI, interaction flow, monitoring, and documentation.

- Core macro admission flow is already usable: Regime / Policy / Signal / approval / execution / audit
- The new primary flow is in place: Dashboard daily mode + Decision Workspace decision mode + Regime Navigator / Pulse linkage
- AI-native surfaces are already in place: **native MCP, Terminal CLI, Agent Runtime, Capability Catalog**
- Still being improved: scheduled task monitoring, more public demo paths, documentation polish, deployment experience

---

## Quick Start

### Windows One-Click Start

1. Run `install.bat` from the repository root
2. Run `start.bat` and choose `Quick Start`
3. Open `http://localhost:8000/setup/` and finish the setup wizard

> The local virtual environment is expected at `agomtradepro/`. It is local-only, ignored by git, and not committed to the repository.
>
> If you are contributing rather than just evaluating the repo, use `install.bat --dev` to install pytest, Playwright, mypy, and other development tools.

### Manual Setup

#### Prerequisites

- Python 3.11+

#### Install

```bash
# Clone
git clone https://github.com/guiyinan/agomTradePro.git
cd agomTradePro

# Virtual environment
python -m venv agomtradepro
source agomtradepro/bin/activate  # Linux/Mac
# or: agomtradepro\Scripts\activate  # Windows

# Install dependencies
pip install -r requirements.txt

# Generate local .env and security keys
python manage.py bootstrap_local_env

# Database setup
python manage.py migrate

# Start development server
python manage.py runserver

# Visit http://localhost:8000/setup/ to complete the setup wizard
```

The setup wizard will guide you through:
1. **Auto-generate security keys** — `SECRET_KEY` and `AGOMTRADEPRO_ENCRYPTION_KEY` are generated automatically and written to `.env` when missing
2. Create an admin account
3. Configure AI providers (optional) — API keys are encrypted at rest with Fernet
4. Configure data sources (optional)

> A first local run defaults to `SQLite + synchronous tasks`. You do not need PostgreSQL, Redis, or Docker just to get the system running.

### Optional System Initialization

If you want to seed built-in configuration and template data, run:

```bash
python manage.py init_all -y
python manage.py init_all --skip-macro -y
```

### Tests

```bash
pytest tests/ -v --cov=apps
pytest tests/integration/ -v -m "not live_required and not optional_runtime and not diagnostic"
```

---

## Contact

If you want to discuss the project's direction or follow-up iterations, you can reach me on WeChat: `Uncleliou`

---

## Why This Exists

Financial markets have been moving hard. What becomes exhausting is not just volatility itself, but the feeling that **you keep reading more, thinking more, and still become more confused**.

This project did not start from “let's build a platform.” It started from a simpler question:

> **If I am the confused participant in a noisy market, can I build a system that explains the environment to myself before I act?**

Most retail investors lose money not because their stock picks are bad, but because they trade at the wrong time.

- You buy quality stocks — **during stagflation**
- You follow a solid strategy — **while policy is tightening**
- You see a clear signal — **but the macro regime is shifting under your feet**

**The result?** Correct logic, wrong world. Loss.

AgomTradePro is built on one principle:

> **"Don't bet in the wrong macroeconomic world, even with correct logic."**

It acts as a **macro gatekeeper** — filtering every investment decision through regime analysis (growth × inflation quadrants) and policy state before you can act. It doesn't predict prices. It prevents mistakes.

---

## Why Fork / Star

If you're looking for more than "yet another stock dashboard" and want a **base that can keep growing into strategy logic, agent tooling, and execution workflows**, this repo is worth following.

- **It is not just a demo UI**: login, setup, analysis, decision flow, approval, execution, and audit are already connected
- **It is not an AI wrapper**: native MCP, Terminal CLI, Agent Runtime, and Capability Catalog are built into the system
- **It is not a one-off script pile**: 36 business modules with explicit DDD boundaries make it suitable for long-term extension
- **It is forkable**: the codebase is modular enough for private strategy kernels, internal research platforms, or custom agent workflows
- **It already has product shape**: Setup Wizard, Dashboard, CLI, and MCP console make the system legible at a glance

For most people, the best way to use this repo is:

1. `Star` it to follow the roadmap
2. `Fork` it as your own macro / strategy / agent infrastructure base
3. Extend the modules around your own trading logic or research workflow

---

## What Problems It Solves

### 1. 📡 Information Overload → Structured Macro Intelligence

You're drowning in PMI releases, CPI prints, M2 data, policy announcements, and market noise. AgomTradePro ingests macro data from multiple sources, normalizes it, applies Kalman/HP filtering, and distills it into one clear answer: **which regime are we in?**

- **Recovery** (growth ↑ inflation ↓) — go risk-on
- **Overheat** (growth ↑ inflation ↑) — be selective
- **Stagflation** (growth ↓ inflation ↑) — defensive
- **Deflation** (growth ↓ inflation ↓) — wait

No more guessing. No more conflicting narratives. One macro state, updated with real data.

### 2. 🔒 Emotional Trading → Systematic Discipline

Every trade must pass through gates before execution:

```
Your Idea → Regime Gate → Policy Gate → Signal Validation → Approval → Execution
                ↓              ↓              ↓
           "Is the macro    "Is policy    "Does this signal
            favorable?"    supportive?"   have invalidation
                                          logic?"
```

- **No signal without invalidation logic** — you must define *when you're wrong* before you enter
- **No trade in hostile regimes** — the system physically blocks it
- **Decision rhythm constraints** — prevents overtrading and FOMO
- **Full audit trail** — every decision recorded for post-trade review

### 3. 🤖 Manual Workflows → AI-Native Automation

Not just an API wrapper. AgomTradePro is built for the AI agent era:

- **Python SDK** — full programmatic access across the system's business modules
- **MCP Server (326 registered tools)** — plug directly into Claude, Cursor, or any MCP-compatible AI
- **Terminal CLI** — AI-interactive command interface
- **Agent Runtime** — task orchestration with proposal → approval → execution lifecycle

Your AI agent can check the macro regime, evaluate signals, and propose trades — but still needs human approval to execute. **AI speed, human judgment.**

---

## Screenshots

<details>
<summary><b>Logged-in Dashboard</b></summary>

![Dashboard](docs/images/readme/dashboard_logged_in.png)

*The first screen after login shows the system as an operating console: accounts, macro state, decision plane, AI stock analysis, and workflow status in one place.*

</details>

<details>
<summary><b>Setup Wizard</b></summary>

![Setup Wizard](docs/images/readme/setup_wizard.png)

*First launch auto-generates security keys, creates admin, and configures AI provider and data sources — no manual .env editing required.*

</details>

<details>
<summary><b>Terminal CLI</b></summary>

![Terminal CLI](docs/images/readme/terminal_cli.png)

*Not just a chat box. This is an operations-oriented CLI surface with commands, context, session state, and AI interaction built into the product.*

</details>

<details>
<summary><b>Native MCP Tools Console</b></summary>

![MCP Tools](docs/images/readme/mcp_tools.png)

*Built-in MCP catalog, schema inspection, and terminal/routing switches. This makes the MCP story feel native rather than bolted on.*

</details>

---

## Features

### Core System
| Module | What It Does |
|--------|-------------|
| **Regime Engine** | Determines current macro regime from growth/inflation indicators with Z-score normalization |
| **Policy Gate** | Tracks fiscal/monetary policy events and their impact on risk appetite |
| **Signal Manager** | Creates, validates, and tracks investment signals with mandatory invalidation logic |
| **Decision Workflow** | Pre-check → approval → execution pipeline with rhythm constraints |
| **Backtest Engine** | Historical validation with Brinson attribution analysis |
| **Audit System** | Post-trade review with full decision trace and performance attribution |

### Portfolio & Execution
| Module | What It Does |
|--------|-------------|
| **Simulated Trading** | Paper trading with margin tracking and daily inspection |
| **Real-time Monitor** | Price alerts, top movers, market surveillance |
| **Strategy System** | DB-driven position rules, strategy binding per portfolio |
| **Sector Rotation** | Regime-based sector allocation recommendations |

### AI & Smart Analysis
| Module | What It Does |
|--------|-------------|
| **Alpha Scoring** | AI stock scoring with 4-layer degradation (Qlib → Cache → Simple → ETF) |
| **Factor Management** | Factor calculation, IC/ICIR evaluation |
| **Hedge Strategies** | Futures hedging calculation and portfolio protection |
| **Sentiment Gate** | News/sentiment analysis as additional risk filter |

### Data Sources
| Source | Coverage |
|--------|----------|
| **Tushare Pro** | A-share market data, SHIBOR, index data |
| **AKShare** | Macro indicators (PMI, CPI, M2, GDP, etc.) |
| **QMT Local** | Local terminal market access and runtime probing |
| **Failover** | Auto-switch with 1% tolerance validation |

---

## Architecture

AgomTradePro is not a bundle of pages and APIs. It is designed more like an **investment operating system**:

```
Data sources → Macro judgment → Policy filter → Signal generation → Decision constraints → Approval/execution → Audit/review
                ↓                ↓                ↓                  ↓
             Regime           Policy           Signal          Workflow / Audit
```

That matters because when you fork it, you do not need to rewrite the whole thing. You can keep the existing seams and grow from there.

### 1. Business Architecture

- **Macro layer**: `macro`, `regime`, `policy` answer "what environment are we in?"
- **Decision layer**: `signal`, `beta_gate`, `alpha_trigger`, `decision_rhythm` answer "should we act now?"
- **Execution layer**: `strategy`, `simulated_trading`, `realtime` answer "how do we execute and monitor it?"
- **Analysis layer**: `backtest`, `audit`, `factor`, `rotation`, `hedge` answer "why did it work, and what failed?"
- **AI layer**: `terminal`, `agent_runtime`, `ai_capability`, `prompt`, `ai_provider` answer "how do real agents plug into the system?"

### 2. Technical Architecture

Core business logic follows strict **Domain-Driven Design** with four explicit layers:

```
┌─────────────────────────────────────────────────────────┐
│  Interface Layer    │ REST API, Admin UI, Serializers    │
├─────────────────────┼───────────────────────────────────┤
│  Application Layer  │ Use Cases, Celery Tasks, DTOs     │
├─────────────────────┼───────────────────────────────────┤
│  Infrastructure     │ Django ORM, API Adapters, Repos   │
├─────────────────────┼───────────────────────────────────┤
│  Domain Layer       │ Entities, Rules, Services          │
│  (pure Python only) │ No Django, No Pandas, No NumPy    │
└─────────────────────────────────────────────────────────┘
```

**Why this is useful when forking:**

- you can swap data sources without rewriting domain rules
- you can rebuild the UI without rewriting the investment core
- you can plug in your own agents without removing approval and audit controls
- you can extract individual modules instead of dragging the whole app everywhere

### 3. Governance Guardrails

The architecture rules are enforced by CI, not only documented.

- **Delta guard**: `Architecture Layer Guard` scans changed lines and fails new Domain / Application / Interface layer violations
- **Repository-wide governance check**: `scripts/check_governance_consistency.py` scans MCP tool counts, key documentation counters, `docs/INDEX.md` links, module shape, misplaced `AppConfig`, singular `dto.py`, and Application-layer pandas/numpy imports
- **Historical-debt baseline**: `governance/governance_baseline.json` records the current accepted state, so old debt stays visible while new regressions fail CI

See [Architecture Guardrails](docs/governance/ARCHITECTURE_GUARDRAILS.md) for details.

### 4. AI Architecture

- **MCP Server** exposes system capabilities directly to Claude, Cursor, Codex, and other agentic tools
- **Terminal CLI** provides an operations-oriented AI interface instead of a generic chat widget
- **Capability Catalog** manages tool routing, schema, switches, and discoverability
- **Agent Runtime** turns proposal → pre-check → approval → execution into a real system path

This is one of the strongest reasons to fork the project: the AI layer is native to the product, not stapled onto the side.

### 5. Current State

- **Core structure is stable enough** to keep extending confidently
- **Product surfaces are mature enough** to show that this is not a toy project
- **Plenty is still evolving**, which makes this a good time to watch, fork, and build on top of it

---

## AI-Native Integration

### Python SDK

```python
from agomtradepro import AgomTradeProClient

client = AgomTradeProClient(
    base_url="http://localhost:8000",
    api_token="your_token"
)

# What macro regime are we in right now?
regime = client.regime.get_current()
print(f"Regime: {regime.dominant_regime}")  # e.g., "Recovery"

# Can I even trade this asset right now?
check = client.signal.check_eligibility(
    asset_code="000001.SH",
    logic_desc="PMI rising, economic recovery"
)

# Create a signal (with mandatory invalidation logic)
if check["is_eligible"]:
    signal = client.signal.create(
        asset_code="000001.SH",
        logic_desc="PMI rising, economic recovery",
        invalidation_logic="PMI falls below 50 for 2 consecutive months",
        invalidation_threshold=49.5
    )
```

### MCP Server for AI Agents

Connect AgomTradePro to Claude Code, Cursor, or any MCP-compatible AI:

```json
{
  "mcpServers": {
    "agomtradepro": {
      "command": "python",
      "args": ["-m", "agomtradepro_mcp.server"],
      "env": {
        "AGOMTRADEPRO_BASE_URL": "http://localhost:8000",
        "AGOMTRADEPRO_API_TOKEN": "your_token"
      }
    }
  }
}
```

Then just talk to your AI:

```
You:    "What's the current macro regime? Should I add to my equity position?"

Claude: [calls get_current_regime] → Stagflation (growth ↓, inflation ↑)
        [calls get_policy_status] → Tight monetary policy

        "The macro regime is Stagflation with tight policy. This is a
         defensive environment. Adding equity exposure would go against
         the regime signal. Consider waiting for regime transition or
         look at hedge positions instead."
```

**326 MCP tools** do not just expose a few query endpoints. They span macro, policy, signals, backtesting, accounts, portfolios, trading flows, AI capability routing, terminal commands, runtime orchestration, and system-level operations.

### Decision Workflow via AI

```
AI Agent proposes trade
        ↓
System runs pre-check (regime gate, policy gate, rhythm check)
        ↓
Proposal created with full context
        ↓
Human reviews and approves/rejects
        ↓
Guarded execution with audit trail
```

AI speed for analysis. Human judgment for execution. Full traceability for review.

---

## Manual Setup Details

### Prerequisites

- Python 3.11+

### Setup

```bash
# Clone
git clone https://github.com/guiyinan/agomTradePro.git
cd agomTradePro

# Virtual environment
python -m venv agomtradepro
source agomtradepro/bin/activate  # Linux/Mac
# or: agomtradepro\Scripts\activate  # Windows

# Install dependencies
pip install -r requirements.txt

# Generate local .env and security keys
python manage.py bootstrap_local_env

# Database setup
python manage.py migrate

# Start development server
python manage.py runserver

# Visit http://localhost:8000/setup/ to complete the setup wizard
```

The setup wizard will guide you through:
1. **Auto-generate security keys** — `SECRET_KEY` and `AGOMTRADEPRO_ENCRYPTION_KEY` are generated automatically and written to `.env` if not already configured
2. Create an admin account
3. Configure AI provider (optional) — API keys are encrypted at rest with Fernet
4. Configure data sources (optional)

> **No manual key setup required.** `python manage.py bootstrap_local_env` prepares the local `.env`, and the setup wizard will still generate any missing keys when you click “Start”.

### Docker Deployment

```bash
# Local Docker (SQLite + Redis)
copy .env.example .env       # Windows
docker-compose up -d

# VPS production
cd deploy
copy .env.vps.example .env   # edit as needed
docker compose -f ../docker/docker-compose.vps.yml up -d
```

**Security keys are handled automatically in Docker too:**

- `entrypoint.prod.sh` checks `SECRET_KEY` and `AGOMTRADEPRO_ENCRYPTION_KEY` before Django starts
- If not provided, keys are auto-generated and persisted to `/app/data/.env.generated` (inside the data volume)
- web, celery_worker, and celery_beat containers share the same keys; they survive container restarts
- If you explicitly set keys in `deploy/.env`, those take precedence over auto-generated values

### Common First-Run Pitfalls

#### 1. `SECRET_KEY` / `AGOMTRADEPRO_ENCRYPTION_KEY`

**Usually no manual setup needed.** Both the setup wizard and Docker entrypoint auto-generate these keys.

If you prefer to set them manually:

```bash
# Django SECRET_KEY
python -c “from django.core.management.utils import get_random_secret_key; print(get_random_secret_key())”

# Encryption key (Fernet)
python -c “from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())”
```

Then add to `.env`:

```env
SECRET_KEY=your-own-django-secret-key
AGOMTRADEPRO_ENCRYPTION_KEY=your-generated-fernet-key
```

#### 2. `DATABASE_URL`

If you just want a quick local run, you can leave `DATABASE_URL` unset and the project will fall back to local SQLite.

#### 3. `REDIS_URL` / Celery

Redis is not required for a first local run.

- without `REDIS_URL`, Celery falls back to eager/synchronous execution
- only set up Redis when you want the full async worker/beat flow

#### 4. Minimal config for “just get it running”

After running `python manage.py bootstrap_local_env`, you usually do not need to change any keys manually:

```bash
python manage.py bootstrap_local_env
python manage.py migrate
python manage.py runserver
# Visit http://localhost:8000/setup/ → click “Start”
```

If you want to skip the wizard and configure manually, these are the essential variables:

```env
SECRET_KEY=your-own-django-secret-key
AGOMTRADEPRO_ENCRYPTION_KEY=your-generated-fernet-key
DEBUG=True
ALLOWED_HOSTS=localhost,127.0.0.1
```

### Install SDK (optional)

```bash
cd sdk
pip install -e ".[dev]"
```

### Run Tests

```bash
pytest tests/ -v --cov=apps
pytest tests/integration/ -v -m "not live_required and not optional_runtime and not diagnostic"
```

---

## Tech Stack

| Layer | Technology |
|-------|-----------|
| **Backend** | Python 3.11+, Django 5.x, DRF |
| **Database** | SQLite (dev) / PostgreSQL (prod) |
| **Task Queue** | Celery + Redis |
| **Data Processing** | Pandas, NumPy, Statsmodels |
| **Visualization** | Streamlit, Plotly |
| **Frontend** | Django Templates + HTMX |
| **AI Integration** | MCP Server, Python SDK |
| **Testing** | Pytest (5,655 collected tests), Playwright (E2E) |

---

## Project Stats

```
36    business modules (apps/, excluding __pycache__)
326   MCP tools (current local registration snapshot)
525   REST API paths (OpenAPI snapshot)
5,655 automated test items (pytest --collect-only snapshot)
302   documentation files (docs/ directory)
```

---

## Documentation

| Document | Description |
|----------|-------------|
| **[Quick Start Guide](docs/QUICK_START.md)** | From zero to running in production |
| **[System Specification](docs/SYSTEM_SPECIFICATION.md)** | Complete technical + functional spec |
| **[SDK Reference](sdk/README.md)** | Python SDK and MCP server guide |
| **[Architecture Guide](docs/architecture/)** | DDD design, module dependencies |
| **[Doc Index](docs/INDEX.md)** | Full documentation navigation |

---

## Who Is This For?

- **Individual investors** who want systematic discipline instead of emotional trading
- **Quant developers** who need a production-grade macro overlay for their strategies
- **AI/LLM enthusiasts** who want to build investment agents with proper guardrails
- **Finance students** learning macro-driven investment frameworks with real code

---

## Contributing

Contributions are welcome! Please read the [development guidelines](docs/development/outsourcing-work-guidelines.md) before submitting PRs.

```bash
# Format
black . && isort . && ruff check .

# Type check
mypy apps/ --strict

# Test (domain layer coverage ≥ 90%)
pytest tests/ -v --cov=apps
pytest tests/integration/ -v -m "not live_required and not optional_runtime and not diagnostic"
```

---

## License

Apache License 2.0 — see [LICENSE](LICENSE) for details.

---

<div align="center">

**If this project helps you trade with more discipline, consider giving it a ⭐**

*Built with frustration from too many "correct logic, wrong timing" losses.*

</div>
