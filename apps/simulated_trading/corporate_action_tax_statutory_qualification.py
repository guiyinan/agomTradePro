"""Bind verified retained clauses to an explicitly reviewed simulated tax model.

The configured applicability declaration is simulation policy, not evidence of
an actual taxpayer's status. Global Data Center legal/decision restrictions
remain intact. Owner authority, instrument/action scope and complete account
history must be independently checked by the assessment composition.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Literal

from apps.data_center.application.statutory_source_bundle import ConfiguredStatutorySourceBundleRead
from apps.data_center.domain.statutory_source_documents import (
    StatutorySourceDateEvidence,
    StatutorySourceDocumentBundle,
)
from apps.simulated_trading.corporate_action_tax_policy_composition import (
    ConfiguredSimulatedDividendTaxPolicy,
)
from apps.simulated_trading.domain.corporate_action_deferred_tax import (
    DeferredDividendTaxValidationError,
)
from apps.simulated_trading.domain.corporate_action_statutory_tax_terms import (
    ParsedStatutoryDividendTaxTerms,
)
from apps.simulated_trading.domain.corporate_action_tax_source_evidence import (
    TaxAssessmentSourceCaptureObservation,
    TaxAssessmentSourceDateEvidence,
    TaxAssessmentSourceDatePrecision,
    TaxAssessmentStatutorySourceBundle,
    TaxAssessmentStatutorySourceRevision,
)
from apps.simulated_trading.infrastructure.statutory_dividend_tax_parser import (
    parse_statutory_dividend_tax_terms,
)
from core.exceptions import BusinessLogicError, DataValidationError


def _blocked(message: str) -> BusinessLogicError:
    """Return a stable model qualification block without source fallback."""

    return BusinessLogicError(message, code="SIMULATED_TAX_STATUTORY_EVIDENCE_BLOCKED")


def _utc(value: datetime, *, name: str) -> datetime:
    """Require one exact aware representable current-read clock."""

    if type(value) is not datetime or value.tzinfo is None:
        raise _blocked(f"{name} must be timezone-aware")
    try:
        if value.utcoffset() is None:
            raise _blocked(f"{name} must be timezone-aware")
        return value.astimezone(UTC)
    except (OverflowError, TypeError, ValueError) as error:
        raise _blocked(f"{name} cannot be represented in UTC") from error


def _source_date(value: StatutorySourceDateEvidence) -> TaxAssessmentSourceDateEvidence:
    """Preserve explicit date/instant/unknown precision without inferred clocks."""

    value.__post_init__()
    return TaxAssessmentSourceDateEvidence(
        precision=TaxAssessmentSourceDatePrecision(value.precision.value),
        date_value=value.date_value,
        instant_value=value.instant_value,
    )


def tax_assessment_source_bundle(
    bundle: StatutorySourceDocumentBundle,
) -> TaxAssessmentStatutorySourceBundle:
    """Convert exact native source/capture facts without supplying authority."""

    if type(bundle) is not StatutorySourceDocumentBundle:
        raise _blocked("the exact retained statutory bundle is required")
    bundle.__post_init__()
    observations: list[TaxAssessmentSourceCaptureObservation] = []
    for capture in bundle.captures:
        capture.__post_init__()
        revision = capture.revision
        revision.__post_init__()
        observations.append(
            TaxAssessmentSourceCaptureObservation(
                capture_id=capture.capture_id,
                revision=TaxAssessmentStatutorySourceRevision(
                    document_id=revision.document_id,
                    source_version=revision.source_version,
                    canonical_url=revision.canonical_url,
                    issuer=revision.issuer,
                    title=revision.title,
                    legal_number=revision.legal_number,
                    publication_date=_source_date(revision.publication_date),
                    effective_date=_source_date(revision.effective_date),
                    body_sha256=revision.body_sha256,
                    body_size_bytes=revision.body_size_bytes,
                ),
                captured_at=capture.captured_at,
                content_type=capture.content_type,
                body_reference=capture.body_reference.reference,
                body_sha256=capture.body_reference.body_sha256,
                body_size_bytes=capture.body_reference.body_size_bytes,
            )
        )
    result = TaxAssessmentStatutorySourceBundle(
        bundle.bundle_id, bundle.version, tuple(observations)
    )
    if (
        result.source_bundle_sha256 != bundle.source_bundle_sha256
        or result.capture_manifest_sha256 != bundle.capture_manifest_sha256
    ):
        raise _blocked("statutory conversion changed original source or capture identity")
    return result


@dataclass(frozen=True, slots=True)
class SimulatedDividendTaxStatutoryEvidence:
    """Clause-consistent source evidence for the explicit simulation model only."""

    source_bundle: TaxAssessmentStatutorySourceBundle
    terms: ParsedStatutoryDividendTaxTerms
    applicability_ref: str
    source_observed_at: datetime
    checked_at: datetime
    valid_until: datetime

    @property
    def must_not_use_as_real_tax_proof(self) -> Literal[True]:
        """Keep real custody/taxpayer qualification outside the simulation model."""

        return True


def qualify_simulated_dividend_tax_statutory_evidence(
    *,
    configured: ConfiguredSimulatedDividendTaxPolicy,
    retained: ConfiguredStatutorySourceBundleRead,
    as_of: datetime,
) -> SimulatedDividendTaxStatutoryEvidence:
    """Recheck exact original bytes, explicit current model scope and parsed terms.

    This operation never refreshes sources, chooses latest captures, or changes
    Data Center's unqualified legal reliability. The supported grammar requires
    exactly one unambiguous rate/mechanics pair from the two selected originals.
    """

    if (
        type(configured) is not ConfiguredSimulatedDividendTaxPolicy
        or type(retained) is not ConfiguredStatutorySourceBundleRead
    ):
        raise _blocked("exact current candidate and retained source evidence are required")
    current = _utc(as_of, name="as_of")
    try:
        configured.__post_init__()
        retained.__post_init__()
        scope = configured.candidate
        if (
            current < _utc(configured.as_of, name="configured.as_of")
            or current < _utc(retained.checked_at, name="source.checked_at")
            or not scope.valid_from <= current < scope.valid_until
            or len(retained.bundle.captures) != 2
            or retained.bundle.bundle_id != scope.statutory_bundle_id
            or retained.bundle.version != scope.statutory_bundle_version
        ):
            raise _blocked("current model scope or exact retained selection is unavailable")
        deadline = min(
            scope.valid_until,
            *(
                capture.captured_at + timedelta(seconds=retained.catalog.max_capture_age_seconds)
                for capture in retained.bundle.captures
            ),
        )
        if current >= deadline:
            raise _blocked("original statutory capture window expired during model qualification")
        source_bundle = tax_assessment_source_bundle(retained.bundle)
        if source_bundle.source_revision_set_sha256 != scope.statutory_revision_set_sha256:
            raise _blocked("native statutory revision set differs from explicit simulation policy")
        matches: list[ParsedStatutoryDividendTaxTerms] = []
        maximum = max(rule.max_bytes for rule in retained.catalog.documents)
        for rate_index, mechanics_index in ((0, 1), (1, 0)):
            rate = retained.bundle.captures[rate_index].revision
            mechanics = retained.bundle.captures[mechanics_index].revision
            try:
                terms = parse_statutory_dividend_tax_terms(
                    rate_document_body=retained.bodies[rate_index],
                    rate_legal_number=rate.legal_number,
                    rate_source_revision_sha256=rate.source_revision_sha256,
                    mechanics_document_body=retained.bodies[mechanics_index],
                    mechanics_legal_number=mechanics.legal_number,
                    mechanics_source_revision_sha256=mechanics.source_revision_sha256,
                    max_body_bytes=maximum,
                )
            except DataValidationError:
                continue
            matches.append(terms)
        if len(matches) != 1:
            raise _blocked("the complete supported statutory clause pair is missing or ambiguous")
        terms = matches[0]
        terms.validate_policy(scope.tax_policy)
        return SimulatedDividendTaxStatutoryEvidence(
            source_bundle=source_bundle,
            terms=terms,
            applicability_ref=scope.applicability_ref,
            source_observed_at=retained.source_observed_at,
            checked_at=current,
            valid_until=deadline,
        )
    except (
        DataValidationError,
        DeferredDividendTaxValidationError,
        OverflowError,
        ValueError,
    ) as error:
        raise _blocked(
            "retained statutory facts or configured simulation terms failed validation"
        ) from error


__all__ = [
    "SimulatedDividendTaxStatutoryEvidence",
    "qualify_simulated_dividend_tax_statutory_evidence",
    "tax_assessment_source_bundle",
]
