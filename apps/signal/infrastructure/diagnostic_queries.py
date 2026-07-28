"""Infrastructure read models for signal diagnostics."""

from __future__ import annotations

from django.db.models import Count, Q

from apps.signal.domain.diagnostics import (
    RecentSignalDiagnostic,
    SignalDiagnosticSummary,
)
from apps.signal.domain.entities import SignalStatus
from apps.signal.infrastructure.models import InvestmentSignalModel


class SignalDiagnosticRepository:
    """Read signal summary rows for operational diagnostics."""

    def get_signal_count(self) -> int:
        """Return the number of investment signals."""

        return int(InvestmentSignalModel.objects.count())

    def get_signal_summary(self, *, recent_limit: int = 5) -> SignalDiagnosticSummary:
        """Return truthful status counts and bounded recent signal evidence."""

        if (
            isinstance(recent_limit, bool)
            or not isinstance(recent_limit, int)
            or not 1 <= recent_limit <= 100
        ):
            raise ValueError("recent_limit must be an integer from 1 to 100")

        all_signals = InvestmentSignalModel._default_manager.all()
        counts = all_signals.aggregate(
            total_count=Count("id"),
            active_count=Count(
                "id",
                filter=Q(status=SignalStatus.APPROVED.value),
            ),
            invalidated_count=Count(
                "id",
                filter=Q(status=SignalStatus.INVALIDATED.value),
            ),
            closed_count=Count(
                "id",
                filter=Q(
                    status__in=(
                        SignalStatus.REJECTED.value,
                        SignalStatus.EXPIRED.value,
                    )
                ),
            ),
        )
        recent_signals: list[RecentSignalDiagnostic] = [
            RecentSignalDiagnostic(
                asset_code=signal.asset_code,
                direction=signal.direction,
                status=signal.status,
                created_at=signal.created_at,
            )
            for signal in all_signals.only(
                "asset_code",
                "direction",
                "status",
                "created_at",
            ).order_by("-created_at")[:recent_limit]
        ]

        return {
            "total_count": counts["total_count"],
            "active_count": counts["active_count"],
            "invalidated_count": counts["invalidated_count"],
            "closed_count": counts["closed_count"],
            "recent_signals": recent_signals,
            "regime_match_available": False,
            "regime_matched_count": 0,
        }

    def list_distinct_asset_codes(self) -> list[str]:
        """Return distinct asset codes referenced by investment signals."""

        return [
            str(asset_code)
            for asset_code in InvestmentSignalModel.objects.values_list(
                "asset_code", flat=True
            ).distinct()
            if asset_code
        ]
