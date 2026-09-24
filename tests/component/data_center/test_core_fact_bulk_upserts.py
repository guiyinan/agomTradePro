"""Bulk persistence contracts for production core-data rebuilds."""

from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from uuid import UUID

import pytest

from apps.data_center.domain.entities import FinancialFact, PriceBar, ValuationFact
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
from apps.data_center.infrastructure.financial_fact_repository import FinancialFactRepository
from apps.data_center.infrastructure.financial_fact_write_guard import (
    FinancialFactProvenanceConflictError,
)
from apps.data_center.infrastructure.fundamental_fact_repositories import ValuationFactRepository
from apps.data_center.infrastructure.market_data_repositories import PriceBarRepository
from apps.data_center.infrastructure.models import (
    FinancialFactModel,
    PriceBarModel,
    ValuationFactModel,
)

pytestmark = pytest.mark.django_db


def _financial_repository() -> FinancialFactRepository:
    """Build a repository with an independent verifier double for retained fixtures."""

    return FinancialFactRepository(source_time_evidence_verifier=lambda _witness: True)


def _financial_fact(
    *,
    period_end: date,
    metric_code: str,
    value: float,
    body_sha256: str,
    source_record_id: str,
) -> FinancialFact:
    """Build one canonical financial row with exact retained-response evidence."""

    announced_at = datetime(2026, 9, 1, 8, tzinfo=UTC)
    available_at = announced_at + timedelta(minutes=5)
    response = FinancialResponseEvidence(
        body_sha256=body_sha256,
        body_size_bytes=128,
        response_completed_at=available_at + timedelta(minutes=1),
        request_scope=FinancialRequestScope(
            provider_name="akshare",
            dataset_key="equity.financial.fact",
            asset_code="000001.SZ",
            period_limit=1,
        ),
        response_scope=FinancialResponseScope(
            asset_codes=("000001.SZ",),
            period_ends=(period_end,),
            row_count=1,
        ),
        response_scope_basis=FinancialResponseScopeBasis.PROVIDER_BODY_VERIFIED,
    )
    decision = FinancialFactDecisionEvidence(
        artifact_reference=FinancialResponseArtifactRef(
            capture_id=UUID(hex=body_sha256[:32]),
            location=f"financial-response/{source_record_id}.bin",
            evidence=response,
            format_version="financial-response-artifact.v1",
            encryption_algorithm="fernet",
            encryption_key_ref="config_center.data02.test-key",
            encryption_key_version="v1",
        ),
        native_asset_code="000001.SZ",
        native_period_end=period_end,
        native_row_id=source_record_id,
        source_time_witness=FinancialSourceTimeWitness(
            artifact_reference=FinancialSourceTimeArtifactRef(
                capture_id=UUID(hex=("9" * 32)),
                location=f"financial-source-time/{source_record_id}.bin",
                provider_name="akshare",
                dataset_key=FINANCIAL_SOURCE_TIME_DATASET_KEY,
                requested_asset_code="000001.SZ",
                requested_announcement_date=date(2026, 9, 1),
                body_sha256="8" * 64,
                body_size_bytes=96,
                response_completed_at=available_at,
                response_row_count=1,
                format_version="financial-source-time-artifact.v1",
                encryption_algorithm="fernet",
                encryption_key_ref="config_center.data02.test-key",
                encryption_key_version="v1",
            ),
            native_asset_code="000001.SZ",
            native_period_end=period_end,
            financial_native_row_id=source_record_id,
            financial_announced_date=date(2026, 9, 1),
            source_native_row_id=f"akshare:notice:{source_record_id}",
            source_timezone="Asia/Shanghai",
            announced_at=announced_at,
            available_at=available_at,
            row_projection_sha256="7" * 64,
            governed_match_contract_id="akshare.financial-announcement.exact",
            governed_match_contract_version="v1",
            governed_match_contract_sha256="6" * 64,
            matched_row_count=1,
            availability_basis=FinancialAvailabilityBasis.PROVIDER_NATIVE_EXACT,
        ),
    )
    return FinancialFact(
        asset_code="000001.SZ",
        period_end=period_end,
        period_type=FinancialPeriodType.QUARTERLY,
        metric_code=metric_code,
        value=value,
        unit="元" if metric_code == "revenue" else "%",
        source="akshare",
        report_date=period_end,
        available_at=available_at,
        source_evidence=FinancialFactSourceEvidence(
            announced_at=announced_at,
            source_record_id=source_record_id,
            raw_payload_hash=body_sha256,
        ),
        decision_evidence=decision,
    )


def test_financial_bulk_upsert_rejects_unbound_source_time() -> None:
    """A valid response body cannot authorize caller-supplied source timestamps."""

    fact = _financial_fact(
        period_end=date(2026, 6, 30),
        metric_code="revenue",
        value=100.0,
        body_sha256="a" * 64,
        source_record_id="row-unbound-source-time",
    )
    assert fact.decision_evidence is not None
    unbound = replace(
        fact,
        decision_evidence=replace(fact.decision_evidence, source_time_witness=None),
    )

    with pytest.raises(FinancialFactProvenanceConflictError, match="source-time artifact"):
        _financial_repository().bulk_upsert([unbound])

    assert FinancialFactModel._default_manager.count() == 0


def test_financial_bulk_upsert_requires_independent_source_time_verifier() -> None:
    """A caller-built witness cannot cross the direct repository boundary by itself."""

    fact = _financial_fact(
        period_end=date(2026, 6, 30),
        metric_code="revenue",
        value=100.0,
        body_sha256="a" * 64,
        source_record_id="row-caller-asserted-source-time",
    )

    with pytest.raises(FinancialFactProvenanceConflictError, match="independently verified"):
        FinancialFactRepository().bulk_upsert([fact])

    assert FinancialFactModel._default_manager.count() == 0
    verified: list[FinancialFactDecisionEvidence] = []

    def verify(decision: FinancialFactDecisionEvidence) -> bool:
        verified.append(decision)
        return True

    assert FinancialFactRepository(source_time_evidence_verifier=verify).bulk_upsert([fact]) == 1
    assert verified == [fact.decision_evidence]


def test_price_bulk_upsert_updates_conflicts_with_bounded_batch_queries(
    django_assert_num_queries: object,
) -> None:
    repository = PriceBarRepository()
    first = [
        PriceBar(
            asset_code=f"{index:06d}.SZ",
            bar_date=date(2026, 7, 31),
            open=10.0,
            high=11.0,
            low=9.0,
            close=10.5,
            source="akshare",
        )
        for index in range(20)
    ]
    revised = [replace(item, high=12.0, close=11.5) for item in first]

    # Ownership and frozen-publication checks plus one batched write stay
    # constant as the batch grows; they must not become per-asset queries.
    with django_assert_num_queries(4):  # type: ignore[operator]
        assert repository.bulk_upsert(first) == 20
    with django_assert_num_queries(5):  # type: ignore[operator]
        assert repository.bulk_upsert(revised) == 20

    assert PriceBarModel._default_manager.filter(close=11.5).count() == 20


def test_financial_and_valuation_bulk_upserts_update_natural_keys() -> None:
    financial_repository = _financial_repository()
    valuation_repository = ValuationFactRepository()
    financial = _financial_fact(
        period_end=date(2026, 6, 30),
        metric_code="revenue",
        value=100.0,
        body_sha256="a" * 64,
        source_record_id="row000000001",
    )
    valuation = ValuationFact(
        asset_code="000001.SZ",
        val_date=date(2026, 7, 31),
        pe_ttm=10.0,
        pb=1.0,
        source="akshare",
    )

    assert financial_repository.bulk_upsert([financial]) == 1
    assert valuation_repository.bulk_upsert([valuation]) == 1
    assert (
        financial_repository.bulk_upsert(
            [
                _financial_fact(
                    period_end=financial.period_end,
                    metric_code=financial.metric_code,
                    value=120.0,
                    body_sha256="b" * 64,
                    source_record_id="row000000002",
                )
            ]
        )
        == 1
    )
    assert (
        valuation_repository.bulk_upsert(
            [
                ValuationFact(
                    **{
                        **valuation.__dict__,
                        "pe_ttm": 12.0,
                    }
                )
            ]
        )
        == 1
    )

    assert FinancialFactModel._default_manager.get().value == 120.0
    assert ValuationFactModel._default_manager.get().pe_ttm == 12.0
    assert FinancialFactModel._default_manager.count() == 1
    assert ValuationFactModel._default_manager.count() == 1


def test_financial_fact_repository_honors_as_of_end_date() -> None:
    repository = _financial_repository()
    repository.bulk_upsert(
        [
            _financial_fact(
                period_end=date(2026, 7, 31),
                metric_code="roe",
                value=10.0,
                body_sha256="c" * 64,
                source_record_id="row000000003",
            ),
            _financial_fact(
                period_end=date(2026, 8, 31),
                metric_code="roe",
                value=20.0,
                body_sha256="d" * 64,
                source_record_id="row000000004",
            ),
        ]
    )

    rows = repository.get_facts(
        "000001.SZ",
        limit=20,
        end=date(2026, 7, 31),
    )

    assert [row.period_end for row in rows] == [date(2026, 7, 31)]


def test_financial_fact_repository_enforces_exact_knowledge_cutoff() -> None:
    """Historical decisions exclude future and source-time-unknown statements."""

    repository = _financial_repository()
    repository.bulk_upsert(
        [
            _financial_fact(
                period_end=date(2026, 3, 31),
                metric_code="roe",
                value=10.0,
                body_sha256="e" * 64,
                source_record_id="row000000005",
            ),
            _financial_fact(
                period_end=date(2026, 6, 30),
                metric_code="roa",
                value=20.0,
                body_sha256="f" * 64,
                source_record_id="row000000006",
            ),
            _financial_fact(
                period_end=date(2026, 6, 30),
                metric_code="debt_ratio",
                value=30.0,
                body_sha256="1" * 64,
                source_record_id="row000000007",
            ),
        ]
    )
    cutoff = datetime(2026, 9, 1, 9, tzinfo=UTC)
    FinancialFactModel._default_manager.filter(metric_code="roe").update(
        announced_at=cutoff,
        available_at=cutoff,
    )
    FinancialFactModel._default_manager.filter(metric_code="roa").update(
        announced_at=cutoff + timedelta(seconds=1),
        available_at=cutoff + timedelta(seconds=1),
    )
    FinancialFactModel._default_manager.filter(metric_code="debt_ratio").update(
        announced_at=None,
        available_at=None,
    )

    rows = repository.get_facts(
        "000001.SZ",
        limit=20,
        end=date(2026, 9, 1),
        knowledge_cutoff=cutoff,
    )

    assert [(row.period_end, row.metric_code) for row in rows] == [(date(2026, 3, 31), "roe")]
    with pytest.raises(ValueError, match="knowledge cutoff must be timezone-aware"):
        repository.get_facts(
            "000001.SZ",
            knowledge_cutoff=datetime(2026, 9, 1, 9),
        )
