"""Canonical financial statement fact persistence."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date, datetime
from uuid import UUID

from django.db.models import OuterRef, Subquery

from apps.data_center.domain.control_plane import PublicationFactReference
from apps.data_center.domain.entities import FinancialFact
from apps.data_center.domain.enums import FinancialPeriodType
from apps.data_center.domain.financial_source_evidence import FinancialFactDecisionEvidence
from apps.data_center.infrastructure._repository_helpers import _resolve_asset_code_candidates
from apps.data_center.infrastructure.financial_availability_repository import (
    FinancialAvailabilityRepositoryMixin,
)
from apps.data_center.infrastructure.models import FinancialFactModel

from .financial_decision_evidence_codec import decode_financial_decision_evidence
from .financial_fact_publication_helpers import (
    _NATURAL_KEY,
    _financial_publication_reference_impl,
    _list_current_financial_publication_candidates,
    _list_financial_publication_candidates,
    _require_publication_decision_evidence_impl,
)
from .financial_fact_write_guard import (
    FinancialFactProvenanceConflictError,
    FinancialSourceTimeEvidenceVerifier,
    bulk_upsert_financial_facts,
    source_evidence_from_model,
)
from .financial_source_policy import requires_verified_financial_source_evidence


class FinancialFactRepository(FinancialAvailabilityRepositoryMixin):
    """ORM-backed repository for financial statement facts."""

    def __init__(
        self,
        source_time_evidence_verifier: FinancialSourceTimeEvidenceVerifier | None = None,
    ) -> None:
        """Bind the verifier that recomputes unique source-time row evidence."""

        self._source_time_evidence_verifier = source_time_evidence_verifier

    @staticmethod
    def _from_model(m: FinancialFactModel) -> FinancialFact:
        return FinancialFact(
            asset_code=m.asset_code,
            period_end=m.period_end,
            period_type=FinancialPeriodType(m.period_type),
            metric_code=m.metric_code,
            value=float(m.value),
            unit=m.unit,
            source=m.source,
            report_date=m.report_date,
            available_at=m.available_at,
            fetched_at=m.fetched_at,
            extra=m.extra or {},
            source_evidence=source_evidence_from_model(m),
            decision_evidence=decode_financial_decision_evidence(m.decision_evidence),
        )

    def get_facts(
        self,
        asset_code: str,
        period_type: FinancialPeriodType | None = None,
        limit: int = 20,
        end: date | None = None,
        fact_pks: Sequence[str] | None = None,
        knowledge_cutoff: datetime | None = None,
    ) -> list[FinancialFact]:
        """Select latest revisions within the requested historical knowledge scope."""
        if knowledge_cutoff is not None and (
            knowledge_cutoff.tzinfo is None or knowledge_cutoff.utcoffset() is None
        ):
            raise ValueError("financial knowledge cutoff must be timezone-aware")
        for candidate in _resolve_asset_code_candidates(asset_code):
            qs = FinancialFactModel.objects.filter(asset_code=candidate)
            if fact_pks is not None:
                qs = qs.filter(pk__in=list(fact_pks))
            if period_type:
                qs = qs.filter(period_type=period_type.value)
            if end is not None:
                qs = qs.filter(period_end__lte=end)
            if knowledge_cutoff is not None:
                qs = qs.filter(
                    announced_at__isnull=False,
                    announced_at__lte=knowledge_cutoff,
                    available_at__isnull=False,
                    available_at__lte=knowledge_cutoff,
                )
            if fact_pks is None:
                latest = (
                    qs.filter(**{name: OuterRef(name) for name in _NATURAL_KEY})
                    .order_by("-revision_number", "-pk")
                    .values("pk")[:1]
                )
                qs = qs.filter(pk=Subquery(latest))
            rows = list(qs.order_by("-period_end")[:limit])
            if rows:
                return [self._from_model(m) for m in rows]
        return []

    def get_latest(
        self, asset_code: str, period_type: FinancialPeriodType | None = None
    ) -> FinancialFact | None:
        """Return the latest source period and revision for an asset."""
        for candidate in _resolve_asset_code_candidates(asset_code):
            qs = FinancialFactModel.objects.filter(asset_code=candidate)
            if period_type:
                qs = qs.filter(period_type=period_type.value)
            m = qs.order_by("-period_end", "-revision_number", "-pk").first()
            if m is not None:
                return self._from_model(m)
        return None

    def bulk_upsert(
        self,
        facts: list[FinancialFact],
        *,
        ingested_run_id: UUID | None = None,
    ) -> int:
        """Persist facts without allowing stale source evidence to follow new values."""

        return bulk_upsert_financial_facts(
            facts,
            source_time_evidence_verifier=self._source_time_evidence_verifier,
            ingested_run_id=ingested_run_id,
        )

    def list_publication_candidates(
        self, facts: Sequence[FinancialFact]
    ) -> list[PublicationFactReference]:
        """Resolve financial rows and require source-provided ``available_at``."""
        return _list_financial_publication_candidates(
            facts,
            source_time_evidence_verifier=self._source_time_evidence_verifier,
            require_verified_source_evidence=requires_verified_financial_source_evidence(),
            reference_factory=_financial_publication_reference,
        )

    def list_current_publication_candidates(
        self,
        asset_codes: tuple[str, ...],
    ) -> list[PublicationFactReference]:
        """Select every metric from each asset's latest evidence-safe period."""
        if not asset_codes:
            return []
        return _list_current_financial_publication_candidates(
            asset_codes,
            source_time_evidence_verifier=self._source_time_evidence_verifier,
            require_verified_source_evidence=requires_verified_financial_source_evidence(),
            natural_key=_NATURAL_KEY,
            reference_factory=_financial_publication_reference,
        )


def _financial_publication_reference(
    row: FinancialFactModel,
    require_verified_source_evidence: bool = False,
    source_time_evidence_verifier: FinancialSourceTimeEvidenceVerifier | None = None,
) -> PublicationFactReference:
    """Convert one evidence-safe financial row to a publication reference."""
    return _financial_publication_reference_impl(
        row,
        require_verified_source_evidence,
        source_time_evidence_verifier,
        decision_evidence_checker=_require_publication_decision_evidence,
    )


def _require_publication_decision_evidence(
    row: FinancialFactModel,
    source_time_evidence_verifier: FinancialSourceTimeEvidenceVerifier | None,
) -> FinancialFactDecisionEvidence:
    """Require the persisted artifact binding to match the exact candidate row."""
    return _require_publication_decision_evidence_impl(row, source_time_evidence_verifier)


__all__ = ["FinancialFactProvenanceConflictError", "FinancialFactRepository"]
