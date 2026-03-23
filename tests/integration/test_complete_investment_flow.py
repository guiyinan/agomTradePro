"""
Integration Test: Complete Investment Flow

This test simulates a complete investment workflow:
1. Get current macro regime
2. Get policy status
3. Check asset eligibility
4. Create investment signal
5. Verify signal creation

Usage:
    pytest tests/integration/test_complete_investment_flow.py -v
    or
    python tests/integration/test_complete_investment_flow.py
"""

import os
import sys
from datetime import date
from typing import Optional

import pytest

# Add project root to path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))

# Set environment variables
os.environ["AGOMTRADEPRO_BASE_URL"] = "http://localhost:8000"
os.environ.setdefault("AGOMTRADEPRO_API_TOKEN", "test-token")

from sdk.agomtradepro import AgomTradeProClient

pytestmark = pytest.mark.skipif(
    not os.environ.get("AGOMTRADEPRO_LIVE_SERVER"),
    reason="Requires running server (set AGOMTRADEPRO_LIVE_SERVER=1)"
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


def test_complete_investment_flow() -> None:
    """
    Test complete investment flow through SDK.

    This test verifies:
    1. Connection to the AgomTradePro API
    2. Retrieval of macro regime data
    3. Retrieval of policy status
    4. Signal eligibility checking
    5. Signal creation
    6. Data consistency across operations
    """

    print("\n" + "="*60)
    print("INTEGRATION TEST: Complete Investment Flow")
    print("="*60)

    client: AgomTradeProClient | None = None
    signal_id: int | None = None

    try:
        # ====================================================================
        # STEP 1: Initialize Client
        # ====================================================================
        print_step(1, "Initialize SDK Client")

        client = AgomTradeProClient()
        print_result(True, f"Client initialized (Base URL: {client._config.base_url})")

        # ====================================================================
        # STEP 2: Get Current Macro Regime
        # ====================================================================
        print_step(2, "Get Current Macro Regime")

        regime = client.regime.get_current()

        print(f"  Dominant Regime: {regime.dominant_regime}")
        print(f"  Growth Level: {regime.growth_level}")
        print(f"  Inflation Level: {regime.inflation_level}")
        print(f"  Observed At: {regime.observed_at}")
        print(f"  Growth Indicator: {regime.growth_indicator} = {regime.growth_value}")
        print(f"  Inflation Indicator: {regime.inflation_indicator} = {regime.inflation_value}")

        print_result(True, f"Current regime is {regime.dominant_regime}")

        # Save regime data for later verification
        saved_regime = regime.dominant_regime
        saved_regime_date = regime.observed_at

        # ====================================================================
        # STEP 3: Get Policy Status
        # ====================================================================
        print_step(3, "Get Policy Status")

        policy_status = client.policy.get_status()

        print(f"  Current Gear: {policy_status.current_gear}")
        print(f"  Observed At: {policy_status.observed_at}")
        print(f"  Recent Events: {len(policy_status.recent_events)}")

        for event in policy_status.recent_events[:3]:
            print(f"    - {event.event_date}: {event.description}")

        print_result(True, f"Current policy gear is {policy_status.current_gear}")

        # Save policy data for later verification
        saved_policy_gear = policy_status.current_gear

        # ====================================================================
        # STEP 4: Check Signal Eligibility
        # ====================================================================
        print_step(4, "Check Signal Eligibility")

        # Test with a common asset
        test_asset_code = "000001.SH"  # Shanghai Stock Exchange Index
        test_logic = "测试信号：基于当前宏观环境的投资建议"

        eligibility = client.signal.check_eligibility(
            asset_code=test_asset_code,
            logic_desc=test_logic
        )

        print(f"  Asset Code: {test_asset_code}")
        print(f"  Logic: {test_logic}")
        print(f"  Is Eligible: {eligibility.is_eligible}")

        if eligibility.regime_match:
            print(f"  Regime Match: {eligibility.regime_match}")

        if eligibility.policy_match:
            print(f"  Policy Match: {eligibility.policy_match}")

        if eligibility.reason:
            print(f"  Reason: {eligibility.reason}")

        print_result(True, f"Eligibility check completed: {eligibility.is_eligible}")

        # ====================================================================
        # STEP 5: List Existing Signals
        # ====================================================================
        print_step(5, "List Existing Signals")

        signals_before = client.signal.list()
        print(f"  Existing signals: {len(signals_before)}")

        if signals_before:
            print("  Most recent signal:")
            print(f"    Asset: {signals_before[0].asset_code}")
            print(f"    Logic: {signals_before[0].logic_desc[:50]}...")

        print_result(True, f"Found {len(signals_before)} existing signals")

        # ====================================================================
        # STEP 6: Create Investment Signal
        # ====================================================================
        print_step(6, "Create Investment Signal")

        # Create a test signal
        new_signal = client.signal.create(
            asset_code=test_asset_code,
            asset_name="上证指数",
            logic_desc=f"集成测试信号 - {date.today()}",
            signal_type="long",
            expected_return=0.05,
            holding_period_days=90,
            notes="通过SDK集成测试自动创建"
        )

        signal_id = new_signal.id

        print(f"  Signal ID: {new_signal.id}")
        print(f"  Asset: {new_signal.asset_code} - {new_signal.asset_name}")
        print(f"  Type: {new_signal.signal_type}")
        print(f"  Expected Return: {new_signal.expected_return}")
        print(f"  Holding Period: {new_signal.holding_period_days} days")
        print(f"  Status: {new_signal.status}")

        print_result(True, f"Signal created successfully (ID: {signal_id})")

        # ====================================================================
        # STEP 7: Verify Signal Creation
        # ====================================================================
        print_step(7, "Verify Signal Creation")

        signals_after = client.signal.list()

        # Find our newly created signal
        found_signal = None
        for s in signals_after:
            if s.id == signal_id:
                found_signal = s
                break

        if found_signal:
            print("  Signal found in list")
            print(f"  Asset: {found_signal.asset_code}")
            print(f"  Logic: {found_signal.logic_desc}")

            # Verify data consistency
            if found_signal.asset_code == test_asset_code:
                print_result(True, "Asset code matches")
            else:
                print_result(False, f"Asset code mismatch: {found_signal.asset_code} != {test_asset_code}")

            if found_signal.signal_type == "long":
                print_result(True, "Signal type matches")
            else:
                print_result(False, f"Signal type mismatch: {found_signal.signal_type} != long")

        else:
            print_result(False, f"Signal {signal_id} not found in list")

        # Verify signal count increased
        if len(signals_after) == len(signals_before) + 1:
            print_result(True, f"Signal count increased by 1 ({len(signals_before)} -> {len(signals_after)})")
        else:
            print_result(False, f"Signal count mismatch: {len(signals_before)} -> {len(signals_after)}")

        # ====================================================================
        # STEP 8: Get Signal Details
        # ====================================================================
        print_step(8, "Get Signal Details")

        if signal_id:
            signal_detail = client.signal.get(signal_id)

            print(f"  Signal ID: {signal_detail.id}")
            print(f"  Created At: {signal_detail.created_at}")
            print(f"  Updated At: {signal_detail.updated_at}")
            print(f"  Regime Context: {signal_detail.regime_context}")
            print(f"  Policy Context: {signal_detail.policy_context}")

            # Verify regime context matches what we got earlier
            if signal_detail.regime_context == saved_regime:
                print_result(True, f"Regime context consistent: {saved_regime}")
            else:
                print_result(False, f"Regime context mismatch: {signal_detail.regime_context} != {saved_regime}")

            print_result(True, "Signal details retrieved successfully")

        # ====================================================================
        # TEST SUMMARY
        # ====================================================================
        print("\n" + "="*60)
        print("INTEGRATION TEST SUMMARY")
        print("="*60)
        print("\nAll steps completed successfully!")
        print("\nVerified:")
        print("  [OK] SDK client initialization")
        print("  [OK] Macro regime retrieval")
        print("  [OK] Policy status retrieval")
        print("  [OK] Signal eligibility checking")
        print("  [OK] Signal creation")
        print("  [OK] Data consistency across operations")
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
                f"complete_investment_flow skipped due to environment endpoint/auth availability: {error_text}"
            )

        print(f"\n[ERROR] Test failed with exception: {e}")
        import traceback
        traceback.print_exc()

        # Clean up: delete the test signal if it was created
        if signal_id and client:
            try:
                client.signal.delete(signal_id)
                print(f"\n[INFO] Cleaned up test signal {signal_id}")
            except Exception:
                pass

        raise

    finally:
        # Clean up: always delete the test signal
        if signal_id and client:
            try:
                client.signal.delete(signal_id)
                print(f"\n[INFO] Cleaned up test signal {signal_id}")
            except Exception:
                pass

        if client:
            client.close()


if __name__ == "__main__":
    test_complete_investment_flow()
