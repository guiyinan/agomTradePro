from datetime import date
from types import SimpleNamespace

from apps.backtest.application.use_cases import RunBacktestRequest, RunBacktestUseCase


def test_run_backtest_uses_audit_interface_service(monkeypatch):
    repository = SimpleNamespace()
    repository.create_backtest = lambda name, config: SimpleNamespace(id=42)
    repository.update_status_calls = []
    repository.save_result_calls = []

    def _update_status(backtest_id, status, error=None):
        repository.update_status_calls.append((backtest_id, status, error))

    def _save_result(backtest_id, result):
        repository.save_result_calls.append((backtest_id, result))

    repository.update_status = _update_status
    repository.save_result = _save_result

    engine_result = SimpleNamespace(
        warnings=[],
        to_summary_dict=lambda: {"total_return": 0.12},
    )
    audit_calls: list[tuple[int, object]] = []

    monkeypatch.setattr(
        "apps.backtest.application.use_cases.BacktestEngine",
        lambda **kwargs: SimpleNamespace(run=lambda: engine_result),
    )
    monkeypatch.setattr(
        "apps.backtest.application.use_cases.generate_attribution_report_for_backtest",
        lambda backtest_id, *, backtest_repository: (
            audit_calls.append((backtest_id, backtest_repository))
            or SimpleNamespace(success=True, report_id=99, error=None)
        ),
    )

    use_case = RunBacktestUseCase(
        repository=repository,
        get_regime_func=lambda _: None,
        get_asset_price_func=lambda *_: None,
    )

    response = use_case.execute(
        RunBacktestRequest(
            name="test",
            start_date=date(2026, 1, 1),
            end_date=date(2026, 1, 31),
            initial_capital=100000.0,
        )
    )

    assert response.status == "completed"
    assert response.audit_status == "success"
    assert response.audit_report_id == 99
    assert audit_calls == [(42, repository)]

