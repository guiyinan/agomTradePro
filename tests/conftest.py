"""
Pytest configuration and shared fixtures.
"""

import pytest
from datetime import date


@pytest.fixture
def sample_date():
    """Sample date for testing"""
    return date(2024, 1, 1)


@pytest.fixture
def sample_macro_data():
    """Sample macro indicator data"""
    from apps.macro.domain.entities import MacroIndicator

    return [
        MacroIndicator(
            code="CN_PMI_MANUFACTURING",
            value=50.1,
            observed_at=date(2024, 1, 1),
            source="test"
        ),
        MacroIndicator(
            code="CN_CPI_YOY",
            value=2.1,
            observed_at=date(2024, 1, 1),
            source="test"
        ),
    ]
