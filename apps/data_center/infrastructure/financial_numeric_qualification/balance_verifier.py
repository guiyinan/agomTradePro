"""Isolated Balance endpoint dispatch and native Decimal replay candidate.

The module is deliberately unactivated. It reuses the typed qualification
resolver candidate and the strict one-row parser, but no Balance provider body,
Owner event, catalog entry, currency/consolidation scope, or broad coverage has
been verified. A successful synthetic replay is not BODY_VERIFIED evidence or
D1/production eligibility.
"""

from __future__ import annotations

import hashlib
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from types import MappingProxyType
from typing import Protocol
from uuid import UUID

from django.db import DatabaseError

from apps.data_center.application.financial_numeric_qualification import (
    FinancialNumericSourceQualificationCatalogPort,
    FinancialNumericSourceQualificationResolution,
    FinancialNumericVerificationContext,
)
from apps.data_center.application.financial_numeric_verification import (
    FinancialNativeProviderIdentityPort,
    FinancialProviderIdentity,
)
from apps.data_center.domain.entities import FinancialFact, RawAudit, raw_audit_content_hash
from apps.data_center.domain.financial_numeric_evidence import (
    NativeFinancialMetricObservation,
)
from apps.data_center.domain.financial_numeric_source_qualification import (
    FinancialNumericSourceQualification,
)
from apps.data_center.domain.financial_response_artifact import FinancialResponseArtifactRef
from apps.data_center.domain.financial_response_evidence import (
    FinancialResponseScopeBasis,
)
from apps.data_center.domain.financial_source_evidence import FINANCIAL_FACT_DATASET_KEY
from apps.data_center.infrastructure._provider_adapter_base import _period_type_from_period_end
from apps.data_center.infrastructure.financial_response_artifact_repository import (
    reference_from_audit,
)
from apps.data_center.infrastructure.financial_source_time_matchers import (
    AKSHARE_MAIN_FINANCIAL_DATA_ENDPOINT,
    AKSHARE_PROVIDER_NAME,
)
from core.exceptions import DataFetchError, DataValidationError

from .balance_raw_boundary import (
    BalanceCandidateContract,
    BalanceCandidateRequest,
    BalanceCandidateSourceRowIdentity,
    BalanceValueBinding,
    build_balance_candidate_query,
    parse_balance_candidate_body,
)

AKSHARE_BALANCE_API_URL = "https://datacenter-web.eastmoney.com/api/data/v1/get"
AKSHARE_BALANCE_REPORT_NAME = "RPT_DMSK_FN_BALANCE"
AKSHARE_BALANCE_FINANCIAL_DATA_ENDPOINT = (
    f"{AKSHARE_BALANCE_API_URL}?reportName={AKSHARE_BALANCE_REPORT_NAME}"
)
_BALANCE_RAW_FIELDS = frozenset({"TOTAL_ASSETS", "TOTAL_LIABILITIES", "TOTAL_EQUITY"})
_BALANCE_CONTRACT_ID = "akshare.stock_zcfz_em.raw.v1"


class BalanceNumericEvidenceVerificationError(DataValidationError):
    """Block a Balance body when retained identity or bytes do not agree."""

    default_message = "Balance 原始数值证据尚未通过独立复核。"
    default_code = "BALANCE_NATIVE_NUMERIC_EVIDENCE_BLOCKED"


class _BalanceArtifactBodyRepository(Protocol):
    """Read the encrypted body bytes from the existing retention repository."""

    def read(self, reference: FinancialResponseArtifactRef) -> bytes:
        """Return the exact retained body or raise a stable data error."""
        ...


class _BalanceArtifactAuditRepository(Protocol):
    """Read every successful RawAudit linked to one financial capture."""

    def list_by_artifact_capture_id(self, capture_id: UUID) -> list[RawAudit]:
        """Return the complete capture-linked audit set for cardinality checks."""
        ...


class _ContextualVerifier(Protocol):
    """Minimal dispatch target shared with the prepared Main verifier."""

    def verify(self, fact: FinancialFact, context: FinancialNumericVerificationContext) -> bool:
        """Verify a fact with caller-sampled use purpose and known-at time."""
        ...


@dataclass(frozen=True, slots=True)
class BalanceVerifiedOriginalResponse:
    """Original bytes plus the audited request parameters used to obtain them.

    Construction alone is not authority. The production reader must perform
    the audit, provider identity, artifact-link, endpoint, and body-hash checks
    implemented by ``BalanceNumericOriginalBodyReader`` below.
    """

    body: bytes
    request_params: Mapping[str, object]

    def __post_init__(self) -> None:
        """Require exact bytes and an immutable text-keyed request mapping."""

        if type(self.body) is not bytes:
            raise TypeError("retained Balance body must be exact bytes")
        if not isinstance(self.request_params, Mapping) or any(
            type(key) is not str for key in self.request_params
        ):
            raise TypeError("audited request parameters must be a string-keyed mapping")
        object.__setattr__(self, "request_params", MappingProxyType(dict(self.request_params)))


class _VerifiedBalanceAuditReader:
    """Validate one artifact-linked audit and its exact persisted provider."""

    def __init__(
        self,
        audit_repository: _BalanceArtifactAuditRepository,
        provider_identity_resolver: FinancialNativeProviderIdentityPort,
    ) -> None:
        """Bind the two independent persisted identity readers."""

        self._audit_repository = audit_repository
        self._provider_identity_resolver = provider_identity_resolver

    def read(
        self,
        reference: FinancialResponseArtifactRef,
        *,
        expected_endpoint: str | None = None,
    ) -> tuple[RawAudit, Mapping[str, object], str]:
        """Return the sole successful audit after exact endpoint/provider checks."""

        if type(reference) is not FinancialResponseArtifactRef:
            raise BalanceNumericEvidenceVerificationError()
        evidence = reference.evidence
        request_scope = evidence.request_scope
        response_scope = evidence.response_scope
        if (
            request_scope.dataset_key != FINANCIAL_FACT_DATASET_KEY
            or request_scope.provider_name != AKSHARE_PROVIDER_NAME
            or evidence.response_scope_basis
            is not FinancialResponseScopeBasis.PROVIDER_BODY_VERIFIED
            or response_scope.row_count <= 0
        ):
            raise BalanceNumericEvidenceVerificationError()
        try:
            audits = self._audit_repository.list_by_artifact_capture_id(reference.capture_id)
        except DatabaseError as error:
            raise BalanceNumericEvidenceVerificationError() from error
        if len(audits) != 1:
            raise BalanceNumericEvidenceVerificationError()
        audit = audits[0]
        params = audit.request_params
        endpoint = params.get("endpoint") if isinstance(params, Mapping) else None
        is_balance = endpoint == AKSHARE_BALANCE_FINANCIAL_DATA_ENDPOINT
        is_main = endpoint == AKSHARE_MAIN_FINANCIAL_DATA_ENDPOINT
        if (
            audit.capability != "financial"
            or audit.status != "ok"
            or audit.redacted is not True
            or audit.provider_name != request_scope.provider_name
            or not isinstance(params, Mapping)
            or type(endpoint) is not str
            or not (is_balance or is_main)
            or (is_balance and params.get("reportName") != AKSHARE_BALANCE_REPORT_NAME)
            or (expected_endpoint is not None and endpoint != expected_endpoint)
            or audit.fetched_at != evidence.response_completed_at
            or audit.response_payload_hash != reference.body_sha256
            or audit.payload_size_bytes != reference.body_size_bytes
            or audit.row_count != response_scope.row_count
            or not audit.content_hash
            or audit.content_hash != raw_audit_content_hash(audit)
        ):
            raise BalanceNumericEvidenceVerificationError()
        try:
            if reference_from_audit(audit) != reference:
                raise BalanceNumericEvidenceVerificationError()
        except (KeyError, TypeError, ValueError) as error:
            raise BalanceNumericEvidenceVerificationError() from error

        raw_link = audit.extra.get("financial_response_artifact")
        if not isinstance(raw_link, Mapping):
            raise BalanceNumericEvidenceVerificationError()
        provider_id = raw_link.get("provider_id")
        if type(provider_id) is not int or provider_id <= 0:
            raise BalanceNumericEvidenceVerificationError()
        try:
            provider = self._provider_identity_resolver.resolve_by_id(provider_id)
        except DatabaseError as error:
            raise BalanceNumericEvidenceVerificationError() from error
        if (
            type(provider) is not FinancialProviderIdentity
            or provider.provider_id != provider_id
            or provider.source_type != request_scope.provider_name
        ):
            raise BalanceNumericEvidenceVerificationError()
        return audit, MappingProxyType(dict(params)), endpoint


class BalanceNumericEndpointRouteResolver:
    """Read the persisted endpoint marker before choosing a metric verifier.

    This route step proves only which endpoint the immutable RawAudit names; it
    does not read the body or establish a catalog qualification. Both routed
    verifiers must independently validate their complete body and contract.
    """

    def __init__(
        self,
        audit_repository: _BalanceArtifactAuditRepository,
        provider_identity_resolver: FinancialNativeProviderIdentityPort,
    ) -> None:
        """Bind exact audit and provider readers without touching the body store."""

        self._audit_reader = _VerifiedBalanceAuditReader(
            audit_repository,
            provider_identity_resolver,
        )

    def resolve(self, reference: FinancialResponseArtifactRef) -> str:
        """Return only the exact Main or Balance endpoint stored in its audit."""

        _, _, endpoint = self._audit_reader.read(reference)
        return endpoint


class FinancialNumericEndpointVerifierDispatcher:
    """Route retained AKShare Main and Balance facts by verified RawAudit endpoint.

    Current read and PIT callers may use the route only as evidence/as-of
    verification. Current decision reads, writes, and Publications still need
    the catalog's caller-owned UOW/current-revocation fence through commit.
    """

    def __init__(
        self,
        route_resolver: BalanceNumericEndpointRouteResolver,
        *,
        main_verifier: _ContextualVerifier,
        balance_verifier: _ContextualVerifier,
    ) -> None:
        """Require both endpoint-specific verifiers and one audit route reader."""

        if route_resolver is None or main_verifier is None or balance_verifier is None:
            raise TypeError("endpoint dispatch requires route, Main, and Balance verifiers")
        self._route_resolver = route_resolver
        self._main_verifier = main_verifier
        self._balance_verifier = balance_verifier

    def verify(self, fact: FinancialFact, context: FinancialNumericVerificationContext) -> bool:
        """Dispatch only by the endpoint read from the exact linked RawAudit."""

        try:
            if type(fact) is not FinancialFact or fact.decision_evidence is None:
                return False
            if type(context) is not FinancialNumericVerificationContext:
                return False
            endpoint = self._route_resolver.resolve(fact.decision_evidence.artifact_reference)
            if endpoint == AKSHARE_MAIN_FINANCIAL_DATA_ENDPOINT:
                return self._main_verifier.verify(fact, context)
            if endpoint == AKSHARE_BALANCE_FINANCIAL_DATA_ENDPOINT:
                return self._balance_verifier.verify(fact, context)
            return False
        except (
            AttributeError,
            BalanceNumericEvidenceVerificationError,
            DatabaseError,
            DataFetchError,
            DataValidationError,
            OSError,
            TypeError,
            ValueError,
            LookupError,
        ):
            return False


class BalanceNumericOriginalBodyReader:
    """Read retained bytes only for the exact Balance endpoint and report name.

    Provider identity is tied to the stored provider primary key and unchanged
    ``source_type``. Current activation is intentionally irrelevant to reading
    historical bytes. This check does not independently prove that the remote
    host was official; controlled-egress and actual request-URL evidence remain
    an integration requirement for the future capture composition.
    """

    def __init__(
        self,
        *,
        artifact_repository: _BalanceArtifactBodyRepository,
        audit_repository: _BalanceArtifactAuditRepository,
        provider_identity_resolver: FinancialNativeProviderIdentityPort,
    ) -> None:
        """Bind exact retained bytes, audit rows, and provider identities."""

        self._artifact_repository = artifact_repository
        self._audit_reader = _VerifiedBalanceAuditReader(
            audit_repository,
            provider_identity_resolver,
        )

    def read_verified_response(
        self,
        reference: FinancialResponseArtifactRef,
    ) -> BalanceVerifiedOriginalResponse:
        """Return exact bytes and audited params after one body-store read."""

        _, request_params, endpoint = self._audit_reader.read(
            reference,
            expected_endpoint=AKSHARE_BALANCE_FINANCIAL_DATA_ENDPOINT,
        )
        if endpoint != AKSHARE_BALANCE_FINANCIAL_DATA_ENDPOINT:
            raise BalanceNumericEvidenceVerificationError()
        try:
            body = self._artifact_repository.read(reference)
        except (DataFetchError, OSError, TypeError, ValueError) as error:
            raise BalanceNumericEvidenceVerificationError() from error
        if (
            type(body) is not bytes
            or len(body) != reference.body_size_bytes
            or hashlib.sha256(body).hexdigest() != reference.body_sha256
        ):
            raise BalanceNumericEvidenceVerificationError()
        return BalanceVerifiedOriginalResponse(body=body, request_params=request_params)


class FinancialNumericQualificationAwareBalanceVerifier:
    """Replay one Balance native field through the qualification-aware catalog.

    Metric and unit bindings are supplied through the typed parser contract and
    source qualification. This verifier contains no financial metric, unit,
    scale, currency, consolidation, or missing-value defaults. Its successful
    synthetic path is not a production qualification: the Balance catalog is
    still empty and source applicability remains unproven.
    """

    def __init__(
        self,
        catalog: FinancialNumericSourceQualificationCatalogPort,
        body_reader: BalanceNumericOriginalBodyReader,
        parser_contract: BalanceCandidateContract,
    ) -> None:
        """Bind the existing typed resolver, Balance-only body reader, and schema."""

        if catalog is None or body_reader is None:
            raise TypeError("Balance qualification resolver and original-body reader are required")
        _validate_balance_parser_contract(parser_contract)
        self._catalog = catalog
        self._body_reader = body_reader
        self._parser_contract = parser_contract

    def verify(self, fact: FinancialFact, context: FinancialNumericVerificationContext) -> bool:
        """Return true only when the exact raw Balance field replays at known_at."""

        try:
            return self._verify(fact, context)
        except (
            ArithmeticError,
            AttributeError,
            BalanceNumericEvidenceVerificationError,
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
        """Check artifact, contract, exact row, catalog clocks, and Decimal replay."""

        if (
            type(fact) is not FinancialFact
            or type(context) is not FinancialNumericVerificationContext
            or fact.numeric_schema != "native-decimal-v2"
        ):
            return False
        observation = fact.numeric_evidence
        source = fact.source_evidence
        decision = fact.decision_evidence
        value = fact.value
        if (
            type(observation) is not NativeFinancialMetricObservation
            or type(value) is not Decimal
            or not value.is_finite()
            or source is None
            or decision is None
            or type(fact.fetched_at) is not datetime
            or fact.fetched_at.tzinfo is None
            or fact.fetched_at.utcoffset() is None
        ):
            return False
        reference = decision.artifact_reference
        evidence = reference.evidence
        request_scope = evidence.request_scope
        response_scope = evidence.response_scope
        response_completed_at = evidence.response_completed_at
        contract = observation.contract
        if (
            type(reference) is not FinancialResponseArtifactRef
            or fact.fetched_at > context.known_at
            or response_completed_at > fact.fetched_at
            or fact.period_type != _period_type_from_period_end(fact.period_end)
            or contract.origin != "native"
            or contract.provider != AKSHARE_PROVIDER_NAME
            or contract.dataset_key != FINANCIAL_FACT_DATASET_KEY
            or contract.metric_code != fact.metric_code
            or contract.canonical_unit != fact.unit
            or fact.source != contract.provider
            or request_scope.dataset_key != FINANCIAL_FACT_DATASET_KEY
            or request_scope.provider_name != AKSHARE_PROVIDER_NAME
            or request_scope.asset_code != fact.asset_code
            or evidence.response_scope_basis
            is not FinancialResponseScopeBasis.PROVIDER_BODY_VERIFIED
            or response_scope.row_count != 1
            or fact.period_end not in response_scope.period_ends
            or observation.body_sha256 != reference.body_sha256
            or source.raw_payload_hash != reference.body_sha256
            or source.source_record_id != observation.native_row_id
            or decision.native_row_id != observation.native_row_id
            or decision.native_asset_code != fact.asset_code
            or decision.native_period_end != fact.period_end
        ):
            return False

        verified_response = self._body_reader.read_verified_response(reference)
        request = _request_for_fact(fact)
        expected_params = dict(
            build_balance_candidate_query(request, self._parser_contract).parameters
        )
        expected_params["endpoint"] = AKSHARE_BALANCE_FINANCIAL_DATA_ENDPOINT
        if not _same_exact_mapping(verified_response.request_params, expected_params):
            return False
        parsed = parse_balance_candidate_body(
            verified_response.body,
            request=request,
            contract=self._parser_contract,
        )
        if (
            parsed.outcome != "candidate_parsed"
            or parsed.body_sha256 != reference.body_sha256
            or parsed.body_size_bytes != reference.body_size_bytes
            or parsed.row_index != 0
            or parsed.source_row_identity is None
            or parsed.row_projection_sha256 is None
        ):
            return False
        identity = parsed.source_row_identity
        if (
            identity.symbol != fact.asset_code
            or identity.security_code != request.security_code
            or identity.report_date != fact.period_end
        ):
            return False
        native_row_id = _balance_native_row_id(identity)
        if native_row_id != observation.native_row_id:
            return False

        bindings = tuple(
            binding
            for binding in self._parser_contract.value_bindings
            if binding.metric_code == contract.metric_code
        )
        if (
            len(bindings) != 1
            or bindings[0].raw_key != contract.source_field
            or bindings[0].unit_code != contract.source_unit
        ):
            return False
        source_context = parsed.raw_row_context
        resolution = self._catalog.resolve_exact(
            observation.contract_identity,
            endpoint=AKSHARE_BALANCE_FINANCIAL_DATA_ENDPOINT,
            source_response_completed_at=response_completed_at,
            source_context=source_context,
            verification_context=context,
        )
        if type(resolution) is not FinancialNumericSourceQualificationResolution:
            return False
        qualification = resolution.qualification
        resolved_contract = qualification.contract
        if (
            type(qualification) is not FinancialNumericSourceQualification
            or resolved_contract != contract
            or resolved_contract.identity != observation.contract_identity
            or resolved_contract.content_hash != observation.contract_hash
            or qualification.endpoint != AKSHARE_BALANCE_FINANCIAL_DATA_ENDPOINT
            or not qualification.matches_source_context(source_context)
            or not qualification.is_eligible_at(
                known_at=context.known_at,
                source_response_completed_at=response_completed_at,
                recorded_at=resolution.recorded_at,
                approved_at=resolution.approved_at,
                revoked_at=resolution.revoked_at,
            )
        ):
            return False

        native_values = tuple(
            item for item in parsed.values if item.metric_code == fact.metric_code
        )
        if len(native_values) != 1:
            return False
        replayed = NativeFinancialMetricObservation.from_raw_value(
            contract=resolved_contract,
            raw_value=native_values[0].value,
            source_field=resolved_contract.source_field,
            body_sha256=reference.body_sha256,
            native_row_id=native_row_id,
        )
        return replayed == observation and value == Decimal(replayed.canonical_value)


def _validate_balance_parser_contract(contract: BalanceCandidateContract) -> None:
    """Require the one source-supported endpoint and known native field set."""

    if type(contract) is not BalanceCandidateContract:
        raise TypeError("parser_contract must be a typed BalanceCandidateContract")
    bindings = contract.value_bindings
    if (
        contract.evidence_state != "static_candidate_unverified"
        or contract.contract_id != _BALANCE_CONTRACT_ID
        or contract.endpoint_url != AKSHARE_BALANCE_API_URL
        or contract.report_name != AKSHARE_BALANCE_REPORT_NAME
        or contract.security_filter_key != "SECURITY_CODE"
        or contract.report_date_filter_key != "REPORT_DATE"
        or contract.result_key != "result"
        or contract.success_key != "success"
        or contract.success_value is not True
        or contract.code_key != "code"
        or type(contract.success_code) is not int
        or contract.success_code != 0
        or contract.count_key != "count"
        or contract.pages_key != "pages"
        or contract.data_key != "data"
        or contract.row_security_code_key != "SECURITY_CODE"
        or contract.row_report_date_key != "REPORT_DATE"
        or contract.row_notice_date_key != "NOTICE_DATE"
        or frozenset(binding.raw_key for binding in bindings) != _BALANCE_RAW_FIELDS
        or len({binding.metric_code for binding in bindings}) != 3
    ):
        raise ValueError("parser contract is not the explicit unverified stock_zcfz_em schema")
    for binding in bindings:
        if type(binding) is not BalanceValueBinding:
            raise TypeError("parser value bindings must remain typed")


def _request_for_fact(fact: FinancialFact) -> BalanceCandidateRequest:
    """Build a strict one-period request identity without exchange inference."""

    symbol = fact.asset_code
    if (
        type(symbol) is not str
        or len(symbol) != 9
        or symbol[6] != "."
        or symbol[7:] not in {"SH", "SZ"}
        or not symbol[:6].isascii()
        or not symbol[:6].isdigit()
    ):
        raise ValueError("Balance verifier supports only explicit six-digit SH/SZ asset codes")
    return BalanceCandidateRequest(
        symbol=symbol,
        security_code=symbol[:6],
        report_date=fact.period_end,
    )


def _balance_native_row_id(identity: BalanceCandidateSourceRowIdentity) -> str:
    """Return one local row identity bound to its exact projected body digest."""

    return f"balance-row-projection.v1:{identity.row_projection_sha256}"


def _same_exact_mapping(
    actual: Mapping[str, object],
    expected: Mapping[str, object],
) -> bool:
    """Compare the audited request projection without coercing scalar types."""

    return (
        type(actual) is MappingProxyType
        and dict(actual) == dict(expected)
        and all(type(actual[key]) is type(value) for key, value in expected.items())
    )


__all__ = [
    "AKSHARE_BALANCE_API_URL",
    "AKSHARE_BALANCE_FINANCIAL_DATA_ENDPOINT",
    "AKSHARE_BALANCE_REPORT_NAME",
    "BalanceNumericEndpointRouteResolver",
    "BalanceNumericEvidenceVerificationError",
    "BalanceNumericOriginalBodyReader",
    "BalanceVerifiedOriginalResponse",
    "FinancialNumericEndpointVerifierDispatcher",
    "FinancialNumericQualificationAwareBalanceVerifier",
]
