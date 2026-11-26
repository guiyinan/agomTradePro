"""Evidence verification for canonical financial fact repository operations."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime

from django.db import DEFAULT_DB_ALIAS
from django.utils import timezone

from apps.data_center.application.financial_numeric_qualification import (
    ContextualFinancialNumericEvidenceVerifier,
    FinancialNumericVerificationContext,
    FinancialNumericVerificationPurpose,
)
from apps.data_center.application.financial_numeric_verification import (
    FinancialNumericEvidenceVerifier,
)
from apps.data_center.application.financial_v3_e1_verification import (
    FinancialV3FactEvidenceVerifier,
    FinancialV3FactVerificationRequest,
)
from apps.data_center.domain.entities import FinancialFact
from apps.data_center.infrastructure.models import FinancialFactModel

from .financial_fact_hydration import financial_fact_from_model
from .financial_fact_write_guard import (
    FinancialFactProvenanceConflictError,
    FinancialSourceTimeEvidenceVerifier,
)


class FinancialFactVerification:
    """Bind verification to a database alias, purpose and knowledge time."""

    def __init__(
        self,
        source_time_evidence_verifier: FinancialSourceTimeEvidenceVerifier | None = None,
        *,
        numeric_evidence_verifier: FinancialNumericEvidenceVerifier | None = None,
        qualified_numeric_evidence_verifier: (
            ContextualFinancialNumericEvidenceVerifier | None
        ) = None,
        database_alias: str = DEFAULT_DB_ALIAS,
        numeric_verification_clock: Callable[[], datetime] = timezone.now,
        v3_evidence_verifier: FinancialV3FactEvidenceVerifier | None = None,
    ) -> None:
        """Bind source-time evidence and optional context-fenced numeric verification.

        The current repository uses Django's default manager for financial-fact
        rows. A qualified verifier is therefore accepted only with that exact
        alias; its catalog adapter must use the same alias. Current write/read
        checks are performed inside an outer transaction retained through the
        operation, while an explicit PIT cutoff is passed unchanged.
        """

        if type(database_alias) is not str or database_alias != DEFAULT_DB_ALIAS:
            raise ValueError("financial facts currently require the configured default alias")
        if not callable(numeric_verification_clock):
            raise TypeError("numeric verification clock must be callable")
        self._source_time_evidence_verifier = source_time_evidence_verifier
        self._numeric_evidence_verifier = numeric_evidence_verifier
        self._qualified_numeric_evidence_verifier = qualified_numeric_evidence_verifier
        self._database_alias = database_alias
        self._numeric_verification_clock = numeric_verification_clock
        self._v3_evidence_verifier = v3_evidence_verifier

    @staticmethod
    def _from_model(m: FinancialFactModel) -> FinancialFact:
        """Restore one supported numeric schema without losing native decimal digits."""

        return financial_fact_from_model(m)

    def _read_model(
        self,
        row: FinancialFactModel,
        *,
        numeric_evidence_verifier: FinancialNumericEvidenceVerifier | None = None,
        verification_request: FinancialV3FactVerificationRequest | None = None,
    ) -> FinancialFact:
        """Require fresh independent qualification before exposing native values."""

        fact = self._from_model(row)
        decision = fact.decision_evidence
        if decision is not None and decision.source_time_witness_v3 is not None:
            if (
                self._v3_evidence_verifier is None
                or type(verification_request) is not FinancialV3FactVerificationRequest
                or verification_request.purpose
                not in {
                    FinancialNumericVerificationPurpose.CURRENT_READ,
                    FinancialNumericVerificationPurpose.POINT_IN_TIME_READ,
                }
                or not self._v3_evidence_verifier.verify(fact, verification_request)
            ):
                raise FinancialFactProvenanceConflictError(
                    "v3 financial reads require exact-body and qualified temporal verification"
                )
            return fact
        verifier = numeric_evidence_verifier or self._numeric_evidence_verifier
        if fact.numeric_schema == "native-decimal-v2" and (verifier is None or not verifier(fact)):
            raise FinancialFactProvenanceConflictError(
                "native financial read requires independent catalog and body verification"
            )
        return fact

    def _numeric_verifier_for(
        self,
        purpose: FinancialNumericVerificationPurpose,
        *,
        known_at: datetime | None = None,
    ) -> FinancialNumericEvidenceVerifier | None:
        """Bind one typed context to the existing fact-verifier callback boundary."""

        contextual = self._qualified_numeric_evidence_verifier
        if contextual is None:
            return self._numeric_evidence_verifier
        selected_known_at = known_at if known_at is not None else self._numeric_verification_clock()
        context = FinancialNumericVerificationContext(
            known_at=selected_known_at,
            purpose=purpose,
        )
        return lambda fact: contextual.verify(fact, context)
