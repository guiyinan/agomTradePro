"""Strict retained-body replay for exact native financial numeric evidence."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from uuid import UUID

import pytest
from cryptography.fernet import Fernet
from django.db import DatabaseError

from apps.data_center.application.financial_numeric_verification import (
    FinancialProviderIdentity,
)
from apps.data_center.domain.entities import FinancialFact, RawAudit, raw_audit_content_hash
from apps.data_center.domain.enums import FinancialPeriodType
from apps.data_center.domain.financial_numeric_evidence import (
    FinancialMetricSourceContract,
    NativeFinancialMetricObservation,
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
    FinancialFactDecisionEvidence,
    FinancialFactSourceEvidence,
)
from apps.data_center.infrastructure import financial_native_numeric_verifier as verifier_module
from apps.data_center.infrastructure._provider_adapter_base import (
    _period_type_from_period_end,
)
from apps.data_center.infrastructure.financial_native_numeric_verifier import (
    DjangoFinancialNativeProviderIdentityResolver,
    FinancialNativeNumericEvidenceVerifier,
    FinancialNativeRawBodyReader,
    FinancialNumericEvidenceVerificationError,
    build_django_financial_native_numeric_verifier,
)
from apps.data_center.infrastructure.financial_source_time_matchers import (
    AKSHARE_MAIN_FINANCIAL_DATA_ENDPOINT,
)

BODY = (
    b'{"success":true,"code":0,"result":{"count":1,"data":['
    b'{"SECUCODE":"000001.SZ","REPORT_DATE":"2026-06-30",'
    b'"NOTICE_DATE":"2026-08-15","RAW_METRIC":123.456789012345} ]}}'
)
ASSET = "000001.SZ"
PERIOD = date(2026, 6, 30)
ANNOUNCED = datetime(2026, 8, 15, 1, 0, tzinfo=UTC)
FETCHED = datetime(2026, 9, 13, 4, 5, 6, tzinfo=UTC)
CAPTURE_ID = UUID("20000000-0000-4000-8000-000000000001")
PROVIDER_ID = 37
ROW_ID = "akshare:000001.SZ:2026-06-30:2026-08-15"


def _contract(**changes: object) -> FinancialMetricSourceContract:
    """Return a test-only explicit metric contract without business defaults."""

    values: dict[str, object] = {
        "provider": "akshare",
        "dataset_key": "equity.financial.fact",
        "metric_code": "synthetic_metric",
        "source_field": "RAW_METRIC",
        "source_unit": "source_test_unit",
        "canonical_unit": "canonical_test_unit",
        "scale_numerator": 1,
        "scale_denominator": 1,
        "contract_version": "unit.test.v1",
        "origin": "native",
    }
    values.update(changes)
    return FinancialMetricSourceContract(**values)  # type: ignore[arg-type]


def _observation(
    *,
    body: bytes = BODY,
    contract: FinancialMetricSourceContract | None = None,
    native_row_id: str = ROW_ID,
    raw_value: object = Decimal("123.456789012345"),
) -> NativeFinancialMetricObservation:
    """Build one exact observation associated with the bytes under test."""

    selected = contract or _contract()
    from hashlib import sha256

    return NativeFinancialMetricObservation.from_raw_value(
        contract=selected,
        raw_value=raw_value,
        source_field=selected.source_field,
        body_sha256=sha256(body).hexdigest(),
        native_row_id=native_row_id,
    )


def _reference(
    body: bytes = BODY,
    *,
    row_count: int = 1,
    asset_code: str = ASSET,
    period_end: date = PERIOD,
    dataset_key: str = "equity.financial.fact",
    provider_name: str = "akshare",
    response_completed_at: datetime = FETCHED,
    response_scope_basis: FinancialResponseScopeBasis = (
        FinancialResponseScopeBasis.PROVIDER_BODY_VERIFIED
    ),
) -> FinancialResponseArtifactRef:
    """Build a body-hash-bound reference for the synthetic AKShare response."""

    from hashlib import sha256

    evidence = FinancialResponseEvidence(
        body_sha256=sha256(body).hexdigest(),
        body_size_bytes=len(body),
        response_completed_at=response_completed_at,
        request_scope=FinancialRequestScope(
            provider_name=provider_name,
            dataset_key=dataset_key,
            asset_code=asset_code,
            period_limit=2,
        ),
        response_scope=FinancialResponseScope(
            asset_codes=(asset_code,),
            period_ends=(period_end,),
            row_count=row_count,
        ),
        body_scope=FinancialResponseBodyScope.BATCH,
        response_scope_basis=response_scope_basis,
    )
    return FinancialResponseArtifactRef(
        capture_id=CAPTURE_ID,
        location=f"financial-response:///v1/{CAPTURE_ID}.frb",
        evidence=evidence,
        format_version="financial-response-body-fernet-v1",
        encryption_algorithm="fernet-aes128cbc-hmacsha256",
        encryption_key_ref="config_center.data02.unit-test-key",
        encryption_key_version="test-v1",
    )


def _audit(reference: FinancialResponseArtifactRef, *, provider_id: int = PROVIDER_ID) -> RawAudit:
    """Bind the exact retained reference into one canonical financial audit."""

    audit = RawAudit(
        provider_name=reference.evidence.request_scope.provider_name,
        capability="financial",
        request_params={"endpoint": AKSHARE_MAIN_FINANCIAL_DATA_ENDPOINT, "method": "GET"},
        status="ok",
        row_count=reference.evidence.response_scope.row_count,
        fetched_at=reference.evidence.response_completed_at,
        extra={
            "financial_response_artifact": {
                "schema": "financial-response-artifact-link.v1",
                **reference.to_dict(),
                "provider_id": provider_id,
            }
        },
        response_payload_hash=reference.body_sha256,
        redacted=True,
        parser_version="financial-response-artifact.v1",
        payload_size_bytes=reference.body_size_bytes,
    )
    return replace(audit, content_hash=raw_audit_content_hash(audit))


def _fact(
    *,
    body: bytes = BODY,
    contract: FinancialMetricSourceContract | None = None,
    native_row_id: str = ROW_ID,
    raw_value: object = Decimal("123.456789012345"),
    field_name: str | None = None,
    row_count: int = 1,
    asset_code: str = ASSET,
    period_end: date = PERIOD,
    provider_name: str = "akshare",
    fetched_at: datetime = FETCHED,
    response_completed_at: datetime = FETCHED,
) -> FinancialFact:
    """Create one exact v2 fact with a consistent typed body/row binding."""

    from hashlib import sha256

    selected_contract = contract or _contract()
    observation = NativeFinancialMetricObservation.from_raw_value(
        contract=selected_contract,
        raw_value=raw_value,
        source_field=field_name or selected_contract.source_field,
        body_sha256=sha256(body).hexdigest(),
        native_row_id=native_row_id,
    )
    reference = _reference(
        body,
        row_count=row_count,
        asset_code=asset_code,
        period_end=period_end,
        provider_name=provider_name,
        response_completed_at=response_completed_at,
    )
    return FinancialFact(
        asset_code=asset_code,
        period_end=period_end,
        period_type=_period_type_from_period_end(period_end),
        metric_code=selected_contract.metric_code,
        value=Decimal(observation.canonical_value),
        unit=selected_contract.canonical_unit,
        source=selected_contract.provider,
        fetched_at=fetched_at,
        source_evidence=FinancialFactSourceEvidence(
            announced_at=ANNOUNCED,
            source_record_id=native_row_id,
            raw_payload_hash=reference.body_sha256,
        ),
        decision_evidence=FinancialFactDecisionEvidence(
            artifact_reference=reference,
            native_asset_code=asset_code,
            native_period_end=period_end,
            native_row_id=native_row_id,
        ),
        numeric_schema="native-decimal-v2",
        numeric_evidence=observation,
    )


class _ArtifactRepository:
    def __init__(self, body: bytes = BODY) -> None:
        self.body = body
        self.reads: list[FinancialResponseArtifactRef] = []

    def read(self, reference: FinancialResponseArtifactRef) -> bytes:
        self.reads.append(reference)
        return self.body


class _AuditRepository:
    def __init__(self, audits: list[RawAudit]) -> None:
        self.audits = audits
        self.capture_ids: list[UUID] = []

    def list_by_artifact_capture_id(self, capture_id: UUID) -> list[RawAudit]:
        self.capture_ids.append(capture_id)
        return self.audits


class _ProviderResolver:
    def __init__(self, identity: FinancialProviderIdentity | None) -> None:
        self.identity = identity
        self.provider_ids: list[int] = []

    def resolve_by_id(self, provider_id: int) -> FinancialProviderIdentity | None:
        self.provider_ids.append(provider_id)
        return self.identity


class _CatalogResolver:
    def __init__(self, contract: FinancialMetricSourceContract | None) -> None:
        self.contract = contract
        self.calls: list[tuple[str, datetime]] = []

    def resolve_exact(
        self,
        identity: str,
        *,
        known_at: datetime,
    ) -> FinancialMetricSourceContract | None:
        self.calls.append((identity, known_at))
        return self.contract


def _reader(
    *,
    body: bytes = BODY,
    reference: FinancialResponseArtifactRef | None = None,
    audits: list[RawAudit] | None = None,
    provider: FinancialProviderIdentity | None = None,
    include_provider: bool = True,
) -> tuple[FinancialNativeRawBodyReader, _ArtifactRepository, _ProviderResolver]:
    """Build the real audit/provider-checking reader around in-memory ports."""

    selected_reference = reference or _reference(body)
    audit_rows = audits if audits is not None else [_audit(selected_reference)]
    artifacts = _ArtifactRepository(body)
    providers = _ProviderResolver(provider if include_provider else None)
    if include_provider and provider is None:
        providers = _ProviderResolver(
            FinancialProviderIdentity(
                provider_id=PROVIDER_ID,
                name="akshare_primary",
                source_type="akshare",
                is_active=True,
            )
        )
    return (
        FinancialNativeRawBodyReader(
            artifact_repository=artifacts,
            audit_repository=_AuditRepository(audit_rows),
            provider_identity_resolver=providers,
        ),
        artifacts,
        providers,
    )


def _verifier(
    *,
    body: bytes = BODY,
    catalog_contract: FinancialMetricSourceContract | None = None,
    audits: list[RawAudit] | None = None,
    provider: FinancialProviderIdentity | None = None,
    include_provider: bool = True,
) -> tuple[FinancialNativeNumericEvidenceVerifier, _CatalogResolver, _ArtifactRepository]:
    """Build the verifier using only in-memory catalog and retention ports."""

    selected = catalog_contract or _contract()
    reader, artifacts, _ = _reader(
        body=body,
        audits=audits,
        provider=provider,
        include_provider=include_provider,
    )
    catalog = _CatalogResolver(selected)
    return FinancialNativeNumericEvidenceVerifier(catalog, reader), catalog, artifacts


def test_exact_contract_and_retained_body_are_replayed_at_fact_knowledge_time() -> None:
    """The verifier queries the catalog and proves the claim against exact bytes."""

    fact = _fact()
    verifier, catalog, artifacts = _verifier()

    assert fact.period_type is FinancialPeriodType.SEMI_ANNUAL
    assert verifier(fact) is True
    assert catalog.calls == [(fact.numeric_evidence.contract.identity, fact.fetched_at)]
    assert len(artifacts.reads) == 1


def test_missing_catalog_contract_fails_closed_after_exact_resolution_attempt() -> None:
    """An embedded self-reported contract never substitutes for the catalog."""

    fact = _fact()
    verifier, catalog, artifacts = _verifier(catalog_contract=None)
    catalog.contract = None

    assert verifier(fact) is False
    assert catalog.calls == [(fact.numeric_evidence.contract.identity, fact.fetched_at)]
    assert artifacts.reads == []


def test_catalog_contract_must_match_full_versioned_identity_and_units() -> None:
    """A catalog row with any changed interpretation cannot authorize the claim."""

    contract = _contract()
    fact = _fact(contract=contract)
    mismatches = [
        replace(contract, provider="other_provider"),
        replace(contract, source_field="OTHER_FIELD"),
        replace(contract, source_unit="other_source_unit"),
        replace(contract, canonical_unit="other_canonical_unit"),
        replace(contract, scale_numerator=2),
        replace(contract, contract_version="unit.test.v2"),
    ]
    for mismatch in mismatches:
        verifier, _, artifacts = _verifier(catalog_contract=mismatch)
        assert verifier(fact) is False
        assert artifacts.reads == []


def test_body_value_must_recompute_exact_observation_and_decimal_fact() -> None:
    """Sidecar text cannot override a different exact number in retained bytes."""

    fact = _fact(raw_value=Decimal("999.123456789012"))
    verifier, _, artifacts = _verifier()

    assert verifier(fact) is False
    assert len(artifacts.reads) == 1


def test_raw_field_must_exist_and_be_an_exact_decimal_in_the_native_row() -> None:
    """Missing fields fail while a provider's exact decimal text remains exact."""

    missing_contract = _contract(source_field="UNDECLARED_FIELD")
    missing_fact = _fact(contract=missing_contract)
    missing_verifier, _, _ = _verifier(catalog_contract=missing_contract)
    assert missing_verifier(missing_fact) is False

    string_body = BODY.replace(b"123.456789012345", b'"123.456789012345"')
    string_fact = _fact(body=string_body)
    string_verifier, _, _ = _verifier(body=string_body)
    assert string_verifier(string_fact) is True


def test_fact_identity_and_row_identity_must_match_unique_native_row() -> None:
    """A correct value from another row, asset, or period is not this fact."""

    wrong_row = "akshare:000001.SZ:2026-06-30:2026-08-14"
    fact = _fact(native_row_id=wrong_row)
    verifier, _, _ = _verifier()
    assert verifier(fact) is False

    wrong_asset = _fact(asset_code="000002.SZ")
    verifier, _, _ = _verifier()
    assert verifier(wrong_asset) is False

    wrong_period = _fact(period_end=date(2026, 3, 31))
    verifier, _, _ = _verifier(audits=[_audit(wrong_period.decision_evidence.artifact_reference)])
    assert verifier(wrong_period) is False


@pytest.mark.parametrize(
    "period_type",
    [
        FinancialPeriodType.QUARTERLY,
        FinancialPeriodType.ANNUAL,
        FinancialPeriodType.TTM,
    ],
)
def test_fact_period_type_must_match_main_endpoint_period_interpretation(
    period_type: FinancialPeriodType,
) -> None:
    """A cumulative June report cannot be relabeled as a quarter, year, or TTM."""

    fact = replace(_fact(), period_type=period_type)
    verifier, catalog, artifacts = _verifier()

    assert verifier(fact) is False
    assert catalog.calls == []
    assert artifacts.reads == []


def test_retained_response_cannot_be_learned_after_the_fact_knowledge_time() -> None:
    """Raw-response completion must not postdate the fact's persisted fetch time."""

    response_completed_at = FETCHED + timedelta(seconds=1)
    fact = _fact(
        fetched_at=FETCHED,
        response_completed_at=response_completed_at,
    )
    verifier, catalog, artifacts = _verifier(
        audits=[_audit(fact.decision_evidence.artifact_reference)]
    )

    assert verifier(fact) is False
    assert catalog.calls == []
    assert artifacts.reads == []


def test_duplicate_native_row_identity_is_rejected() -> None:
    """Two body rows with the same composite identity are ambiguous evidence."""

    row = (
        b'{"SECUCODE":"000001.SZ","REPORT_DATE":"2026-06-30",'
        b'"NOTICE_DATE":"2026-08-15","RAW_METRIC":123.456789012345}'
    )
    body = b'{"success":true,"code":0,"result":{"count":2,"data":[' + row + b"," + row + b"]}}"
    fact = _fact(body=body, row_count=2)
    reference = _reference(body, row_count=2)
    verifier, _, _ = _verifier(body=body, audits=[_audit(reference)])

    assert verifier(fact) is False


def test_response_scope_row_count_must_match_the_raw_provider_envelope() -> None:
    """A body whose envelope row count differs from its retained scope is blocked."""

    fact = _fact(row_count=2)
    reference = fact.decision_evidence.artifact_reference
    verifier, _, _ = _verifier(audits=[_audit(reference)])
    assert verifier(fact) is False


def test_body_hash_and_size_are_verified_against_replayed_artifact() -> None:
    """A reader cannot claim the expected reference while returning changed bytes."""

    tampered = BODY.replace(b"123.456789012345", b"123.456789012346")
    fact = _fact()
    reference = _reference(BODY)
    reader, artifacts, _ = _reader(body=BODY, audits=[_audit(reference)])
    artifacts.body = tampered

    verifier = FinancialNativeNumericEvidenceVerifier(_CatalogResolver(_contract()), reader)
    assert verifier(fact) is False


@pytest.mark.parametrize(
    "identity",
    [
        None,
        FinancialProviderIdentity(PROVIDER_ID, "akshare_primary", "tushare", True),
        FinancialProviderIdentity(PROVIDER_ID + 1, "akshare_primary", "akshare", True),
        FinancialProviderIdentity(PROVIDER_ID, "akshare", "replaced_source", True),
    ],
)
def test_provider_identity_must_match_audit_source_type_and_id(
    identity: FinancialProviderIdentity | None,
) -> None:
    """A provider id/name cannot override a changed or missing logical source type."""

    fact = _fact()
    verifier, _, _ = _verifier(provider=identity, include_provider=identity is not None)
    if identity is None:
        verifier, _, _ = _verifier(include_provider=False)
    assert verifier(fact) is False


def test_inactive_provider_with_unchanged_identity_remains_readable_for_history() -> None:
    """Current activation cannot rewrite whether a retained historical body verifies."""

    fact = _fact()
    provider = FinancialProviderIdentity(
        PROVIDER_ID,
        "akshare_primary",
        "akshare",
        False,
    )
    verifier, _, _ = _verifier(provider=provider)
    assert verifier(fact) is True


def test_source_type_drift_cannot_rebind_a_historical_provider_id() -> None:
    """The persisted provider id must still identify the audited logical source."""

    fact = _fact()
    provider = FinancialProviderIdentity(
        PROVIDER_ID,
        "akshare_primary",
        "other_source",
        True,
    )
    verifier, _, _ = _verifier(provider=provider)
    assert verifier(fact) is False


def test_non_akshare_provider_remains_blocked_until_its_body_parser_exists() -> None:
    """Provider-specific raw shapes are never parsed with an unrelated parser."""

    contract = _contract(provider="tushare")
    fact = _fact(contract=contract, provider_name="tushare")
    verifier, catalog, artifacts = _verifier(catalog_contract=contract)

    assert verifier(fact) is False
    assert catalog.calls == [(contract.identity, fact.fetched_at)]
    assert artifacts.reads == []


def test_ambiguous_or_mismatched_raw_audit_fails_closed() -> None:
    """Only one complete matching successful RawAudit can authorize body replay."""

    reference = _reference()
    correct = _audit(reference)
    verifier, _, _ = _verifier(audits=[correct, correct])
    assert verifier(_fact()) is False

    wrong_hash_audit = replace(correct, response_payload_hash="f" * 64)
    verifier, _, _ = _verifier(audits=[wrong_hash_audit])
    assert verifier(_fact()) is False

    unredacted = replace(correct, redacted=False)
    unredacted = replace(unredacted, content_hash=raw_audit_content_hash(unredacted))
    verifier, _, _ = _verifier(audits=[unredacted])
    assert verifier(_fact()) is False


def test_unverified_or_legacy_numeric_fact_is_rejected() -> None:
    """Only a v2 exact Decimal fact with typed native evidence enters replay."""

    legacy = FinancialFact(
        asset_code=ASSET,
        period_end=PERIOD,
        period_type=FinancialPeriodType.QUARTERLY,
        metric_code="synthetic_metric",
        value=123.45,
        source="akshare",
    )
    verifier, _, _ = _verifier()
    assert verifier(legacy) is False

    missing_source = replace(_fact(), source_evidence=None)
    assert verifier(missing_source) is False

    missing_decision = replace(_fact(), decision_evidence=None)
    assert verifier(missing_decision) is False


def test_naive_fact_knowledge_time_is_rejected_before_catalog_lookup() -> None:
    """An exact catalog resolution cannot use an ambiguous local timestamp."""

    fact = replace(_fact(), fetched_at=datetime(2026, 9, 13, 4, 5, 6))
    verifier, catalog, _ = _verifier()
    assert verifier(fact) is False
    assert catalog.calls == []


def test_derived_metric_contract_is_outside_native_verification() -> None:
    """The source contract type itself refuses implicit derived interpretation."""

    with pytest.raises(ValueError, match="native"):
        _contract(origin="derived")


def test_raw_body_reader_rejects_audit_reference_mismatch_with_stable_error() -> None:
    """RawAudit link corruption is reported as a stable business block."""

    reference = _reference()
    corrupt_link = _audit(reference)
    corrupt_extra = dict(corrupt_link.extra)
    link = dict(corrupt_extra["financial_response_artifact"])
    link["body_sha256"] = "f" * 64
    corrupt_extra["financial_response_artifact"] = link
    corrupt_link = replace(corrupt_link, extra=corrupt_extra)
    corrupt_link = replace(corrupt_link, content_hash=raw_audit_content_hash(corrupt_link))
    reader, _, _ = _reader(audits=[corrupt_link])

    with pytest.raises(FinancialNumericEvidenceVerificationError) as error:
        reader.read_verified_body(reference)
    assert error.value.code == "FINANCIAL_NATIVE_NUMERIC_EVIDENCE_BLOCKED"


@pytest.mark.parametrize(
    "change",
    [
        {"capability": "quote"},
        {"status": "error"},
        {"provider_name": "other_provider"},
        {"response_payload_hash": "f" * 64},
        {"payload_size_bytes": 0},
        {"row_count": 2},
        {"content_hash": ""},
    ],
)
def test_raw_body_reader_rejects_noncanonical_audit_fields(change: dict[str, object]) -> None:
    """Every stored audit dimension remains part of the body verification gate."""

    reference = _reference()
    audit = replace(_audit(reference), **change)
    reader, _, _ = _reader(reference=reference, audits=[audit])

    with pytest.raises(FinancialNumericEvidenceVerificationError):
        reader.read_verified_body(reference)


def test_raw_body_reader_requires_one_valid_provider_body_reference() -> None:
    """Caller-declared scope, wrong dataset, and malformed provider id are blocked."""

    original = _reference()
    invalid_reference_list = (
        replace(
            original,
            evidence=replace(
                original.evidence,
                request_scope=replace(
                    original.evidence.request_scope,
                    dataset_key="equity.other.dataset",
                ),
            ),
        ),
        replace(
            original,
            evidence=replace(
                original.evidence,
                response_scope_basis=FinancialResponseScopeBasis.CALLER_DECLARED,
            ),
        ),
    )
    for invalid_reference in invalid_reference_list:
        reader, _, _ = _reader(reference=invalid_reference)
        with pytest.raises(FinancialNumericEvidenceVerificationError):
            reader.read_verified_body(invalid_reference)

    reference = _reference()
    audit = _audit(reference)
    extra = dict(audit.extra)
    link = dict(extra["financial_response_artifact"])
    link["provider_id"] = True
    extra["financial_response_artifact"] = link
    malformed = replace(audit, extra=extra)
    malformed = replace(malformed, content_hash=raw_audit_content_hash(malformed))
    reader, _, _ = _reader(reference=reference, audits=[malformed])
    with pytest.raises(FinancialNumericEvidenceVerificationError):
        reader.read_verified_body(reference)


def test_raw_body_reader_requires_exact_owner_approved_endpoint() -> None:
    """Missing, sibling, and near-match endpoints cannot share the approved parser."""

    reference = _reference()
    audit = _audit(reference)
    wrong_endpoints = (
        {"method": "GET"},
        {"endpoint": f"{AKSHARE_MAIN_FINANCIAL_DATA_ENDPOINT}_sibling"},
        {"endpoint": AKSHARE_MAIN_FINANCIAL_DATA_ENDPOINT.replace("MAINFINADATA", "MAINFINANCE")},
    )
    for request_params in wrong_endpoints:
        invalid = replace(audit, request_params=request_params)
        invalid = replace(invalid, content_hash=raw_audit_content_hash(invalid))
        reader, artifacts, _ = _reader(reference=reference, audits=[invalid])

        with pytest.raises(FinancialNumericEvidenceVerificationError):
            reader.read_verified_body(reference)
        assert artifacts.reads == []


def test_raw_body_reader_converts_database_lookup_failures_to_stable_blocks() -> None:
    """Audit and provider database failures cannot be mistaken for valid evidence."""

    class _FailingAuditRepository:
        def list_by_artifact_capture_id(self, _capture_id: UUID) -> list[RawAudit]:
            raise DatabaseError("isolated audit reader failure")

    class _FailingProviderResolver:
        def resolve_by_id(self, _provider_id: int) -> FinancialProviderIdentity | None:
            raise DatabaseError("isolated provider reader failure")

    reference = _reference()
    failing_audit_reader = FinancialNativeRawBodyReader(
        artifact_repository=_ArtifactRepository(),
        audit_repository=_FailingAuditRepository(),
        provider_identity_resolver=_ProviderResolver(None),
    )
    with pytest.raises(FinancialNumericEvidenceVerificationError):
        failing_audit_reader.read_verified_body(reference)

    failing_provider_reader = FinancialNativeRawBodyReader(
        artifact_repository=_ArtifactRepository(),
        audit_repository=_AuditRepository([_audit(reference)]),
        provider_identity_resolver=_FailingProviderResolver(),
    )
    with pytest.raises(FinancialNumericEvidenceVerificationError):
        failing_provider_reader.read_verified_body(reference)


@pytest.mark.parametrize("returned_body", [b"short", "not-bytes", None])
def test_raw_body_reader_rejects_wrong_body_bytes_and_types(returned_body: object) -> None:
    """Read results must be exact bytes with the stored size and digest."""

    reference = _reference()

    class _BodyRepository:
        def read(self, _reference: FinancialResponseArtifactRef) -> bytes:
            return returned_body  # type: ignore[return-value]

    reader = FinancialNativeRawBodyReader(
        artifact_repository=_BodyRepository(),
        audit_repository=_AuditRepository([_audit(reference)]),
        provider_identity_resolver=_ProviderResolver(
            FinancialProviderIdentity(PROVIDER_ID, "akshare_primary", "akshare", True)
        ),
    )
    with pytest.raises(FinancialNumericEvidenceVerificationError):
        reader.read_verified_body(reference)


def test_raw_body_reader_wraps_artifact_read_failures() -> None:
    """Missing encrypted artifacts produce the stable exact-evidence block."""

    reference = _reference()

    class _FailingArtifactRepository:
        def read(self, _reference: FinancialResponseArtifactRef) -> bytes:
            raise OSError("isolated artifact read failure")

    reader = FinancialNativeRawBodyReader(
        artifact_repository=_FailingArtifactRepository(),
        audit_repository=_AuditRepository([_audit(reference)]),
        provider_identity_resolver=_ProviderResolver(
            FinancialProviderIdentity(PROVIDER_ID, "akshare_primary", "akshare", True)
        ),
    )
    with pytest.raises(FinancialNumericEvidenceVerificationError):
        reader.read_verified_body(reference)


def test_verifier_requires_a_catalog_and_known_at_without_default_bypass() -> None:
    """Catalog identity resolution has no optional None-verifier success path."""

    fact = _fact()
    reader, _, _ = _reader()
    catalog = _CatalogResolver(_contract())
    verifier = FinancialNativeNumericEvidenceVerifier(catalog, reader)

    assert verifier(fact) is True
    assert catalog.calls[0][1] == FETCHED
    with pytest.raises(TypeError):
        FinancialNativeNumericEvidenceVerifier(None, reader)  # type: ignore[arg-type]


def test_body_reader_rejects_untyped_reference_and_missing_ports() -> None:
    """No retained-body capability can be omitted or called with a loose claim."""

    with pytest.raises(TypeError):
        FinancialNativeRawBodyReader(
            artifact_repository=None,  # type: ignore[arg-type]
            audit_repository=_AuditRepository([]),
            provider_identity_resolver=_ProviderResolver(None),
        )
    with pytest.raises(TypeError):
        FinancialNativeRawBodyReader(
            artifact_repository=_ArtifactRepository(),
            audit_repository=_AuditRepository([]),
            provider_identity_resolver=None,  # type: ignore[arg-type]
        )
    reader, _, _ = _reader()
    with pytest.raises(FinancialNumericEvidenceVerificationError):
        reader.read_verified_body(object())  # type: ignore[arg-type]


def test_django_provider_identity_resolver_reads_only_exact_nonsecret_row(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Provider identity resolution reads the configured row without credentials."""

    row = SimpleNamespace(
        pk=PROVIDER_ID,
        name="akshare_primary",
        source_type="akshare",
        is_active=False,
    )

    class _Query:
        def first(self) -> object:
            return row

    class _Manager:
        requested_ids: list[int] = []

        def filter(self, *, pk: int) -> _Query:
            self.requested_ids.append(pk)
            return _Query()

    manager = _Manager()
    monkeypatch.setattr(
        verifier_module,
        "ProviderConfigModel",
        SimpleNamespace(_default_manager=manager),
    )
    resolver = DjangoFinancialNativeProviderIdentityResolver()

    assert resolver.resolve_by_id(True) is None  # type: ignore[arg-type]
    identity = resolver.resolve_by_id(PROVIDER_ID)
    assert identity == FinancialProviderIdentity(
        provider_id=PROVIDER_ID,
        name="akshare_primary",
        source_type="akshare",
        is_active=False,
    )
    assert manager.requested_ids == [PROVIDER_ID]


def test_django_provider_identity_resolver_blocks_a_missing_row(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A stale audit provider id cannot fall through to another provider row."""

    class _Query:
        def first(self) -> None:
            return None

    class _Manager:
        def filter(self, *, pk: int) -> _Query:
            assert pk == PROVIDER_ID
            return _Query()

    monkeypatch.setattr(
        verifier_module,
        "ProviderConfigModel",
        SimpleNamespace(_default_manager=_Manager()),
    )
    assert DjangoFinancialNativeProviderIdentityResolver().resolve_by_id(PROVIDER_ID) is None


def test_django_verifier_builder_blocks_missing_retention_configuration(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """No local or plaintext fallback is created when encrypted storage is disabled."""

    monkeypatch.setattr(
        verifier_module, "resolve_financial_response_artifact_config", lambda **_: None
    )
    with pytest.raises(FinancialNumericEvidenceVerificationError) as error:
        build_django_financial_native_numeric_verifier(_CatalogResolver(None))
    assert error.value.code == "FINANCIAL_NATIVE_NUMERIC_EVIDENCE_BLOCKED"


def test_django_verifier_builder_uses_explicit_storage_without_provider_egress(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Configured storage builds only local readers and performs no provider request."""

    runtime = SimpleNamespace(
        root=tmp_path / "retained",
        encryption_key=Fernet.generate_key(),
        encryption_key_ref="config_center.data02.unit-test-key",
        encryption_key_version="test-v1",
        max_body_bytes=1024,
    )
    monkeypatch.setattr(
        verifier_module,
        "resolve_financial_response_artifact_config",
        lambda **_: runtime,
    )
    verifier = build_django_financial_native_numeric_verifier(_CatalogResolver(None))
    assert isinstance(verifier, FinancialNativeNumericEvidenceVerifier)
    assert not runtime.root.exists() or runtime.root.is_dir()
