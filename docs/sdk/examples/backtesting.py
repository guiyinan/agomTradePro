"""
AgomTradePro SDK - Backtesting Examples

This file demonstrates backtesting and advanced usage of the AgomTradePro SDK.
"""

from agomtradepro import AgomTradeProClient
from datetime import date, timedelta
import time

# Initialize client
client = AgomTradeProClient(
    base_url="http://localhost:8000",
    api_token="your_token_here"
)

# Example 1: Run a simple backtest
print("=== Running Momentum Strategy Backtest ===")
result = client.backtest.run(
    strategy_name="momentum",
    start_date=date(2023, 1, 1),
    end_date=date(2024, 12, 31),
    initial_capital=1000000.0
)

print(f"Backtest ID: {result.id}")
print(f"Status: {result.status}")
print(f"Total Return: {result.total_return:.2%}")
print(f"Annual Return: {result.annual_return:.2%}")
print(f"Max Drawdown: {result.max_drawdown:.2%}")
if result.sharpe_ratio:
    print(f"Sharpe Ratio: {result.sharpe_ratio:.2f}")
print()

# Wait for backtest to complete if needed
if result.status == "running":
    print("Waiting for backtest to complete...")
    time.sleep(2)
    result = client.backtest.get_result(result.id)
    print(f"Final status: {result.status}")

# Example 2: Get equity curve
print("=== Equity Curve ===")
equity_curve = client.backtest.get_equity_curve(result.id)
for point in equity_curve[:5]:
    print(f"{point['date']}: ${point['value']:,.2f}")
print(f"... ({len(equity_curve)} total points)")
print()

# Example 3: Compare multiple strategies
print("=== Strategy Comparison ===")
strategies = ["momentum", "mean_reversion", "buy_hold"]
results = {}

for strategy in strategies:
    try:
        result = client.backtest.run(
            strategy_name=strategy,
            start_date=date(2023, 1, 1),
            end_date=date(2024, 12, 31),
            initial_capital=1000000.0
        )
        results[strategy] = result
    except Exception as e:
        print(f"Error running {strategy}: {e}")

print(f"{'Strategy':<20} {'Return':<12} {'Drawdown':<12}")
print("-" * 44)
for name, result in results.items():
    print(f"{name:<20} {result.total_return:>10.2%} {result.max_drawdown:>10.2%}")
print()

# Example 4: List all backtests
print("=== All Backtests ===")
all_backtests = client.backtest.list(limit=10)
for bt in all_backtests:
    print(f"ID {bt.id}: status={bt.status}, annual_return={bt.annual_return:.2%}")
print()

# Example 5: Get backtest result details
if results:
    first_result = list(results.values())[0]
    print("=== Detailed Backtest Result ===")
    print(f"Strategy: {first_result.strategy_name}")
    print(f"Period: {first_result.start_date} to {first_result.end_date}")
    print(f"Initial Capital: ${first_result.initial_capital:,.2f}")
    print(f"Final Value: ${first_result.final_value:,.2f}")
    print(f"Total Return: {first_result.total_return:.2%}")
    print(f"Annual Return: {first_result.annual_return:.2%}")
    print(f"Max Drawdown: {first_result.max_drawdown:.2%}")
    print(f"Win Rate: {first_result.win_rate:.2%}")
    if first_result.sharpe_ratio:
        print(f"Sharpe Ratio: {first_result.sharpe_ratio:.2f}")
    if first_result.sortino_ratio:
        print(f"Sortino Ratio: {first_result.sortino_ratio:.2f}")
print()

# Clean up
client.close()
