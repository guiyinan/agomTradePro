"""Canonical financial statement fact persistence."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from datetime import date, datetime
from uuid import UUID

from django.db import DEFAULT_DB_ALIAS
from django.db.models import OuterRef, Q, Subquery
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
from apps.data_center.domain.control_plane import PublicationFactReference
from apps.data_center.domain.entities import FinancialFact
from apps.data_center.domain.enums import FinancialPeriodType
from apps.data_center.domain.financial_source_evidence import FinancialFactDecisionEvidence
from apps.data_center.infrastructure._repository_helpers import _resolve_asset_code_candidates
from apps.data_center.infrastructure.financial_availability_repository import (
    FinancialAvailabilityRepositoryMixin,
)
from apps.data_center.infrastructure.models import FinancialFactModel

from .financial_fact_hydration import financial_fact_from_model
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
)
from .financial_source_policy import requires_verified_financial_source_evidence
from .financial_v3_current_uow import (
    financial_v3_current_operation_uow,
    require_financial_v3_caller_owned_uow,
)


class FinancialFactRepository(FinancialAvailabilityRepositoryMixin):
    """ORM-backed repository for financial statement facts."""

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


def _financial_publication_reference(
    row: FinancialFactModel,
    require_verified_source_evidence: bool = False,
    source_time_evidence_verifier: FinancialSourceTimeEvidenceVerifier | None = None,
    numeric_evidence_verifier: FinancialNumericEvidenceVerifier | None = None,
    v3_evidence_verifier: FinancialV3FactEvidenceVerifier | None = None,
    v3_verification_request: FinancialV3FactVerificationRequest | None = None,
) -> PublicationFactReference:
    """Convert one evidence-safe financial row to a publication reference."""
    decision = None
    if isinstance(row.decision_evidence, dict):
        decision = financial_fact_from_model(row).decision_evidence
    if decision is not None and decision.source_time_witness_v3 is not None:
        fact = financial_fact_from_model(row)
        if (
            v3_evidence_verifier is None
            or type(v3_verification_request) is not FinancialV3FactVerificationRequest
            or v3_verification_request.purpose
            is not FinancialNumericVerificationPurpose.CURRENT_PUBLICATION
            or not v3_evidence_verifier.verify(fact, v3_verification_request)
        ):
            raise FinancialFactProvenanceConflictError(
                "v3 financial publication requires current exact-body and temporal verification"
            )
        return _financial_publication_reference_impl(
            row,
            False,
            source_time_evidence_verifier,
            decision_evidence_checker=_require_v3_publication_decision_evidence,
        )
    if row.numeric_schema != "legacy-decimal-v1":
        fact = financial_fact_from_model(row)
        if numeric_evidence_verifier is None or not numeric_evidence_verifier(fact):
            raise FinancialFactProvenanceConflictError(
                "native financial publication requires independent catalog and body verification"
            )
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


def _require_v3_publication_decision_evidence(
    row: FinancialFactModel,
    source_time_evidence_verifier: FinancialSourceTimeEvidenceVerifier | None,
) -> FinancialFactDecisionEvidence:
    """Require a date-only v3 binding after its composite verifier succeeded."""

    decision = financial_fact_from_model(row).decision_evidence
    if (
        decision is None
        or decision.source_time_witness_v3 is None
        or row.announced_at is not None
        or row.available_at != decision.source_time_witness_v3.available_at
        or row.source_record_id != decision.native_row_id
        or row.raw_payload_hash != decision.artifact_reference.body_sha256
    ):
        raise FinancialFactProvenanceConflictError(
            "v3 publication row does not preserve its original date-only source binding"
        )
    return decision


__all__ = ["FinancialFactProvenanceConflictError", "FinancialFactRepository"]
