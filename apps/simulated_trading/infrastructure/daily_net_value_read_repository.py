"""Read and project daily net-value history with fee-correction lineage."""

from __future__ import annotations

from datetime import date, datetime, time, timedelta

from django.db import DEFAULT_DB_ALIAS
from django.utils import timezone

from apps.simulated_trading.application.daily_net_value_metrics import (
    project_daily_net_value_metrics,
)
from apps.simulated_trading.application.fee_correction import (
    FeeCorrectionCashPosting,
    FeeCorrectionHistoryRepositoryProtocol,
)
from apps.simulated_trading.application.ports import (
    DailyNetValueRecord,
    PreviousDailyNetValueRecord,
)
from apps.simulated_trading.infrastructure.models import (
    DailyNetValueModel,
    SimulatedAccountModel,
)
from core.exceptions import BusinessLogicError

from .daily_net_value_correction_overlay import overlay_daily_correction_cash


class DjangoDailyNetValueReadRepository:
    """Own corrected history projection and read-side coverage guarantees."""

    _correction_history: FeeCorrectionHistoryRepositoryProtocol

    def list_daily_records(
        self,
        account_id: int,
        start_date: date | None = None,
        end_date: date | None = None,
    ) -> list[DailyNetValueRecord]:
        """Read persisted snapshots, overlay known fee corrections, and project metrics."""

        queryset = (
            DailyNetValueModel._default_manager.using(DEFAULT_DB_ALIAS)
            .filter(account_id=account_id)
            .order_by("record_date")
        )
        if end_date:
            queryset = queryset.filter(record_date__lte=end_date)
        rows = queryset.values(
            "record_date",
            "net_value",
            "cash",
            "market_value",
            "daily_return",
            "cumulative_return",
            "drawdown",
            "total_trades",
            "positions_count",
            "correction_event_watermark",
            "correction_event_watermark_sha256",
        )
        values = list(rows)
        if not values:
            return []
        initial_capital = (
            SimulatedAccountModel._default_manager.using(DEFAULT_DB_ALIAS)
            .filter(pk=account_id)
            .values_list("initial_capital", flat=True)
            .first()
        )
        correction_events = self._correction_events_through(
            account_id=account_id,
            end_date=values[-1]["record_date"],
        )
        result: list[DailyNetValueRecord] = []
        for row in values:
            overlay = overlay_daily_correction_cash(
                account_id=account_id,
                record_date=row["record_date"],
                cash=row["cash"],
                total_value=row["net_value"],
                correction_event_watermark=row["correction_event_watermark"],
                correction_event_watermark_sha256=row["correction_event_watermark_sha256"],
                events=correction_events,
            )
            result.append(
                DailyNetValueRecord(
                    record_date=row["record_date"],
                    net_value=overlay.total_value,
                    cash=overlay.cash,
                    market_value=row["market_value"],
                    daily_return=row["daily_return"],
                    cumulative_return=row["cumulative_return"],
                    drawdown=row["drawdown"],
                    total_trades=row["total_trades"],
                    positions_count=row["positions_count"],
                    correction_event_watermark=row["correction_event_watermark"],
                    correction_event_watermark_sha256=row["correction_event_watermark_sha256"],
                    correction_coverage_known=overlay.correction_coverage_known,
                    original_net_value=row["net_value"],
                    original_cash=row["cash"],
                    original_daily_return=row["daily_return"],
                    original_cumulative_return=row["cumulative_return"],
                    original_drawdown=row["drawdown"],
                    correction_overlay_applied=(
                        overlay.cash != row["cash"] or overlay.total_value != row["net_value"]
                    ),
                )
            )
        metric_projections = project_daily_net_value_metrics(
            result,
            initial_capital=initial_capital,
        )
        for record, metrics in zip(result, metric_projections, strict=True):
            record["daily_return"] = metrics.daily_return
            record["cumulative_return"] = metrics.cumulative_return
            record["drawdown"] = metrics.drawdown
            record["original_daily_return"] = metrics.original_daily_return
            record["original_cumulative_return"] = metrics.original_cumulative_return
            record["original_drawdown"] = metrics.original_drawdown
            record["effective_metrics_known"] = metrics.metrics_known
            record["effective_metrics_reason_code"] = metrics.reason_code
        if start_date:
            result = [record for record in result if record["record_date"] >= start_date]
        return result

    def get_latest_record_before(
        self,
        account_id: int,
        current_date: date,
    ) -> PreviousDailyNetValueRecord | None:
        """Return the previous snapshot only when its correction coverage is known."""

        records = self.list_daily_records(
            account_id,
            end_date=current_date - timedelta(days=1),
        )
        if not records:
            return None
        row = records[-1]
        if not row["correction_coverage_known"]:
            raise BusinessLogicError(
                "上一净值记录的费用更正覆盖范围未知",
                code="DAILY_NET_VALUE_CORRECTION_COVERAGE_UNKNOWN",
            )
        return PreviousDailyNetValueRecord(
            record_date=row["record_date"],
            net_value=row["net_value"],
            cumulative_return=row["cumulative_return"],
            correction_coverage_known=row["correction_coverage_known"],
        )

    def get_max_net_value_before(self, account_id: int, before_date: date) -> float | None:
        """Return the corrected historical maximum only when coverage is complete."""

        records = self.list_daily_records(
            account_id,
            end_date=before_date - timedelta(days=1),
        )
        if any(not row["correction_coverage_known"] for row in records):
            raise BusinessLogicError(
                "历史净值的费用更正覆盖范围未知",
                code="DAILY_NET_VALUE_CORRECTION_COVERAGE_UNKNOWN",
            )
        return max((float(row["net_value"]) for row in records), default=None)

    def _correction_events_through(
        self,
        *,
        account_id: int,
        end_date: date,
    ) -> tuple[FeeCorrectionCashPosting, ...]:
        """Read proof-validated cash events through one local end-of-day clock."""

        as_of = timezone.make_aware(datetime.combine(end_date, time.max))
        projection = self._correction_history.get_account_history(
            account_id=account_id,
            as_of=as_of,
        )
        return projection.cash_events


__all__ = ["DjangoDailyNetValueReadRepository"]
