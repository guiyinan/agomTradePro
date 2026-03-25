<div align="center">

**[English](README_EN.md) | [中文](README.md)**

# AgomTradePro

### Stop Trading Against the Macro. Start Trading With Discipline.

**An AI-native personal research foundation that gives AI a data foundation and decision framework, bringing macro judgment, strategy discipline, agent capabilities, and execution workflows into one system.**

[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/downloads/)
[![Django 5.x](https://img.shields.io/badge/django-5.x-green.svg)](https://www.djangoproject.com/)
[![Tests](https://img.shields.io/badge/tests-1%2C600+-brightgreen.svg)](#testing)
[![Modules](https://img.shields.io/badge/business_modules-34-purple.svg)](#architecture)
[![MCP Tools](https://img.shields.io/badge/MCP_tools-65+-orange.svg)](#ai-native-integration)
[![Status](https://img.shields.io/badge/status-active_development-yellow.svg)](#project-status)
[![License](https://img.shields.io/badge/license-Apache%202.0-blue.svg)](LICENSE)

[Quick Start](#quick-start) · [Why This Exists](#why-this-exists) · [Why Fork / Star](#why-fork--star) · [Architecture](#architecture) · [AI Integration](#ai-native-integration) · [Screenshots](#screenshots) · [Docs](docs/INDEX.md)

</div>

---

## What's New

> This section is maintained day by day and should focus on user-visible changes from the last 1-7 days.

### 2026-03-24

- The full Regime Navigator + Pulse redesign rollout is now closed out across Dashboard, Decision Workspace, and the Regime page
- Dashboard navigation has been tightened, and `beta_gate`, `alpha_trigger`, and `decision_rhythm` are no longer exposed as standalone primary homepage entries
- The Regime page now includes a historical `Regime + Pulse + Action` layered time-series chart
- The Dashboard now supports optional browser-level Pulse transition notifications
- SDK, MCP, and docs are aligned around `decision_workflow.get_funnel_context(trade_id, backtest_id)` and `client.pulse.*`

### Maintenance Rule

- Only record changes that matter to users, integrators, or fork maintainers
- Keep the same-day updates under the same date instead of creating noise
- Anything important beyond one week should be moved into `CHANGELOG.md`

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

For now, the **simplest installation path** is:

1. Clone this repository locally
2. Let **OpenClaw** or **Claude Code** read the repo and handle dependency install, environment setup, migrations, and startup for you
3. If you prefer a manual path, continue with `deploy/README_DEPLOY.md` and the docs under `docs/deployment/`

### Notes

- The public install flow is still being simplified, so the easiest option today is to let OpenClaw or Claude Code install it for you
- A more direct **Docker package / deployment bundle** will be provided later by the author

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
- **It is not a one-off script pile**: 34 business modules with explicit DDD boundaries make it suitable for long-term extension
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
- **MCP Server (65+ tools)** — plug directly into Claude, Cursor, or any MCP-compatible AI
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

### 3. AI Architecture

- **MCP Server** exposes system capabilities directly to Claude, Cursor, Codex, and other agentic tools
- **Terminal CLI** provides an operations-oriented AI interface instead of a generic chat widget
- **Capability Catalog** manages tool routing, schema, switches, and discoverability
- **Agent Runtime** turns proposal → pre-check → approval → execution into a real system path

This is one of the strongest reasons to fork the project: the AI layer is native to the product, not stapled onto the side.

### 4. Current State

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

**65+ MCP tools** do not just expose a few query endpoints. They span macro, policy, signals, backtesting, accounts, portfolios, trading flows, AI capability routing, terminal commands, runtime orchestration, and system-level operations.

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

## Quick Start

### Prerequisites

- Python 3.11+
- Redis (for Celery task queue)

### Setup

```bash
# Clone
git clone https://github.com/guiyinan/agomTradePro.git
cd agomTradePro

# Copy env template
copy .env.example .env   # Windows
# cp .env.example .env   # Linux/Mac

# Virtual environment
python -m venv agomtradepro
source agomtradepro/bin/activate  # Linux/Mac
# or: agomtradepro\Scripts\activate  # Windows

# Install dependencies
pip install -r requirements.txt

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

> **No manual key setup required.** When you click “Start” on the welcome page, the wizard checks for missing keys and generates them automatically. If you prefer to set them manually in `.env` beforehand, the wizard will skip already-configured keys.

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

`.env.example` includes a PostgreSQL example connection string.
If you just want a quick local run, you can **remove or leave `DATABASE_URL` empty**, and the project will fall back to local SQLite.

#### 3. `REDIS_URL` / Celery

Redis is not required for a first local run.

- without `REDIS_URL`, Celery falls back to eager/synchronous execution
- only set up Redis when you want the full async worker/beat flow

#### 4. Minimal config for “just get it running”

After copying `.env.example`, you don't even need to change any keys — the setup wizard handles it:

```bash
copy .env.example .env
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
| **Testing** | Pytest (1,600+ tests), Playwright (E2E) |

---

## Project Stats

```
32   business modules (complete DDD four-layer each)
65+  MCP tools for AI agents
100+ REST API endpoints
1,600+ automated tests
230+ documentation files
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
```

---

## License

Apache License 2.0 — see [LICENSE](LICENSE) for details.

---

<div align="center">

**If this project helps you trade with more discipline, consider giving it a ⭐**

*Built with frustration from too many "correct logic, wrong timing" losses.*

</div>
