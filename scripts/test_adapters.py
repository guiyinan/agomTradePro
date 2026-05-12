"""
Test script for data adapters.

Quick validation that adapters are properly configured.
"""

import os
import sys
from datetime import date, timedelta

# Add project root to Python path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def test_adapter_imports():
    """Test that all adapters can be imported"""
    print("Testing adapter imports...")
    try:
        from apps.macro.infrastructure.adapters import (
            PUBLICATION_LAGS,
            AKShareAdapter,
            FailoverAdapter,
            MacroDataPoint,
            MultiSourceAdapter,
            TushareAdapter,
            create_default_adapter,
        )
        print("  [OK] All adapters imported successfully")
        return True
    except ImportError as e:
        print(f"  [FAIL] Import failed: {e}")
        return False


def test_publication_lags():
    """Test publication lag configuration"""
    print("\nTesting publication lag configuration...")
    from apps.macro.infrastructure.adapters import PUBLICATION_LAGS

    expected_indicators = ["CN_PMI", "CN_CPI", "SHIBOR", "000001.SH"]
    all_found = True
    for indicator in expected_indicators:
        if indicator in PUBLICATION_LAGS:
            lag = PUBLICATION_LAGS[indicator]
            print(f"  [OK] {indicator}: {lag.days} days - {lag.description}")
        else:
            print(f"  [FAIL] {indicator}: not found in PUBLICATION_LAGS")
            all_found = False
    return all_found


def test_data_point():
    """Test MacroDataPoint creation"""
    print("\nTesting MacroDataPoint creation...")
    from apps.macro.infrastructure.adapters import MacroDataPoint

    point = MacroDataPoint(
        code="CN_PMI",
        value=50.5,
        observed_at=date(2024, 1, 1),
        source="test"
    )

    print(f"  [OK] Created data point: {point.code} = {point.value} @ {point.observed_at}")
    print(f"  [OK] Published at: {point.published_at}")

    return True


def test_adapter_supports():
    """Test adapter support checks"""
    print("\nTesting adapter support checks...")

    # Mock adapter for testing
    from apps.macro.infrastructure.adapters.base import BaseMacroAdapter

    class TestAdapter(BaseMacroAdapter):
        source_name = "test"
        SUPPORTED_INDICATORS = {"CN_PMI", "CN_CPI"}

        def supports(self, indicator_code: str) -> bool:
            return indicator_code in self.SUPPORTED_INDICATORS

        def fetch(self, indicator_code, start_date, end_date):
            return []

    adapter = TestAdapter()

    tests = [
        ("CN_PMI", True),
        ("CN_CPI", True),
        ("SHIBOR", False),
    ]

    all_passed = True
    for code, expected in tests:
        result = adapter.supports(code)
        if result == expected:
            print(f"  [OK] {code}: supports={result} (expected={expected})")
        else:
            print(f"  [FAIL] {code}: supports={result} (expected={expected})")
            all_passed = False

    return all_passed


def test_failover_adapter():
    """Test FailoverAdapter creation"""
    print("\nTesting FailoverAdapter...")

    from apps.macro.infrastructure.adapters import BaseMacroAdapter, FailoverAdapter

    # Create mock adapters
    class MockAdapter(BaseMacroAdapter):
        def __init__(self, name, supports_result, fetch_result):
            self.source_name = name
            self._supports_result = supports_result
            self._fetch_result = fetch_result

        def supports(self, indicator_code):
            return self._supports_result

        def fetch(self, indicator_code, start_date, end_date):
            if self._fetch_result == "error":
                raise Exception("Mock error")
            return self._fetch_result

    primary = MockAdapter("primary", True, [])
    backup = MockAdapter("backup", True, [])

    failover = FailoverAdapter([primary, backup])
    print(f"  [OK] Created FailoverAdapter with {len(failover.adapters)} adapters")

    return True


def main():
    """Run all tests"""
    print("=" * 60)
    print("Data Adapter Tests")
    print("=" * 60)

    tests = [
        test_adapter_imports,
        test_publication_lags,
        test_data_point,
        test_adapter_supports,
        test_failover_adapter,
    ]

    results = []
    for test in tests:
        try:
            result = test()
            results.append(result)
        except Exception as e:
            print(f"\n  [FAIL] Test failed with exception: {e}")
            import traceback
            traceback.print_exc()
            results.append(False)

    print("\n" + "=" * 60)
    passed = sum(results)
    total = len(results)
    print(f"Results: {passed}/{total} tests passed")
    print("=" * 60)

    return all(results)


if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
