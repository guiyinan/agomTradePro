"""
Performance test fixtures.

Pre-populates the database with large-scale test data for latency benchmarking.
"""

import json
import math
from datetime import date, timedelta
from pathlib import Path

import pytest

FIXTURES_DIR = Path(__file__).resolve().parent.parent / "fixtures"


@pytest.fixture
def large_macro_dataset(db):
    """Create 1000+ macro data points across multiple indicators."""
    from apps.macro.infrastructure.models import MacroIndicator

    indicators = []
    indicator_configs = [
        ("CN_PMI_MANUFACTURING", "指数", 50.0),
        ("CN_CPI_YOY", "%", 2.0),
        ("CN_M2_YOY", "%", 8.0),
        ("CN_PPI_YOY", "%", -1.0),
        ("CN_GDP_YOY", "%", 5.0),
        ("CN_INDUSTRIAL_PRODUCTION", "%", 6.0),
        ("CN_RETAIL_SALES_YOY", "%", 4.5),
        ("CN_FIXED_ASSET_INVESTMENT", "%", 3.0),
        ("US_CPI_YOY", "%", 3.5),
        ("US_PMI_MANUFACTURING", "指数", 51.0),
    ]

    for code, unit, base_value in indicator_configs:
        # Generate 120 months of data (10 years)
        for i in range(120):
            data_date = date(2015, 1, 1) + timedelta(days=30 * i)
            # Sine-wave variation for realistic-looking data
            variation = math.sin(i * 0.3) * 2.0
            value = base_value + variation

            MacroIndicator.objects.get_or_create(
                code=code,
                reporting_period=data_date,
                defaults={
                    "value": round(value, 2),
                    "unit": unit,
                    "source": "fixture",
                    "period_type": "M",
                },
            )

        indicators.append(code)

    return indicators


@pytest.fixture
def large_signal_dataset(db):
    """Create 500+ investment signals."""
    from apps.signal.infrastructure.models import InvestmentSignalModel

    signals = []
    for i in range(500):
        signal = InvestmentSignalModel.objects.create(
            asset_code=f"{(i % 50) + 1:06d}.{'SH' if i % 2 == 0 else 'SZ'}",
            asset_class="a_share",
            direction="LONG",
            logic_desc=f"Test signal {i}: momentum breakout",
            invalidation_description=f"Price drops below support level {i}",
            invalidation_threshold=float(i % 100),
            status="approved" if i % 3 != 0 else "pending",
        )
        signals.append(signal)

    return signals
