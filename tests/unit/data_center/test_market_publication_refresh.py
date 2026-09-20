"""Full-market snapshots must never publish an intermediate or failed batch."""

from datetime import date

import pytest

from apps.data_center.application.market_publication_refresh import (
    MarketPublicationRefreshPorts,
    refresh_market_price_inputs,
    refresh_market_publications,
)
from core.exceptions import DataFetchError


def run(*, quote_count=None, publish_error=False, empty=False):
    published = []

    def publish(codes):
        if publish_error:
            raise ValueError("missing policy evidence")
        published.append(codes)
        return len(codes) * 2

    ports = MarketPublicationRefreshPorts(
        list_codes=lambda: [] if empty else ["000001.SZ", "000002.SZ", "000003.SZ"],
        sync_quotes=lambda codes: len(codes) if quote_count is None else quote_count,
        sync_valuations=lambda codes, day: len(codes),
        publish=publish,
    )
    return (
        refresh_market_publications(ports=ports, as_of_date=date(2026, 9, 18), batch_size=2),
        published,
    )


def test_complete_market_refresh_publishes_full_scope_once():
    result, published = run()
    assert result["outcome"] == "success"
    assert result["requested"] == result["succeeded"] == 5
    assert result["failed"] == 0
    assert result["stored"] == result["published_members"] == 6
    assert published == [["000001.SZ", "000002.SZ", "000003.SZ"]]


def test_partial_market_refresh_keeps_previous_publication():
    result, published = run(quote_count=0)
    assert result["outcome"] == "partial"
    assert result["requested"] == result["succeeded"] + result["failed"]
    assert result["published_members"] == 0
    assert published == []


def test_publication_evidence_failure_is_not_success():
    result, published = run(publish_error=True)
    assert result["outcome"] == "partial"
    assert result["failed"] == 1
    assert published == []


def test_empty_scope_is_not_success():
    result, published = run(empty=True)
    assert result["outcome"] == "failed"
    assert result["stored"] == 0
    assert published == []


@pytest.mark.parametrize("batch_size", [True, 0, 201, "10"])
def test_market_refresh_rejects_invalid_input_before_io(batch_size):
    ports = MarketPublicationRefreshPorts(
        list_codes=lambda: pytest.fail("unexpected IO"),
        sync_quotes=lambda _: 0,
        sync_valuations=lambda *_: 0,
        publish=lambda _: 0,
    )
    with pytest.raises(ValueError):
        refresh_market_publications(
            ports=ports, as_of_date=date(2026, 9, 18), batch_size=batch_size
        )


@pytest.mark.parametrize("kwargs", [{"batch_size": True}, {"batch_size": 0}, {"source": "bad"}])
def test_task_invalid_input_returns_failure_without_provider_access(monkeypatch, kwargs):
    from apps.data_center.application import tasks

    monkeypatch.setattr(
        tasks, "get_active_provider_id_by_source", lambda _: pytest.fail("provider IO")
    )
    result = tasks.refresh_full_market_publications_task.run(**kwargs)
    assert result["outcome"] == "failed"
    assert result["stored"] == 0


def test_task_calendar_unavailable_is_blocked(monkeypatch):
    from types import SimpleNamespace

    from apps.data_center.application import tasks

    monkeypatch.setattr(tasks, "get_active_provider_id_by_source", lambda _: 3)
    monkeypatch.setattr(tasks, "latest_completed_cn_market_session", lambda _: None)
    monkeypatch.setattr(tasks, "make_backfill_sync_quote_use_case", lambda: SimpleNamespace())
    monkeypatch.setattr(
        tasks, "make_backfill_sync_current_valuation_batch_use_case", lambda: SimpleNamespace()
    )
    monkeypatch.setattr(
        tasks, "make_core_current_publication_rebuild_use_case", lambda **_: SimpleNamespace()
    )
    result = tasks.refresh_full_market_publications_task.run()
    assert result["outcome"] == "blocked"
    assert result["stored"] == 0


def test_audit_configuration_blocks_before_market_fetch(monkeypatch):
    from apps.audit.application.system_audit_composition import SystemAuditCompositionUnavailable
    from apps.data_center.application import tasks

    monkeypatch.setattr(tasks, "get_active_provider_id_by_source", lambda _: 3)

    def unavailable():
        raise SystemAuditCompositionUnavailable("unavailable", reason_code="audit_runtime_disabled")

    monkeypatch.setattr(tasks, "make_backfill_sync_quote_use_case", unavailable)
    monkeypatch.setattr(
        tasks,
        "make_backfill_sync_current_valuation_batch_use_case",
        lambda: pytest.fail("unexpected valuation fetch"),
    )
    result = tasks.refresh_full_market_publications_task.run()
    assert result["outcome"] == "blocked"
    assert result["blocked_reason"] == "system_audit_audit_runtime_disabled"
    assert result["stored"] == 0


def test_task_does_not_publish_stale_quotes_even_when_all_rows_were_stored(monkeypatch):
    from datetime import UTC, datetime
    from types import SimpleNamespace

    from apps.data_center.application import tasks

    monkeypatch.setattr(tasks, "get_active_provider_id_by_source", lambda _: 3)
    monkeypatch.setattr(tasks, "latest_completed_cn_market_session", lambda _: date(2026, 9, 18))
    monkeypatch.setattr(tasks, "list_active_stock_codes_for_backfill", lambda: ["000001.SZ"])
    sync = SimpleNamespace(execute=lambda *_, **kwargs: SimpleNamespace(stored_count=1))
    monkeypatch.setattr(tasks, "make_backfill_sync_quote_use_case", lambda: sync)
    monkeypatch.setattr(tasks, "make_backfill_sync_current_valuation_batch_use_case", lambda: sync)
    preview = SimpleNamespace(
        ready=True,
        datasets=[
            SimpleNamespace(
                dataset_key="equity.quote.snapshot",
                ready=True,
                oldest_observed_at=datetime(2026, 9, 17, 7, tzinfo=UTC),
                newest_observed_at=datetime(2026, 9, 17, 7, tzinfo=UTC),
            )
        ],
    )
    monkeypatch.setattr(
        tasks,
        "make_core_current_publication_rebuild_use_case",
        lambda **_: SimpleNamespace(
            preview=lambda **_: preview, execute=lambda **_: pytest.fail("published stale scope")
        ),
    )
    result = tasks.refresh_full_market_publications_task.run()
    assert result["outcome"] == "partial"
    assert result["published_members"] == 0


def test_market_dataset_selection_retains_default_financial_rebuild():
    from apps.data_center.composition import make_core_current_publication_rebuild_use_case

    default = make_core_current_publication_rebuild_use_case()
    assert len(default._rebuilders) == 4
    selected = make_core_current_publication_rebuild_use_case(
        dataset_keys=("equity.quote.snapshot", "equity.valuation.fact")
    )
    assert {item.dataset.dataset_key for item in selected._rebuilders} == {
        "equity.quote.snapshot",
        "equity.valuation.fact",
    }
    for keys in [(), ("bad",), ("equity.price.bar", "equity.price.bar")]:
        with pytest.raises(ValueError):
            make_core_current_publication_rebuild_use_case(dataset_keys=keys)


@pytest.mark.parametrize("reason", ["MODEL_MARKET_STALE", "MODEL_MARKET_SOURCE_CONFLICT"])
def test_price_stage_never_publishes_stale_or_conflicting_existing_facts(reason):
    from types import SimpleNamespace

    def fail(*args):
        raise DataFetchError("invalid", code=reason)

    with pytest.raises(DataFetchError) as caught:
        refresh_market_price_inputs(
            SimpleNamespace(stock_history=fail), ["000001.SZ"], date(2026, 9, 18)
        )
    assert caught.value.code == reason


@pytest.mark.parametrize("evidence_date", ["2026-09-18", "2026-09-17"])
def test_price_stage_requires_target_bound_suspension_evidence(evidence_date):
    from types import SimpleNamespace

    def read(code, start, end):
        if code == "000001.SZ":
            return [SimpleNamespace(trade_date=end)]
        raise DataFetchError(
            "suspended",
            code="MODEL_MARKET_SUSPENDED",
            details={"asset_code": code, "suspended_through": evidence_date},
        )

    port = SimpleNamespace(stock_history=read)
    if evidence_date == "2026-09-18":
        assert refresh_market_price_inputs(port, ["000001.SZ", "000016.SZ"], date(2026, 9, 18)) == (
            "000016.SZ",
        )
    else:
        with pytest.raises(DataFetchError):
            refresh_market_price_inputs(port, ["000016.SZ"], date(2026, 9, 18))


def test_task_repairs_missing_price_scope_before_final_publication(monkeypatch):
    from datetime import UTC, datetime
    from types import SimpleNamespace

    from apps.data_center.application import market_publication_refresh, public, tasks

    events = []
    monkeypatch.setattr(tasks, "get_active_provider_id_by_source", lambda _: 3)
    monkeypatch.setattr(tasks, "latest_completed_cn_market_session", lambda _: date(2026, 9, 18))
    monkeypatch.setattr(tasks, "list_active_stock_codes_for_backfill", lambda: ["000001.SZ"])
    sync = SimpleNamespace(execute=lambda *_, **kwargs: SimpleNamespace(stored_count=1))
    monkeypatch.setattr(tasks, "make_backfill_sync_quote_use_case", lambda: sync)
    monkeypatch.setattr(tasks, "make_backfill_sync_current_valuation_batch_use_case", lambda: sync)
    observed = datetime(2026, 9, 18, 7, tzinfo=UTC)
    datasets = [
        SimpleNamespace(
            dataset_key=key, ready=True, oldest_observed_at=observed, newest_observed_at=observed
        )
        for key in ("equity.quote.snapshot", "equity.valuation.fact")
    ]
    datasets.append(SimpleNamespace(dataset_key="equity.price.bar", ready=False))
    monkeypatch.setattr(
        tasks,
        "make_core_current_publication_rebuild_use_case",
        lambda **_: SimpleNamespace(
            preview=lambda **_: SimpleNamespace(ready=False, datasets=datasets),
            execute=lambda **_: (events.append("publish") or SimpleNamespace(published_count=3)),
        ),
    )
    monkeypatch.setattr(public, "get_model_market_data_port", lambda: object())
    monkeypatch.setattr(
        market_publication_refresh,
        "refresh_market_price_inputs",
        lambda *_: (events.append("refresh_prices") or ()),
    )
    result = tasks.refresh_full_market_publications_task.run()
    assert events == ["refresh_prices", "publish"]
    assert result["outcome"] == "success"
    assert result["price_scope_verified"] == 1
