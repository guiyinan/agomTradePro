"""Persisted daily snapshot correction-watermark contract."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from uuid import uuid4

import pytest

from apps.simulated_trading.infrastructure.account_mapper import SimulatedAccountMapper
from apps.simulated_trading.infrastructure.daily_net_value_repository import (
    DjangoDailyNetValueRepository,
)
from apps.simulated_trading.infrastructure.fee_correction_prefix import (
    fee_correction_account_genesis_sha256,
)
from apps.simulated_trading.infrastructure.models import (
    DailyNetValueModel,
    SimulatedAccountModel,
)

pytestmark = pytest.mark.django_db(transaction=True)


def test_new_snapshot_captures_zero_watermark_and_legacy_row_stays_unknown() -> None:
    """New rows prove no earlier correction existed; existing rows are not backfilled."""

    suffix = uuid4().hex[:12]
    account = SimulatedAccountModel.objects.create(
        account_name=f"fee-correction-watermark-{suffix}",
        account_type="simulated",
        initial_capital=Decimal("10000.00"),
        current_cash=Decimal("10000.00"),
        current_market_value=Decimal("0.00"),
        total_value=Decimal("10000.00"),
        is_active=True,
    )
    repository = DjangoDailyNetValueRepository()
    record_date = date(2026, 10, 24)
    payload = {
        "net_value": 10_000.0,
        "cash": 10_000.0,
        "market_value": 0.0,
        "daily_return": 0.0,
        "cumulative_return": 0.0,
        "drawdown": 0.0,
        "total_trades": 0,
        "positions_count": 0,
    }

    assert (
        repository.upsert_daily_record(
            account_id=account.pk,
            record_date=record_date,
            payload=payload,
            expected_account=SimulatedAccountMapper.to_entity(account),
        )
        is True
    )

    new_row = DailyNetValueModel.objects.get(account=account, record_date=record_date)
    assert new_row.correction_event_watermark == 0
    assert new_row.correction_event_watermark_sha256 == fee_correction_account_genesis_sha256(
        account.pk
    )

    legacy_row = DailyNetValueModel.objects.create(
        account=account,
        record_date=date(2026, 10, 23),
        net_value=Decimal("10000.0000"),
        cash=Decimal("10000.00"),
        market_value=Decimal("0.00"),
    )
    legacy_row.refresh_from_db()
    assert legacy_row.correction_event_watermark is None
    assert legacy_row.correction_event_watermark_sha256 is None
