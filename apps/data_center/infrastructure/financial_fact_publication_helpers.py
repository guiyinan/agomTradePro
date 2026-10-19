"""Financial-fact publication selection and persisted-evidence validation."""

from __future__ import annotations

from collections.abc import Callable, Sequence

from django.db.models import OuterRef, Subquery

from apps.data_center.domain.control_plane import PublicationFactReference
from apps.data_center.domain.entities import FinancialFact
from apps.data_center.domain.financial_source_evidence import FinancialFactDecisionEvidence
from apps.data_center.infrastructure.financial_decision_evidence_codec import (
    decode_financial_decision_evidence,
)
from apps.data_center.infrastructure.financial_fact_write_guard import (
    FinancialFactProvenanceConflictError,
    FinancialSourceTimeEvidenceVerifier,
)
from apps.data_center.infrastructure.models import FinancialFactModel
from apps.data_center.infrastructure.publication_fact_evidence import (
    publication_fact_reference_for_dataset,
)
from apps.data_center.infrastructure.published_fact_versions import latest_fact_revisions

_NATURAL_KEY = ("asset_code", "period_end", "period_type", "metric_code", "source")
_PublicationReferenceFactory = Callable[
    [FinancialFactModel, bool, FinancialSourceTimeEvidenceVerifier | None],
    PublicationFactReference,
]
_DecisionEvidenceChecker = Callable[
    [FinancialFactModel, FinancialSourceTimeEvidenceVerifier | None],
    FinancialFactDecisionEvidence,
]


def _list_financial_publication_candidates(
    facts: Sequence[FinancialFact],
    *,
    source_time_evidence_verifier: FinancialSourceTimeEvidenceVerifier | None,
    require_verified_source_evidence: bool,
    reference_factory: _PublicationReferenceFactory,
) -> list[PublicationFactReference]:
    """Resolve input facts to latest persisted rows with source availability."""

    references: list[PublicationFactReference] = []
    seen_fact_pks: set[str] = set()
    for fact in facts:
        row = (
            FinancialFactModel._default_manager.filter(
                asset_code=fact.asset_code,
                period_end=fact.period_end,
                period_type=fact.period_type.value,
                metric_code=fact.metric_code,
                source=fact.source,
            )
            .order_by("-revision_number", "-id")
            .first()
        )
        if row is None or str(row.pk) in seen_fact_pks:
            continue
        if row.available_at is None:
            # Never substitute period_end or fetched_at for source availability.
            continue
        fact_pk = str(row.pk)
        seen_fact_pks.add(fact_pk)
        references.append(
            reference_factory(
                row,
                require_verified_source_evidence,
                source_time_evidence_verifier,
            )
        )
    return references


def _list_current_financial_publication_candidates(
    asset_codes: tuple[str, ...],
    *,
    source_time_evidence_verifier: FinancialSourceTimeEvidenceVerifier | None,
    require_verified_source_evidence: bool,
    natural_key: tuple[str, ...],
    reference_factory: _PublicationReferenceFactory,
) -> list[PublicationFactReference]:
    """Select current metrics from each asset's latest evidence-safe period."""

    if not asset_codes:
        return []
    latest_available_period = (
        latest_fact_revisions(FinancialFactModel, natural_key)
        .filter(
            asset_code=OuterRef("asset_code"),
            available_at__isnull=False,
        )
        .order_by("-period_end")
        .values("period_end")[:1]
    )
    latest_metric_row = (
        latest_fact_revisions(FinancialFactModel, natural_key)
        .filter(
            asset_code=OuterRef("asset_code"),
            period_end=OuterRef("period_end"),
            period_type=OuterRef("period_type"),
            metric_code=OuterRef("metric_code"),
            available_at__isnull=False,
        )
        .order_by("-available_at", "-revision_number", "-fetched_at", "-id")
        .values("id")[:1]
    )
    rows = FinancialFactModel._default_manager.filter(
        asset_code__in=asset_codes,
        available_at__isnull=False,
        period_end=Subquery(latest_available_period),
        pk=Subquery(latest_metric_row),
    ).order_by("asset_code", "period_type", "metric_code")
    return [
        reference_factory(row, require_verified_source_evidence, source_time_evidence_verifier)
        for row in rows
    ]


def _financial_publication_reference_impl(
    row: FinancialFactModel,
    require_verified_source_evidence: bool,
    source_time_evidence_verifier: FinancialSourceTimeEvidenceVerifier | None,
    *,
    decision_evidence_checker: _DecisionEvidenceChecker,
) -> PublicationFactReference:
    """Build a publication reference only after exact-row evidence checks."""

    if row.available_at is None:
        raise ValueError("financial publication candidate requires available_at")
    decision_evidence_checker(row, source_time_evidence_verifier)
    return publication_fact_reference_for_dataset(
        row,
        dataset_key="equity.financial.fact",
        require_verified_source_evidence=require_verified_source_evidence,
    )


def _require_publication_decision_evidence_impl(
    row: FinancialFactModel,
    source_time_evidence_verifier: FinancialSourceTimeEvidenceVerifier | None,
) -> FinancialFactDecisionEvidence:
    """Require persisted decision and source-time evidence to bind the exact row."""

    decision = decode_financial_decision_evidence(row.decision_evidence)
    if decision is None:
        raise FinancialFactProvenanceConflictError(
            "financial decision evidence is required for publication candidates"
        )
    artifact = decision.artifact_reference
    if (
        decision.native_asset_code != row.asset_code
        or decision.native_period_end != row.period_end
        or decision.native_row_id != row.source_record_id
        or artifact.evidence.body_sha256 != row.raw_payload_hash
    ):
        raise FinancialFactProvenanceConflictError(
            "financial publication decision evidence does not match the persisted row"
        )
    source_time = decision.source_time_witness
    if source_time is None:
        raise FinancialFactProvenanceConflictError(
            "financial source-time evidence is required for publication candidates"
        )
    if (
        source_time.announced_at != row.announced_at
        or source_time.available_at != row.available_at
        or source_time.native_asset_code != row.asset_code
        or source_time.native_period_end != row.period_end
        or source_time.financial_native_row_id != row.source_record_id
    ):
        raise FinancialFactProvenanceConflictError(
            "financial publication source-time evidence does not match the persisted row"
        )
    extra = row.extra if isinstance(row.extra, dict) else {}
    source_time_artifact = source_time.artifact_reference
    expected_transport = {
        "financial_response_capture_id": str(artifact.capture_id),
        "raw_payload_scope": artifact.evidence.body_scope.value,
        "response_scope_basis": artifact.evidence.response_scope_basis.value,
        "financial_source_time_capture_id": str(source_time_artifact.capture_id),
        "financial_source_time_body_sha256": source_time_artifact.body_sha256,
        "financial_source_time_row_sha256": source_time.row_projection_sha256,
        "financial_source_time_match_contract_id": source_time.governed_match_contract_id,
        "financial_source_time_match_contract_version": (
            source_time.governed_match_contract_version
        ),
        "financial_source_time_match_contract_sha256": source_time.governed_match_contract_sha256,
        "financial_source_time_matched_row_count": source_time.matched_row_count,
    }
    if any(extra.get(key) != value for key, value in expected_transport.items()):
        raise FinancialFactProvenanceConflictError(
            "financial publication transport evidence does not match the persisted row"
        )
    if source_time_evidence_verifier is None or not source_time_evidence_verifier(decision):
        raise FinancialFactProvenanceConflictError(
            "financial source-time evidence must be independently reverified for publication"
        )
    return decision
