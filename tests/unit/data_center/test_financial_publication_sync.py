from __future__ import annotations

from dataclasses import replace
from datetime import UTC, date, datetime
from uuid import UUID

import pytest

from apps.data_center.application.dtos import SyncFinancialRequest
from apps.data_center.application.publication_sync import PublishFinancialBatchUseCase
from apps.data_center.application.sync_use_cases import SyncFinancialUseCase
from apps.data_center.domain.contracts import DatasetKey, PublicationPolicy
from apps.data_center.domain.control_plane import CanonicalPublication, PublicationFactReference
from apps.data_center.domain.entities import FinancialFact, ProviderConfig
from apps.data_center.domain.enums import FinancialPeriodType
from apps.data_center.domain.financial_response_artifact import FinancialResponseArtifactRef
from apps.data_center.domain.financial_response_evidence import (
    FinancialRequestScope,
    FinancialResponseEvidence,
    FinancialResponseScope,
    FinancialResponseScopeBasis,
)
from apps.data_center.domain.financial_source_evidence import (
    FinancialFactDecisionEvidence,
    FinancialFactSourceEvidence,
)
from apps.data_center.domain.financial_source_time_evidence import (
    FINANCIAL_SOURCE_TIME_DATASET_KEY,
    FinancialAvailabilityBasis,
    FinancialSourceTimeArtifactRef,
    FinancialSourceTimeWitness,
)
from apps.data_center.infrastructure.financial_decision_evidence_codec import (
    encode_financial_decision_evidence,
)
from apps.data_center.infrastructure.financial_fact_repository import FinancialFactRepository
from apps.data_center.infrastructure.financial_fact_write_guard import (
    FinancialFactProvenanceConflictError,
)
from apps.data_center.infrastructure.models import FinancialFactModel

PUBLISHED_AT = datetime(2026, 8, 4, 12, 0, tzinfo=UTC)
PERIOD_END = date(2026, 6, 30)
AVAILABLE_AT = datetime(2026, 7, 31, 9, 30, tzinfo=UTC)


class _CandidateRepository:
    def __init__(self, references: list[PublicationFactReference]) -> None:
        self.references = references

    def list_publication_candidates(self, _facts):
        return list(self.references)


class _PolicyRepository:
    def get_active(self, _dataset_key: str):
        return PublicationPolicy(
            dataset=DatasetKey("equity.financial.fact", "1.0", "1.0"),
            minimum_coverage_ratio=1.0,
            allow_partial=True,
            conflict_action="quarantine",
            required_evidence=("source", "observed_at", "available_at", "payload_hash"),
            retention_days=3650,
        )


class _PublicationRepository:
    def __init__(self) -> None:
        self.current: CanonicalPublication | None = None
        self.published: list[tuple[CanonicalPublication, tuple[object, ...]]] = []

    def get_current(self, _dataset_key: str, _publication_key: str):
        return self.current

    def publish_with_members(self, publication, members):
        self.current = publication
        self.published.append((publication, members))
        return publication

    def list_members(self, publication_id):
        return next(
            (
                members
                for publication, members in self.published
                if publication.publication_id == publication_id
            ),
            (),
        )


def _fact(
    asset_code: str = "000001.SZ",
    *,
    available_at: datetime | None = AVAILABLE_AT,
) -> FinancialFact:
    return FinancialFact(
        asset_code=asset_code,
        period_end=PERIOD_END,
        period_type=FinancialPeriodType.QUARTERLY,
        metric_code="revenue",
        value=123.4,
        unit="元",
        source="provider-main",
        report_date=date(2026, 7, 30),
        available_at=available_at,
        fetched_at=PUBLISHED_AT,
    )


def _source_ready_fact(
    *,
    raw_hash: str = "c" * 64,
    source_record_id: str = "tushare:fina_indicator:000001.SZ:20260630",
) -> FinancialFact:
    """Build one fact bound to a typed retained response and native row."""

    response = FinancialResponseEvidence(
        body_sha256=raw_hash,
        body_size_bytes=128,
        response_completed_at=datetime(2026, 8, 4, 11, 59, tzinfo=UTC),
        request_scope=FinancialRequestScope(
            provider_name="provider-main",
            dataset_key="equity.financial.fact",
            asset_code="000001.SZ",
            period_limit=1,
        ),
        response_scope=FinancialResponseScope(
            asset_codes=("000001.SZ",),
            period_ends=(PERIOD_END,),
            row_count=1,
        ),
        response_scope_basis=FinancialResponseScopeBasis.PROVIDER_BODY_VERIFIED,
    )
    announced_at = datetime(2026, 7, 30, 8, 0, tzinfo=UTC)
    source_time_witness = FinancialSourceTimeWitness(
        artifact_reference=FinancialSourceTimeArtifactRef(
            capture_id=UUID("20000000-0000-4000-8000-000000000006"),
            location="financial-source-time/publication.bin",
            provider_name="provider-main",
            dataset_key=FINANCIAL_SOURCE_TIME_DATASET_KEY,
            requested_asset_code="000001.SZ",
            requested_announcement_date=date(2026, 7, 30),
            body_sha256="d" * 64,
            body_size_bytes=96,
            response_completed_at=AVAILABLE_AT,
            response_row_count=1,
            format_version="financial-source-time-artifact.v1",
            encryption_algorithm="fernet",
            encryption_key_ref="config_center.data02.test-key",
            encryption_key_version="v1",
        ),
        native_asset_code="000001.SZ",
        native_period_end=PERIOD_END,
        financial_native_row_id=source_record_id,
        financial_announced_date=date(2026, 7, 30),
        source_native_row_id="provider-main:notice:000001.SZ:20260730:1",
        source_timezone="Asia/Shanghai",
        announced_at=announced_at,
        available_at=AVAILABLE_AT,
        row_projection_sha256="e" * 64,
        governed_match_contract_id="provider-main.financial-announcement.exact",
        governed_match_contract_version="v1",
        governed_match_contract_sha256="f" * 64,
        matched_row_count=1,
        availability_basis=FinancialAvailabilityBasis.PROVIDER_NATIVE_EXACT,
    )
    return replace(
        _fact(),
        source_evidence=FinancialFactSourceEvidence(
            announced_at=announced_at,
            source_record_id=source_record_id,
            raw_payload_hash=raw_hash,
        ),
        decision_evidence=FinancialFactDecisionEvidence(
            artifact_reference=FinancialResponseArtifactRef(
                capture_id=UUID("20000000-0000-4000-8000-000000000003"),
                location="financial-response/publication.bin",
                evidence=response,
                format_version="financial-response-artifact.v1",
                encryption_algorithm="fernet",
                encryption_key_ref="config_center.data02.test-key",
                encryption_key_version="v1",
            ),
            native_asset_code="000001.SZ",
            native_period_end=PERIOD_END,
            native_row_id=source_record_id,
            source_time_witness=source_time_witness,
        ),
    )


def _reference(
    asset_code: str = "000001.SZ",
    fact_pk: str = "201",
    *,
    observed_at: datetime = AVAILABLE_AT,
) -> PublicationFactReference:
    return PublicationFactReference(
        natural_key=(f"{asset_code}:{PERIOD_END.isoformat()}:quarterly:revenue:provider-main"),
        source="provider-main",
        source_record_id=f"financial-{asset_code}",
        fact_table="data_center_financial_fact",
        fact_pk=fact_pk,
        observed_at=observed_at,
        available_at=observed_at,
        fetched_at=PUBLISHED_AT,
        raw_payload_hash="a" * 64,
    )


def test_financial_publication_uses_available_at_and_exact_members() -> None:
    repository = _PublicationRepository()
    use_case = PublishFinancialBatchUseCase(
        fact_repository=_CandidateRepository([_reference()]),
        publication_repository=repository,
        policy_repository=_PolicyRepository(),
    )

    publication = use_case.execute(
        [_fact()],
        provider_name="provider-main",
        published_at=PUBLISHED_AT,
    )

    assert publication is not None
    assert publication.as_of == AVAILABLE_AT
    assert publication.as_of != _fact().fetched_at
    assert publication.coverage.selected_count == 1
    assert publication.coverage.missing_count == 0
    assert repository.published[0][1][0].fact_pk == "201"
    assert repository.published[0][1][0].observed_at == AVAILABLE_AT


def test_financial_publication_is_idempotent_for_same_snapshot() -> None:
    repository = _PublicationRepository()
    use_case = PublishFinancialBatchUseCase(
        fact_repository=_CandidateRepository([_reference()]),
        publication_repository=repository,
        policy_repository=_PolicyRepository(),
    )

    first = use_case.execute([_fact()], provider_name="provider-main", published_at=PUBLISHED_AT)
    second = use_case.execute([_fact()], provider_name="provider-main", published_at=PUBLISHED_AT)

    assert first is second
    assert len(repository.published) == 1


def test_financial_publication_fails_closed_below_coverage_policy() -> None:
    facts = [_fact("000001.SZ"), _fact("600000.SH")]
    use_case = PublishFinancialBatchUseCase(
        fact_repository=_CandidateRepository([_reference("000001.SZ")]),
        publication_repository=_PublicationRepository(),
        policy_repository=_PolicyRepository(),
    )

    with pytest.raises(ValueError, match="coverage"):
        use_case.execute(facts, provider_name="provider-main", published_at=PUBLISHED_AT)


def test_financial_publication_blocks_when_available_at_is_missing() -> None:
    use_case = PublishFinancialBatchUseCase(
        fact_repository=_CandidateRepository([]),
        publication_repository=_PublicationRepository(),
        policy_repository=_PolicyRepository(),
    )

    with pytest.raises(ValueError, match="available_at"):
        use_case.execute(
            [_fact(available_at=None)],
            provider_name="provider-main",
            published_at=PUBLISHED_AT,
        )


def test_financial_publication_rejects_future_available_at() -> None:
    future = datetime(2026, 8, 5, tzinfo=UTC)
    use_case = PublishFinancialBatchUseCase(
        fact_repository=_CandidateRepository([_reference(observed_at=future)]),
        publication_repository=_PublicationRepository(),
        policy_repository=_PolicyRepository(),
    )

    with pytest.raises(ValueError, match="availability"):
        use_case.execute([_fact()], provider_name="provider-main", published_at=PUBLISHED_AT)


@pytest.mark.django_db
def test_financial_repository_candidate_requires_available_at_and_preserves_evidence() -> None:
    bound_fact = _source_ready_fact(raw_hash="b" * 64, source_record_id="financial-1")
    assert bound_fact.decision_evidence is not None
    missing = FinancialFactModel.objects.create(
        asset_code="600000.SH",
        period_end=PERIOD_END,
        period_type="quarterly",
        metric_code="revenue",
        value=120,
        unit="元",
        source="provider-main",
        report_date=date(2026, 7, 30),
        available_at=None,
        source_record_id="missing-available",
    )
    row = FinancialFactModel.objects.create(
        asset_code="000001.SZ",
        period_end=PERIOD_END,
        period_type="quarterly",
        metric_code="revenue",
        value=123.4,
        unit="元",
        source="provider-main",
        report_date=date(2026, 7, 30),
        available_at=AVAILABLE_AT,
        announced_at=bound_fact.source_evidence.announced_at,
        source_record_id="financial-1",
        raw_payload_hash="b" * 64,
        extra={
            "financial_response_capture_id": str(
                bound_fact.decision_evidence.artifact_reference.capture_id
            ),
            "raw_payload_scope": "batch_response_body",
            "response_scope_basis": "provider_body_verified",
            "financial_source_time_capture_id": str(
                bound_fact.decision_evidence.source_time_witness.artifact_reference.capture_id
            ),
            "financial_source_time_body_sha256": (
                bound_fact.decision_evidence.source_time_witness.artifact_reference.body_sha256
            ),
            "financial_source_time_row_sha256": (
                bound_fact.decision_evidence.source_time_witness.row_projection_sha256
            ),
            "financial_source_time_match_contract_id": (
                bound_fact.decision_evidence.source_time_witness.governed_match_contract_id
            ),
            "financial_source_time_match_contract_version": (
                bound_fact.decision_evidence.source_time_witness.governed_match_contract_version
            ),
            "financial_source_time_match_contract_sha256": (
                bound_fact.decision_evidence.source_time_witness.governed_match_contract_sha256
            ),
            "financial_source_time_matched_row_count": (
                bound_fact.decision_evidence.source_time_witness.matched_row_count
            ),
        },
        decision_evidence=encode_financial_decision_evidence(bound_fact.decision_evidence),
    )

    verified: list[FinancialFactDecisionEvidence] = []

    def verify(decision: FinancialFactDecisionEvidence) -> bool:
        verified.append(decision)
        return True

    with pytest.raises(
        FinancialFactProvenanceConflictError,
        match="independently reverified",
    ):
        FinancialFactRepository().list_publication_candidates([bound_fact])

    references = FinancialFactRepository(
        source_time_evidence_verifier=verify
    ).list_publication_candidates([_fact(), _fact("600000.SH", available_at=None)])

    assert len(references) == 1
    assert references[0].fact_pk == str(row.pk)
    assert references[0].source == "provider-main"
    assert references[0].source_record_id == "financial-1"
    assert references[0].raw_payload_hash == "b" * 64
    assert references[0].observed_at == AVAILABLE_AT
    assert references[0].observed_at != row.fetched_at
    assert str(missing.pk) not in {reference.fact_pk for reference in references}
    assert verified == [bound_fact.decision_evidence]


@pytest.mark.django_db
def test_financial_repository_rejects_legacy_evidence_without_source_time_witness() -> None:
    """Readable v1 evidence remains ineligible for a current Publication."""

    bound_fact = _source_ready_fact(raw_hash="b" * 64, source_record_id="financial-legacy")
    assert bound_fact.decision_evidence is not None
    legacy = FinancialFactDecisionEvidence(
        artifact_reference=bound_fact.decision_evidence.artifact_reference,
        native_asset_code=bound_fact.decision_evidence.native_asset_code,
        native_period_end=bound_fact.decision_evidence.native_period_end,
        native_row_id=bound_fact.decision_evidence.native_row_id,
    )
    FinancialFactModel.objects.create(
        asset_code=bound_fact.asset_code,
        period_end=bound_fact.period_end,
        period_type=bound_fact.period_type.value,
        metric_code=bound_fact.metric_code,
        value=bound_fact.value,
        unit=bound_fact.unit,
        source=bound_fact.source,
        report_date=bound_fact.report_date,
        available_at=bound_fact.available_at,
        announced_at=bound_fact.source_evidence.announced_at,
        source_record_id="financial-legacy",
        raw_payload_hash="b" * 64,
        decision_evidence=encode_financial_decision_evidence(legacy),
    )

    with pytest.raises(FinancialFactProvenanceConflictError, match="source-time evidence"):
        FinancialFactRepository().list_publication_candidates([bound_fact])


def test_sync_financial_use_case_invokes_publication_after_fact_write() -> None:
    class _Provider:
        def provider_name(self) -> str:
            return "provider-main"

        def fetch_financials(self, _asset_code, periods: int = 8) -> list[FinancialFact]:
            return [_source_ready_fact()][:periods]

    class _ProviderRepository:
        def __init__(self) -> None:
            self.config = ProviderConfig(
                id=1,
                name="provider-main",
                source_type="tushare",
                is_active=True,
                priority=1,
                api_key="",
                api_secret="",
                http_url="",
                api_endpoint="",
                extra_config={},
                description="",
            )

        def get_by_id(self, _provider_id: int):
            return self.config

        def save(self, config):
            self.config = config
            return config

    class _Registry:
        def get_by_id(self, _provider_id: int):
            return _Provider()

        def record_success(self, *_args) -> None:
            return None

        def record_failure(self, *_args) -> None:
            return None

    class _Facts:
        def __init__(self) -> None:
            self.saved: list[FinancialFact] = []

        def bulk_upsert(self, facts: list[FinancialFact]) -> int:
            self.saved.extend(facts)
            return len(facts)

    class _RawAudit:
        def log(self, _audit) -> None:
            return None

    class _Publisher:
        def __init__(self) -> None:
            self.calls: list[tuple[list[FinancialFact], str]] = []

        def execute(self, facts, *, provider_name: str):
            self.calls.append((list(facts), provider_name))
            return None

    provider_repo = _ProviderRepository()
    facts = _Facts()
    publisher = _Publisher()
    result = SyncFinancialUseCase(
        provider_repo=provider_repo,
        provider_registry=_Registry(),
        fact_repo=facts,
        raw_audit_repo=_RawAudit(),
        publication_publisher=publisher,
        artifact_verifier=lambda _provider, _reference: True,
        source_time_artifact_verifier=lambda _provider, _reference: True,
    ).execute(SyncFinancialRequest(provider_id=1, asset_code="000001.SZ", periods=1))

    assert result.status == "success"
    assert len(facts.saved) == 1
    assert publisher.calls == [(facts.saved, "provider-main")]
