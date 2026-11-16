"""Qualification-aware exact native financial value replay candidate.

This class is a numeric proof primitive. It does not atomically fence a write,
Publication build, or activation. Those operations must resolve and recheck
the same qualification under their committing unit of work before use.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from types import MappingProxyType

from django.db import DatabaseError

from apps.data_center.application.financial_numeric_qualification import (
    FinancialNumericSourceQualificationCatalogPort,
    FinancialNumericSourceQualificationResolution,
    FinancialNumericVerificationContext,
)
from apps.data_center.application.financial_numeric_verification import (
    FinancialRetainedFinancialBodyPort,
)
from apps.data_center.domain.entities import FinancialFact
from apps.data_center.domain.financial_numeric_evidence import NativeFinancialMetricObservation
from apps.data_center.domain.financial_response_artifact import FinancialResponseArtifactRef
from apps.data_center.domain.financial_response_evidence import (
    FinancialResponseScopeBasis,
)
from apps.data_center.domain.financial_source_evidence import FINANCIAL_FACT_DATASET_KEY
from apps.data_center.infrastructure._provider_adapter_base import _period_type_from_period_end
from apps.data_center.infrastructure.financial_source_time_matchers import (
    AKSHARE_MAIN_FINANCIAL_DATA_ENDPOINT,
    AKSHARE_PROVIDER_NAME,
    _composite_row_id,
    _main_financial_data_rows,
    _row_asset,
    _row_period_end,
)
from core.exceptions import DataFetchError, DataValidationError


class FinancialNumericQualificationAwareNativeVerifier:
    """Verify one fact against exact bytes and a qualification at explicit clocks.

    The body reader is responsible for independently checking retained bytes,
    the successful RawAudit, the approved main endpoint, and the persisted
    provider identity. This verifier then derives row context and the source
    response clock from that verified body/reference; neither value nor
    knowledge time comes from ``fact.extra`` or a defaulted fact timestamp.

    For reads, writes, and Publications, ``context.known_at`` must be sampled
    by the caller for that operation. Point-in-time callers supply the
    historical cutoff explicitly. This method proves qualification and
    numeric replay only; writes and Publication activation still require an
    independent same-unit-of-work fence/recheck to address revocation races.
    """

    def __init__(
        self,
        catalog: FinancialNumericSourceQualificationCatalogPort,
        body_reader: FinancialRetainedFinancialBodyPort,
    ) -> None:
        """Require the qualification resolver and independently verified reader."""

        if catalog is None or body_reader is None:
            raise TypeError("financial qualification catalog and verified body reader are required")
        self._catalog = catalog
        self._body_reader = body_reader

    def verify(self, fact: FinancialFact, context: FinancialNumericVerificationContext) -> bool:
        """Return true only for an exact native claim qualified for this context."""

        try:
            return self._verify(fact, context)
        except (
            ArithmeticError,
            AttributeError,
            DatabaseError,
            DataFetchError,
            DataValidationError,
            LookupError,
            OSError,
            TypeError,
            ValueError,
        ):
            return False

    def _verify(self, fact: FinancialFact, context: FinancialNumericVerificationContext) -> bool:
        """Validate clocks, raw identity, qualification, and exact decimal replay."""

        if (
            type(fact) is not FinancialFact
            or type(context) is not FinancialNumericVerificationContext
            or fact.numeric_schema != "native-decimal-v2"
        ):
            return False
        observation = fact.numeric_evidence
        source_evidence = fact.source_evidence
        decision_evidence = fact.decision_evidence
        value = fact.value
        if (
            type(observation) is not NativeFinancialMetricObservation
            or type(value) is not Decimal
            or not value.is_finite()
            or source_evidence is None
            or decision_evidence is None
            or type(fact.fetched_at) is not datetime
            or fact.fetched_at.tzinfo is None
            or fact.fetched_at.utcoffset() is None
        ):
            return False
        reference = decision_evidence.artifact_reference
        contract = observation.contract
        request_scope = reference.evidence.request_scope
        response_scope = reference.evidence.response_scope
        response_completed_at = reference.evidence.response_completed_at
        if (
            type(reference) is not FinancialResponseArtifactRef
            or fact.fetched_at > context.known_at
            or response_completed_at > fact.fetched_at
            or response_completed_at > context.known_at
            or fact.period_type != _period_type_from_period_end(fact.period_end)
            or contract.origin != "native"
            or contract.provider != AKSHARE_PROVIDER_NAME
            or contract.metric_code != fact.metric_code
            or contract.canonical_unit != fact.unit
            or contract.dataset_key != FINANCIAL_FACT_DATASET_KEY
            or request_scope.dataset_key != FINANCIAL_FACT_DATASET_KEY
            or request_scope.provider_name != AKSHARE_PROVIDER_NAME
            or request_scope.asset_code != fact.asset_code
            or reference.evidence.response_scope_basis
            is not FinancialResponseScopeBasis.PROVIDER_BODY_VERIFIED
            or response_scope.row_count <= 0
            or observation.body_sha256 != reference.body_sha256
            or source_evidence.raw_payload_hash != reference.body_sha256
            or source_evidence.source_record_id != observation.native_row_id
            or decision_evidence.native_row_id != observation.native_row_id
            or decision_evidence.native_asset_code != fact.asset_code
            or decision_evidence.native_period_end != fact.period_end
        ):
            return False

        body = self._body_reader.read_verified_body(reference)
        rows = _main_financial_data_rows(body)
        if rows is None or len(rows) != response_scope.row_count:
            return False
        matching_rows = tuple(
            row for row in rows if _composite_row_id(row) == observation.native_row_id
        )
        if len(matching_rows) != 1:
            return False
        row = matching_rows[0]
        if _row_asset(row) != fact.asset_code or _row_period_end(row) != fact.period_end:
            return False

        catalog_context = self._catalog.resolve_exact(
            observation.contract_identity,
            endpoint=AKSHARE_MAIN_FINANCIAL_DATA_ENDPOINT,
            source_response_completed_at=response_completed_at,
            source_context=MappingProxyType(dict(row)),
            verification_context=context,
        )
        if type(catalog_context) is not FinancialNumericSourceQualificationResolution:
            return False
        qualification = catalog_context.qualification
        resolved_contract = qualification.contract
        if (
            resolved_contract != contract
            or resolved_contract.identity != observation.contract_identity
            or resolved_contract.content_hash != observation.contract_hash
            or qualification.endpoint != AKSHARE_MAIN_FINANCIAL_DATA_ENDPOINT
            or not qualification.matches_source_context(row)
            or not qualification.is_eligible_at(
                known_at=context.known_at,
                source_response_completed_at=response_completed_at,
                recorded_at=catalog_context.recorded_at,
                approved_at=catalog_context.approved_at,
                revoked_at=catalog_context.revoked_at,
            )
        ):
            return False

        raw_value: object = row.get(contract.source_field)
        if raw_value is None or isinstance(raw_value, bool) or isinstance(raw_value, float):
            return False
        replayed = NativeFinancialMetricObservation.from_raw_value(
            contract=resolved_contract,
            raw_value=raw_value,
            source_field=contract.source_field,
            body_sha256=reference.body_sha256,
            native_row_id=observation.native_row_id,
        )
        return replayed == observation and value == Decimal(replayed.canonical_value)


__all__ = ["FinancialNumericQualificationAwareNativeVerifier"]
