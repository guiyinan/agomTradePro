"""
AgomTradePro SDK - Equity and Fund Analysis Example

This file demonstrates stock and fund analysis using the AgomTradePro SDK.
"""

from datetime import date

from agomtradepro import AgomTradeProClient

# Initialize client
client = AgomTradeProClient(base_url="http://localhost:8000", api_token="your_token_here")

# =============================================================================
# Equity Analysis
# =============================================================================

print("=== Equity Analysis ===\n")

# Example 1: Get stock score
print("1. Stock Score Analysis")
stock_code = "000001.SZ"
try:
    score = client.equity.get_stock_score(stock_code)
    print(f"   {stock_code} ({score.get('name', 'N/A')})")
    print(f"   Overall Score: {score.get('overall_score', 0)}/100")
    print(f"   Valuation Score: {score.get('valuation_score', 0)}/100")
    print(f"   Growth Score: {score.get('growth_score', 0)}/100")
    print(f"   Quality Score: {score.get('quality_score', 0)}/100")
except Exception as e:
    print(f"   Error: {e}")
print()

# Example 2: List stocks by sector
print("2. Top Stocks in Banking Sector")
try:
    stocks = client.equity.list_stocks(sector="银行", min_score=60, limit=10)
    print(f"   {'Code':<12} {'Name':<20} {'Score':<8}")
    print("   " + "-" * 40)
    for stock in stocks[:5]:
        print(f"   {stock['code']:<12} {stock['name']:<20} {stock.get('score', 0):>6}")
except Exception as e:
    print(f"   Error: {e}")
print()

# Example 3: Get stock recommendations based on regime
print("3. Stock Recommendations for Current Regime")
try:
    regime = client.regime.get_current()
    print(f"   Current Regime: {regime.dominant_regime}")

    recommendations = client.equity.get_recommendations(regime=regime.dominant_regime, limit=5)
    print(f"   {'Code':<12} {'Name':<20} {'Reason'}")
    print("   " + "-" * 60)
    for rec in recommendations:
        print(f"   {rec['code']:<12} {rec['name']:<20} {rec.get('reason', 'N/A')}")
except Exception as e:
    print(f"   Error: {e}")
print()

# Example 4: Get stock financials
print("4. Stock Financial Data")
try:
    financials = client.equity.get_financials(stock_code, report_type="annual", limit=3)
    print(f"   {stock_code} Annual Reports")
    for f in financials:
        print(
            f"   {f['report_date']}: Revenue {f.get('revenue', 0):,.0f}, "
            f"Net Income {f.get('net_income', 0):,.0f}"
        )
except Exception as e:
    print(f"   Error: {e}")
print()

# Example 5: Get stock valuation
print("5. Stock Valuation")
try:
    valuation = client.equity.get_valuation(stock_code)
    print(f"   {stock_code} Valuation Metrics")
    print(f"   PE Ratio: {valuation.get('pe', 'N/A')}")
    print(f"   PB Ratio: {valuation.get('pb', 'N/A')}")
    print(f"   PS Ratio: {valuation.get('ps', 'N/A')}")
    print(f"   Dividend Yield: {valuation.get('dividend_yield', 0):.2%}")
except Exception as e:
    print(f"   Error: {e}")
print()

# =============================================================================
# Fund Analysis
# =============================================================================

print("\n=== Fund Analysis ===\n")

# Example 6: Rank funds under current regime
print("6. Ranked Funds for Current Regime")
fund_code = "000001"
try:
    regime = client.regime.get_current()
    ranked = client.fund.rank_funds(regime=regime.dominant_regime, max_count=5)
    print(f"   Current Regime: {regime.dominant_regime}")
    print(f"   {'Rank':<6} {'Code':<10} {'Name':<24} {'Score':<8}")
    print("   " + "-" * 56)
    for item in ranked:
        print(
            f"   {item['rank']:<6} {item['fund_code']:<10} "
            f"{item['fund_name'][:24]:<24} {item['total_score']:>6.1f}"
        )
    if ranked:
        fund_code = ranked[0]["fund_code"]
except Exception as e:
    print(f"   Error: {e}")
print()

# Example 7: Screen equity growth funds
print("7. Screen Equity Growth Funds")
try:
    screen_result = client.fund.screen_funds(
        regime="Recovery",
        custom_types=["股票型"],
        custom_styles=["成长"],
        min_scale=1_000_000_000,
        limit=5,
    )
    print(f"   Success: {screen_result.get('success')}")
    for code, name in zip(screen_result.get("fund_codes", []), screen_result.get("fund_names", []), strict=False):
        print(f"   {code:<12} {name}")
except Exception as e:
    print(f"   Error: {e}")
print()

# Example 8: Get fund detail
print("8. Fund Detail")
try:
    detail = client.fund.get_fund_detail(fund_code)
    print(f"   Code: {detail.get('fund_code')}")
    print(f"   Name: {detail.get('fund_name')}")
    print(f"   Type: {detail.get('fund_type')}")
    print(f"   Style: {detail.get('investment_style')}")
except Exception as e:
    print(f"   Error: {e}")
print()

# Example 9: Get fund NAV and performance
print("9. Fund NAV and Performance")
try:
    nav_history = client.fund.get_nav_history(
        fund_code,
        start_date=date(2024, 1, 1),
        end_date=date(2024, 12, 31),
        limit=3,
    )
    perf = client.fund.get_performance(fund_code, period="1y")
    for nav in nav_history:
        print(f"   NAV {nav['nav_date']}: unit={nav['unit_nav']} accum={nav['accum_nav']}")
    print(f"   Total Return: {perf.get('total_return')}")
    print(f"   Volatility: {perf.get('volatility')}")
    print(f"   Sharpe Ratio: {perf.get('sharpe_ratio')}")
except Exception as e:
    print(f"   Error: {e}")
print()

# Example 10: Get fund holdings
print("10. Fund Top Holdings")
try:
    holdings = client.fund.get_holdings(fund_code, report_date=date(2024, 9, 30))
    print(f"   {fund_code} Top Holdings")
    print(f"   {'Stock':<12} {'Name':<20} {'Ratio':<10}")
    print("   " + "-" * 42)
    for h in holdings[:5]:
        stock_name = h.get("stock_name", "N/A")[:18]
        ratio = (h.get("holding_ratio") or 0) * 100
        print(f"   {h['stock_code']:<12} {stock_name:<20} {ratio:>6.2f}%")
except Exception as e:
    print(f"   Error: {e}")
print()

# =============================================================================
# Sector Analysis
# =============================================================================

print("\n=== Sector Analysis ===\n")

# Example 11: Get hot sectors
print("11. Hot Sectors Today")
try:
    hot_sectors = client.sector.get_hot_sectors(limit=5)
    print(f"   {'Sector':<20} {'Change':<10} {'Score':<8}")
    print("   " + "-" * 38)
    for sector in hot_sectors:
        change = sector.get("change_percent", 0) * 100
        print(f"   {sector['name']:<20} {change:>+6.2f}% {sector.get('score', 0):>6}")
except Exception as e:
    print(f"   Error: {e}")
print()

# Example 12: Compare sectors
print("12. Sector Comparison")
try:
    sectors_to_compare = ["银行", "医药", "地产"]
    comparison = client.sector.compare_sectors(sectors_to_compare)
    print(f"   {'Sector':<12} {'Score':<8} {'Change':<10}")
    print("   " + "-" * 30)
    for name, data in comparison.items():
        change = data.get("change_percent", 0) * 100
        print(f"   {name:<12} {data.get('score', 0):>6} {change:>+6.2f}%")
except Exception as e:
    print(f"   Error: {e}")
print()

# Clean up
client.close()
print("=== Analysis Complete ===")
