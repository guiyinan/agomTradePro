"""
模拟盘数据仓储实现

Infrastructure层:
- 实现Domain层定义的Repository Protocol接口
- 负责Domain实体与ORM模型之间的转换
- 封装数据库操作细节
"""

from datetime import date

from apps.simulated_trading.application.ports import (
    DailyNetValueRecord,
    DailyNetValueWritePayload,
    PreviousDailyNetValueRecord,
)
from apps.simulated_trading.infrastructure.models import (
    DailyNetValueModel,
)


class DjangoDailyNetValueRepository:
    """日净值记录仓储。"""

    def upsert_daily_record(
        self,
        account_id: int,
        record_date: date,
        payload: DailyNetValueWritePayload,
    ) -> None:
        DailyNetValueModel._default_manager.update_or_create(
            account_id=account_id,
            record_date=record_date,
            defaults=payload,
        )

    def list_daily_records(
        self,
        account_id: int,
        start_date: date | None = None,
        end_date: date | None = None,
    ) -> list[DailyNetValueRecord]:
        queryset = DailyNetValueModel._default_manager.filter(account_id=account_id).order_by(
            "record_date"
        )
        if start_date:
            queryset = queryset.filter(record_date__gte=start_date)
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
        )
        return [
            DailyNetValueRecord(
                record_date=row["record_date"],
                net_value=row["net_value"],
                cash=row["cash"],
                market_value=row["market_value"],
                daily_return=row["daily_return"],
                cumulative_return=row["cumulative_return"],
                drawdown=row["drawdown"],
                total_trades=row["total_trades"],
                positions_count=row["positions_count"],
            )
            for row in rows
        ]

    def get_latest_record_before(
        self,
        account_id: int,
        current_date: date,
    ) -> PreviousDailyNetValueRecord | None:
        row = (
            DailyNetValueModel._default_manager.filter(
                account_id=account_id,
                record_date__lt=current_date,
            )
            .order_by("-record_date")
            .values(
                "record_date",
                "net_value",
                "cumulative_return",
            )
            .first()
        )
        if row is None:
            return None
        return PreviousDailyNetValueRecord(
            record_date=row["record_date"],
            net_value=row["net_value"],
            cumulative_return=row["cumulative_return"],
        )

    def get_max_net_value_before(self, account_id: int, before_date: date) -> float | None:
        record = (
            DailyNetValueModel._default_manager.filter(
                account_id=account_id,
                record_date__lt=before_date,
            )
            .order_by("-net_value")
            .values("net_value")
            .first()
        )
        return float(record["net_value"]) if record else None
