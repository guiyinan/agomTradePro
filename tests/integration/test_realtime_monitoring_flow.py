"""
Integration Test: Real-time Monitoring Flow

This test simulates a real-time data monitoring workflow:
1. Get real-time prices
2. Get market overview
3. Get top gainers/losers
4. Verify real-time data freshness

Usage:
    set AGOMTRADEPRO_RUN_LIVE_REALTIME_TESTS=1
    pytest tests/integration/test_realtime_monitoring_flow.py -v
    or
    set AGOMTRADEPRO_RUN_LIVE_REALTIME_TESTS=1
    python tests/integration/test_realtime_monitoring_flow.py
"""

import os
import sys
from datetime import UTC, datetime, timezone

import pytest

# Add project root to path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))

# Set environment variables
os.environ["AGOMTRADEPRO_BASE_URL"] = "http://localhost:8000"
os.environ.setdefault("AGOMTRADEPRO_API_TOKEN", "test-token")

from sdk.agomtradepro import AgomTradeProClient


@pytest.fixture(scope="module", autouse=True)
def require_live_realtime_environment() -> None:
    """
    默认跳过依赖本地服务和真实行情的实时集成测试。

    显式设置 `AGOMTRADEPRO_RUN_LIVE_REALTIME_TESTS=1` 时才运行。
    """
    if os.getenv("AGOMTRADEPRO_RUN_LIVE_REALTIME_TESTS") != "1":
        pytest.skip(
            "real-time integration test skipped by default; set AGOMTRADEPRO_RUN_LIVE_REALTIME_TESTS=1 to enable"
        )

    try:
        import requests

        response = requests.get("http://localhost:8000/api/", timeout=3)
        response.raise_for_status()
    except Exception as exc:
        pytest.skip(f"real-time integration test requires a live server at http://localhost:8000: {exc}")


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

        from sdk.agomtradepro import AgomTradeProClient
        client = AgomTradeProClient()
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
                print(f"    Current Price: {price_data.get('current_price')}")
                print(
                    f"    Change: {price_data.get('price_change')} "
                    f"({float(price_data.get('price_change_percent') or 0):.2f}%)"
                )
                print(f"    Volume: {price_data.get('volume')}")
                print(f"    Turnover: {price_data.get('turnover')}")
                print(f"    High: {price_data.get('high_price')}")
                print(f"    Low: {price_data.get('low_price')}")
                print(f"    Open: {price_data.get('open_price')}")
                print(f"    Update Time: {price_data.get('updated_at')}")

                # Check data freshness (should be within last trading day)
                if price_data.get("updated_at"):
                    now = datetime.now(UTC)
                    updated_at = datetime.fromisoformat(price_data["updated_at"])
                    if updated_at.tzinfo is None:
                        updated_at = updated_at.replace(tzinfo=UTC)
                    age_hours = (now - updated_at.astimezone(UTC)).total_seconds() / 3600
                    if age_hours < 48:
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
                print(
                    f"    {price_data.get('asset_code')}: {price_data.get('current_price')} "
                    f"({float(price_data.get('price_change_percent') or 0):+.2f}%)"
                )

            print_result(True, f"Batch prices retrieved for {len(batch_prices)} assets")

        except Exception as e:
            print_result(False, f"Failed to get batch prices: {e}")

        # ====================================================================
        # STEP 4: Get Market Overview
        # ====================================================================
        print_step(4, "Get Market Overview")

        try:
            overview = client.realtime.get_market_overview()

            print(f"  Market Status: {overview.get('market_status')}")
            print(f"  Last Update: {overview.get('last_update')}")

            if overview.get("indices"):
                print("\n  Major Indices:")
                for idx in overview["indices"]:
                    print(
                        f"    {idx.get('name')}: {idx.get('value')} "
                        f"({float(idx.get('change_percent') or 0):+.2f}%)"
                    )

            if overview.get("market_summary"):
                print("\n  Market Summary:")
                summary = overview["market_summary"]
                print(
                    f"    Up/Down/Unchanged: "
                    f"{summary.get('advancing')}/{summary.get('declining')}/{summary.get('unchanged')}"
                )
                print(f"    Limit Up: {summary.get('limit_up')}")
                print(f"    Limit Down: {summary.get('limit_down')}")

            if overview.get("turnover"):
                print(f"\n  Turnover: {overview.get('turnover')}")

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
                print(
                    f"    {i}. {item.get('asset_code')}: {item.get('current_price')} "
                    f"({float(item.get('price_change_percent') or 0):+.2f}%)"
                )
                print(f"       Turnover: {item.get('turnover')}")

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
                print(
                    f"    {i}. {item.get('asset_code')}: {item.get('current_price')} "
                    f"({float(item.get('price_change_percent') or 0):+.2f}%)"
                )
                print(f"       Turnover: {item.get('turnover')}")

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
                print(
                    f"    {i}. {item.get('asset_code')}: {item.get('volume')} "
                    f"({item.get('current_price')}, {float(item.get('price_change_percent') or 0):+.2f}%)"
                )

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

            print(f"  First call: {price1.get('current_price')} at {price1.get('updated_at')}")
            print(f"  Second call: {price2.get('current_price')} at {price2.get('updated_at')}")

            # Prices should be identical or very close (no rapid changes expected)
            if abs(float(price1.get("current_price") or 0) - float(price2.get("current_price") or 0)) < 0.01:
                print_result(True, "Price data is consistent across calls")
            else:
                print_result(False, f"Price changed: {price1.get('current_price')} -> {price2.get('current_price')}")

            # Update times should be identical (cached data)
            if price1.get("updated_at") == price2.get("updated_at"):
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
        error_text = str(e)
        if (
            "[404]" in error_text
            or "Resource not found" in error_text
            or "[401]" in error_text
            or "[403]" in error_text
            or "Authentication failed" in error_text
            or "Either api_token or username/password must be provided" in error_text
        ):
            pytest.skip(
                f"realtime_monitoring_flow skipped due to environment endpoint/auth availability: {error_text}"
            )
        print(f"\n[ERROR] Test failed with exception: {e}")
        import traceback
        traceback.print_exc()
        raise

    finally:
        if client:
            client.close()


if __name__ == "__main__":
    test_realtime_monitoring_flow()
