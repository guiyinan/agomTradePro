"""Compose captured Data Center evidence with canonical disclosure Audit writes."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
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
    SecurityDisclosureListingCoverageAppendResult,
)
from apps.data_center.security_disclosure_capture_composition import (
    CapturedSzseDistributionCandidate,
    capture_szse_distribution_window,
    make_security_disclosure_event_append_use_cases,
)


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
) -> tuple[AppendSecurityDisclosureAuditObservationUseCase, AuditScopeRef, datetime]:
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
    return writer, writer.preflight(as_of=checked_at), valid_until


def capture_and_append_szse_distribution_window(
    *,
    asset_code: str,
    start_on: date,
    end_on: date,
    body_store_root: Path,
    using: str = "default",
    audit_environment: str = "production",
) -> SzseDistributionWindowIngestion:
    """Capture, recheck authority, then atomically persist facts, coverage, and Audit."""

    audit_writer, initial_scope, _ = _preflight_disclosure_audit(
        environment=audit_environment,
        using=using,
    )
    candidate = capture_szse_distribution_window(
        asset_code=asset_code,
        start_on=start_on,
        end_on=end_on,
        body_store_root=body_store_root,
    )
    audit_writer, current_scope, lease_valid_until = _preflight_disclosure_audit(
        environment=audit_environment,
        using=using,
    )
    if current_scope != initial_scope:
        raise SecurityDisclosureAuditUnavailable(
            "SZSE disclosure Audit authority changed during external capture."
        )
    proof = candidate.proof
    batch_recorded_at = timezone.now()
    if batch_recorded_at >= lease_valid_until:
        raise SecurityDisclosureAuditUnavailable(
            "SZSE disclosure batch clock is outside the active Audit authority lease."
        )
    if batch_recorded_at < proof.verified_at or any(
        event.available_at > batch_recorded_at for event, _ in candidate.events
    ):
        raise SecurityDisclosureAuditUnavailable(
            "SZSE disclosure batch clock predates verified source availability."
        )
    observation = SecurityDisclosureAuditObservation(
        source=proof.source.value,
        exchange=proof.exchange.value,
        asset_code=proof.asset_code,
        start_on=proof.start_on,
        end_on=proof.end_on,
        first_observed_at=proof.first_observed_at,
        verified_at=proof.verified_at,
        announcement_count=proof.announcement_count,
        coverage_manifest_sha256=proof.coverage_manifest_sha256,
        source_manifest_sha256=proof.source_manifest_sha256,
        first_pass_page_body_sha256=proof.first_pass_page_body_sha256,
        second_pass_page_body_sha256=proof.second_pass_page_body_sha256,
        facts=tuple(_fact_evidence(event) for event, _ in candidate.events),
        recorded_at=batch_recorded_at,
        scope=current_scope,
    )
    appenders = make_security_disclosure_event_append_use_cases(
        using=using,
        recorded_at=batch_recorded_at,
    )
    if appenders.database_alias != using:
        raise SecurityDisclosureAuditUnavailable(
            "Disclosure fact appenders do not share the Audit database alias."
        )
    results: list[SecurityDisclosureEventAppendResult] = []
    with audit_writer.atomic():
        existing_audit = audit_writer.find_exact_winner(
            observation,
            as_of=batch_recorded_at,
            scope=current_scope,
        )
        for event, body in candidate.events:
            results.append(appenders.events.execute(event, body))
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
            coverage = appenders.coverage.execute(proof)
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
            persisted_proof = appenders.coverage.get_by_episode(proof)
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
    return SzseDistributionWindowIngestion(
        candidate=candidate,
        events=tuple(results),
        coverage=coverage,
        audit=audit,
    )


def _fact_evidence(event: SecurityDisclosureEvent) -> SecurityDisclosureFactEvidence:
    """Project one captured source event into its exact Audit evidence identity."""

    return SecurityDisclosureFactEvidence(
        source_event_id=event.source_event_id,
        source_revision_id=event.source_revision_id,
        content_hash=event.content_hash,
        source_body_sha256=event.source_body_sha256,
    )
