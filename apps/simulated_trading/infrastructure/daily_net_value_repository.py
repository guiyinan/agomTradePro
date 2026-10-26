"""
模拟盘数据仓储实现

Infrastructure层:
- 实现Domain层定义的Repository Protocol接口
- 负责Domain实体与ORM模型之间的转换
- 封装数据库操作细节
"""

from datetime import date, datetime, time

from django.db import DEFAULT_DB_ALIAS, transaction
from django.utils import timezone

from apps.simulated_trading.application.fee_correction import (
    FeeCorrectionHistoryRepositoryProtocol,
)
from apps.simulated_trading.application.ports import DailyNetValueWritePayload
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
from .daily_net_value_read_repository import DjangoDailyNetValueReadRepository


class DjangoDailyNetValueRepository(DjangoDailyNetValueReadRepository):
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
