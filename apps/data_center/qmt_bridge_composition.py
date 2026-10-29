"""Composition root for the integrated QMT bridge."""

from datetime import date, datetime

from apps.data_center.application.qmt_bridge import QmtBridgeService
from apps.data_center.application.qmt_daily_status import QmtDailyStatusResult, ReadQmtDailyStatus
from apps.data_center.infrastructure.qmt_bridge_repository import QmtBridgeRepository
from apps.data_center.infrastructure.qmt_daily_status_repository import QmtDailyStatusRepository


def build_qmt_bridge_service() -> QmtBridgeService:
    """Wire bridge use cases to their Django persistence implementation."""
    return QmtBridgeService(QmtBridgeRepository())


def read_qmt_daily_status(
    *, owner_id: int, binding_id: str, asset_code: str, bar_date: date, as_of: datetime
) -> QmtDailyStatusResult:
    """Read owner-scoped historical assertions without publication or trading authority."""
    return ReadQmtDailyStatus(QmtDailyStatusRepository()).execute(
        owner_id=owner_id,
        binding_id=binding_id,
        asset_code=asset_code,
        bar_date=bar_date,
        as_of=as_of,
    )
