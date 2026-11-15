"""Atomic operator composition for qualified retained NBS calendar originals."""

from __future__ import annotations

from dataclasses import replace
from zoneinfo import ZoneInfo

from django.db import transaction

from apps.data_center.application.institutional_calendar_sources import (
    RetainedInstitutionalOriginal,
)
from apps.data_center.domain.institutional_calendar import InstitutionalEvent
from apps.data_center.infrastructure.institutional_calendar_configuration import (
    decode_institutional_source_policy,
)
from apps.data_center.infrastructure.institutional_calendar_originals import (
    DjangoInstitutionalOriginalRepository,
)
from apps.data_center.infrastructure.institutional_calendar_repository import (
    DjangoInstitutionalCalendarRepository,
)
from apps.data_center.infrastructure.models import ProviderConfigModel
from apps.data_center.infrastructure.nbs_institutional_calendar_parser import (
    parse_nbs_actual_release,
    parse_nbs_schedule,
)
from core.exceptions import DataValidationError


def import_nbs_calendar_originals(
    *,
    schedule: RetainedInstitutionalOriginal,
    actual: RetainedInstitutionalOriginal | None,
    content_title: str,
    event_id_prefix: str,
    using: str = "default",
) -> tuple[InstitutionalEvent, ...]:
    """Validate complete originals before retaining schedules and an actual successor."""
    maximum = ProviderConfigModel._meta.get_field("name").max_length
    if maximum is not None and len(schedule.policy.source_id) > maximum:
        raise DataValidationError(
            "Source identity exceeds the provider configuration contract.",
            code="INSTITUTIONAL_ORIGINAL_INVALID",
        )
    original_repository = DjangoInstitutionalOriginalRepository(using=using)
    schedule = _reuse_capture(schedule, original_repository)
    actual = None if actual is None else _reuse_capture(actual, original_repository)
    zone = ZoneInfo(schedule.policy.timezone_name)
    document = parse_nbs_schedule(
        schedule.body, content_title=content_title, source_timezone=schedule.policy.timezone_name
    )
    inputs = tuple(
        entry.to_input(
            event_id=f"{event_id_prefix}:{entry.scheduled_at.astimezone(zone).strftime('%Y-%m')}",
            source_id=schedule.policy.source_id,
            source_event_id=f"{event_id_prefix}:{entry.scheduled_month:02d}",
            event_type=schedule.policy.event_type,
            title=content_title,
            first_seen_at=schedule.first_seen_at,
            recorded_at=schedule.recorded_at,
        )
        for entry in document.entries
    )
    events = [item.to_event() for item in inputs]
    for event in events:
        schedule.validate_event(event)
    if actual is not None:
        if actual.policy != schedule.policy:
            raise DataValidationError(
                "NBS originals use different qualification versions.",
                code="INSTITUTIONAL_ORIGINAL_INVALID",
            )
        release = parse_nbs_actual_release(actual.body, source_timezone=actual.policy.timezone_name)
        scheduled_year = release.reference_year + (1 if release.reference_month == 12 else 0)
        scheduled_month = release.reference_month % 12 + 1
        matches = [
            item
            for item in inputs
            if (item.scheduled_at.astimezone(zone).year, item.scheduled_at.astimezone(zone).month)
            == (scheduled_year, scheduled_month)
        ]
        if len(matches) != 1:
            raise DataValidationError(
                "NBS actual release has no unique scheduled month.",
                code="NBS_ACTUAL_SCHEDULE_MISMATCH",
            )
        item = matches[0]
        event = release.to_input(
            item, first_seen_at=actual.first_seen_at, recorded_at=actual.recorded_at
        ).to_event(item.to_event())
        actual.validate_event(event)
        events.append(event)
    with transaction.atomic(using=using):
        policy = schedule.policy
        provider, _ = ProviderConfigModel.objects.using(using).get_or_create(
            name=policy.source_id,
            defaults={
                "source_type": "public_document",
                "is_active": True,
                "extra_config": {
                    "institutional_calendar": {
                        "source_id": policy.source_id,
                        "event_type": policy.event_type,
                        "rule_version": policy.rule_version,
                        "catalogue_sha256": policy.catalogue_sha256,
                        "timezone_name": policy.timezone_name,
                        "attribution": policy.attribution,
                        "allowed_urls": list(policy.allowed_urls),
                        "valid_until": policy.valid_until.isoformat(),
                    }
                },
            },
        )
        if (
            provider.source_type != "public_document"
            or not provider.is_active
            or decode_institutional_source_policy(
                provider.extra_config.get("institutional_calendar")
            )
            != policy
        ):
            raise DataValidationError(
                "Existing source configuration differs; operator review required.",
                code="INSTITUTIONAL_SOURCE_POLICY_INVALID",
            )
        originals = DjangoInstitutionalOriginalRepository(using=using)
        originals.append(schedule)
        if actual is not None:
            originals.append(actual)
        repository = DjangoInstitutionalCalendarRepository(using=using)
        return tuple(repository.append(event) for event in events)


def _reuse_capture(
    original: RetainedInstitutionalOriginal, repository: DjangoInstitutionalOriginalRepository
) -> RetainedInstitutionalOriginal:
    """Preserve the original persistence clock on an identical operator retry."""
    retained = repository.read(original.sha256)
    if retained is None:
        return original
    if replace(original, recorded_at=retained.recorded_at) != retained:
        raise DataValidationError(
            "Original retry changed source scope, bytes or first receipt time.",
            code="INSTITUTIONAL_ORIGINAL_INVALID",
        )
    return retained


__all__ = ["import_nbs_calendar_originals"]
