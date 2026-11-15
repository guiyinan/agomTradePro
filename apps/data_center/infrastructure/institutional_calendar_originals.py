"""Lossless public HTML retention using the existing hash-addressed raw store."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from typing import cast

from django.db import transaction

from apps.data_center.application.institutional_calendar import NbsScheduleInput
from apps.data_center.application.institutional_calendar_sources import (
    InstitutionalSourcePolicy,
    RetainedInstitutionalOriginal,
)
from apps.data_center.domain.institutional_calendar import EventLifecycle, InstitutionalEvent
from apps.data_center.infrastructure.institutional_calendar_repository import (
    DjangoInstitutionalCalendarRepository,
)
from apps.data_center.infrastructure.models import RawPayloadModel
from apps.data_center.infrastructure.nbs_institutional_calendar_parser import (
    parse_nbs_actual_release,
    parse_nbs_schedule,
)
from core.exceptions import AgomTradeProException, DataValidationError

_DATASET = "institutional_calendar_original"
_SCHEMA = "institutional-calendar-utf8-html-v1"


class DjangoInstitutionalOriginalRepository:
    """Retain public UTF-8 bytes losslessly and verify the complete sealed envelope."""

    def __init__(self, *, using: str = "default") -> None:
        """Bind the same explicit database alias as the event repository."""
        self._using = using

    def append(self, original: RetainedInstitutionalOriginal) -> RetainedInstitutionalOriginal:
        """Insert one original without silently changing an earlier capture's clocks."""
        maximum = RawPayloadModel._meta.get_field("provider_name").max_length
        if maximum is not None and len(original.policy.source_id) > maximum:
            raise _invalid("Source identity exceeds the raw provider storage contract.")
        envelope = _encode(original)
        with transaction.atomic(using=self._using):
            existing = self.read(original.sha256)
            if existing is not None:
                if existing != original:
                    raise _invalid("Original identity already has different capture metadata.")
                return existing
            RawPayloadModel.objects.using(self._using).get_or_create(
                payload_hash="inst-cal-original:" + original.sha256,
                defaults={
                    "dataset_key": _DATASET,
                    "provider_name": original.policy.source_id,
                    "schema_fingerprint": _digest(envelope),
                    "payload": envelope,
                    "request_params": {"original_sha256": original.sha256},
                    "content_type": "text/html; charset=utf-8",
                    "parser_version": _SCHEMA,
                    # Public HTML has no credential fields; the sanitization is identity.
                    "redacted": True,
                    "payload_size_bytes": len(original.body),
                    "fetched_at": original.first_seen_at,
                },
            )
            retained = self.read(original.sha256)
            if retained != original:
                raise _invalid("Retained original failed independent readback.")
            return retained

    def read(self, sha256: str) -> RetainedInstitutionalOriginal | None:
        """Verify storage identity, metadata and reconstructed exact bytes on each read."""
        rows = list(
            RawPayloadModel.objects.using(self._using).filter(
                dataset_key=_DATASET, request_params__original_sha256=sha256
            )[:2]
        )
        if not rows:
            return None
        if len(rows) != 1:
            raise _invalid("Original identity has ambiguous retained captures.")
        row = rows[0]
        payload = row.payload
        if not isinstance(payload, dict):
            raise _invalid("Original envelope is invalid.")
        envelope = cast(dict[str, object], payload)
        if (
            row.payload_hash != "inst-cal-original:" + sha256
            or row.schema_fingerprint != _digest(envelope)
            or row.parser_version != _SCHEMA
        ):
            raise _invalid("Original envelope integrity failed.")
        original = _decode(envelope)
        if (
            original.sha256 != sha256
            or original.policy.source_id != row.provider_name
            or original.first_seen_at != row.fetched_at
            or len(original.body) != row.payload_size_bytes
            or row.content_type != "text/html; charset=utf-8"
            or not row.redacted
        ):
            raise _invalid("Original envelope and storage metadata differ.")
        return original

    def verify_event(
        self, event: InstitutionalEvent, original: RetainedInstitutionalOriginal
    ) -> bool:
        """Reparse the complete source and exact predecessor before claiming confirmation."""
        try:
            original.validate_event(event)
            if event.revision == 1 and event.lifecycle is EventLifecycle.SCHEDULED:
                return _schedule_input(event, original).to_event() == event
            if event.revision != 2 or event.lifecycle is not EventLifecycle.OCCURRED:
                return False
            prior = DjangoInstitutionalCalendarRepository(using=self._using).get_version(
                event.event_id, 1
            )
            if prior is None:
                return False
            prior_original = self.read(prior.original_sha256)
            if prior_original is None or not self.verify_event(prior, prior_original):
                return False
            actual = parse_nbs_actual_release(
                original.body, source_timezone=original.policy.timezone_name
            )
            expected = actual.to_input(
                _schedule_input(prior, prior_original),
                first_seen_at=original.first_seen_at,
                recorded_at=original.recorded_at,
            ).to_event(prior)
            return expected == event
        except AgomTradeProException:
            return False


def _schedule_input(
    event: InstitutionalEvent, original: RetainedInstitutionalOriginal
) -> NbsScheduleInput:
    """Locate the exact official schedule entry without trusting persisted dates."""
    document = parse_nbs_schedule(
        original.body, content_title=event.title, source_timezone=original.policy.timezone_name
    )
    entries = [entry for entry in document.entries if entry.scheduled_at == event.scheduled_at]
    if len(entries) != 1:
        raise _invalid("Recorded event is not in the retained schedule.")
    return entries[0].to_input(
        event_id=event.event_id,
        source_id=original.policy.source_id,
        source_event_id=event.source_event_id,
        event_type=original.policy.event_type,
        title=event.title,
        first_seen_at=original.first_seen_at,
        recorded_at=original.recorded_at,
    )


def _encode(original: RetainedInstitutionalOriginal) -> dict[str, object]:
    """JSON-escape exact UTF-8 text without normalization or loss of original bytes."""
    try:
        text = original.body.decode("utf-8")
    except UnicodeDecodeError as error:
        raise _invalid("Original must be exact UTF-8 HTML.") from error
    policy = original.policy
    return {
        "schema": _SCHEMA,
        "html": text,
        "sha256": original.sha256,
        "url": original.url,
        "first_seen_at": original.first_seen_at.isoformat(),
        "recorded_at": original.recorded_at.isoformat(),
        "source_id": policy.source_id,
        "event_type": policy.event_type,
        "rule_version": policy.rule_version,
        "catalogue_sha256": policy.catalogue_sha256,
        "timezone_name": policy.timezone_name,
        "attribution": policy.attribution,
        "allowed_urls": list(policy.allowed_urls),
        "valid_until": policy.valid_until.isoformat(),
    }


def _decode(raw: dict[str, object]) -> RetainedInstitutionalOriginal:
    """Narrow JSON into typed source evidence before it enters Application."""
    try:
        urls = raw["allowed_urls"]
        if not isinstance(urls, list) or any(not isinstance(url, str) for url in urls):
            raise _invalid("Original URL scope is invalid.")
        policy = InstitutionalSourcePolicy(
            source_id=_text(raw, "source_id"),
            event_type=_text(raw, "event_type"),
            rule_version=_text(raw, "rule_version"),
            catalogue_sha256=_text(raw, "catalogue_sha256"),
            timezone_name=_text(raw, "timezone_name"),
            attribution=_text(raw, "attribution"),
            allowed_urls=tuple(cast(list[str], urls)),
            valid_until=datetime.fromisoformat(_text(raw, "valid_until")),
        )
        return RetainedInstitutionalOriginal(
            policy=policy,
            url=_text(raw, "url"),
            body=_text(raw, "html").encode("utf-8"),
            sha256=_text(raw, "sha256"),
            first_seen_at=datetime.fromisoformat(_text(raw, "first_seen_at")),
            recorded_at=datetime.fromisoformat(_text(raw, "recorded_at")),
        )
    except (KeyError, TypeError, ValueError) as error:
        raise _invalid("Original envelope cannot be decoded.") from error


def _text(raw: dict[str, object], key: str) -> str:
    """Require explicit nonempty strings at the persisted JSON boundary."""
    value = raw[key]
    if not isinstance(value, str) or not value:
        raise _invalid("Original envelope text is missing.")
    return value


def _digest(raw: dict[str, object]) -> str:
    """Seal the entire envelope, including its source scope and receipt clocks."""
    return hashlib.sha256(
        json.dumps(raw, sort_keys=True, ensure_ascii=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def _invalid(message: str) -> DataValidationError:
    """Expose a bounded integrity failure without disclosing original HTML."""
    return DataValidationError(message, code="INSTITUTIONAL_ORIGINAL_INVALID")


__all__ = ["DjangoInstitutionalOriginalRepository"]
