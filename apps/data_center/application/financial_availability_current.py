"""Current, fenced C2 governance reads and v3 temporal revalidation.

Successful values from this module remain reference-only. They recheck current
rule/policy rows and calendar timing; they do not grant E1 publication or
financial-decision eligibility.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import UTC, date, datetime
from typing import NoReturn

from apps.data_center.application.financial_availability_governance import (
    FinancialAvailabilityGovernanceReadResult,
    materialize_financial_availability_record,
)
from apps.data_center.application.financial_availability_governance_ports import (
    FinancialAvailabilityGovernanceRepositoryPort,
    FinancialAvailabilityOwnerEventRepositoryPort,
    FinancialAvailabilitySourceRead,
    FinancialAvailabilitySourceReaderPort,
)
from apps.data_center.application.formal_exchange_calendar_publication import (
    CalendarFormalPublicationApplicationError,
    CurrentPublishedExchangeCalendar,
)
from apps.data_center.application.formal_exchange_calendar_publication_history import (
    HistoricalPublishedExchangeCalendar,
)
from apps.data_center.domain.calendar_publication_window import CalendarPublicationLifecycle
from apps.data_center.domain.exchange_calendar import (
    ExchangeCalendarError,
    next_exchange_calendar_session,
)
from apps.data_center.domain.financial_availability_governance import (
    ExchangeSessionOpeningRuleProposal,
    FinancialAvailabilityGovernanceRecord,
    FinancialAvailabilityOwnerEventAction,
    FinancialAvailabilityOwnerEventIdentity,
    FinancialAvailabilityRecordKind,
    resolve_financial_availability_owner_apply,
)
from apps.data_center.domain.financial_next_session_availability import (
    ExchangeSessionOpeningRule,
    FinancialNextSessionAvailability,
    FinancialNextSessionAvailabilityError,
    resolve_financial_next_session_availability,
)
from apps.data_center.domain.financial_next_session_witness import (
    FinancialApprovalIdentity,
    FinancialCalendarPublicationReference,
    FinancialDisclosureAvailabilityPolicy,
    FinancialNextSessionSourceTimeWitnessV3,
)
from apps.data_center.domain.formal_exchange_calendar_publication import (
    CalendarFormalPublicationError,
    exchange_calendar_publication_key,
    validate_current_calendar_publication,
)
from core.exceptions import DataValidationError


@dataclass(frozen=True, slots=True)
class ResolveCurrentFinancialAvailabilityGovernanceQuery:
    """Resolve both C2 configuration kinds for one explicit next-session date."""

    exchange: str
    effective_on: date

    def __post_init__(self) -> None:
        """Reject incomplete current selectors; current time is sampled after locks."""

        if (
            type(self.exchange) is not str
            or not self.exchange
            or self.exchange.strip() != self.exchange
        ):
            raise ValueError("exchange must be explicit canonical text")
        try:
            if not exchange_calendar_publication_key(self.exchange):
                raise ValueError("exchange is unsupported by the formal calendar contract")
        except (CalendarFormalPublicationError, TypeError, ValueError) as error:
            raise ValueError("exchange is unsupported by the formal calendar contract") from error
        if type(self.effective_on) is not date:
            raise ValueError("effective_on must be an exact date")


@dataclass(frozen=True, slots=True)
class CurrentFinancialAvailabilityGovernancePair:
    """One locked, current opening-rule and policy pair with an unchanged cutoff."""

    exchange: str
    effective_on: date
    opening_rule: FinancialAvailabilityGovernanceReadResult
    disclosure_policy: FinancialAvailabilityGovernanceReadResult
    known_at: datetime
    checked_at: datetime

    def __post_init__(self) -> None:
        """Bind both rows, both event streams, and clocks to one current scope."""

        if type(self.exchange) is not str or not self.exchange:
            raise ValueError("current governance exchange is invalid")
        if type(self.effective_on) is not date:
            raise ValueError("current governance effective date is invalid")
        _require_utc(self.known_at, "known_at")
        _require_utc(self.checked_at, "checked_at")
        if self.checked_at < self.known_at:
            raise ValueError("current governance check clock precedes its locked cutoff")
        if (
            type(self.opening_rule) is not FinancialAvailabilityGovernanceReadResult
            or type(self.disclosure_policy) is not FinancialAvailabilityGovernanceReadResult
        ):
            raise ValueError("current governance pair requires exact typed read results")
        for result, expected_kind in (
            (self.opening_rule, FinancialAvailabilityRecordKind.OPENING_RULE),
            (self.disclosure_policy, FinancialAvailabilityRecordKind.DISCLOSURE_POLICY),
        ):
            if (
                result.record.kind is not expected_kind
                or result.record.exchange != self.exchange
                or result.known_at != self.known_at
                or result.checked_at > self.checked_at
            ):
                raise ValueError("current governance pair scope or cutoff differs")
            start, end = _effective_range(result.record)
            if not start <= self.effective_on <= end:
                raise ValueError("current governance pair is outside its effective dates")

    @property
    def reference_only(self) -> bool:
        """Report that current database checks are not a decision qualification."""

        return True

    @property
    def must_not_use_for_decision(self) -> bool:
        """Require the later E1 source and publication gates to run independently."""

        return True

    @property
    def must_not_execute(self) -> bool:
        """This governance read has no order execution capability."""

        return True


@dataclass(frozen=True, slots=True)
class CurrentFinancialNextSessionTemporalCheck:
    """Evidence-only current remap while preserving the original v3 witness."""

    witness: FinancialNextSessionSourceTimeWitnessV3
    governance: CurrentFinancialAvailabilityGovernancePair
    historical_calendar: HistoricalPublishedExchangeCalendar
    current_calendar: CurrentPublishedExchangeCalendar
    current_availability: FinancialNextSessionAvailability
    checked_at: datetime

    def __post_init__(self) -> None:
        """Recheck the old exact as-of and the new current freshness boundary."""

        expected = validate_current_financial_next_session_temporal_binding(
            self.witness,
            self.governance,
            self.historical_calendar,
            self.current_calendar,
            checked_at=self.checked_at,
        )
        if expected != self.current_availability:
            raise ValueError("current temporal check differs from its recomputed availability")

    @property
    def reference_only(self) -> bool:
        """Current temporal validation does not establish E1 or fact eligibility."""

        return True

    @property
    def must_not_use_for_decision(self) -> bool:
        """A separate qualified witness and current financial consumer gate remain required."""

        return True

    @property
    def must_not_execute(self) -> bool:
        """A calendar/source-time check has no execution capability."""

        return True


def resolve_current_financial_availability_governance(
    query: ResolveCurrentFinancialAvailabilityGovernanceQuery,
    *,
    records: FinancialAvailabilityGovernanceRepositoryPort,
    owner_events: FinancialAvailabilityOwnerEventRepositoryPort,
    source_reader: FinancialAvailabilitySourceReaderPort,
) -> CurrentFinancialAvailabilityGovernancePair:
    """Resolve active C2 rule/policy only under one caller-owned PG RC UOW.

    The same transaction-scoped scope keys are exclusive for apply/revoke and
    shared here. Every configuration row and every lifecycle event in both
    scopes is locked and re-decoded before the database clock is sampled. The
    returned ``known_at`` is that post-lock clock; it never replaces a v3
    witness's original historical cutoff.
    """

    if type(query) is not ResolveCurrentFinancialAvailabilityGovernanceQuery:
        raise DataValidationError(
            "C2 current resolution requires an exact typed query.",
            code="FIN_AVAILABILITY_CURRENT_QUERY_INVALID",
        )
    try:
        query.__post_init__()
    except (TypeError, ValueError) as error:
        raise DataValidationError(
            "C2 current resolution query is invalid.",
            code="FIN_AVAILABILITY_CURRENT_QUERY_INVALID",
        ) from error
    aliases = (records.database_alias, owner_events.database_alias, source_reader.database_alias)
    if any(type(alias) is not str or not alias or alias.strip() != alias for alias in aliases):
        raise DataValidationError(
            "C2 current resolution alias is invalid.",
            code="FIN_AVAILABILITY_CURRENT_ALIAS_INVALID",
        )
    if not (aliases[0] == aliases[1] == aliases[2]):
        raise DataValidationError(
            "C2 current governance and source reads must share one alias.",
            code="FIN_AVAILABILITY_CURRENT_ALIAS_MISMATCH",
        )

    records.require_caller_owned_current_uow()
    scopes = (
        (FinancialAvailabilityRecordKind.OPENING_RULE, query.exchange),
        (FinancialAvailabilityRecordKind.DISCLOSURE_POLICY, query.exchange),
    )
    records.lock_current_scopes(scopes)
    rows_by_kind: dict[
        FinancialAvailabilityRecordKind,
        tuple[FinancialAvailabilityGovernanceRecord, ...],
    ] = {}
    histories: dict[tuple[str, str], tuple[FinancialAvailabilityOwnerEventIdentity, ...]] = {}
    for kind, exchange in scopes:
        try:
            rows = records.list_scope_for_current_update(kind=kind, exchange=exchange)
        except DataValidationError as error:
            raise DataValidationError(
                "C2 current scope row is missing or changed.",
                code="FIN_AVAILABILITY_GOVERNANCE_CHANGED",
            ) from error
        if type(rows) is not tuple:
            raise DataValidationError(
                "C2 current repository returned an invalid locked row set.",
                code="FIN_AVAILABILITY_GOVERNANCE_CHANGED",
            )
        checked_rows: list[FinancialAvailabilityGovernanceRecord] = []
        for record in rows:
            if type(record) is not FinancialAvailabilityGovernanceRecord:
                raise DataValidationError(
                    "C2 current repository returned an untyped row.",
                    code="FIN_AVAILABILITY_GOVERNANCE_CHANGED",
                )
            try:
                record.__post_init__()
            except (TypeError, ValueError) as error:
                raise DataValidationError(
                    "C2 current configuration row is corrupt.",
                    code="FIN_AVAILABILITY_GOVERNANCE_CHANGED",
                ) from error
            if record.kind is not kind or record.exchange != exchange:
                raise DataValidationError(
                    "C2 current repository crossed the requested scope.",
                    code="FIN_AVAILABILITY_GOVERNANCE_CHANGED",
                )
            key = (record.record_id, record.record_version)
            if key in histories:
                raise DataValidationError(
                    "C2 current configuration key is ambiguous.",
                    code="FIN_AVAILABILITY_GOVERNANCE_CHANGED",
                )
            try:
                history = owner_events.list_complete_history_for_update(
                    record_id=record.record_id,
                    record_version=record.record_version,
                )
            except DataValidationError as error:
                raise DataValidationError(
                    "C2 current Owner event stream is missing or changed.",
                    code="FIN_AVAILABILITY_GOVERNANCE_CHANGED",
                ) from error
            if type(history) is not tuple:
                raise DataValidationError(
                    "C2 current repository returned an invalid locked event stream.",
                    code="FIN_AVAILABILITY_GOVERNANCE_CHANGED",
                )
            histories[key] = history
            checked_rows.append(record)
        rows_by_kind[kind] = tuple(checked_rows)

    # Deliberately sample only after both scope sets and all existing lifecycle
    # rows are locked. This is the current operation cutoff, not tx start time.
    known_at = _require_utc(records.now(), "database server time")
    opening = _resolve_kind(
        kind=FinancialAvailabilityRecordKind.OPENING_RULE,
        exchange=query.exchange,
        effective_on=query.effective_on,
        known_at=known_at,
        rows=rows_by_kind[FinancialAvailabilityRecordKind.OPENING_RULE],
        histories=histories,
        source_reader=source_reader,
    )
    policy = _resolve_kind(
        kind=FinancialAvailabilityRecordKind.DISCLOSURE_POLICY,
        exchange=query.exchange,
        effective_on=query.effective_on,
        known_at=known_at,
        rows=rows_by_kind[FinancialAvailabilityRecordKind.DISCLOSURE_POLICY],
        histories=histories,
        source_reader=source_reader,
    )
    checked_at = _require_utc(records.now(), "database server check time")
    if checked_at < known_at:
        raise DataValidationError(
            "C2 current database clock moved backwards.",
            code="FIN_AVAILABILITY_CURRENT_CLOCK_INVALID",
        )
    return CurrentFinancialAvailabilityGovernancePair(
        exchange=query.exchange,
        effective_on=query.effective_on,
        opening_rule=replace(opening, checked_at=max(opening.checked_at, checked_at)),
        disclosure_policy=replace(policy, checked_at=max(policy.checked_at, checked_at)),
        known_at=known_at,
        checked_at=checked_at,
    )


def validate_current_financial_next_session_temporal_binding(
    witness: FinancialNextSessionSourceTimeWitnessV3,
    governance: CurrentFinancialAvailabilityGovernancePair,
    historical_calendar: HistoricalPublishedExchangeCalendar,
    current_calendar: CurrentPublishedExchangeCalendar,
    *,
    checked_at: datetime,
) -> FinancialNextSessionAvailability:
    """Re-read the witness's original calendar as-of and current fresh mapping.

    The original witness and its expiry are immutable. This check independently
    verifies the exact historical publication at ``witness.known_at`` and then
    recalculates NOTICE_DATE against the current fresh calendar and exact
    currently applied C2 rule/policy. It never extends the old publication's
    TTL and returns no financial decision or publication authority.
    """

    if type(witness) is not FinancialNextSessionSourceTimeWitnessV3:
        raise DataValidationError(
            "C2 temporal check requires one exact v3 witness.",
            code="FIN_AVAILABILITY_CURRENT_WITNESS_INVALID",
        )
    if type(governance) is not CurrentFinancialAvailabilityGovernancePair:
        raise DataValidationError(
            "C2 temporal check requires one locked current governance pair.",
            code="FIN_AVAILABILITY_GOVERNANCE_CHANGED",
        )
    if type(historical_calendar) is not HistoricalPublishedExchangeCalendar:
        raise DataValidationError(
            "C2 temporal check requires an exact historical publication and Audit pair.",
            code="FIN_AVAILABILITY_HISTORICAL_CALENDAR_MISSING",
        )
    if type(current_calendar) is not CurrentPublishedExchangeCalendar:
        raise DataValidationError(
            "C2 temporal check requires an exact fresh current publication.",
            code="FIN_AVAILABILITY_CURRENT_CALENDAR_MISSING",
        )
    try:
        witness.__post_init__()
        governance.__post_init__()
        _require_utc(checked_at, "checked_at")
    except (TypeError, ValueError) as error:
        raise DataValidationError(
            "C2 temporal check input is invalid.",
            code="FIN_AVAILABILITY_CURRENT_WITNESS_INVALID",
        ) from error
    if governance.exchange != witness.availability.calendar.exchange:
        _block("FIN_AVAILABILITY_GOVERNANCE_CHANGED", "C2 scope differs from the witness.")
    if governance.effective_on != witness.availability.next_session:
        _block(
            "FIN_AVAILABILITY_GOVERNANCE_CHANGED",
            "C2 versions were not resolved for the witness's exact next session.",
        )
    if governance.known_at < witness.known_at:
        _block(
            "FIN_AVAILABILITY_CURRENT_CUTOFF_INVALID",
            "Current governance cutoff predates the original witness.",
        )
    if checked_at < max(governance.checked_at, current_calendar.as_of):
        _block(
            "FIN_AVAILABILITY_CURRENT_CLOCK_INVALID",
            "Current check cutoff predates one of its locked reads.",
        )
    if witness.known_at > checked_at or not witness.is_temporally_available_at(checked_at):
        _block(
            "FIN_AVAILABILITY_NOT_TEMPORALLY_AVAILABLE",
            "The original financial response or next-session instant is not yet available.",
        )

    _verify_original_calendar_reference(witness, historical_calendar)
    _verify_current_governance_binding(witness, governance)
    if current_calendar.as_of != governance.known_at:
        _block(
            "FIN_AVAILABILITY_CURRENT_CUTOFF_INVALID",
            "Current calendar and governance reads use different operation cutoffs.",
        )
    try:
        validate_current_calendar_publication(
            current_calendar.record,
            current_calendar.pointer,
            as_of=current_calendar.as_of,
        )
        validate_current_calendar_publication(
            current_calendar.record,
            current_calendar.pointer,
            as_of=checked_at,
        )
    except (CalendarFormalPublicationError, TypeError, ValueError) as error:
        code = (
            "FIN_AVAILABILITY_CURRENT_CALENDAR_EXPIRED"
            if getattr(error, "code", "") == "CALENDAR_FORMAL_TTL_EXPIRED"
            else "FIN_AVAILABILITY_CURRENT_CALENDAR_CHANGED"
        )
        raise DataValidationError(
            "Current formal calendar is no longer exact and fresh at the check cutoff.",
            code=code,
        ) from error

    opening = governance.opening_rule.resolved_content
    policy = governance.disclosure_policy.resolved_content
    if type(opening) is not ExchangeSessionOpeningRule:
        _block("FIN_AVAILABILITY_GOVERNANCE_CHANGED", "Applied C2 opening rule is invalid.")
    if type(policy) is not FinancialDisclosureAvailabilityPolicy:
        _block("FIN_AVAILABILITY_GOVERNANCE_CHANGED", "Applied C2 policy is invalid.")
    try:
        current = resolve_financial_next_session_availability(
            source_date=witness.financial_row.notice_date,
            known_at=governance.known_at,
            calendar_record=current_calendar.record,
            calendar_pointer=current_calendar.pointer,
            opening_rule=opening,
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
        raise DataValidationError(str(error), code=code) from error
    if (
        current.next_session != witness.availability.next_session
        or current.available_at != witness.availability.available_at
    ):
        _block(
            "FIN_AVAILABILITY_NEXT_SESSION_MAPPING_CHANGED",
            "Fresh calendar or currently applied rule changes the notice-to-open mapping.",
        )
    try:
        governance_record_calendar_ttl = (
            current.calendar_record.seal.calendar_response_max_age_seconds
        )
        witness.governance.validate_for(
            opening_rule=opening,
            calendar=FinancialCalendarPublicationReference.from_resolved_availability(current),
            next_session=current.next_session,
            known_at=governance.known_at,
        )
    except (TypeError, ValueError):
        _block(
            "FIN_AVAILABILITY_GOVERNANCE_CHANGED",
            "Current approved rule/policy does not match the fresh calendar binding.",
        )
    if policy.calendar_response_max_age_seconds != governance_record_calendar_ttl:
        _block(
            "FIN_AVAILABILITY_GOVERNANCE_CHANGED",
            "Current approved policy and fresh calendar TTL differ.",
        )
    return current


def _resolve_kind(
    *,
    kind: FinancialAvailabilityRecordKind,
    exchange: str,
    effective_on: date,
    known_at: datetime,
    rows: tuple[FinancialAvailabilityGovernanceRecord, ...],
    histories: dict[tuple[str, str], tuple[FinancialAvailabilityOwnerEventIdentity, ...]],
    source_reader: FinancialAvailabilitySourceReaderPort,
) -> FinancialAvailabilityGovernanceReadResult:
    """Select exactly one applied version from already locked current inputs."""

    if not rows:
        _block("FIN_AVAILABILITY_GOVERNANCE_MISSING", "No C2 version exists in this scope.")
    current_rows: list[FinancialAvailabilityGovernanceRecord] = []
    for record in rows:
        if record.recorded_at > known_at:
            _block(
                "FIN_AVAILABILITY_GOVERNANCE_CHANGED",
                "A locked C2 version has a future record clock.",
            )
        start, end = _effective_range(record)
        if start <= effective_on <= end:
            current_rows.append(record)
    if not current_rows:
        if all(_effective_range(record)[1] < effective_on for record in rows):
            _block(
                "FIN_AVAILABILITY_GOVERNANCE_EXPIRED",
                "All C2 versions ended before the requested next session.",
            )
        _block(
            "FIN_AVAILABILITY_GOVERNANCE_NOT_EFFECTIVE",
            "No C2 version covers the requested next session.",
        )

    active: list[FinancialAvailabilityGovernanceReadResult] = []
    observed_revoke = False
    for record in current_rows:
        history = histories[(record.record_id, record.record_version)]
        if any(
            event.action is FinancialAvailabilityOwnerEventAction.REVOKE
            and event.recorded_at <= known_at
            for event in history
        ):
            observed_revoke = True
        try:
            apply = resolve_financial_availability_owner_apply(
                record,
                history,
                known_at=known_at,
                server_now=known_at,
            )
        except (TypeError, ValueError) as error:
            raise DataValidationError(
                "C2 current lifecycle history failed exact revalidation.",
                code="FIN_AVAILABILITY_GOVERNANCE_CHANGED",
            ) from error
        if apply is None:
            continue
        try:
            content = materialize_financial_availability_record(record, apply)
        except (TypeError, ValueError, DataValidationError) as error:
            raise DataValidationError(
                "C2 current apply event does not bind its exact content.",
                code="FIN_AVAILABILITY_GOVERNANCE_CHANGED",
            ) from error
        source_read: FinancialAvailabilitySourceRead | None = None
        if kind is FinancialAvailabilityRecordKind.OPENING_RULE:
            source = record.source
            if source is None:
                _block(
                    "FIN_AVAILABILITY_GOVERNANCE_CHANGED",
                    "Applied opening rule lost its exact source capture.",
                )
            try:
                source_read = source_reader.read_exact_capture(
                    issuer=source.issuer,
                    document_id=source.document_id,
                    source_version=source.source_version,
                    capture_id=source.capture_id,
                    known_at=known_at,
                )
            except DataValidationError as error:
                raise DataValidationError(
                    "C2 opening rule source capture changed during current reread.",
                    code="FIN_AVAILABILITY_GOVERNANCE_SOURCE_CHANGED",
                ) from error
            if (
                type(source_read) is not FinancialAvailabilitySourceRead
                or source_read.reference != source
            ):
                _block(
                    "FIN_AVAILABILITY_GOVERNANCE_SOURCE_CHANGED",
                    "Applied opening rule's exact statutory capture is absent or changed.",
                )
            try:
                source_read.__post_init__()
            except (TypeError, ValueError) as error:
                raise DataValidationError(
                    "C2 opening rule source capture failed exact readback.",
                    code="FIN_AVAILABILITY_GOVERNANCE_SOURCE_CHANGED",
                ) from error
        active.append(
            FinancialAvailabilityGovernanceReadResult(
                record=record,
                apply_event=apply,
                resolved_content=content,
                known_at=known_at,
                checked_at=max(known_at, source_read.checked_at if source_read else known_at),
                source_read=source_read,
            )
        )
    if not active:
        if observed_revoke:
            _block(
                "FIN_AVAILABILITY_GOVERNANCE_REVOKED",
                "The current C2 version has a visible revoke event.",
            )
        _block(
            "FIN_AVAILABILITY_GOVERNANCE_MISSING",
            "No applied C2 version is visible at the post-lock cutoff.",
        )
    if len(active) != 1:
        _block(
            "FIN_AVAILABILITY_GOVERNANCE_AMBIGUOUS",
            "Multiple applied C2 versions overlap the current scope.",
        )
    return active[0]


def _effective_range(record: FinancialAvailabilityGovernanceRecord) -> tuple[date, date]:
    """Return explicit effective dates from one exact record payload."""

    content = record.content
    if type(content) is ExchangeSessionOpeningRuleProposal:
        return content.effective_start, content.effective_end
    if type(content) is FinancialDisclosureAvailabilityPolicy:
        return content.effective_start, content.effective_end
    _block("FIN_AVAILABILITY_GOVERNANCE_CHANGED", "C2 record payload kind is unsupported.")


def _verify_original_calendar_reference(
    witness: FinancialNextSessionSourceTimeWitnessV3,
    historical: HistoricalPublishedExchangeCalendar,
) -> None:
    """Bind history read to the old immutable publication and original cutoff."""

    reference = witness.availability.calendar
    record = historical.record
    seal = record.seal
    try:
        historical.__post_init__()
        effective = record.is_effective_at(witness.known_at)
    except (CalendarFormalPublicationApplicationError, TypeError, ValueError) as error:
        raise DataValidationError(
            "Original formal calendar evidence is malformed or changed.",
            code="FIN_AVAILABILITY_HISTORICAL_CALENDAR_CHANGED",
        ) from error
    if not effective:
        _block(
            "FIN_AVAILABILITY_HISTORICAL_CALENDAR_EXPIRED",
            "Original calendar publication was not effective at the witness cutoff.",
        )
    if (
        historical.as_of != witness.known_at
        or record.publication_id != reference.publication_id
        or seal.publication_hash != reference.publication_hash
        or seal.dataset.value != reference.dataset_key
        or seal.exchange != reference.exchange
        or seal.publication_key != reference.publication_key
        or seal.snapshot_reference != reference.snapshot_reference
        or seal.contract_recorded_at != reference.contract_recorded_at
        or seal.policy_version != reference.policy_version
        or seal.policy_identity != reference.policy_identity
        or seal.policy_recorded_at != reference.policy_recorded_at
        or seal.snapshot_first_seen_at != reference.snapshot_first_seen_at
        or seal.snapshot_recorded_at != reference.snapshot_recorded_at
        or seal.calendar_response_max_age_seconds != reference.response_max_age_seconds
        or record.published_at != reference.published_at
        or reference.lifecycle_at_resolution is not CalendarPublicationLifecycle.PUBLISHED
        or reference.superseded_at_at_resolution is not None
    ):
        _block(
            "FIN_AVAILABILITY_HISTORICAL_CALENDAR_CHANGED",
            "Historical calendar immutable identity differs from the original witness.",
        )
    try:
        historical_next = next_exchange_calendar_session(
            seal.snapshot,
            after_date=witness.financial_row.notice_date,
        )
    except (ExchangeCalendarError, TypeError, ValueError) as error:
        raise DataValidationError(
            "Original calendar cannot prove a strictly later open session.",
            code="FIN_AVAILABILITY_HISTORICAL_CALENDAR_CHANGED",
        ) from error
    if historical_next != witness.availability.next_session:
        _block(
            "FIN_AVAILABILITY_HISTORICAL_CALENDAR_CHANGED",
            "Original calendar no longer proves the witness's next session.",
        )


def _verify_current_governance_binding(
    witness: FinancialNextSessionSourceTimeWitnessV3,
    governance: CurrentFinancialAvailabilityGovernancePair,
) -> None:
    """Require exact current rule, policy and both real local Owner events."""

    rule_result = governance.opening_rule
    policy_result = governance.disclosure_policy
    rule = rule_result.resolved_content
    policy = policy_result.resolved_content
    if type(rule) is not ExchangeSessionOpeningRule or rule != witness.availability.opening_rule:
        _block(
            "FIN_AVAILABILITY_GOVERNANCE_CHANGED",
            "Current applied opening rule differs from the witness identity.",
        )
    if (
        type(policy) is not FinancialDisclosureAvailabilityPolicy
        or policy != witness.governance.policy
    ):
        _block(
            "FIN_AVAILABILITY_GOVERNANCE_CHANGED",
            "Current applied disclosure policy differs from the witness identity.",
        )
    _verify_approval(
        witness.governance.opening_rule_approval,
        record=rule_result.record,
        event=rule_result.apply_event,
        expected_record_id=witness.governance.opening_rule_record_id,
        expected_subject_sha256=rule.rule_sha256,
    )
    _verify_approval(
        witness.governance.policy_approval,
        record=policy_result.record,
        event=policy_result.apply_event,
        expected_record_id=policy.policy_id,
        expected_subject_sha256=policy.policy_sha256,
    )


def _verify_approval(
    approval: FinancialApprovalIdentity,
    *,
    record: FinancialAvailabilityGovernanceRecord,
    event: FinancialAvailabilityOwnerEventIdentity,
    expected_record_id: str,
    expected_subject_sha256: str,
) -> None:
    """Compare every v3 Owner reference with its locked local apply event."""

    if (
        record.record_id != expected_record_id
        or approval.subject_record_id != record.record_id
        or approval.subject_sha256 != expected_subject_sha256
        or approval.event_id != str(event.event_id)
        or approval.event_sha256 != event.event_sha256
        or approval.principal_id != event.actor_id
        or approval.approved_at != event.occurred_at
        or approval.recorded_at != event.recorded_at
        or event.action is not FinancialAvailabilityOwnerEventAction.APPLY
        or event.record_id != record.record_id
        or event.record_version != record.record_version
        or event.resulting_content_sha256 != expected_subject_sha256
    ):
        _block(
            "FIN_AVAILABILITY_GOVERNANCE_CHANGED",
            "Current Owner apply event differs from the exact v3 approval identity.",
        )


def _require_utc(value: object, name: str) -> datetime:
    """Require an exact aware zero-offset datetime without changing its cutoff."""

    if type(value) is not datetime or value.tzinfo is None:
        raise DataValidationError(
            f"{name} must be an explicit aware UTC datetime.",
            code="FIN_AVAILABILITY_CURRENT_CLOCK_INVALID",
        )
    offset = value.utcoffset()
    if offset is None or offset.total_seconds() != 0:
        raise DataValidationError(
            f"{name} must be an explicit aware UTC datetime.",
            code="FIN_AVAILABILITY_CURRENT_CLOCK_INVALID",
        )
    try:
        return value.astimezone(UTC)
    except (OverflowError, ValueError) as error:
        raise DataValidationError(
            f"{name} is outside the UTC datetime range.",
            code="FIN_AVAILABILITY_CURRENT_CLOCK_INVALID",
        ) from error


def _block(code: str, message: str) -> NoReturn:
    """Raise one stable current C2 block reason."""

    raise DataValidationError(message, code=code)


__all__ = [
    "CurrentFinancialAvailabilityGovernancePair",
    "CurrentFinancialNextSessionTemporalCheck",
    "ResolveCurrentFinancialAvailabilityGovernanceQuery",
    "resolve_current_financial_availability_governance",
    "validate_current_financial_next_session_temporal_binding",
]
