from apps.equity.application.use_cases import get_runtime_benchmark_code


class _FakeAccountConfigSummaryService:
    def get_runtime_benchmark_code(self, key: str, default: str = "") -> str:
        assert key == "equity_market_benchmark"
        return "000300.SH" or default


def test_equity_runtime_benchmark_lookup_uses_account_config_service(monkeypatch):
    monkeypatch.setattr(
        "apps.equity.application.use_cases.get_account_config_summary_service",
        lambda: _FakeAccountConfigSummaryService(),
    )

    assert get_runtime_benchmark_code("equity_market_benchmark") == "000300.SH"
