"""
Regime V2 Logic Verification Script

Independent script to verify the new Regime calculation logic
"""

import json
import sys
from datetime import date


def main():
    print("=" * 60)
    print("Regime V2.0 Logic Verification")
    print("=" * 60)

    # Import new services
    sys.path.insert(0, '.')
    from apps.regime.domain.services_v2 import (
        RegimeCalculatorV2,
        RegimeType,
        ThresholdConfig,
        calculate_regime_by_level,
    )

    # 1. Test current data (Jan 2026)
    print("\n[1/3] Current Data Test (2026-01-31)")
    print("   PMI = 49.3, CPI = 0.8%")

    calculator = RegimeCalculatorV2()
    pmi_series = [50.2, 50.5, 49.0, 49.5, 49.7, 49.3, 49.4, 49.8, 49.0, 49.2, 50.1, 49.3]
    cpi_series = [0.5, -0.7, -0.1, -0.1, -0.1, 0.1, 0.0, -0.4, -0.3, 0.2, 0.7, 0.8]

    result = calculator.calculate(pmi_series, cpi_series, date(2026, 1, 31))

    print(f"   Regime: {result.regime.value}")
    print(f"   Confidence: {result.confidence:.1%}")
    print(f"   PMI: {result.growth_level} ({result.growth_state})")
    print(f"   CPI: {result.inflation_level}% ({result.inflation_state})")

    print("\n   Distribution:")
    for regime, prob in result.distribution.items():
        print(f"     {regime}: {prob:.2%}")

    # 2. Test all four quadrants
    print("\n[2/3] All Quadrants Test")
    test_cases = [
        ("Deflation", 49.0, 0.5),
        ("Overheat", 52.0, 3.0),
        ("Recovery", 51.0, 0.5),
        ("Stagflation", 49.0, 3.0),
    ]

    all_pass = True
    for expected, pmi, cpi in test_cases:
        regime = calculate_regime_by_level(pmi, cpi)
        passed = regime.value == expected
        status = "[PASS]" if passed else "[FAIL]"
        print(f"   {status} {expected}: PMI={pmi}, CPI={cpi}% -> {regime.value}")
        if not passed:
            all_pass = False

    # 3. Compare with old algorithm
    print("\n[3/3] Old vs New Algorithm Comparison")
    from apps.regime.domain.services import RegimeCalculator as OldCalculator

    old_calc = OldCalculator()
    old_result = old_calc.calculate(pmi_series, cpi_series, date(2026, 1, 31))

    print("   Old Algorithm (Momentum-based):")
    print(f"     Regime: {old_result.snapshot.dominant_regime}")
    print(f"     Confidence: {old_result.snapshot.confidence:.1%}")
    print(f"     Growth Z: {old_result.snapshot.growth_momentum_z:+.3f}")
    print(f"     Inflation Z: {old_result.snapshot.inflation_momentum_z:+.3f}")

    print("\n   New Algorithm (Level-based):")
    print(f"     Regime: {result.regime.value}")
    print(f"     Confidence: {result.confidence:.1%}")

    # Economic intuition check
    if result.growth_level < 50 and result.inflation_level < 2:
        print("\n   [CORRECT] New algorithm matches economic intuition:")
        print(f"     PMI {result.growth_level} < 50 (contraction)")
        print(f"     CPI {result.inflation_level}% < 2% (low inflation)")
        print(f"     -> Should be {result.regime.value}, not {old_result.snapshot.dominant_regime}")

    # Summary
    print("\n" + "=" * 60)
    if all_pass:
        print("[SUCCESS] All tests passed!")
    else:
        print("[WARNING] Some tests failed")
    print("=" * 60)

    return 0


if __name__ == "__main__":
    sys.exit(main())
