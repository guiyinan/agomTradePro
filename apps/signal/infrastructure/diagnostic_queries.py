"""Infrastructure read models for signal diagnostics."""

from __future__ import annotations

from typing import Any

from apps.signal.infrastructure.models import InvestmentSignalModel


class SignalDiagnosticRepository:
    """Read signal summary rows for operational diagnostics."""

    def get_signal_count(self) -> int:
        """Return the number of investment signals."""

        return int(InvestmentSignalModel.objects.count())

    def get_signal_summary(self, *, recent_limit: int = 5) -> dict[str, Any]:
        """Return status counts, recent signals, and regime match count."""

        all_signals = InvestmentSignalModel.objects.all()
        recent_signals = [
            {
                "asset_code": signal.asset_code,
                "direction": signal.direction,
                "status": signal.status,
                "created_at": signal.created_at,
            }
            for signal in all_signals.order_by("-created_at")[:recent_limit]
        ]
        regime_matched_count = 0
        if any(
            field.name == "regime_match_score"
            for field in InvestmentSignalModel._meta.get_fields()
        ):
            regime_matched_count = all_signals.filter(regime_match_score__gte=0.7).count()

        return {
            "total_count": all_signals.count(),
            "active_count": all_signals.filter(status="active").count(),
            "invalidated_count": all_signals.filter(status="invalidated").count(),
            "closed_count": all_signals.filter(status="closed").count(),
            "recent_signals": recent_signals,
            "regime_matched_count": regime_matched_count,
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
