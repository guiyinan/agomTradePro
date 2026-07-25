"""Fail-closed fetchers for weekly indicators lacking semantic source coverage."""

from __future__ import annotations

import logging
from collections.abc import Callable
from datetime import date
from typing import Any

from ..base import MacroDataPoint

logger = logging.getLogger(__name__)

ValidateDataPoint = Callable[[MacroDataPoint], None]
SortAndDeduplicate = Callable[[list[MacroDataPoint]], list[MacroDataPoint]]

_UNSUPPORTED_REASONS = {
    "CN_POWER_GEN": (
        "macro_china_society_electricity publishes electricity consumption, " "not power generation"
    ),
    "CN_BLAST_FURNACE": ("sh000819 is a steel equity index, not blast-furnace utilization"),
    "CN_CCFI": (
        "BDI measures global dry-bulk shipping, not the China Containerized " "Freight Index"
    ),
    "CN_SCFI": (
        "BCI measures Capesize dry-bulk shipping, not the Shanghai " "Containerized Freight Index"
    ),
}


class WeeklyIndicatorFetcher:
    """Keep routed methods stable while rejecting incompatible proxy series."""

    def __init__(
        self,
        ak: Any,
        source_name: str,
        validate_fn: ValidateDataPoint,
        sort_dedup_fn: SortAndDeduplicate,
    ) -> None:
        self.ak = ak
        self.source_name = source_name
        self._validate = validate_fn
        self._sort_and_deduplicate = sort_dedup_fn

    @staticmethod
    def _unsupported(indicator_code: str) -> list[MacroDataPoint]:
        """Return no facts when the available endpoint has different semantics."""

        logger.warning(
            "%s: %s; automatic publication is disabled",
            indicator_code,
            _UNSUPPORTED_REASONS[indicator_code],
        )
        return []

    def fetch_power_generation(
        self,
        start_date: date,
        end_date: date,
    ) -> list[MacroDataPoint]:
        """Reject electricity-consumption data mislabeled as power generation."""

        return self._unsupported("CN_POWER_GEN")

    def fetch_blast_furnace_utilization(
        self,
        start_date: date,
        end_date: date,
    ) -> list[MacroDataPoint]:
        """Reject a steel equity index mislabeled as furnace utilization."""

        return self._unsupported("CN_BLAST_FURNACE")

    def fetch_ccfi(
        self,
        start_date: date,
        end_date: date,
    ) -> list[MacroDataPoint]:
        """Reject BDI dry-bulk data mislabeled as CCFI."""

        return self._unsupported("CN_CCFI")

    def fetch_scfi(
        self,
        start_date: date,
        end_date: date,
    ) -> list[MacroDataPoint]:
        """Reject BCI dry-bulk data mislabeled as SCFI."""

        return self._unsupported("CN_SCFI")
