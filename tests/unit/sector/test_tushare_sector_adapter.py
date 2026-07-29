"""Compatibility and data-quality boundaries for the legacy sector adapter."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from apps.sector.infrastructure import repositories as sector_repositories
from apps.sector.infrastructure.adapters.tushare_sector_adapter import TushareSectorAdapter
from apps.sector.infrastructure.repositories import DjangoSectorRepository


class _Frame:
    def __init__(self, rows: list[dict[str, object]]) -> None:
        self._rows = rows

    def iterrows(self):
        yield from enumerate(self._rows)


def test_legacy_adapter_rejects_invalid_codes_and_dates_before_delegation() -> None:
    """Traversal-like codes and malformed ranges never reach the delegate."""

    adapter = TushareSectorAdapter()
    adapter._delegate = SimpleNamespace(
        fetch_sector_index_daily=lambda **_: pytest.fail("delegate must not run"),
        fetch_all_sector_index_daily=lambda **_: pytest.fail("delegate must not run"),
    )

    with pytest.raises(ValueError, match="sector_date"):
        adapter.fetch_sector_index_daily("801010", "bad", "20250331")
    with pytest.raises(ValueError, match="sector_code"):
        adapter.fetch_all_sector_index_daily(["../secret"], "20250301", "20250331")
    with pytest.raises(ValueError, match="sector_code"):
        adapter.fetch_sector_constituents("../secret")


def test_batch_repository_skips_non_finite_rows(monkeypatch) -> None:
    """NaN market bars cannot cross the dataframe-to-ORM boundary."""

    saved: list[dict[str, object]] = []

    def _upsert(**kwargs: object) -> tuple[object, bool]:
        saved.append(kwargs)
        return object(), True

    monkeypatch.setattr(
        sector_repositories.SectorIndexModel._default_manager,
        "update_or_create",
        _upsert,
    )
    frame = _Frame(
        [
            {
                "sector_code": "801010",
                "trade_date": "2026-07-28",
                "open_price": "nan",
                "high": 11,
                "low": 9,
                "close": 10,
                "volume": 100,
                "amount": 1000,
                "change_pct": 1.2,
            },
            {
                "sector_code": "801010",
                "trade_date": "2026-07-29",
                "open_price": 10,
                "high": 11,
                "low": 9,
                "close": 10.5,
                "volume": 100,
                "amount": 1000,
                "change_pct": 1.2,
            },
        ]
    )

    count = DjangoSectorRepository().batch_save_sector_indices(frame)

    assert count == 1
    assert len(saved) == 1
    assert saved[0]["trade_date"].isoformat() == "2026-07-29"
