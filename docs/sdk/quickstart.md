# AgomTradePro SDK Quick Start Guide

This guide will help you get started with the AgomTradePro SDK in minutes.

## Installation

```bash
cd sdk
pip install -e .
```

## Authentication

The backend expects DRF Token auth:

- `Authorization: Token <token>`

Generate token for an existing user:

```bash
cd .
python -c "import os; os.environ.setdefault('DJANGO_SETTINGS_MODULE','core.settings.development'); import django; django.setup(); from django.contrib.auth.models import User; from apps.account.infrastructure.models import UserAccessTokenModel; u=User.objects.get(username='admin'); t,key=UserAccessTokenModel.create_token(user=u, name='sdk-quickstart'); print(key)"
```

### Environment Variables by Platform

#### Windows PowerShell

```powershell
$env:AGOMTRADEPRO_BASE_URL="http://127.0.0.1:8000"
$env:AGOMTRADEPRO_API_TOKEN="your_token_here"
$env:NO_PROXY="127.0.0.1,localhost"
$env:no_proxy="127.0.0.1,localhost"
```

#### Linux/macOS (bash)

```bash
export AGOMTRADEPRO_BASE_URL="http://127.0.0.1:8000"
export AGOMTRADEPRO_API_TOKEN="your_token_here"
export NO_PROXY="127.0.0.1,localhost"
export no_proxy="127.0.0.1,localhost"
```

## Basic Usage

### 1. Initialize the Client

```python
from agomtradepro import AgomTradeProClient

# Method 1: Using parameters
client = AgomTradeProClient(
    base_url="http://127.0.0.1:8000",
    api_token="your_token_here"
)

# Method 2: Using environment variables
import os
os.environ["AGOMTRADEPRO_BASE_URL"] = "http://127.0.0.1:8000"
os.environ["AGOMTRADEPRO_API_TOKEN"] = "your_token_here"
client = AgomTradeProClient()

# Method 3: Using config file (~/.agomtradepro/config.json)
client = AgomTradeProClient()
```

If your machine has proxy variables configured, bypass localhost:

```python
import os
os.environ["NO_PROXY"] = "127.0.0.1,localhost"
os.environ["no_proxy"] = "127.0.0.1,localhost"
```

### 2. Get Current Macro Regime

```python
regime = client.regime.get_current()
print(f"Current Regime: {regime.dominant_regime}")
print(f"Growth: {regime.growth_level}, Inflation: {regime.inflation_level}")
```

### 3. Check Investment Signal Eligibility

```python
eligibility = client.signal.check_eligibility(
    asset_code="000001.SH",
    logic_desc="PMI rising, economic recovery",
    target_regime="Recovery"
)

if eligibility["is_eligible"]:
    print("Signal is eligible!")
else:
    print(f"Signal not eligible: {eligibility['rejection_reason']}")
```

### 4. Create Investment Signal

```python
signal = client.signal.create(
    asset_code="000001.SH",
    logic_desc="PMI rising, economic recovery",
    invalidation_logic="PMI falls below 50",
    invalidation_threshold=49.5
)
print(f"Signal created: {signal.id}")
```

### 5. Run Backtest

```python
from datetime import date

result = client.backtest.run(
    strategy_name="momentum",
    start_date=date(2023, 1, 1),
    end_date=date(2024, 12, 31),
    initial_capital=1000000.0
)
print(f"Annual Return: {result.annual_return:.2%}")
print(f"Max Drawdown: {result.max_drawdown:.2%}")
```

### 6. Bind Portfolio Strategy and Submit Decision

```python
# 1) Bind strategy to a portfolio
bind_result = client.strategy.bind_portfolio_strategy(
    portfolio_id=1,
    strategy_id=12,
)
print(bind_result["message"])

# 2) Update Alpha candidate status to ACTIONABLE
client.alpha_trigger.update_candidate_status(
    candidate_id="cand_xxx",
    status="ACTIONABLE",
)

# 3) Submit candidate into Decision Rhythm queue
decision = client.decision_rhythm.submit({
    "asset_code": "000001.SH",
    "asset_class": "a_share",
    "direction": "BUY",
    "priority": "high",
    "trigger_id": "cand_xxx",
    "reason": "from actionable candidate",
    "expected_confidence": 0.78,
    "quota_period": "weekly"
})
print(decision.get("success", False))
```

### 7. Bridge System Recommendation Into User Decision

```python
# 1) Refresh unified recommendations for one stock
refresh = client.decision_workflow.refresh_recommendations(
    account_id="default",
    security_codes=["600519.SH"],
)
print(refresh["success"])

# 2) Load the recommendation back from decision workspace
recommendations = client.decision_workflow.list_recommendations(
    account_id="default",
    security_code="600519.SH",
)
recommendation = recommendations["data"]["recommendations"][0]
print(recommendation["security_name"], recommendation["security_code"])

# 3) Mark user's choice
client.decision_workflow.apply_recommendation_action(
    recommendation_id=recommendation["recommendation_id"],
    action="watch",
    account_id="default",
    note="from dashboard alpha",
)
```

### 8. Read Pulse And Funnel Context

```python
pulse = client.pulse.get_current()
print(pulse["composite_score"], pulse["regime_strength"])

context = client.decision_workflow.get_funnel_context(
    trade_id="trade-001",
    backtest_id=123,
)
print(context["step1_environment"]["regime_name"])
print(context["step6_audit"]["attribution_method"])
```

### 9. Read Regime Navigator And Top-Down Action

```python
navigator = client.pulse.get_navigator()
print(navigator["regime_name"], navigator["movement"]["direction"])

action = client.pulse.get_action_recommendation()
print(action["asset_weights"])
print(action["risk_budget_pct"])
```

Notes:

- `client.decision_workflow.get_funnel_context()` supports both `trade_id` and `backtest_id`.
- `client.decision_workflow.list_recommendations()` returns the same unified recommendation payload as the Decision Workspace API, including `security_name`.
- SDK 当前内建的是 `precheck / list_recommendations / refresh_recommendations / apply_recommendation_action / get_funnel_context`；交易计划生成与审批仍使用 HTTP Decision Workspace API。
- `client.pulse.*` reads canonical JSON APIs directly; it does not depend on dashboard HTML rendering.

## Module Overview

| Module | Description |
|--------|-------------|
| `client.regime` | Macro regime determination |
| `client.signal` | Investment signal management |
| `client.macro` | Macro economic data |
| `client.policy` | Policy event management |
| `client.backtest` | Backtesting engine |
| `client.account` | Account and portfolio management |
| `client.simulated_trading` | Simulated trading accounts |
| `client.equity` | Stock analysis |
| `client.fund` | Fund analysis |
| `client.sector` | Sector analysis |
| `client.strategy` | Strategy management |
| `client.realtime` | Real-time price monitoring |

## Configuration

### Environment Variables

| Variable | Description | Default |
|----------|-------------|---------|
| `AGOMTRADEPRO_BASE_URL` | API base URL | `http://127.0.0.1:8000` |
| `AGOMTRADEPRO_API_TOKEN` | API authentication token | - |
| `AGOMTRADEPRO_USERNAME` | Username (for password auth) | - |
| `AGOMTRADEPRO_PASSWORD` | Password (for password auth) | - |
| `AGOMTRADEPRO_TIMEOUT` | Request timeout (seconds) | `30` |
| `AGOMTRADEPRO_MAX_RETRIES` | Maximum retry attempts | `3` |

### Config File

Create `~/.agomtradepro/config.json`:

```json
{
  "base_url": "http://127.0.0.1:8000",
  "api_token": "your_token_here",
  "timeout": 30,
  "max_retries": 3
}
```

## Error Handling

```python
from agomtradepro import AgomTradeProClient
from agomtradepro.exceptions import (
    AuthenticationError,
    ValidationError,
    NotFoundError,
    AgomTradeProAPIError
)

client = AgomTradeProClient()

try:
    regime = client.regime.get_current()
except AuthenticationError:
    print("Invalid API token")
except ValidationError as e:
    print(f"Validation error: {e.errors}")
except NotFoundError:
    print("Resource not found")
except AgomTradeProAPIError as e:
    print(f"API error: {e}")
```

## Next Steps

- Read the [API Reference](api_reference.md)
- Check out the [Examples](examples/)
- Learn about [MCP Integration](../mcp/mcp_guide.md)
