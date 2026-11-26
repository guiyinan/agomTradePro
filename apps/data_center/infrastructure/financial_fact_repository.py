"""Canonical financial statement fact persistence."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from uuid import UUID

from apps.data_center.application.financial_numeric_qualification import (
    FinancialNumericVerificationPurpose,
)
from apps.data_center.application.financial_numeric_verification import (
    FinancialNumericEvidenceVerifier,
)
from apps.data_center.application.financial_v3_e1_verification import (
    FinancialV3FactVerificationRequest,
)
from apps.data_center.domain.control_plane import PublicationFactReference
from apps.data_center.domain.entities import FinancialFact
from apps.data_center.infrastructure.financial_availability_repository import (
    FinancialAvailabilityRepositoryMixin,
)
from apps.data_center.infrastructure.models import FinancialFactModel

from .financial_fact_publication_evidence import (
    _financial_publication_reference as _financial_publication_reference,
)
from .financial_fact_publication_helpers import (
    _NATURAL_KEY,
    _list_current_financial_publication_candidates,
    _list_financial_publication_candidates,
)
from .financial_fact_reads import FinancialFactReads
from .financial_fact_write_guard import (
    FinancialFactProvenanceConflictError,
    FinancialSourceTimeEvidenceVerifier,
    bulk_upsert_financial_facts,
)
from .financial_source_policy import requires_verified_financial_source_evidence
from .financial_v3_current_uow import (
    financial_v3_current_operation_uow,
    require_financial_v3_caller_owned_uow,
)


class FinancialFactRepository(FinancialFactReads, FinancialAvailabilityRepositoryMixin):
    """ORM-backed repository for financial statement facts."""

    def _publication_reference(
        self,
        row: FinancialFactModel,
        require_verified_source_evidence: bool,
        source_time_evidence_verifier: FinancialSourceTimeEvidenceVerifier | None,
        *,
        verification_request: FinancialV3FactVerificationRequest | None = None,
    ) -> PublicationFactReference:
        """Pass this repository's numeric verifier through every publication query."""

        return _financial_publication_reference(
            row,
            require_verified_source_evidence,
            source_time_evidence_verifier,
            self._numeric_evidence_verifier,
            self._v3_evidence_verifier,
            verification_request,
        )

    def verify_recovery_fact(
        self, fact: FinancialFact, request: FinancialV3FactVerificationRequest
    ) -> bool:
        """Run the configured v3 verifier for a no-write recovery forecast."""

        return self._v3_evidence_verifier is not None and self._v3_evidence_verifier.verify(
            fact, request
        )

    def bulk_upsert(
        self,
        facts: list[FinancialFact],
        *,
        ingested_run_id: UUID | None = None,
        verification_request: FinancialV3FactVerificationRequest | None = None,
    ) -> int:
        """Persist facts without allowing stale source evidence to follow new values."""

        if verification_request is not None and (
            type(verification_request) is not FinancialV3FactVerificationRequest
            or verification_request.purpose is not FinancialNumericVerificationPurpose.CURRENT_WRITE
        ):
            raise FinancialFactProvenanceConflictError(
                "financial writes require CURRENT_WRITE verification purpose"
            )
        has_v3_fact = any(
            type(fact) is FinancialFact
            and fact.decision_evidence is not None
            and fact.decision_evidence.source_time_witness_v3 is not None
            for fact in facts
        )
        if has_v3_fact and (
            self._v3_evidence_verifier is None
            or type(verification_request) is not FinancialV3FactVerificationRequest
        ):
            raise FinancialFactProvenanceConflictError(
                "v3 financial writes require a configured verifier and CURRENT_WRITE request"
            )
        if has_v3_fact or self._qualified_numeric_evidence_verifier is not None:
            with financial_v3_current_operation_uow(using=self._database_alias):
                verifier = self._numeric_verifier_for(
                    FinancialNumericVerificationPurpose.CURRENT_WRITE
                )
                return bulk_upsert_financial_facts(
                    facts,
                    source_time_evidence_verifier=self._source_time_evidence_verifier,
                    numeric_evidence_verifier=verifier,
                    v3_evidence_verifier=self._v3_evidence_verifier,
                    v3_verification_request=verification_request,
                    ingested_run_id=ingested_run_id,
                )
        return bulk_upsert_financial_facts(
            facts,
            source_time_evidence_verifier=self._source_time_evidence_verifier,
            numeric_evidence_verifier=self._numeric_evidence_verifier,
            v3_evidence_verifier=self._v3_evidence_verifier,
            v3_verification_request=verification_request,
            ingested_run_id=ingested_run_id,
        )

    def list_publication_candidates(
        self,
        facts: Sequence[FinancialFact],
        *,
        verification_request: FinancialV3FactVerificationRequest | None = None,
    ) -> list[PublicationFactReference]:
        """Resolve financial rows and require source-provided ``available_at``."""
        self._require_publication_request(verification_request)
        if verification_request is not None:
            require_financial_v3_caller_owned_uow(using=self._database_alias)
        verifier = self._numeric_verifier_for(
            FinancialNumericVerificationPurpose.CURRENT_PUBLICATION
        )
        return _list_financial_publication_candidates(
            facts,
            source_time_evidence_verifier=self._source_time_evidence_verifier,
            require_verified_source_evidence=requires_verified_financial_source_evidence(),
            reference_factory=self._publication_reference_factory(verifier, verification_request),
        )

    def list_current_publication_candidates(
        self,
        asset_codes: tuple[str, ...],
        *,
        verification_request: FinancialV3FactVerificationRequest | None = None,
    ) -> list[PublicationFactReference]:
        """Select every metric from each asset's latest evidence-safe period."""
        self._require_publication_request(verification_request)
        if verification_request is not None:
            require_financial_v3_caller_owned_uow(using=self._database_alias)
        if not asset_codes:
            return []
        verifier = self._numeric_verifier_for(
            FinancialNumericVerificationPurpose.CURRENT_PUBLICATION
        )
        return _list_current_financial_publication_candidates(
            asset_codes,
            source_time_evidence_verifier=self._source_time_evidence_verifier,
            require_verified_source_evidence=requires_verified_financial_source_evidence(),
            natural_key=_NATURAL_KEY,
            reference_factory=self._publication_reference_factory(verifier, verification_request),
        )

    @staticmethod
    def _require_publication_request(
        verification_request: FinancialV3FactVerificationRequest | None,
    ) -> None:
        """Require any explicit publication request to select CURRENT_PUBLICATION."""

        if verification_request is not None and (
            type(verification_request) is not FinancialV3FactVerificationRequest
            or verification_request.purpose
            is not FinancialNumericVerificationPurpose.CURRENT_PUBLICATION
        ):
            raise FinancialFactProvenanceConflictError(
                "financial publication requires CURRENT_PUBLICATION verification purpose"
            )

    def _publication_reference_factory(
        self,
        numeric_evidence_verifier: FinancialNumericEvidenceVerifier | None,
        verification_request: FinancialV3FactVerificationRequest | None,
    ) -> Callable[
        [FinancialFactModel, bool, FinancialSourceTimeEvidenceVerifier | None],
        PublicationFactReference,
    ]:
        """Bind one publication-time catalog context to every selected row."""

        def build(
            row: FinancialFactModel,
            require_verified_source_evidence: bool,
            source_time_evidence_verifier: FinancialSourceTimeEvidenceVerifier | None,
        ) -> PublicationFactReference:
            return _financial_publication_reference(
                row,
                require_verified_source_evidence,
                source_time_evidence_verifier,
                numeric_evidence_verifier,
                self._v3_evidence_verifier,
                verification_request,
            )

        return build


__all__ = ["FinancialFactProvenanceConflictError", "FinancialFactRepository"]
