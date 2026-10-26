"""
模拟盘数据仓储实现

Infrastructure层:
- 实现Domain层定义的Repository Protocol接口
- 负责Domain实体与ORM模型之间的转换
- 封装数据库操作细节
"""

from datetime import date, datetime, time, timedelta

from django.db import DEFAULT_DB_ALIAS, transaction
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
    DailyNetValueWritePayload,
    PreviousDailyNetValueRecord,
)
from apps.simulated_trading.domain.entities import SimulatedAccount
from apps.simulated_trading.infrastructure.fee_correction_event_models import (
    SimulatedFeeCorrectionEventModel,
)
from apps.simulated_trading.infrastructure.fee_correction_prefix import (
    fee_correction_account_genesis_sha256,
)
from apps.simulated_trading.infrastructure.fee_correction_runtime import (
    build_django_fee_correction_repository,
)
from apps.simulated_trading.infrastructure.models import (
    DailyNetValueModel,
    SimulatedAccountModel,
)
from core.exceptions import BusinessLogicError

from .account_repository_guard import _require_account_snapshot_matches
from .daily_net_value_correction_overlay import overlay_daily_correction_cash


class DjangoDailyNetValueRepository:
    """日净值记录仓储。"""

    def __init__(
        self,
        *,
        correction_history: FeeCorrectionHistoryRepositoryProtocol | None = None,
    ) -> None:
        """Inject the validated correction reader used by daily-value queries."""

        self._correction_history = correction_history or build_django_fee_correction_repository()

    def upsert_daily_record(
        self,
        account_id: int,
        record_date: date,
        payload: DailyNetValueWritePayload,
        *,
        expected_account: SimulatedAccount,
    ) -> bool:
        """Insert one immutable daily value if absent and its parent snapshot is current."""

        if (
            type(account_id) is not int
            or account_id <= 0
            or type(expected_account) is not SimulatedAccount
            or expected_account.account_id != account_id
            or type(record_date) is not date
        ):
            raise BusinessLogicError(
                "日净值写入快照输入无效",
                code="DAILY_NET_VALUE_SNAPSHOT_INVALID",
            )
        with transaction.atomic(using=DEFAULT_DB_ALIAS):
            account = (
                SimulatedAccountModel._default_manager.using(DEFAULT_DB_ALIAS)
                .select_for_update()
                .filter(pk=account_id)
                .first()
            )
            if account is None:
                raise BusinessLogicError(
                    "日净值所属账户不存在",
                    code="ACCOUNT_NOT_FOUND",
                )
            _require_account_snapshot_matches(account, expected_account)
            records = DailyNetValueModel._default_manager.using(DEFAULT_DB_ALIAS)
            if records.filter(account_id=account_id, record_date=record_date).exists():
                return False
            event_rows = SimulatedFeeCorrectionEventModel._base_manager.using(
                DEFAULT_DB_ALIAS
            ).filter(account_id=account_id)
            if event_rows.filter(posting_date__gt=record_date).exists():
                raise BusinessLogicError(
                    "当前账户状态已包含记录日之后的费用更正，不能据此伪造历史日净值",
                    code="DAILY_NET_VALUE_CORRECTION_AS_OF_UNKNOWN",
                )
            as_of = timezone.make_aware(datetime.combine(record_date, time.max))
            correction_history = self._correction_history.get_account_history(
                account_id=account_id,
                as_of=as_of,
            )
            head = max(
                correction_history.cash_events,
                key=lambda event: event.account_revision,
                default=None,
            )
            watermark = head.account_revision if head is not None else 0
            watermark_sha256 = (
                head.account_prefix_sha256
                if head is not None
                else fee_correction_account_genesis_sha256(account_id)
            )
            _, created = records.get_or_create(
                account_id=account_id,
                record_date=record_date,
                defaults={
                    **payload,
                    "correction_event_watermark": watermark,
                    "correction_event_watermark_sha256": watermark_sha256,
                },
            )
            return created

    def list_daily_records(
        self,
        account_id: int,
        start_date: date | None = None,
        end_date: date | None = None,
    ) -> list[DailyNetValueRecord]:
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
