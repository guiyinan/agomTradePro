"""Synthetic endpoint dispatch and exact Balance native replay tests.

These tests exercise the canonical implementation. Their fabricated body,
audit, provider, catalog entry and Owner event do not establish production
approval, official origin, BODY_VERIFIED capture, or source applicability.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from uuid import UUID

import pytest

from apps.data_center.application.financial_numeric_qualification import (
    FinancialNumericSourceQualificationResolution,
    FinancialNumericVerificationContext,
    FinancialNumericVerificationPurpose,
)
from apps.data_center.application.financial_numeric_verification import (
    FinancialProviderIdentity,
)
from apps.data_center.domain.entities import FinancialFact, RawAudit, raw_audit_content_hash
from apps.data_center.domain.financial_numeric_catalog import (
    FinancialNumericCatalogEntry,
    FinancialNumericCatalogOwnerEvent,
)
from apps.data_center.domain.financial_numeric_evidence import (
    FinancialMetricSourceContract,
    NativeFinancialMetricObservation,
)
from apps.data_center.domain.financial_numeric_source_qualification import (
    FinancialNumericSourceContextRequirement,
    FinancialNumericSourceDocumentCaptureReference,
    FinancialNumericSourceQualification,
)
from apps.data_center.domain.financial_response_artifact import FinancialResponseArtifactRef
from apps.data_center.domain.financial_response_evidence import (
    FinancialRequestScope,
    FinancialResponseBodyScope,
    FinancialResponseEvidence,
    FinancialResponseScope,
    FinancialResponseScopeBasis,
)
from apps.data_center.domain.financial_source_evidence import (
    FINANCIAL_FACT_DATASET_KEY,
    FinancialFactDecisionEvidence,
    FinancialFactSourceEvidence,
)
from apps.data_center.infrastructure._provider_adapter_base import _period_type_from_period_end
from apps.data_center.infrastructure.financial_numeric_qualification.balance_raw_boundary import (
    BalanceCandidateContract,
    BalanceCandidateRequest,
    BalanceValueBinding,
    build_balance_candidate_query,
    parse_balance_candidate_body,
)
from apps.data_center.infrastructure.financial_numeric_qualification.balance_verifier import (
    AKSHARE_BALANCE_API_URL,
    AKSHARE_BALANCE_FINANCIAL_DATA_ENDPOINT,
    AKSHARE_BALANCE_REPORT_NAME,
    BalanceNumericEndpointRouteResolver,
    BalanceNumericEvidenceVerificationError,
    BalanceNumericOriginalBodyReader,
    FinancialNumericEndpointVerifierDispatcher,
    FinancialNumericQualificationAwareBalanceVerifier,
)
from apps.data_center.infrastructure.financial_source_time_matchers import (
    AKSHARE_MAIN_FINANCIAL_DATA_ENDPOINT,
)

_ASSET = "000858.SZ"
_PERIOD = date(2026, 9, 30)
_RESPONSE_AT = datetime(2026, 11, 1, 4, 0, tzinfo=UTC)
_KNOWN_AT = datetime(2026, 11, 5, 12, 0, tzinfo=UTC)
_PROVIDER_ID = 73
_CAPTURE_ID = UUID("20000000-0000-4000-8000-000000000017")
_ENTRY_ID = UUID("10000000-0000-4000-8000-000000000017")
_APPLY_ID = UUID("30000000-0000-4000-8000-000000000017")
_DOC_CAPTURE_ID = UUID("40000000-0000-4000-8000-000000000017")
_UNIT_BY_FIELD = {
    "TOTAL_ASSETS": "synthetic-assets-source-unit",
    "TOTAL_LIABILITIES": "synthetic-liabilities-source-unit",
    "TOTAL_EQUITY": "synthetic-equity-source-unit",
}
_METRIC_BY_FIELD = {
    "TOTAL_ASSETS": "synthetic.asset.metric",
    "TOTAL_LIABILITIES": "synthetic.liability.metric",
    "TOTAL_EQUITY": "synthetic.equity.metric",
}


def _parser_contract(
    *, base_filter_terms: tuple[str, ...] | None = None
) -> BalanceCandidateContract:
    """Build the exact static candidate schema with explicit test-only bindings."""

    return BalanceCandidateContract(
        contract_id="akshare.stock_zcfz_em.raw.v1",
        evidence_state="static_candidate_unverified",
        endpoint_url=AKSHARE_BALANCE_API_URL,
        report_name=AKSHARE_BALANCE_REPORT_NAME,
        base_filter_terms=base_filter_terms or ('(SYNTHETIC_FILTER="test-only")',),
        security_filter_key="SECURITY_CODE",
        report_date_filter_key="REPORT_DATE",
        result_key="result",
        success_key="success",
        success_value=True,
        code_key="code",
        success_code=0,
        count_key="count",
        pages_key="pages",
        data_key="data",
        row_security_code_key="SECURITY_CODE",
        row_report_date_key="REPORT_DATE",
        row_notice_date_key="NOTICE_DATE",
        value_bindings=(
            BalanceValueBinding(
                _METRIC_BY_FIELD["TOTAL_ASSETS"],
                "TOTAL_ASSETS",
                _UNIT_BY_FIELD["TOTAL_ASSETS"],
            ),
            BalanceValueBinding(
                _METRIC_BY_FIELD["TOTAL_LIABILITIES"],
                "TOTAL_LIABILITIES",
                _UNIT_BY_FIELD["TOTAL_LIABILITIES"],
            ),
            BalanceValueBinding(
                _METRIC_BY_FIELD["TOTAL_EQUITY"],
                "TOTAL_EQUITY",
                _UNIT_BY_FIELD["TOTAL_EQUITY"],
            ),
        ),
    )


def _body(*, rows: object | None = None) -> bytes:
    """Return one clearly synthetic, finite-decimal Balance response."""

    if rows is None:
        return (
            b'{"success":true,"code":0,"result":{"count":1,"pages":1,"data":['
            b'{"SECURITY_CODE":"000858","REPORT_DATE":"2026-09-30 00:00:00",'
            b'"NOTICE_DATE":"2026-10-25 00:00:00",'
            b'"TOTAL_ASSETS":123456789012345.1234567,'
            b'"TOTAL_LIABILITIES":234567890123.45009,'
            b'"TOTAL_EQUITY":987654321.875}]}}'
        )
    return json.dumps(
        {"success": True, "code": 0, "result": {"count": 1, "pages": 1, "data": rows}},
        separators=(",", ":"),
    ).encode("utf-8")


class _BodyRepository:
    """Return synthetic bytes and count body reads."""

    def __init__(self, body: bytes) -> None:
        """Bind the exact test response."""

        self.body = body
        self.reads: list[FinancialResponseArtifactRef] = []

    def read(self, reference: FinancialResponseArtifactRef) -> bytes:
        """Return bytes after recording one requested body read."""

        self.reads.append(reference)
        return self.body


class _AuditRepository:
    """Return synthetic linked audit rows for one capture."""

    def __init__(self, audits: list[RawAudit]) -> None:
        """Bind the fabricated capture audit rows."""

        self.audits = audits
        self.reads: list[UUID] = []

    def list_by_artifact_capture_id(self, capture_id: UUID) -> list[RawAudit]:
        """Return all rows, preserving exact-cardinality behavior."""

        self.reads.append(capture_id)
        return self.audits


class _ProviderResolver:
    """Return a synthetic persisted-provider identity."""

    def __init__(self, provider: FinancialProviderIdentity | None = None) -> None:
        """Bind an exact provider fixture, including its activation state."""

        self.provider = provider or FinancialProviderIdentity(
            provider_id=_PROVIDER_ID,
            name="synthetic_akshare",
            source_type="akshare",
            is_active=False,
        )

    def resolve_by_id(self, provider_id: int) -> FinancialProviderIdentity | None:
        """Resolve only the configured test identity."""

        return self.provider if provider_id == self.provider.provider_id else None


class _Catalog:
    """Return one real-shaped, but synthetic, typed catalog resolution."""

    def __init__(self, entry: FinancialNumericCatalogEntry | None) -> None:
        """Bind a synthetic immutable entry or absence."""

        self.entry = entry
        self.calls: list[dict[str, object]] = []

    def resolve_exact(
        self,
        contract_identity: str,
        *,
        endpoint: str,
        source_response_completed_at: datetime,
        source_context: Mapping[str, object],
        verification_context: FinancialNumericVerificationContext,
    ) -> FinancialNumericSourceQualificationResolution | None:
        """Record the exact source and knowledge query before returning the entry."""

        self.calls.append(
            {
                "contract_identity": contract_identity,
                "endpoint": endpoint,
                "source_response_completed_at": source_response_completed_at,
                "source_context": source_context,
                "known_at": verification_context.known_at,
                "purpose": verification_context.purpose,
            }
        )
        if self.entry is None:
            return None
        visible_events = tuple(
            event
            for event in self.entry.owner_events
            if event.recorded_at <= verification_context.known_at
        )
        visible_entry = replace(self.entry, owner_events=visible_events)
        return FinancialNumericSourceQualificationResolution(visible_entry)


def _contract(field: str = "TOTAL_ASSETS") -> FinancialMetricSourceContract:
    """Create one test-only explicit native contract from runtime binding data."""

    return FinancialMetricSourceContract(
        provider="akshare",
        dataset_key=FINANCIAL_FACT_DATASET_KEY,
        metric_code=_METRIC_BY_FIELD[field],
        source_field=field,
        source_unit=_UNIT_BY_FIELD[field],
        canonical_unit=f"synthetic-{field.lower()}-canonical-unit",
        scale_numerator=1,
        scale_denominator=1,
        contract_version="balance-verifier-test.v1",
        origin="native",
    )


def _qualification(
    contract: FinancialMetricSourceContract,
    *,
    context_requirements: tuple[FinancialNumericSourceContextRequirement, ...] | None = None,
) -> FinancialNumericSourceQualification:
    """Build a synthetic exact endpoint qualification and document reference."""

    captured_at = _RESPONSE_AT - timedelta(days=5)
    capture = FinancialNumericSourceDocumentCaptureReference(
        capture_id=_DOC_CAPTURE_ID,
        document_id="synthetic-akshare-balance-doc",
        issuer="synthetic-doc-publisher",
        canonical_url="https://docs.example.invalid/stock_zcfz_em",
        body_sha256="d" * 64,
        body_size_bytes=256,
        captured_at=captured_at,
        content_type="text/html",
    )
    return FinancialNumericSourceQualification(
        contract=contract,
        endpoint=AKSHARE_BALANCE_FINANCIAL_DATA_ENDPOINT,
        source_applicability="synthetic-only-balance-row",
        document_capture=capture,
        context_requirements=context_requirements
        or (
            FinancialNumericSourceContextRequirement("SECURITY_CODE", "000858"),
            FinancialNumericSourceContextRequirement("REPORT_DATE", "2026-09-30 00:00:00"),
        ),
        effective_from=captured_at,
        effective_until=None,
    )


def _entry(
    qualification: FinancialNumericSourceQualification,
    *,
    approved_at: datetime = _RESPONSE_AT - timedelta(hours=1),
    recorded_at: datetime | None = None,
    revoked_at: datetime | None = None,
) -> FinancialNumericCatalogEntry:
    """Build a synthetic typed catalog entry with its separately typed Owner event."""

    entry_recorded_at = qualification.document_capture.captured_at + timedelta(seconds=2)
    owner_recorded_at = recorded_at or approved_at + timedelta(seconds=5)
    apply_event = FinancialNumericCatalogOwnerEvent(
        event_id=_APPLY_ID,
        entry_id=_ENTRY_ID,
        action="apply",
        qualification_identity=qualification.identity,
        qualification_sha256=qualification.content_hash,
        actor_id=701,
        actor_username="synthetic-authenticated-owner",
        event_at=approved_at,
        recorded_at=owner_recorded_at,
    )
    owner_events = [apply_event]
    if revoked_at is not None:
        owner_events.append(
            FinancialNumericCatalogOwnerEvent(
                event_id=UUID("50000000-0000-4000-8000-000000000017"),
                entry_id=_ENTRY_ID,
                action="revoke",
                qualification_identity=qualification.identity,
                qualification_sha256=qualification.content_hash,
                actor_id=701,
                actor_username="synthetic-authenticated-owner",
                event_at=revoked_at,
                recorded_at=revoked_at + timedelta(seconds=5),
            )
        )
    return FinancialNumericCatalogEntry(
        entry_id=_ENTRY_ID,
        qualification=qualification,
        recorded_at=entry_recorded_at,
        capture_recorded_at=qualification.document_capture.captured_at + timedelta(seconds=1),
        owner_events=tuple(owner_events),
    )


def _reference(
    body: bytes, *, endpoint: str = AKSHARE_BALANCE_FINANCIAL_DATA_ENDPOINT
) -> FinancialResponseArtifactRef:
    """Build a synthetic body-hash-bound response reference."""

    response_evidence = FinancialResponseEvidence(
        body_sha256=hashlib.sha256(body).hexdigest(),
        body_size_bytes=len(body),
        response_completed_at=_RESPONSE_AT,
        request_scope=FinancialRequestScope(
            provider_name="akshare",
            dataset_key=FINANCIAL_FACT_DATASET_KEY,
            asset_code=_ASSET,
            period_limit=1,
        ),
        response_scope=FinancialResponseScope(
            asset_codes=(_ASSET,),
            period_ends=(_PERIOD,),
            row_count=1,
        ),
        body_scope=FinancialResponseBodyScope.BATCH,
        response_scope_basis=FinancialResponseScopeBasis.PROVIDER_BODY_VERIFIED,
    )
    return FinancialResponseArtifactRef(
        capture_id=_CAPTURE_ID,
        location="financial-response:///v1/20000000-0000-4000-8000-000000000017.frb",
        evidence=response_evidence,
        format_version="financial-response-body-fernet-v1",
        encryption_algorithm="fernet-aes128cbc-hmacsha256",
        encryption_key_ref="synthetic-only.balance-test-key",
        encryption_key_version="synthetic-v1",
    )


def _audit(
    reference: FinancialResponseArtifactRef,
    *,
    endpoint: str = AKSHARE_BALANCE_FINANCIAL_DATA_ENDPOINT,
    provider_name: str = "akshare",
    parser_contract: BalanceCandidateContract | None = None,
) -> RawAudit:
    """Bind the exact synthetic artifact and request to one RawAudit value."""

    request_params = dict(
        build_balance_candidate_query(
            BalanceCandidateRequest(_ASSET, _ASSET[:6], _PERIOD),
            parser_contract or _parser_contract(),
        ).parameters
    )
    request_params["endpoint"] = endpoint
    if endpoint == AKSHARE_BALANCE_FINANCIAL_DATA_ENDPOINT:
        request_params["reportName"] = AKSHARE_BALANCE_REPORT_NAME
    audit = RawAudit(
        provider_name=provider_name,
        capability="financial",
        request_params=request_params,
        status="ok",
        row_count=reference.evidence.response_scope.row_count,
        fetched_at=reference.evidence.response_completed_at,
        extra={
            "financial_response_artifact": {
                "schema": "financial-response-artifact-link.v1",
                **reference.to_dict(),
                "provider_id": _PROVIDER_ID,
            }
        },
        response_payload_hash=reference.body_sha256,
        redacted=True,
        parser_version="financial-response-artifact.v1",
        payload_size_bytes=reference.body_size_bytes,
    )
    return replace(audit, content_hash=raw_audit_content_hash(audit))


def _row_id(body: bytes) -> str:
    """Compute the parser's body-bound one-row projection identity."""

    from apps.data_center.infrastructure.financial_numeric_qualification.balance_raw_boundary import (
        BalanceCandidateRequest,
        parse_balance_candidate_body,
    )

    parsed = parse_balance_candidate_body(
        body,
        request=BalanceCandidateRequest(_ASSET, _ASSET[:6], _PERIOD),
        contract=_parser_contract(),
    )
    if parsed.source_row_identity is None:
        return f"candidate-invalid-body.v1:{hashlib.sha256(body).hexdigest()}"
    return f"balance-row-projection.v1:{parsed.source_row_identity.row_projection_sha256}"


def _fact(
    *,
    body: bytes | None = None,
    field: str = "TOTAL_ASSETS",
    fetched_at: datetime = _RESPONSE_AT + timedelta(seconds=1),
) -> tuple[FinancialFact, FinancialResponseArtifactRef]:
    """Build one synthetic v2 fact and its independently linked artifact reference."""

    selected_body = body or _body()
    contract = _contract(field)
    parser_value = {
        "TOTAL_ASSETS": Decimal("123456789012345.1234567"),
        "TOTAL_LIABILITIES": Decimal("234567890123.45009"),
        "TOTAL_EQUITY": Decimal("987654321.875"),
    }[field]
    observation = NativeFinancialMetricObservation.from_raw_value(
        contract=contract,
        raw_value=parser_value,
        source_field=field,
        body_sha256=hashlib.sha256(selected_body).hexdigest(),
        native_row_id=_row_id(selected_body),
    )
    reference = _reference(selected_body)
    fact = FinancialFact(
        asset_code=_ASSET,
        period_end=_PERIOD,
        period_type=_period_type_from_period_end(_PERIOD),
        metric_code=contract.metric_code,
        value=Decimal(observation.canonical_value),
        unit=contract.canonical_unit,
        source=contract.provider,
        fetched_at=fetched_at,
        source_evidence=FinancialFactSourceEvidence(
            source_record_id=observation.native_row_id,
            raw_payload_hash=reference.body_sha256,
        ),
        decision_evidence=FinancialFactDecisionEvidence(
            artifact_reference=reference,
            native_asset_code=_ASSET,
            native_period_end=_PERIOD,
            native_row_id=observation.native_row_id,
        ),
        numeric_schema="native-decimal-v2",
        numeric_evidence=observation,
    )
    return fact, reference


def _verifier(
    *,
    body: bytes | None = None,
    qualification: FinancialNumericSourceQualification | None = None,
    entry: FinancialNumericCatalogEntry | None = None,
    audits: list[RawAudit] | None = None,
    provider: FinancialProviderIdentity | None = None,
    parser_contract: BalanceCandidateContract | None = None,
) -> tuple[
    FinancialNumericQualificationAwareBalanceVerifier,
    _Catalog,
    _BodyRepository,
    _AuditRepository,
]:
    """Build the candidate from explicit in-memory test ports only."""

    selected_body = body or _body()
    fact_contract = _contract()
    selected_qualification = qualification or _qualification(fact_contract)
    selected_entry = entry or _entry(selected_qualification)
    fact, reference = _fact(body=selected_body)
    audit_repo = _AuditRepository(
        audits if audits is not None else [_audit(reference, parser_contract=parser_contract)]
    )
    body_repo = _BodyRepository(selected_body)
    provider_resolver = _ProviderResolver(provider)
    body_reader = BalanceNumericOriginalBodyReader(
        artifact_repository=body_repo,
        audit_repository=audit_repo,
        provider_identity_resolver=provider_resolver,
    )
    verifier = FinancialNumericQualificationAwareBalanceVerifier(
        _Catalog(selected_entry),
        body_reader,
        parser_contract or _parser_contract(),
    )
    return verifier, verifier._catalog, body_repo, audit_repo


def test_balance_decimal_claim_replays_through_exact_endpoint_and_typed_catalog() -> None:
    """The synthetic path sends actual row context and both explicit clocks."""

    body = _body()
    fact, reference = _fact(body=body)
    qualification = _qualification(fact.numeric_evidence.contract)
    entry = _entry(qualification)
    audit_repo = _AuditRepository([_audit(reference)])
    body_repo = _BodyRepository(body)
    reader = BalanceNumericOriginalBodyReader(
        artifact_repository=body_repo,
        audit_repository=audit_repo,
        provider_identity_resolver=_ProviderResolver(),
    )
    catalog = _Catalog(entry)
    verifier = FinancialNumericQualificationAwareBalanceVerifier(
        catalog,
        reader,
        _parser_contract(),
    )
    context = FinancialNumericVerificationContext(
        known_at=_KNOWN_AT,
        purpose=FinancialNumericVerificationPurpose.POINT_IN_TIME_READ,
    )

    assert verifier.verify(fact, context) is True
    assert len(body_repo.reads) == 1
    assert len(audit_repo.reads) == 1
    assert catalog.calls == [
        {
            "contract_identity": fact.numeric_evidence.contract_identity,
            "endpoint": AKSHARE_BALANCE_FINANCIAL_DATA_ENDPOINT,
            "source_response_completed_at": _RESPONSE_AT,
            "source_context": {
                "SECURITY_CODE": "000858",
                "REPORT_DATE": "2026-09-30 00:00:00",
                "NOTICE_DATE": "2026-10-25 00:00:00",
                "TOTAL_ASSETS": Decimal("123456789012345.1234567"),
                "TOTAL_LIABILITIES": Decimal("234567890123.45009"),
                "TOTAL_EQUITY": Decimal("987654321.875"),
            },
            "known_at": _KNOWN_AT,
            "purpose": FinancialNumericVerificationPurpose.POINT_IN_TIME_READ,
        }
    ]
    assert fact.numeric_evidence.canonical_value == "123456789012345.1234567"
    assert type(fact.value) is Decimal


def test_complete_raw_context_preserves_unconfigured_fields_and_exact_json_types() -> None:
    """Catalog sees every row value, while no currency or scope is invented."""

    body = (
        b'{"success":true,"code":0,"result":{"count":1,"pages":1,"data":['
        b'{"SECURITY_CODE":"000858","REPORT_DATE":"2026-09-30 00:00:00",'
        b'"NOTICE_DATE":"2026-10-25 00:00:00","CURRENCY":"SYNTH-CURRENCY",'
        b'"CONSOLIDATED":false,"SYNTHETIC_COUNT":7,'
        b'"SYNTHETIC_NESTED":{"label":"raw-text","amount":1.2300},'
        b'"TOTAL_ASSETS":123456789012345.1234567,'
        b'"TOTAL_LIABILITIES":234567890123.45009,"TOTAL_EQUITY":987654321.875}]}}'
    )
    parser_contract = _parser_contract(
        base_filter_terms=('(CALLER_SUPPLIED_FILTER="synthetic-only")',)
    )
    contract = _contract()
    qualification = _qualification(
        contract,
        context_requirements=(
            FinancialNumericSourceContextRequirement("CURRENCY", "SYNTH-CURRENCY"),
            FinancialNumericSourceContextRequirement("CONSOLIDATED", False),
        ),
    )
    verifier, catalog, _, _ = _verifier(
        body=body,
        qualification=qualification,
        parser_contract=parser_contract,
    )
    context = FinancialNumericVerificationContext(
        known_at=_KNOWN_AT,
        purpose=FinancialNumericVerificationPurpose.POINT_IN_TIME_READ,
    )

    assert verifier.verify(_fact(body=body)[0], context) is True
    source_context = catalog.calls[0]["source_context"]
    assert isinstance(source_context, Mapping)
    assert source_context["CURRENCY"] == "SYNTH-CURRENCY"
    assert source_context["CONSOLIDATED"] is False
    assert source_context["SYNTHETIC_COUNT"] == 7
    assert type(source_context["TOTAL_ASSETS"]) is Decimal
    assert source_context["TOTAL_ASSETS"].as_tuple().exponent == -7
    nested = source_context["SYNTHETIC_NESTED"]
    assert isinstance(nested, Mapping)
    assert nested["label"] == "raw-text"
    assert type(nested["amount"]) is Decimal
    assert nested["amount"].as_tuple().exponent == -4
    with pytest.raises(TypeError):
        source_context["CURRENCY"] = "INVENTED"


def test_integrated_parser_preserves_the_original_six_field_projection_hash() -> None:
    """The new full context is additive; the selected projection remains byte-stable."""

    candidate_contract = _parser_contract()
    candidate_request = BalanceCandidateRequest(
        symbol=_ASSET,
        security_code=_ASSET[:6],
        report_date=_PERIOD,
    )
    raw_body = _body()
    candidate_result = parse_balance_candidate_body(
        raw_body,
        request=candidate_request,
        contract=candidate_contract,
    )

    assert candidate_result.outcome == "candidate_parsed"
    # Frozen before the additive raw-context change; see the acceptance index.
    assert tuple(
        (field.raw_key, field.raw_value_text) for field in candidate_result.raw_row_projection
    ) == (
        ("SECURITY_CODE", "000858"),
        ("REPORT_DATE", "2026-09-30 00:00:00"),
        ("NOTICE_DATE", "2026-10-25 00:00:00"),
        ("TOTAL_ASSETS", "123456789012345.1234567"),
        ("TOTAL_LIABILITIES", "234567890123.45009"),
        ("TOTAL_EQUITY", "987654321.875"),
    )
    assert candidate_result.row_projection_sha256 == (
        "9d65cccd5be2ce69b20d6fd2da615ac258990d9647cf519c2e443a1fec0e7b2f"
    )
    assert candidate_result.raw_row_context["REPORT_DATE"] == "2026-09-30 00:00:00"
    assert candidate_result.raw_row_context["TOTAL_ASSETS"] == Decimal("123456789012345.1234567")


def test_caller_filter_terms_must_match_exact_audited_request_parameters() -> None:
    """Configurable filters pass only when the RawAudit records the same query."""

    body = _body()
    fact, reference = _fact(body=body)
    parser_contract = _parser_contract(
        base_filter_terms=('(CALLER_SUPPLIED_FILTER="synthetic-only")',)
    )
    qualification = _qualification(fact.numeric_evidence.contract)
    verifier, catalog, _, _ = _verifier(
        body=body,
        qualification=qualification,
        parser_contract=parser_contract,
        audits=[_audit(reference, parser_contract=_parser_contract())],
    )
    context = FinancialNumericVerificationContext(
        known_at=_KNOWN_AT,
        purpose=FinancialNumericVerificationPurpose.POINT_IN_TIME_READ,
    )

    assert verifier.verify(fact, context) is False
    assert catalog.calls == []


def test_catalog_absence_or_unknown_row_context_stays_blocked() -> None:
    """No catalog entry or absent row context such as currency cannot pass."""

    fact, reference = _fact()
    body = _body()
    audit_repo = _AuditRepository([_audit(reference)])
    body_repo = _BodyRepository(body)
    reader = BalanceNumericOriginalBodyReader(
        artifact_repository=body_repo,
        audit_repository=audit_repo,
        provider_identity_resolver=_ProviderResolver(),
    )
    absent_catalog = _Catalog(None)
    verifier = FinancialNumericQualificationAwareBalanceVerifier(
        absent_catalog,
        reader,
        _parser_contract(),
    )
    context = FinancialNumericVerificationContext(
        known_at=_KNOWN_AT,
        purpose=FinancialNumericVerificationPurpose.CURRENT_READ,
    )
    assert verifier.verify(fact, context) is False

    qualification = _qualification(
        fact.numeric_evidence.contract,
        context_requirements=(FinancialNumericSourceContextRequirement("CURRENCY", "CNY"),),
    )
    missing_context_verifier, _, _, _ = _verifier(qualification=qualification)
    assert missing_context_verifier.verify(fact, context) is False


def test_source_response_and_knowledge_clocks_are_separate() -> None:
    """Future response, unapproved-at-cutoff, and revoked-at-cutoff values block."""

    fact, reference = _fact()
    body = _body()
    reader = BalanceNumericOriginalBodyReader(
        artifact_repository=_BodyRepository(body),
        audit_repository=_AuditRepository([_audit(reference)]),
        provider_identity_resolver=_ProviderResolver(),
    )
    qualification = _qualification(fact.numeric_evidence.contract)
    resolver = _Catalog(_entry(qualification, approved_at=_KNOWN_AT + timedelta(days=1)))
    verifier = FinancialNumericQualificationAwareBalanceVerifier(
        resolver,
        reader,
        _parser_contract(),
    )
    cutoff = FinancialNumericVerificationContext(
        known_at=_KNOWN_AT,
        purpose=FinancialNumericVerificationPurpose.POINT_IN_TIME_READ,
    )
    assert verifier.verify(fact, cutoff) is False
    assert resolver.calls[0]["source_response_completed_at"] == _RESPONSE_AT
    assert resolver.calls[0]["known_at"] == _KNOWN_AT

    future_fact, _ = _fact(fetched_at=_RESPONSE_AT - timedelta(seconds=1))
    assert verifier.verify(future_fact, cutoff) is False


def test_current_known_at_honors_revoke_while_earlier_pit_remains_as_of() -> None:
    """A persisted revoke blocks current resolution but not a prior PIT cutoff."""

    fact, reference = _fact()
    revoked_at = datetime(2026, 11, 4, 10, 0, tzinfo=UTC)
    qualification = _qualification(fact.numeric_evidence.contract)
    entry = _entry(qualification, revoked_at=revoked_at)
    body = _body()
    reader = BalanceNumericOriginalBodyReader(
        artifact_repository=_BodyRepository(body),
        audit_repository=_AuditRepository([_audit(reference)]),
        provider_identity_resolver=_ProviderResolver(),
    )
    verifier = FinancialNumericQualificationAwareBalanceVerifier(
        _Catalog(entry), reader, _parser_contract()
    )
    current = FinancialNumericVerificationContext(
        known_at=_KNOWN_AT,
        purpose=FinancialNumericVerificationPurpose.CURRENT_READ,
    )
    historical = FinancialNumericVerificationContext(
        known_at=datetime(2026, 11, 4, 9, 59, tzinfo=UTC),
        purpose=FinancialNumericVerificationPurpose.POINT_IN_TIME_READ,
    )

    assert verifier.verify(fact, current) is False
    assert verifier.verify(fact, historical) is True


def test_audited_endpoint_and_report_name_are_exact_and_body_is_read_once() -> None:
    """An endpoint alias or mismatched report name cannot enter Balance replay."""

    body = _body()
    fact, reference = _fact(body=body)
    provider = _ProviderResolver()
    main_audit = _audit(reference, endpoint=AKSHARE_MAIN_FINANCIAL_DATA_ENDPOINT)
    balance_body_repo = _BodyRepository(body)
    balance_reader = BalanceNumericOriginalBodyReader(
        artifact_repository=balance_body_repo,
        audit_repository=_AuditRepository([main_audit]),
        provider_identity_resolver=provider,
    )
    with pytest.raises(BalanceNumericEvidenceVerificationError):
        balance_reader.read_verified_response(reference)
    assert balance_body_repo.reads == []

    wrong_name = _audit(reference)
    wrong_name_params = dict(wrong_name.request_params)
    wrong_name_params["reportName"] = "RPT_F10_FINANCE_MAINFINADATA"
    wrong_name = replace(wrong_name, request_params=wrong_name_params)
    wrong_name = replace(wrong_name, content_hash=raw_audit_content_hash(wrong_name))
    reader = BalanceNumericOriginalBodyReader(
        artifact_repository=balance_body_repo,
        audit_repository=_AuditRepository([wrong_name]),
        provider_identity_resolver=provider,
    )
    with pytest.raises(BalanceNumericEvidenceVerificationError):
        reader.read_verified_response(reference)
    assert balance_body_repo.reads == []


def test_provider_source_type_drift_blocks_but_inactive_unchanged_identity_reads() -> None:
    """Historical body access needs the stable source identity, not active state."""

    body = _body()
    reference = _reference(body)
    audit_repo = _AuditRepository([_audit(reference)])
    body_repo = _BodyRepository(body)
    reader = BalanceNumericOriginalBodyReader(
        artifact_repository=body_repo,
        audit_repository=audit_repo,
        provider_identity_resolver=_ProviderResolver(
            FinancialProviderIdentity(
                provider_id=_PROVIDER_ID,
                name="synthetic_akshare",
                source_type="akshare",
                is_active=False,
            )
        ),
    )
    assert reader.read_verified_response(reference).body == body
    assert len(body_repo.reads) == 1

    drifted = BalanceNumericOriginalBodyReader(
        artifact_repository=_BodyRepository(body),
        audit_repository=_AuditRepository([_audit(reference)]),
        provider_identity_resolver=_ProviderResolver(
            FinancialProviderIdentity(
                provider_id=_PROVIDER_ID,
                name="synthetic_akshare",
                source_type="other-provider",
                is_active=True,
            )
        ),
    )
    with pytest.raises(BalanceNumericEvidenceVerificationError):
        drifted.read_verified_response(reference)


class _VerifierSpy:
    """Record dispatch to one endpoint-specific verifier."""

    def __init__(self, result: bool) -> None:
        """Set the synthetic verifier result."""

        self.result = result
        self.calls: list[tuple[FinancialFact, FinancialNumericVerificationContext]] = []

    def verify(self, fact: FinancialFact, context: FinancialNumericVerificationContext) -> bool:
        """Record the target and return the configured test value."""

        self.calls.append((fact, context))
        return self.result


def test_dispatch_uses_the_verified_audit_endpoint_and_rejects_unknown_route() -> None:
    """The dispatch decision is not taken from fact.extra or metric labels."""

    body = _body()
    fact, reference = _fact(body=body)
    context = FinancialNumericVerificationContext(
        known_at=_KNOWN_AT,
        purpose=FinancialNumericVerificationPurpose.CURRENT_READ,
    )
    route_reader = BalanceNumericEndpointRouteResolver(
        _AuditRepository([_audit(reference)]),
        _ProviderResolver(),
    )
    main = _VerifierSpy(False)
    balance = _VerifierSpy(True)
    dispatcher = FinancialNumericEndpointVerifierDispatcher(
        route_reader,
        main_verifier=main,
        balance_verifier=balance,
    )
    assert dispatcher.verify(fact, context) is True
    assert main.calls == []
    assert balance.calls == [(fact, context)]

    main_routed = _VerifierSpy(True)
    balance_not_routed = _VerifierSpy(False)
    main_dispatcher = FinancialNumericEndpointVerifierDispatcher(
        BalanceNumericEndpointRouteResolver(
            _AuditRepository([_audit(reference, endpoint=AKSHARE_MAIN_FINANCIAL_DATA_ENDPOINT)]),
            _ProviderResolver(),
        ),
        main_verifier=main_routed,
        balance_verifier=balance_not_routed,
    )
    assert main_dispatcher.verify(fact, context) is True
    assert main_routed.calls == [(fact, context)]
    assert balance_not_routed.calls == []

    unknown_audit = _audit(reference, endpoint="datacenter-web.eastmoney.com/other/get")
    unknown_route = FinancialNumericEndpointVerifierDispatcher(
        BalanceNumericEndpointRouteResolver(
            _AuditRepository([unknown_audit]),
            _ProviderResolver(),
        ),
        main_verifier=main,
        balance_verifier=balance,
    )
    assert unknown_route.verify(fact, context) is False
    assert len(balance.calls) == 1


@pytest.mark.parametrize("field", ["TOTAL_LIABILITIES", "TOTAL_EQUITY"])
def test_other_native_fields_need_their_own_explicit_contract(field: str) -> None:
    """Amount3 bindings come from runtime contracts; this path derives nothing."""

    fact, reference = _fact(field=field)
    contract = fact.numeric_evidence.contract
    qualification = _qualification(contract)
    entry = _entry(qualification)
    body_repo = _BodyRepository(_body())
    reader = BalanceNumericOriginalBodyReader(
        artifact_repository=body_repo,
        audit_repository=_AuditRepository([_audit(reference)]),
        provider_identity_resolver=_ProviderResolver(),
    )
    verifier = FinancialNumericQualificationAwareBalanceVerifier(
        _Catalog(entry), reader, _parser_contract()
    )
    context = FinancialNumericVerificationContext(
        known_at=_KNOWN_AT,
        purpose=FinancialNumericVerificationPurpose.POINT_IN_TIME_READ,
    )
    assert verifier.verify(fact, context) is True
    assert fact.numeric_evidence.canonical_value == str(fact.value)


def test_duplicate_row_and_non_native_parser_contract_are_blocked() -> None:
    """A duplicate target or a Main/other parser identity cannot be dispatched."""

    duplicated = _body(
        rows=[
            {
                "SECURITY_CODE": "000858",
                "REPORT_DATE": "2026-09-30 00:00:00",
                "NOTICE_DATE": "2026-10-25 00:00:00",
                "TOTAL_ASSETS": 1,
                "TOTAL_LIABILITIES": 2,
                "TOTAL_EQUITY": 3,
            },
            {
                "SECURITY_CODE": "000858",
                "REPORT_DATE": "2026-09-30 00:00:00",
                "NOTICE_DATE": "2026-10-25 00:00:00",
                "TOTAL_ASSETS": 1,
                "TOTAL_LIABILITIES": 2,
                "TOTAL_EQUITY": 3,
            },
        ]
    )
    fact, reference = _fact(body=duplicated)
    reader = BalanceNumericOriginalBodyReader(
        artifact_repository=_BodyRepository(duplicated),
        audit_repository=_AuditRepository([_audit(reference)]),
        provider_identity_resolver=_ProviderResolver(),
    )
    qualification = _qualification(fact.numeric_evidence.contract)
    verifier = FinancialNumericQualificationAwareBalanceVerifier(
        _Catalog(_entry(qualification)), reader, _parser_contract()
    )
    context = FinancialNumericVerificationContext(
        known_at=_KNOWN_AT,
        purpose=FinancialNumericVerificationPurpose.CURRENT_READ,
    )
    assert verifier.verify(fact, context) is False

    main_contract = replace(
        _parser_contract(),
        report_name="RPT_F10_FINANCE_MAINFINADATA",
    )
    with pytest.raises(ValueError):
        FinancialNumericQualificationAwareBalanceVerifier(
            _Catalog(_entry(qualification)), reader, main_contract
        )
