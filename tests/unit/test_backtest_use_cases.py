from datetime import date
from types import SimpleNamespace

from apps.backtest.application.use_cases import RunBacktestRequest, RunBacktestUseCase


class _PITView:
    def query(self, dataset, as_of_time, knowledge_scope, filters):  # type: ignore[no-untyped-def]
        return []


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


def test_pit_verified_backtest_fails_closed_without_decision_snapshot_reader() -> None:
    repository = SimpleNamespace(
        create_backtest=lambda name, config: SimpleNamespace(id=7),
        update_status=lambda *args: None,
    )
    use_case = RunBacktestUseCase(
        repository=repository,
        get_regime_func=lambda _: None,
        get_asset_price_func=lambda *_: None,
        pit_data_view=_PITView(),
    )

    response = use_case.execute(
        RunBacktestRequest(
            name="trusted",
            start_date=date(2026, 1, 1),
            end_date=date(2026, 1, 31),
            initial_capital=100000.0,
            use_pit_data=True,
            trust_status="pit_verified",
            data_manifest_id="manifest-1",
            config_hash="a" * 64,
            code_commit="b" * 40,
            engine_version="engine-v1",
            research_trial_id="trial-1",
            decision_snapshot_id="snapshot-1",
        )
    )

    assert response.status == "failed"
    assert "decision snapshot reader" in response.errors[0]

