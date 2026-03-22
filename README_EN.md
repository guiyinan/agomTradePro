<div align="center">

**[English](README_EN.md) | [中文](README.md)**

# AgomTradePro

### Stop Trading Against the Macro. Start Trading With Discipline.

**A macro-first investment admission system that prevents you from betting in the wrong economic environment — even when your logic feels right.**

[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/downloads/)
[![Django 5.x](https://img.shields.io/badge/django-5.x-green.svg)](https://www.djangoproject.com/)
[![Tests](https://img.shields.io/badge/tests-1%2C600+-brightgreen.svg)](#testing)
[![Modules](https://img.shields.io/badge/business_modules-32-purple.svg)](#architecture)
[![MCP Tools](https://img.shields.io/badge/MCP_tools-65+-orange.svg)](#ai-native-integration)
[![License](https://img.shields.io/badge/license-Apache%202.0-blue.svg)](LICENSE)

[Quick Start](#quick-start) · [Why This Exists](#why-this-exists) · [Features](#features) · [AI Integration](#ai-native-integration) · [Screenshots](#screenshots) · [Docs](docs/INDEX.md)

</div>

---

## Why This Exists

Most retail investors lose money not because their stock picks are bad, but because they trade at the wrong time.

- You buy quality stocks — **during stagflation**
- You follow a solid strategy — **while policy is tightening**
- You see a clear signal — **but the macro regime is shifting under your feet**

**The result?** Correct logic, wrong world. Loss.

AgomTradePro is built on one principle:

> **"Don't bet in the wrong macroeconomic world, even with correct logic."**

It acts as a **macro gatekeeper** — filtering every investment decision through regime analysis (growth × inflation quadrants) and policy state before you can act. It doesn't predict prices. It prevents mistakes.

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

- **Python SDK** — full programmatic access to all 32 modules
- **MCP Server (65+ tools)** — plug directly into Claude, Cursor, or any MCP-compatible AI
- **Terminal CLI** — AI-interactive command interface
- **Agent Runtime** — task orchestration with proposal → approval → execution lifecycle

Your AI agent can check the macro regime, evaluate signals, and propose trades — but still needs human approval to execute. **AI speed, human judgment.**

---

## Screenshots

<details>
<summary><b>Investment Command Center (Dashboard)</b></summary>

![Dashboard](output/playwright/dashboard.png)

*Unified view: accounts, holdings, regime status, active signals, and performance at a glance.*

</details>

<details>
<summary><b>Regime Analysis</b></summary>

![Regime Dashboard](output/playwright/regime_dashboard.png)

*Four-quadrant regime visualization with momentum trends, confidence metrics, and historical tracking.*

</details>

<details>
<summary><b>Macro Data Intelligence</b></summary>

![Macro Data](output/playwright/macro_data.png)

*Real-time macro indicator tracking with multi-source sync, AI-powered chat for data exploration.*

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

Strict **Domain-Driven Design** with four-layer enforcement:

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

**Why this matters:** Domain logic is framework-independent, fully testable, and portable. Financial rules live where they belong — in pure Python with zero external dependencies.

**32 business modules**, each with complete four-layer implementation. No shortcuts.

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

**65+ MCP tools** across all modules — regime, signals, macro data, backtesting, trading, portfolio management, and more.

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

# Virtual environment
python -m venv agomtradepro
source agomtradepro/bin/activate  # Linux/Mac
# or: agomtradepro\Scripts\activate  # Windows

# Install dependencies
pip install -r requirements.txt

# Database setup
python manage.py migrate
python manage.py createsuperuser

# Start development server
python manage.py runserver
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
