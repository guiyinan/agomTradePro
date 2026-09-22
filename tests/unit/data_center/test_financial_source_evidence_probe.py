"""Fail-closed financial source-evidence probe contracts."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, date, datetime
from uuid import UUID

import pytest

from apps.data_center.application.batch_identity import ProviderAssetIdentityError
from apps.data_center.application.dtos import SyncFinancialRequest
from apps.data_center.application.sync_use_cases import SyncFinancialUseCase
from apps.data_center.domain.entities import FinancialFact, ProviderConfig, RawAudit
from apps.data_center.domain.enums import FinancialPeriodType
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
from core.exceptions import InvalidInputError

ANNOUNCED_AT = datetime(2026, 8, 28, 8, 0, tzinfo=UTC)
AVAILABLE_AT = datetime(2026, 8, 28, 8, 1, tzinfo=UTC)
COMPLETED_AT = datetime(2026, 8, 28, 8, 1, 30, tzinfo=UTC)
FETCHED_AT = datetime(2026, 8, 28, 8, 2, tzinfo=UTC)
RAW_HASH = "a" * 64
CAPTURE_ID = UUID("20000000-0000-4000-8000-000000000001")
SOURCE_RECORD_ID = "tushare:fina_indicator:000001.SZ:20260630:roe"


def _decision_evidence() -> FinancialFactDecisionEvidence:
    """Build one typed retained-artifact and native-row binding."""

    response_evidence = FinancialResponseEvidence(
        body_sha256=RAW_HASH,
        body_size_bytes=128,
        response_completed_at=COMPLETED_AT,
        request_scope=FinancialRequestScope(
            provider_name="provider-main",
            dataset_key="equity.financial.fact",
            asset_code="000001.SZ",
            period_limit=1,
        ),
        response_scope=FinancialResponseScope(
            asset_codes=("000001.SZ",),
            period_ends=(date(2026, 6, 30),),
            row_count=1,
        ),
        body_scope=FinancialResponseBodyScope.BATCH,
        response_scope_basis=FinancialResponseScopeBasis.PROVIDER_BODY_VERIFIED,
    )
    return FinancialFactDecisionEvidence(
        artifact_reference=FinancialResponseArtifactRef(
            capture_id=CAPTURE_ID,
            location="financial-response/20000000-0000-4000-8000-000000000001.bin",
            evidence=response_evidence,
            format_version="financial-response-artifact.v1",
            encryption_algorithm="fernet",
            encryption_key_ref="config_center.data02.test-key",
            encryption_key_version="v1",
        ),
        native_asset_code="000001.SZ",
        native_period_end=date(2026, 6, 30),
        native_row_id=SOURCE_RECORD_ID,
    )


def _fact(*, complete: bool) -> FinancialFact:
    """Build one source-complete or deliberately incomplete provider fact."""

    return FinancialFact(
        asset_code="000001.SZ",
        period_end=date(2026, 6, 30),
        period_type=FinancialPeriodType.QUARTERLY,
        metric_code="roe",
        value=12.5,
        unit="%",
        source="provider-main",
        report_date=date(2026, 8, 28),
        available_at=AVAILABLE_AT if complete else None,
        fetched_at=FETCHED_AT,
        extra={},
        source_evidence=(
            FinancialFactSourceEvidence(
                announced_at=ANNOUNCED_AT,
                source_record_id=SOURCE_RECORD_ID,
                raw_payload_hash=RAW_HASH,
            )
            if complete
            else None
        ),
        decision_evidence=_decision_evidence() if complete else None,
    )


class _Provider:
    """Provider double with an explicit fetch counter."""

    def __init__(self, facts: list[FinancialFact]) -> None:
        self.facts = facts
        self.calls = 0

    def provider_name(self) -> str:
        return "provider-main"

    def fetch_financials(self, asset_code: str, periods: int = 8) -> list[FinancialFact]:
        assert asset_code == "000001.SZ"
        assert periods == 1
        self.calls += 1
        return list(self.facts)


class _ProviderRepository:
    """Provider configuration port without persistence side effects."""

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

    def get_by_id(self, provider_id: int) -> ProviderConfig:
        assert provider_id == 1
        return self.config

    def save(self, config: ProviderConfig) -> ProviderConfig:
        self.config = config
        return config


class _ProviderRegistry:
    """Registry double returning the one configured provider."""

    def __init__(self, provider: _Provider) -> None:
        self.provider = provider
        self.success_count = 0
        self.failure_count = 0

    def get_by_id(self, provider_id: int) -> _Provider:
        assert provider_id == 1
        return self.provider

    def record_success(self, *_args: object) -> None:
        self.success_count += 1

    def record_failure(self, *_args: object) -> None:
        self.failure_count += 1


class _Facts:
    """Fact repository double recording normalized financial writes."""

    def __init__(self) -> None:
        self.calls: list[list[FinancialFact]] = []

    def bulk_upsert(self, facts: list[FinancialFact]) -> int:
        self.calls.append(list(facts))
        return len(facts)


class _RawAudit:
    """Sync-audit double recording only execute-path outcomes."""

    def __init__(self) -> None:
        self.items: list[RawAudit] = []

    def log(self, audit: RawAudit) -> RawAudit:
        self.items.append(audit)
        return audit


class _Publisher:
    """Publication double recording any attempted batch publication."""

    def __init__(self) -> None:
        self.calls: list[list[FinancialFact]] = []

    def execute(self, facts: list[FinancialFact], *, provider_name: str) -> None:
        assert provider_name == "provider-main"
        self.calls.append(list(facts))


def _use_case(
    provider: _Provider,
    *,
    artifact_retained: bool = True,
) -> tuple[SyncFinancialUseCase, _Facts, _RawAudit, _Publisher]:
    facts = _Facts()
    audit = _RawAudit()
    publisher = _Publisher()
    return (
        SyncFinancialUseCase(
            provider_repo=_ProviderRepository(),
            provider_registry=_ProviderRegistry(provider),
            fact_repo=facts,
            raw_audit_repo=audit,
            publication_publisher=publisher,
            artifact_verifier=lambda _provider, _reference: artifact_retained,
        ),
        facts,
        audit,
        publisher,
    )


def test_source_evidence_probe_fetches_without_fact_publication_or_sync_audit_writes() -> None:
    """The explicit probe classifies provider facts without normalized writes."""

    provider = _Provider([_fact(complete=False)])
    use_case, facts, audit, publisher = _use_case(provider)

    result = use_case.probe_source_evidence(
        SyncFinancialRequest(provider_id=1, asset_code="000001.SZ", periods=1)
    )

    assert provider.calls == 1
    assert result.fact_count == 1
    assert result.decision_ready is False
    assert set(result.block_reasons) == {
        "financial_source_evidence_missing",
        "financial_available_at_missing",
        "financial_decision_evidence_missing",
    }
    assert facts.calls == []
    assert publisher.calls == []
    assert audit.items == []


def test_strict_financial_sync_blocks_incomplete_evidence_before_fact_write() -> None:
    """DATA-02 strict mode must not persist a provider fact before evidence passes."""

    provider = _Provider([_fact(complete=False)])
    use_case, facts, audit, publisher = _use_case(provider)

    with pytest.raises(InvalidInputError) as caught:
        use_case.execute(
            SyncFinancialRequest(
                provider_id=1,
                asset_code="000001.SZ",
                periods=1,
            )
        )

    assert caught.value.code == "FINANCIAL_SOURCE_EVIDENCE_REQUIRED"
    assert provider.calls == 1
    assert facts.calls == []
    assert publisher.calls == []
    assert len(audit.items) == 1
    assert audit.items[0].status == "error"
    assert audit.items[0].row_count == 0


def test_strict_financial_sync_persists_only_complete_bound_evidence() -> None:
    """A complete timestamp and body binding may cross the normalized write boundary."""

    provider = _Provider([_fact(complete=True)])
    use_case, facts, audit, publisher = _use_case(provider)

    probe = use_case.probe_source_evidence(
        SyncFinancialRequest(provider_id=1, asset_code="000001.SZ", periods=1)
    )
    result = use_case.execute(
        SyncFinancialRequest(
            provider_id=1,
            asset_code="000001.SZ",
            periods=1,
        )
    )

    assert probe.decision_ready is True
    assert probe.complete_fact_count == 1
    assert probe.block_reasons == ()
    assert len(facts.calls) == 1
    assert facts.calls[0][0].extra == {
        "financial_response_capture_id": str(CAPTURE_ID),
        "provider_name": "provider-main",
        "raw_payload_scope": "batch_response_body",
        "response_scope_basis": "provider_body_verified",
        "source_type": "tushare",
    }
    assert publisher.calls == facts.calls
    assert result.stored_count == 1
    assert audit.items[-1].status == "ok"
    assert provider.calls == 2


def test_financial_request_cannot_disable_decision_evidence() -> None:
    """Every reachable FinancialFact writer keeps the evidence gate enabled."""

    with pytest.raises(ValueError, match="must remain enabled"):
        SyncFinancialRequest(
            provider_id=1,
            asset_code="000001.SZ",
            periods=1,
            require_decision_evidence=False,
        )


def test_source_evidence_probe_requires_a_retained_audited_artifact() -> None:
    """Typed metadata alone cannot substitute for body-store and audit existence."""

    use_case, facts, audit, publisher = _use_case(
        _Provider([_fact(complete=True)]),
        artifact_retained=False,
    )

    result = use_case.probe_source_evidence(
        SyncFinancialRequest(provider_id=1, asset_code="000001.SZ", periods=1)
    )

    assert result.decision_ready is False
    assert result.block_reasons == ("financial_response_artifact_not_retained",)
    assert facts.calls == []
    assert publisher.calls == []
    assert audit.items == []


@pytest.mark.parametrize(
    ("request_scope", "reason"),
    [
        (
            FinancialRequestScope(
                provider_name="different-provider",
                dataset_key="equity.financial.fact",
                asset_code="000001.SZ",
                period_limit=1,
            ),
            "financial_response_provider_identity_mismatch",
        ),
        (
            FinancialRequestScope(
                provider_name="provider-main",
                dataset_key="equity.financial.fact",
                asset_code="000001.SZ",
                period_limit=2,
            ),
            "financial_response_period_limit_mismatch",
        ),
    ],
)
def test_source_evidence_probe_binds_provider_and_period_request_scope(
    request_scope: FinancialRequestScope,
    reason: str,
) -> None:
    """A retained body must belong to the exact configured provider request."""

    decision = _decision_evidence()
    artifact = decision.artifact_reference
    mismatched = replace(
        decision,
        artifact_reference=replace(
            artifact,
            evidence=replace(artifact.evidence, request_scope=request_scope),
        ),
    )
    use_case, _facts, _audit, _publisher = _use_case(
        _Provider([replace(_fact(complete=True), decision_evidence=mismatched)])
    )

    result = use_case.probe_source_evidence(
        SyncFinancialRequest(provider_id=1, asset_code="000001.SZ", periods=1)
    )

    assert result.decision_ready is False
    assert reason in result.block_reasons


def test_prepared_financial_sync_reuses_the_verified_fetch_for_write() -> None:
    """Backfill preparation and write consume one identical provider batch."""

    provider = _Provider([_fact(complete=True)])
    use_case, facts, audit, publisher = _use_case(provider)

    prepared = use_case.prepare_for_write(
        SyncFinancialRequest(provider_id=1, asset_code="000001.SZ", periods=1)
    )
    result = use_case.execute_prepared(prepared)

    assert provider.calls == 1
    assert len(facts.calls) == 1
    assert publisher.calls == facts.calls
    assert result.stored_count == 1
    assert audit.items[-1].status == "ok"


def test_source_evidence_probe_rejects_substituted_asset_before_any_write() -> None:
    """A canonical but different provider asset cannot cross the probe boundary."""

    provider = _Provider([replace(_fact(complete=True), asset_code="600000.SH")])
    use_case, facts, audit, publisher = _use_case(provider)

    with pytest.raises(ProviderAssetIdentityError):
        use_case.probe_source_evidence(
            SyncFinancialRequest(provider_id=1, asset_code="000001.SZ", periods=1)
        )

    assert facts.calls == []
    assert publisher.calls == []
    assert audit.items == []


@pytest.mark.parametrize(
    ("fact", "reason"),
    [
        (
            replace(_fact(complete=True), available_at=datetime(2026, 8, 27, tzinfo=UTC)),
            "financial_source_time_order_invalid",
        ),
        (
            replace(
                _fact(complete=True),
                source_evidence=FinancialFactSourceEvidence(
                    announced_at=ANNOUNCED_AT,
                    source_record_id=SOURCE_RECORD_ID,
                    raw_payload_hash="b" * 64,
                ),
            ),
            "financial_response_body_hash_mismatch",
        ),
        (
            replace(
                _fact(complete=True),
                source_evidence=FinancialFactSourceEvidence(
                    announced_at=ANNOUNCED_AT,
                    source_record_id="tushare:other-native-row",
                    raw_payload_hash=RAW_HASH,
                ),
            ),
            "financial_native_row_identity_mismatch",
        ),
        (
            replace(
                _fact(complete=True),
                decision_evidence=None,
                extra={
                    "raw_payload_scope": "batch_response_body",
                    "response_scope_basis": "provider_body_verified",
                    "financial_response_capture_id": str(CAPTURE_ID),
                },
            ),
            "financial_decision_evidence_missing",
        ),
    ],
)
def test_source_evidence_probe_fails_closed_on_invalid_witness_parts(
    fact: FinancialFact,
    reason: str,
) -> None:
    """Invalid chronology or response bindings stay out of the write path."""

    use_case, facts, audit, publisher = _use_case(_Provider([fact]))

    result = use_case.probe_source_evidence(
        SyncFinancialRequest(provider_id=1, asset_code="000001.SZ", periods=1)
    )

    assert result.decision_ready is False
    assert reason in result.block_reasons
    assert facts.calls == []
    assert publisher.calls == []
    assert audit.items == []


def test_source_evidence_probe_rejects_duplicate_financial_natural_key() -> None:
    """Repeated provider rows cannot inflate a source-complete financial batch."""

    fact = _fact(complete=True)
    use_case, facts, audit, publisher = _use_case(_Provider([fact, fact]))

    result = use_case.probe_source_evidence(
        SyncFinancialRequest(provider_id=1, asset_code="000001.SZ", periods=1)
    )

    assert result.decision_ready is False
    assert result.complete_fact_count == 1
    assert result.block_reasons == ("financial_natural_key_duplicate",)
    assert facts.calls == []
    assert publisher.calls == []
    assert audit.items == []
