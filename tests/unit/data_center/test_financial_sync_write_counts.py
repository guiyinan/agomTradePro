"""Application audit semantics for financial repository write counts."""

from __future__ import annotations

from datetime import UTC, date, datetime
from uuid import UUID

import pytest

from apps.data_center.application.dtos import SyncFinancialRequest
from apps.data_center.application.sync_use_cases import SyncFinancialUseCase
from apps.data_center.domain.entities import FinancialFact, ProviderConfig, RawAudit
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

_FETCHED_AT = datetime(2026, 9, 14, 12, 0, tzinfo=UTC)
_AVAILABLE_AT = datetime(2026, 9, 14, 11, 58, tzinfo=UTC)
_COMPLETED_AT = datetime(2026, 9, 14, 11, 59, tzinfo=UTC)
_RAW_HASH = "a" * 64
_SOURCE_RECORD_ID = "tushare:fina_indicator:000001.SZ:20260630"


def _decision_evidence() -> FinancialFactDecisionEvidence:
    response = FinancialResponseEvidence(
        body_sha256=_RAW_HASH,
        body_size_bytes=128,
        response_completed_at=_COMPLETED_AT,
        request_scope=FinancialRequestScope(
            provider_name="provider-main",
            dataset_key="equity.financial.fact",
            asset_code="000001.SZ",
            period_limit=2,
        ),
        response_scope=FinancialResponseScope(
            asset_codes=("000001.SZ",),
            period_ends=(date(2026, 6, 30),),
            row_count=1,
        ),
        response_scope_basis=FinancialResponseScopeBasis.PROVIDER_BODY_VERIFIED,
    )
    return FinancialFactDecisionEvidence(
        artifact_reference=FinancialResponseArtifactRef(
            capture_id=UUID("20000000-0000-4000-8000-000000000002"),
            location="financial-response/write-count.bin",
            evidence=response,
            format_version="financial-response-artifact.v1",
            encryption_algorithm="fernet",
            encryption_key_ref="config_center.data02.test-key",
            encryption_key_version="v1",
        ),
        native_asset_code="000001.SZ",
        native_period_end=date(2026, 6, 30),
        native_row_id=_SOURCE_RECORD_ID,
    )


def _fact(metric_code: str) -> FinancialFact:
    """Build one provider fact for the two-row mixed/replay contract."""

    return FinancialFact(
        asset_code="000001.SZ",
        period_end=date(2026, 6, 30),
        period_type=FinancialPeriodType.QUARTERLY,
        metric_code=metric_code,
        value=123.45,
        unit="CNY",
        source="provider-main",
        report_date=date(2026, 9, 13),
        available_at=_AVAILABLE_AT,
        fetched_at=_FETCHED_AT,
        source_evidence=FinancialFactSourceEvidence(
            announced_at=_AVAILABLE_AT,
            source_record_id=_SOURCE_RECORD_ID,
            raw_payload_hash=_RAW_HASH,
        ),
        decision_evidence=_decision_evidence(),
    )


class _Provider:
    """Minimal typed provider returning one requested two-fact batch."""

    def provider_name(self) -> str:
        return "provider-main"

    def fetch_financials(self, _asset_code: str, periods: int = 8) -> list[FinancialFact]:
        return [_fact("revenue"), _fact("net_profit")][:periods]


class _ProviderRepository:
    """Provider configuration port recording health persistence."""

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

    def get_by_id(self, _provider_id: int) -> ProviderConfig:
        return self.config

    def save(self, config: ProviderConfig) -> ProviderConfig:
        self.config = config
        return config


class _ProviderRegistry:
    """Runtime provider port with no pre-existing health snapshots."""

    def get_by_id(self, _provider_id: int) -> _Provider:
        return _Provider()

    def record_success(self, *_args: object) -> None:
        return None

    def record_failure(self, *_args: object) -> None:
        return None


class _Facts:
    """Fact repository double exposing the actual write count contract."""

    def __init__(self, stored_count: int) -> None:
        self.stored_count = stored_count
        self.calls: list[list[FinancialFact]] = []

    def bulk_upsert(self, facts: list[FinancialFact]) -> int:
        self.calls.append(list(facts))
        return self.stored_count


class _RawAudit:
    """In-memory raw-audit writer for status and row-count assertions."""

    def __init__(self) -> None:
        self.items: list[RawAudit] = []

    def log(self, audit: RawAudit) -> RawAudit:
        self.items.append(audit)
        return audit


@pytest.mark.parametrize(
    ("stored_count", "expected_status", "expected_audit_status"),
    [(0, "noop", "noop"), (1, "success", "ok")],
)
def test_sync_financial_reports_actual_repository_write_count(
    stored_count: int,
    expected_status: str,
    expected_audit_status: str,
) -> None:
    """No-op replays and mixed batches keep DTO/audit counts truthful."""

    facts = _Facts(stored_count)
    raw_audit = _RawAudit()
    result = SyncFinancialUseCase(
        provider_repo=_ProviderRepository(),
        provider_registry=_ProviderRegistry(),
        fact_repo=facts,
        raw_audit_repo=raw_audit,
        artifact_verifier=lambda _provider, _reference: True,
    ).execute(SyncFinancialRequest(provider_id=1, asset_code="000001.SZ", periods=2))

    assert len(facts.calls) == 1
    assert len(facts.calls[0]) == 2
    assert result.stored_count == stored_count
    assert result.status == expected_status
    assert len(raw_audit.items) == 1
    assert raw_audit.items[0].status == expected_audit_status
    assert raw_audit.items[0].row_count == stored_count
    if stored_count == 0:
        assert raw_audit.items[0].error_message == "provider completed without output"
