"""Compose captured Data Center evidence with canonical disclosure Audit writes."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path

from django.utils import timezone

from apps.audit.application.security_disclosure_audit import (
    AppendSecurityDisclosureAuditObservationUseCase,
    SecurityDisclosureAuditAppendResult,
    SecurityDisclosureAuditConflict,
    SecurityDisclosureAuditDisposition,
    SecurityDisclosureAuditObservation,
    SecurityDisclosureAuditUnavailable,
    SecurityDisclosureFactEvidence,
)
from apps.audit.application.system_audit_authority_renewal_guard import (
    SystemAuditAuthorityLease,
)
from apps.audit.domain.system_audit_event import AuditScopeRef
from apps.audit.infrastructure.system_audit_outbox_runtime import (
    build_security_disclosure_audit_writer,
    get_system_audit_authority_lease,
)
from apps.data_center.domain.security_disclosure_event import (
    SecurityDisclosureEvent,
    SecurityDisclosureEventAppendDisposition,
    SecurityDisclosureEventAppendResult,
    SecurityDisclosureExchange,
    SecurityDisclosureListingCoverageAppendResult,
    SecurityDisclosureListingCoverageProof,
    SecurityDisclosureSource,
)
from apps.data_center.security_disclosure_capture_composition import (
    CapturedOfficialSzseListingWindow,
    CapturedSzseDistributionCandidate,
    SzseDistributionWindowRequest,
    capture_szse_distribution_cohort,
    make_security_disclosure_event_append_use_cases,
)

_MAXIMUM_COHORT_LEASE = timedelta(seconds=60)


@dataclass(frozen=True, slots=True)
class SzseDistributionWindowIngestion:
    """Captured listing, selected facts, coverage proof, and Audit/Outbox receipt."""

    candidate: CapturedSzseDistributionCandidate
    events: tuple[SecurityDisclosureEventAppendResult, ...]
    coverage: SecurityDisclosureListingCoverageAppendResult
    audit: SecurityDisclosureAuditAppendResult


def _preflight_disclosure_audit(
    *,
    environment: str,
    using: str,
) -> tuple[AppendSecurityDisclosureAuditObservationUseCase, AuditScopeRef, datetime, datetime]:
    """Require live required/outbox authority and a scoped writer before capture."""

    checked_at = timezone.now()
    lease = get_system_audit_authority_lease(environment=environment, using=using)
    if (
        type(lease) is not SystemAuditAuthorityLease
        or lease.mode != "required"
        or lease.outbox_enabled is not True
        or lease.valid_until is None
        or lease.valid_until <= checked_at
    ):
        raise SecurityDisclosureAuditUnavailable(
            "SZSE disclosure capture requires an active required Audit/Outbox authority lease."
        )
    writer = build_security_disclosure_audit_writer(environment=environment, using=using)
    if writer.database_alias != using:
        raise SecurityDisclosureAuditUnavailable(
            "SZSE disclosure facts and Audit/Outbox must share one database alias."
        )
    valid_until = lease.valid_until
    if valid_until is None:
        raise SecurityDisclosureAuditUnavailable(
            "SZSE disclosure capture requires an expiring Audit authority lease."
        )
    return writer, writer.preflight(as_of=checked_at), valid_until, checked_at


def capture_and_append_szse_distribution_window(
    *,
    asset_code: str,
    start_on: date,
    end_on: date,
    body_store_root: Path,
    using: str = "default",
    audit_environment: str = "production",
) -> SzseDistributionWindowIngestion:
    """Preserve the single-window API by delegating to a one-member cohort."""

    request = SzseDistributionWindowRequest(
        asset_code=asset_code,
        start_on=start_on,
        end_on=end_on,
        body_store_root=body_store_root,
    )
    return capture_and_append_szse_distribution_cohort(
        (request,),
        lease_ttl=_MAXIMUM_COHORT_LEASE,
        using=using,
        audit_environment=audit_environment,
    )[0]


def capture_and_append_szse_distribution_cohort(
    windows: tuple[SzseDistributionWindowRequest, ...],
    *,
    lease_ttl: timedelta,
    using: str = "default",
    audit_environment: str = "production",
) -> tuple[SzseDistributionWindowIngestion, ...]:
    """Capture every source first, then atomically persist one verified cohort."""

    if (
        type(windows) is not tuple
        or not windows
        or any(type(window) is not SzseDistributionWindowRequest for window in windows)
        or type(lease_ttl) is not timedelta
        or lease_ttl <= timedelta(0)
        or lease_ttl > _MAXIMUM_COHORT_LEASE
    ):
        raise SecurityDisclosureAuditUnavailable("SZSE disclosure cohort scope is invalid.")
    first = windows[0]
    if any(
        window.start_on != first.start_on or window.end_on != first.end_on for window in windows
    ) or len({window.asset_code for window in windows}) != len(windows):
        raise SecurityDisclosureAuditUnavailable("SZSE disclosure cohort identities are invalid.")

    audit_writer, initial_scope, _, _ = _preflight_disclosure_audit(
        environment=audit_environment,
        using=using,
    )
    candidates = capture_szse_distribution_cohort(windows)
    if type(candidates) is not tuple or len(candidates) != len(windows):
        raise SecurityDisclosureAuditUnavailable("SZSE disclosure cohort is incomplete.")

    common_verified_at: datetime | None = None
    observations: list[SecurityDisclosureAuditObservation] = []
    for window, candidate in zip(windows, candidates, strict=True):
        if (
            type(candidate) is not CapturedSzseDistributionCandidate
            or type(candidate.listing) is not CapturedOfficialSzseListingWindow
            or type(candidate.proof) is not SecurityDisclosureListingCoverageProof
            or type(candidate.events) is not tuple
            or candidate.proof.source is not SecurityDisclosureSource.SZSE_OFFICIAL
            or candidate.proof.exchange is not SecurityDisclosureExchange.SZSE
            or candidate.proof.asset_code != window.asset_code
            or candidate.proof.start_on != window.start_on
            or candidate.proof.end_on != window.end_on
            or candidate.listing.asset_code != window.asset_code
            or candidate.listing.start_on != window.start_on
            or candidate.listing.end_on != window.end_on
            or candidate.listing.observed_at > candidate.proof.verified_at
        ):
            raise SecurityDisclosureAuditUnavailable("SZSE disclosure cohort identity mismatched.")
        if common_verified_at is None:
            common_verified_at = candidate.proof.verified_at
        elif candidate.proof.verified_at != common_verified_at:
            raise SecurityDisclosureAuditUnavailable(
                "SZSE disclosure cohort does not share one verification clock."
            )
        if any(
            event.source is not SecurityDisclosureSource.SZSE_OFFICIAL
            or event.exchange is not SecurityDisclosureExchange.SZSE
            or event.asset_code != window.asset_code
            for event, _ in candidate.events
        ):
            raise SecurityDisclosureAuditUnavailable("SZSE disclosure fact identity mismatched.")

    if common_verified_at is None:
        raise SecurityDisclosureAuditUnavailable(
            "SZSE disclosure cohort has no verification clock."
        )
    audit_writer, current_scope, lease_valid_until, _ = _preflight_disclosure_audit(
        environment=audit_environment,
        using=using,
    )
    if current_scope != initial_scope:
        raise SecurityDisclosureAuditUnavailable(
            "SZSE disclosure Audit authority changed during external cohort capture."
        )
    batch_recorded_at = timezone.now()
    try:
        verified_expires_at = common_verified_at + lease_ttl
    except OverflowError as error:
        raise SecurityDisclosureAuditUnavailable(
            "SZSE disclosure cohort lease deadline is invalid."
        ) from error
    if (
        batch_recorded_at < common_verified_at
        or batch_recorded_at >= verified_expires_at
        or batch_recorded_at >= lease_valid_until
    ):
        raise SecurityDisclosureAuditUnavailable(
            "SZSE disclosure cohort clock is outside the active half-open lease."
        )
    if any(
        event.available_at > batch_recorded_at
        for candidate in candidates
        for event, _ in candidate.events
    ):
        raise SecurityDisclosureAuditUnavailable(
            "SZSE disclosure batch clock predates source availability."
        )

    for candidate in candidates:
        proof = candidate.proof
        observations.append(
            SecurityDisclosureAuditObservation(
                source=proof.source.value,
                exchange=proof.exchange.value,
                asset_code=proof.asset_code,
                start_on=proof.start_on,
                end_on=proof.end_on,
                first_observed_at=proof.first_observed_at,
                verified_at=common_verified_at,
                announcement_count=proof.announcement_count,
                coverage_manifest_sha256=proof.coverage_manifest_sha256,
                source_manifest_sha256=proof.source_manifest_sha256,
                first_pass_page_body_sha256=proof.first_pass_page_body_sha256,
                second_pass_page_body_sha256=proof.second_pass_page_body_sha256,
                facts=tuple(_fact_evidence(event) for event, _ in candidate.events),
                recorded_at=batch_recorded_at,
                scope=current_scope,
            )
        )
    appenders = make_security_disclosure_event_append_use_cases(
        using=using,
        recorded_at=batch_recorded_at,
    )
    if appenders.database_alias != using or audit_writer.database_alias != using:
        raise SecurityDisclosureAuditUnavailable(
            "Disclosure facts, coverage, and Audit/Outbox must share one alias."
        )

    ingestions: list[SzseDistributionWindowIngestion] = []
    with audit_writer.atomic():
        for candidate, observation in zip(candidates, observations, strict=True):
            results = [appenders.events.execute(event, body) for event, body in candidate.events]
            existing_audit = audit_writer.find_exact_winner(
                observation,
                as_of=batch_recorded_at,
                scope=current_scope,
            )
            if existing_audit is None:
                duplicate_facts = tuple(
                    _fact_evidence(result.record.event)
                    for result in results
                    if result.disposition is SecurityDisclosureEventAppendDisposition.DUPLICATE
                )
                if duplicate_facts:
                    audit_writer.assert_previously_audited_facts(
                        observation,
                        facts=duplicate_facts,
                        as_of=batch_recorded_at,
                        scope=current_scope,
                    )
                coverage = appenders.coverage.execute(candidate.proof)
                if coverage.disposition is SecurityDisclosureEventAppendDisposition.DUPLICATE:
                    raise SecurityDisclosureAuditConflict(
                        "Un-audited disclosure coverage proof already exists for this source batch."
                    )
            else:
                if any(
                    result.disposition is not SecurityDisclosureEventAppendDisposition.DUPLICATE
                    for result in results
                ):
                    raise SecurityDisclosureAuditConflict(
                        "An audited disclosure batch is missing one or more immutable source facts."
                    )
                persisted_proof = appenders.coverage.get_by_episode(candidate.proof)
                if persisted_proof is None:
                    raise SecurityDisclosureAuditConflict(
                        "An audited disclosure batch is missing its immutable coverage proof."
                    )
                coverage = SecurityDisclosureListingCoverageAppendResult(
                    disposition=SecurityDisclosureEventAppendDisposition.DUPLICATE,
                    record=persisted_proof,
                )
            audit = audit_writer.execute_in_atomic_transaction(
                observation,
                scope=current_scope,
            )
            if (
                existing_audit is None
                and audit.disposition is not SecurityDisclosureAuditDisposition.STORED
            ):
                raise SecurityDisclosureAuditConflict(
                    "Disclosure Audit identity changed during the atomic append."
                )
            if (
                existing_audit is not None
                and audit.disposition is not SecurityDisclosureAuditDisposition.DUPLICATE
            ):
                raise SecurityDisclosureAuditConflict(
                    "Existing disclosure Audit identity was not replayed exactly."
                )
            ingestions.append(
                SzseDistributionWindowIngestion(
                    candidate=candidate,
                    events=tuple(results),
                    coverage=coverage,
                    audit=audit,
                )
            )

        final_writer, final_scope, final_lease_until, commit_checked_at = (
            _preflight_disclosure_audit(environment=audit_environment, using=using)
        )
        if (
            final_writer.database_alias != using
            or final_scope != current_scope
            or commit_checked_at < batch_recorded_at
            or commit_checked_at >= verified_expires_at
            or commit_checked_at >= batch_recorded_at + lease_ttl
            or commit_checked_at >= final_lease_until
        ):
            raise SecurityDisclosureAuditUnavailable(
                "SZSE disclosure cohort expired or its Audit authority changed before commit."
            )
    return tuple(ingestions)


def _fact_evidence(event: SecurityDisclosureEvent) -> SecurityDisclosureFactEvidence:
    """Project one captured source event into its exact Audit evidence identity."""

    return SecurityDisclosureFactEvidence(
        source_event_id=event.source_event_id,
        source_revision_id=event.source_revision_id,
        content_hash=event.content_hash,
        source_body_sha256=event.source_body_sha256,
    )
