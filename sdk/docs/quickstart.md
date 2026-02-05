# AgomSAAF SDK Quick Start Guide

This guide will help you get started with the AgomSAAF SDK in minutes.

## Installation

```bash
cd D:/githv/agomSAAF/sdk
pip install -e .
```

## Basic Usage

### 1. Initialize the Client

```python
from agomsaaf import AgomSAAFClient

# Method 1: Using parameters
client = AgomSAAFClient(
    base_url="http://localhost:8000",
    api_token="your_token_here"
)

# Method 2: Using environment variables
import os
os.environ["AGOMSAAF_BASE_URL"] = "http://localhost:8000"
os.environ["AGOMSAAF_API_TOKEN"] = "your_token_here"
client = AgomSAAFClient()

# Method 3: Using config file (~/.agomsaaf/config.json)
client = AgomSAAFClient()
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
| `AGOMSAAF_BASE_URL` | API base URL | `http://localhost:8000` |
| `AGOMSAAF_API_TOKEN` | API authentication token | - |
| `AGOMSAAF_USERNAME` | Username (for password auth) | - |
| `AGOMSAAF_PASSWORD` | Password (for password auth) | - |
| `AGOMSAAF_TIMEOUT` | Request timeout (seconds) | `30` |
| `AGOMSAAF_MAX_RETRIES` | Maximum retry attempts | `3` |

### Config File

Create `~/.agomsaaf/config.json`:

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
from agomsaaf import AgomSAAFClient
from agomsaaf.exceptions import (
    AuthenticationError,
    ValidationError,
    NotFoundError,
    AgomSAAFAPIError
)

client = AgomSAAFClient()

try:
    regime = client.regime.get_current()
except AuthenticationError:
    print("Invalid API token")
except ValidationError as e:
    print(f"Validation error: {e.errors}")
except NotFoundError:
    print("Resource not found")
except AgomSAAFAPIError as e:
    print(f"API error: {e}")
```

## Next Steps

- Read the [API Reference](api_reference.md)
- Check out the [Examples](examples/)
- Learn about [MCP Integration](mcp_guide.md)
