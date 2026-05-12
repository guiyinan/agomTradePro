"""
AgomTradePro SDK - Real-time Monitoring and Strategy Example

This file demonstrates real-time price monitoring and strategy management.
"""


from agomtradepro import AgomTradeProClient

# Initialize client
client = AgomTradeProClient(
    base_url="http://localhost:8000",
    api_token="your_token_here"
)

# =============================================================================
# Real-time Price Monitoring
# =============================================================================

print("=== Real-time Price Monitoring ===\n")

# Example 1: Get real-time price for a single stock
print("1. Real-time Price")
try:
    price = client.realtime.get_price("000001.SH")
    print(f"   {price['asset_code']} ({price.get('name', 'N/A')})")
    print(f"   Current: ${price['current_price']:.2f}")
    print(f"   Change: {price.get('change', 0):>+8.2f} ({price.get('change_percent', 0):>+6.2f}%)")
    print(f"   Volume: {price.get('volume', 0):,.0f}")
    print(f"   Time: {price.get('timestamp', 'N/A')}")
except Exception as e:
    print(f"   Error: {e}")
print()

# Example 2: Get multiple prices
print("2. Multiple Stock Prices")
watch_list = ["000001.SH", "000002.SZ", "600519.SH", "600036.SH"]
try:
    prices = client.realtime.get_multiple_prices(watch_list)
    print(f"   {'Code':<12} {'Price':>10} {'Change':>10} {'% Change':>10}")
    print("   " + "-" * 42)
    for code, data in prices.items():
        change = data.get('change', 0)
        pct = data.get('change_percent', 0)
        print(f"   {code:<12} ${data.get('current_price', 0):>8.2f} {change:>+8.2f} {pct:>+8.2f}%")
except Exception as e:
    print(f"   Error: {e}")
print()

# Example 3: Market summary
print("3. Market Summary")
try:
    summary = client.realtime.get_market_summary()
    print(f"   Shanghai Index: {summary.get('sh_index', 0):.2f}")
    print(f"   Shenzhen Index: {summary.get('sz_index', 0):.2f}")
    print(f"   ChiNext Index: {summary.get('cyb_index', 0):.2f}")
    print("   ")
    print(f"   Up: {summary.get('up_count', 0)}")
    print(f"   Down: {summary.get('down_count', 0)}")
    print(f"   Unchanged: {summary.get('flat_count', 0)}")
    print(f"   Limit Up: {summary.get('limit_up_count', 0)}")
    print(f"   Limit Down: {summary.get('limit_down_count', 0)}")
    print(f"   Total Volume: {summary.get('total_volume', 0):,.0f}")
    print(f"   Total Value: {summary.get('total_value', 0):,.0f}")
except Exception as e:
    print(f"   Error: {e}")
print()

# Example 4: Top gainers and losers
print("4. Top Movers")
try:
    gainers = client.realtime.get_top_movers(direction="up", limit=5)
    print("   Top Gainers:")
    for i, stock in enumerate(gainers, 1):
        print(f"   {i}. {stock['code']} ({stock.get('name', 'N/A')}) "
              f"{stock.get('change_percent', 0):>+6.2f}%")

    losers = client.realtime.get_top_movers(direction="down", limit=5)
    print("\n   Top Losers:")
    for i, stock in enumerate(losers, 1):
        print(f"   {i}. {stock['code']} ({stock.get('name', 'N/A')}) "
              f"{stock.get('change_percent', 0):>+6.2f}%")
except Exception as e:
    print(f"   Error: {e}")
print()

# Example 5: Sector performance
print("5. Sector Performance")
try:
    sectors = client.realtime.get_sector_performance()
    print(f"   {'Sector':<20} {'Change':<10} {'Volume':>15}")
    print("   " + "-" * 45)
    for sector in sectors[:8]:
        change = sector.get('change_percent', 0) * 100
        volume = sector.get('volume', 0)
        print(f"   {sector['name']:<20} {change:>+6.2f}% {volume:>13,.0f}")
except Exception as e:
    print(f"   Error: {e}")
print()

# =============================================================================
# Strategy Management
# =============================================================================

print("\n=== Strategy Management ===\n")

# Example 6: List strategies
print("6. Available Strategies")
try:
    strategies = client.strategy.list_strategies(status="active")
    print(f"   {'ID':<6} {'Name':<25} {'Type':<15} {'Status':<10}")
    print("   " + "-" * 56)
    for s in strategies:
        print(f"   {s['id']:<6} {s['name']:<25} {s['type']:<15} {s['status']:<10}")
except Exception as e:
    print(f"   Error: {e}")
print()

# Example 7: Create a new strategy
print("7. Create Strategy")
try:
    new_strategy = client.strategy.create_strategy(
        name="RSI Reversal",
        strategy_type="mean_reversion",
        description="Mean reversion based on RSI indicator",
        params={"rsi_period": 14, "oversold": 30, "overbought": 70}
    )
    print(f"   Strategy Created: ID {new_strategy['id']}")
    print(f"   Name: {new_strategy['name']}")
    print(f"   Type: {new_strategy['type']}")
    print(f"   Parameters: {new_strategy.get('params', {})}")
    strategy_id = new_strategy['id']
except Exception as e:
    print(f"   Error: {e}")
    strategy_id = None
print()

# Example 8: Execute strategy
if strategy_id:
    print("8. Execute Strategy")
    try:
        result = client.strategy.execute_strategy(strategy_id)
        print(f"   Execution ID: {result.get('execution_id', 'N/A')}")
        print(f"   Signals Created: {result.get('signals_created', 0)}")
        print(f"   Status: {result.get('status', 'unknown')}")
    except Exception as e:
        print(f"   Error: {e}")
    print()

    # Example 9: Get strategy signals
    print("9. Strategy Signals")
    try:
        signals = client.strategy.get_strategy_signals(strategy_id, limit=5)
        print(f"   {'ID':<6} {'Asset':<12} {'Type':<8} {'Created':<20}")
        print("   " + "-" * 46)
        for s in signals:
            created = s.get('created_at', 'N/A')
            if isinstance(created, str):
                created = created[:19]
            print(f"   {s['id']:<6} {s['asset_code']:<12} {s.get('signal_type', 'N/A'):<8} {created:<20}")
    except Exception as e:
        print(f"   Error: {e}")
    print()

    # Example 10: Get strategy performance
    print("10. Strategy Performance")
    try:
        perf = client.strategy.get_strategy_performance(strategy_id)
        print(f"   Total Return: {perf.get('total_return', 0):.2%}")
        print(f"   Annual Return: {perf.get('annual_return', 0):.2%}")
        print(f"   Max Drawdown: {perf.get('max_drawdown', 0):.2%}")
        print(f"   Win Rate: {perf.get('win_rate', 0):.1%}")
        print(f"   Total Trades: {perf.get('total_trades', 0)}")
    except Exception as e:
        print(f"   Error: {e}")
    print()

# =============================================================================
# Price Alerts
# =============================================================================

print("\n=== Price Alerts ===\n")

# Example 11: List active alerts
print("11. Active Price Alerts")
try:
    alerts = client.realtime.list_alerts(status="active", limit=10)
    if alerts:
        print(f"   {'ID':<6} {'Asset':<12} {'Condition':<15} {'Threshold':>10}")
        print("   " + "-" * 43)
        for alert in alerts[:5]:
            print(f"   {alert['id']:<6} {alert['asset_code']:<12} "
                  f"{alert['condition']:<15} ${alert['threshold']:>8.2f}")
    else:
        print("   No active alerts")
except Exception as e:
    print(f"   Error: {e}")
print()

# Example 12: Create price alert
print("12. Create Price Alert")
try:
    alert = client.realtime.create_alert(
        asset_code="000001.SH",
        condition="above",
        threshold=12.00,
        message="Price breakout above 12.00"
    )
    print(f"   Alert Created: ID {alert['id']}")
    print(f"   Asset: {alert['asset_code']}")
    print(f"   Condition: {alert['condition']}")
    print(f"   Threshold: ${alert['threshold']:.2f}")
    print(f"   Message: {alert.get('message', 'N/A')}")

    # Clean up - delete the example alert
    client.realtime.delete_alert(alert['id'])
    print("   (Alert deleted for cleanup)")
except Exception as e:
    print(f"   Error: {e}")
print()

# Clean up
client.close()
print("\n=== Monitoring Complete ===")
