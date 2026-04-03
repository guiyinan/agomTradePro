"""
Share ORM Models Tests

Tests for Infrastructure layer models.
"""

from datetime import timedelta

import pytest
from django.contrib.auth.hashers import check_password
from django.core.exceptions import ValidationError
from django.utils import timezone

from apps.share.infrastructure.models import (
    ShareAccessLogModel,
    ShareDisclaimerConfigModel,
    ShareLinkModel,
    ShareSnapshotModel,
)


class TestShareLinkModel:
    """Test ShareLinkModel."""

    def test_create_minimal_share_link(self, test_user, test_account):
        """Test creating a share link with minimal required fields."""
        link = ShareLinkModel.objects.create(
            owner=test_user,
            account_id=test_account.id,
            short_code="TEST123456",
            title="Test Share",
        )

        assert link.id is not None
        assert link.short_code == "TEST123456"
        assert link.title == "Test Share"
        assert link.status == "active"
        assert link.share_level == "snapshot"
        assert link.access_count == 0
        assert link.allow_indexing is False

    def test_str_representation(self, active_share_link):
        """Test __str__ method returns correct format."""
        str_repr = str(active_share_link)
        assert "Test Share Link" in str_repr
        assert "ABC1234567" in str_repr

    def test_default_values(self, test_user, test_account):
        """Test default field values."""
        link = ShareLinkModel.objects.create(
            owner=test_user,
            account_id=test_account.id,
            short_code="TEST123456",
            title="Test",
        )

        assert link.status == "active"
        assert link.share_level == "snapshot"
        assert link.access_count == 0
        assert link.allow_indexing is False
        assert link.show_amounts is False
        assert link.show_positions is True
        assert link.show_transactions is True
        assert link.show_decision_summary is True
        assert link.show_decision_evidence is False
        assert link.show_invalidation_logic is False

    def test_unique_short_code(self, test_user, test_account):
        """Test short_code must be unique."""
        ShareLinkModel.objects.create(
            owner=test_user,
            account_id=test_account.id,
            short_code="DUPLICATE",
            title="First",
        )

        with pytest.raises(Exception):  # IntegrityError
            ShareLinkModel.objects.create(
                owner=test_user,
                account_id=test_account.id,
                short_code="DUPLICATE",
                title="Second",
            )

    def test_is_accessible_true(self, active_share_link):
        """Test is_accessible returns True for active link."""
        assert active_share_link.is_accessible() is True

    def test_is_accessible_false_revoked(self, revoked_share_link):
        """Test is_accessible returns False for revoked link."""
        assert revoked_share_link.is_accessible() is False

    def test_is_accessible_false_expired(self, expired_share_link):
        """Test is_accessible returns False for expired link."""
        assert expired_share_link.is_accessible() is False

    def test_is_accessible_false_max_count(self, max_count_share_link):
        """Test is_accessible returns False when max count reached."""
        assert max_count_share_link.is_accessible() is False

    def test_requires_password_true(self, password_protected_share_link):
        """Test requires_password returns True when password is set."""
        assert password_protected_share_link.requires_password() is True

    def test_requires_password_false(self, active_share_link):
        """Test requires_password returns False when no password."""
        assert active_share_link.requires_password() is False

    def test_increment_access_count(self, active_share_link):
        """Test increment_access_count increments counter and updates timestamp."""
        initial_count = active_share_link.access_count
        initial_time = active_share_link.last_accessed_at

        active_share_link.increment_access_count()

        active_share_link.refresh_from_db()
        assert active_share_link.access_count == initial_count + 1
        assert active_share_link.last_accessed_at is not None

    def test_clean_validates_max_access_count(self, test_user, test_account):
        """Test clean validates max_access_count for snapshot mode."""
        link = ShareLinkModel(
            owner=test_user,
            account_id=test_account.id,
            short_code="TEST123456",
            title="Test",
            share_level="snapshot",
            max_access_count=0,
        )

        with pytest.raises(ValidationError) as exc_info:
            link.clean()

        assert "max_access_count" in str(exc_info.value)

    def test_clean_validates_expires_at_future(self, test_user, test_account):
        """Test clean validates expires_at is in the future."""
        link = ShareLinkModel(
            owner=test_user,
            account_id=test_account.id,
            short_code="TEST123456",
            title="Test",
            expires_at=timezone.now() - timedelta(hours=1),
        )

        with pytest.raises(ValidationError) as exc_info:
            link.clean()

        assert "expires_at" in str(exc_info.value)

    def test_share_level_choices(self, test_user, test_account):
        """Test share_level accepts valid choices."""
        valid_levels = ["snapshot", "observer", "research"]

        for level in valid_levels:
            link = ShareLinkModel.objects.create(
                owner=test_user,
                account_id=test_account.id,
                short_code=f"TEST{level}",
                title=f"Test {level}",
                share_level=level,
            )
            assert link.share_level == level

    def test_status_choices(self, test_user, test_account):
        """Test status accepts valid choices."""
        valid_statuses = ["active", "revoked", "expired", "disabled"]

        for status_value in valid_statuses:
            link = ShareLinkModel.objects.create(
                owner=test_user,
                account_id=test_account.id,
                short_code=f"TEST{status_value}",
                title=f"Test {status_value}",
                status=status_value,
            )
            assert link.status == status_value


class TestShareSnapshotModel:
    """Test ShareSnapshotModel."""

    def test_create_snapshot(self, active_share_link):
        """Test creating a snapshot."""
        snapshot = ShareSnapshotModel.objects.create(
            share_link=active_share_link,
            snapshot_version=1,
            summary_payload={"total_value": 100000},
            performance_payload={"sharpe_ratio": 1.5},
        )

        assert snapshot.id is not None
        assert snapshot.snapshot_version == 1
        assert snapshot.summary_payload == {"total_value": 100000}

    def test_auto_version_increment(self, active_share_link):
        """Test snapshot versions must be explicitly set to be unique."""
        snapshot1 = ShareSnapshotModel.objects.create(
            share_link=active_share_link,
            snapshot_version=1,
            summary_payload={"v": 1},
        )
        snapshot2 = ShareSnapshotModel.objects.create(
            share_link=active_share_link,
            snapshot_version=2,
            summary_payload={"v": 2},
        )

        assert snapshot1.snapshot_version != snapshot2.snapshot_version

    def test_unique_together_share_link_version(self, active_share_link):
        """Test share_link + snapshot_version must be unique."""
        ShareSnapshotModel.objects.create(
            share_link=active_share_link,
            snapshot_version=1,
            summary_payload={"first": True},
        )

        with pytest.raises(Exception):  # IntegrityError
            ShareSnapshotModel.objects.create(
                share_link=active_share_link,
                snapshot_version=1,
                summary_payload={"duplicate": True},
            )

    def test_default_json_payloads(self, active_share_link):
        """Test default JSON payloads are empty dicts."""
        snapshot = ShareSnapshotModel.objects.create(
            share_link=active_share_link,
            snapshot_version=1,
        )

        assert snapshot.summary_payload == {}
        assert snapshot.performance_payload == {}
        assert snapshot.positions_payload == {}
        assert snapshot.transactions_payload == {}
        assert snapshot.decision_payload == {}

    def test_str_representation(self, test_snapshot):
        """Test __str__ method returns correct format."""
        str_repr = str(test_snapshot)
        assert "Snapshot v1" in str_repr
        assert "Test Share Link" in str_repr

    def test_is_empty_true(self, active_share_link):
        """Test is_empty returns True when all payloads are empty."""
        snapshot = ShareSnapshotModel.objects.create(
            share_link=active_share_link,
            snapshot_version=1,
        )
        assert snapshot.is_empty() is True

    def test_is_empty_false(self, test_snapshot):
        """Test is_empty returns False when any payload has data."""
        assert test_snapshot.is_empty() is False

    def test_ordering(self, active_share_link):
        """Test snapshots are ordered by -snapshot_version."""
        ShareSnapshotModel.objects.create(
            share_link=active_share_link,
            snapshot_version=3,
            summary_payload={"v": 3},
        )
        ShareSnapshotModel.objects.create(
            share_link=active_share_link,
            snapshot_version=1,
            summary_payload={"v": 1},
        )
        ShareSnapshotModel.objects.create(
            share_link=active_share_link,
            snapshot_version=2,
            summary_payload={"v": 2},
        )

        snapshots = ShareSnapshotModel.objects.filter(share_link=active_share_link)

        assert snapshots[0].snapshot_version == 3
        assert snapshots[1].snapshot_version == 2
        assert snapshots[2].snapshot_version == 1


class TestShareAccessLogModel:
    """Test ShareAccessLogModel."""

    def test_create_log(self, active_share_link):
        """Test creating an access log."""
        log = ShareAccessLogModel.objects.create(
            share_link=active_share_link,
            ip_hash="abc123def456",
            user_agent="Mozilla/5.0",
            referer="https://example.com",
            is_verified=True,
            result_status="success",
        )

        assert log.id is not None
        assert log.ip_hash == "abc123def456"
        assert log.is_verified is True
        assert log.result_status == "success"

    def test_str_representation(self, active_share_link):
        """Test __str__ method returns correct format."""
        log = ShareAccessLogModel.objects.create(
            share_link=active_share_link,
            ip_hash="abc123",
            result_status="success",
        )

        str_repr = str(log)
        assert "ABC1234567" in str_repr

    def test_is_successful_true(self, active_share_link):
        """Test is_successful returns True for success status."""
        log = ShareAccessLogModel.objects.create(
            share_link=active_share_link,
            ip_hash="abc123",
            result_status="success",
        )
        assert log.is_successful() is True

    def test_is_successful_false(self, active_share_link):
        """Test is_successful returns False for non-success status."""
        log = ShareAccessLogModel.objects.create(
            share_link=active_share_link,
            ip_hash="abc123",
            result_status="password_invalid",
        )
        assert log.is_successful() is False

    def test_result_status_choices(self, active_share_link):
        """Test result_status accepts all valid choices."""
        valid_statuses = [
            "success",
            "password_required",
            "password_invalid",
            "expired",
            "revoked",
            "max_count_exceeded",
            "not_found",
        ]

        for status_value in valid_statuses:
            log = ShareAccessLogModel.objects.create(
                share_link=active_share_link,
                ip_hash=f"test_{status_value}",
                result_status=status_value,
            )
            assert log.result_status == status_value

    def test_auto_timestamp(self, active_share_link):
        """Test accessed_at is auto-set to current time."""
        before = timezone.now()
        log = ShareAccessLogModel.objects.create(
            share_link=active_share_link,
            ip_hash="test123",
            result_status="success",
        )
        after = timezone.now()

        assert before <= log.accessed_at <= after

    def test_ordering(self, active_share_link):
        """Test logs are ordered by -accessed_at."""
        log1 = ShareAccessLogModel.objects.create(
            share_link=active_share_link,
            ip_hash="first",
            result_status="success",
        )

        # Small delay to ensure different timestamps
        import time

        time.sleep(0.01)

        log2 = ShareAccessLogModel.objects.create(
            share_link=active_share_link,
            ip_hash="second",
            result_status="success",
        )

        logs = ShareAccessLogModel.objects.filter(share_link=active_share_link)

        assert logs[0].id == log2.id
        assert logs[1].id == log1.id


class TestShareDisclaimerConfigModel:
    def test_get_solo_creates_default_config(self, db):
        config = ShareDisclaimerConfigModel.get_solo()

        assert config.singleton_key == "default"
        assert config.is_enabled is True
        assert config.modal_enabled is True
        assert len(config.lines) >= 4

    def test_get_solo_returns_same_record(self, db):
        first = ShareDisclaimerConfigModel.get_solo()
        second = ShareDisclaimerConfigModel.get_solo()

        assert first.id == second.id
