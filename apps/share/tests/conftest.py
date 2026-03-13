"""
Share Application Test Fixtures

Pytest conftest for share app tests.
"""
import pytest
from datetime import datetime, timedelta, date
from decimal import Decimal
from django.utils import timezone
from django.contrib.auth import get_user_model

from apps.share.domain.entities import (
    ShareLevel,
    ShareStatus,
    ShareLinkEntity,
    ShareSnapshotEntity,
    ShareAccessLogEntity,
    AccessResultStatus,
)
from apps.share.infrastructure.models import (
    ShareDisclaimerConfigModel,
    ShareLinkModel,
    ShareSnapshotModel,
    ShareAccessLogModel,
)
from apps.simulated_trading.infrastructure.models import SimulatedAccountModel

User = get_user_model()


@pytest.fixture
def db_setup(db):
    """
    Setup test database with base data.

    Creates:
    - Test user
    - Test simulated account
    """
    # Create test user
    user = User.objects.create_user(
        username="testuser",
        email="test@example.com",
        password="testpass123",
    )

    # Create test simulated account
    account = SimulatedAccountModel.objects.create(
        user=user,
        account_name="Test Account",
        account_type="simulated",
        initial_capital=Decimal("100000.00"),
        current_cash=Decimal("50000.00"),
        current_market_value=Decimal("50000.00"),
        total_value=Decimal("100000.00"),
        start_date=timezone.now().date(),
    )

    return {
        "user": user,
        "account": account,
    }


@pytest.fixture
def test_user(db):
    """Create a test user."""
    return User.objects.create_user(
        username="testuser",
        email="test@example.com",
        password="testpass123",
    )


@pytest.fixture
def other_user(db):
    """Create another test user for permission testing."""
    return User.objects.create_user(
        username="otheruser",
        email="other@example.com",
        password="otherpass123",
    )


@pytest.fixture
def test_account(test_user):
    """Create a test simulated account."""
    return SimulatedAccountModel.objects.create(
        user=test_user,
        account_name="Test Account",
        account_type="simulated",
        initial_capital=Decimal("100000.00"),
        current_cash=Decimal("50000.00"),
        current_market_value=Decimal("50000.00"),
        total_value=Decimal("100000.00"),
        start_date=timezone.now().date(),
    )


@pytest.fixture
def active_share_link(test_user, test_account):
    """Create an active share link."""
    return ShareLinkModel.objects.create(
        owner=test_user,
        account_id=test_account.id,
        short_code="ABC1234567",
        title="Test Share Link",
        subtitle="Test Subtitle",
        share_level="snapshot",
        status="active",
        expires_at=None,
        max_access_count=None,
        access_count=0,
        allow_indexing=False,
        show_amounts=True,
        show_positions=True,
        show_transactions=True,
        show_decision_summary=True,
        show_decision_evidence=False,
        show_invalidation_logic=False,
    )


@pytest.fixture
def password_protected_share_link(test_user, test_account):
    """Create a password-protected share link."""
    from django.contrib.auth.hashers import make_password
    return ShareLinkModel.objects.create(
        owner=test_user,
        account_id=test_account.id,
        short_code="PWD1234567",
        title="Protected Share Link",
        subtitle="Password Protected",
        share_level="observer",
        status="active",
        password_hash=make_password("testpass"),
        expires_at=None,
        max_access_count=None,
        access_count=5,
        allow_indexing=False,
        show_amounts=True,
        show_positions=True,
        show_transactions=True,
        show_decision_summary=True,
        show_decision_evidence=False,
        show_invalidation_logic=False,
    )


@pytest.fixture
def expired_share_link(test_user, test_account):
    """Create an expired share link."""
    return ShareLinkModel.objects.create(
        owner=test_user,
        account_id=test_account.id,
        short_code="EXP1234567",
        title="Expired Share Link",
        share_level="snapshot",
        status="active",
        expires_at=timezone.now() - timedelta(hours=1),
        max_access_count=None,
        access_count=0,
        allow_indexing=False,
        show_amounts=True,
        show_positions=True,
        show_transactions=True,
        show_decision_summary=True,
        show_decision_evidence=False,
        show_invalidation_logic=False,
    )


@pytest.fixture
def revoked_share_link(test_user, test_account):
    """Create a revoked share link."""
    return ShareLinkModel.objects.create(
        owner=test_user,
        account_id=test_account.id,
        short_code="REV1234567",
        title="Revoked Share Link",
        share_level="snapshot",
        status="revoked",
        expires_at=None,
        max_access_count=None,
        access_count=10,
        allow_indexing=False,
        show_amounts=True,
        show_positions=True,
        show_transactions=True,
        show_decision_summary=True,
        show_decision_evidence=False,
        show_invalidation_logic=False,
    )


@pytest.fixture
def max_count_share_link(test_user, test_account):
    """Create a share link with max access count reached."""
    return ShareLinkModel.objects.create(
        owner=test_user,
        account_id=test_account.id,
        short_code="MAX1234567",
        title="Max Count Share Link",
        share_level="snapshot",
        status="active",
        expires_at=None,
        max_access_count=10,
        access_count=10,
        allow_indexing=False,
        show_amounts=True,
        show_positions=True,
        show_transactions=True,
        show_decision_summary=True,
        show_decision_evidence=False,
        show_invalidation_logic=False,
    )


@pytest.fixture
def test_snapshot(active_share_link):
    """Create a test snapshot."""
    return ShareSnapshotModel.objects.create(
        share_link=active_share_link,
        snapshot_version=1,
        summary_payload={
            "account_name": "Test Account",
            "total_value": "100000.00",
            "total_return": 10.5,
        },
        performance_payload={
            "daily_returns": [0.1, 0.2, -0.1],
            "sharpe_ratio": 1.5,
        },
        positions_payload={
            "items": [
                {"asset_code": "000001.SH", "quantity": 100, "value": 5000},
            ]
        },
        transactions_payload={
            "items": [
                {"asset_code": "000001.SH", "action": "buy", "quantity": 100},
            ]
        },
        decision_payload={
            "summary": {"total_signals": 5},
            "evidence": [],
        },
        source_range_start=timezone.now().date() - timedelta(days=30),
        source_range_end=timezone.now().date(),
    )


@pytest.fixture
def share_link_entity():
    """Create a ShareLinkEntity for testing."""
    now = datetime.now(timezone.utc)
    return ShareLinkEntity(
        id=1,
        owner_id=1,
        account_id=1,
        short_code="TEST123456",
        title="Test Entity",
        subtitle=None,
        share_level=ShareLevel.SNAPSHOT,
        status=ShareStatus.ACTIVE,
        password_hash=None,
        expires_at=None,
        max_access_count=None,
        access_count=0,
        last_snapshot_at=None,
        last_accessed_at=None,
        allow_indexing=False,
        show_amounts=True,
        show_positions=True,
        show_transactions=True,
        show_decision_summary=True,
        show_decision_evidence=False,
        show_invalidation_logic=False,
        created_at=now,
        updated_at=now,
    )


@pytest.fixture
def share_disclaimer_config(db):
    return ShareDisclaimerConfigModel.get_solo()


@pytest.fixture
def api_client():
    """Create an API client for testing."""
    from rest_framework.test import APIClient
    return APIClient()


@pytest.fixture
def authenticated_api_client(api_client, test_user):
    """Create an authenticated API client."""
    api_client.force_authenticate(user=test_user)
    return api_client
