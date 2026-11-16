"""Trusted composition for the session-authenticated C2 Owner JSON API.

The request contains only a strict configuration record or revoke identity and
reason. Django's authenticated HttpRequest, default database alias and
active Config Center body-store settings are composed here; settings and the
retained source reader are loaded only for an opening-rule source read. This
module creates no new authorization mechanism or qualification authority.
"""

from __future__ import annotations

import json
from uuid import UUID

from django.db import DEFAULT_DB_ALIAS
from django.http import HttpRequest

from apps.data_center.domain.financial_availability_governance import (
    FinancialAvailabilityGovernanceRecord,
    FinancialAvailabilityOwnerEventAction,
    FinancialAvailabilityOwnerEventIdentity,
)
from apps.data_center.financial_availability_e1_composition import (
    apply_financial_availability_governance_from_request,
    revoke_financial_availability_governance_from_request,
)
from apps.data_center.infrastructure.financial_availability_governance_codec import (
    deserialize_financial_availability_record,
)
from apps.data_center.infrastructure.financial_availability_governance_writer import (
    DjangoFinancialAvailabilityGovernanceRepository,
    DjangoFinancialAvailabilityOwnerEventRepository,
)
from apps.data_center.infrastructure.financial_availability_source_reader import (
    DjangoFinancialAvailabilitySourceReader,
)
from apps.data_center.infrastructure.financial_source_body_runtime import (
    LazyFinancialAvailabilitySourceReader,
    build_statutory_source_body_store,
)
from apps.data_center.infrastructure.statutory_source_repository import (
    DjangoStatutorySourceRepository,
)
from core.exceptions import DataValidationError


def apply_financial_availability_owner_request(
    request: HttpRequest,
    *,
    record_payload: dict[str, object],
    reason: str,
) -> tuple[FinancialAvailabilityGovernanceRecord, FinancialAvailabilityOwnerEventIdentity]:
    """Decode and apply one exact submitted record using the real session request.

    The stored record and rule/policy hashes are restamped by the governance
    repository after scope locking. ``record_payload.recorded_at`` is only an
    input codec field and is never treated as an Owner event or source-known-at
    clock. The E1 composition samples source-known-at from PostgreSQL itself.
    """

    record = _decode_record(record_payload)
    records, owner_events = _build_owner_repositories()
    return apply_financial_availability_governance_from_request(
        request,
        record,
        reason=reason,
        records=records,
        owner_events=owner_events,
    )


def revoke_financial_availability_owner_request(
    request: HttpRequest,
    *,
    target: dict[str, str],
    reason: str,
) -> FinancialAvailabilityOwnerEventIdentity:
    """Resolve an exact persisted apply target and append its revoke event.

    Target body fields are selectors only. The record and full event history
    are read from the selected database, then the existing E1 write path locks
    and revalidates them again before appending.
    """

    records, owner_events = _build_owner_repositories()
    known_at = records.now()
    record = records.get_exact(
        record_id=target["record_id"],
        record_version=target["record_version"],
        expected_content_sha256=target["record_content_sha256"],
        known_at=known_at,
    )
    if record is None:
        raise DataValidationError(
            "The exact C2 governance revoke target is unavailable.",
            code="FIN_AVAILABILITY_REVOKE_TARGET_MISSING",
        )

    matches = tuple(
        event
        for event in owner_events.list_complete_history(
            record_id=record.record_id,
            record_version=record.record_version,
        )
        if event.action is FinancialAvailabilityOwnerEventAction.APPLY
        and event.event_id == _target_uuid(target["apply_event_id"])
        and event.event_sha256 == target["apply_event_sha256"]
        and event.record_content_sha256 == record.content_sha256
        and event.is_knowable_at(known_at)
    )
    if len(matches) != 1:
        raise DataValidationError(
            "The exact C2 apply event is missing, ambiguous, or not yet knowable.",
            code="FIN_AVAILABILITY_REVOKE_APPLY_EVENT_INVALID",
        )
    return revoke_financial_availability_governance_from_request(
        request,
        record,
        matches[0],
        reason=reason,
        records=records,
        owner_events=owner_events,
    )


def _build_owner_repositories() -> tuple[
    DjangoFinancialAvailabilityGovernanceRepository,
    DjangoFinancialAvailabilityOwnerEventRepository,
]:
    """Bind C2 repositories; resolve retained storage only for an opening rule."""

    source_reader = LazyFinancialAvailabilitySourceReader(
        using=DEFAULT_DB_ALIAS,
        reader_factory=_build_financial_availability_source_reader,
    )
    records = DjangoFinancialAvailabilityGovernanceRepository(using=DEFAULT_DB_ALIAS)
    owner_events = DjangoFinancialAvailabilityOwnerEventRepository(
        using=DEFAULT_DB_ALIAS,
        source_reader=source_reader,
    )
    if records.database_alias != owner_events.database_alias:
        raise DataValidationError(
            "C2 Owner repositories must share the authenticated default database.",
            code="FIN_AVAILABILITY_ALIAS_MISMATCH",
        )
    return records, owner_events


def _build_financial_availability_source_reader() -> DjangoFinancialAvailabilitySourceReader:
    """Load Config Center storage and bind the real reader at first source use."""

    body_store = build_statutory_source_body_store()
    source_repository = DjangoStatutorySourceRepository(
        body_store=body_store,
        using=DEFAULT_DB_ALIAS,
    )
    return DjangoFinancialAvailabilitySourceReader(
        repository=source_repository,
        body_store=body_store,
        using=DEFAULT_DB_ALIAS,
    )


def _decode_record(payload: dict[str, object]) -> FinancialAvailabilityGovernanceRecord:
    """Run the existing strict storage codec over one JSON object at the edge."""

    try:
        raw = json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
        record = deserialize_financial_availability_record(raw)
    except (TypeError, ValueError, UnicodeEncodeError) as error:
        raise DataValidationError(
            "C2 Owner record does not match the strict governance codec.",
            code="FIN_AVAILABILITY_RECORD_INVALID",
        ) from error
    if type(record) is not FinancialAvailabilityGovernanceRecord:
        raise DataValidationError(
            "C2 Owner record decoder returned an unsupported type.",
            code="FIN_AVAILABILITY_RECORD_INVALID",
        )
    return record


def _target_uuid(value: str) -> UUID:
    """Parse a serializer-validated canonical event identifier."""

    try:
        result = UUID(value)
    except (AttributeError, TypeError, ValueError) as error:
        raise DataValidationError(
            "C2 revoke event identifier is invalid.",
            code="FIN_AVAILABILITY_REVOKE_TARGET_INVALID",
        ) from error
    if str(result) != value:
        raise DataValidationError(
            "C2 revoke event identifier is not canonical.",
            code="FIN_AVAILABILITY_REVOKE_TARGET_INVALID",
        )
    return result


__all__ = [
    "apply_financial_availability_owner_request",
    "revoke_financial_availability_owner_request",
]
