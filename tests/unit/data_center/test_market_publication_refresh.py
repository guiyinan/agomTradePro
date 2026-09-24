"""Full-market snapshots must never publish an intermediate or failed batch."""

from datetime import UTC, date, datetime, timedelta

import pytest

from apps.data_center.application.market_publication_refresh import (
    MarketPublicationRefreshPorts,
    refresh_market_price_inputs,
    refresh_market_publications,
)
from core.exceptions import DataFetchError


@pytest.fixture(autouse=True)
def _patch_current_authority(monkeypatch):
    """Bind task-path tests to one current server-issued authority."""

    from types import SimpleNamespace

    from apps.data_center.application import tasks

    context = SimpleNamespace(
        authority_source_id="config-center",
        actor_id="service:market-refresh",
        user_id=1,
        tenant_id="tenant:production",
        owner_id="owner:production",
        is_authenticated=True,
        is_staff=True,
        role="system_owner",
        authority_content_hash="b" * 64,
        authority_valid_until=datetime.now(UTC) + timedelta(hours=2),
    )
    monkeypatch.setattr(
        tasks,
        "preflight_data_reliability_audit_runtime",
        lambda **_: context,
    )
    monkeypatch.setattr(
        tasks,
        "sync_active_a_share_universe",
        lambda: {"active_count": 1, "touched_count": 1},
    )
    return context


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


def test_provider_identity_gap_is_a_partial_business_result() -> None:
    def reject_valuation(_codes, _day):
        from apps.data_center.application.batch_identity import ProviderAssetIdentityError

        raise ProviderAssetIdentityError("valuation provider asset identities mismatch")

    ports = MarketPublicationRefreshPorts(
        list_codes=lambda: ["000001.SZ", "000016.SZ"],
        sync_quotes=lambda codes: len(codes),
        sync_valuations=reject_valuation,
        publish=lambda _: pytest.fail("incomplete valuation scope reached publication"),
    )

    result = refresh_market_publications(
        ports=ports,
        as_of_date=date(2026, 9, 23),
        batch_size=2,
    )

    assert result["outcome"] == "partial"
    assert result["success"] is False
    assert result["stored"] == 2
    assert result["published_members"] == 0
    assert result["errors"] == [
        "PROVIDER_ASSET_IDENTITY_MISMATCH",
        "market_publication_skipped_incomplete_refresh",
    ]


def test_publication_evidence_failure_is_not_success():
    result, published = run(publish_error=True)
    assert result["outcome"] == "partial"
    assert result["failed"] == 1
    assert result["error_code"] == "MARKET_PUBLICATION_VALIDATION_FAILED"
    assert result["blocked_reason"] == "MARKET_PUBLICATION_VALIDATION_FAILED"
    assert result["errors"] == ["MARKET_PUBLICATION_VALIDATION_FAILED"]
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


@pytest.mark.parametrize(
    "kwargs",
    [
        {"batch_size": True},
        {"batch_size": 0},
        {"source": "bad"},
        {"quote_source": "bad"},
        {"valuation_source": "bad"},
    ],
)
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
    monkeypatch.setattr(tasks, "latest_closed_cn_market_session", lambda _: None)
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


def test_task_blocks_without_current_authority_before_provider_access(monkeypatch):
    """Scheduled market writes require the canonical current Audit authority."""

    from apps.audit.application.system_audit_composition import SystemAuditCompositionUnavailable
    from apps.data_center.application import tasks

    def unavailable(**_):
        raise SystemAuditCompositionUnavailable(
            "unavailable",
            reason_code="authority_unavailable",
        )

    monkeypatch.setattr(tasks, "preflight_data_reliability_audit_runtime", unavailable)
    provider = monkeypatch.setattr(
        tasks,
        "get_active_provider_id_by_source",
        lambda _: pytest.fail("provider IO"),
    )

    result = tasks.refresh_full_market_publications_task.run()

    assert provider is None
    assert result["outcome"] == "blocked"
    assert result["blocked_reason"] == "system_audit_authority_unavailable"
    assert result["stored"] == 0


def test_task_blocks_authority_window_shorter_than_task_budget(
    monkeypatch,
    _patch_current_authority,
):
    """A scheduled refresh cannot outlive the authority used to start it."""

    from apps.data_center.application import tasks

    _patch_current_authority.authority_valid_until = datetime.now(UTC) + timedelta(minutes=10)
    monkeypatch.setattr(
        tasks,
        "get_active_provider_id_by_source",
        lambda _: pytest.fail("provider IO"),
    )

    result = tasks.refresh_full_market_publications_task.run()

    assert result["outcome"] == "blocked"
    assert result["blocked_reason"] == "authority_window_too_short"
    assert result["stored"] == 0


def test_task_stops_before_provider_when_authority_identity_changes(monkeypatch):
    """A scheduled batch must not continue under a different authority identity."""

    from types import SimpleNamespace

    from apps.data_center.application import tasks

    initial = SimpleNamespace(
        authority_source_id="config-center",
        actor_id="service:market-refresh",
        user_id=1,
        tenant_id="tenant:production",
        owner_id="owner:production",
        is_authenticated=True,
        is_staff=True,
        role="system_owner",
        authority_content_hash="b" * 64,
        authority_valid_until=datetime.now(UTC) + timedelta(hours=2),
    )
    changed = SimpleNamespace(
        authority_source_id=initial.authority_source_id,
        actor_id="service:other-refresh",
        user_id=initial.user_id,
        tenant_id=initial.tenant_id,
        owner_id=initial.owner_id,
        is_authenticated=initial.is_authenticated,
        is_staff=initial.is_staff,
        role=initial.role,
        authority_content_hash="c" * 64,
        authority_valid_until=initial.authority_valid_until,
    )
    contexts = iter((initial, changed))
    monkeypatch.setattr(
        tasks,
        "preflight_data_reliability_audit_runtime",
        lambda **_: next(contexts),
    )
    monkeypatch.setattr(tasks, "get_active_provider_id_by_source", lambda _: 3)
    monkeypatch.setattr(tasks, "latest_closed_cn_market_session", lambda _: date(2026, 9, 18))
    monkeypatch.setattr(
        tasks,
        "list_active_stock_codes_for_backfill",
        lambda: ["000001.SZ"],
    )
    quote = SimpleNamespace(
        execute=lambda *_args, **_kwargs: pytest.fail("quote provider called after authority drift")
    )
    monkeypatch.setattr(tasks, "make_backfill_sync_quote_use_case", lambda: quote)
    monkeypatch.setattr(
        tasks,
        "make_backfill_sync_current_valuation_batch_use_case",
        lambda: SimpleNamespace(execute=lambda **_: pytest.fail("valuation provider called")),
    )
    monkeypatch.setattr(
        tasks,
        "make_core_current_publication_rebuild_use_case",
        lambda **_: SimpleNamespace(preview=lambda **_: pytest.fail("publication preview called")),
    )

    result = tasks.refresh_full_market_publications_task.run(batch_size=1)

    assert result["outcome"] == "blocked"
    assert result["blocked_reason"] == "authority_changed_or_expired"
    assert result["stored"] == 0


def test_task_exposes_stable_universe_refresh_error(monkeypatch):
    """Provider exception text stays out of the user-facing task result."""

    from types import SimpleNamespace

    from apps.data_center.application import tasks

    monkeypatch.setattr(tasks, "get_active_provider_id_by_source", lambda _: 3)
    monkeypatch.setattr(tasks, "latest_closed_cn_market_session", lambda _: date(2026, 9, 18))
    monkeypatch.setattr(tasks, "make_backfill_sync_quote_use_case", SimpleNamespace)
    monkeypatch.setattr(
        tasks,
        "make_backfill_sync_current_valuation_batch_use_case",
        SimpleNamespace,
    )
    monkeypatch.setattr(
        tasks,
        "make_core_current_publication_rebuild_use_case",
        lambda **_: SimpleNamespace(),
    )
    monkeypatch.setattr(
        tasks,
        "sync_active_a_share_universe",
        lambda: (_ for _ in ()).throw(ValueError("secret upstream response")),
    )

    result = tasks.refresh_full_market_publications_task.run()

    assert result["outcome"] == "blocked"
    assert result["blocked_reason"] == "market_universe_refresh_failed"
    assert result["error_code"] == "MARKET_UNIVERSE_REFRESH_FAILED"
    assert result["errors"] == ["MARKET_UNIVERSE_REFRESH_FAILED"]
    assert "secret" not in str(result)


def test_equivalent_authority_successor_does_not_interrupt_active_refresh(
    monkeypatch,
    _patch_current_authority,
):
    """An append-only renewal with the same identity may rotate the authority hash."""

    from types import SimpleNamespace

    from apps.data_center.application import tasks

    successor = SimpleNamespace(
        **{
            **vars(_patch_current_authority),
            "authority_content_hash": "c" * 64,
            "authority_valid_until": datetime.now(UTC) + timedelta(hours=3),
        }
    )
    monkeypatch.setattr(
        tasks,
        "preflight_data_reliability_audit_runtime",
        lambda **_: successor,
    )

    assert tasks._same_data02_task_authority_is_current(
        _patch_current_authority,
        as_of=datetime.now(UTC),
    )


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
    monkeypatch.setattr(tasks, "latest_closed_cn_market_session", lambda _: date(2026, 9, 18))
    monkeypatch.setattr(tasks, "list_active_stock_codes_for_backfill", lambda: ["000001.SZ"])
    sync = SimpleNamespace(
        execute=lambda *_, **kwargs: SimpleNamespace(
            stored_count=1,
            stored_asset_codes=("000001.SZ",),
            succeeded_asset_codes=("000001.SZ",),
            returned_asset_codes=("000001.SZ",),
        )
    )
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
    composition_calls = []

    def build_publications(**kwargs):
        composition_calls.append(kwargs)
        return SimpleNamespace(
            preview=lambda **_: preview, execute=lambda **_: pytest.fail("published stale scope")
        )

    monkeypatch.setattr(tasks, "make_core_current_publication_rebuild_use_case", build_publications)
    result = tasks.refresh_full_market_publications_task.run()
    assert result["outcome"] == "partial"
    assert result["published_members"] == 0
    assert composition_calls[0]["created_by"] == (
        "celery.full_market_refresh:service:market-refresh"
    )


@pytest.mark.parametrize(
    ("quote_codes", "valuation_succeeded_codes", "expected_outcome"),
    [
        (("000001.SZ", "000001.SZ"), ("000001.SZ", "000002.SZ"), "partial"),
        (("000001.SZ", "000002.SZ"), ("000001.SZ", "000001.SZ"), "blocked"),
    ],
)
def test_task_rejects_duplicate_provider_asset_identities_before_publication(
    monkeypatch,
    quote_codes,
    valuation_succeeded_codes,
    expected_outcome,
):
    """A count-equal duplicate batch cannot reach full-market publication."""

    from types import SimpleNamespace

    from apps.data_center.application import tasks

    monkeypatch.setattr(tasks, "get_active_provider_id_by_source", lambda _: 3)
    monkeypatch.setattr(tasks, "latest_closed_cn_market_session", lambda _: date(2026, 9, 18))
    monkeypatch.setattr(
        tasks,
        "list_active_stock_codes_for_backfill",
        lambda: ["000001.SZ", "000002.SZ"],
    )
    quote = SimpleNamespace(
        execute=lambda *_args, **_kwargs: SimpleNamespace(
            stored_count=2,
            stored_asset_codes=quote_codes,
        )
    )
    valuation = SimpleNamespace(
        execute=lambda *_args, **_kwargs: SimpleNamespace(
            stored_count=2,
            succeeded_asset_codes=valuation_succeeded_codes,
            returned_asset_codes=("000001.SZ", "000002.SZ"),
        )
    )
    monkeypatch.setattr(tasks, "make_backfill_sync_quote_use_case", lambda: quote)
    monkeypatch.setattr(
        tasks,
        "make_backfill_sync_current_valuation_batch_use_case",
        lambda: valuation,
    )
    publication = SimpleNamespace(
        preview=lambda **_: pytest.fail("duplicate quote batch reached preview"),
        execute=lambda **_: pytest.fail("duplicate quote batch reached publication"),
    )
    monkeypatch.setattr(
        tasks,
        "make_core_current_publication_rebuild_use_case",
        lambda **_: publication,
    )

    result = tasks.refresh_full_market_publications_task.run(batch_size=2)

    assert result["outcome"] == expected_outcome
    assert result.get("published_members", 0) == 0


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
    provider_ids = {"tushare": 3, "akshare": 7}
    monkeypatch.setattr(tasks, "get_active_provider_id_by_source", lambda name: provider_ids[name])
    monkeypatch.setattr(tasks, "latest_closed_cn_market_session", lambda _: date(2026, 9, 18))
    monkeypatch.setattr(tasks, "list_active_stock_codes_for_backfill", lambda: ["000001.SZ"])
    quote_provider_ids = []
    valuation_provider_ids = []

    def sync_quote(request):
        quote_provider_ids.append(request.provider_id)
        return SimpleNamespace(
            stored_count=1,
            stored_asset_codes=("000001.SZ",),
        )

    def sync_valuation(**kwargs):
        valuation_provider_ids.append(kwargs["provider_id"])
        return SimpleNamespace(
            stored_count=1,
            succeeded_asset_codes=("000001.SZ",),
            returned_asset_codes=("000001.SZ",),
        )

    monkeypatch.setattr(
        tasks, "make_backfill_sync_quote_use_case", lambda: SimpleNamespace(execute=sync_quote)
    )
    monkeypatch.setattr(
        tasks,
        "make_backfill_sync_current_valuation_batch_use_case",
        lambda: SimpleNamespace(execute=sync_valuation),
    )
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
    assert result["quote_source"] == "akshare"
    assert result["valuation_source"] == "tushare"
    assert quote_provider_ids == [7]
    assert valuation_provider_ids == [3]
