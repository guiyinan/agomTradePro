from datetime import date
from types import SimpleNamespace

import pytest

from apps.alpha.application.ops_locks import (
    build_dashboard_alpha_refresh_lock_key,
    build_inference_batch_lock_key,
    build_qlib_data_refresh_lock_key,
    release_dashboard_alpha_refresh_lock,
    release_inference_batch_lock,
    release_qlib_data_refresh_lock,
)
from apps.alpha.application.ops_use_cases import (
    TriggerGeneralInferenceUseCase,
    TriggerQlibScopedCodesRefreshUseCase,
    TriggerQlibUniverseRefreshUseCase,
    TriggerScopedBatchInferenceUseCase,
    TriggerScopedInferenceUseCase,
)
from apps.task_monitor.application.repository_provider import get_task_record_repository
from apps.task_monitor.domain.entities import TaskStatus


@pytest.mark.django_db
def test_trigger_general_inference_use_case_queues_qlib_task(monkeypatch):
    captured = {}

    class FakeTask:
        id = "task-general-1"

    class FakeDelayWrapper:
        @staticmethod
        def delay(universe_id: str, intended_trade_date: str, top_n: int):
            captured["universe_id"] = universe_id
            captured["trade_date"] = intended_trade_date
            captured["top_n"] = top_n
            return FakeTask()

    monkeypatch.setattr("apps.alpha.application.tasks.qlib_predict_scores", FakeDelayWrapper)

    payload = TriggerGeneralInferenceUseCase().execute(
        trade_date=date(2026, 4, 28),
        top_n=20,
        universe_id="csi300",
    )

    release_dashboard_alpha_refresh_lock(
        build_dashboard_alpha_refresh_lock_key(
            alpha_scope="general",
            target_date=date(2026, 4, 28),
            top_n=20,
            raw_universe_id="csi300",
        )
    )
    assert payload["success"] is True
    assert payload["task_id"] == "task-general-1"
    assert captured["universe_id"] == "csi300"
    assert captured["trade_date"] == "2026-04-28"
    assert captured["top_n"] == 20


@pytest.mark.django_db
def test_trigger_scoped_inference_use_case_passes_scope_payload(monkeypatch):
    captured = {}

    class FakeTask:
        id = "task-scoped-1"

    class FakeDelayWrapper:
        @staticmethod
        def delay(universe_id: str, intended_trade_date: str, top_n: int, scope_payload=None):
            captured["universe_id"] = universe_id
            captured["trade_date"] = intended_trade_date
            captured["top_n"] = top_n
            captured["scope_payload"] = scope_payload
            return FakeTask()

    class FakeResolver:
        def resolve(self, *, user_id: int, trade_date: date, portfolio_id: int | None = None, pool_mode: str | None = None):
            return SimpleNamespace(
                portfolio_id=portfolio_id,
                portfolio_name="测试组合",
                scope=SimpleNamespace(
                    universe_id="portfolio-9-scope",
                    scope_hash="scope-9",
                    pool_mode=pool_mode,
                    display_label="测试组合 · Scoped Alpha 池",
                    to_dict=lambda: {
                        "portfolio_id": portfolio_id,
                        "pool_mode": pool_mode,
                        "trade_date": trade_date.isoformat(),
                        "instrument_codes": ["000001.SZ"],
                    },
                ),
            )

    monkeypatch.setattr("apps.alpha.application.tasks.qlib_predict_scores", FakeDelayWrapper)
    monkeypatch.setattr("apps.alpha.application.ops_use_cases.PortfolioAlphaPoolResolver", FakeResolver)

    payload = TriggerScopedInferenceUseCase().execute(
        actor_user_id=7,
        trade_date=date(2026, 4, 28),
        top_n=15,
        portfolio_id=9,
        pool_mode="price_covered",
    )

    release_dashboard_alpha_refresh_lock(
        build_dashboard_alpha_refresh_lock_key(
            alpha_scope="portfolio",
            target_date=date(2026, 4, 28),
            top_n=15,
            raw_universe_id="portfolio-9-scope",
            scope_hash="scope-9",
        )
    )
    assert payload["success"] is True
    assert captured["universe_id"] == "portfolio-9-scope"
    assert captured["scope_payload"]["portfolio_id"] == 9
    assert captured["scope_payload"]["pool_mode"] == "price_covered"


@pytest.mark.django_db
def test_trigger_scoped_batch_inference_use_case_queues_batch_task(monkeypatch):
    captured = {}

    class FakeTask:
        id = "task-batch-1"

    class FakeDelayWrapper:
        @staticmethod
        def delay(**kwargs):
            captured.update(kwargs)
            return FakeTask()

    monkeypatch.setattr("apps.alpha.application.tasks.qlib_daily_scoped_inference", FakeDelayWrapper)

    payload = TriggerScopedBatchInferenceUseCase().execute(top_n=25, pool_mode="market")

    release_inference_batch_lock(
        build_inference_batch_lock_key(
            mode="daily_scoped_batch",
            target_date=date.today(),
            top_n=25,
            descriptor="market:0",
        )
    )
    assert payload["success"] is True
    assert payload["task_id"] == "task-batch-1"
    assert captured["top_n"] == 25
    assert captured["pool_mode"] == "market"


@pytest.mark.django_db
def test_trigger_qlib_universe_refresh_use_case_queues_refresh_task(monkeypatch):
    captured = {}

    class FakeTask:
        id = "task-refresh-1"

    class FakeDelayWrapper:
        @staticmethod
        def delay(**kwargs):
            captured.update(kwargs)
            return FakeTask()

    monkeypatch.setattr("apps.alpha.application.tasks.qlib_refresh_runtime_data_task", FakeDelayWrapper)

    payload = TriggerQlibUniverseRefreshUseCase().execute(
        target_date=date(2026, 4, 28),
        lookback_days=420,
        universes=["csi300", "csi500"],
    )

    release_qlib_data_refresh_lock(
        build_qlib_data_refresh_lock_key(
            mode="universes",
            target_date=date(2026, 4, 28),
            lookback_days=420,
            descriptor="csi300,csi500",
        )
    )
    assert payload["success"] is True
    assert payload["task_id"] == "task-refresh-1"
    assert captured["target_date"] == "2026-04-28"
    assert captured["lookback_days"] == 420
    assert captured["universes"] == ["csi300", "csi500"]
    record = get_task_record_repository().get_by_task_id("task-refresh-1")
    assert record is not None
    assert record.task_name == "apps.alpha.application.tasks.qlib_refresh_runtime_data_task"
    assert record.status == TaskStatus.PENDING
    assert record.kwargs["target_date"] == "2026-04-28"
    assert record.kwargs["universes"] == ["csi300", "csi500"]
    assert record.kwargs["lookback_days"] == 420


@pytest.mark.django_db
def test_trigger_qlib_scoped_codes_refresh_use_case_queues_refresh_task(monkeypatch):
    captured = {}

    class FakeTask:
        id = "task-refresh-codes-1"

    class FakeDelayWrapper:
        @staticmethod
        def delay(**kwargs):
            captured.update(kwargs)
            return FakeTask()

    monkeypatch.setattr(
        "apps.alpha.application.tasks.qlib_refresh_runtime_data_for_codes_task",
        FakeDelayWrapper,
    )

    payload = TriggerQlibScopedCodesRefreshUseCase().execute(
        target_date=date(2026, 4, 28),
        lookback_days=150,
        portfolio_ids=[12, 18],
        all_active_portfolios=False,
        pool_mode="price_covered",
    )

    release_qlib_data_refresh_lock(
        build_qlib_data_refresh_lock_key(
            mode="scoped_codes",
            target_date=date(2026, 4, 28),
            lookback_days=150,
            descriptor="12,18:price_covered",
        )
    )
    assert payload["success"] is True
    assert payload["task_id"] == "task-refresh-codes-1"
    assert captured["target_date"] == "2026-04-28"
    assert captured["portfolio_ids"] == [12, 18]
    assert captured["all_active_portfolios"] is False
    assert captured["pool_mode"] == "price_covered"
    record = get_task_record_repository().get_by_task_id("task-refresh-codes-1")
    assert record is not None
    assert record.task_name == "apps.alpha.application.tasks.qlib_refresh_runtime_data_for_codes_task"
    assert record.status == TaskStatus.PENDING
    assert record.kwargs["target_date"] == "2026-04-28"
    assert record.kwargs["portfolio_ids"] == [12, 18]
    assert record.kwargs["all_active_portfolios"] is False
    assert record.kwargs["pool_mode"] == "price_covered"
