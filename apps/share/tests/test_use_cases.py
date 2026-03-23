"""
Share Application Use Cases Tests

Tests for Application layer use cases.
"""
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest
from django.contrib.auth.hashers import check_password
from django.core.exceptions import ValidationError
from django.utils import timezone as django_timezone

from apps.share.application.use_cases import (
    ShareAccessUseCases,
    ShareLinkUseCases,
    ShareSnapshotUseCases,
)
from apps.share.domain.entities import AccessResultStatus, ShareLevel, ShareStatus
from apps.share.infrastructure.models import (
    ShareAccessLogModel,
    ShareLinkModel,
    ShareSnapshotModel,
)


class TestShareLinkUseCases:
    """Test ShareLinkUseCases."""

    @pytest.fixture
    def use_case(self):
        """Create use case instance."""
        return ShareLinkUseCases()

    def test_create_share_link_minimal(self, use_case, test_user, test_account):
        """Test creating a share link with minimal parameters."""
        entity = use_case.create_share_link(
            owner_id=test_user.id,
            account_id=test_account.id,
            title="Test Share",
        )

        assert entity.id is not None
        assert entity.title == "Test Share"
        assert entity.share_level == ShareLevel.SNAPSHOT
        assert entity.status == ShareStatus.ACTIVE
        assert entity.password_hash is None
        assert entity.access_count == 0

        # Verify in database
        model = ShareLinkModel.objects.get(id=entity.id)
        assert model.title == "Test Share"

    def test_create_share_link_with_password(self, use_case, test_user, test_account):
        """Test creating a share link with password protection."""
        entity = use_case.create_share_link(
            owner_id=test_user.id,
            account_id=test_account.id,
            title="Protected Share",
            password="secret123",
        )

        assert entity.password_hash is not None
        assert entity.requires_password() is True

        # Verify password is correctly hashed
        model = ShareLinkModel.objects.get(id=entity.id)
        assert check_password("secret123", model.password_hash) is True

    def test_create_share_link_with_expiry(self, use_case, test_user, test_account):
        """Test creating a share link with expiry."""
        expires_at = django_timezone.now() + timedelta(days=7)
        entity = use_case.create_share_link(
            owner_id=test_user.id,
            account_id=test_account.id,
            title="Expiring Share",
            expires_at=expires_at,
        )

        assert entity.expires_at is not None

    def test_create_share_link_with_max_access_count(
        self, use_case, test_user, test_account
    ):
        """Test creating a share link with max access count."""
        entity = use_case.create_share_link(
            owner_id=test_user.id,
            account_id=test_account.id,
            title="Limited Share",
            max_access_count=100,
        )

        assert entity.max_access_count == 100

    def test_create_share_link_invalid_account(self, use_case, test_user):
        """Test creating share link with non-existent account raises error."""
        with pytest.raises(ValidationError) as exc_info:
            use_case.create_share_link(
                owner_id=test_user.id,
                account_id=99999,
                title="Invalid Account",
            )

        assert "account_id" in str(exc_info.value)

    def test_create_share_link_invalid_user(self, use_case, test_account):
        """Test creating share link with non-existent user raises error."""
        with pytest.raises(ValidationError) as exc_info:
            use_case.create_share_link(
                owner_id=99999,
                account_id=test_account.id,
                title="Invalid User",
            )

        assert "owner_id" in str(exc_info.value)

    def test_create_share_link_custom_short_code(
        self, use_case, test_user, test_account
    ):
        """Test creating share link with custom short code."""
        entity = use_case.create_share_link(
            owner_id=test_user.id,
            account_id=test_account.id,
            title="Custom Code",
            short_code="CUSTOM12",
        )

        assert entity.short_code == "CUSTOM12"

    def test_create_share_link_duplicate_short_code(
        self, use_case, test_user, test_account, active_share_link
    ):
        """Test creating share link with duplicate short code raises error."""
        with pytest.raises(ValidationError) as exc_info:
            use_case.create_share_link(
                owner_id=test_user.id,
                account_id=test_account.id,
                title="Duplicate",
                short_code=active_share_link.short_code,
            )

        assert "short_code" in str(exc_info.value)

    def test_get_share_link(self, use_case, active_share_link):
        """Test getting a share link by ID."""
        entity = use_case.get_share_link(active_share_link.id)

        assert entity is not None
        assert entity.id == active_share_link.id
        assert entity.title == active_share_link.title

    def test_get_share_link_not_found(self, use_case):
        """Test getting non-existent share link returns None."""
        entity = use_case.get_share_link(99999)
        assert entity is None

    def test_get_share_link_by_code(self, use_case, active_share_link):
        """Test getting a share link by short code."""
        entity = use_case.get_share_link_by_code(active_share_link.short_code)

        assert entity is not None
        assert entity.short_code == active_share_link.short_code

    def test_get_share_link_by_code_not_found(self, use_case):
        """Test getting non-existent short code returns None."""
        entity = use_case.get_share_link_by_code("NONEXIST")
        assert entity is None

    def test_list_share_links_all(self, use_case, test_user, test_account):
        """Test listing all share links for a user."""
        # Create multiple share links
        for i in range(3):
            ShareLinkModel.objects.create(
                owner=test_user,
                account_id=test_account.id,
                short_code=f"TEST{i}",
                title=f"Share {i}",
            )

        entities = use_case.list_share_links(owner_id=test_user.id)
        assert len(entities) >= 3

    def test_list_share_links_filter_by_account(self, use_case, test_user):
        """Test filtering share links by account."""
        entities = use_case.list_share_links(
            owner_id=test_user.id,
            account_id=1,
        )
        # Should only return links for account_id=1
        for entity in entities:
            assert entity.account_id == 1

    def test_list_share_links_filter_by_status(self, use_case, test_user):
        """Test filtering share links by status."""
        entities = use_case.list_share_links(
            owner_id=test_user.id,
            status="active",
        )
        for entity in entities:
            assert entity.status == ShareStatus.ACTIVE

    def test_update_share_link_title(self, use_case, active_share_link, test_user):
        """Test updating share link title."""
        entity = use_case.update_share_link(
            share_link_id=active_share_link.id,
            owner_id=test_user.id,
            title="Updated Title",
        )

        assert entity.title == "Updated Title"

        # Verify in database
        active_share_link.refresh_from_db()
        assert active_share_link.title == "Updated Title"

    def test_update_share_link_password(self, use_case, active_share_link, test_user):
        """Test updating share link password."""
        entity = use_case.update_share_link(
            share_link_id=active_share_link.id,
            owner_id=test_user.id,
            password="newpassword",
        )

        assert entity.requires_password() is True

        # Verify password works
        assert use_case.verify_password(active_share_link.id, "newpassword") is True

    def test_update_share_link_remove_password(self, use_case, active_share_link, test_user):
        """Test removing password from share link."""
        # First set a password
        use_case.update_share_link(
            share_link_id=active_share_link.id,
            owner_id=test_user.id,
            password="secret",
        )

        # Then remove it
        entity = use_case.update_share_link(
            share_link_id=active_share_link.id,
            owner_id=test_user.id,
            password="",
        )

        assert entity.requires_password() is False

    def test_update_share_link_wrong_owner(self, use_case, active_share_link, other_user):
        """Test updating share link by non-owner raises error."""
        with pytest.raises(ValidationError) as exc_info:
            use_case.update_share_link(
                share_link_id=active_share_link.id,
                owner_id=other_user.id,
                title="Hacked",
            )

        assert "无权" in str(exc_info.value)

    def test_update_share_link_not_found(self, use_case, test_user):
        """Test updating non-existent share link returns None."""
        entity = use_case.update_share_link(
            share_link_id=99999,
            owner_id=test_user.id,
            title="Missing",
        )
        assert entity is None

    def test_revoke_share_link(self, use_case, active_share_link, test_user):
        """Test revoking a share link."""
        success = use_case.revoke_share_link(active_share_link.id, test_user.id)

        assert success is True

        active_share_link.refresh_from_db()
        assert active_share_link.status == "revoked"

    def test_revoke_share_link_wrong_owner(self, use_case, active_share_link, other_user):
        """Test revoking by non-owner fails."""
        success = use_case.revoke_share_link(active_share_link.id, other_user.id)
        assert success is False

    def test_revoke_share_link_not_found(self, use_case, test_user):
        """Test revoking non-existent share link fails."""
        success = use_case.revoke_share_link(99999, test_user.id)
        assert success is False

    def test_delete_share_link(self, use_case, active_share_link, test_user):
        """Test deleting a share link."""
        link_id = active_share_link.id
        success = use_case.delete_share_link(link_id, test_user.id)

        assert success is True
        assert not ShareLinkModel.objects.filter(id=link_id).exists()

    def test_delete_share_link_wrong_owner(self, use_case, active_share_link, other_user):
        """Test deleting by non-owner fails."""
        success = use_case.delete_share_link(active_share_link.id, other_user.id)
        assert success is False

    def test_verify_password_correct(self, use_case, password_protected_share_link):
        """Test password verification with correct password."""
        result = use_case.verify_password(password_protected_share_link.id, "testpass")
        assert result is True

    def test_verify_password_incorrect(self, use_case, password_protected_share_link):
        """Test password verification with incorrect password."""
        result = use_case.verify_password(password_protected_share_link.id, "wrongpass")
        assert result is False

    def test_verify_password_no_password(self, use_case, active_share_link):
        """Test password verification when no password is set."""
        result = use_case.verify_password(active_share_link.id, "anything")
        assert result is True


class TestShareSnapshotUseCases:
    """Test ShareSnapshotUseCases."""

    @pytest.fixture
    def use_case(self):
        """Create use case instance."""
        return ShareSnapshotUseCases()

    def test_create_snapshot(self, use_case, active_share_link):
        """Test creating a snapshot."""
        snapshot_id = use_case.create_snapshot(
            share_link_id=active_share_link.id,
            summary_payload={"total_value": 100000},
            performance_payload={"sharpe_ratio": 1.5},
            positions_payload={"items": []},
            transactions_payload={"items": []},
            decision_payload={},
        )

        assert snapshot_id is not None

        snapshot = ShareSnapshotModel.objects.get(id=snapshot_id)
        assert snapshot.snapshot_version == 1
        assert snapshot.summary_payload == {"total_value": 100000}

    def test_create_snapshot_increments_version(
        self, use_case, active_share_link
    ):
        """Test snapshot versions increment automatically."""
        use_case.create_snapshot(
            share_link_id=active_share_link.id,
            summary_payload={"v": 1},
            performance_payload={},
            positions_payload={},
            transactions_payload={},
            decision_payload={},
        )

        use_case.create_snapshot(
            share_link_id=active_share_link.id,
            summary_payload={"v": 2},
            performance_payload={},
            positions_payload={},
            transactions_payload={},
            decision_payload={},
        )

        snapshots = ShareSnapshotModel.objects.filter(
            share_link_id=active_share_link.id
        )
        assert snapshots.count() == 2
        assert snapshots[0].snapshot_version == 2  # Latest first

    def test_create_snapshot_updates_last_snapshot_at(
        self, use_case, active_share_link
    ):
        """Test creating snapshot updates share_link's last_snapshot_at."""
        assert active_share_link.last_snapshot_at is None

        use_case.create_snapshot(
            share_link_id=active_share_link.id,
            summary_payload={},
            performance_payload={},
            positions_payload={},
            transactions_payload={},
            decision_payload={},
        )

        active_share_link.refresh_from_db()
        assert active_share_link.last_snapshot_at is not None

    def test_create_snapshot_non_existent_link(self, use_case):
        """Test creating snapshot for non-existent link returns None."""
        snapshot_id = use_case.create_snapshot(
            share_link_id=99999,
            summary_payload={},
            performance_payload={},
            positions_payload={},
            transactions_payload={},
            decision_payload={},
        )
        assert snapshot_id is None

    def test_get_latest_snapshot(self, use_case, test_snapshot):
        """Test getting latest snapshot."""
        snapshot = use_case.get_latest_snapshot(test_snapshot.share_link_id)

        assert snapshot is not None
        assert snapshot["snapshot_version"] == 1
        assert snapshot["summary"]["account_name"] == "Test Account"

    def test_get_latest_snapshot_no_snapshots(self, use_case, active_share_link):
        """Test getting latest snapshot when none exist."""
        snapshot = use_case.get_latest_snapshot(active_share_link.id)
        assert snapshot is None


class TestShareAccessUseCases:
    """Test ShareAccessUseCases."""

    @pytest.fixture
    def use_case(self):
        """Create use case instance."""
        return ShareAccessUseCases()

    def test_log_access(self, use_case, active_share_link):
        """Test logging an access."""
        log_id = use_case.log_access(
            share_link_id=active_share_link.id,
            ip_address="192.168.1.1",
            user_agent="Mozilla/5.0",
            referer="https://example.com",
            result_status="success",
            is_verified=True,
        )

        assert log_id is not None

        log = ShareAccessLogModel.objects.get(id=log_id)
        assert log.share_link_id == active_share_link.id
        assert log.ip_hash is not None
        assert log.ip_hash != "192.168.1.1"  # Should be hashed
        assert log.is_verified is True
        assert log.result_status == "success"

    def test_log_access_password_invalid(self, use_case, active_share_link):
        """Test logging failed access."""
        log_id = use_case.log_access(
            share_link_id=active_share_link.id,
            ip_address="192.168.1.1",
            result_status="password_invalid",
        )

        log = ShareAccessLogModel.objects.get(id=log_id)
        assert log.result_status == "password_invalid"

    def test_get_access_logs(self, use_case, active_share_link):
        """Test getting access logs."""
        # Create some logs
        for i in range(5):
            ShareAccessLogModel.objects.create(
                share_link=active_share_link,
                ip_hash=f"test{i}",
                result_status="success",
            )

        logs = use_case.get_access_logs(active_share_link.id, limit=10)

        assert len(logs) == 5
        assert all("accessed_at" in log for log in logs)

    def test_get_access_logs_respects_limit(self, use_case, active_share_link):
        """Test get_access_logs respects limit parameter."""
        # Create many logs
        for i in range(20):
            ShareAccessLogModel.objects.create(
                share_link=active_share_link,
                ip_hash=f"test{i}",
                result_status="success",
            )

        logs = use_case.get_access_logs(active_share_link.id, limit=5)

        assert len(logs) == 5

    def test_get_access_stats(self, use_case, active_share_link):
        """Test getting access statistics."""
        # Create various logs
        ShareAccessLogModel.objects.create(
            share_link=active_share_link,
            ip_hash="ip1",
            result_status="success",
        )
        ShareAccessLogModel.objects.create(
            share_link=active_share_link,
            ip_hash="ip1",
            result_status="success",
        )
        ShareAccessLogModel.objects.create(
            share_link=active_share_link,
            ip_hash="ip2",
            result_status="password_invalid",
        )

        stats = use_case.get_access_stats(active_share_link.id)

        assert stats["total_accesses"] == 3
        assert stats["successful_accesses"] == 2
        assert stats["unique_visitors"] == 2  # ip1 and ip2

    def test_get_access_stats_empty(self, use_case, active_share_link):
        """Test getting stats when no logs exist."""
        stats = use_case.get_access_stats(active_share_link.id)

        assert stats["total_accesses"] == 0
        assert stats["successful_accesses"] == 0
        assert stats["unique_visitors"] == 0
