"""Safety regressions for public share persistence boundaries."""

from datetime import date

import pytest
from django.contrib.auth import get_user_model

from apps.share.infrastructure.models import ShareLinkModel, ShareSnapshotModel
from apps.share.infrastructure.repositories import (
    ShareApplicationRepository,
    ShareInterfaceRepository,
)
from apps.share.interface.serializers import CreateShareLinkSerializer


@pytest.fixture
def share_link(db) -> ShareLinkModel:
    owner = get_user_model().objects.create_user(
        username="share_repository_owner",
        password="testpass123",
    )
    return ShareLinkModel._default_manager.create(
        owner=owner,
        account_id=101,
        short_code="atomicshare01",
        title="Atomic Share",
        max_access_count=1,
    )


def test_access_consumption_never_exceeds_limit(share_link: ShareLinkModel) -> None:
    repository = ShareInterfaceRepository()

    assert repository.increment_share_link_access_count(share_link_id=share_link.id)
    assert not repository.increment_share_link_access_count(share_link_id=share_link.id)

    share_link.refresh_from_db()
    assert share_link.access_count == 1
    assert share_link.last_accessed_at is not None


def test_revoked_link_cannot_consume_access(share_link: ShareLinkModel) -> None:
    share_link.status = "revoked"
    share_link.save(update_fields=["status"])

    consumed = ShareInterfaceRepository().increment_share_link_access_count(
        share_link_id=share_link.id
    )

    assert consumed is False
    share_link.refresh_from_db()
    assert share_link.access_count == 0


def test_snapshot_versions_are_allocated_under_link_lock(
    share_link: ShareLinkModel,
) -> None:
    repository = ShareApplicationRepository()

    first_id = repository.create_snapshot(
        share_link_id=share_link.id,
        summary_payload={},
        performance_payload={},
        positions_payload={},
        transactions_payload={},
        decision_payload={},
        source_range_start=date(2026, 7, 1),
        source_range_end=date(2026, 7, 26),
    )
    second_id = repository.create_snapshot(
        share_link_id=share_link.id,
        summary_payload={},
        performance_payload={},
        positions_payload={},
        transactions_payload={},
        decision_payload={},
    )

    assert first_id is not None
    assert second_id is not None
    assert list(
        ShareSnapshotModel._default_manager.filter(share_link=share_link).values_list(
            "snapshot_version", flat=True
        )
    ) == [2, 1]


def test_create_serializer_fails_closed_without_authenticated_owner() -> None:
    serializer = CreateShareLinkSerializer(
        data={
            "account_id": 101,
            "title": "No owner context",
        }
    )

    assert serializer.is_valid() is False
    assert serializer.errors["account_id"] == ["缺少有效的账户所有者身份"]
