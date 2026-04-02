"""
Share Domain Entities Tests

Tests for Domain layer entities (pure Python, no Django dependencies).
"""

from dataclasses import FrozenInstanceError
from datetime import UTC, datetime, timedelta, timezone

import pytest

from apps.share.domain.entities import (
    AccessResultStatus,
    ShareAccessLogEntity,
    ShareConfig,
    ShareLevel,
    ShareLinkEntity,
    ShareSnapshotEntity,
    ShareStatus,
    ShareTheme,
)


class TestShareLevel:
    """Test ShareLevel enum."""

    def test_share_level_values(self):
        """Test ShareLevel enum has correct values."""
        assert ShareLevel.SNAPSHOT.value == "snapshot"
        assert ShareLevel.OBSERVER.value == "observer"
        assert ShareLevel.RESEARCH.value == "research"


class TestShareStatus:
    """Test ShareStatus enum."""

    def test_share_status_values(self):
        """Test ShareStatus enum has correct values."""
        assert ShareStatus.ACTIVE.value == "active"
        assert ShareStatus.REVOKED.value == "revoked"
        assert ShareStatus.EXPIRED.value == "expired"
        assert ShareStatus.DISABLED.value == "disabled"


class TestAccessResultStatus:
    """Test AccessResultStatus enum."""

    def test_access_result_status_values(self):
        """Test AccessResultStatus enum has correct values."""
        assert AccessResultStatus.SUCCESS.value == "success"
        assert AccessResultStatus.PASSWORD_REQUIRED.value == "password_required"
        assert AccessResultStatus.PASSWORD_INVALID.value == "password_invalid"
        assert AccessResultStatus.EXPIRED.value == "expired"
        assert AccessResultStatus.REVOKED.value == "revoked"
        assert AccessResultStatus.MAX_COUNT_EXCEEDED.value == "max_count_exceeded"
        assert AccessResultStatus.NOT_FOUND.value == "not_found"


class TestShareLinkEntity:
    """Test ShareLinkEntity."""

    @pytest.fixture
    def base_entity(self):
        """Create a base entity for testing."""
        now = datetime.now(UTC)
        return ShareLinkEntity(
            id=None,
            owner_id=1,
            account_id=1,
            short_code="TEST123456",
            title="Test Share",
            subtitle="Test Subtitle",
            theme=ShareTheme.BLOOMBERG,
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

    def test_entity_is_immutable(self, base_entity):
        """Test entity is frozen (immutable)."""
        with pytest.raises(FrozenInstanceError):
            base_entity.title = "New Title"

    def test_is_accessible_active_no_restrictions(self, base_entity):
        """Test is_accessible returns True for active link without restrictions."""
        now = datetime.now(UTC)
        is_accessible, status = base_entity.is_accessible(now)

        assert is_accessible is True
        assert status == AccessResultStatus.SUCCESS

    def test_is_accessible_revoked(self, base_entity):
        """Test is_accessible returns False for revoked link."""
        now = datetime.now(UTC)
        entity = ShareLinkEntity(**{**base_entity.__dict__, "status": ShareStatus.REVOKED})
        is_accessible, status = entity.is_accessible(now)

        assert is_accessible is False
        assert status == AccessResultStatus.REVOKED

    def test_is_accessible_expired(self, base_entity):
        """Test is_accessible returns False for expired link."""
        now = datetime.now(UTC)
        past = now - timedelta(hours=1)
        entity = ShareLinkEntity(**{**base_entity.__dict__, "expires_at": past})
        is_accessible, status = entity.is_accessible(now)

        assert is_accessible is False
        assert status == AccessResultStatus.EXPIRED

    def test_is_accessible_max_count_exceeded(self, base_entity):
        """Test is_accessible returns False when max count exceeded."""
        now = datetime.now(UTC)
        entity = ShareLinkEntity(
            **{**base_entity.__dict__, "max_access_count": 10, "access_count": 10}
        )
        is_accessible, status = entity.is_accessible(now)

        assert is_accessible is False
        assert status == AccessResultStatus.MAX_COUNT_EXCEEDED

    def test_is_accessible_expires_at_future(self, base_entity):
        """Test is_accessible returns True when expires_at is in future."""
        now = datetime.now(UTC)
        future = now + timedelta(hours=1)
        entity = ShareLinkEntity(**{**base_entity.__dict__, "expires_at": future})
        is_accessible, status = entity.is_accessible(now)

        assert is_accessible is True
        assert status == AccessResultStatus.SUCCESS

    def test_requires_password_true(self, base_entity):
        """Test requires_password returns True when password_hash is set."""
        entity = ShareLinkEntity(**{**base_entity.__dict__, "password_hash": "hashed_password"})
        assert entity.requires_password() is True

    def test_requires_password_false(self, base_entity):
        """Test requires_password returns False when no password."""
        assert base_entity.requires_password() is False

    def test_requires_password_empty_string(self, base_entity):
        """Test requires_password returns False for empty password_hash."""
        entity = ShareLinkEntity(**{**base_entity.__dict__, "password_hash": ""})
        assert entity.requires_password() is False

    def test_get_visibility_config(self, base_entity):
        """Test get_visibility_config returns correct visibility flags."""
        config = base_entity.get_visibility_config()

        assert config == {
            "amounts": True,
            "positions": True,
            "transactions": True,
            "decision_summary": True,
            "decision_evidence": False,
            "invalidation_logic": False,
        }


class TestShareSnapshotEntity:
    """Test ShareSnapshotEntity."""

    @pytest.fixture
    def snapshot_entity(self):
        """Create a snapshot entity for testing."""
        now = datetime.now(UTC)
        return ShareSnapshotEntity(
            id=None,
            share_link_id=1,
            snapshot_version=1,
            summary_payload={"total_value": 100000},
            performance_payload={"sharpe_ratio": 1.5},
            positions_payload={"items": []},
            transactions_payload={"items": []},
            decision_payload={},
            generated_at=now,
            source_range_start=None,
            source_range_end=None,
        )

    def test_entity_is_immutable(self, snapshot_entity):
        """Test snapshot entity is frozen."""
        with pytest.raises(FrozenInstanceError):
            snapshot_entity.snapshot_version = 2

    def test_is_empty_true(self):
        """Test is_empty returns True when all payloads are empty."""
        now = datetime.now(UTC)
        entity = ShareSnapshotEntity(
            id=None,
            share_link_id=1,
            snapshot_version=1,
            summary_payload={},
            performance_payload={},
            positions_payload={},
            transactions_payload={},
            decision_payload={},
            generated_at=now,
            source_range_start=None,
            source_range_end=None,
        )
        assert entity.is_empty() is True

    def test_is_empty_false(self, snapshot_entity):
        """Test is_empty returns False when any payload has data."""
        assert snapshot_entity.is_empty() is False


class TestShareAccessLogEntity:
    """Test ShareAccessLogEntity."""

    @pytest.fixture
    def log_entity(self):
        """Create a log entity for testing."""
        now = datetime.now(UTC)
        return ShareAccessLogEntity(
            id=None,
            share_link_id=1,
            accessed_at=now,
            ip_hash="abc123",
            user_agent="Mozilla/5.0",
            referer="https://example.com",
            is_verified=True,
            result_status=AccessResultStatus.SUCCESS,
        )

    def test_entity_is_immutable(self, log_entity):
        """Test log entity is frozen."""
        with pytest.raises(FrozenInstanceError):
            log_entity.ip_hash = "xyz789"

    def test_is_successful_access_true(self, log_entity):
        """Test is_successful_access returns True for success status."""
        assert log_entity.is_successful_access() is True

    def test_is_successful_access_false(self, log_entity):
        """Test is_successful_access returns False for other status."""
        entity = ShareAccessLogEntity(
            **{**log_entity.__dict__, "result_status": AccessResultStatus.PASSWORD_INVALID}
        )
        assert entity.is_successful_access() is False


class TestShareConfig:
    """Test ShareConfig value object."""

    def test_default_values(self):
        """Test ShareConfig has correct default values."""
        config = ShareConfig(title="Test Share")

        assert config.title == "Test Share"
        assert config.subtitle is None
        assert config.share_level == ShareLevel.SNAPSHOT
        assert config.password is None
        assert config.expires_at is None
        assert config.max_access_count is None
        assert config.allow_indexing is False
        assert config.show_amounts is False
        assert config.show_positions is True
        assert config.show_transactions is True
        assert config.show_decision_summary is True
        assert config.show_decision_evidence is False
        assert config.show_invalidation_logic is False

    def test_get_visibility_flags(self):
        """Test get_visibility_flags returns correct flags."""
        config = ShareConfig(
            title="Test",
            show_amounts=False,
            show_positions=True,
            show_transactions=False,
        )
        flags = config.get_visibility_flags()

        assert flags == {
            "show_amounts": False,
            "show_positions": True,
            "show_transactions": False,
            "show_decision_summary": True,
            "show_decision_evidence": False,
            "show_invalidation_logic": False,
        }

    def test_requires_password_true(self):
        """Test requires_password returns True when password is set."""
        config = ShareConfig(title="Test", password="secret123")
        assert config.requires_password() is True

    def test_requires_password_false(self):
        """Test requires_password returns False when no password."""
        config = ShareConfig(title="Test")
        assert config.requires_password() is False

    def test_requires_password_empty_string(self):
        """Test requires_password returns False for empty password."""
        config = ShareConfig(title="Test", password="")
        assert config.requires_password() is False
