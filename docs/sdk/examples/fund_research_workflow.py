"""
AgomTradePro SDK - Fund Research Workflow Example

Canonical workflow:
1. Prepare local fund research data.
2. Rank funds by regime.
3. Screen a narrower universe.
4. Inspect detail, NAV, holdings, and performance for one target fund.
"""

from datetime import date

from agomtradepro import AgomTradeProClient


def main() -> None:
    print("Before using fund research APIs, prepare local data first:")
    print(
        "  python manage.py prepare_fund_research_data "
        "--start-date 2024-01-01 --end-date 2024-12-31"
    )
    print()

    client = AgomTradeProClient(
        base_url="http://127.0.0.1:8000",
        api_token="your_token_here",
    )

    try:
        regime = client.regime.get_current().dominant_regime
        print(f"Current regime: {regime}")
        print()

        ranked = client.fund.rank_funds(regime=regime, max_count=5)
        print("Top ranked funds:")
        for item in ranked:
            print(
                f"  {item['rank']:>2}. {item['fund_code']} "
                f"{item['fund_name']} total={item['total_score']:.1f}"
            )
        print()

        screened = client.fund.screen_funds(
            regime=regime,
            custom_types=["股票型"],
            custom_styles=["成长"],
            min_scale=1_000_000_000,
            limit=5,
        )
        print("Screen result:")
        print(f"  success={screened['success']} count={len(screened['fund_codes'])}")
        for code, name in zip(screened["fund_codes"], screened["fund_names"]):
            print(f"  {code} {name}")
        print()

        target_code = ranked[0]["fund_code"]
        detail = client.fund.get_fund_detail(target_code)
        print("Target fund detail:")
        print(
            f"  {detail['fund_code']} {detail['fund_name']} "
            f"type={detail.get('fund_type')} style={detail.get('investment_style')}"
        )
        print()

        nav_history = client.fund.get_nav_history(
            target_code,
            start_date=date(2024, 1, 1),
            end_date=date(2024, 12, 31),
            limit=5,
        )
        print("Recent NAV points:")
        for nav in nav_history[:5]:
            print(
                f"  {nav['nav_date']} unit_nav={nav['unit_nav']} " f"accum_nav={nav['accum_nav']}"
            )
        print()

        performance = client.fund.get_performance(target_code, period="1y")
        print("Performance snapshot:")
        print(
            f"  total_return={performance.get('total_return')} "
            f"volatility={performance.get('volatility')} "
            f"sharpe_ratio={performance.get('sharpe_ratio')}"
        )
        print()

        holdings = client.fund.get_holdings(
            target_code,
            report_date=date(2024, 9, 30),
        )
        print("Top holdings:")
        for row in holdings[:5]:
            print(
                f"  {row['stock_code']} {row.get('stock_name', '')} "
                f"ratio={row.get('holding_ratio')}"
            )
    finally:
        client.close()


if __name__ == "__main__":
    main()
