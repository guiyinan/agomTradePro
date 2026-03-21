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
python -c "import os; os.environ.setdefault('DJANGO_SETTINGS_MODULE','core.settings.development'); import django; django.setup(); from django.contrib.auth.models import User; from rest_framework.authtoken.models import Token; u=User.objects.get(username='admin'); t,_=Token.objects.get_or_create(user=u); print(t.key)"
```

### Environment Variables by Platform

#### Windows PowerShell

```powershell
$env:AGOMTRADEPRO_BASE_URL="http://localhost:8000"
$env:AGOMTRADEPRO_API_TOKEN="your_token_here"
$env:NO_PROXY="127.0.0.1,localhost"
$env:no_proxy="127.0.0.1,localhost"
```

#### Linux/macOS (bash)

```bash
export AGOMTRADEPRO_BASE_URL="http://localhost:8000"
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
    base_url="http://localhost:8000",
    api_token="your_token_here"
)

# Method 2: Using environment variables
import os
os.environ["AGOMTRADEPRO_BASE_URL"] = "http://localhost:8000"
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
| `AGOMTRADEPRO_BASE_URL` | API base URL | `http://localhost:8000` |
| `AGOMTRADEPRO_API_TOKEN` | API authentication token | - |
| `AGOMTRADEPRO_USERNAME` | Username (for password auth) | - |
| `AGOMTRADEPRO_PASSWORD` | Password (for password auth) | - |
| `AGOMTRADEPRO_TIMEOUT` | Request timeout (seconds) | `30` |
| `AGOMTRADEPRO_MAX_RETRIES` | Maximum retry attempts | `3` |

### Config File

Create `~/.agomtradepro/config.json`:

```json
{
  "base_url": "http://localhost:8000",
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
