from core.celery import app


def test_canonical_and_compatibility_tasks_are_registered_with_celery() -> None:
    """Workers should register both canonical task names and legacy beat-compatible aliases."""
    app.loader.import_default_modules()

    expected_tasks = {
        "apps.regime.application.orchestration.sync_macro_then_refresh_regime",
        "apps.regime.application.orchestration.generate_daily_regime_signal",
        "apps.regime.application.orchestration.recalculate_regime_with_daily_signal",
        "apps.equity.application.tasks_valuation_sync.sync_validate_scan_equity_valuation_task",
        "apps.equity.application.tasks_valuation_sync.validate_equity_valuation_quality_task",
        "apps.equity.application.tasks.sync_financial_data_task",
        "apps.simulated_trading.application.tasks.update_position_prices_task",
        "apps.simulated_trading.application.tasks.send_performance_summary_task",
        "apps.simulated_trading.application.tasks.check_position_invalidation_task",
        "apps.simulated_trading.application.tasks.notify_invalidated_positions_task",
        "apps.alpha.application.tasks.qlib_daily_inference",
        "apps.alpha.application.tasks.qlib_refresh_cache",
    }

    for task_name in expected_tasks:
        assert task_name in app.tasks
