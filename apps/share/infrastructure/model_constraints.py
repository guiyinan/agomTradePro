"""Database constraints for public Share persistence models."""

from django.db import models
from django.db.models import F, Q
from django.db.models.constraints import BaseConstraint

SHARE_LINK_CONSTRAINTS: list[BaseConstraint] = [
    models.CheckConstraint(condition=Q(account_id__gte=1), name="share_link_account_positive"),
    models.CheckConstraint(condition=Q(access_count__gte=0), name="share_link_access_nonnegative"),
    models.CheckConstraint(
        condition=Q(max_access_count__isnull=True) | Q(max_access_count__gte=1),
        name="share_link_max_access_positive",
    ),
    models.CheckConstraint(
        condition=Q(max_access_count__isnull=True) | Q(access_count__lte=F("max_access_count")),
        name="share_link_access_within_limit",
    ),
]

SHARE_SNAPSHOT_CONSTRAINTS: list[BaseConstraint] = [
    models.CheckConstraint(
        condition=Q(snapshot_version__gte=1),
        name="share_snapshot_version_positive",
    ),
    models.CheckConstraint(
        condition=(Q(source_range_start__isnull=True) & Q(source_range_end__isnull=True))
        | (
            Q(source_range_start__isnull=False)
            & Q(source_range_end__isnull=False)
            & Q(source_range_end__gte=F("source_range_start"))
        ),
        name="share_snapshot_source_range_valid",
    ),
]

SHARE_ACCESS_LOG_CONSTRAINTS: list[BaseConstraint] = [
    models.CheckConstraint(
        condition=Q(
            result_status__in=[
                "success",
                "password_required",
                "password_invalid",
                "expired",
                "revoked",
                "max_count_exceeded",
                "not_found",
            ]
        ),
        name="share_access_log_status_valid",
    ),
]

SHARE_DISCLAIMER_CONSTRAINTS: list[BaseConstraint] = [
    models.CheckConstraint(
        condition=Q(singleton_key="default"),
        name="share_disclaimer_default_singleton",
    ),
]

__all__ = [
    "SHARE_ACCESS_LOG_CONSTRAINTS",
    "SHARE_DISCLAIMER_CONSTRAINTS",
    "SHARE_LINK_CONSTRAINTS",
    "SHARE_SNAPSHOT_CONSTRAINTS",
]
