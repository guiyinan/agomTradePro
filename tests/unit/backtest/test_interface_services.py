"""Behavioral tests for Backtest interface-facing application services."""

from types import SimpleNamespace

import pytest

from apps.backtest.application import interface_services


def test_load_backtest_list_context_uses_one_repository_snapshot(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The page context keeps list and statistics queries behind the repository."""
    repository = SimpleNamespace(
        get_all_backtests=lambda *, limit, user_id: [{"id": 1, "limit": limit, "user_id": user_id}],
        get_statistics=lambda *, user_id: {"completed": 1, "user_id": user_id},
    )
    monkeypatch.setattr(
        interface_services,
        "get_backtest_repository",
        lambda: repository,
    )

    context = interface_services.load_backtest_list_context(user_id=5, limit=7)

    assert context == {
        "backtests": [{"id": 1, "limit": 7, "user_id": 5}],
        "stats": {"completed": 1, "user_id": 5},
    }


def test_backtest_exists_preserves_repository_presence_semantics(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Existence checks distinguish a missing row from a present falsey payload."""
    rows = {7: {"id": 7}, 8: None}
    monkeypatch.setattr(
        interface_services,
        "get_backtest_repository",
        lambda: SimpleNamespace(
            get_backtest_by_id=lambda backtest_id, *, user_id: rows.get(backtest_id)
        ),
    )

    assert interface_services.backtest_exists(7, user_id=5) is True
    assert interface_services.backtest_exists(8, user_id=5) is False


def test_rerun_backtest_reuses_owner_scoped_persisted_configuration(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Reruns copy governed inputs into a new execution without mutating the old row."""

    row = SimpleNamespace(
        name="Existing run",
        start_date="2026-01-01",
        end_date="2026-06-30",
        initial_capital=100000,
        rebalance_frequency="monthly",
        use_pit_data=False,
        transaction_cost_bps=12.5,
        trust_status="exploratory",
        data_manifest_id=None,
        pit_coverage={"prices": 1.0},
        config_hash="config-hash",
        code_commit="commit-hash",
        engine_version="",
        research_trial_id=None,
        decision_snapshot_id=None,
    )
    repository = SimpleNamespace(
        get_backtest_by_id=lambda backtest_id, *, user_id: (
            row if (backtest_id, user_id) == (7, 5) else None
        )
    )
    captured: dict[str, object] = {}
    expected = SimpleNamespace(status="completed")

    monkeypatch.setattr(interface_services, "get_backtest_repository", lambda: repository)

    def _run(payload, *, user_id):
        captured.update({"payload": payload, "user_id": user_id})
        return expected

    monkeypatch.setattr(interface_services, "run_backtest_payload", _run)

    assert interface_services.rerun_backtest_payload(7, user_id=5) is expected
    assert captured["user_id"] == 5
    assert captured["payload"] == {
        "name": "Existing run",
        "start_date": "2026-01-01",
        "end_date": "2026-06-30",
        "initial_capital": 100000.0,
        "rebalance_frequency": "monthly",
        "use_pit_data": False,
        "transaction_cost_bps": 12.5,
        "trust_status": "exploratory",
        "data_manifest_id": None,
        "pit_coverage": {"prices": 1.0},
        "config_hash": "config-hash",
        "code_commit": "commit-hash",
        "engine_version": "backtest-v1",
        "research_trial_id": None,
        "decision_snapshot_id": None,
    }
    assert interface_services.rerun_backtest_payload(8, user_id=5) is None


def test_load_backtest_detail_context_handles_missing_and_completed_rows(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Detail context exposes a summary only for a persisted completed run."""

    class FakeRepository:
        row = None

        def get_backtest_by_id(self, _backtest_id: int, *, user_id: int):
            return self.row

        @staticmethod
        def to_domain_entity(row):
            return SimpleNamespace(to_summary_dict=lambda: {"id": row.id})

    repository = FakeRepository()
    monkeypatch.setattr(
        interface_services,
        "get_backtest_repository",
        lambda: repository,
    )

    assert interface_services.load_backtest_detail_context(99, user_id=5) is None

    repository.row = SimpleNamespace(id=7, status="completed")
    context = interface_services.load_backtest_detail_context(7, user_id=5)

    assert context == {
        "backtest": repository.row,
        "summary": {"id": 7},
        "is_completed": True,
    }
