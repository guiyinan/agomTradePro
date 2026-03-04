"""
AgomSAAF SDK - Basic Usage Examples

This file demonstrates basic usage of the AgomSAAF SDK.
"""

from agomsaaf import AgomSAAFClient
from datetime import date

# Initialize client
client = AgomSAAFClient(
    base_url="http://localhost:8000",
    api_token="your_token_here"
)

# Example 1: Get current regime
print("=== Current Regime ===")
regime = client.regime.get_current()
print(f"Regime: {regime.dominant_regime}")
print(f"Growth: {regime.growth_level}, Inflation: {regime.inflation_level}")
print()

# Example 2: Get regime history
print("=== Regime History ===")
history = client.regime.history(
    start_date=date(2024, 1, 1),
    end_date=date(2024, 1, 31),
    limit=10
)
for state in history[:5]:
    print(f"{state.observed_at}: {state.dominant_regime}")
print()

# Example 3: Check signal eligibility
print("=== Signal Eligibility ===")
eligibility = client.signal.check_eligibility(
    asset_code="000001.SH",
    logic_desc="PMI rising, economic recovery"
)
print(f"Eligible: {eligibility['is_eligible']}")
print(f"Regime match: {eligibility['regime_match']}")
print(f"Policy match: {eligibility['policy_match']}")
print()

# Example 4: List approved signals
print("=== Approved Signals ===")
signals = client.signal.list(status="approved", limit=5)
for signal in signals:
    print(f"{signal.asset_code}: {signal.logic_desc}")
print()

# Example 5: Get macro indicators
print("=== Macro Indicators ===")
indicators = client.macro.list_indicators(limit=5)
for indicator in indicators:
    print(f"{indicator.code}: {indicator.name}")
print()

# Example 6: Get latest PMI data
print("=== Latest PMI ===")
latest_pmi = client.macro.get_latest_data("PMI")
if latest_pmi:
    print(f"Date: {latest_pmi.date}")
    print(f"Value: {latest_pmi.value} {latest_pmi.unit}")
print()

# Example 7: Get policy status
print("=== Policy Status ===")
policy = client.policy.get_status()
print(f"Current gear: {policy.current_gear}")
print(f"Recent events: {len(policy.recent_events)}")
print()

# Example 8: List portfolios
print("=== Portfolios ===")
portfolios = client.account.get_portfolios()
for portfolio in portfolios:
    print(f"{portfolio.name}: ${portfolio.total_value:,.2f}")
print()

# Clean up
client.close()
