from datetime import date
from unittest.mock import patch

from apps.data_center.domain.entities import ProviderConfig
from apps.data_center.infrastructure.connection_tester import run_connection_test
from apps.macro.infrastructure.adapters.base import MacroDataPoint


def _tushare_config() -> ProviderConfig:
    return ProviderConfig(
        id=1,
        name="Tushare Pro",
        source_type="tushare",
        is_active=True,
        priority=1,
        api_key="token-123",
        api_secret="",
        http_url="https://proxy.example.com",
        api_endpoint="",
        extra_config={},
        description="",
    )


def test_run_connection_test_tushare_uses_adapter_fetch_to_validate_parse_path():
    with patch(
        "apps.macro.infrastructure.adapters.tushare_adapter.TushareAdapter.fetch",
        return_value=[
            MacroDataPoint(
                code="SHIBOR",
                value=1.338,
                observed_at=date(2026, 4, 3),
                published_at=date(2026, 4, 3),
                source="tushare",
            )
        ],
    ) as fetch_mock:
        result = run_connection_test(_tushare_config())

    fetch_mock.assert_called_once()
    assert result.success is True
    assert "1 rows" in result.summary
    assert any("SHIBOR" in line for line in result.logs)
