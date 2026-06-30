"""Infrastructure read models for regime diagnostics."""

from __future__ import annotations

from datetime import date

from apps.regime.infrastructure.models import RegimeLog


class RegimeDiagnosticRepository:
    """Read regime summary rows for operational diagnostics."""

    def get_regime_count(self) -> int:
        """Return the number of regime log rows."""

        return int(RegimeLog.objects.count())

    def get_latest_observed_at(self) -> date | None:
        """Return the latest regime observation date."""

        latest = RegimeLog.objects.order_by("-observed_at").first()
        return latest.observed_at if latest is not None else None
