"""Public source-bound institutional-calendar task composition."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime

from django.conf import settings
from django.utils import timezone

from apps.data_center.application.institutional_calendar_task import ReadInstitutionalCalendarTask
from apps.data_center.infrastructure.institutional_calendar_configuration import (
    DjangoInstitutionalCalendarPolicyReader,
)
from apps.data_center.infrastructure.institutional_calendar_originals import (
    DjangoInstitutionalOriginalRepository,
)
from apps.data_center.institutional_calendar_composition import make_institutional_calendar_query


def make_institutional_calendar_task(
    *, using: str = "default", clock: Callable[[], datetime] = timezone.now
) -> ReadInstitutionalCalendarTask:
    """Bind the public read to configured source timezone and independently checked bytes."""
    policies = DjangoInstitutionalCalendarPolicyReader(using=using)
    policy = policies.read_policy()
    timezone_name = settings.TIME_ZONE if policy is None else policy.timezone_name
    return ReadInstitutionalCalendarTask(
        make_institutional_calendar_query(using=using, timezone_name=timezone_name),
        DjangoInstitutionalOriginalRepository(using=using),
        policies,
        policy=policy,
        clock=clock,
    )


__all__ = ["make_institutional_calendar_task"]
