from datetime import date
from types import SimpleNamespace

from apps.data_center.application.interface_services import (
    load_alpha_homepage_data,
    queue_alpha_score_prediction,
    resolve_portfolio_alpha_scope,
    run_alpha_score_prediction_now,
)


class _FakeAlphaHomepageQuery:
    def execute(self, *, user, top_n, portfolio_id, pool_mode):
        return {
            "user": user,
            "top_n": top_n,
            "portfolio_id": portfolio_id,
            "pool_mode": pool_mode,
        }


class _FakeResolver:
    def resolve(self, *, user_id, portfolio_id, trade_date, pool_mode):
        return SimpleNamespace(
            user_id=user_id,
            portfolio_id=portfolio_id,
            trade_date=trade_date,
            pool_mode=pool_mode,
        )


class _FakeTask:
    @staticmethod
    def apply_async(*, args, kwargs):
        return SimpleNamespace(id="task-1", args=args, kwargs=kwargs)

    @staticmethod
    def apply(*, args, kwargs):
        return SimpleNamespace(get=lambda: {"args": args, "kwargs": kwargs})


def test_load_alpha_homepage_data_uses_dashboard_query(monkeypatch):
    monkeypatch.setattr(
        "apps.dashboard.application.alpha_homepage.AlphaHomepageQuery",
        _FakeAlphaHomepageQuery,
    )

    assert load_alpha_homepage_data(
        user="user-1",
        top_n=10,
        portfolio_id=7,
        pool_mode="price_covered",
    ) == {
        "user": "user-1",
        "top_n": 10,
        "portfolio_id": 7,
        "pool_mode": "price_covered",
    }


def test_resolve_portfolio_alpha_scope_uses_alpha_module(monkeypatch):
    monkeypatch.setattr(
        "apps.alpha.application.pool_resolver.PortfolioAlphaPoolResolver",
        _FakeResolver,
    )

    resolved = resolve_portfolio_alpha_scope(
        user_id=7,
        portfolio_id=11,
        trade_date=date(2026, 4, 26),
    )

    assert resolved.user_id == 7
    assert resolved.portfolio_id == 11
    assert resolved.pool_mode == "price_covered"


def test_queue_and_run_alpha_score_prediction_use_alpha_task(monkeypatch):
    monkeypatch.setattr("apps.alpha.application.tasks.qlib_predict_scores", _FakeTask)

    queued = queue_alpha_score_prediction(
        universe_id="u-1",
        trade_date=date(2026, 4, 26),
        scope_payload={"scope_hash": "x"},
    )
    ran = run_alpha_score_prediction_now(
        universe_id="u-1",
        trade_date=date(2026, 4, 26),
        scope_payload={"scope_hash": "x"},
    )

    assert queued.id == "task-1"
    assert ran["args"][0] == "u-1"
