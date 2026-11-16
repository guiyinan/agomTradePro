"""Trusted same-UOW composition for current C2/E1 evidence checks and Owner writes.

This candidate uses the existing formal calendar current/history readers and
Core Audit bridges in an ambient default-database transaction. Its temporal
check remains reference-only until the v3 statutory-source identity union and
the financial decision/readback gate are integrated.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

from django.contrib.auth.models import AbstractBaseUser
from django.db import DEFAULT_DB_ALIAS, connections
from django.http import HttpRequest
from django.utils import timezone

from apps.data_center.application.calendar_formal_publication_audit_port import (
    CalendarFormalPublicationAuditPort,
)
from apps.data_center.application.calendar_historical_publication_audit_port import (
    CalendarHistoricalPublicationAuditPort,
)
from apps.data_center.application.financial_availability_current import (
    CurrentFinancialNextSessionTemporalCheck,
    ResolveCurrentFinancialAvailabilityGovernanceQuery,
    resolve_current_financial_availability_governance,
    validate_current_financial_next_session_temporal_binding,
)
from apps.data_center.application.financial_availability_governance import (
    FinancialAvailabilityGovernanceReadResult,
    append_and_apply_financial_availability_governance,
    append_financial_availability_revoke,
    materialize_financial_availability_record,
)
from apps.data_center.application.financial_availability_governance_ports import (
    FinancialAvailabilityGovernanceRepositoryPort,
    FinancialAvailabilityOwnerEventRepositoryPort,
    FinancialAvailabilityPermissionAuthorizerPort,
    FinancialAvailabilitySessionRequestProof,
    FinancialAvailabilitySourceRead,
    FinancialAvailabilitySourceReaderPort,
)
from apps.data_center.application.formal_exchange_calendar_publication import (
    CalendarFormalPublicationApplicationError as CalendarHistoryApplicationError,
)
from apps.data_center.application.formal_exchange_calendar_publication import (
    CurrentPublishedExchangeCalendar,
    ReadCurrentExchangeCalendarPublicationQuery,
)
from apps.data_center.application.formal_exchange_calendar_publication_history import (
    CalendarHistoryClock,
    HistoricalPublishedExchangeCalendar,
    ReadExchangeCalendarPublicationAsOfQuery,
    ReadExchangeCalendarPublicationAsOfUseCase,
)
from apps.data_center.domain.exchange_calendar import (
    ExchangeCalendarError,
    next_exchange_calendar_session,
)
from apps.data_center.domain.financial_availability_governance import (
    FinancialAvailabilityGovernanceRecord,
    FinancialAvailabilityOwnerEventAction,
    FinancialAvailabilityOwnerEventIdentity,
)
from apps.data_center.domain.financial_next_session_availability import (
    ExchangeSessionOpeningRule,
    FinancialNextSessionAvailabilityError,
    resolve_financial_next_session_availability,
)
from apps.data_center.domain.financial_next_session_witness import (
    FinancialApprovalIdentity,
    FinancialDisclosureAvailabilityPolicy,
    FinancialNativeRowBinding,
    FinancialNextSessionGovernanceBinding,
    FinancialNextSessionSourceTimeWitnessV3,
)
from apps.data_center.domain.financial_statutory_source_identity import (
    FinancialStatutorySourceIdentity,
)
from apps.data_center.domain.formal_exchange_calendar_publication import (
    exchange_calendar_publication_key,
)
from apps.data_center.domain.statutory_source_documents import (
    StatutorySourceBodyReference,
)
from apps.data_center.infrastructure.financial_availability_governance_authority import (
    DjangoFinancialAvailabilityPermissionAuthorizer,
)
from apps.data_center.infrastructure.formal_exchange_calendar_publication_history_reader import (
    DjangoFormalExchangeCalendarPublicationHistoryReader,
)
from core.exceptions import AuthorizationError, DataFetchError, DataValidationError
from core.integration.calendar_formal_publication_audit import (
    CoreCalendarFormalPublicationAuditBridge,
)
from core.integration.calendar_formal_publication_history_audit import (
    CoreCalendarFormalPublicationHistoricalAuditBridge,
)


class _AmbientClock(CalendarHistoryClock):
    """Use the exact governance repository's database clock for future checks."""

    def __init__(self, records: FinancialAvailabilityGovernanceRepositoryPort) -> None:
        """Bind the clock to the already selected same-alias repository."""

        self._records = records

    def now(self) -> datetime:
        """Return server wall time without changing any requested historical cutoff."""

        value = self._records.now()
        if type(value) is not datetime or value.tzinfo is None or value.utcoffset() != timedelta(0):
            raise DataFetchError(
                "C2 current composition clock must be aware UTC",
                code="FIN_AVAILABILITY_CURRENT_CLOCK_INVALID",
            )
        return value.astimezone(UTC)


def validate_financial_next_session_witness_current(
    witness: FinancialNextSessionSourceTimeWitnessV3,
    *,
    records: FinancialAvailabilityGovernanceRepositoryPort,
    owner_events: FinancialAvailabilityOwnerEventRepositoryPort,
    source_reader: FinancialAvailabilitySourceReaderPort,
) -> CurrentFinancialNextSessionTemporalCheck:
    """Re-read old calendar at its original cutoff and current fresh remapping.

    The caller must own exactly one default-database PostgreSQL READ COMMITTED
    transaction. The existing current calendar composition joins this UOW; the
    historical reader and Core Audit bridges are assembled directly because
    the ordinary historical composition deliberately owns its own transaction.
    """

    if type(witness) is not FinancialNextSessionSourceTimeWitnessV3:
        raise DataValidationError(
            "E1 C2 readback requires one exact v3 reference.",
            code="FIN_AVAILABILITY_CURRENT_WITNESS_INVALID",
        )
    _require_default_caller_uow()
    if any(
        alias != DEFAULT_DB_ALIAS
        for alias in (
            records.database_alias,
            owner_events.database_alias,
            source_reader.database_alias,
        )
    ):
        raise DataValidationError(
            "E1 C2/calendar validation requires one default-database alias.",
            code="FIN_AVAILABILITY_CURRENT_ALIAS_MISMATCH",
        )

    pair = resolve_current_financial_availability_governance(
        ResolveCurrentFinancialAvailabilityGovernanceQuery(
            exchange=witness.availability.calendar.exchange,
            effective_on=witness.availability.next_session,
        ),
        records=records,
        owner_events=owner_events,
        source_reader=source_reader,
    )
    current_calendar = _read_current_calendar(
        witness,
        as_of=pair.known_at,
    )
    historical_calendar = _read_historical_calendar(
        witness,
        records=records,
    )
    checked_at = _AmbientClock(records).now()
    availability = validate_current_financial_next_session_temporal_binding(
        witness,
        pair,
        historical_calendar,
        current_calendar,
        checked_at=checked_at,
    )
    return CurrentFinancialNextSessionTemporalCheck(
        witness=witness,
        governance=pair,
        historical_calendar=historical_calendar,
        current_calendar=current_calendar,
        current_availability=availability,
        checked_at=checked_at,
    )


def build_financial_next_session_witness_v3(
    financial_row: FinancialNativeRowBinding,
    *,
    exchange: str,
    calendar_dataset_key: str,
    records: FinancialAvailabilityGovernanceRepositoryPort,
    owner_events: FinancialAvailabilityOwnerEventRepositoryPort,
    source_reader: FinancialAvailabilitySourceReaderPort,
) -> FinancialNextSessionSourceTimeWitnessV3:
    """Build one reference-only v3 witness from current C2 and calendar reads.

    The caller supplies the exact exchange and calendar dataset from its
    validated run plan; no asset-suffix inference, phase, TTL, or wall-clock
    default is used. A first fresh calendar read selects the effective next
    session. The current C2 pair is then resolved under its normal scope/event
    locks, and the calendar is reread at that pair's post-lock ``known_at``.
    Any change to the next-session mapping blocks construction.

    The caller must own the single default PostgreSQL READ COMMITTED UOW used
    by C2 and the formal calendar reader. The result preserves exact statutory
    capture clocks, local Owner APPLY event identities, and calendar identity,
    but remains evidence-only. The E1 writer/readback gate must independently
    revalidate source bytes/audits, current governance, calendar, and the raw
    financial NOTICE row before it can qualify a fact.
    """

    if type(financial_row) is not FinancialNativeRowBinding:
        raise DataValidationError(
            "C2 witness builder requires one exact native financial row binding.",
            code="FIN_AVAILABILITY_CURRENT_WITNESS_INVALID",
        )
    try:
        financial_row.__post_init__()
        exchange_calendar_publication_key(exchange)
    except (TypeError, ValueError, CalendarHistoryApplicationError) as error:
        raise DataValidationError(
            "C2 witness builder scope or raw row is invalid.",
            code="FIN_AVAILABILITY_CURRENT_QUERY_INVALID",
        ) from error
    if (
        type(calendar_dataset_key) is not str
        or not calendar_dataset_key
        or calendar_dataset_key.strip() != calendar_dataset_key
        or len(calendar_dataset_key) > 160
        or any(character.isspace() for character in calendar_dataset_key)
    ):
        raise DataValidationError(
            "C2 witness builder requires an explicit calendar dataset key.",
            code="FIN_AVAILABILITY_CURRENT_QUERY_INVALID",
        )

    _require_default_caller_uow()
    if any(
        alias != DEFAULT_DB_ALIAS
        for alias in (
            records.database_alias,
            owner_events.database_alias,
            source_reader.database_alias,
        )
    ):
        raise DataValidationError(
            "C2 witness construction requires one default-database alias.",
            code="FIN_AVAILABILITY_CURRENT_ALIAS_MISMATCH",
        )

    initial_cutoff = _AmbientClock(records).now()
    initial_calendar = _read_current_calendar_for_scope(
        calendar_dataset_key=calendar_dataset_key,
        exchange=exchange,
        as_of=initial_cutoff,
    )
    initial_next_session = _next_session_after_notice(financial_row, initial_calendar)

    governance = resolve_current_financial_availability_governance(
        ResolveCurrentFinancialAvailabilityGovernanceQuery(
            exchange=exchange,
            effective_on=initial_next_session,
        ),
        records=records,
        owner_events=owner_events,
        source_reader=source_reader,
    )
    try:
        governance.__post_init__()
    except (TypeError, ValueError) as error:
        raise DataValidationError(
            "Current C2 governance pair is malformed.",
            code="FIN_AVAILABILITY_GOVERNANCE_CHANGED",
        ) from error
    current_calendar = _read_current_calendar_for_scope(
        calendar_dataset_key=calendar_dataset_key,
        exchange=exchange,
        as_of=governance.known_at,
    )
    current_next_session = _next_session_after_notice(financial_row, current_calendar)
    if (
        current_next_session != initial_next_session
        or governance.effective_on != current_next_session
    ):
        raise DataValidationError(
            "Current calendar mapping changed while C2 scope was being resolved.",
            code="FIN_AVAILABILITY_NEXT_SESSION_MAPPING_CHANGED",
        )

    opening_rule = governance.opening_rule.resolved_content
    policy = governance.disclosure_policy.resolved_content
    if type(opening_rule) is not ExchangeSessionOpeningRule:
        raise DataValidationError(
            "Current applied C2 opening rule is unavailable.",
            code="FIN_AVAILABILITY_GOVERNANCE_CHANGED",
        )
    if type(policy) is not FinancialDisclosureAvailabilityPolicy:
        raise DataValidationError(
            "Current applied C2 disclosure policy is unavailable.",
            code="FIN_AVAILABILITY_GOVERNANCE_CHANGED",
        )
    try:
        availability = resolve_financial_next_session_availability(
            source_date=financial_row.notice_date,
            known_at=governance.known_at,
            calendar_record=current_calendar.record,
            calendar_pointer=current_calendar.pointer,
            opening_rule=opening_rule,
        )
    except FinancialNextSessionAvailabilityError as error:
        code = (
            "FIN_AVAILABILITY_CURRENT_CALENDAR_EXPIRED"
            if error.code == "CALENDAR_NOT_CURRENT_OR_FRESH"
            else (
                "FIN_AVAILABILITY_GOVERNANCE_EXPIRED"
                if error.code == "RULE_NOT_EFFECTIVE"
                else "FIN_AVAILABILITY_CURRENT_CALENDAR_CHANGED"
            )
        )
        raise DataValidationError(
            "Current C2 rule and formal calendar cannot resolve the exact next opening.",
            code=code,
        ) from error
    if availability.next_session != governance.effective_on:
        raise DataValidationError(
            "Current governance scope differs from the computed next session.",
            code="FIN_AVAILABILITY_GOVERNANCE_CHANGED",
        )

    official_source = _official_source_from_governance_result(governance.opening_rule)
    binding = FinancialNextSessionGovernanceBinding(
        opening_rule_record_id=governance.opening_rule.record.record_id,
        official_source=official_source,
        opening_rule_approval=_approval_identity_from_governance_result(
            governance.opening_rule,
            expected_content_sha256=opening_rule.rule_sha256,
        ),
        policy=policy,
        policy_approval=_approval_identity_from_governance_result(
            governance.disclosure_policy,
            expected_content_sha256=policy.policy_sha256,
        ),
    )
    try:
        return FinancialNextSessionSourceTimeWitnessV3.from_resolved_availability(
            financial_row=financial_row,
            availability=availability,
            governance=binding,
        )
    except (TypeError, ValueError) as error:
        raise DataValidationError(
            "Current C2 evidence could not form an exact date-only v3 witness.",
            code="FIN_AVAILABILITY_GOVERNANCE_CHANGED",
        ) from error


def apply_financial_availability_governance_from_request(
    request: HttpRequest,
    record: FinancialAvailabilityGovernanceRecord,
    *,
    reason: str,
    records: FinancialAvailabilityGovernanceRepositoryPort,
    owner_events: FinancialAvailabilityOwnerEventRepositoryPort,
) -> tuple[FinancialAvailabilityGovernanceRecord, FinancialAvailabilityOwnerEventIdentity]:
    """Derive C2 Owner proof from Django's real authenticated request and apply.

    The request body cannot supply an actor, session selector, alias, timestamp,
    or permission boolean. The serializer must first produce the exact typed
    record. Infrastructure reloads and locks the real database session, User,
    Permission and grants before standard ``has_perm`` checks.
    """

    proof = _proof_from_authenticated_request(request)
    _require_default_request_alias(proof.database_alias, records.database_alias)
    if owner_events.database_alias != DEFAULT_DB_ALIAS:
        raise DataValidationError(
            "C2 Owner event repository is not on the authenticated database.",
            code="FIN_AVAILABILITY_CURRENT_ALIAS_MISMATCH",
        )
    authorizer: FinancialAvailabilityPermissionAuthorizerPort = (
        DjangoFinancialAvailabilityPermissionAuthorizer(using=DEFAULT_DB_ALIAS)
    )
    source_known_at = _require_utc(records.now(), "server source cutoff")
    return append_and_apply_financial_availability_governance(
        record,
        proof=proof,
        reason=reason,
        source_known_at=source_known_at,
        records=records,
        owner_events=owner_events,
        authorizer=authorizer,
    )


def revoke_financial_availability_governance_from_request(
    request: HttpRequest,
    record: FinancialAvailabilityGovernanceRecord,
    apply_event: FinancialAvailabilityOwnerEventIdentity,
    *,
    reason: str,
    records: FinancialAvailabilityGovernanceRepositoryPort,
    owner_events: FinancialAvailabilityOwnerEventRepositoryPort,
) -> FinancialAvailabilityOwnerEventIdentity:
    """Append a C2 revoke from the same real request/session authorization path."""

    proof = _proof_from_authenticated_request(request)
    _require_default_request_alias(proof.database_alias, records.database_alias)
    if owner_events.database_alias != DEFAULT_DB_ALIAS:
        raise DataValidationError(
            "C2 Owner event repository is not on the authenticated database.",
            code="FIN_AVAILABILITY_CURRENT_ALIAS_MISMATCH",
        )
    authorizer: FinancialAvailabilityPermissionAuthorizerPort = (
        DjangoFinancialAvailabilityPermissionAuthorizer(using=DEFAULT_DB_ALIAS)
    )
    return append_financial_availability_revoke(
        record,
        apply_event,
        proof=proof,
        reason=reason,
        records=records,
        owner_events=owner_events,
        authorizer=authorizer,
    )


def _read_current_calendar(
    witness: FinancialNextSessionSourceTimeWitnessV3,
    *,
    as_of: datetime,
) -> CurrentPublishedExchangeCalendar:
    """Join the actual current-calendar reader and Core Audit bridge to ambient UOW."""

    from apps.data_center.calendar_publication_operations_composition import (
        read_current_exchange_calendar_reference,
    )

    try:
        return read_current_exchange_calendar_reference(
            ReadCurrentExchangeCalendarPublicationQuery(
                dataset_key=witness.availability.calendar.dataset_key,
                exchange=witness.availability.calendar.exchange,
                as_of=as_of,
            )
        )
    except (DataValidationError, DataFetchError) as error:
        code = _map_calendar_reader_error(error, historical=False)
        raise DataValidationError(
            "Current formal calendar is absent, expired, or changed.", code=code
        ) from error


def _read_current_calendar_for_scope(
    *,
    calendar_dataset_key: str,
    exchange: str,
    as_of: datetime,
) -> CurrentPublishedExchangeCalendar:
    """Read the exact current formal calendar in the ambient same-alias UOW."""

    from apps.data_center.calendar_publication_operations_composition import (
        read_current_exchange_calendar_reference,
    )

    try:
        calendar = read_current_exchange_calendar_reference(
            ReadCurrentExchangeCalendarPublicationQuery(
                dataset_key=calendar_dataset_key,
                exchange=exchange,
                as_of=as_of,
            )
        )
    except (DataValidationError, DataFetchError) as error:
        raise DataValidationError(
            "Current formal calendar is absent, expired, or changed.",
            code=_map_calendar_reader_error(error, historical=False),
        ) from error
    if (
        type(calendar) is not CurrentPublishedExchangeCalendar
        or calendar.as_of != as_of
        or calendar.record.seal.dataset.value != calendar_dataset_key
        or calendar.record.seal.exchange != exchange
    ):
        raise DataValidationError(
            "Current formal calendar read crossed its exact scope or cutoff.",
            code="FIN_AVAILABILITY_CURRENT_CALENDAR_CHANGED",
        )
    try:
        calendar.__post_init__()
    except (TypeError, ValueError, CalendarHistoryApplicationError) as error:
        raise DataValidationError(
            "Current formal calendar failed exact revalidation.",
            code="FIN_AVAILABILITY_CURRENT_CALENDAR_CHANGED",
        ) from error
    return calendar


def _next_session_after_notice(
    financial_row: FinancialNativeRowBinding,
    calendar: CurrentPublishedExchangeCalendar,
) -> date:
    """Require the exact current calendar to cover the first session after NOTICE_DATE."""

    try:
        return next_exchange_calendar_session(
            calendar.record.seal.snapshot,
            after_date=financial_row.notice_date,
        )
    except (ExchangeCalendarError, TypeError, ValueError) as error:
        raise DataValidationError(
            "Current formal calendar cannot prove the next open session after NOTICE_DATE.",
            code="FIN_AVAILABILITY_CURRENT_CALENDAR_CHANGED",
        ) from error


def _official_source_from_governance_result(
    result: FinancialAvailabilityGovernanceReadResult,
) -> FinancialStatutorySourceIdentity:
    """Preserve the exact verified native revision and capture clocks for the rule."""

    source_read = result.source_read
    source = result.record.source
    if (
        type(source_read) is not FinancialAvailabilitySourceRead
        or source is None
        or source_read.reference != source
        or source_read.known_at != result.known_at
        or source_read.checked_at > result.checked_at
    ):
        raise DataValidationError(
            "Current opening rule has no exact retained source read.",
            code="FIN_AVAILABILITY_GOVERNANCE_SOURCE_CHANGED",
        )
    try:
        source_read.__post_init__()
        source.__post_init__()
        body_reference = StatutorySourceBodyReference(
            capture_id=source.capture_id,
            reference=source.body_reference,
            body_sha256=source.body_sha256,
            body_size_bytes=source.body_size_bytes,
        )
        return FinancialStatutorySourceIdentity(
            issuer=source.issuer,
            document_id=source.document_id,
            source_version=source.source_version,
            source_revision_sha256=source.source_revision_sha256,
            source_uri=source.canonical_url,
            body_reference=body_reference,
            first_seen_at=source.first_seen_at,
            revision_recorded_at=source.revision_recorded_at,
            capture_observed_at=source.capture_observed_at,
            recorded_at=source.capture_recorded_at,
        )
    except (TypeError, ValueError) as error:
        raise DataValidationError(
            "Current opening-rule source identity is invalid.",
            code="FIN_AVAILABILITY_GOVERNANCE_SOURCE_CHANGED",
        ) from error


def _approval_identity_from_governance_result(
    result: FinancialAvailabilityGovernanceReadResult,
    *,
    expected_content_sha256: str,
) -> FinancialApprovalIdentity:
    """Project one exact local APPLY event without inventing Owner authority."""

    record = result.record
    event = result.apply_event
    try:
        record.__post_init__()
        event.__post_init__()
        materialized = materialize_financial_availability_record(record, event)
        if (
            type(event.action) is not FinancialAvailabilityOwnerEventAction
            or event.action is not FinancialAvailabilityOwnerEventAction.APPLY
            or event.record_id != record.record_id
            or event.record_version != record.record_version
            or event.record_content_sha256 != record.content_sha256
            or event.resulting_content_sha256 != expected_content_sha256
            or materialized != result.resolved_content
            or event.recorded_at > result.known_at
            or not event.is_knowable_at(result.known_at)
        ):
            raise ValueError("current Owner apply event differs from its exact record")
        return FinancialApprovalIdentity(
            subject_record_id=record.record_id,
            subject_sha256=expected_content_sha256,
            event_id=str(event.event_id),
            event_sha256=event.event_sha256,
            principal_id=event.actor_id,
            approved_at=event.occurred_at,
            recorded_at=event.recorded_at,
        )
    except (DataValidationError, TypeError, ValueError) as error:
        raise DataValidationError(
            "Current C2 Owner apply event cannot bind exact content.",
            code="FIN_AVAILABILITY_GOVERNANCE_CHANGED",
        ) from error


def _read_historical_calendar(
    witness: FinancialNextSessionSourceTimeWitnessV3,
    *,
    records: FinancialAvailabilityGovernanceRepositoryPort,
) -> HistoricalPublishedExchangeCalendar:
    """Use actual exact-history reader and both Core Audit ports in ambient UOW."""

    reference = witness.availability.calendar
    publication_audit: CalendarFormalPublicationAuditPort = (
        CoreCalendarFormalPublicationAuditBridge(using=DEFAULT_DB_ALIAS)
    )
    historical_audit: CalendarHistoricalPublicationAuditPort = (
        CoreCalendarFormalPublicationHistoricalAuditBridge(using=DEFAULT_DB_ALIAS)
    )
    reader = DjangoFormalExchangeCalendarPublicationHistoryReader(
        audit_port=publication_audit,
        historical_audit_port=historical_audit,
        using=DEFAULT_DB_ALIAS,
        clock=records.now,
    )
    use_case = ReadExchangeCalendarPublicationAsOfUseCase(
        reader,
        clock=_AmbientClock(records),
    )
    try:
        return use_case.execute(
            ReadExchangeCalendarPublicationAsOfQuery(
                publication_id=reference.publication_id,
                publication_hash=reference.publication_hash,
                dataset_key=reference.dataset_key,
                exchange=reference.exchange,
                as_of=witness.known_at,
            )
        )
    except (CalendarHistoryApplicationError, DataFetchError) as error:
        code = _map_calendar_reader_error(error, historical=True)
        raise DataValidationError(
            "The original exact formal calendar is absent, expired, or changed.",
            code=code,
        ) from error


def _map_calendar_reader_error(error: Exception, *, historical: bool) -> str:
    """Preserve absent/expired/changed distinctions; classify other failures unavailable."""

    raw_value = getattr(error, "code", "")
    raw_code = raw_value if type(raw_value) is str else ""
    if historical:
        if raw_code == "CALENDAR_HISTORY_PUBLICATION_MISSING":
            return "FIN_AVAILABILITY_HISTORICAL_CALENDAR_MISSING"
        if raw_code in {"CALENDAR_HISTORY_NOT_EFFECTIVE", "CALENDAR_FORMAL_TTL_EXPIRED"}:
            return "FIN_AVAILABILITY_HISTORICAL_CALENDAR_EXPIRED"
        changed_codes = {
            "CALENDAR_HISTORY_SCOPE_MISMATCH",
            "CALENDAR_HISTORY_ROLLBACK_UNSUPPORTED",
            "CALENDAR_HISTORY_TIMELINE_INVALID",
            "CALENDAR_HISTORY_TIMELINE_AMBIGUOUS",
            "CALENDAR_HISTORY_LIFECYCLE_INVALID",
            "CALENDAR_HISTORY_LIFECYCLE_UNSUPPORTED",
            "CALENDAR_HISTORY_AUDIT_INVALID",
            "CALENDAR_FORMAL_PUBLICATION_CARDINALITY_INVALID",
            "CALENDAR_FORMAL_PUBLICATION_ROW_INVALID",
            "CALENDAR_FORMAL_SEAL_INVALID",
            "CALENDAR_FORMAL_SOURCE_MISSING",
            "CALENDAR_FORMAL_MEMBER_INVALID",
            "CALENDAR_FORMAL_MEMBER_BINDING_INVALID",
            "CALENDAR_FORMAL_CATALOG_INVALID",
            "CALENDAR_FORMAL_AUDIT_INTEGRITY_INVALID",
        }
        if raw_code in changed_codes:
            return "FIN_AVAILABILITY_HISTORICAL_CALENDAR_CHANGED"
        return "FIN_AVAILABILITY_HISTORICAL_CALENDAR_UNAVAILABLE"

    if raw_code == "CALENDAR_CURRENT_PUBLICATION_MISSING":
        return "FIN_AVAILABILITY_CURRENT_CALENDAR_MISSING"
    if raw_code == "CALENDAR_FORMAL_TTL_EXPIRED":
        return "FIN_AVAILABILITY_CURRENT_CALENDAR_EXPIRED"
    changed_codes = {
        "CALENDAR_FORMAL_POINTER_MISSING",
        "CALENDAR_FORMAL_POINTER_PLACEHOLDER",
        "CALENDAR_FORMAL_POINTER_MISMATCH",
        "CALENDAR_FORMAL_POINTER_TARGET_INVALID",
        "CALENDAR_FORMAL_PUBLICATION_CARDINALITY_INVALID",
        "CALENDAR_FORMAL_PUBLICATION_ROW_INVALID",
        "CALENDAR_FORMAL_SEAL_INVALID",
        "CALENDAR_FORMAL_SOURCE_MISSING",
        "CALENDAR_FORMAL_MEMBER_INVALID",
        "CALENDAR_FORMAL_MEMBER_BINDING_INVALID",
        "CALENDAR_FORMAL_CATALOG_INVALID",
        "CALENDAR_FORMAL_CATALOG_CLOCK_INVALID",
        "CALENDAR_FORMAL_AUDIT_INTEGRITY_INVALID",
    }
    if raw_code in changed_codes:
        return "FIN_AVAILABILITY_CURRENT_CALENDAR_CHANGED"
    return "FIN_AVAILABILITY_CURRENT_CALENDAR_UNAVAILABLE"


def _proof_from_authenticated_request(
    request: HttpRequest,
) -> FinancialAvailabilitySessionRequestProof:
    """Extract only the live request's authenticated Django User and session key."""

    if not isinstance(request, HttpRequest):
        raise AuthorizationError("C2 Owner writes require a real Django HttpRequest.")
    user = request.user
    if not isinstance(user, AbstractBaseUser):
        raise AuthorizationError("C2 Owner request has no authenticated Django User.")
    try:
        user_id = user.pk
        user_alias = user._state.db
        session_key = request.session.session_key
        authenticated = user.is_authenticated
    except (AttributeError, TypeError) as error:
        raise AuthorizationError("C2 Owner request has no persisted session identity.") from error
    if (
        authenticated is not True
        or type(user_id) is not int
        or user_id <= 0
        or type(user_alias) is not str
        or not user_alias
        or type(session_key) is not str
        or not session_key
    ):
        raise AuthorizationError("C2 Owner request has no persisted authenticated session.")
    request_at = timezone.now()
    return FinancialAvailabilitySessionRequestProof(
        user_id=user_id,
        session_key=session_key,
        request_authenticated_at=request_at.astimezone(UTC),
        request_user_database_alias=user_alias,
        database_alias=user_alias,
    )


def _require_default_request_alias(request_alias: str, repository_alias: str) -> None:
    """Prevent default-authenticated Users from being relabeled onto another DB."""

    if request_alias != DEFAULT_DB_ALIAS or repository_alias != DEFAULT_DB_ALIAS:
        raise AuthorizationError(
            "C2 HTTP authorization and configuration must use the default database alias."
        )


def _require_default_caller_uow() -> None:
    """Require the one caller-owned READ COMMITTED transaction used by calendar readers."""

    connection = connections[DEFAULT_DB_ALIAS]
    if (
        connection.alias != DEFAULT_DB_ALIAS
        or connection.vendor != "postgresql"
        or not connection.in_atomic_block
        or connection.get_autocommit()
        or len(connection.atomic_blocks) != 1
    ):
        raise DataValidationError(
            "E1 C2 readback requires one caller-owned default PostgreSQL UOW.",
            code="FIN_AVAILABILITY_CURRENT_UOW_INVALID",
        )
    with connection.cursor() as cursor:
        cursor.execute("SHOW transaction_isolation")
        row = cursor.fetchone()
    if row is None or row[0] != "read committed":
        raise DataValidationError(
            "E1 C2 readback requires READ COMMITTED isolation.",
            code="FIN_AVAILABILITY_CURRENT_UOW_INVALID",
        )


def _require_utc(value: object, name: str) -> datetime:
    """Require a trusted server-sampled aware UTC instant."""

    if type(value) is not datetime or value.tzinfo is None or value.utcoffset() != timedelta(0):
        raise DataValidationError(
            f"{name} must be an aware UTC datetime.",
            code="FIN_AVAILABILITY_CURRENT_CLOCK_INVALID",
        )
    return value.astimezone(UTC)


__all__ = [
    "apply_financial_availability_governance_from_request",
    "build_financial_next_session_witness_v3",
    "revoke_financial_availability_governance_from_request",
    "validate_financial_next_session_witness_current",
]
