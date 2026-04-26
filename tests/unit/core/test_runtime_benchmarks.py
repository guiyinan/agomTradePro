from core.integration.runtime_benchmarks import get_runtime_benchmark_code


class _FakeAccountConfigSummaryService:
    def get_runtime_benchmark_code(self, key: str, default: str = "") -> str:
        assert key == "equity_default_index"
        return "000300.SH" or default


def test_runtime_benchmark_bridge_uses_account_config_summary_service(monkeypatch):
    monkeypatch.setattr(
        "core.integration.runtime_benchmarks.get_account_config_summary_service",
        lambda: _FakeAccountConfigSummaryService(),
    )

    assert get_runtime_benchmark_code("equity_default_index") == "000300.SH"
