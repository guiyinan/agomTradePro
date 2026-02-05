"""
AgomSAAF SDK - Equity and Fund Analysis Example

This file demonstrates stock and fund analysis using the AgomSAAF SDK.
"""

from agomsaaf import AgomSAAFClient
from datetime import date

# Initialize client
client = AgomSAAFClient(
    base_url="http://localhost:8000",
    api_token="your_token_here"
)

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
        print(f"   {f['report_date']}: Revenue {f.get('revenue', 0):,.0f}, "
              f"Net Income {f.get('net_income', 0):,.0f}")
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

# Example 6: Get fund score
print("6. Fund Score Analysis")
fund_code = "000001.OF"
try:
    score = client.fund.get_fund_score(fund_code)
    print(f"   {fund_code} ({score.get('name', 'N/A')})")
    print(f"   Overall Score: {score.get('overall_score', 0)}/100")
    print(f"   Performance Score: {score.get('performance_score', 0)}/100")
    print(f"   Risk Score: {score.get('risk_score', 0)}/100")
    print(f"   Manager Score: {score.get('manager_score', 0)}/100")
except Exception as e:
    print(f"   Error: {e}")
print()

# Example 7: List equity funds
print("7. Top Equity Funds")
try:
    funds = client.fund.list_funds(fund_type="equity", min_score=60, limit=10)
    print(f"   {'Code':<12} {'Name':<30} {'Score':<8}")
    print("   " + "-" * 50)
    for fund in funds[:5]:
        name = fund.get('name', 'N/A')[:28]
        print(f"   {fund['code']:<12} {name:<30} {fund.get('score', 0):>6}")
except Exception as e:
    print(f"   Error: {e}")
print()

# Example 8: Get fund performance
print("8. Fund Performance")
try:
    perf = client.fund.get_performance(fund_code, period="1y")
    print(f"   {fund_code} Performance (1 Year)")
    print(f"   Return: {perf.get('return', 0):.2%}")
    print(f"   Volatility: {perf.get('volatility', 0):.2%}")
    print(f"   Sharpe Ratio: {perf.get('sharpe', 'N/A')}")
    print(f"   Max Drawdown: {perf.get('max_drawdown', 0):.2%}")
except Exception as e:
    print(f"   Error: {e}")
print()

# Example 9: Get fund holdings
print("9. Fund Top Holdings")
try:
    holdings = client.fund.get_holdings(fund_code, limit=10)
    print(f"   {fund_code} Top Holdings")
    print(f"   {'Stock':<12} {'Name':<20} {'Weight':<10}")
    print("   " + "-" * 42)
    for h in holdings[:5]:
        stock_name = h.get('stock_name', 'N/A')[:18]
        weight = h.get('weight', 0) * 100
        print(f"   {h['stock_code']:<12} {stock_name:<20} {weight:>6.2f}%")
except Exception as e:
    print(f"   Error: {e}")
print()

# =============================================================================
# Sector Analysis
# =============================================================================

print("\n=== Sector Analysis ===\n")

# Example 10: Get hot sectors
print("10. Hot Sectors Today")
try:
    hot_sectors = client.sector.get_hot_sectors(limit=5)
    print(f"   {'Sector':<20} {'Change':<10} {'Score':<8}")
    print("   " + "-" * 38)
    for sector in hot_sectors:
        change = sector.get('change_percent', 0) * 100
        print(f"   {sector['name']:<20} {change:>+6.2f}% {sector.get('score', 0):>6}")
except Exception as e:
    print(f"   Error: {e}")
print()

# Example 11: Compare sectors
print("11. Sector Comparison")
try:
    sectors_to_compare = ["银行", "医药", "地产"]
    comparison = client.sector.compare_sectors(sectors_to_compare)
    print(f"   {'Sector':<12} {'Score':<8} {'Change':<10}")
    print("   " + "-" * 30)
    for name, data in comparison.items():
        change = data.get('change_percent', 0) * 100
        print(f"   {name:<12} {data.get('score', 0):>6} {change:>+6.2f}%")
except Exception as e:
    print(f"   Error: {e}")
print()

# Clean up
client.close()
print("=== Analysis Complete ===")
