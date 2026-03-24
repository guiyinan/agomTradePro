import pytest
from datetime import date
from unittest.mock import patch, MagicMock
from apps.macro.infrastructure.adapters.fetchers.financial_fetchers import FinancialIndicatorFetcher
from apps.macro.infrastructure.adapters.base import MacroDataPoint

def dummy_validate(code, val, date_val, freq, unit):
    # Depending on the version, sometimes we just don't even need to mock validate like this if dummy_validate ignores arguments
    pass

def dummy_dedup(points):
    return points

def test_fetch_dr007_success():
    ak_mock = MagicMock()
    # attach repo_rate_hist to our mock, so hasattr passes
    ak_mock.repo_rate_hist = MagicMock()
    
    fetcher = FinancialIndicatorFetcher(ak_mock, "akshare", lambda x: None, dummy_dedup)
    
    with patch.object(ak_mock, "repo_rate_hist", create=True) as mock_repo_rate:
        # Mock normal akshare response using real DataFrame
        import pandas as pd
        mock_repo_rate.return_value = pd.DataFrame([
            {"date": "2024-01-01", "DR007": 0.0185}
        ])
        
        indicators = fetcher.fetch_dr007(date(2024, 1, 1), date(2024, 1, 31))
        assert len(indicators) == 1
        assert indicators[0].code == "CN_DR007"
        assert indicators[0].value == 0.0185

def test_fetch_pboc_open_market_success():
    ak_mock = MagicMock()
    # attach macro_china_pboc_open_market so hasattr passes
    ak_mock.macro_china_pboc_open_market = MagicMock()
    fetcher = FinancialIndicatorFetcher(ak_mock, "akshare", lambda x: None, dummy_dedup)
    
    with patch.object(ak_mock, "macro_china_pboc_open_market", create=True) as mock_pboc:
        # Mock pboc data using real DataFrame
        import pandas as pd
        mock_pboc.return_value = pd.DataFrame([
            {"日期": "2024-01-01", "净投放": "1500亿"}
        ])
        
        indicators = fetcher.fetch_pboc_open_market(date(2024, 1, 1), date(2024, 1, 31))
        assert len(indicators) == 1
        assert indicators[0].code == "CN_PBOC_NET_INJECTION"
        assert indicators[0].value == 1500.0
