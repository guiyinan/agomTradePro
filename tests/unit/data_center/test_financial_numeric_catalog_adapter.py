"""No-database tests for mapping resolver purposes and persisted metadata snapshots."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from typing import Literal, cast
from uuid import UUID

import pytest

from apps.data_center.application.financial_numeric_qualification import (
    FinancialNumericCatalogEntrySnapshotReadPort,
    FinancialNumericSourceQualificationResolution,
    FinancialNumericVerificationContext,
    FinancialNumericVerificationPurpose,
)
from apps.data_center.application.financial_numeric_verification import (
    FinancialNativeProviderIdentityPort,
)
from apps.data_center.domain.entities import FinancialFact, RawAudit
from apps.data_center.domain.financial_numeric_catalog import (
    FinancialNumericCatalogEntry,
    FinancialNumericCatalogOwnerEvent,
    FinancialNumericCatalogResolutionPurpose,
)
from apps.data_center.domain.financial_numeric_evidence import FinancialMetricSourceContract
from apps.data_center.domain.financial_numeric_source_qualification import (
    FinancialNumericSourceContextRequirement,
    FinancialNumericSourceDocumentCaptureReference,
    FinancialNumericSourceQualification,
)
from apps.data_center.domain.financial_response_artifact import FinancialResponseArtifactRef
from apps.data_center.infrastructure.financial_native_numeric_verifier import (
    FinancialNativeRawBodyReader,
    _FinancialArtifactAuditRepository,
    _FinancialArtifactBodyRepository,
)
from apps.data_center.infrastructure.financial_numeric_qualification.catalog_adapter import (
    FinancialNumericQualificationCatalogAdapter,
)
from apps.data_center.infrastructure.financial_numeric_qualification.main_verifier import (
    FinancialNumericQualificationAwareNativeVerifier,
)
from apps.data_center.infrastructure.financial_source_time_matchers import (
    AKSHARE_BALANCE_FINANCIAL_DATA_ENDPOINT,
    AKSHARE_MAIN_FINANCIAL_DATA_ENDPOINT,
)

_RESPONSE_AT = datetime(2026, 9, 15, 4, 0, tzinfo=UTC)
_KNOWN_AT = datetime(2026, 11, 16, 12, 0, tzinfo=UTC)
_PIT_AT = datetime(2026, 9, 20, 12, 0, tzinfo=UTC)
_CONTEXT = {"REPORT_DATE": "2026-06-30"}
_ENTRY_ID = UUID("10000000-0000-4000-8000-000000000001")
_CAPTURE_ID = UUID("20000000-0000-4000-8000-000000000001")
_APPLY_EVENT_ID = UUID("30000000-0000-4000-8000-000000000001")
_REVOKE_EVENT_ID = UUID("40000000-0000-4000-8000-000000000001")


def _contract(
    *, metric_code: str = "synthetic_metric", origin: Literal["native"] = "native"
) -> FinancialMetricSourceContract:
    """Build one explicit synthetic metric contract without business defaults."""

    return FinancialMetricSourceContract(
        provider="akshare",
        dataset_key="equity.financial.fact",
        metric_code=metric_code,
        source_field="RAW_METRIC",
        source_unit="synthetic-source-unit",
        canonical_unit="synthetic-canonical-unit",
        scale_numerator=1,
        scale_denominator=1,
        contract_version="adapter-test.v1",
        origin=origin,
    )


def _qualification(
    contract: FinancialMetricSourceContract | None = None,
    *,
    effective_until: datetime | None = datetime(2026, 10, 1, tzinfo=UTC),
) -> FinancialNumericSourceQualification:
    """Build an explicit Main-endpoint qualification and capture reference."""

    selected_contract = contract or _contract()
    captured_at = datetime(2026, 9, 1, tzinfo=UTC)
    capture = FinancialNumericSourceDocumentCaptureReference(
        capture_id=_CAPTURE_ID,
        document_id="synthetic-document",
        issuer="synthetic-publisher",
        canonical_url="https://docs.example.test/financial/main",
        body_sha256="d" * 64,
        body_size_bytes=128,
        captured_at=captured_at,
        content_type="text/html; charset=utf-8",
    )
    return FinancialNumericSourceQualification(
        contract=selected_contract,
        endpoint=AKSHARE_MAIN_FINANCIAL_DATA_ENDPOINT,
        source_applicability="synthetic-main-row-context",
        document_capture=capture,
        context_requirements=(
            FinancialNumericSourceContextRequirement("REPORT_DATE", "2026-06-30"),
        ),
        effective_from=captured_at,
        effective_until=effective_until,
    )


def _entry(
    qualification: FinancialNumericSourceQualification | None = None,
    *,
    revoke_at: datetime | None = None,
) -> FinancialNumericCatalogEntry:
    """Build a synthetic snapshot with distinct persisted record and event clocks."""

    selected = qualification or _qualification()
    entry_recorded = datetime(2026, 9, 3, tzinfo=UTC)
    apply_at = datetime(2026, 9, 5, tzinfo=UTC)
    apply_recorded = apply_at + timedelta(seconds=7)
    events = [
        FinancialNumericCatalogOwnerEvent(
            event_id=_APPLY_EVENT_ID,
            entry_id=_ENTRY_ID,
            action="apply",
            qualification_identity=selected.identity,
            qualification_sha256=selected.content_hash,
            actor_id=73,
            actor_username="synthetic-authenticated-owner",
            event_at=apply_at,
            recorded_at=apply_recorded,
        )
    ]
    if revoke_at is not None:
        events.append(
            FinancialNumericCatalogOwnerEvent(
                event_id=_REVOKE_EVENT_ID,
                entry_id=_ENTRY_ID,
                action="revoke",
                qualification_identity=selected.identity,
                qualification_sha256=selected.content_hash,
                actor_id=73,
                actor_username="synthetic-authenticated-owner",
                event_at=revoke_at,
                recorded_at=revoke_at + timedelta(seconds=3),
            )
        )
    return FinancialNumericCatalogEntry(
        entry_id=_ENTRY_ID,
        qualification=selected,
        recorded_at=entry_recorded,
        capture_recorded_at=selected.document_capture.captured_at + timedelta(seconds=5),
        owner_events=tuple(events),
    )


class _FakeCatalogRepository:
    """Record exact resolver calls and return one explicit qualification candidate."""

    def __init__(self, qualification: FinancialNumericSourceQualification | None) -> None:
        """Bind the qualification returned by both frozen repository operations."""

        self.qualification = qualification
        self.read_calls: list[dict[str, object]] = []
        self.uow_calls: list[dict[str, object]] = []

    def resolve_exact(
        self,
        contract_identity: str,
        *,
        endpoint: str,
        source_response_completed_at: datetime,
        source_context: Mapping[str, object],
        known_at: datetime,
    ) -> FinancialNumericSourceQualification | None:
        """Record the read-only resolver call with its exact caller cutoff."""

        self.read_calls.append(
            {
                "contract_identity": contract_identity,
                "endpoint": endpoint,
                "source_response_completed_at": source_response_completed_at,
                "source_context": source_context,
                "known_at": known_at,
            }
        )
        return self.qualification

    def resolve_exact_in_uow(
        self,
        contract_identity: str,
        *,
        endpoint: str,
        source_response_completed_at: datetime,
        source_context: Mapping[str, object],
        purpose: FinancialNumericCatalogResolutionPurpose,
        known_at: datetime,
    ) -> FinancialNumericSourceQualification | None:
        """Record use of the caller-owned current write/publication fence."""

        self.uow_calls.append(
            {
                "contract_identity": contract_identity,
                "endpoint": endpoint,
                "source_response_completed_at": source_response_completed_at,
                "source_context": source_context,
                "purpose": purpose,
                "known_at": known_at,
            }
        )
        return self.qualification


class _FakeSnapshotReader(FinancialNumericCatalogEntrySnapshotReadPort):
    """Return one in-memory entry snapshot and record its exact knowledge cutoff."""

    def __init__(self, entry: FinancialNumericCatalogEntry | None) -> None:
        """Bind one actual-shaped catalog entry snapshot for the adapter test."""

        self.entry = entry
        self.calls: list[dict[str, object]] = []

    def read_exact_entry(
        self,
        qualification: FinancialNumericSourceQualification,
        *,
        known_at: datetime,
    ) -> FinancialNumericCatalogEntry | None:
        """Record exact requested qualification identity, hash, and cutoff."""

        self.calls.append(
            {
                "qualification_identity": qualification.identity,
                "qualification_sha256": qualification.content_hash,
                "known_at": known_at,
            }
        )
        return self.entry


def _resolve(
    *,
    context: FinancialNumericVerificationContext,
    qualification: FinancialNumericSourceQualification | None = None,
    entry: FinancialNumericCatalogEntry | None = None,
    endpoint: str = AKSHARE_MAIN_FINANCIAL_DATA_ENDPOINT,
) -> tuple[
    FinancialNumericSourceQualificationResolution | None,
    _FakeCatalogRepository,
    _FakeSnapshotReader,
]:
    """Call the adapter with an explicit source clock, row context, and purpose."""

    selected_qualification = qualification or _qualification()
    repository = _FakeCatalogRepository(selected_qualification)
    reader = _FakeSnapshotReader(entry if entry is not None else _entry(selected_qualification))
    adapter = FinancialNumericQualificationCatalogAdapter(repository, reader)
    result = adapter.resolve_exact(
        selected_qualification.contract.identity,
        endpoint=endpoint,
        source_response_completed_at=_RESPONSE_AT,
        source_context=_CONTEXT,
        verification_context=context,
    )
    return result, repository, reader


def test_current_read_uses_the_uow_fence_and_returns_persisted_event_metadata() -> None:
    """Current reads keep catalog locks while preserving persisted event metadata."""

    context = FinancialNumericVerificationContext(
        known_at=_KNOWN_AT,
        purpose=FinancialNumericVerificationPurpose.CURRENT_READ,
    )
    result, repository, reader = _resolve(context=context)

    assert result is not None
    assert repository.read_calls == []
    assert len(repository.uow_calls) == 1
    assert (
        repository.uow_calls[0]["purpose"] is FinancialNumericCatalogResolutionPurpose.CURRENT_READ
    )
    assert repository.uow_calls[0]["known_at"] == _KNOWN_AT
    assert repository.uow_calls[0]["source_response_completed_at"] == _RESPONSE_AT
    assert reader.calls == [
        {
            "qualification_identity": result.qualification.identity,
            "qualification_sha256": result.qualification.content_hash,
            "known_at": _KNOWN_AT,
        }
    ]
    assert result.entry.entry_id == _ENTRY_ID
    assert result.entry.qualification.content_hash == result.apply_event.qualification_sha256
    assert result.apply_event.event_id == _APPLY_EVENT_ID
    assert result.apply_event.actor_id == 73
    assert result.recorded_at == datetime(2026, 9, 3, tzinfo=UTC)
    assert result.capture_recorded_at == datetime(2026, 9, 1, 0, 0, 5, tzinfo=UTC)
    assert result.approved_at == datetime(2026, 9, 5, tzinfo=UTC)
    assert result.approved_recorded_at == result.approved_at + timedelta(seconds=7)
    assert result.revoked_at is None


@pytest.mark.parametrize(
    ("verification_purpose", "catalog_purpose"),
    [
        (
            FinancialNumericVerificationPurpose.CURRENT_READ,
            FinancialNumericCatalogResolutionPurpose.CURRENT_READ,
        ),
        (
            FinancialNumericVerificationPurpose.CURRENT_WRITE,
            FinancialNumericCatalogResolutionPurpose.CURRENT_WRITE,
        ),
        (
            FinancialNumericVerificationPurpose.CURRENT_PUBLICATION,
            FinancialNumericCatalogResolutionPurpose.CURRENT_PUBLICATION,
        ),
    ],
)
def test_current_write_and_publication_use_only_the_uow_fence(
    verification_purpose: FinancialNumericVerificationPurpose,
    catalog_purpose: FinancialNumericCatalogResolutionPurpose,
) -> None:
    """Write and Publication requests call the exact lock-preserving API."""

    context = FinancialNumericVerificationContext(_KNOWN_AT, verification_purpose)
    result, repository, _reader = _resolve(context=context)

    assert result is not None
    assert repository.read_calls == []
    assert len(repository.uow_calls) == 1
    call = repository.uow_calls[0]
    assert call["purpose"] is catalog_purpose
    assert call["known_at"] == _KNOWN_AT
    assert call["source_response_completed_at"] == _RESPONSE_AT


def test_point_in_time_uses_the_explicit_historical_cutoff() -> None:
    """PIT remains a nonlocking as-of query with the supplied cutoff unchanged."""

    context = FinancialNumericVerificationContext(
        known_at=_PIT_AT,
        purpose=FinancialNumericVerificationPurpose.POINT_IN_TIME_READ,
    )
    result, repository, reader = _resolve(context=context)

    assert result is not None
    assert repository.read_calls[0]["known_at"] == _PIT_AT
    assert repository.uow_calls == []
    assert reader.calls[0]["known_at"] == _PIT_AT


def test_balance_endpoint_is_accepted_only_as_an_exact_allowlisted_endpoint() -> None:
    """A Balance contract enters the same current UOW adapter by exact endpoint."""

    context = FinancialNumericVerificationContext(
        _KNOWN_AT, FinancialNumericVerificationPurpose.CURRENT_READ
    )
    qualification = replace(
        _qualification(),
        endpoint=AKSHARE_BALANCE_FINANCIAL_DATA_ENDPOINT,
    )
    result, repository, reader = _resolve(
        context=context,
        qualification=qualification,
        endpoint=AKSHARE_BALANCE_FINANCIAL_DATA_ENDPOINT,
    )

    assert result is not None
    assert repository.read_calls == []
    assert len(repository.uow_calls) == 1
    assert repository.uow_calls[0]["endpoint"] == AKSHARE_BALANCE_FINANCIAL_DATA_ENDPOINT
    assert (
        repository.uow_calls[0]["purpose"] is FinancialNumericCatalogResolutionPurpose.CURRENT_READ
    )
    assert reader.calls[0]["qualification_identity"] == qualification.identity


def test_endpoint_mismatch_blocks_before_catalog_or_snapshot_reads() -> None:
    """Balance-like and similar endpoint strings cannot enter the adapter."""

    context = FinancialNumericVerificationContext(
        _KNOWN_AT, FinancialNumericVerificationPurpose.CURRENT_READ
    )
    qualification = _qualification()
    repository = _FakeCatalogRepository(qualification)
    reader = _FakeSnapshotReader(_entry(qualification))
    adapter = FinancialNumericQualificationCatalogAdapter(repository, reader)

    result = adapter.resolve_exact(
        qualification.contract.identity,
        endpoint=AKSHARE_MAIN_FINANCIAL_DATA_ENDPOINT + "&balance=1",
        source_response_completed_at=_RESPONSE_AT,
        source_context=_CONTEXT,
        verification_context=context,
    )

    assert result is None
    assert repository.read_calls == []
    assert repository.uow_calls == []
    assert reader.calls == []


def test_missing_qualification_or_mismatched_entry_snapshot_fails_closed() -> None:
    """Missing rows and a hash/identity disagreement never create metadata."""

    context = FinancialNumericVerificationContext(
        _KNOWN_AT, FinancialNumericVerificationPurpose.CURRENT_READ
    )
    qualification = _qualification()
    missing_repo = _FakeCatalogRepository(None)
    missing_reader = _FakeSnapshotReader(None)
    missing_adapter = FinancialNumericQualificationCatalogAdapter(missing_repo, missing_reader)
    assert (
        missing_adapter.resolve_exact(
            qualification.contract.identity,
            endpoint=AKSHARE_MAIN_FINANCIAL_DATA_ENDPOINT,
            source_response_completed_at=_RESPONSE_AT,
            source_context=_CONTEXT,
            verification_context=context,
        )
        is None
    )
    assert missing_reader.calls == []

    wrong_qualification = _qualification(_contract(metric_code="different_metric"))
    wrong_entry = _entry(wrong_qualification)
    repository = _FakeCatalogRepository(qualification)
    reader = _FakeSnapshotReader(wrong_entry)
    adapter = FinancialNumericQualificationCatalogAdapter(repository, reader)
    assert (
        adapter.resolve_exact(
            qualification.contract.identity,
            endpoint=AKSHARE_MAIN_FINANCIAL_DATA_ENDPOINT,
            source_response_completed_at=_RESPONSE_AT,
            source_context=_CONTEXT,
            verification_context=context,
        )
        is None
    )


def test_domain_forbids_derived_contract_and_revoked_snapshot_does_not_resolve() -> None:
    """The contract is native-only and a revoke at the cutoff blocks."""

    context = FinancialNumericVerificationContext(
        _KNOWN_AT, FinancialNumericVerificationPurpose.CURRENT_READ
    )
    with pytest.raises(ValueError, match="native origin"):
        _contract(metric_code="derived_metric", origin=cast(Literal["native"], "derived"))

    revoked_context = _KNOWN_AT
    qualification = _qualification()
    revoked_entry = _entry(qualification, revoke_at=revoked_context - timedelta(days=1))
    result, _repository, _reader = _resolve(
        context=context,
        qualification=qualification,
        entry=revoked_entry,
    )
    assert result is None


def test_resolution_requires_real_apply_event_and_no_implicit_one_argument_api() -> None:
    """Metadata cannot be supplied as just timestamps or through a legacy call."""

    qualification = _qualification()
    entry_without_apply = FinancialNumericCatalogEntry(
        entry_id=_ENTRY_ID,
        qualification=qualification,
        recorded_at=datetime(2026, 9, 3, tzinfo=UTC),
        capture_recorded_at=qualification.document_capture.captured_at + timedelta(seconds=5),
        owner_events=(),
    )
    with pytest.raises(ValueError, match="persisted apply event"):
        FinancialNumericSourceQualificationResolution(entry=entry_without_apply)

    repository = _FakeCatalogRepository(qualification)
    reader: FinancialNumericCatalogEntrySnapshotReadPort = _FakeSnapshotReader(
        _entry(qualification)
    )
    adapter = FinancialNumericQualificationCatalogAdapter(repository, reader)
    legacy_call = cast(Callable[[str], object], adapter.resolve_exact)
    with pytest.raises(TypeError):
        legacy_call(qualification.contract.identity)


def test_resolved_catalog_snapshot_satisfies_existing_native_verifier_port() -> None:
    """The rich entry result flows through the existing explicit-context verifier."""

    from tests.unit.data_center import financial_numeric_fixtures as helper_module

    helper_exports = vars(helper_module)

    fact_factory = cast(Callable[[], FinancialFact], helper_exports["_fact"])
    contract_builder = cast(
        Callable[[FinancialMetricSourceContract], FinancialNumericSourceQualification],
        helper_exports["_qualification"],
    )
    audit_builder = cast(
        Callable[[FinancialResponseArtifactRef], RawAudit],
        helper_exports["_audit"],
    )
    fact = fact_factory()
    assert fact.numeric_evidence is not None
    assert fact.decision_evidence is not None
    reference = fact.decision_evidence.artifact_reference
    qualification = contract_builder(fact.numeric_evidence.contract)
    adapter = FinancialNumericQualificationCatalogAdapter(
        _FakeCatalogRepository(qualification),
        _FakeSnapshotReader(_entry(qualification)),
    )

    body = cast(bytes, helper_exports["BODY"])
    known_at = cast(datetime, helper_exports["KNOWN_NOW"])
    artifact_store_factory = cast(
        Callable[[bytes], object],
        helper_exports["_ArtifactRepository"],
    )
    audit_repository_factory = cast(
        Callable[[RawAudit], object],
        helper_exports["_AuditRepository"],
    )
    provider_resolver_factory = cast(
        Callable[[], object],
        helper_exports["_ProviderIdentityResolver"],
    )
    body_reader = FinancialNativeRawBodyReader(
        artifact_repository=cast(_FinancialArtifactBodyRepository, artifact_store_factory(body)),
        audit_repository=cast(
            _FinancialArtifactAuditRepository,
            audit_repository_factory(audit_builder(reference)),
        ),
        provider_identity_resolver=cast(
            FinancialNativeProviderIdentityPort,
            provider_resolver_factory(),
        ),
    )
    verifier = FinancialNumericQualificationAwareNativeVerifier(adapter, body_reader)
    context = FinancialNumericVerificationContext(
        known_at=known_at,
        purpose=FinancialNumericVerificationPurpose.CURRENT_READ,
    )

    assert verifier.verify(fact, context) is True
