"""Business outcomes and exact alias delegation for Alpha monitoring tasks."""

from __future__ import annotations

from datetime import date
from types import SimpleNamespace
from typing import Any

import pytest

from apps.alpha.application import monitoring_tasks


def _metrics() -> SimpleNamespace:
    return SimpleNamespace(
        registry=SimpleNamespace(set_gauge=lambda *_args, **_kwargs: None),
        log_metrics=lambda: None,
        record_coverage=lambda *_args, **_kwargs: None,
        record_ic_metrics=lambda *_args, **_kwargs: None,
        record_queue_lag=lambda *_args, **_kwargs: None,
        get_metrics_json=lambda: {"healthy": True},
    )


def test_evaluate_alerts_reports_success_and_complete_failure(monkeypatch) -> None:
    """Alert presence is a successful evaluation; owner failure is a failed task."""
    monkeypatch.setattr(
        monitoring_tasks,
        "get_alpha_runtime_alert_manager",
        lambda: SimpleNamespace(evaluate_all=lambda: ["drift"]),
    )
    result = monitoring_tasks.evaluate_alerts.run()
    assert result["outcome"] == "success"
    assert result["success"] is True
    assert (result["requested"], result["succeeded"], result["failed"], result["stored"]) == (
        1,
        1,
        0,
        0,
    )

    monkeypatch.setattr(
        monitoring_tasks,
        "get_alpha_runtime_alert_manager",
        lambda: (_ for _ in ()).throw(RuntimeError("alert owner unavailable")),
    )
    failed = monitoring_tasks.evaluate_alerts.run()
    assert failed["outcome"] == "failed"
    assert failed["success"] is False


def test_update_provider_metrics_reports_success_and_complete_failure(monkeypatch) -> None:
    """Provider metric collection exposes both completed work and owner failure."""
    monkeypatch.setattr(monitoring_tasks, "get_alpha_metrics", _metrics)
    monkeypatch.setattr(
        monitoring_tasks,
        "_cache_repository",
        SimpleNamespace(
            list_recent_provider_caches=lambda **_kwargs: [],
            get_latest_cache_for_universe=lambda **_kwargs: None,
        ),
    )
    result = monitoring_tasks.update_provider_metrics.run()
    assert result["outcome"] == "success"
    assert result["requested"] == result["succeeded"] == 4
    assert result["failed"] == result["stored"] == 0

    monkeypatch.setattr(
        monitoring_tasks,
        "_cache_repository",
        SimpleNamespace(
            list_recent_provider_caches=lambda **_kwargs: (_ for _ in ()).throw(
                RuntimeError("cache unavailable")
            )
        ),
    )
    failed = monitoring_tasks.update_provider_metrics.run()
    assert failed["outcome"] == "failed"
    assert failed["success"] is False


def test_calculate_ic_drift_reports_blocked_success_and_failure(monkeypatch) -> None:
    """Missing evidence blocks drift while valid evidence records one result."""
    monkeypatch.setattr(monitoring_tasks, "get_alpha_metrics", _metrics)
    monkeypatch.setattr(
        monitoring_tasks,
        "_registry_repository",
        SimpleNamespace(get_active_model=lambda: None),
    )
    blocked = monitoring_tasks.calculate_ic_drift.run()
    assert blocked["outcome"] == "blocked"
    assert blocked["success"] is False

    caches = [
        SimpleNamespace(
            universe_id="csi300",
            intended_trade_date=date(2026, 7, index + 1),
        )
        for index in range(20)
    ]
    monkeypatch.setattr(
        monitoring_tasks,
        "_registry_repository",
        SimpleNamespace(get_active_model=lambda: SimpleNamespace(artifact_hash="hash")),
    )
    monkeypatch.setattr(
        monitoring_tasks,
        "_cache_repository",
        SimpleNamespace(list_caches_for_model=lambda **_kwargs: caches),
    )
    monkeypatch.setattr(
        monitoring_tasks,
        "calculate_rolling_metrics",
        lambda **_kwargs: [SimpleNamespace(ic=0.1 + index / 100) for index in range(20)],
    )
    result = monitoring_tasks.calculate_ic_drift.run()
    assert result["outcome"] == "success"
    assert result["stored"] == 1

    monkeypatch.setattr(
        monitoring_tasks,
        "_registry_repository",
        SimpleNamespace(
            get_active_model=lambda: (_ for _ in ()).throw(RuntimeError("registry unavailable"))
        ),
    )
    failed = monitoring_tasks.calculate_ic_drift.run()
    assert failed["outcome"] == "failed"


def test_check_queue_lag_reports_blocked_success_and_failure(monkeypatch) -> None:
    """No worker evidence blocks; a thrown inspect call is a complete failure."""
    monkeypatch.setattr(monitoring_tasks, "get_alpha_metrics", _metrics)
    monkeypatch.setattr(
        monitoring_tasks,
        "current_app",
        SimpleNamespace(
            control=SimpleNamespace(
                inspect=lambda: SimpleNamespace(reserved=lambda: None),
            )
        ),
    )
    blocked = monitoring_tasks.check_queue_lag.run()
    assert blocked["outcome"] == "blocked"
    assert blocked["success"] is False

    monkeypatch.setattr(
        monitoring_tasks,
        "current_app",
        SimpleNamespace(
            control=SimpleNamespace(
                inspect=lambda: SimpleNamespace(
                    reserved=lambda: {"worker": [{"delivery_info": {"routing_key": "qlib_infer"}}]}
                )
            )
        ),
    )
    result = monitoring_tasks.check_queue_lag.run()
    assert result["outcome"] == "success"
    assert result["stored"] == 2

    monkeypatch.setattr(
        monitoring_tasks,
        "current_app",
        SimpleNamespace(
            control=SimpleNamespace(
                inspect=lambda: (_ for _ in ()).throw(RuntimeError("inspect failed"))
            )
        ),
    )
    failed = monitoring_tasks.check_queue_lag.run()
    assert failed["outcome"] == "failed"


def test_generate_daily_report_reports_success_and_complete_failure(monkeypatch) -> None:
    """Report generation publishes one completed request or one failed request."""
    monkeypatch.setattr(monitoring_tasks, "get_alpha_metrics", _metrics)
    monkeypatch.setattr(
        monitoring_tasks,
        "_cache_repository",
        SimpleNamespace(list_today_cache_rows=lambda _today: []),
    )
    monkeypatch.setattr(
        monitoring_tasks,
        "_registry_repository",
        SimpleNamespace(count_activations_on=lambda _today: 0),
    )
    result = monitoring_tasks.generate_daily_report.run()
    assert result["outcome"] == "success"
    assert result["requested"] == result["succeeded"] == 1
    assert result["failed"] == result["stored"] == 0

    monkeypatch.setattr(
        monitoring_tasks,
        "_cache_repository",
        SimpleNamespace(
            list_today_cache_rows=lambda _today: (_ for _ in ()).throw(
                RuntimeError("cache unavailable")
            )
        ),
    )
    failed = monitoring_tasks.generate_daily_report.run()
    assert failed["outcome"] == "failed"


def test_cleanup_old_metrics_reports_success_noop_and_complete_failure(monkeypatch) -> None:
    """Cleanup reports deleted/archived counts and never turns owner failure into success."""
    monkeypatch.setattr(
        monitoring_tasks,
        "_cache_repository",
        SimpleNamespace(
            archive_before=lambda _cutoff: {"archived_count": 3},
            cleanup_before=lambda _cutoff: 3,
        ),
    )
    result = monitoring_tasks.cleanup_old_metrics.run(30)
    assert result["outcome"] == "success"
    assert (result["requested"], result["succeeded"], result["failed"], result["stored"]) == (
        3,
        3,
        0,
        3,
    )

    monkeypatch.setattr(
        monitoring_tasks,
        "_cache_repository",
        SimpleNamespace(
            archive_before=lambda _cutoff: {"archived_count": 0},
            cleanup_before=lambda _cutoff: 0,
        ),
    )
    noop = monitoring_tasks.cleanup_old_metrics.run(30)
    assert noop["outcome"] == "noop"

    monkeypatch.setattr(
        monitoring_tasks,
        "_cache_repository",
        SimpleNamespace(
            archive_before=lambda _cutoff: (_ for _ in ()).throw(
                RuntimeError("archive unavailable")
            )
        ),
    )
    failed = monitoring_tasks.cleanup_old_metrics.run(30)
    assert failed["outcome"] == "failed"


@pytest.mark.parametrize(
    ("alias_name", "canonical_name", "kwargs"),
    [
        ("evaluate_alerts_legacy", "evaluate_alerts", {}),
        ("update_provider_metrics_legacy", "update_provider_metrics", {}),
        ("check_queue_lag_legacy", "check_queue_lag", {}),
        ("calculate_ic_drift_legacy", "calculate_ic_drift", {}),
        ("generate_daily_report_legacy", "generate_daily_report", {}),
        ("cleanup_old_metrics_legacy", "cleanup_old_metrics", {"days": 17}),
    ],
)
def test_monitoring_legacy_aliases_delegate_exactly_once(
    monkeypatch,
    alias_name: str,
    canonical_name: str,
    kwargs: dict[str, Any],
) -> None:
    """Each compatibility registration delegates once without owning business logic."""
    calls: list[dict[str, Any]] = []
    sentinel = {"outcome": "sentinel"}
    canonical = getattr(monitoring_tasks, canonical_name)
    monkeypatch.setattr(
        canonical,
        "run",
        lambda **actual: calls.append(actual) or sentinel,
    )

    result = getattr(monitoring_tasks, alias_name).run(**kwargs)

    assert result is sentinel
    assert calls == [kwargs]
