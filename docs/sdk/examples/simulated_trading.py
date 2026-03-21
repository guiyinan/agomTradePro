"""
AgomTradePro SDK - Simulated Trading Example

This file demonstrates simulated trading using the AgomTradePro SDK.
"""

from agomtradepro import AgomTradeProClient
from datetime import date, datetime
import time

# Initialize client
client = AgomTradeProClient(
    base_url="http://localhost:8000",
    api_token="your_token_here"
)

# Example 1: Create a simulated account
print("=== Creating Simulated Account ===")
account = client.simulated_trading.create_account(
    name="Momentum Strategy Account",
    initial_capital=1000000.0,
    start_date=date(2024, 1, 1)
)

print(f"Account Created: ID {account['id']}")
print(f"Name: {account['name']}")
print(f"Initial Capital: ${account['initial_capital']:,.2f}")
print()

account_id = account["id"]

# Example 2: Execute trades
print("=== Executing Trades ===")
trades = [
    ("000001.SH", "buy", 1000, 10.50),
    ("000002.SZ", "buy", 500, 25.30),
    ("600519.SH", "buy", 200, 1800.0),
]

for asset_code, side, quantity, price in trades:
    try:
        result = client.simulated_trading.execute_trade(
            account_id=account_id,
            asset_code=asset_code,
            side=side,
            quantity=quantity,
            price=price
        )
        print(f"{side.upper()} {quantity} {asset_code} @ ${price:.2f}")
        print(f"  -> Order ID: {result['order_id']}")
    except Exception as e:
        print(f"  -> Error: {e}")
print()

# Example 3: Get positions
print("=== Current Positions ===")
positions = client.simulated_trading.get_positions(account_id)
print(f"{'Asset':<12} {'Qty':>10} {'Avg Cost':>10} {'Current':>10} {'Value':>12} {'P&L':>12}")
print("-" * 70)

total_value = 0
total_pnl = 0
for pos in positions:
    value = pos["quantity"] * pos["current_price"]
    pnl = (pos["current_price"] - pos["avg_cost"]) * pos["quantity"]
    total_value += value
    total_pnl += pnl

    print(f"{pos['asset_code']:<12} {pos['quantity']:>10.2f} ${pos['avg_cost']:>8.2f} ${pos['current_price']:>8.2f} ${value:>10,.2f} ${pnl:>10,.2f}")

print("-" * 70)
print(f"{'Total':<12} {'':>10} {'':>10} {'':>10} ${total_value:>10,.2f} ${total_pnl:>10,.2f}")
print()

# Example 4: Get performance
print("=== Account Performance ===")
performance = client.simulated_trading.get_performance(account_id)
print(f"Total Return: {performance['total_return']:.2%}")
print(f"Annual Return: {performance['annual_return']:.2%}")
print(f"Max Drawdown: {performance['max_drawdown']:.2%}")
print(f"Sharpe Ratio: {performance.get('sharpe_ratio', 'N/A')}")
print(f"Win Rate: {performance.get('win_rate', 0):.1%}")
print()

# Example 5: Trade history
print("=== Recent Trades ===")
trade_history = client.simulated_trading.get_trade_history(account_id, limit=10)
print(f"{'Time':<20} {'Asset':<12} {'Side':<6} {'Qty':>8} {'Price':>10}")
print("-" * 60)

for trade in trade_history[:5]:
    trade_time = trade.get("created_at", trade.get("timestamp"))
    if isinstance(trade_time, str):
        trade_time = datetime.fromisoformat(trade_time)
    print(f"{str(trade_time):<20} {trade['asset_code']:<12} {trade['side']:<6} {trade['quantity']:>8.2f} ${trade['price']:>8.2f}")
print()

# Example 6: Close a position
print("=== Closing Position ===")
if positions:
    first_asset = positions[0]["asset_code"]
    result = client.simulated_trading.close_position(
        account_id=account_id,
        asset_code=first_asset
    )
    print(f"Closed position: {first_asset}")
    print(f"Order ID: {result['order_id']}")
    print()

    # Check updated positions
    updated_positions = client.simulated_trading.get_positions(account_id)
    print(f"Remaining positions: {len(updated_positions)}")
print()

# Example 7: Reset account (optional - comment out to preserve data)
# print("=== Resetting Account ===")
# result = client.simulated_trading.reset_account(account_id)
# print(f"Account reset: {account_id}")

# Example 8: List all simulated accounts
print("=== All Simulated Accounts ===")
all_accounts = client.simulated_trading.list_accounts()
for acc in all_accounts:
    print(f"ID {acc['id']}: {acc['name']} - ${acc.get('total_value', 0):,.2f}")
print()

# Clean up
client.close()
print("=== Trading Session Complete ===")
