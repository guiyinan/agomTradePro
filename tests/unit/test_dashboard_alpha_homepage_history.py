"""Focused tests for Dashboard Alpha history application behavior."""

from __future__ import annotations

import logging
from datetime import date
from types import SimpleNamespace

from apps.alpha.domain.entities import AlphaPoolScope, AlphaResult
from apps.dashboard.application.alpha_homepage_history import AlphaHistoryMixin


class _HistoryRepository:
    def __init__(self) -> None:
        self.run_payload: dict[str, object] = {}
        self.snapshot_payload: list[dict[str, object]] = []

    def upsert_run(self, **kwargs: object) -> SimpleNamespace:
        self.run_payload = kwargs
        return SimpleNamespace(id=17)

    def replace_snapshots(
        self,
        *,
        run: object,
        snapshots: list[dict[str, object]],
    ) -> None:
        self.snapshot_payload = snapshots


class _SnapshotManager:
    def __init__(self, snapshots: list[SimpleNamespace]) -> None:
        self.snapshots = snapshots
        self.call_count = 0

    def all(self) -> list[SimpleNamespace]:
        self.call_count += 1
        return self.snapshots


def _scope() -> AlphaPoolScope:
    return AlphaPoolScope(
        pool_type="portfolio_market",
        market="CN",
        pool_mode="strict_valuation",
        instrument_codes=("000001.SZ",),
        selection_reason="test",
        trade_date=date(2026, 7, 27),
        display_label="Test pool",
    )


def _alpha_result() -> AlphaResult:
    return AlphaResult(
        success=True,
        scores=[],
        source="cache",
        timestamp="2026-07-27T09:00:00+08:00",
        metadata={"model_version": "test-v1"},
    )


def test_persist_history_preserves_run_when_metadata_date_is_malformed() -> None:
    repository = _HistoryRepository()
    query = AlphaHistoryMixin()
    query.history_repo = repository  # type: ignore[assignment]

    run_id = query._persist_history(
        user_id=3,
        portfolio_id=None,
        portfolio_name="",
        scope=_scope(),
        alpha_result=_alpha_result(),
        meta={
            "source": "cache",
            "requested_trade_date": "not-an-iso-date",
            "effective_asof_date": "2026-07-25",
        },
        snapshots=[],
    )

    assert run_id == 17
    assert repository.run_payload["requested_trade_date"] is None
    assert repository.run_payload["effective_asof_date"] == date(2026, 7, 25)
    assert repository.run_payload["meta"] == {
        "model_version": "test-v1",
        "history_parse_warnings": ["requested_trade_date"],
    }


def test_persist_history_log_redacts_repository_exception(caplog) -> None:
    class _FailingRepository(_HistoryRepository):
        def upsert_run(self, **kwargs: object) -> SimpleNamespace:
            raise RuntimeError("database password is secret")

    query = AlphaHistoryMixin()
    query.history_repo = _FailingRepository()  # type: ignore[assignment]

    with caplog.at_level(
        logging.WARNING,
        logger="apps.dashboard.application.alpha_homepage_history",
    ):
        result = query._persist_history(
            user_id=3,
            portfolio_id=None,
            portfolio_name="",
            scope=_scope(),
            alpha_result=_alpha_result(),
            meta={},
            snapshots=[],
        )

    assert result is None
    assert "RuntimeError" in caplog.text
    assert "database password is secret" not in caplog.text


def test_history_detail_loads_snapshots_once_and_normalizes_fallback_name() -> None:
    snapshot = SimpleNamespace(
        stock_code="000001.sz",
        stock_name="",
        stage="top_ranked",
        gate_status="allowed",
        rank=1,
        alpha_score=0.8,
        confidence=0.9,
        source="cache",
        buy_reasons=[],
        no_buy_reasons=[],
        invalidation_rule={},
        risk_snapshot={},
        suggested_position_pct=0.1,
        suggested_notional=1000.0,
        suggested_quantity=100.0,
        extra_payload={},
    )
    manager = _SnapshotManager([snapshot])
    run = SimpleNamespace(
        id=7,
        portfolio_id=None,
        portfolio_name="",
        trade_date=date(2026, 7, 27),
        scope_label="Test pool",
        source="cache",
        provider_source="",
        uses_cached_data=True,
        cache_reason="",
        fallback_reason="",
        requested_trade_date=None,
        effective_asof_date=None,
        meta={},
        snapshots=manager,
    )
    query = AlphaHistoryMixin()
    query.history_repo = SimpleNamespace(  # type: ignore[assignment]
        get_run_detail=lambda **kwargs: run
    )
    query.context_repo = SimpleNamespace(  # type: ignore[assignment]
        load_stock_context=lambda codes, persist_names: {"000001.SZ": {"name": 12345}}
    )

    detail = query.get_history_detail(user_id=3, run_id=7)

    assert manager.call_count == 1
    assert detail is not None
    assert detail["snapshots"][0]["code"] == "000001.SZ"
    assert detail["snapshots"][0]["name"] == "12345"
