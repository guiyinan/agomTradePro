"""Fake-egress contracts for retained AKShare financial response pairs."""

from __future__ import annotations

import hashlib
from collections.abc import Mapping
from dataclasses import dataclass, replace
from datetime import UTC, date, datetime
from pathlib import Path
from uuid import UUID

import pytest
from cryptography.fernet import Fernet

from apps.data_center import akshare_financial_capture_composition as composition
from apps.data_center import akshare_financial_slice_sync_composition as financial_slice_composition
from apps.data_center.akshare_financial_capture_composition import (
    AKSHARE_FINANCIAL_DATASET_KEY,
    AKSHARE_MAIN_FINANCIAL_DATA_ENDPOINT_URL,
    AKSHARE_SOURCE_TIME_DATASET_KEY,
    AkshareFinancialCaptureError,
    AkshareFinancialCaptureGateway,
)
from apps.data_center.application.egress_service import FinancialResponseCaptureProtocol
from apps.data_center.application.financial_slice_sync import (
    FinancialAnnouncementSlice,
    FinancialSliceSyncBudget,
    FinancialSliceSyncRequest,
    FinancialSliceSyncResult,
    SyncAkshareFinancialSlicesUseCase,
)
from apps.data_center.domain.egress_routing import EgressRequestContext
from apps.data_center.domain.entities import (
    FinancialFact,
    ProviderConfig,
    RawAudit,
    raw_audit_content_hash,
)
from apps.data_center.domain.financial_response_evidence import (
    FinancialRequestScope,
    FinancialResponseEvidence,
    FinancialResponseScope,
    raw_body_sha256,
)
from apps.data_center.infrastructure import akshare_financial_slice_sync
from apps.data_center.infrastructure._provider_adapter_akshare import (
    AkshareUnifiedProviderAdapter,
)
from apps.data_center.infrastructure.financial_response_artifact_config import (
    FinancialResponseArtifactRuntimeConfig,
)
from apps.data_center.infrastructure.financial_response_artifact_repository import (
    FinancialResponseArtifactRepository,
    reference_from_audit,
)
from apps.data_center.infrastructure.financial_response_body_store import (
    FinancialResponseArtifactConfigurationError,
    FinancialResponseBodyStore,
)
from apps.data_center.infrastructure.financial_source_time_artifact_repository import (
    FinancialSourceTimeArtifactRepository,
)
from apps.data_center.infrastructure.financial_source_time_audit import (
    StrictFinancialSourceTimeAuditLinkVerifier,
)
from apps.data_center.infrastructure.financial_source_time_audit_repository import (
    DjangoFinancialSourceTimeArtifactAuditRepository,
)
from apps.data_center.infrastructure.financial_source_time_body_store import (
    FinancialSourceTimeBodyStore,
)
from core.exceptions import DataFetchError

ASSET_CODE = "000001.SZ"
ANNOUNCEMENT_DATE = date(2026, 8, 15)
CAPTURE_IDS = (
    UUID("a1cbffca-a92b-42ab-ae10-0604e034db90"),
    UUID("73cc8be5-2825-4cb5-aa63-36518b1080e7"),
)
FINANCIAL_BODY = (
    b'{"success":true,"code":0,"result":{"count":1,"data":'
    b'[{"SECUCODE":"000001.SZ","REPORT_DATE":"2026-06-30 00:00:00",'
    b'"NOTICE_DATE":"2026-08-15 00:00:00","TOTALOPERATEREVE":1000000,'
    b'"PARENTNETPROFIT":250000,"TOTALOPERATEREVETZ":8.5,'
    b'"PARENTNETPROFITTZ":12.0,"ROEJQ":7.5,"ZCFZL":50,'
    b'"LIABILITY":500000,"TOTAL_ASSETS":1000000,"TOTAL_EQUITY":500000,'
    b'"JROA":3.8}]}}'
)
SOURCE_TIME_BODY = (
    b'{\n  "success": true,\n  "code": 0,\n  "result": {\n'
    b'    "count": 1,\n    "data": [{\n'
    b'      "SECUCODE": "000001.SZ",\n'
    b'      "REPORT_DATE": "2026-06-30 00:00:00",\n'
    b'      "NOTICE_DATE": "2026-08-15 00:00:00",\n'
    b'      "TOTALOPERATEREVE": 1000000,\n'
    b'      "PARENTNETPROFIT": 250000,\n'
    b'      "TOTALOPERATEREVETZ": 8.5,\n'
    b'      "PARENTNETPROFITTZ": 12.0,\n'
    b'      "ROEJQ": 7.5,\n'
    b'      "ZCFZL": 50,\n'
    b'      "LIABILITY": 500000,\n'
    b'      "TOTAL_ASSETS": 1000000,\n'
    b'      "TOTAL_EQUITY": 500000,\n'
    b'      "JROA": 3.8\n'
    b"    }]\n  }\n}"
)
COMPLETED_AT = datetime(2026, 8, 28, 7, 32, tzinfo=UTC)


@dataclass(frozen=True, slots=True)
class _Capture:
    """Structural exact-byte response returned by the fake egress runner."""

    payload: object
    evidence: FinancialResponseEvidence
    raw_body: bytes


class _CaptureIdFactory:
    """Yield deterministic request identities for independent captures."""

    def __init__(self, values: tuple[UUID, ...] = CAPTURE_IDS) -> None:
        self._values = iter(values)

    def __call__(self) -> UUID:
        return next(self._values)


class _Runner:
    """Return queued provider bytes while recording both egress requests."""

    def __init__(self, bodies: Mapping[str, bytes]) -> None:
        self._bodies = dict(bodies)
        self.calls: list[tuple[EgressRequestContext, UUID, Mapping[str, object]]] = []

    def __call__(
        self,
        context: EgressRequestContext,
        *,
        request_id: UUID,
        method: str,
        params: Mapping[str, object] | None,
        json_body: Mapping[str, object] | None,
        headers: Mapping[str, str] | None,
        request_scope: FinancialRequestScope,
        response_scope: FinancialResponseScope,
        max_attempts: int = 2,
    ) -> FinancialResponseCaptureProtocol:
        """Synthesize the transport's immutable capture projection."""

        assert method == "GET"
        assert json_body is None
        assert headers is None
        assert max_attempts == 2
        assert params is not None
        body = self._bodies[context.dataset_key]
        self.calls.append((context, request_id, dict(params)))
        evidence = FinancialResponseEvidence(
            body_sha256=raw_body_sha256(body),
            body_size_bytes=len(body),
            response_completed_at=COMPLETED_AT,
            request_scope=request_scope,
            response_scope=response_scope,
        )
        return _Capture(payload={}, evidence=evidence, raw_body=body)


class _ProviderConfigs:
    """Return one exact provider row while recording application lookups."""

    def __init__(self, config: ProviderConfig | None = None) -> None:
        self.config = config or _provider()
        self.lookups: list[int] = []

    def get_by_id(self, provider_id: int) -> ProviderConfig | None:
        """Return the configured row only for its exact ID."""

        self.lookups.append(provider_id)
        return self.config if self.config.id == provider_id else None


class _Registry:
    """Expose one row-bound provider object without any fallback lookup."""

    def __init__(self, provider: AkshareUnifiedProviderAdapter | None) -> None:
        self.provider = provider
        self.lookups: list[int] = []

    def get_by_id(self, provider_id: int) -> AkshareUnifiedProviderAdapter | None:
        """Return the provider only when its row identity is requested."""

        self.lookups.append(provider_id)
        if self.provider is None:
            return None
        try:
            return self.provider if self.provider.provider_id() == provider_id else None
        except ValueError:
            return None


class _FactWriter:
    """Count financial batch writes and retain the exact submitted facts."""

    def __init__(self, stored_count: int | None = None) -> None:
        self.calls: list[list[object]] = []
        self.stored_count = stored_count

    def bulk_upsert(self, facts) -> int:
        """Record one atomic-batch call and report all rows as stored."""

        self.calls.append(list(facts))
        return len(facts) if self.stored_count is None else self.stored_count


class _SequenceFetcher:
    """Return one successful slice and then synthesize a provider outage."""

    def __init__(self, facts: list[FinancialFact]) -> None:
        self.facts = facts
        self.calls = 0

    def fetch_financials_for_announcement_date(
        self,
        asset_code: str,
        announcement_date: date,
        periods: int,
    ) -> list[FinancialFact]:
        """Return the first slice and fail the next provider request group."""

        del asset_code, announcement_date, periods
        self.calls += 1
        if self.calls == 1:
            return self.facts
        raise DataFetchError("synthetic second-slice provider outage")


class _Audits:
    """Append-only in-memory RawAudit port with selective failure injection."""

    def __init__(
        self,
        *,
        fail_financial: bool = False,
        fail_source_time: bool = False,
        duplicate_source_capture_id: UUID | None = None,
    ) -> None:
        self.financial_rows: list[RawAudit] = []
        self.source_time_rows: list[RawAudit] = []
        self.fail_financial = fail_financial
        self.fail_source_time = fail_source_time
        self.duplicate_source_capture_id = duplicate_source_capture_id
        self.financial_log_calls = 0
        self.source_time_log_calls = 0

    def log(self, audit: RawAudit) -> RawAudit:
        """Append a financial artifact audit or simulate a storage failure."""

        self.financial_log_calls += 1
        if self.fail_financial:
            raise OSError("synthetic financial audit failure")
        persisted = replace(audit, raw_audit_id=str(self.financial_log_calls))
        self.financial_rows.append(persisted)
        return persisted

    def find_by_artifact_capture_id(self, capture_id: UUID) -> RawAudit | None:
        """Return the financial audit bound to the requested capture UUID."""

        expected = str(capture_id)
        for row in self.financial_rows:
            link = row.extra.get("financial_response_artifact")
            if isinstance(link, Mapping) and link.get("capture_id") == expected:
                return row
        return None

    def log_failure(self, audit: RawAudit) -> RawAudit:
        """Keep the fake complete for the financial repository port."""

        return self.log(audit)

    def find_by_failure_capture_id(self, capture_id: UUID) -> RawAudit | None:
        """There are no rejected-body audit rows in these success-path tests."""

        del capture_id
        return None

    def list_by_source_time_artifact_capture_id(self, capture_id: UUID) -> list[RawAudit]:
        """Return every existing source-time claim without truncating cardinality."""

        if capture_id == self.duplicate_source_capture_id:
            first = _duplicate_source_audit(capture_id)
            return [first, replace(first, raw_audit_id="duplicate")]
        expected = str(capture_id)
        return [
            row
            for row in self.source_time_rows
            if row.extra["financial_source_time_artifact"]["capture_id"] == expected
        ]

    def log_source_time(self, audit: RawAudit) -> RawAudit:
        """Append one canonical source-time audit or inject failure."""

        self.source_time_log_calls += 1
        if self.fail_source_time:
            raise OSError("synthetic source-time audit failure")
        persisted = replace(
            audit,
            raw_audit_id=str(self.source_time_log_calls),
            content_hash=raw_audit_content_hash(audit),
        )
        self.source_time_rows.append(persisted)
        return persisted


def _duplicate_source_audit(capture_id: UUID) -> RawAudit:
    """Build a minimally valid audit-shaped duplicate for cardinality checks."""

    return RawAudit(
        provider_name="akshare",
        capability="financial_source_time",
        request_params={},
        status="ok",
        extra={"financial_source_time_artifact": {"capture_id": str(capture_id)}},
    )


def _provider() -> ProviderConfig:
    """Return an active row whose display name differs from its logical source."""

    return ProviderConfig(
        id=17,
        name="AKShare Public",
        source_type="akshare",
        is_active=True,
        priority=1,
        api_key="",
        api_secret="",
        http_url="",
        api_endpoint="",
        extra_config={},
        description="test provider",
    )


def _gateway(
    tmp_path: Path,
    runner: _Runner,
    audits: _Audits | None = None,
    *,
    capture_ids: tuple[UUID, ...] = CAPTURE_IDS,
    provider: ProviderConfig | None = None,
) -> tuple[
    AkshareFinancialCaptureGateway,
    _Audits,
    FinancialResponseBodyStore,
    FinancialSourceTimeBodyStore,
]:
    """Build real encrypted stores and repository adapters around fake ports."""

    audit_port = audits or _Audits()
    key = Fernet.generate_key()
    financial_store = FinancialResponseBodyStore(
        tmp_path / "financial",
        encryption_key=key,
        encryption_key_ref="test/financial-body-key",
        encryption_key_version="test-v1",
        max_body_bytes=1024 * 1024,
    )
    source_time_store = FinancialSourceTimeBodyStore(
        tmp_path / "source-time",
        encryption_key=key,
        encryption_key_ref="test/financial-body-key",
        encryption_key_version="test-v1",
        max_body_bytes=1024 * 1024,
    )
    gateway = AkshareFinancialCaptureGateway(
        provider or _provider(),
        deployment_region="test-region",
        financial_repository=FinancialResponseArtifactRepository(
            financial_store,
            audit_port,
            failure_audit_repository=audit_port,
        ),
        source_time_repository=FinancialSourceTimeArtifactRepository(
            source_time_store,
            audit_port,
        ),
        capture_runner=runner,
        capture_id_factory=_CaptureIdFactory(capture_ids),
    )
    return gateway, audit_port, financial_store, source_time_store


def _capture_pair(gateway: AkshareFinancialCaptureGateway, *, period_limit: int = 8):
    """Retain one pair from gateway-built, asset/date-bound request parameters."""

    return gateway.capture_and_retain(
        asset_code=ASSET_CODE,
        period_limit=period_limit,
        announcement_date=ANNOUNCEMENT_DATE,
    )


def test_akshare_financial_capture_retains_independent_exact_body_pair(tmp_path: Path) -> None:
    """Capture IDs and exact response bytes stay independent across both artifacts."""

    runner = _Runner(
        {
            AKSHARE_FINANCIAL_DATASET_KEY: FINANCIAL_BODY,
            AKSHARE_SOURCE_TIME_DATASET_KEY: SOURCE_TIME_BODY,
        }
    )
    gateway, audits, financial_store, source_time_store = _gateway(tmp_path, runner)

    retained = _capture_pair(gateway)

    assert [call[0].dataset_key for call in runner.calls] == [
        AKSHARE_FINANCIAL_DATASET_KEY,
        AKSHARE_SOURCE_TIME_DATASET_KEY,
    ]
    assert [call[0].target_url for call in runner.calls] == [
        AKSHARE_MAIN_FINANCIAL_DATA_ENDPOINT_URL,
        AKSHARE_MAIN_FINANCIAL_DATA_ENDPOINT_URL,
    ]
    assert [call[1] for call in runner.calls] == list(CAPTURE_IDS)
    assert runner.calls[0][2] == runner.calls[1][2]
    assert runner.calls[0][2] == {
        "type": "RPT_F10_FINANCE_MAINFINADATA",
        "sty": "APP_F10_MAINFINADATA",
        "quoteColumns": "",
        "filter": "(SECUCODE=\"000001.SZ\")(NOTICE_DATE='2026-08-15')",
        "p": "1",
        "ps": "8",
        "sr": "-1",
        "st": "REPORT_DATE",
        "source": "HSF10",
        "client": "PC",
    }
    assert retained.financial.reference.capture_id != retained.source_time.reference.capture_id
    assert financial_store.read(retained.financial.reference) == FINANCIAL_BODY
    assert source_time_store.read(retained.source_time.reference) == SOURCE_TIME_BODY
    assert FINANCIAL_BODY != SOURCE_TIME_BODY
    assert retained.financial.reference.body_sha256 == hashlib.sha256(FINANCIAL_BODY).hexdigest()
    assert (
        retained.source_time.reference.body_sha256 == hashlib.sha256(SOURCE_TIME_BODY).hexdigest()
    )
    assert len(audits.financial_rows) == 1
    assert len(audits.source_time_rows) == 1
    assert retained.financial.audit.capability == "financial"
    assert retained.source_time.audit.capability == "financial_source_time"
    links = StrictFinancialSourceTimeAuditLinkVerifier(expected_provider_id=17)
    assert links.verify_financial(retained.financial.audit, retained.financial.reference) == 17
    assert (
        links.verify_source_time(retained.source_time.audit, retained.source_time.reference) == 17
    )
    wrong_row = StrictFinancialSourceTimeAuditLinkVerifier(expected_provider_id=18)
    assert (
        wrong_row.verify_financial(retained.financial.audit, retained.financial.reference) is None
    )
    assert (
        wrong_row.verify_source_time(retained.source_time.audit, retained.source_time.reference)
        is None
    )


def test_akshare_adapter_builds_typed_facts_from_two_retained_raw_bodies(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The one-date adapter path binds raw EastMoney metrics to its first witness."""

    runner = _Runner(
        {
            AKSHARE_FINANCIAL_DATASET_KEY: FINANCIAL_BODY,
            AKSHARE_SOURCE_TIME_DATASET_KEY: SOURCE_TIME_BODY,
        }
    )
    gateway, audits, financial_store, source_time_store = _gateway(tmp_path, runner)
    adapter = AkshareUnifiedProviderAdapter(_provider())
    monkeypatch.setattr(
        "apps.data_center.infrastructure._provider_adapter_akshare.get_akshare_module",
        lambda: pytest.fail("source-time path must not use a normalized DataFrame"),
    )

    facts = adapter.fetch_financials_for_announcement_date(
        ASSET_CODE,
        ANNOUNCEMENT_DATE,
        capture_gateway=gateway,
    )

    assert len(facts) == 10
    assert {fact.metric_code for fact in facts} == {
        "revenue",
        "net_profit",
        "revenue_growth",
        "net_profit_growth",
        "total_assets",
        "total_liabilities",
        "equity",
        "roe",
        "roa",
        "debt_ratio",
    }
    assert len(audits.financial_rows) == len(audits.source_time_rows) == 1
    for fact in facts:
        source_evidence = fact.source_evidence
        decision_evidence = fact.decision_evidence
        assert source_evidence is not None and source_evidence.is_complete
        assert decision_evidence is not None
        witness = decision_evidence.source_time_witness
        assert witness is not None
        assert decision_evidence.native_row_id == source_evidence.source_record_id
        assert source_evidence.raw_payload_hash == hashlib.sha256(FINANCIAL_BODY).hexdigest()
        assert source_evidence.announced_at == datetime(2026, 8, 14, 16, tzinfo=UTC)
        assert fact.available_at == datetime(2026, 8, 15, 16, tzinfo=UTC)
        assert (
            witness.artifact_reference.capture_id != decision_evidence.artifact_reference.capture_id
        )
        assert financial_store.read(decision_evidence.artifact_reference) == FINANCIAL_BODY
        assert source_time_store.read(witness.artifact_reference) == SOURCE_TIME_BODY


@pytest.mark.parametrize(
    "failure_stage",
    ["provider", "capture_parse", "witness", "source_time_audit"],
)
def test_akshare_adapter_failures_before_fact_return_leave_zero_persisted_facts(
    tmp_path: Path,
    failure_stage: str,
) -> None:
    """Provider, parsing, witness, and audit failures expose no facts to a writer."""

    rejected_provider_body = b'{"success":false,"code":500,"result":{"count":0,"data":[]}}'
    mismatched_source_body = SOURCE_TIME_BODY.replace(b"2026-06-30", b"2026-03-31", 1)
    financial_body = b"not-json" if failure_stage == "capture_parse" else FINANCIAL_BODY
    source_time_body = (
        rejected_provider_body
        if failure_stage == "provider"
        else mismatched_source_body if failure_stage == "witness" else SOURCE_TIME_BODY
    )
    audits = _Audits(fail_source_time=failure_stage == "source_time_audit")
    runner = _Runner(
        {
            AKSHARE_FINANCIAL_DATASET_KEY: financial_body,
            AKSHARE_SOURCE_TIME_DATASET_KEY: source_time_body,
        }
    )
    gateway, _audits, _financial_store, _source_time_store = _gateway(
        tmp_path,
        runner,
        audits,
    )
    adapter = AkshareUnifiedProviderAdapter(_provider())
    writes: list[object] = []

    def fetch_then_write() -> None:
        candidate_facts = adapter.fetch_financials_for_announcement_date(
            ASSET_CODE,
            ANNOUNCEMENT_DATE,
            capture_gateway=gateway,
        )
        writes.extend(candidate_facts)

    with pytest.raises(DataFetchError) as caught:
        fetch_then_write()

    if failure_stage == "provider":
        assert caught.value.code == "AKSHARE_FINANCIAL_PROVIDER_REJECTED"
    elif failure_stage == "capture_parse":
        assert caught.value.code == "AKSHARE_FINANCIAL_CAPTURE_INVALID"
    elif failure_stage == "witness":
        assert caught.value.code == "AKSHARE_FINANCIAL_FACT_EVIDENCE_INVALID"
    assert writes == []


def test_akshare_financial_capture_rejects_missing_raw_body_before_retention(
    tmp_path: Path,
) -> None:
    """An empty raw buffer cannot be replaced by a decoded or normalized payload."""

    runner = _Runner(
        {
            AKSHARE_FINANCIAL_DATASET_KEY: b"",
            AKSHARE_SOURCE_TIME_DATASET_KEY: SOURCE_TIME_BODY,
        }
    )
    gateway, audits, _financial_store, _source_time_store = _gateway(tmp_path, runner)

    with pytest.raises(AkshareFinancialCaptureError):
        _capture_pair(gateway)

    assert audits.financial_rows == []
    assert audits.source_time_rows == []
    assert list((tmp_path / "financial").rglob("*.bin")) == []
    assert list((tmp_path / "source-time").rglob("*.bin")) == []


def test_akshare_financial_capture_provider_failure_does_not_retain_any_artifact(
    tmp_path: Path,
) -> None:
    """A provider business rejection on the second call writes neither artifact."""

    rejected_body = b'{"success":false,"code":500,"result":{"count":0,"data":[]}}'
    runner = _Runner(
        {
            AKSHARE_FINANCIAL_DATASET_KEY: FINANCIAL_BODY,
            AKSHARE_SOURCE_TIME_DATASET_KEY: rejected_body,
        }
    )
    gateway, audits, _financial_store, _source_time_store = _gateway(tmp_path, runner)

    with pytest.raises(DataFetchError) as caught:
        _capture_pair(gateway)

    assert caught.value.code == "AKSHARE_FINANCIAL_PROVIDER_REJECTED"
    assert len(runner.calls) == 2
    assert audits.financial_rows == []
    assert audits.source_time_rows == []
    assert list((tmp_path / "financial").rglob("*.bin")) == []
    assert list((tmp_path / "source-time").rglob("*.bin")) == []


def test_akshare_financial_capture_rejects_duplicate_capture_ids_before_egress(
    tmp_path: Path,
) -> None:
    """The two request identities must differ before either egress call starts."""

    runner = _Runner(
        {
            AKSHARE_FINANCIAL_DATASET_KEY: FINANCIAL_BODY,
            AKSHARE_SOURCE_TIME_DATASET_KEY: SOURCE_TIME_BODY,
        }
    )
    gateway, audits, _financial_store, _source_time_store = _gateway(
        tmp_path,
        runner,
        capture_ids=(CAPTURE_IDS[0], CAPTURE_IDS[0]),
    )

    with pytest.raises(AkshareFinancialCaptureError):
        _capture_pair(gateway)

    assert runner.calls == []
    assert audits.financial_rows == []
    assert audits.source_time_rows == []


def test_akshare_financial_capture_rejects_page_size_above_provider_limit_before_egress(
    tmp_path: Path,
) -> None:
    """The caller cannot expand an EastMoney read beyond its 200-row page cap."""

    runner = _Runner(
        {
            AKSHARE_FINANCIAL_DATASET_KEY: FINANCIAL_BODY,
            AKSHARE_SOURCE_TIME_DATASET_KEY: SOURCE_TIME_BODY,
        }
    )
    gateway, audits, _financial_store, _source_time_store = _gateway(tmp_path, runner)

    with pytest.raises(AkshareFinancialCaptureError):
        _capture_pair(gateway, period_limit=201)

    assert runner.calls == []
    assert audits.financial_rows == []
    assert audits.source_time_rows == []


@pytest.mark.parametrize(
    "provider",
    [
        replace(_provider(), source_type="tushare"),
        replace(_provider(), is_active=False),
        replace(_provider(), id=None),
    ],
)
def test_akshare_financial_capture_requires_active_source_row_identity_before_egress(
    tmp_path: Path,
    provider: ProviderConfig,
) -> None:
    """Display names are allowed, but source type, active flag, and ID are strict."""

    runner = _Runner(
        {
            AKSHARE_FINANCIAL_DATASET_KEY: FINANCIAL_BODY,
            AKSHARE_SOURCE_TIME_DATASET_KEY: SOURCE_TIME_BODY,
        }
    )

    with pytest.raises(AkshareFinancialCaptureError):
        _gateway(tmp_path, runner, provider=provider)

    assert runner.calls == []


def test_akshare_financial_capture_duplicate_source_audits_block_source_body_write(
    tmp_path: Path,
) -> None:
    """Ambiguous source-time audit cardinality fails before source body storage."""

    audits = _Audits(duplicate_source_capture_id=CAPTURE_IDS[1])
    runner = _Runner(
        {
            AKSHARE_FINANCIAL_DATASET_KEY: FINANCIAL_BODY,
            AKSHARE_SOURCE_TIME_DATASET_KEY: SOURCE_TIME_BODY,
        }
    )
    gateway, _audits, _financial_store, _source_time_store = _gateway(tmp_path, runner, audits)

    with pytest.raises(DataFetchError) as caught:
        _capture_pair(gateway)

    assert caught.value.code == "FINANCIAL_SOURCE_TIME_ARTIFACT_REPLAY_CONFLICT"
    assert len(audits.financial_rows) == 1
    assert audits.source_time_log_calls == 0
    assert list((tmp_path / "source-time").rglob("*.bin")) == []


@pytest.mark.parametrize("failed_side", ["financial", "source_time"])
def test_akshare_financial_capture_audit_append_failure_exposes_orphan(
    tmp_path: Path,
    failed_side: str,
) -> None:
    """A body published before audit failure remains inspectable as an orphan."""

    audits = _Audits(
        fail_financial=failed_side == "financial",
        fail_source_time=failed_side == "source_time",
    )
    runner = _Runner(
        {
            AKSHARE_FINANCIAL_DATASET_KEY: FINANCIAL_BODY,
            AKSHARE_SOURCE_TIME_DATASET_KEY: SOURCE_TIME_BODY,
        }
    )
    gateway, _audits, financial_store, source_time_store = _gateway(tmp_path, runner, audits)

    with pytest.raises(DataFetchError) as caught:
        _capture_pair(gateway)

    if failed_side == "financial":
        orphan = gateway._financial_repository.inspect_orphan(caught.value.reference)
        assert orphan.is_orphan is True
        assert financial_store.read(orphan.reference) == FINANCIAL_BODY
        assert audits.source_time_log_calls == 0
    else:
        orphan = gateway._source_time_repository.inspect_orphan(caught.value.reference)
        assert orphan.is_orphan is True
        assert source_time_store.read(orphan.reference) == SOURCE_TIME_BODY
        assert len(audits.financial_rows) == 1
        financial_reference = reference_from_audit(audits.financial_rows[0])
        assert financial_store.read(financial_reference) == FINANCIAL_BODY


def test_akshare_financial_capture_composition_uses_approved_registry_and_dual_repositories(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Production composition wires the shared RawAudit owner and both stores."""

    key = Fernet.generate_key()
    runtime = FinancialResponseArtifactRuntimeConfig(
        root=tmp_path / "composed",
        encryption_key=key,
        encryption_key_ref="test/composed-financial-key",
        encryption_key_version="test-v1",
        max_body_bytes=1024 * 1024,
    )
    monkeypatch.setattr(
        composition, "resolve_financial_response_artifact_config", lambda **_: runtime
    )
    monkeypatch.setattr(composition, "RawAuditRepository", _Audits)
    monkeypatch.setattr(composition.settings, "BASE_DIR", Path(__file__).parents[3])

    gateway = composition.build_akshare_financial_capture_gateway(
        _provider(),
        deployment_region="test-region",
        environment="test",
    )

    assert gateway._capture_runner is composition.execute_financial_response_request
    assert isinstance(
        gateway._source_time_repository._retainer._audit_repository,
        DjangoFinancialSourceTimeArtifactAuditRepository,
    )
    assert gateway._financial_repository._body_store._root == (tmp_path / "composed").resolve()
    assert gateway._source_time_repository._body_store._root == (tmp_path / "composed").resolve()
    assert (
        gateway._financial_repository._body_store is not gateway._source_time_repository._body_store
    )


def test_akshare_financial_capture_registry_mismatch_blocks_before_egress(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Runtime capture rechecks the exact approved registry identity before transport."""

    class _NoContractRegistry:
        def get(self, **_kwargs: object) -> None:
            return None

    runner = _Runner(
        {
            AKSHARE_FINANCIAL_DATASET_KEY: FINANCIAL_BODY,
            AKSHARE_SOURCE_TIME_DATASET_KEY: SOURCE_TIME_BODY,
        }
    )
    gateway, audits, _financial_store, _source_time_store = _gateway(tmp_path, runner)
    monkeypatch.setattr(
        composition,
        "load_financial_source_time_contract_registry",
        lambda _path: _NoContractRegistry(),
    )

    with pytest.raises(FinancialResponseArtifactConfigurationError):
        _capture_pair(gateway)

    assert runner.calls == []
    assert audits.financial_rows == []
    assert audits.source_time_rows == []


def test_akshare_financial_slice_sync_uses_exact_approved_route_and_one_atomic_write(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The controlled entrypoint reaches only the retained-body AKShare adapter."""

    runner = _Runner(
        {
            AKSHARE_FINANCIAL_DATASET_KEY: FINANCIAL_BODY,
            AKSHARE_SOURCE_TIME_DATASET_KEY: SOURCE_TIME_BODY,
        }
    )
    gateway, audits, _financial_store, _source_time_store = _gateway(tmp_path, runner)
    provider = AkshareUnifiedProviderAdapter(_provider())
    writer = _FactWriter()
    configs = _ProviderConfigs()
    registry = _Registry(provider)
    gateway_builds: list[tuple[int | None, str]] = []

    def _build_gateway(config: ProviderConfig, *, deployment_region: str):
        gateway_builds.append((config.id, deployment_region))
        return gateway

    monkeypatch.setattr(
        akshare_financial_slice_sync,
        "build_akshare_financial_capture_gateway",
        _build_gateway,
    )
    use_case = SyncAkshareFinancialSlicesUseCase(
        provider_repo=configs,
        provider_registry=registry,
        fact_repo=writer,
        fetcher_factory=akshare_financial_slice_sync.build_akshare_financial_slice_fetcher,
        evidence_verifier=lambda _config, _evidence: True,
        request_budget=FinancialSliceSyncBudget(1, 2, 2, 200),
    )

    result = use_case.execute(
        FinancialSliceSyncRequest(
            provider_id=17,
            source="akshare",
            slices=(FinancialAnnouncementSlice(ASSET_CODE, ANNOUNCEMENT_DATE),),
        )
    )

    assert result.to_dict() == {
        "outcome": "success",
        "source": "akshare",
        "provider_id": 17,
        "provider_name": "AKShare Public",
        "requested": 1,
        "succeeded": 1,
        "failed": 0,
        "stored": len(writer.calls[0]),
        "planned_provider_requests": 2,
        "atomic_fact_write_count": 1,
        "failure_reason": None,
    }
    assert result.atomic_fact_write_count == 1
    assert gateway_builds == [(17, "unknown")]
    assert configs.lookups == [17]
    assert registry.lookups == [17]
    assert len(runner.calls) == 2
    assert len(audits.financial_rows) == 1
    assert len(audits.source_time_rows) == 1
    assert len(writer.calls) == 1
    assert all(fact.decision_evidence is not None for fact in writer.calls[0])
    assert all(
        fact.extra["financial_response_capture_id"]
        == str(fact.decision_evidence.artifact_reference.capture_id)
        for fact in writer.calls[0]
    )
    assert all(
        fact.extra["financial_source_time_capture_id"]
        == str(fact.decision_evidence.source_time_witness.artifact_reference.capture_id)
        for fact in writer.calls[0]
    )


def test_akshare_financial_slice_sync_default_source_blocks_without_fallback(
    tmp_path: Path,
) -> None:
    """An omitted source never selects the default provider or performs egress."""

    configs = _ProviderConfigs()
    registry = _Registry(AkshareUnifiedProviderAdapter(_provider()))
    writer = _FactWriter()
    fetcher_calls: list[int] = []
    use_case = SyncAkshareFinancialSlicesUseCase(
        provider_repo=configs,
        provider_registry=registry,
        fact_repo=writer,
        fetcher_factory=lambda _config, _provider: fetcher_calls.append(1),
        evidence_verifier=lambda _config, _evidence: True,
        request_budget=FinancialSliceSyncBudget(1, 2, 2, 200),
    )

    result = use_case.execute(
        FinancialSliceSyncRequest(
            provider_id=17,
            slices=(FinancialAnnouncementSlice(ASSET_CODE, ANNOUNCEMENT_DATE),),
        )
    )

    assert result.outcome == "blocked"
    assert result.failure_reason == "explicit_source_akshare_required"
    assert result.requested == 1
    assert result.failed == 1
    assert result.planned_provider_requests == 2
    assert configs.lookups == []
    assert registry.lookups == []
    assert fetcher_calls == []
    assert writer.calls == []


def test_akshare_financial_slice_sync_zero_store_explains_noop(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A valid idempotent batch reports why no fact row was stored."""

    runner = _Runner(
        {
            AKSHARE_FINANCIAL_DATASET_KEY: FINANCIAL_BODY,
            AKSHARE_SOURCE_TIME_DATASET_KEY: SOURCE_TIME_BODY,
        }
    )
    gateway, _audits, _financial_store, _source_time_store = _gateway(tmp_path, runner)
    provider = AkshareUnifiedProviderAdapter(_provider())
    writer = _FactWriter(stored_count=0)
    monkeypatch.setattr(
        akshare_financial_slice_sync,
        "build_akshare_financial_capture_gateway",
        lambda _config, *, deployment_region: gateway,
    )
    use_case = SyncAkshareFinancialSlicesUseCase(
        provider_repo=_ProviderConfigs(),
        provider_registry=_Registry(provider),
        fact_repo=writer,
        fetcher_factory=akshare_financial_slice_sync.build_akshare_financial_slice_fetcher,
        evidence_verifier=lambda _config, _evidence: True,
        request_budget=FinancialSliceSyncBudget(1, 2, 2, 200),
    )

    result = use_case.execute(
        FinancialSliceSyncRequest(
            provider_id=17,
            source="akshare",
            slices=(FinancialAnnouncementSlice(ASSET_CODE, ANNOUNCEMENT_DATE),),
        )
    )

    assert result.outcome == "noop"
    assert result.requested == result.succeeded == 1
    assert result.failed == result.stored == 0
    assert result.failure_reason == "financial_facts_already_current"
    assert len(writer.calls) == 1


def test_akshare_financial_slice_sync_rejects_wrong_source_and_provider_row(
    tmp_path: Path,
) -> None:
    """Wrong explicit source and non-AKShare provider rows fail before routing."""

    config = replace(_provider(), source_type="tushare")
    configs = _ProviderConfigs(config)
    registry = _Registry(AkshareUnifiedProviderAdapter(_provider()))
    writer = _FactWriter()
    fetcher_calls: list[int] = []
    use_case = SyncAkshareFinancialSlicesUseCase(
        provider_repo=configs,
        provider_registry=registry,
        fact_repo=writer,
        fetcher_factory=lambda _config, _provider: fetcher_calls.append(1),
        evidence_verifier=lambda _config, _evidence: True,
        request_budget=FinancialSliceSyncBudget(1, 2, 2, 200),
    )
    item = FinancialAnnouncementSlice(ASSET_CODE, ANNOUNCEMENT_DATE)

    wrong_source = use_case.execute(
        FinancialSliceSyncRequest(provider_id=17, source="tushare", slices=(item,))
    )
    wrong_provider = use_case.execute(
        FinancialSliceSyncRequest(provider_id=17, source="akshare", slices=(item,))
    )
    wrong_provider_id = use_case.execute(
        FinancialSliceSyncRequest(provider_id=18, source="akshare", slices=(item,))
    )

    assert wrong_source.outcome == "blocked"
    assert wrong_source.failure_reason == "explicit_source_akshare_required"
    assert wrong_provider.outcome == "blocked"
    assert wrong_provider.failure_reason == "exact_active_akshare_provider_required"
    assert wrong_provider_id.outcome == "blocked"
    assert wrong_provider_id.failure_reason == "exact_active_akshare_provider_required"
    assert configs.lookups == [17, 18]
    assert registry.lookups == []
    assert fetcher_calls == []
    assert writer.calls == []


def test_akshare_financial_slice_sync_blocks_when_approval_or_capture_capability_is_missing(
    tmp_path: Path,
) -> None:
    """Approval/capture preflight failure blocks before fetch or fact write."""

    provider = AkshareUnifiedProviderAdapter(_provider())
    writer = _FactWriter()
    runner = _Runner(
        {
            AKSHARE_FINANCIAL_DATASET_KEY: FINANCIAL_BODY,
            AKSHARE_SOURCE_TIME_DATASET_KEY: SOURCE_TIME_BODY,
        }
    )
    fetcher_calls: list[int] = []

    def _reject_preflight(_config: ProviderConfig, _provider: object) -> object:
        raise FinancialResponseArtifactConfigurationError(
            "synthetic missing approved capture capability"
        )

    use_case = SyncAkshareFinancialSlicesUseCase(
        provider_repo=_ProviderConfigs(),
        provider_registry=_Registry(provider),
        fact_repo=writer,
        fetcher_factory=_reject_preflight,
        evidence_verifier=lambda _config, _evidence: True,
        request_budget=FinancialSliceSyncBudget(1, 2, 2, 200),
    )

    result = use_case.execute(
        FinancialSliceSyncRequest(
            provider_id=17,
            source="akshare",
            slices=(FinancialAnnouncementSlice(ASSET_CODE, ANNOUNCEMENT_DATE),),
        )
    )

    assert result.outcome == "blocked"
    assert result.failure_reason == "owner_approved_capture_capability_unavailable"
    assert result.succeeded == 0
    assert result.failed == 1
    assert runner.calls == []
    assert fetcher_calls == []
    assert writer.calls == []


def test_akshare_financial_slice_fetcher_rejects_adapter_row_drift_before_gateway_build(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A registry adapter with a different persisted row cannot reach capture setup."""

    gateway_builds: list[int] = []

    def _gateway_builder(config: ProviderConfig, *, deployment_region: str) -> object:
        del deployment_region
        gateway_builds.append(config.id or 0)
        raise AssertionError("row drift must stop before gateway creation")

    monkeypatch.setattr(
        akshare_financial_slice_sync,
        "build_akshare_financial_capture_gateway",
        _gateway_builder,
    )

    with pytest.raises(DataFetchError):
        akshare_financial_slice_sync.build_akshare_financial_slice_fetcher(
            _provider(),
            AkshareUnifiedProviderAdapter(replace(_provider(), id=18)),
        )

    assert gateway_builds == []


def test_akshare_financial_slice_sync_evidence_rejection_writes_zero_facts(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A retained-body verifier rejection blocks the whole financial batch."""

    runner = _Runner(
        {
            AKSHARE_FINANCIAL_DATASET_KEY: FINANCIAL_BODY,
            AKSHARE_SOURCE_TIME_DATASET_KEY: SOURCE_TIME_BODY,
        }
    )
    gateway, _audits, _financial_store, _source_time_store = _gateway(tmp_path, runner)
    monkeypatch.setattr(
        akshare_financial_slice_sync,
        "build_akshare_financial_capture_gateway",
        lambda _config, **_kwargs: gateway,
    )
    writer = _FactWriter()
    use_case = SyncAkshareFinancialSlicesUseCase(
        provider_repo=_ProviderConfigs(),
        provider_registry=_Registry(AkshareUnifiedProviderAdapter(_provider())),
        fact_repo=writer,
        fetcher_factory=akshare_financial_slice_sync.build_akshare_financial_slice_fetcher,
        evidence_verifier=lambda _config, _evidence: False,
        request_budget=FinancialSliceSyncBudget(1, 2, 2, 200),
    )

    result = use_case.execute(
        FinancialSliceSyncRequest(
            provider_id=17,
            source="akshare",
            slices=(FinancialAnnouncementSlice(ASSET_CODE, ANNOUNCEMENT_DATE),),
        )
    )

    assert result.outcome == "blocked"
    assert result.requested == 1
    assert result.succeeded == 0
    assert result.failed == 1
    assert result.stored == 0
    assert result.atomic_fact_write_count == 0
    assert len(runner.calls) == 2
    assert writer.calls == []


def test_akshare_financial_slice_sync_scale_gate_counts_two_requests_per_pair(
    tmp_path: Path,
) -> None:
    """The hard cap uses 2N logical provider requests before any route is built."""

    configs = _ProviderConfigs()
    registry = _Registry(AkshareUnifiedProviderAdapter(_provider()))
    writer = _FactWriter()
    fetcher_calls: list[int] = []
    use_case = SyncAkshareFinancialSlicesUseCase(
        provider_repo=configs,
        provider_registry=registry,
        fact_repo=writer,
        fetcher_factory=lambda _config, _provider: fetcher_calls.append(1),
        evidence_verifier=lambda _config, _evidence: True,
        request_budget=FinancialSliceSyncBudget(1, 2, 2, 200),
    )

    result = use_case.execute(
        FinancialSliceSyncRequest(
            provider_id=17,
            source="akshare",
            slices=(
                FinancialAnnouncementSlice(ASSET_CODE, ANNOUNCEMENT_DATE),
                FinancialAnnouncementSlice("600000.SH", ANNOUNCEMENT_DATE),
            ),
        )
    )

    assert result.outcome == "blocked"
    assert result.failure_reason == "financial_provider_request_scale_exceeds_governed_bound"
    assert result.requested == 2
    assert result.succeeded == 0
    assert result.failed == 2
    assert result.stored == 0
    assert result.planned_provider_requests == 4
    assert configs.lookups == []
    assert registry.lookups == []
    assert fetcher_calls == []
    assert writer.calls == []


def test_akshare_financial_slice_sync_partial_provider_failure_writes_zero_facts(
    tmp_path: Path,
) -> None:
    """A failed later slice is partial and the earlier prepared facts stay unwritten."""

    transport = _Runner(
        {
            AKSHARE_FINANCIAL_DATASET_KEY: FINANCIAL_BODY,
            AKSHARE_SOURCE_TIME_DATASET_KEY: SOURCE_TIME_BODY,
        }
    )
    gateway, _audits, _financial_store, _source_time_store = _gateway(tmp_path, transport)
    facts = AkshareUnifiedProviderAdapter(_provider()).fetch_financials_for_announcement_date(
        ASSET_CODE,
        ANNOUNCEMENT_DATE,
        capture_gateway=gateway,
    )
    fetcher = _SequenceFetcher(facts)
    writer = _FactWriter()
    use_case = SyncAkshareFinancialSlicesUseCase(
        provider_repo=_ProviderConfigs(),
        provider_registry=_Registry(AkshareUnifiedProviderAdapter(_provider())),
        fact_repo=writer,
        fetcher_factory=lambda _config, _provider: fetcher,
        evidence_verifier=lambda _config, _evidence: True,
        request_budget=FinancialSliceSyncBudget(2, 2, 4, 200),
    )

    result = use_case.execute(
        FinancialSliceSyncRequest(
            provider_id=17,
            source="akshare",
            slices=(
                FinancialAnnouncementSlice(ASSET_CODE, ANNOUNCEMENT_DATE),
                FinancialAnnouncementSlice(ASSET_CODE, date(2026, 8, 16)),
            ),
        )
    )

    assert result.outcome == "partial"
    assert result.requested == 2
    assert result.succeeded == 1
    assert result.failed == 1
    assert result.stored == 0
    assert result.atomic_fact_write_count == 0
    assert result.planned_provider_requests == 4
    assert fetcher.calls == 2
    assert writer.calls == []


@pytest.mark.parametrize("atomic_fact_write_count", (True, -1, 2))
def test_financial_slice_sync_result_rejects_invalid_atomic_write_count(
    atomic_fact_write_count: int,
) -> None:
    """The count contract accepts only zero writes or one batch-write invocation."""

    with pytest.raises(ValueError):
        FinancialSliceSyncResult(
            outcome="blocked",
            source="akshare",
            provider_id=17,
            provider_name="AKShare Public",
            requested=1,
            succeeded=0,
            failed=1,
            stored=0,
            planned_provider_requests=2,
            atomic_fact_write_count=atomic_fact_write_count,
        )


def test_akshare_financial_slice_budget_is_contract_bound_and_fails_closed(
    tmp_path: Path,
) -> None:
    """Only the reviewed one-pair, two-request budget loads as executable policy."""

    import json

    source_path = Path(__file__).parents[3] / "governance" / "financial_sync_request_budgets.json"
    budget = akshare_financial_slice_sync.load_akshare_financial_slice_sync_budget(source_path)
    assert budget == FinancialSliceSyncBudget(1, 2, 2, 200)

    malformed_path = tmp_path / "budget.json"
    payload = json.loads(source_path.read_text(encoding="utf-8"))
    payload["contract_sha256"] = "0" * 64
    malformed_path.write_text(json.dumps(payload), encoding="utf-8")
    assert (
        akshare_financial_slice_sync.load_akshare_financial_slice_sync_budget(malformed_path)
        is None
    )


def test_akshare_financial_slice_composition_builds_explicit_fact_only_use_case(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The composition builder injects exact routing, evidence, and budget ports."""

    configs = _ProviderConfigs()
    registry = _Registry(AkshareUnifiedProviderAdapter(_provider()))
    writer = _FactWriter()
    budget = FinancialSliceSyncBudget(1, 2, 2, 200)

    def fetcher_factory(_config: ProviderConfig, _provider: object) -> None:
        return None

    monkeypatch.setattr(
        financial_slice_composition,
        "get_provider_config_repository",
        lambda: configs,
    )
    monkeypatch.setattr(
        financial_slice_composition,
        "build_provider_registry_for_repo",
        lambda repository: registry if repository is configs else None,
    )
    monkeypatch.setattr(
        financial_slice_composition,
        "FinancialFactRepository",
        lambda **_kwargs: writer,
    )
    monkeypatch.setattr(
        financial_slice_composition,
        "build_akshare_financial_slice_fetcher",
        fetcher_factory,
    )
    monkeypatch.setattr(
        financial_slice_composition,
        "load_akshare_financial_slice_sync_budget",
        lambda: budget,
    )

    use_case = financial_slice_composition.make_sync_akshare_financial_slices_use_case()

    assert isinstance(use_case, SyncAkshareFinancialSlicesUseCase)
    assert use_case._provider_repo is configs
    assert use_case._provider_registry is registry
    assert use_case._fact_repo is writer
    assert use_case._fetcher_factory is fetcher_factory
    assert use_case._request_budget == budget
