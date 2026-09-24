from __future__ import annotations

from datetime import date
from types import SimpleNamespace

from apps.alpha.application.pool_resolver import ResolvedAlphaPool
from apps.alpha.domain.entities import AlphaPoolScope, AlphaResult
from apps.dashboard.application.alpha_homepage import AlphaHomepageQuery
from apps.dashboard.application.alpha_homepage_runtime import AlphaRuntimeMixin


class _ReadOnlyAlphaService:
    def __init__(self) -> None:
        self.provider_filters: list[str] = []

    def get_stock_scores(
        self,
        *,
        universe_id: str,
        intended_trade_date: date,
        top_n: int,
        user: object,
        provider_filter: str,
        pool_scope: AlphaPoolScope | None = None,
    ) -> AlphaResult:
        del universe_id, intended_trade_date, top_n, user, pool_scope
        self.provider_filters.append(provider_filter)
        return AlphaResult(
            success=False,
            scores=[],
            source=provider_filter,
            timestamp="2026-09-24",
            status="unavailable",
        )


def _resolved_pool() -> ResolvedAlphaPool:
    scope = AlphaPoolScope(
        pool_type="portfolio_market",
        market="CN",
        pool_mode="price_covered",
        instrument_codes=("000001.SZ",),
        selection_reason="test",
        trade_date=date(2026, 9, 24),
        display_label="测试账户池",
        portfolio_id=11,
        portfolio_name="测试组合",
    )
    return ResolvedAlphaPool(
        portfolio_id=11,
        portfolio_name="测试组合",
        scope=scope,
        requested_pool_mode="price_covered",
        requested_pool_size=1,
    )


def test_scoped_alpha_read_does_not_queue_inference(monkeypatch) -> None:
    service = _ReadOnlyAlphaService()
    runtime = AlphaRuntimeMixin()
    runtime.alpha_service = service
    triggered: list[object] = []

    def record_trigger(**kwargs: object) -> dict[str, object]:
        triggered.append(kwargs)
        return {"refresh_triggered": True}

    monkeypatch.setattr(runtime, "_trigger_async_inference_if_needed", record_trigger)

    result = runtime._fetch_alpha_result(
        user=SimpleNamespace(id=7, is_authenticated=True),
        scope=_resolved_pool().scope,
        trade_date=date(2026, 9, 24),
        top_n=10,
        allow_refresh=False,
    )

    assert result.status == "unavailable"
    assert service.provider_filters == ["cache", "simple"]
    assert triggered == []


def test_general_alpha_read_skips_refresh_capable_provider_by_default() -> None:
    service = _ReadOnlyAlphaService()
    runtime = AlphaRuntimeMixin()
    runtime.alpha_service = service

    result = runtime._fetch_general_alpha_result(
        user=SimpleNamespace(id=7, is_authenticated=True),
        trade_date=date(2026, 9, 24),
        top_n=10,
        allow_refresh=False,
    )

    assert result.status == "unavailable"
    assert service.provider_filters == ["cache", "simple", "etf"]


def test_homepage_read_does_not_persist_history(monkeypatch) -> None:
    query = object.__new__(AlphaHomepageQuery)
    query.history_repo = SimpleNamespace(list_recent_runs=lambda **kwargs: [])
    resolved_pool = _resolved_pool()
    persist_calls: list[object] = []

    monkeypatch.setattr(
        "apps.dashboard.application.alpha_homepage.resolve_recent_closed_trade_date",
        lambda: date(2026, 9, 24),
    )
    monkeypatch.setattr(
        "apps.dashboard.application.alpha_homepage.PortfolioAlphaPoolResolver",
        lambda: SimpleNamespace(resolve=lambda **kwargs: resolved_pool),
    )
    monkeypatch.setattr(
        query,
        "_fetch_alpha_result",
        lambda **kwargs: AlphaResult(
            success=False,
            scores=[],
            source="cache",
            timestamp="2026-09-24",
            status="unavailable",
        ),
    )
    monkeypatch.setattr(query, "_attach_scope_resolution_metadata", lambda **kwargs: None)
    monkeypatch.setattr(query, "_build_meta", lambda **kwargs: {})
    monkeypatch.setattr(query, "_load_stock_context", lambda codes: {})
    monkeypatch.setattr(query, "_load_actionable_map", lambda: {})
    monkeypatch.setattr(query, "_load_pending_map", lambda user_id: {})
    monkeypatch.setattr(
        query,
        "_load_portfolio_context",
        lambda **kwargs: ({}, None, None),
    )
    monkeypatch.setattr(query, "_load_policy_state", lambda: {})
    monkeypatch.setattr(query, "_build_exit_watchlist", lambda **kwargs: [])
    monkeypatch.setattr(query, "_build_exit_watch_summary", lambda items: {})
    monkeypatch.setattr(
        query,
        "_persist_history",
        lambda **kwargs: persist_calls.append(kwargs) or 99,
    )
    monkeypatch.setattr(query, "_serialize_recent_runs", lambda runs: list(runs))

    result = query.execute(user=SimpleNamespace(id=7))

    assert result.history_run_id is None
    assert result.recent_runs == []
    assert persist_calls == []
