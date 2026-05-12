"""
Pytest configuration for AgomTradePro SDK tests
"""

import os

import pytest


@pytest.fixture
def mock_config():
    """Mock configuration for testing"""
    prev_base_url = os.environ.get("AGOMTRADEPRO_BASE_URL")
    prev_token = os.environ.get("AGOMTRADEPRO_API_TOKEN")
    os.environ["AGOMTRADEPRO_BASE_URL"] = "http://localhost:8000"
    os.environ["AGOMTRADEPRO_API_TOKEN"] = "test_token"
    yield {
        "base_url": "http://localhost:8000",
        "api_token": "test_token",
    }
    if prev_base_url is None:
        os.environ.pop("AGOMTRADEPRO_BASE_URL", None)
    else:
        os.environ["AGOMTRADEPRO_BASE_URL"] = prev_base_url
    if prev_token is None:
        os.environ.pop("AGOMTRADEPRO_API_TOKEN", None)
    else:
        os.environ["AGOMTRADEPRO_API_TOKEN"] = prev_token


@pytest.fixture
def mock_client():
    """Mock AgomTradeProClient for testing"""
    from agomtradepro import AgomTradeProClient

    client = AgomTradeProClient(
        base_url="http://localhost:8000",
        api_token="test_token",
    )
    return client


@pytest.fixture
def mock_regime_response():
    """Mock regime API response"""
    return {
        "dominant_regime": "Recovery",
        "observed_at": "2024-01-15",
        "growth_level": "up",
        "inflation_level": "down",
        "growth_indicator": "PMI",
        "inflation_indicator": "CPI",
        "growth_value": 50.8,
        "inflation_value": 2.1,
        "confidence": 0.85,
    }


@pytest.fixture
def mock_signal_response():
    """Mock signal API response"""
    return {
        "id": 123,
        "asset_code": "000001.SH",
        "logic_desc": "PMI rising, economic recovery",
        "status": "approved",
        "created_at": "2024-01-15T10:30:00Z",
        "invalidation_logic": "PMI falls below 50",
        "invalidation_threshold": 49.5,
        "approved_at": "2024-01-15T11:00:00Z",
        "created_by": "test_user",
    }
