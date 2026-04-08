from datetime import timedelta

import pytest
from django.contrib.auth.models import User
from django.utils import timezone

from apps.signal.application.tasks import send_daily_signal_summary
from apps.signal.infrastructure.models import InvestmentSignalModel


@pytest.mark.django_db
def test_send_daily_signal_summary_handles_recent_signals(mocker) -> None:
    """Daily signal summary should read recent signals without querying missing fields."""
    recent_time = timezone.now() - timedelta(hours=1)
    user = User.objects.create_user(username="summary-user", password="test-pass-123")

    created_signal = InvestmentSignalModel.objects.create(
        user=user,
        asset_code="000001.SH",
        asset_class="a_share_growth",
        direction="LONG",
        logic_desc="新增信号",
        invalidation_logic="测试证伪逻辑描述，长度至少需要十个字符",
        invalidation_threshold=50.0,
        target_regime="Recovery",
        status="pending",
    )
    invalidated_signal = InvestmentSignalModel.objects.create(
        asset_code="000002.SH",
        asset_class="a_share_growth",
        direction="LONG",
        logic_desc="已证伪信号",
        invalidation_logic="测试证伪逻辑描述，长度至少需要十个字符",
        invalidation_threshold=49.0,
        target_regime="Recovery",
        status="invalidated",
        invalidation_details={"reason": "PMI failed"},
    )
    InvestmentSignalModel.objects.filter(id=created_signal.id).update(created_at=recent_time)
    InvestmentSignalModel.objects.filter(id=invalidated_signal.id).update(
        invalidated_at=recent_time,
        created_at=recent_time,
    )

    notifier = mocker.patch(
        "apps.signal.application.tasks._send_signal_summary_notification",
        return_value=True,
    )

    summary = send_daily_signal_summary()

    notifier.assert_called_once()
    assert summary["new_signals"] == 2
    assert summary["invalidated_signals"] == 1
