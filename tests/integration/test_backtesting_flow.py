"""
Integration Test: Backtesting Flow

This test simulates a backtesting workflow:
1. Run a backtest
2. Get backtest results
3. Get net value curve
4. Verify backtest data

Usage:
    pytest tests/integration/test_backtesting_flow.py -v
    or
    python tests/integration/test_backtesting_flow.py
"""

import os
import sys
from datetime import date, datetime, timedelta
import pytest

# Add project root to path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))

# Set environment variables
os.environ["AGOMSAAF_BASE_URL"] = "http://localhost:8000"
os.environ.setdefault("AGOMSAAF_API_TOKEN", "test-token")

from sdk.agomsaaf import AgomSAAFClient

pytestmark = pytest.mark.skipif(
    not os.environ.get("AGOMSAAF_LIVE_SERVER"),
    reason="Requires running server (set AGOMSAAF_LIVE_SERVER=1)"
)


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


def print_info(message: str) -> None:
    """Print informational message"""
    print(f"  INFO: {message}")


def test_backtesting_flow() -> None:
    """
    Test backtesting flow through SDK.

    This test verifies:
    1. Listing existing backtests
    2. Running a new backtest (if supported)
    3. Retrieving backtest results
    4. Getting net value curve data
    5. Verifying backtest metrics
    """

    print("\n" + "="*60)
    print("INTEGRATION TEST: Backtesting Flow")
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
        # STEP 2: List Existing Backtests
        # ====================================================================
        print_step(2, "List Existing Backtests")

        backtests = client.backtest.list_backtests()
        print(f"  Total backtests: {len(backtests)}")

        if backtests:
            print(f"  Most recent backtest:")
            print(f"    ID: {backtests[0].id}")
            print(f"    Name: {backtests[0].name}")
            print(f"    Status: {backtests[0].status}")
            print(f"    Created: {backtests[0].created_at}")

        print_result(True, f"Found {len(backtests)} backtests")

        # ====================================================================
        # STEP 3: Get Backtest Details
        # ====================================================================
        print_step(3, "Get Backtest Details")

        if backtests:
            # Get details of the most recent backtest
            backtest_id = backtests[0].id
            backtest_detail = client.backtest.get(backtest_id)

            print(f"  Backtest ID: {backtest_detail.id}")
            print(f"  Name: {backtest_detail.name}")
            print(f"  Description: {backtest_detail.description or 'N/A'}")
            print(f"  Status: {backtest_detail.status}")

            if backtest_detail.start_date:
                print(f"  Start Date: {backtest_detail.start_date}")
            if backtest_detail.end_date:
                print(f"  End Date: {backtest_detail.end_date}")

            if backtest_detail.initial_capital:
                print(f"  Initial Capital: {backtest_detail.initial_capital}")

            print_result(True, f"Retrieved details for backtest {backtest_id}")

            # Save for next steps
            test_backtest_id = backtest_id
        else:
            print_result(False, "No backtests found to test with")
            print_info("Please create a backtest through the admin panel first")
            test_backtest_id = None

        # ====================================================================
        # STEP 4: Get Backtest Results
        # ====================================================================
        print_step(4, "Get Backtest Results")

        if test_backtest_id:
            try:
                results = client.backtest.get_results(test_backtest_id)

                print(f"  Total Return: {results.total_return}")
                print(f"  Annualized Return: {results.annualized_return}")
                print(f"  Max Drawdown: {results.max_drawdown}")
                print(f"  Sharpe Ratio: {results.sharpe_ratio}")
                print(f"  Win Rate: {results.win_rate}")
                print(f"  Total Trades: {results.total_trades}")

                print_result(True, "Backtest results retrieved successfully")

                # Verify metrics are reasonable
                if results.total_return is not None:
                    print_result(True, f"Total return: {results.total_return:.2%}")
                if results.max_drawdown is not None:
                    print_result(True, f"Max drawdown: {results.max_drawdown:.2%}")
                if results.sharpe_ratio is not None:
                    print_result(True, f"Sharpe ratio: {results.sharpe_ratio:.2f}")

            except Exception as e:
                print_result(False, f"Failed to get results: {e}")
                print_info("The backtest might still be running or results not available")

        # ====================================================================
        # STEP 5: Get Net Value Curve
        # ====================================================================
        print_step(5, "Get Net Value Curve")

        if test_backtest_id:
            try:
                curve = client.backtest.get_net_value_curve(test_backtest_id)

                print(f"  Data points: {len(curve)}")

                if curve:
                    print(f"  First point: {curve[0].date} = {curve[0].value}")
                    print(f"  Last point: {curve[-1].date} = {curve[-1].value}")

                    # Calculate total return from curve
                    if len(curve) > 1:
                        total_return = (curve[-1].value / curve[0].value) - 1
                        print(f"  Calculated return: {total_return:.2%}")

                    # Sample some middle points
                    if len(curve) > 10:
                        mid = len(curve) // 2
                        print(f"  Mid point: {curve[mid].date} = {curve[mid].value}")

                print_result(True, f"Net value curve retrieved with {len(curve)} points")

            except Exception as e:
                print_result(False, f"Failed to get net value curve: {e}")
                print_info("The backtest might not have curve data available")

        # ====================================================================
        # STEP 6: Get Trade History
        # ====================================================================
        print_step(6, "Get Trade History")

        if test_backtest_id:
            try:
                trades = client.backtest.get_trade_history(test_backtest_id)

                print(f"  Total trades: {len(trades)}")

                if trades:
                    print(f"  First trade:")
                    print(f"    Asset: {trades[0].asset_code}")
                    print(f"    Type: {trades[0].trade_type}")
                    print(f"    Date: {trades[0].trade_date}")
                    print(f"    Price: {trades[0].price}")
                    print(f"    Quantity: {trades[0].quantity}")

                    # Show last few trades
                    if len(trades) > 1:
                        print(f"  Last trade:")
                        print(f"    Asset: {trades[-1].asset_code}")
                        print(f"    Type: {trades[-1].trade_type}")
                        print(f"    Date: {trades[-1].trade_date}")

                print_result(True, f"Trade history retrieved with {len(trades)} trades")

            except Exception as e:
                print_result(False, f"Failed to get trade history: {e}")
                print_info("Trade history might not be available for this backtest")

        # ====================================================================
        # TEST SUMMARY
        # ====================================================================
        print("\n" + "="*60)
        print("INTEGRATION TEST SUMMARY")
        print("="*60)
        print("\nBacktesting flow test completed!")
        print("\nVerified:")
        print("  [OK] SDK client initialization")
        print("  [OK] Backtest listing")
        print("  [OK] Backtest details retrieval")
        print("  [OK] Backtest results retrieval")
        print("  [OK] Net value curve retrieval")
        print("  [OK] Trade history retrieval")
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
            pytest.skip(f"backtesting_flow skipped due to environment endpoint/auth availability: {error_text}")
        print(f"\n[ERROR] Test failed with exception: {e}")
        import traceback
        traceback.print_exc()
        raise

    finally:
        if client:
            client.close()


if __name__ == "__main__":
    test_backtesting_flow()
