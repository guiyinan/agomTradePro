"""Integrity regressions for Share ORM models."""

from datetime import date, datetime, timedelta

import pytest
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.utils import timezone

from apps.share.infrastructure.models import (
    ShareAccessLogModel,
    ShareDisclaimerConfigModel,
    ShareLinkModel,
    ShareSnapshotModel,
)


@pytest.fixture
def share_link(db) -> ShareLinkModel:
    """Persist an unrestricted active link for model-boundary tests."""

    owner = get_user_model().objects.create_user(
        username="share_integrity_owner",
        password="testpass123",
    )
    return ShareLinkModel._default_manager.create(
        owner=owner,
        account_id=101,
        short_code="modelshare01",
        title="Model Share",
    )


def test_stale_link_instances_increment_without_lost_update(share_link: ShareLinkModel) -> None:
    first = ShareLinkModel._default_manager.get(pk=share_link.pk)
    second = ShareLinkModel._default_manager.get(pk=share_link.pk)

    assert first.increment_access_count() is True
    assert second.increment_access_count() is True

    share_link.refresh_from_db()
    assert share_link.access_count == 2
    assert share_link.last_accessed_at is not None


@pytest.mark.parametrize("state", ["revoked", "expired", "at_limit"])
def test_increment_refuses_inaccessible_link(
    share_link: ShareLinkModel,
    state: str,
) -> None:
    if state == "revoked":
        share_link.status = "revoked"
        share_link.save(update_fields=["status"])
    elif state == "expired":
        share_link.expires_at = timezone.now() - timedelta(minutes=1)
        share_link.save(update_fields=["expires_at"])
    else:
        share_link.max_access_count = 1
        share_link.access_count = 1
        share_link.save(update_fields=["max_access_count", "access_count"])

    assert share_link.increment_access_count() is False

    share_link.refresh_from_db()
    assert share_link.access_count == (1 if state == "at_limit" else 0)


def test_unsaved_link_cannot_increment() -> None:
    link = ShareLinkModel(account_id=101, short_code="unsaved01", title="Unsaved")

    with pytest.raises(ValueError, match="未保存"):
        link.increment_access_count()


def test_naive_expiry_fails_closed(share_link: ShareLinkModel) -> None:
    share_link.expires_at = datetime(2026, 7, 29, 12, 0)

    assert share_link.is_accessible() is False


@pytest.mark.parametrize(
    ("field_values", "constraint_name"),
    [
        ({"access_count": -1}, "share_link_access_nonnegative"),
        (
            {"access_count": 2, "max_access_count": 1},
            "share_link_access_within_limit",
        ),
    ],
)
def test_database_rejects_invalid_link_counters(
    share_link: ShareLinkModel,
    field_values: dict[str, int],
    constraint_name: str,
) -> None:
    with pytest.raises(IntegrityError, match=constraint_name), transaction.atomic():
        ShareLinkModel._default_manager.filter(pk=share_link.pk).update(**field_values)


@pytest.mark.parametrize(
    "snapshot_values",
    [
        {"snapshot_version": 0},
        {
            "snapshot_version": 1,
            "source_range_start": date(2026, 7, 2),
            "source_range_end": date(2026, 7, 1),
        },
        {
            "snapshot_version": 1,
            "source_range_start": date(2026, 7, 1),
            "source_range_end": None,
        },
    ],
)
def test_database_rejects_invalid_snapshot_ranges(
    share_link: ShareLinkModel,
    snapshot_values: dict[str, object],
) -> None:
    with pytest.raises(IntegrityError), transaction.atomic():
        ShareSnapshotModel._default_manager.create(
            share_link=share_link,
            **snapshot_values,
        )


@pytest.mark.parametrize("payload", [[], {"metric": float("nan")}, {"metric": float("inf")}])
def test_snapshot_clean_rejects_invalid_json_payloads(
    share_link: ShareLinkModel,
    payload: object,
) -> None:
    snapshot = ShareSnapshotModel(
        share_link=share_link,
        snapshot_version=1,
        summary_payload=payload,
    )

    with pytest.raises(ValidationError) as exc_info:
        snapshot.clean()

    assert "summary_payload" in exc_info.value.message_dict


def test_database_rejects_unknown_access_log_status(share_link: ShareLinkModel) -> None:
    with pytest.raises(IntegrityError, match="share_access_log_status_valid"), transaction.atomic():
        ShareAccessLogModel._default_manager.create(
            share_link=share_link,
            ip_hash="invalid-status",
            result_status="access_limit_reached",
        )


def test_get_solo_repairs_truthy_malformed_lines(db) -> None:
    config = ShareDisclaimerConfigModel.get_solo()
    ShareDisclaimerConfigModel._default_manager.filter(pk=config.pk).update(
        lines=["", 42],
    )

    repaired = ShareDisclaimerConfigModel.get_solo()

    assert repaired.pk == config.pk
    assert repaired.lines
    assert all(isinstance(line, str) and line.strip() for line in repaired.lines)
