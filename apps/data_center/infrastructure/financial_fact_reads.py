"""Current and point-in-time financial statement queries."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date, datetime

from django.db.models import OuterRef, Q, Subquery

from apps.data_center.application.financial_numeric_qualification import (
    FinancialNumericVerificationPurpose,
)
from apps.data_center.application.financial_numeric_verification import (
    FinancialNumericEvidenceVerifier,
)
from apps.data_center.application.financial_v3_e1_verification import (
    FinancialV3FactVerificationRequest,
)
from apps.data_center.domain.entities import FinancialFact
from apps.data_center.domain.enums import FinancialPeriodType
from apps.data_center.infrastructure._repository_helpers import _resolve_asset_code_candidates
from apps.data_center.infrastructure.models import FinancialFactModel

from .financial_fact_publication_helpers import (
    _NATURAL_KEY,
)
from .financial_fact_verification import FinancialFactVerification
from .financial_fact_write_guard import (
    FinancialFactProvenanceConflictError,
)
from .financial_v3_current_uow import (
    financial_v3_current_operation_uow,
)


class FinancialFactReads(FinancialFactVerification):
    """Read financial facts using the caller's evidence and time scope."""

    def get_facts(
        self,
        asset_code: str,
        period_type: FinancialPeriodType | None = None,
        limit: int = 20,
        end: date | None = None,
        fact_pks: Sequence[str] | None = None,
        knowledge_cutoff: datetime | None = None,
        *,
        verification_request: FinancialV3FactVerificationRequest | None = None,
    ) -> list[FinancialFact]:
        """Select latest revisions and independently verify explicit v3 reads."""
        if verification_request is not None and (
            type(verification_request) is not FinancialV3FactVerificationRequest
            or (
                knowledge_cutoff is None
                and verification_request.purpose
                is not FinancialNumericVerificationPurpose.CURRENT_READ
            )
            or (
                knowledge_cutoff is not None
                and (
                    verification_request.purpose
                    is not FinancialNumericVerificationPurpose.POINT_IN_TIME_READ
                    or verification_request.known_at != knowledge_cutoff
                )
            )
        ):
            raise FinancialFactProvenanceConflictError(
                "financial fact read request must match its current or exact PIT scope"
            )
        if knowledge_cutoff is None and (
            self._qualified_numeric_evidence_verifier is not None
            or verification_request is not None
        ):
            with financial_v3_current_operation_uow(using=self._database_alias):
                verifier = self._numeric_verifier_for(
                    FinancialNumericVerificationPurpose.CURRENT_READ
                )
                return self._get_facts(
                    asset_code,
                    period_type=period_type,
                    limit=limit,
                    end=end,
                    fact_pks=fact_pks,
                    knowledge_cutoff=None,
                    numeric_evidence_verifier=verifier,
                    verification_request=verification_request,
                )
        if self._qualified_numeric_evidence_verifier is None:
            return self._get_facts(
                asset_code,
                period_type=period_type,
                limit=limit,
                end=end,
                fact_pks=fact_pks,
                knowledge_cutoff=knowledge_cutoff,
                numeric_evidence_verifier=self._numeric_evidence_verifier,
                verification_request=verification_request,
            )
        if knowledge_cutoff is not None:
            verifier = self._numeric_verifier_for(
                FinancialNumericVerificationPurpose.POINT_IN_TIME_READ,
                known_at=knowledge_cutoff,
            )
            return self._get_facts(
                asset_code,
                period_type=period_type,
                limit=limit,
                end=end,
                fact_pks=fact_pks,
                knowledge_cutoff=knowledge_cutoff,
                numeric_evidence_verifier=verifier,
                verification_request=verification_request,
            )
        raise AssertionError("current reads with a qualified verifier must use the outer UOW")

    def _get_facts(
        self,
        asset_code: str,
        *,
        period_type: FinancialPeriodType | None,
        limit: int,
        end: date | None,
        fact_pks: Sequence[str] | None,
        knowledge_cutoff: datetime | None,
        numeric_evidence_verifier: FinancialNumericEvidenceVerifier | None,
        verification_request: FinancialV3FactVerificationRequest | None,
    ) -> list[FinancialFact]:
        """Select and verify fact rows inside the caller-selected knowledge boundary."""

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
                legacy_or_v2 = Q(
                    announced_at__isnull=False,
                    announced_at__lte=knowledge_cutoff,
                    available_at__isnull=False,
                    available_at__lte=knowledge_cutoff,
                ) & (
                    Q(numeric_schema="legacy-decimal-v1")
                    | Q(numeric_schema="native-decimal-v2", fetched_at__lte=knowledge_cutoff)
                )
                if (
                    type(verification_request) is FinancialV3FactVerificationRequest
                    and verification_request.purpose
                    is FinancialNumericVerificationPurpose.POINT_IN_TIME_READ
                ):
                    v3 = Q(
                        numeric_schema="native-decimal-v2",
                        announced_at__isnull=True,
                        available_at__isnull=False,
                        available_at__lte=knowledge_cutoff,
                        fetched_at__lte=knowledge_cutoff,
                        decision_evidence__schema="financial-fact-decision-evidence.v3",
                        decision_evidence__source_time_witness_v3__availability__known_at__lte=(
                            knowledge_cutoff.isoformat()
                        ),
                    )
                    qs = qs.filter(legacy_or_v2 | v3)
                else:
                    qs = qs.filter(legacy_or_v2)
            if fact_pks is None:
                latest = (
                    qs.filter(**{name: OuterRef(name) for name in _NATURAL_KEY})
                    .order_by("-revision_number", "-pk")
                    .values("pk")[:1]
                )
                qs = qs.filter(pk=Subquery(latest))
            rows = list(qs.order_by("-period_end")[:limit])
            if rows:
                return [
                    self._read_model(
                        m,
                        numeric_evidence_verifier=numeric_evidence_verifier,
                        verification_request=verification_request,
                    )
                    for m in rows
                ]
        return []

    def get_latest(
        self,
        asset_code: str,
        period_type: FinancialPeriodType | None = None,
        *,
        verification_request: FinancialV3FactVerificationRequest | None = None,
    ) -> FinancialFact | None:
        """Return the latest source period with current v3 verification when requested."""
        if verification_request is not None and (
            type(verification_request) is not FinancialV3FactVerificationRequest
            or verification_request.purpose is not FinancialNumericVerificationPurpose.CURRENT_READ
        ):
            raise FinancialFactProvenanceConflictError(
                "latest financial reads require CURRENT_READ verification purpose"
            )
        if (
            self._qualified_numeric_evidence_verifier is not None
            or verification_request is not None
        ):
            with financial_v3_current_operation_uow(using=self._database_alias):
                verifier = self._numeric_verifier_for(
                    FinancialNumericVerificationPurpose.CURRENT_READ
                )
                return self._get_latest(
                    asset_code,
                    period_type=period_type,
                    numeric_evidence_verifier=verifier,
                    verification_request=verification_request,
                )
        return self._get_latest(
            asset_code,
            period_type=period_type,
            numeric_evidence_verifier=self._numeric_evidence_verifier,
            verification_request=None,
        )

    def _get_latest(
        self,
        asset_code: str,
        *,
        period_type: FinancialPeriodType | None,
        numeric_evidence_verifier: FinancialNumericEvidenceVerifier | None,
        verification_request: FinancialV3FactVerificationRequest | None,
    ) -> FinancialFact | None:
        """Select one latest row and verify it before returning it."""

        for candidate in _resolve_asset_code_candidates(asset_code):
            qs = FinancialFactModel.objects.filter(asset_code=candidate)
            if period_type:
                qs = qs.filter(period_type=period_type.value)
            m = qs.order_by("-period_end", "-revision_number", "-pk").first()
            if m is not None:
                return self._read_model(
                    m,
                    numeric_evidence_verifier=numeric_evidence_verifier,
                    verification_request=verification_request,
                )
        return None
