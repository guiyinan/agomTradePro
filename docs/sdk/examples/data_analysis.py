"""
AgomTradePro SDK - Data Analysis with Pandas

This file demonstrates how to use the SDK with pandas for data analysis.
Requires: pip install pandas
"""

from agomtradepro import AgomTradeProClient
from datetime import date
import pandas as pd

# Initialize client
client = AgomTradeProClient(
    base_url="http://localhost:8000",
    api_token="your_token_here"
)

# Example 1: Analyze Regime Distribution
print("=== Regime Distribution Analysis ===")
regime_history = client.regime.history(
    start_date=date(2023, 1, 1),
    end_date=date(2024, 12, 31),
    limit=500
)

# Convert to DataFrame
df = pd.DataFrame([
    {
        "date": r.observed_at,
        "regime": r.dominant_regime,
        "growth": r.growth_level,
        "inflation": r.inflation_level,
    }
    for r in regime_history
])

# Regime distribution
regime_counts = df["regime"].value_counts()
print("Days per Regime:")
for regime, count in regime_counts.items():
    print(f"  {regime}: {count} days ({count/len(df)*100:.1f}%)")
print()

# Monthly regime changes
df["month"] = pd.to_datetime(df["date"]).dt.to_period("M")
monthly_regime = df.groupby("month")["regime"].first()
print("Regime by Month:")
for month, regime in monthly_regime.head(6).items():
    print(f"  {month}: {regime}")
print()

# Example 2: Analyze Macro Data
print("=== Macro Data Analysis ===")
pmi_series = client.data_center.get_macro_series(
    indicator_code="CN_PMI",
    start="2023-01-01",
    end="2024-12-31",
    limit=100,
)

pmi_df = pd.DataFrame(
    [
        {"date": item["observed_at"], "value": item["display_value"]}
        for item in pmi_series.get("data", [])
    ]
)
pmi_df["date"] = pd.to_datetime(pmi_df["date"])
pmi_df = pmi_df.sort_values("date")

# Calculate statistics
print(f"PMI Statistics:")
print(f"  Mean: {pmi_df["value"].mean():.2f}")
print(f"  Std: {pmi_df["value"].std():.2f}")
print(f"  Min: {pmi_df["value"].min():.2f}")
print(f"  Max: {pmi_df["value"].max():.2f}")
print()

# PMI trend
pmi_df["ma_3"] = pmi_df["value"].rolling(3).mean()
pmi_df["ma_6"] = pmi_df["value"].rolling(6).mean()
print("Recent PMI with Moving Averages:")
print(pmi_df[["date", "value", "ma_3", "ma_6"]].tail())
print()

# Example 3: Analyze Signals
print("=== Signal Analysis ===")
signals = client.signal.list(limit=100)
signals_df = pd.DataFrame([
    {
        "id": s.id,
        "asset": s.asset_code,
        "status": s.status,
        "created": s.created_at,
    }
    for s in signals
])

signals_df["created"] = pd.to_datetime(signals_df["created"])
signals_by_status = signals_df["status"].value_counts()
print("Signals by Status:")
for status, count in signals_by_status.items():
    print(f"  {status}: {count}")
print()

# Signals over time
signals_df["date"] = signals_df["created"].dt.date
daily_signals = signals_df.groupby("date").size()
print("Recent Signal Activity:")
for date, count in daily_signals.tail(5).items():
    print(f"  {date}: {count} signals")
print()

# Example 4: Portfolio Analysis
print("=== Portfolio Analysis ===")
portfolios = client.account.get_portfolios()
for portfolio in portfolios:
    print(f"\nPortfolio: {portfolio.name}")
    print(f"Total Value: ${portfolio.total_value:,.2f}")
    print(f"Cash: ${portfolio.cash:,.2f}")

    if portfolio.positions:
        pos_df = pd.DataFrame([
            {
                "asset": p.asset_code,
                "quantity": p.quantity,
                "cost": p.avg_cost,
                "price": p.current_price,
                "value": p.market_value,
                "pnl": p.profit_loss,
                "pnl_%": (p.profit_loss / (p.avg_cost * p.quantity)) * 100
            }
            for p in portfolio.positions
        ])
        pos_df = pos_df.sort_values("value", ascending=False)

        print(f"\nTop 5 Positions:")
        print(pos_df[["asset", "value", "pnl", "pnl_%"]].head(5).to_string(index=False))

        total_pnl = pos_df["pnl"].sum()
        print(f"\nTotal P&L: ${total_pnl:,.2f}")

# Clean up
client.close()
print("\n=== Analysis Complete ===")
