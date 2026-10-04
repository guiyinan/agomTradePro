"""DATA-02 historical snapshot time-boundary contracts."""

from datetime import UTC, date, datetime

from apps.data_center.infrastructure.data02_isolated_snapshot import (
    PostgresData02HistoricalSnapshotAdapter,
)


class _PriceCursor:
    """Return one deterministic daily price row from the selector query."""

    def execute(self, _query: object, _params: object = None) -> None:
        """Accept the selector query without external I/O."""

    def fetchall(self) -> list[tuple[object, ...]]:
        """Return one daily price row for a closed mainland-China session."""

        return [(7, "000001.SZ", "tushare", date(2026, 9, 11), "accepted", "1d", "none")]


def test_price_snapshot_projects_daily_bar_to_official_session_close() -> None:
    """A daily price fact represents the official 15:00 China-market close."""

    references = PostgresData02HistoricalSnapshotAdapter._price_facts(
        _PriceCursor(),
        ("000001.SZ",),
    )

    assert len(references) == 1
    assert references[0].observed_at == datetime(2026, 9, 11, 7, tzinfo=UTC)
