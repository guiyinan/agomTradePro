"""Contracts for the authenticated dashboard signal-status API projection."""

from datetime import timedelta
from types import SimpleNamespace

import pytest
from django.contrib.auth import get_user_model
from django.utils import timezone

from apps.dashboard.application.use_cases import GetDashboardDataUseCase
from apps.signal.infrastructure.models import InvestmentSignalModel
from apps.signal.infrastructure.repositories import DjangoSignalRepository


def _create_signal(
    *,
    user,
    asset_code: str,
    status: str,
    created_at,
) -> None:
    """Persist a signal with a deterministic owner-query ordering timestamp."""

    signal = InvestmentSignalModel.objects.create(
        user=user,
        asset_code=asset_code,
        asset_class="equity",
        direction="LONG",
        logic_desc=f"逻辑-{asset_code}",
        target_regime="Recovery",
        status=status,
    )
    InvestmentSignalModel.objects.filter(pk=signal.pk).update(created_at=created_at)


@pytest.mark.django_db
def test_signal_status_v1_uses_persisted_owner_scoped_signals(
    authenticated_client,
    auth_user,
    monkeypatch,
):
    """Project real owner queries while isolating unrelated dashboard assembly."""

    other_user = get_user_model().objects.create_user(
        username="other_signal_status_user",
        password="testpass123",
        email="other-signal-status@example.com",
    )
    now = timezone.now()
    approved_codes = [f"60000{index}.SH" for index in range(7)]
    approved_created_at = {
        code: now - timedelta(days=6 - index) for index, code in enumerate(approved_codes)
    }

    for code, created_at in approved_created_at.items():
        _create_signal(
            user=auth_user,
            asset_code=code,
            status="approved",
            created_at=created_at,
        )
    _create_signal(
        user=auth_user,
        asset_code="600100.SH",
        status="pending",
        created_at=now - timedelta(hours=1),
    )
    _create_signal(
        user=auth_user,
        asset_code="600101.SH",
        status="rejected",
        created_at=now - timedelta(hours=2),
    )
    _create_signal(
        user=auth_user,
        asset_code="600102.SH",
        status="invalidated",
        created_at=now - timedelta(hours=3),
    )
    _create_signal(
        user=other_user,
        asset_code="000001.SZ",
        status="approved",
        created_at=now,
    )
    _create_signal(
        user=other_user,
        asset_code="000002.SZ",
        status="pending",
        created_at=now - timedelta(hours=1),
    )

    use_case = object.__new__(GetDashboardDataUseCase)
    use_case.signal_repo = DjangoSignalRepository()

    def build_signal_dashboard_data(user_id: int) -> SimpleNamespace:
        return SimpleNamespace(
            signal_stats=use_case._calculate_signal_stats(user_id),
            active_signals=use_case._get_user_signals(user_id),
        )

    monkeypatch.setattr(
        "apps.dashboard.interface.views._build_dashboard_data",
        build_signal_dashboard_data,
    )
    monkeypatch.setattr(
        "apps.asset_analysis.application.asset_name_service.resolve_asset_names",
        lambda codes: {code: f"名称-{code}" for code in codes},
    )

    own_response = authenticated_client.get(
        "/api/dashboard/v1/signal-status/",
        {"limit": 200},
    )

    assert own_response.status_code == 200
    assert own_response["Content-Type"].startswith("application/json")
    own_payload = own_response.json()
    assert own_payload["stats"] == {
        "total": 10,
        "approved": 7,
        "pending": 1,
        "rejected": 1,
    }
    assert own_payload["stats_series"] == [
        {"status": "全部", "count": 10},
        {"status": "已批准", "count": 7},
        {"status": "待审核", "count": 1},
        {"status": "已拒绝", "count": 1},
    ]
    expected_recent_codes = list(reversed(approved_codes[-5:]))
    assert [row["asset_code"] for row in own_payload["signals"]] == expected_recent_codes
    assert all(row["status"] == "approved" for row in own_payload["signals"])
    assert all(row["asset_name"] == f"名称-{row['asset_code']}" for row in own_payload["signals"])
    assert [row["created_at"] for row in own_payload["signals"]] == [
        approved_created_at[code].date().isoformat() for code in expected_recent_codes
    ]
    assert own_payload["limit"] == 200
    assert len(own_payload["signals"]) == 5

    short_response = authenticated_client.get(
        "/api/dashboard/v1/signal-status/",
        {"limit": 2},
    )
    assert short_response.status_code == 200
    assert [row["asset_code"] for row in short_response.json()["signals"]] == (
        expected_recent_codes[:2]
    )

    authenticated_client.force_authenticate(user=other_user)
    other_response = authenticated_client.get(
        "/api/dashboard/v1/signal-status/",
        {"limit": 5},
    )

    assert other_response.status_code == 200
    other_payload = other_response.json()
    assert other_payload["stats"] == {
        "total": 2,
        "approved": 1,
        "pending": 1,
        "rejected": 0,
    }
    assert other_payload["stats_series"] == [
        {"status": "全部", "count": 2},
        {"status": "已批准", "count": 1},
        {"status": "待审核", "count": 1},
        {"status": "已拒绝", "count": 0},
    ]
    assert [row["asset_code"] for row in other_payload["signals"]] == ["000001.SZ"]
    assert all(row["asset_code"] not in approved_codes for row in other_payload["signals"])
    assert all(row["status"] == "approved" for row in other_payload["signals"])
    assert other_payload["limit"] == 5
