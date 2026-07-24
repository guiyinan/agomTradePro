"""Behavioral tests for Backtest interface-facing application services."""

from types import SimpleNamespace

import pytest

from apps.backtest.application import interface_services


def test_load_backtest_list_context_uses_one_repository_snapshot(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The page context keeps list and statistics queries behind the repository."""
    repository = SimpleNamespace(
        get_all_backtests=lambda *, limit: [{"id": 1, "limit": limit}],
        get_statistics=lambda: {"completed": 1},
    )
    monkeypatch.setattr(
        interface_services,
        "get_backtest_repository",
        lambda: repository,
    )

    context = interface_services.load_backtest_list_context(limit=7)

    assert context == {
        "backtests": [{"id": 1, "limit": 7}],
        "stats": {"completed": 1},
    }


def test_backtest_exists_preserves_repository_presence_semantics(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Existence checks distinguish a missing row from a present falsey payload."""
    rows = {7: {"id": 7}, 8: None}
    monkeypatch.setattr(
        interface_services,
        "get_backtest_repository",
        lambda: SimpleNamespace(get_backtest_by_id=rows.get),
    )

    assert interface_services.backtest_exists(7) is True
    assert interface_services.backtest_exists(8) is False


def test_load_backtest_detail_context_handles_missing_and_completed_rows(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Detail context exposes a summary only for a persisted completed run."""

    class FakeRepository:
        row = None

        def get_backtest_by_id(self, _backtest_id: int):
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

    assert interface_services.load_backtest_detail_context(99) is None

    repository.row = SimpleNamespace(id=7, status="completed")
    context = interface_services.load_backtest_detail_context(7)

    assert context == {
        "backtest": repository.row,
        "summary": {"id": 7},
        "is_completed": True,
    }
