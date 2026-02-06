"""
AgomSAAF SDK Connection Test Script

Tests the SDK's basic connection and functionality.
This script verifies that the SDK can connect to the AgomSAAF API
and perform basic operations.

Usage:
    python test_sdk_connection.py

Requirements:
    - Django server running on http://localhost:8000
    - SDK installed in development mode
"""

import os
import sys
from typing import Any
from pathlib import Path

# Add project root to Python path
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

# Set environment variables for testing
os.environ["AGOMSAAF_BASE_URL"] = "http://localhost:8000"


def print_section(title: str) -> None:
    """Print a formatted section header"""
    print("\n" + "=" * 60)
    print(f"  {title}")
    print("=" * 60)


def print_test(name: str) -> None:
    """Print a test name"""
    print(f"\n[{name}]")


def print_success(message: str) -> None:
    """Print a success message"""
    print(f"  OK: {message}")


def print_error(message: str) -> None:
    """Print an error message"""
    print(f"  FAIL: {message}", file=sys.stderr)


def print_info(message: str) -> None:
    """Print an info message"""
    print(f"  INFO: {message}")


def test_import_sdk() -> bool:
    """Test 1: Import SDK"""
    print_test("Test 1: Import SDK")
    try:
        from sdk.agomsaaf import AgomSAAFClient
        print_success("SDK imported successfully")
        return True
    except ImportError as e:
        print_error(f"Failed to import SDK: {e}")
        print_info("Make sure the SDK is installed: pip install -e sdk/")
        return False


def test_create_client() -> bool:
    """Test 2: Create Client"""
    print_test("Test 2: Create Client")
    try:
        from sdk.agomsaaf import AgomSAAFClient

        client = AgomSAAFClient()
        print_success("Client created successfully")
        print_info(f"Base URL: {client._config.base_url}")
        return True
    except Exception as e:
        print_error(f"Failed to create client: {e}")
        return False


def test_get_current_regime() -> bool:
    """Test 3: Get Current Regime"""
    print_test("Test 3: Get Current Regime")
    try:
        from sdk.agomsaaf import AgomSAAFClient

        client = AgomSAAFClient()
        regime = client.regime.get_current()

        print_success(f"Current regime: {regime.dominant_regime}")
        print_info(f"Growth level: {regime.growth_level}")
        print_info(f"Inflation level: {regime.inflation_level}")
        print_info(f"Observed at: {regime.observed_at}")
        return True
    except Exception as e:
        print_error(f"Failed to get current regime: {e}")
        print_info("Make sure the server has macro data available")
        return False


def test_get_policy_status() -> bool:
    """Test 4: Get Policy Status"""
    print_test("Test 4: Get Policy Status")
    try:
        from sdk.agomsaaf import AgomSAAFClient

        client = AgomSAAFClient()
        status = client.policy.get_status()

        print_success(f"Current gear: {status.current_gear}")
        print_info(f"Observed at: {status.observed_at}")
        if status.recent_events:
            print_info(f"Recent events: {len(status.recent_events)}")
        return True
    except Exception as e:
        print_error(f"Failed to get policy status: {e}")
        return False


def test_list_macro_indicators() -> bool:
    """Test 5: List Macro Indicators"""
    print_test("Test 5: List Macro Indicators")
    try:
        from sdk.agomsaaf import AgomSAAFClient

        client = AgomSAAFClient()
        indicators = client.macro.list_indicators()

        print_success(f"Found {len(indicators)} macro indicators")
        if indicators:
            print_info(f"First indicator: {indicators[0].code} - {indicators[0].name}")
        return True
    except Exception as e:
        print_error(f"Failed to list macro indicators: {e}")
        return False


def test_list_signals() -> bool:
    """Test 6: List Investment Signals"""
    print_test("Test 6: List Investment Signals")
    try:
        from sdk.agomsaaf import AgomSAAFClient

        client = AgomSAAFClient()
        signals = client.signal.list()

        print_success(f"Found {len(signals)} investment signals")
        if signals:
            print_info(f"First signal: {signals[0].asset_code} - {signals[0].logic_desc[:50]}...")
        return True
    except Exception as e:
        print_error(f"Failed to list signals: {e}")
        return False


def test_check_signal_eligibility() -> bool:
    """Test 7: Check Signal Eligibility"""
    print_test("Test 7: Check Signal Eligibility")
    try:
        from sdk.agomsaaf import AgomSAAFClient

        client = AgomSAAFClient()
        eligibility = client.signal.check_eligibility(
            asset_code="000001.SH",
            logic_desc="Test signal for eligibility check"
        )

        print_success(f"Eligibility check completed")
        print_info(f"Is eligible: {eligibility.is_eligible}")
        if eligibility.regime_match:
            print_info(f"Regime match: {eligibility.regime_match}")
        if eligibility.policy_match:
            print_info(f"Policy match: {eligibility.policy_match}")
        return True
    except Exception as e:
        print_error(f"Failed to check eligibility: {e}")
        return False


def test_regime_history() -> bool:
    """Test 8: Get Regime History"""
    print_test("Test 8: Get Regime History")
    try:
        from sdk.agomsaaf import AgomSAAFClient

        client = AgomSAAFClient()
        history = client.regime.history(limit=5)

        print_success(f"Found {len(history)} regime history records")
        if history:
            print_info(f"Latest: {history[0].dominant_regime} at {history[0].observed_at}")
        return True
    except Exception as e:
        print_error(f"Failed to get regime history: {e}")
        return False


def test_list_backtests() -> bool:
    """Test 9: List Backtests"""
    print_test("Test 9: List Backtests")
    try:
        from sdk.agomsaaf import AgomSAAFClient

        client = AgomSAAFClient()
        backtests = client.backtest.list_backtests()

        print_success(f"Found {len(backtests)} backtests")
        return True
    except Exception as e:
        print_error(f"Failed to list backtests: {e}")
        return False


def test_get_portfolios() -> bool:
    """Test 10: Get Portfolios"""
    print_test("Test 10: Get Portfolios")
    try:
        from sdk.agomsaaf import AgomSAAFClient

        client = AgomSAAFClient()
        portfolios = client.account.get_portfolios()

        print_success(f"Found {len(portfolios)} portfolios")
        return True
    except Exception as e:
        print_error(f"Failed to get portfolios: {e}")
        return False


def main() -> int:
    """Run all tests"""
    print_section("AgomSAAF SDK Connection Test")

    # Check if server is running
    print_test("Server Check")
    try:
        import requests
        response = requests.get("http://localhost:8000/api/", timeout=5)
        print_success("Server is running")
    except Exception as e:
        print_error(f"Cannot connect to server: {e}")
        print_info("Please start the server first: .\\scripts\\start-dev.ps1")
        return 1

    # Run tests
    tests = [
        ("Import SDK", test_import_sdk),
        ("Create Client", test_create_client),
        ("Get Current Regime", test_get_current_regime),
        ("Get Policy Status", test_get_policy_status),
        ("List Macro Indicators", test_list_macro_indicators),
        ("List Signals", test_list_signals),
        ("Check Signal Eligibility", test_check_signal_eligibility),
        ("Get Regime History", test_regime_history),
        ("List Backtests", test_list_backtests),
        ("Get Portfolios", test_get_portfolios),
    ]

    results: list[tuple[str, bool]] = []

    for name, test_func in tests:
        try:
            result = test_func()
            results.append((name, result))
        except Exception as e:
            print_error(f"Unexpected error: {e}")
            results.append((name, False))

    # Print summary
    print_section("Test Summary")

    passed = sum(1 for _, result in results if result)
    total = len(results)

    for name, result in results:
        status = "PASS" if result else "FAIL"
        symbol = "OK" if result else "X"
        print(f"  [{symbol}] {name}: {status}")

    print()
    print(f"  Total: {passed}/{total} tests passed")

    if passed == total:
        print_success("All tests passed!")
        return 0
    else:
        print_error(f"{total - passed} test(s) failed")
        return 1


if __name__ == "__main__":
    sys.exit(main())
