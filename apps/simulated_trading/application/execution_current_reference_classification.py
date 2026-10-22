"""Application port for the explicitly selected simulated asset classification."""

from __future__ import annotations

from datetime import datetime
from typing import Protocol

from apps.simulated_trading.domain.execution_instrument_classification import (
    SimulatedInstrumentClassificationEvidenceV1,
)


class CurrentReferenceClassificationReader(Protocol):
    """Read one active v2 classification bound to the exact current source item."""

    def resolve_simulated_instrument_classification(
        self,
        *,
        security_id: str,
        asset_code: str,
        as_of: datetime,
    ) -> SimulatedInstrumentClassificationEvidenceV1 | None:
        """Return the exact active classification, or no classification when absent.

        A ``None`` result is not a type default. Callers must block any path that
        requires classification when the explicit v2 selector is unavailable.
        """
