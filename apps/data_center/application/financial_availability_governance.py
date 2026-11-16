"""Application read composition for exact C2 governance versions and events."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, date, datetime

from apps.data_center.application.financial_availability_governance_ports import (
    FinancialAvailabilityGovernanceRepositoryPort,
    FinancialAvailabilityOwnerEventRepositoryPort,
    FinancialAvailabilityPermissionAuthorizerPort,
    FinancialAvailabilitySessionRequestProof,
    FinancialAvailabilitySourceRead,
    FinancialAvailabilitySourceReaderPort,
    GetFinancialAvailabilityGovernanceQuery,
)
from apps.data_center.domain.financial_availability_governance import (
    ExchangeSessionOpeningRuleProposal,
    FinancialAvailabilityGovernanceRecord,
    FinancialAvailabilityOwnerEventIdentity,
    FinancialAvailabilityRecordKind,
    resolve_financial_availability_owner_apply,
)
from apps.data_center.domain.financial_next_session_availability import (
    ExchangeSessionOpeningRule,
)
from apps.data_center.domain.financial_next_session_witness import (
    FinancialDisclosureAvailabilityPolicy,
)
from core.exceptions import DataValidationError


@dataclass(frozen=True, slots=True)
class FinancialAvailabilityGovernanceReadResult:
    """One exact locally applied config row for later C2 composition.

    This result proves no official source interpretation, formal calendar
    publication, E1 Audit authority, or financial decision qualification.
    """

    record: FinancialAvailabilityGovernanceRecord
    apply_event: FinancialAvailabilityOwnerEventIdentity
    resolved_content: ExchangeSessionOpeningRule | FinancialDisclosureAvailabilityPolicy
    known_at: datetime
    checked_at: datetime
    source_read: FinancialAvailabilitySourceRead | None = field(default=None, repr=False)


def read_financial_availability_governance(
    query: GetFinancialAvailabilityGovernanceQuery,
    *,
    records: FinancialAvailabilityGovernanceRepositoryPort,
    owner_events: FinancialAvailabilityOwnerEventRepositoryPort,
    source_reader: FinancialAvailabilitySourceReaderPort,
) -> FinancialAvailabilityGovernanceReadResult:
    """Resolve one exact applied rule or policy at an explicit knowledge time.

    The repositories must address the same database alias and join the
    caller's READ COMMITTED UOW. The explicit ``known_at`` is never replaced
    by a transaction-start time. The read rehashes the exact configuration
    and lifecycle stream and rereads the retained source body for an opening
    rule. It never uses a mutable current pointer or latest-row fallback.
    """

    if type(query) is not GetFinancialAvailabilityGovernanceQuery:
        raise DataValidationError("C2 governance requires an exact typed query.")
    try:
        query.__post_init__()
    except (TypeError, ValueError) as error:
        raise DataValidationError("C2 governance query is invalid.") from error
    aliases = (
        records.database_alias,
        owner_events.database_alias,
        source_reader.database_alias,
    )
    if any(type(alias) is not str or not alias or alias.strip() != alias for alias in aliases):
        raise DataValidationError("C2 governance database alias is invalid.")
    if not (aliases[0] == aliases[1] == aliases[2]):
        raise DataValidationError("C2 governance and source reads must share one database alias.")
    with records.atomic():
        return _read_in_uow(
            query,
            records=records,
            owner_events=owner_events,
            source_reader=source_reader,
        )


def _read_in_uow(
    query: GetFinancialAvailabilityGovernanceQuery,
    *,
    records: FinancialAvailabilityGovernanceRepositoryPort,
    owner_events: FinancialAvailabilityOwnerEventRepositoryPort,
    source_reader: FinancialAvailabilitySourceReaderPort,
) -> FinancialAvailabilityGovernanceReadResult:
    """Perform all exact-scope reads within the caller's READ COMMITTED UOW."""

    server_now = _require_utc(records.now(), "database server time")
    known_at = _require_utc(query.known_at, "known_at")
    if known_at > server_now:
        raise DataValidationError("C2 governance cutoff is in the future.")

    candidates = records.list_for_effective_date(
        kind=query.kind,
        exchange=query.exchange,
        effective_on=query.effective_on,
        known_at=known_at,
    )
    if type(candidates) is not tuple:
        raise DataValidationError("C2 governance repository returned an invalid candidate set.")
    active: list[FinancialAvailabilityGovernanceReadResult] = []
    for record in candidates:
        if type(record) is not FinancialAvailabilityGovernanceRecord:
            raise DataValidationError("C2 governance repository returned an untyped record.")
        try:
            record.__post_init__()
        except (TypeError, ValueError) as error:
            raise DataValidationError("C2 governance record failed exact validation.") from error
        if record.kind is not query.kind or record.exchange != query.exchange:
            raise DataValidationError("C2 governance repository crossed the requested scope.")
        if record.recorded_at > server_now:
            raise DataValidationError("C2 governance record has a future knowledge clock.")
        if record.recorded_at > known_at:
            continue
        effective_start, effective_end = _effective_range(record)
        if not effective_start <= query.effective_on <= effective_end:
            continue

        history = owner_events.list_complete_history(
            record_id=record.record_id,
            record_version=record.record_version,
        )
        try:
            apply_event = resolve_financial_availability_owner_apply(
                record,
                history,
                known_at=known_at,
                server_now=server_now,
            )
        except (TypeError, ValueError) as error:
            raise DataValidationError("C2 Owner event history failed exact validation.") from error
        if apply_event is None:
            continue
        try:
            resolved_content = materialize_financial_availability_record(record, apply_event)
        except (TypeError, ValueError) as error:
            raise DataValidationError("C2 applied result hash failed exact validation.") from error
        source_read: FinancialAvailabilitySourceRead | None = None
        if record.kind is FinancialAvailabilityRecordKind.OPENING_RULE:
            source = record.source
            if source is None:
                raise DataValidationError("C2 opening rule has no exact retained source.")
            source_read = source_reader.read_exact_capture(
                issuer=source.issuer,
                document_id=source.document_id,
                source_version=source.source_version,
                capture_id=source.capture_id,
                known_at=known_at,
            )
            if source_read is None:
                raise DataValidationError("C2 exact source revision/capture is missing.")
            if type(source_read) is not FinancialAvailabilitySourceRead:
                raise DataValidationError("C2 source reader returned an untyped source result.")
            try:
                source_read.__post_init__()
            except (TypeError, ValueError) as error:
                raise DataValidationError("C2 exact source read failed validation.") from error
            if source_read.reference != source:
                raise DataValidationError("C2 exact source revision/capture is missing or changed.")
        checked_at = max(
            server_now, source_read.checked_at if source_read is not None else server_now
        )
        active.append(
            FinancialAvailabilityGovernanceReadResult(
                record=record,
                apply_event=apply_event,
                resolved_content=resolved_content,
                known_at=known_at,
                checked_at=checked_at,
                source_read=source_read,
            )
        )

    if not active:
        raise DataValidationError("No applied C2 governance version is visible at the cutoff.")
    if len(active) != 1:
        raise DataValidationError("Multiple applied C2 governance versions overlap the cutoff.")
    return active[0]


def append_and_apply_financial_availability_governance(
    record: FinancialAvailabilityGovernanceRecord,
    *,
    proof: FinancialAvailabilitySessionRequestProof,
    reason: str,
    source_known_at: datetime,
    records: FinancialAvailabilityGovernanceRepositoryPort,
    owner_events: FinancialAvailabilityOwnerEventRepositoryPort,
    authorizer: FinancialAvailabilityPermissionAuthorizerPort,
) -> tuple[FinancialAvailabilityGovernanceRecord, FinancialAvailabilityOwnerEventIdentity]:
    """Append a version and local Owner apply event in one authenticated UOW.

    ``source_known_at`` is supplied by the trusted command at its operation
    boundary and is passed through unchanged. The database repository stamps
    the persisted record and event clocks. This command creates no calendar
    publication, SystemAudit event/outbox pair, or financial decision witness.
    """

    if type(record) is not FinancialAvailabilityGovernanceRecord:
        raise DataValidationError("C2 governance write requires an exact typed record.")
    if type(proof) is not FinancialAvailabilitySessionRequestProof:
        raise DataValidationError("C2 governance write requires the typed session proof.")
    try:
        record.__post_init__()
        proof.__post_init__()
        cutoff = _require_utc(source_known_at, "source_known_at")
    except (TypeError, ValueError) as error:
        raise DataValidationError("C2 governance write input is invalid.") from error
    aliases = (records.database_alias, owner_events.database_alias, authorizer.database_alias)
    if any(type(alias) is not str or not alias or alias.strip() != alias for alias in aliases):
        raise DataValidationError("C2 governance write alias is invalid.")
    if not (aliases[0] == aliases[1] == aliases[2] == proof.database_alias):
        raise DataValidationError("C2 governance write must use the authenticated User alias.")
    with records.atomic():
        records.lock_change_scope(kind=record.kind, exchange=record.exchange)
        with authorizer.lock_authorized_principal(proof) as principal:
            persisted = records.append_record(record)
            event = owner_events.append_apply_event(
                record=persisted,
                principal=principal,
                reason=reason,
                known_at=cutoff,
            )
            return persisted, event


def append_financial_availability_revoke(
    record: FinancialAvailabilityGovernanceRecord,
    apply_event: FinancialAvailabilityOwnerEventIdentity,
    *,
    proof: FinancialAvailabilitySessionRequestProof,
    reason: str,
    records: FinancialAvailabilityGovernanceRepositoryPort,
    owner_events: FinancialAvailabilityOwnerEventRepositoryPort,
    authorizer: FinancialAvailabilityPermissionAuthorizerPort,
) -> FinancialAvailabilityOwnerEventIdentity:
    """Append a real authenticated Owner revoke without mutating prior rows."""

    if (
        type(record) is not FinancialAvailabilityGovernanceRecord
        or type(apply_event) is not FinancialAvailabilityOwnerEventIdentity
        or type(proof) is not FinancialAvailabilitySessionRequestProof
    ):
        raise DataValidationError("C2 revoke requires one exact record, apply event and session.")
    try:
        record.__post_init__()
        apply_event.__post_init__()
        proof.__post_init__()
    except (TypeError, ValueError) as error:
        raise DataValidationError("C2 revoke input is invalid.") from error
    if apply_event.action.value != "apply":
        raise DataValidationError("C2 revoke requires an exact apply event.")
    aliases = (records.database_alias, owner_events.database_alias, authorizer.database_alias)
    if any(type(alias) is not str or not alias or alias.strip() != alias for alias in aliases):
        raise DataValidationError("C2 revoke alias is invalid.")
    if not (aliases[0] == aliases[1] == aliases[2] == proof.database_alias):
        raise DataValidationError("C2 revoke must use the authenticated User alias.")
    with records.atomic():
        records.lock_change_scope(kind=record.kind, exchange=record.exchange)
        with authorizer.lock_authorized_principal(proof) as principal:
            return owner_events.append_revoke_event(
                record=record,
                apply_event=apply_event,
                principal=principal,
                reason=reason,
            )


def _effective_range(
    record: FinancialAvailabilityGovernanceRecord,
) -> tuple[date, date]:
    """Return explicit effective date bounds from one exact typed content value."""

    content = record.content
    if type(content) is ExchangeSessionOpeningRuleProposal:
        return content.effective_start, content.effective_end
    if type(content) is FinancialDisclosureAvailabilityPolicy:
        return content.effective_start, content.effective_end
    raise DataValidationError("C2 governance record has an unsupported content type.")


def materialize_financial_availability_record(
    record: FinancialAvailabilityGovernanceRecord,
    apply_event: FinancialAvailabilityOwnerEventIdentity,
) -> ExchangeSessionOpeningRule | FinancialDisclosureAvailabilityPolicy:
    """Return the exact resulting typed content bound by the apply event."""

    if type(record.content) is ExchangeSessionOpeningRuleProposal:
        result = record.content.materialize_applied_rule(
            recorded_at=record.recorded_at,
            approved_at=apply_event.occurred_at,
        )
        if result.rule_sha256 != apply_event.resulting_content_sha256:
            raise DataValidationError("C2 applied opening rule hash differs from its event.")
        return result
    if type(record.content) is FinancialDisclosureAvailabilityPolicy:
        if record.content.policy_sha256 != apply_event.resulting_content_sha256:
            raise DataValidationError("C2 applied policy hash differs from its event.")
        return record.content
    raise DataValidationError("C2 governance record has an unsupported content type.")


def _require_utc(value: object, name: str) -> datetime:
    """Require one representable aware UTC instant."""

    if type(value) is not datetime or value.tzinfo is None:
        raise DataValidationError(f"{name} is not an aware UTC timestamp.")
    offset = value.utcoffset()
    if offset is None or offset.total_seconds() != 0:
        raise DataValidationError(f"{name} is not an explicit UTC timestamp.")
    try:
        return value.astimezone(UTC)
    except (OverflowError, ValueError) as error:
        raise DataValidationError(f"{name} is outside the UTC range.") from error


__all__ = [
    "FinancialAvailabilityGovernanceReadResult",
    "append_and_apply_financial_availability_governance",
    "append_financial_availability_revoke",
    "materialize_financial_availability_record",
    "read_financial_availability_governance",
]
