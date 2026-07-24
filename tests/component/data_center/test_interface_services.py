from datetime import date
from types import SimpleNamespace

import pytest

from apps.data_center.application.interface_services import fetch_latest_realtime_prices
from apps.task_monitor.application.repository_provider import get_task_record_repository
from apps.task_monitor.domain.entities import TaskStatus


def test_fetch_latest_realtime_prices_uses_core_bridge(monkeypatch):
    monkeypatch.setattr(
        "apps.data_center.application.interface_services.fetch_latest_prices",
        lambda asset_codes: [{"asset_code": code, "price": 9.87} for code in asset_codes],
    )

    assert fetch_latest_realtime_prices(["510300.SH"]) == [
        {"asset_code": "510300.SH", "price": 9.87}
    ]


@pytest.mark.django_db
def test_decision_repair_alpha_refresh_records_pending_task_immediately(monkeypatch):
    from apps.data_center.application import interface_services

    class FakeTask:
        id = "repair-alpha-1"

    monkeypatch.setattr(
        "django.core.management.call_command",
        lambda *args, **kwargs: None,
    )
    monkeypatch.setattr(
        "apps.data_center.application.interface_services.resolve_portfolio_alpha_scope",
        lambda user_id, portfolio_id, trade_date: SimpleNamespace(
            scope=SimpleNamespace(
                universe_id="portfolio-366-scope",
                scope_hash="scope-366",
                instrument_codes=("510300.SH",),
                to_dict=lambda: {
                    "universe_id": "portfolio-366-scope",
                    "scope_hash": "scope-366",
                    "instrument_codes": ["510300.SH"],
                },
            )
        ),
    )
    monkeypatch.setattr(
        "apps.data_center.application.interface_services._sync_scope_quotes",
        lambda asset_codes: {"status": "success", "synced": list(asset_codes)},
    )
    monkeypatch.setattr(
        "apps.data_center.application.interface_services.queue_alpha_score_prediction",
        lambda universe_id, trade_date, scope_payload: FakeTask(),
    )

    refresher = interface_services._build_alpha_refresher(SimpleNamespace(id=7))
    payload = refresher(date(2026, 4, 30), 366)

    assert payload["status"] == "queued"
    assert payload["task_id"] == "repair-alpha-1"

    record = get_task_record_repository().get_by_task_id("repair-alpha-1")
    assert record is not None
    assert record.status == TaskStatus.PENDING
    assert record.task_name == "apps.alpha.application.tasks.qlib_predict_scores"
    assert record.args == ("portfolio-366-scope", "2026-04-30", 30)
    assert record.kwargs["scope_payload"]["scope_hash"] == "scope-366"
