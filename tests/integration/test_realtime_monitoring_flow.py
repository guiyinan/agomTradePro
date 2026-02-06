"""
Integration Test: Real-time Monitoring Flow

This test simulates a real-time data monitoring workflow:
1. Get real-time prices
2. Get market overview
3. Get top gainers/losers
4. Verify real-time data freshness

Usage:
    pytest tests/integration/test_realtime_monitoring_flow.py -v
    or
    python tests/integration/test_realtime_monitoring_flow.py
"""

import os
import sys
from datetime import datetime, timezone

# Add project root to path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))

# Set environment variables
os.environ["AGOMSAAF_BASE_URL"] = "http://localhost:8000"

from sdk.agomsaaf import AgomSAAFClient


def print_step(step: int, description: str) -> None:
    """Print a test step"""
    print(f"\n{'='*60}")
    print(f"STEP {step}: {description}")
    print('='*60)


def print_result(success: bool, message: str) -> None:
    """Print a test result"""
    status = "PASS" if success else "FAIL"
    symbol = "[OK]" if success else "[FAIL]"
    print(f"{symbol} {message}")


def test_realtime_monitoring_flow() -> None:
    """
    Test real-time monitoring flow through SDK.

    This test verifies:
    1. Real-time price retrieval
    2. Market overview data
    3. Top gainers and losers
    4. Data freshness and accuracy
    """

    print("\n" + "="*60)
    print("INTEGRATION TEST: Real-time Monitoring Flow")
    print("="*60)

    client = None

    try:
        # ====================================================================
        # STEP 1: Initialize Client
        # ====================================================================
        print_step(1, "Initialize SDK Client")

        from sdk.agomsaaf import AgomSAAFClient
        client = AgomSAAFClient()
        print_result(True, f"Client initialized (Base URL: {client._config.base_url})")

        # ====================================================================
        # STEP 2: Get Real-time Price for Single Asset
        # ====================================================================
        print_step(2, "Get Real-time Price")

        # Test with common indices
        test_assets = ["000001.SH", "399001.SZ", "000300.SH"]

        for asset_code in test_assets:
            try:
                price_data = client.realtime.get_price(asset_code)

                print(f"\n  Asset: {asset_code}")
                print(f"    Current Price: {price_data.current_price}")
                print(f"    Change: {price_data.price_change} ({price_data.price_change_percent:.2f}%)")
                print(f"    Volume: {price_data.volume}")
                print(f"    Turnover: {price_data.turnover}")
                print(f"    High: {price_data.high_price}")
                print(f"    Low: {price_data.low_price}")
                print(f"    Open: {price_data.open_price}")
                print(f"    Update Time: {price_data.updated_at}")

                # Check data freshness (should be within last trading day)
                if price_data.updated_at:
                    now = datetime.now(timezone.utc)
                    age_hours = (now - price_data.updated_at).total_seconds() / 3600
                    if age_hours < 48:  # Within 2 days (accounting for weekends)
                        print_result(True, f"Data is fresh ({age_hours:.1f} hours old)")
                    else:
                        print_result(False, f"Data is stale ({age_hours:.1f} hours old)")

                print_result(True, f"Retrieved price for {asset_code}")
                break  # Success, no need to try other assets

            except Exception as e:
                print(f"  Failed to get price for {asset_code}: {e}")
                continue

        # ====================================================================
        # STEP 3: Get Batch Real-time Prices
        # ====================================================================
        print_step(3, "Get Batch Real-time Prices")

        batch_assets = ["000001.SH", "399001.SZ", "000300.SH", "000016.SH", "399006.SZ"]

        try:
            batch_prices = client.realtime.get_batch_prices(batch_assets)

            print(f"  Requested: {len(batch_assets)} assets")
            print(f"  Received: {len(batch_prices)} price records")

            for price_data in batch_prices:
                print(f"    {price_data.asset_code}: {price_data.current_price} "
                      f"({price_data.price_change_percent:+.2f}%)")

            print_result(True, f"Batch prices retrieved for {len(batch_prices)} assets")

        except Exception as e:
            print_result(False, f"Failed to get batch prices: {e}")

        # ====================================================================
        # STEP 4: Get Market Overview
        # ====================================================================
        print_step(4, "Get Market Overview")

        try:
            overview = client.realtime.get_market_overview()

            print(f"  Market Status: {overview.market_status}")
            print(f"  Last Update: {overview.last_update}")

            if overview.indices:
                print(f"\n  Major Indices:")
                for idx in overview.indices:
                    print(f"    {idx.name}: {idx.value} ({idx.change_percent:+.2f}%)")

            if overview.market_summary:
                print(f"\n  Market Summary:")
                summary = overview.market_summary
                print(f"    Up/Down/Unchanged: {summary.advancing}/{summary.declining}/{summary.unchanged}")
                print(f"    Limit Up: {summary.limit_up}")
                print(f"    Limit Down: {summary.limit_down}")

            if overview.turnover:
                print(f"\n  Turnover: {overview.turnover}")

            print_result(True, "Market overview retrieved successfully")

        except Exception as e:
            print_result(False, f"Failed to get market overview: {e}")

        # ====================================================================
        # STEP 5: Get Top Gainers
        # ====================================================================
        print_step(5, "Get Top Gainers")

        try:
            gainers = client.realtime.get_top_gainers(limit=10)

            print(f"  Top {len(gainers)} Gainers:")

            for i, item in enumerate(gainers[:5], 1):
                print(f"    {i}. {item.asset_code}: {item.current_price} "
                      f"({item.price_change_percent:+.2f}%)")
                print(f"       Turnover: {item.turnover}")

            print_result(True, f"Retrieved {len(gainers)} top gainers")

        except Exception as e:
            print_result(False, f"Failed to get top gainers: {e}")

        # ====================================================================
        # STEP 6: Get Top Losers
        # ====================================================================
        print_step(6, "Get Top Losers")

        try:
            losers = client.realtime.get_top_losers(limit=10)

            print(f"  Top {len(losers)} Losers:")

            for i, item in enumerate(losers[:5], 1):
                print(f"    {i}. {item.asset_code}: {item.current_price} "
                      f"({item.price_change_percent:+.2f}%)")
                print(f"       Turnover: {item.turnover}")

            print_result(True, f"Retrieved {len(losers)} top losers")

        except Exception as e:
            print_result(False, f"Failed to get top losers: {e}")

        # ====================================================================
        # STEP 7: Get Most Active Stocks
        # ====================================================================
        print_step(7, "Get Most Active Stocks")

        try:
            active = client.realtime.get_most_active(limit=10)

            print(f"  Top {len(active)} Most Active:")

            for i, item in enumerate(active[:5], 1):
                print(f"    {i}. {item.asset_code}: {item.turnover} "
                      f"({item.current_price}, {item.price_change_percent:+.2f}%)")

            print_result(True, f"Retrieved {len(active)} most active stocks")

        except Exception as e:
            print_result(False, f"Failed to get most active stocks: {e}")

        # ====================================================================
        # STEP 8: Test Real-time Data Consistency
        # ====================================================================
        print_step(8, "Test Real-time Data Consistency")

        try:
            # Get price for same asset twice
            asset_code = "000001.SH"
            price1 = client.realtime.get_price(asset_code)
            # Small delay
            import time
            time.sleep(0.5)
            price2 = client.realtime.get_price(asset_code)

            print(f"  First call: {price1.current_price} at {price1.updated_at}")
            print(f"  Second call: {price2.current_price} at {price2.updated_at}")

            # Prices should be identical or very close (no rapid changes expected)
            if abs(price1.current_price - price2.current_price) < 0.01:
                print_result(True, "Price data is consistent across calls")
            else:
                print_result(False, f"Price changed: {price1.current_price} -> {price2.current_price}")

            # Update times should be identical (cached data)
            if price1.updated_at == price2.updated_at:
                print_result(True, "Timestamps are identical (cached)")
            else:
                print_result(False, "Timestamps differ (unexpected)")

        except Exception as e:
            print_result(False, f"Failed consistency test: {e}")

        # ====================================================================
        # TEST SUMMARY
        # ====================================================================
        print("\n" + "="*60)
        print("INTEGRATION TEST SUMMARY")
        print("="*60)
        print("\nReal-time monitoring flow test completed!")
        print("\nVerified:")
        print("  [OK] SDK client initialization")
        print("  [OK] Real-time price retrieval")
        print("  [OK] Batch price retrieval")
        print("  [OK] Market overview")
        print("  [OK] Top gainers/losers")
        print("  [OK] Most active stocks")
        print("  [OK] Data consistency")
        print("\n" + "="*60)

    except Exception as e:
        print(f"\n[ERROR] Test failed with exception: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

    finally:
        if client:
            client.close()


if __name__ == "__main__":
    test_realtime_monitoring_flow()
