"""Injectable Strategy selection port for ordinary daily inspections."""

from __future__ import annotations

from collections.abc import Callable
from typing import Protocol

from apps.strategy.application.execution_gateway import InspectionSelection


class DailyInspectionStrategySelectionReader(Protocol):
    """Read a strategy selection after resolving the simulated-account owner."""

    def get_owner_inspection_selection(
        self,
        account_id: int,
        owner_user_id: int,
        strategy_id: int | None = None,
    ) -> InspectionSelection:
        """Return only the account owner's currently visible Strategy content."""
        ...


_reader_factory: Callable[[], DailyInspectionStrategySelectionReader] | None = None


def configure_daily_inspection_strategy_selection_reader(
    reader_factory: Callable[[], DailyInspectionStrategySelectionReader],
) -> None:
    """Register the Infrastructure composition used by ordinary inspections."""

    global _reader_factory
    _reader_factory = reader_factory


def get_daily_inspection_strategy_selection_reader() -> (
    DailyInspectionStrategySelectionReader | None
):
    """Return the configured Strategy owner-scope reader, if the app is wired."""

    return _reader_factory() if _reader_factory is not None else None


__all__: tuple[str, ...] = (
    "DailyInspectionStrategySelectionReader",
    "configure_daily_inspection_strategy_selection_reader",
    "get_daily_inspection_strategy_selection_reader",
)
