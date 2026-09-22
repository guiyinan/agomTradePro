"""Contracts for the opt-in financial response artifact adoption slice."""

from __future__ import annotations

import json
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, replace
from datetime import UTC, date, datetime
from pathlib import Path
from typing import cast
from unittest.mock import Mock
from uuid import UUID

import pytest
from cryptography.fernet import Fernet
from django.core.management import CommandError

from apps.data_center.application import egress_service
from apps.data_center.application.dtos import SyncFinancialRequest
from apps.data_center.application.financial_response_artifact import (
    FinancialResponseArtifactAuditError,
    FinancialResponseArtifactAuditLookupError,
    FinancialResponseArtifactOutcomeConflictError,
    FinancialResponseFailureAuditError,
    RetainFinancialResponseArtifactUseCase,
    RetainFinancialResponseFailureUseCase,
)
from apps.data_center.application.sync_use_cases import SyncFinancialUseCase
from apps.data_center.domain.egress_routing import (
    EgressRequestContext,
    EgressRouteDecision,
    EgressStrategy,
)
from apps.data_center.domain.entities import ProviderConfig, RawAudit, raw_audit_content_hash
from apps.data_center.domain.financial_response_artifact import FinancialResponseArtifactRef
from apps.data_center.domain.financial_response_evidence import (
    FinancialRequestScope,
    FinancialResponseEvidence,
    FinancialResponseScope,
    FinancialResponseScopeBasis,
    raw_body_sha256,
)
from apps.data_center.financial_response_artifact_composition import (
    FINANCIAL_DATASET_KEY,
    _ConfiguredTushareFinancialResponseHandler,
)
from apps.data_center.infrastructure import _provider_adapter_tushare as adapter_module
from apps.data_center.infrastructure import financial_response_artifact_config as config_module
from apps.data_center.infrastructure import provider_state_repositories
from apps.data_center.infrastructure.financial_response_artifact_config import (
    ARTIFACT_ENABLED_KEY,
    ARTIFACT_KEY_VERSION_KEY,
    ARTIFACT_MAX_BODY_BYTES_KEY,
    ARTIFACT_ROOT_KEY,
    build_financial_response_artifact_repository,
    resolve_financial_response_artifact_config,
)
from apps.data_center.infrastructure.financial_response_artifact_repository import (
    FinancialResponseArtifactRepository,
    failure_reference_from_audit,
    reference_from_audit,
)
from apps.data_center.infrastructure.financial_response_body_store import (
    FinancialResponseArtifactConfigurationError,
    FinancialResponseArtifactConflictError,
    FinancialResponseBodyStore,
)
from apps.data_center.infrastructure.financial_response_capture import (
    CapturedFinancialResponse,
    capture_financial_response,
    decode_json_bytes,
)
from apps.data_center.infrastructure.provider_state_repositories import RawAuditRepository
from apps.data_center.management.commands.initialize_financial_response_artifact import Command
from core.exceptions import InvalidInputError, TushareError

BODY = b'{"code":0,"data":{"fields":["ts_code"],"items":[["000001.SZ"]]}}'
SCOPED_BODY = (
    b'{"code":0,"data":{"fields":["ts_code","end_date"],' b'"items":[["000001.SZ","20251231"]]}}'
)
SYNTHETIC_REJECTED_BODY = b'{"code":2003,"msg":"synthetic provider rejection"}'
FINANCIAL_BODY = (
    b'{"code":0,"data":{"fields":["ts_code","end_date","ann_date","roe"],'
    b'"items":[["000001.SZ","2025-12-31","2026-03-30",12.5]]}}'
)
CAPTURE_ID = UUID("20000000-0000-4000-8000-000000000001")
COMPLETED_AT = datetime(2026, 9, 14, 6, 0, 0, tzinfo=UTC)


class _AuditRepository:
    """In-memory audit port used to test application idempotency."""

    def __init__(self, *, fail_log: bool = False) -> None:
        self.rows: list[RawAudit] = []
        self.fail_log = fail_log

    def log(self, audit: RawAudit) -> RawAudit:
        """Append one audit row or simulate a durable audit failure."""

        if self.fail_log:
            raise OSError("simulated audit failure")
        persisted = replace(audit, raw_audit_id=str(len(self.rows) + 1))
        self.rows.append(persisted)
        return persisted

    def find_by_artifact_capture_id(self, capture_id: UUID) -> RawAudit | None:
        """Find the one row whose link contains the requested capture UUID."""

        expected = str(capture_id)
        for row in self.rows:
            link = row.extra.get("financial_response_artifact")
            if isinstance(link, dict) and link.get("capture_id") == expected:
                return row
        return None

    def log_failure(self, audit: RawAudit) -> RawAudit:
        """Append one failure audit row or simulate a durable audit failure."""

        if self.fail_log:
            raise OSError("simulated audit failure")
        persisted = replace(audit, raw_audit_id=str(len(self.rows) + 1))
        self.rows.append(persisted)
        return persisted

    def find_by_failure_capture_id(self, capture_id: UUID) -> RawAudit | None:
        """Find the one failure row whose link contains the requested capture UUID."""

        expected = str(capture_id)
        for row in self.rows:
            link = row.extra.get("financial_response_failure_artifact")
            if isinstance(link, dict) and link.get("capture_id") == expected:
                return row
        return None


class _FailingAuditLookup(_AuditRepository):
    """Audit port that fails before any body publication is attempted."""

    def find_by_artifact_capture_id(self, capture_id: UUID) -> RawAudit | None:
        """Simulate a durable audit read outage."""

        del capture_id
        raise OSError("simulated audit lookup failure")


@dataclass(frozen=True)
class _Captured:
    """Small structural capture used at the application egress boundary."""

    payload: object
    evidence: FinancialResponseEvidence
    raw_body: bytes


class _FinancialTransport:
    """Fake transport that records the one request UUID and typed scopes."""

    def __init__(self, capture: _Captured) -> None:
        self.capture = capture
        self.calls: list[dict[str, object]] = []

    def request_financial_response(
        self, context: EgressRequestContext, **kwargs: object
    ) -> tuple[egress_service.EgressTransportResult, _Captured]:
        """Return a successful capture without making a network request."""

        self.calls.append({"context": context, **kwargs})
        return egress_service.EgressTransportResult(outcome="success"), self.capture


class _RawFinancialResponse:
    """One response-shaped object for the strict capture seam."""

    status_code = 200

    def __init__(self, body: bytes) -> None:
        self._body = body
        self.headers = {
            "content-length": str(len(body)),
            "Content-Encoding": "identity",
        }
        self.read_count = 0

    def iter_content(self, *, chunk_size: int) -> Iterable[bytes]:
        """Yield the exact body once, split to exercise stream assembly."""

        del chunk_size
        self.read_count += 1
        yield self._body[:7]
        yield self._body[7:]


class _CapturingFinancialTransport:
    """Run the real strict capture seam behind the application egress port."""

    def __init__(self, body: bytes) -> None:
        self.body = body
        self.calls: list[dict[str, object]] = []
        self.responses: list[_RawFinancialResponse] = []

    def request_financial_response(
        self,
        context: EgressRequestContext,
        *,
        egress_id: int | None,
        request_id: UUID,
        attempt: int,
        method: str,
        params: Mapping[str, object] | None,
        json_body: Mapping[str, object] | None,
        headers: Mapping[str, str] | None,
        request_scope: FinancialRequestScope,
        response_scope: FinancialResponseScope,
    ) -> tuple[
        egress_service.EgressTransportResult,
        CapturedFinancialResponse[object] | None,
    ]:
        """Capture the fake HTTP response with the production decoder."""

        self.calls.append(
            {
                "context": context,
                "egress_id": egress_id,
                "request_id": request_id,
                "attempt": attempt,
                "method": method,
                "params": params,
                "json_body": json_body,
                "headers": headers,
            }
        )
        response = _RawFinancialResponse(self.body)
        self.responses.append(response)
        captured = capture_financial_response(
            response,
            request_scope=request_scope,
            response_scope=response_scope,
            decode=decode_json_bytes,
            clock=lambda: COMPLETED_AT,
            max_bytes=1024 * 1024,
        )
        return (
            egress_service.EgressTransportResult(outcome="success", status_code=200),
            captured,
        )


class _RetentionRepository:
    """Structural repository seam for the handler unit contract."""

    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []
        self.failure_calls: list[dict[str, object]] = []

    def retain(self, **kwargs: object) -> _RetentionResult:
        """Record only the typed retention arguments supplied by the handler."""

        self.calls.append(kwargs)
        capture_id = kwargs["capture_id"]
        evidence = kwargs["evidence"]
        assert isinstance(capture_id, UUID)
        assert isinstance(evidence, FinancialResponseEvidence)
        return _RetentionResult(
            reference=FinancialResponseArtifactRef(
                capture_id=capture_id,
                location=f"test-financial-response:///{capture_id}",
                evidence=evidence,
                format_version="financial-response-artifact.v1",
                encryption_algorithm="fernet",
                encryption_key_ref="test/financial-response-key",
                encryption_key_version="test-v1",
            )
        )

    def retain_rejected(self, **kwargs: object) -> None:
        """Record only the typed failure-retention arguments supplied by the handler."""

        self.failure_calls.append(kwargs)


@dataclass(frozen=True)
class _RetentionResult:
    """Minimal successful retention result returned by the repository seam."""

    reference: FinancialResponseArtifactRef


def _evidence(body: bytes = BODY) -> FinancialResponseEvidence:
    """Build one bounded response observation for tests."""

    return FinancialResponseEvidence(
        body_sha256=raw_body_sha256(body),
        body_size_bytes=len(body),
        response_completed_at=COMPLETED_AT,
        request_scope=FinancialRequestScope(
            provider_name="Tushare Pro",
            dataset_key=FINANCIAL_DATASET_KEY,
            asset_code="000001.SZ",
            period_limit=2,
        ),
        response_scope=FinancialResponseScope(
            asset_codes=("000001.SZ",),
            period_ends=(date(2025, 12, 31),),
            row_count=0,
        ),
    )


def _store(tmp_path: Path) -> FinancialResponseBodyStore:
    """Construct a fully explicit encrypted store for one test."""

    return FinancialResponseBodyStore(
        tmp_path,
        encryption_key=Fernet.generate_key(),
        encryption_key_ref="test/financial-response-key",
        encryption_key_version="test-v1",
        max_body_bytes=1024 * 1024,
    )


@pytest.fixture
def artifact_tmp_path(tmp_path: Path) -> Path:
    """Use pytest-owned scratch storage without requiring a repository var tree."""

    return tmp_path


def _provider() -> ProviderConfig:
    """Return a provider projection without credentials in the test body."""

    return ProviderConfig(
        id=7,
        name="Tushare Pro",
        source_type="tushare",
        is_active=True,
        priority=1,
        api_key="test-token",
        api_secret="",
        http_url="https://provider.example.test/tushare",
        api_endpoint="",
        extra_config={"tushare_request_mode": "unified_relay"},
        description="",
    )


def test_retention_binds_exact_bytes_without_secret_or_source_claims(
    artifact_tmp_path: Path,
) -> None:
    """The audit link carries raw-byte evidence while preserving unknown source fields."""

    audits = _AuditRepository()
    result = RetainFinancialResponseArtifactUseCase(_store(artifact_tmp_path), audits).execute(
        capture_id=CAPTURE_ID,
        evidence=_evidence(),
        body=BODY,
        provider_name="Tushare Pro",
        request_params={"api_name": "fina_indicator", "params": {"ts_code": "000001.SZ"}},
        provider_id=7,
    )

    assert result.reference.body_sha256 == raw_body_sha256(BODY)
    assert result.reference.body_size_bytes == len(BODY)
    assert result.audit.response_payload_hash == ""
    assert result.audit.extra["financial_response_artifact"]["capture_id"] == str(CAPTURE_ID)
    assert "announcement_at" not in result.audit.extra["financial_response_artifact"]
    assert "available_at" not in result.audit.extra["financial_response_artifact"]
    assert "test-token" not in repr(result.audit)
    encrypted = next(artifact_tmp_path.rglob("*.frb")).read_bytes()
    assert BODY not in encrypted


def test_retention_replay_is_idempotent_and_conflict_is_immutable(
    artifact_tmp_path: Path,
) -> None:
    """The same capture reuses one audit row and rejects changed evidence."""

    audits = _AuditRepository()
    use_case = RetainFinancialResponseArtifactUseCase(_store(artifact_tmp_path), audits)
    first = use_case.execute(
        capture_id=CAPTURE_ID,
        evidence=_evidence(),
        body=BODY,
        provider_name="Tushare Pro",
        request_params={"params": {"ts_code": "000001.SZ"}},
        provider_id=7,
    )
    replay = use_case.execute(
        capture_id=CAPTURE_ID,
        evidence=_evidence(),
        body=BODY,
        provider_name="Tushare Pro",
        request_params={"params": {"ts_code": "000001.SZ"}},
        provider_id=7,
    )
    assert replay.reference == first.reference
    assert replay.audit == first.audit
    assert len(audits.rows) == 1
    audits.rows[0] = replace(audits.rows[0], run_id="foreign-run")
    with pytest.raises(ValueError):
        use_case.execute(
            capture_id=CAPTURE_ID,
            evidence=_evidence(),
            body=BODY,
            provider_name="Tushare Pro",
            request_params={"params": {"ts_code": "000001.SZ"}},
            provider_id=7,
        )
    audits.rows[0] = replace(audits.rows[0], run_id="")
    audits.rows[0] = replace(audits.rows[0], ingested_run_id="foreign-ingested-run")
    with pytest.raises(ValueError):
        use_case.execute(
            capture_id=CAPTURE_ID,
            evidence=_evidence(),
            body=BODY,
            provider_name="Tushare Pro",
            request_params={"params": {"ts_code": "000001.SZ"}},
            provider_id=7,
        )
    audits.rows[0] = replace(audits.rows[0], ingested_run_id="")
    audits.rows[0] = replace(audits.rows[0], content_hash="f" * 64)
    with pytest.raises(ValueError):
        use_case.execute(
            capture_id=CAPTURE_ID,
            evidence=_evidence(),
            body=BODY,
            provider_name="Tushare Pro",
            request_params={"params": {"ts_code": "000001.SZ"}},
            provider_id=7,
        )
    audits.rows[0] = replace(audits.rows[0], content_hash=raw_audit_content_hash(audits.rows[0]))
    assert (
        use_case.execute(
            capture_id=CAPTURE_ID,
            evidence=_evidence(),
            body=BODY,
            provider_name="Tushare Pro",
            request_params={"params": {"ts_code": "000001.SZ"}},
            provider_id=7,
        ).audit
        == audits.rows[0]
    )
    audits.rows[0] = replace(audits.rows[0], content_hash="")
    audits.rows[0] = replace(audits.rows[0], error_message="corrupted success audit")
    with pytest.raises(ValueError):
        use_case.execute(
            capture_id=CAPTURE_ID,
            evidence=_evidence(),
            body=BODY,
            provider_name="Tushare Pro",
            request_params={"params": {"ts_code": "000001.SZ"}},
            provider_id=7,
        )

    changed_body = BODY + b"\n"
    with pytest.raises(FinancialResponseArtifactConflictError):
        use_case.execute(
            capture_id=CAPTURE_ID,
            evidence=_evidence(changed_body),
            body=changed_body,
            provider_name="Tushare Pro",
            request_params={"params": {"ts_code": "000001.SZ"}},
            provider_id=7,
        )
    assert len(audits.rows) == 1


def test_failure_retention_encrypts_exact_body_with_separate_error_link(
    artifact_tmp_path: Path,
) -> None:
    """A rejected body is replayable without becoming a successful raw audit."""

    audits = _AuditRepository()
    store = _store(artifact_tmp_path)
    evidence = _evidence(SYNTHETIC_REJECTED_BODY)
    result = RetainFinancialResponseFailureUseCase(store, audits).execute(
        capture_id=CAPTURE_ID,
        evidence=evidence,
        body=SYNTHETIC_REJECTED_BODY,
        provider_name="Tushare Pro",
        request_params={"api_name": "fina_indicator", "params": {"ts_code": "000001.SZ"}},
        failure_code="TUSHARE_PROVIDER_REJECTED",
        provider_id=7,
    )

    assert result.audit.capability == "financial_response_failure"
    assert result.audit.status == "error"
    assert result.audit.error_message == "TUSHARE_PROVIDER_REJECTED"
    assert result.audit.parser_version == "financial-response-failure.v1"
    assert result.audit.response_payload_hash == ""
    assert result.audit.row_count == 0
    assert result.audit.extra["financial_response_failure_artifact"]["failure_code"] == (
        "TUSHARE_PROVIDER_REJECTED"
    )
    assert failure_reference_from_audit(result.audit) == result.reference
    assert audits.find_by_artifact_capture_id(CAPTURE_ID) is None
    failure_repo = FinancialResponseArtifactRepository(
        store,
        audits,
        failure_audit_repository=audits,
    )
    assert failure_repo.inspect_rejected_orphan(result.reference).is_orphan is False
    audits.rows[0] = replace(audits.rows[0], error_message="CORRUPTED_FAILURE")
    assert failure_repo.inspect_rejected_orphan(result.reference).is_orphan is True
    audits.rows[0] = replace(audits.rows[0], error_message="TUSHARE_PROVIDER_REJECTED")
    audits.rows[0] = replace(audits.rows[0], status="ok")
    assert failure_repo.inspect_rejected_orphan(result.reference).is_orphan is True
    encrypted = next(artifact_tmp_path.rglob("*.frb")).read_bytes()
    assert SYNTHETIC_REJECTED_BODY not in encrypted
    assert "synthetic provider rejection" not in repr(result.audit)


def test_failure_replay_rejects_changed_metadata_and_body(
    artifact_tmp_path: Path,
) -> None:
    """A failure capture remains immutable across code, request, and body changes."""

    audits = _AuditRepository()
    store = _store(artifact_tmp_path)
    use_case = RetainFinancialResponseFailureUseCase(store, audits)
    evidence = _evidence(SYNTHETIC_REJECTED_BODY)
    params = {"api_name": "fina_indicator", "params": {"ts_code": "000001.SZ"}}
    first = use_case.execute(
        capture_id=CAPTURE_ID,
        evidence=evidence,
        body=SYNTHETIC_REJECTED_BODY,
        provider_name="Tushare Pro",
        request_params=params,
        failure_code="TUSHARE_PROVIDER_REJECTED",
        provider_id=7,
    )
    replay = use_case.execute(
        capture_id=CAPTURE_ID,
        evidence=evidence,
        body=SYNTHETIC_REJECTED_BODY,
        provider_name="Tushare Pro",
        request_params=dict(params),
        failure_code="TUSHARE_PROVIDER_REJECTED",
        provider_id=7,
    )
    assert replay == first

    audits.rows[0] = replace(audits.rows[0], error_message="CORRUPTED_FAILURE")
    with pytest.raises(FinancialResponseArtifactOutcomeConflictError):
        use_case.execute(
            capture_id=CAPTURE_ID,
            evidence=evidence,
            body=SYNTHETIC_REJECTED_BODY,
            provider_name="Tushare Pro",
            request_params=params,
            failure_code="TUSHARE_PROVIDER_REJECTED",
            provider_id=7,
        )
    audits.rows[0] = replace(audits.rows[0], error_message="TUSHARE_PROVIDER_REJECTED")

    with pytest.raises(FinancialResponseArtifactOutcomeConflictError):
        use_case.execute(
            capture_id=CAPTURE_ID,
            evidence=evidence,
            body=SYNTHETIC_REJECTED_BODY,
            provider_name="Tushare Pro",
            request_params={**params, "limit": 1},
            failure_code="TUSHARE_PROVIDER_REJECTED",
            provider_id=7,
        )
    with pytest.raises(FinancialResponseArtifactOutcomeConflictError):
        use_case.execute(
            capture_id=CAPTURE_ID,
            evidence=evidence,
            body=SYNTHETIC_REJECTED_BODY,
            provider_name="Tushare Pro",
            request_params=params,
            failure_code="TUSHARE_INVALID_PAYLOAD",
            provider_id=7,
        )
    audits.rows[0] = replace(audits.rows[0], error_message="TUSHARE_PROVIDER_REJECTED")
    audits.rows[0] = replace(audits.rows[0], run_id="foreign-run")
    with pytest.raises(FinancialResponseArtifactOutcomeConflictError):
        use_case.execute(
            capture_id=CAPTURE_ID,
            evidence=evidence,
            body=SYNTHETIC_REJECTED_BODY,
            provider_name="Tushare Pro",
            request_params=params,
            failure_code="TUSHARE_PROVIDER_REJECTED",
            provider_id=7,
        )
    audits.rows[0] = replace(audits.rows[0], run_id="")
    audits.rows[0] = replace(audits.rows[0], ingested_run_id="foreign-ingested-run")
    with pytest.raises(FinancialResponseArtifactOutcomeConflictError):
        use_case.execute(
            capture_id=CAPTURE_ID,
            evidence=evidence,
            body=SYNTHETIC_REJECTED_BODY,
            provider_name="Tushare Pro",
            request_params=params,
            failure_code="TUSHARE_PROVIDER_REJECTED",
            provider_id=7,
        )
    audits.rows[0] = replace(audits.rows[0], ingested_run_id="")
    audits.rows[0] = replace(audits.rows[0], content_hash="f" * 64)
    with pytest.raises(FinancialResponseArtifactOutcomeConflictError):
        use_case.execute(
            capture_id=CAPTURE_ID,
            evidence=evidence,
            body=SYNTHETIC_REJECTED_BODY,
            provider_name="Tushare Pro",
            request_params=params,
            failure_code="TUSHARE_PROVIDER_REJECTED",
            provider_id=7,
        )
    audits.rows[0] = replace(audits.rows[0], content_hash=raw_audit_content_hash(audits.rows[0]))
    assert (
        use_case.execute(
            capture_id=CAPTURE_ID,
            evidence=evidence,
            body=SYNTHETIC_REJECTED_BODY,
            provider_name="Tushare Pro",
            request_params=params,
            failure_code="TUSHARE_PROVIDER_REJECTED",
            provider_id=7,
        ).audit
        == audits.rows[0]
    )
    changed_body = SYNTHETIC_REJECTED_BODY + b"\n"
    with pytest.raises(FinancialResponseArtifactConflictError):
        use_case.execute(
            capture_id=CAPTURE_ID,
            evidence=_evidence(changed_body),
            body=changed_body,
            provider_name="Tushare Pro",
            request_params=params,
            failure_code="TUSHARE_PROVIDER_REJECTED",
            provider_id=7,
        )
    assert len(audits.rows) == 1
    assert store.read(first.reference) == SYNTHETIC_REJECTED_BODY


def test_failure_audit_error_returns_opaque_reference_for_reconciliation(
    artifact_tmp_path: Path,
) -> None:
    """A failure-audit append error leaves an identifiable encrypted orphan."""

    store = _store(artifact_tmp_path)
    audits = _AuditRepository(fail_log=True)
    with pytest.raises(FinancialResponseFailureAuditError) as caught:
        RetainFinancialResponseFailureUseCase(store, audits).execute(
            capture_id=CAPTURE_ID,
            evidence=_evidence(SYNTHETIC_REJECTED_BODY),
            body=SYNTHETIC_REJECTED_BODY,
            provider_name="Tushare Pro",
            request_params={"params": {"ts_code": "000001.SZ"}},
            failure_code="TUSHARE_PROVIDER_REJECTED",
            provider_id=7,
        )

    orphan = FinancialResponseArtifactRepository(
        store,
        audits,
        failure_audit_repository=audits,
    ).inspect_rejected_orphan(caught.value.reference)
    assert orphan.is_orphan is True
    assert orphan.body_verified is True
    assert caught.value.details["body_sha256"] == caught.value.reference.body_sha256
    assert caught.value.details["failure_code"] == "TUSHARE_PROVIDER_REJECTED"
    assert SYNTHETIC_REJECTED_BODY.decode() not in str(caught.value)

    recovered_audits = _AuditRepository()
    RetainFinancialResponseFailureUseCase(store, recovered_audits).execute(
        capture_id=CAPTURE_ID,
        evidence=_evidence(SYNTHETIC_REJECTED_BODY),
        body=SYNTHETIC_REJECTED_BODY,
        provider_name="Tushare Pro",
        request_params={"params": {"ts_code": "000001.SZ"}},
        failure_code="TUSHARE_PROVIDER_REJECTED",
        provider_id=7,
    )
    assert (
        FinancialResponseArtifactRepository(
            store,
            recovered_audits,
            failure_audit_repository=recovered_audits,
        )
        .inspect_rejected_orphan(caught.value.reference)
        .is_orphan
        is False
    )


def test_success_and_failure_capture_outcomes_cannot_share_uuid(
    artifact_tmp_path: Path,
) -> None:
    """A capture UUID cannot be promoted from one outcome to the other."""

    audits = _AuditRepository()
    store = _store(artifact_tmp_path)
    repository = FinancialResponseArtifactRepository(
        store,
        audits,
        failure_audit_repository=audits,
    )
    repository.retain(
        capture_id=CAPTURE_ID,
        evidence=_evidence(),
        body=BODY,
        provider_name="Tushare Pro",
        request_params={"params": {"ts_code": "000001.SZ"}},
        provider_id=7,
    )
    with pytest.raises(FinancialResponseArtifactOutcomeConflictError):
        repository.retain_rejected(
            capture_id=CAPTURE_ID,
            evidence=_evidence(SYNTHETIC_REJECTED_BODY),
            body=SYNTHETIC_REJECTED_BODY,
            provider_name="Tushare Pro",
            request_params={"params": {"ts_code": "000001.SZ"}},
            failure_code="TUSHARE_PROVIDER_REJECTED",
            provider_id=7,
        )

    failure_id = UUID("20000000-0000-4000-8000-000000000004")
    repository.retain_rejected(
        capture_id=failure_id,
        evidence=_evidence(SYNTHETIC_REJECTED_BODY),
        body=SYNTHETIC_REJECTED_BODY,
        provider_name="Tushare Pro",
        request_params={"params": {"ts_code": "000001.SZ"}},
        failure_code="TUSHARE_PROVIDER_REJECTED",
        provider_id=7,
    )
    with pytest.raises(FinancialResponseArtifactOutcomeConflictError):
        repository.retain(
            capture_id=failure_id,
            evidence=_evidence(SYNTHETIC_REJECTED_BODY),
            body=SYNTHETIC_REJECTED_BODY,
            provider_name="Tushare Pro",
            request_params={"params": {"ts_code": "000001.SZ"}},
            provider_id=7,
        )


def test_audit_failure_returns_opaque_reference_for_orphan_reconciliation(
    artifact_tmp_path: Path,
) -> None:
    """A published body remains identifiable when the audit append fails."""

    store = _store(artifact_tmp_path)
    audits = _AuditRepository(fail_log=True)
    use_case = RetainFinancialResponseArtifactUseCase(store, audits)
    with pytest.raises(FinancialResponseArtifactAuditError) as caught:
        use_case.execute(
            capture_id=CAPTURE_ID,
            evidence=_evidence(),
            body=BODY,
            provider_name="Tushare Pro",
            request_params={"params": {"ts_code": "000001.SZ"}},
            provider_id=7,
        )

    orphan = FinancialResponseArtifactRepository(store, audits).inspect_orphan(
        caught.value.reference
    )
    assert orphan.is_orphan is True
    assert orphan.body_verified is True
    assert caught.value.details["location"] == caught.value.reference.location
    assert BODY.decode() not in str(caught.value)


def test_audit_lookup_failure_does_not_publish_a_body(artifact_tmp_path: Path) -> None:
    """A preflight audit read failure cannot leave a newly published orphan."""

    with pytest.raises(FinancialResponseArtifactAuditLookupError):
        RetainFinancialResponseArtifactUseCase(
            _store(artifact_tmp_path), _FailingAuditLookup()
        ).execute(
            capture_id=CAPTURE_ID,
            evidence=_evidence(),
            body=BODY,
            provider_name="Tushare Pro",
            request_params={"params": {"ts_code": "000001.SZ"}},
        )
    assert not tuple(artifact_tmp_path.rglob("*.frb"))


def test_retention_rejects_credential_shaped_request_dimensions(
    artifact_tmp_path: Path,
) -> None:
    """Headers and token-shaped values cannot cross into RawAudit parameters."""

    with pytest.raises(ValueError):
        RetainFinancialResponseArtifactUseCase(
            _store(artifact_tmp_path), _AuditRepository()
        ).execute(
            capture_id=CAPTURE_ID,
            evidence=_evidence(),
            body=BODY,
            provider_name="Tushare Pro",
            request_params={"token": "secret"},
        )


def test_egress_financial_helper_reuses_request_id_and_requires_route(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The application port passes typed scopes to the shared transport route."""

    evidence = _evidence()
    captured = _Captured(
        payload={
            "code": 0,
            "data": {"fields": ["ts_code"], "items": [["000001.SZ"]]},
        },
        evidence=evidence,
        raw_body=BODY,
    )
    transport = _FinancialTransport(captured)
    route = EgressRouteDecision(
        rule_id=11,
        strategy=EgressStrategy.FIXED,
        candidates=(3,),
        reason="financial",
        matched_domain="provider.example.test",
    )
    monkeypatch.setattr(egress_service, "_transport", cast(object, transport))
    monkeypatch.setattr(egress_service, "preview_route", lambda _context: route)
    request_id = UUID("20000000-0000-4000-8000-000000000002")
    context = EgressRequestContext(
        provider_id=7,
        dataset_key=FINANCIAL_DATASET_KEY,
        target_url="https://provider.example.test/tushare",
        deployment_region="local",
    )

    result = egress_service.execute_financial_response_request(
        context,
        request_id=request_id,
        method="POST",
        params=None,
        json_body={"params": {"ts_code": "000001.SZ", "limit": 2}},
        headers={"X-API-Key": "secret"},
        request_scope=evidence.request_scope,
        response_scope=evidence.response_scope,
    )

    assert result is captured
    assert transport.calls[0]["request_id"] == request_id
    assert transport.calls[0]["request_scope"] == evidence.request_scope


def test_tushare_handler_retains_capture_without_token_or_source_inference(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The opt-in handler retains one body and returns its decoded payload."""

    repository = _RetentionRepository()
    handler = _ConfiguredTushareFinancialResponseHandler(
        _provider(),
        cast(FinancialResponseArtifactRepository, repository),
    )
    evidence = _evidence(SCOPED_BODY)
    captured = _Captured(
        payload={
            "code": 0,
            "data": {
                "fields": ["ts_code", "end_date"],
                "items": [["000001.SZ", "20251231"]],
            },
        },
        evidence=evidence,
        raw_body=SCOPED_BODY,
    )
    request_id = UUID("20000000-0000-4000-8000-000000000003")

    def execute(_context: EgressRequestContext, **kwargs: object) -> _Captured:
        """Return the single injected capture and inspect its request dimensions."""

        assert kwargs["request_id"] == request_id
        assert kwargs["request_scope"] == evidence.request_scope
        return captured

    monkeypatch.setattr(
        "apps.data_center.financial_response_artifact_composition.execute_financial_response_request",
        execute,
    )
    context = EgressRequestContext(
        provider_id=7,
        dataset_key=FINANCIAL_DATASET_KEY,
        target_url="https://provider.example.test/tushare",
        deployment_region="local",
    )
    result = handler(
        request_id=request_id,
        context=context,
        method="POST",
        params=None,
        json_body={
            "api_name": "fina_indicator",
            "token": "secret",
            "params": {"ts_code": "000001.SZ", "limit": 2},
        },
        headers={"X-API-Key": "secret"},
        api_name="fina_indicator",
    )

    assert result.payload == {
        "code": 0,
        "data": {
            "fields": ["ts_code", "end_date"],
            "items": [["000001.SZ", "20251231"]],
        },
    }
    assert len(repository.calls) == 1
    request_projection = repository.calls[0]["request_params"]
    assert isinstance(request_projection, dict)
    assert "token" not in repr(request_projection)
    assert repository.calls[0]["capture_id"] == request_id
    retained_evidence = repository.calls[0]["evidence"]
    assert isinstance(retained_evidence, FinancialResponseEvidence)
    assert (
        retained_evidence.response_scope_basis is FinancialResponseScopeBasis.PROVIDER_BODY_VERIFIED
    )
    assert retained_evidence.response_scope == FinancialResponseScope(
        asset_codes=("000001.SZ",),
        period_ends=(date(2025, 12, 31),),
        row_count=1,
    )
    assert repository.calls[0]["row_count"] == 1
    assert result.reference.capture_id == request_id
    assert result.reference.evidence == retained_evidence


@pytest.mark.parametrize(
    ("fields", "items"),
    [
        (["ts_code", "ann_date"], [["000001.SZ", "20260330"]]),
        (["ts_code", "end_date"], [["000002.SZ", "20251231"]]),
        (["ts_code", "end_date"], [["000001.SZ", "2025/12/31"]]),
        (["ts_code", "end_date"], [["000001.SZ", "2025-W01-1"]]),
    ],
)
def test_tushare_handler_rejects_unverifiable_provider_body_scope(
    monkeypatch: pytest.MonkeyPatch,
    fields: list[str],
    items: list[list[object]],
) -> None:
    """Successful provider payloads need exact asset and period body coverage."""

    repository = _RetentionRepository()
    handler = _ConfiguredTushareFinancialResponseHandler(
        _provider(),
        cast(FinancialResponseArtifactRepository, repository),
    )
    payload = {"code": 0, "data": {"fields": fields, "items": items}}
    raw_body = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    captured = _Captured(payload=payload, evidence=_evidence(raw_body), raw_body=raw_body)

    monkeypatch.setattr(
        "apps.data_center.financial_response_artifact_composition.execute_financial_response_request",
        lambda _context, **_kwargs: captured,
    )
    context = EgressRequestContext(
        provider_id=7,
        dataset_key=FINANCIAL_DATASET_KEY,
        target_url="https://provider.example.test/tushare",
        deployment_region="local",
    )

    with pytest.raises(TushareError) as caught:
        handler(
            request_id=CAPTURE_ID,
            context=context,
            method="POST",
            params=None,
            json_body={"params": {"ts_code": "000001.SZ", "limit": 2}},
            headers={"X-API-Key": "secret"},
            api_name="fina_indicator",
        )

    assert caught.value.code == "TUSHARE_INVALID_PAYLOAD"
    assert repository.calls == []
    assert repository.failure_calls == []


@pytest.mark.parametrize("provider_code", [False, 0.0, "0", None])
def test_tushare_handler_rejects_non_integer_success_code(
    monkeypatch: pytest.MonkeyPatch,
    provider_code: object,
) -> None:
    """Only the exact integer zero may authorize successful artifact retention."""

    repository = _RetentionRepository()
    handler = _ConfiguredTushareFinancialResponseHandler(
        _provider(),
        cast(FinancialResponseArtifactRepository, repository),
    )
    payload = {
        "code": provider_code,
        "data": {
            "fields": ["ts_code", "end_date"],
            "items": [["000001.SZ", "20251231"]],
        },
    }
    raw_body = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    captured = _Captured(payload=payload, evidence=_evidence(raw_body), raw_body=raw_body)
    monkeypatch.setattr(
        "apps.data_center.financial_response_artifact_composition.execute_financial_response_request",
        lambda _context, **_kwargs: captured,
    )

    with pytest.raises(TushareError) as caught:
        handler(
            request_id=CAPTURE_ID,
            context=EgressRequestContext(
                provider_id=7,
                dataset_key=FINANCIAL_DATASET_KEY,
                target_url="https://provider.example.test/tushare",
                deployment_region="local",
            ),
            method="POST",
            params=None,
            json_body={"params": {"ts_code": "000001.SZ", "limit": 2}},
            headers={"X-API-Key": "secret"},
            api_name="fina_indicator",
        )

    assert caught.value.code == "TUSHARE_INVALID_PAYLOAD"
    assert repository.calls == []
    assert repository.failure_calls == []


def test_tushare_handler_rejects_provider_business_failure_before_audit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A captured provider rejection gets failure evidence without success audit."""

    repository = _RetentionRepository()
    handler = _ConfiguredTushareFinancialResponseHandler(
        _provider(),
        cast(FinancialResponseArtifactRepository, repository),
    )
    captured = _Captured(
        payload={"code": 2003, "msg": "synthetic provider rejection"},
        evidence=_evidence(SYNTHETIC_REJECTED_BODY),
        raw_body=SYNTHETIC_REJECTED_BODY,
    )

    def execute(_context: EgressRequestContext, **_kwargs: object) -> _Captured:
        """Return one transport-successful but provider-rejected payload."""

        return captured

    monkeypatch.setattr(
        "apps.data_center.financial_response_artifact_composition.execute_financial_response_request",
        execute,
    )
    context = EgressRequestContext(
        provider_id=7,
        dataset_key=FINANCIAL_DATASET_KEY,
        target_url="https://provider.example.test/tushare",
        deployment_region="local",
    )

    with pytest.raises(TushareError) as caught:
        handler(
            request_id=CAPTURE_ID,
            context=context,
            method="POST",
            params=None,
            json_body={"params": {"ts_code": "000001.SZ", "limit": 2}},
            headers={"X-API-Key": "secret"},
            api_name="fina_indicator",
        )

    assert caught.value.code == "TUSHARE_PROVIDER_REJECTED"
    assert repository.calls == []
    assert len(repository.failure_calls) == 1
    assert repository.failure_calls[0]["capture_id"] == CAPTURE_ID
    assert repository.failure_calls[0]["failure_code"] == "TUSHARE_PROVIDER_REJECTED"
    assert repository.failure_calls[0]["body"] == SYNTHETIC_REJECTED_BODY
    rejected_evidence = repository.failure_calls[0]["evidence"]
    assert isinstance(rejected_evidence, FinancialResponseEvidence)
    assert rejected_evidence.response_scope_basis is FinancialResponseScopeBasis.CALLER_DECLARED


def test_tushare_adapter_binds_retained_body_and_native_row_without_inventing_time(
    monkeypatch: pytest.MonkeyPatch,
    artifact_tmp_path: Path,
) -> None:
    """The adapter binds retained bytes and row identity but keeps source time unknown."""

    audits = _AuditRepository()
    store = _store(artifact_tmp_path)
    repository = FinancialResponseArtifactRepository(store, audits)
    handler = _ConfiguredTushareFinancialResponseHandler(_provider(), repository)
    transport = _CapturingFinancialTransport(FINANCIAL_BODY)
    route = EgressRouteDecision(
        rule_id=11,
        strategy=EgressStrategy.FIXED,
        candidates=(3,),
        reason="financial",
        matched_domain="provider.example.test",
    )
    monkeypatch.setattr(egress_service, "_transport", cast(object, transport))
    monkeypatch.setattr(egress_service, "preview_route", lambda _context: route)
    monkeypatch.setattr(
        adapter_module,
        "build_tushare_financial_gateway",
        lambda **_kwargs: None,
    )
    monkeypatch.setattr(
        adapter_module,
        "build_tushare_financial_response_handler",
        lambda _provider: handler,
    )

    facts = adapter_module.TushareUnifiedProviderAdapter(_provider()).fetch_financials(
        "000001.SZ", periods=2
    )

    assert len(facts) == 1
    fact = facts[0]
    assert fact.asset_code == "000001.SZ"
    assert fact.period_end == date(2025, 12, 31)
    assert fact.report_date == date(2026, 3, 30)
    assert fact.available_at is None
    assert fact.source_evidence is not None
    assert fact.source_evidence.announced_at is None
    assert fact.source_evidence.raw_payload_hash == raw_body_sha256(FINANCIAL_BODY)
    assert (
        fact.source_evidence.source_record_id
        == "tushare:fina_indicator:000001.SZ:20251231:20260330:roe"
    )
    assert fact.source_evidence.is_complete is False
    assert fact.decision_evidence is not None
    assert fact.decision_evidence.native_asset_code == "000001.SZ"
    assert fact.decision_evidence.native_period_end == date(2025, 12, 31)
    assert fact.decision_evidence.native_row_id == fact.source_evidence.source_record_id
    assert len(transport.calls) == 1
    assert transport.responses[0].read_count == 1
    assert len(audits.rows) == 1
    audit = audits.rows[0]
    link = audit.extra["financial_response_artifact"]
    assert isinstance(link, dict)
    assert link["body_sha256"] == raw_body_sha256(FINANCIAL_BODY)
    assert link["body_size_bytes"] == len(FINANCIAL_BODY)
    assert link["response_scope"]["row_count"] == 1
    assert link["response_scope"]["period_ends"] == ["2025-12-31"]
    assert link["response_scope_basis"] == "provider_body_verified"
    assert audit.response_payload_hash == ""
    assert audit.row_count == 1
    assert audit.fetched_at == COMPLETED_AT
    artifact_reference = reference_from_audit(audit)
    assert fact.decision_evidence.artifact_reference == artifact_reference
    assert store.read(artifact_reference) == FINANCIAL_BODY

    provider_repository = Mock()
    provider_repository.get_by_id.return_value = _provider()
    provider_registry = Mock()
    provider_registry.get_by_id.return_value = adapter_module.TushareUnifiedProviderAdapter(
        _provider()
    )
    provider_registry.get_all_statuses.return_value = []
    fact_repository = Mock()
    raw_audit_repository = Mock()
    use_case = SyncFinancialUseCase(
        provider_repo=provider_repository,
        provider_registry=provider_registry,
        fact_repo=fact_repository,
        raw_audit_repo=raw_audit_repository,
        artifact_verifier=lambda _provider_config, reference: store.read(reference)
        == FINANCIAL_BODY,
    )

    with pytest.raises(InvalidInputError) as caught:
        use_case.execute(SyncFinancialRequest(provider_id=7, asset_code="000001.SZ", periods=2))

    assert caught.value.code == "FINANCIAL_SOURCE_EVIDENCE_REQUIRED"
    assert caught.value.details == {
        "block_reasons": [
            "financial_available_at_missing",
            "financial_source_evidence_incomplete",
        ]
    }
    fact_repository.bulk_upsert.assert_not_called()


def test_artifact_config_requires_explicit_complete_values(monkeypatch: pytest.MonkeyPatch) -> None:
    """A missing switch preserves legacy mode; enabled mode has no implicit defaults."""

    monkeypatch.setattr(config_module, "get_runtime_config_value", lambda *_args, **_kwargs: None)
    assert resolve_financial_response_artifact_config(environment="test") is None

    values = {ARTIFACT_ENABLED_KEY: True}

    def runtime_value(key: str, **_kwargs: object) -> object | None:
        """Return only the explicit test profile values."""

        return values.get(key)

    monkeypatch.setattr(config_module, "get_runtime_config_value", runtime_value)
    with pytest.raises(FinancialResponseArtifactConfigurationError):
        resolve_financial_response_artifact_config(environment="test")


@pytest.mark.parametrize("enabled", [None, False])
def test_disabled_artifact_retention_preserves_unpersisted_provider(
    monkeypatch: pytest.MonkeyPatch, enabled: bool | None
) -> None:
    """An opt-in feature must not reject an existing unsaved legacy provider."""

    monkeypatch.setattr(
        config_module, "get_runtime_config_value", lambda *_args, **_kwargs: enabled
    )
    provider = ProviderConfig(**{**_provider().__dict__, "id": None})
    assert build_financial_response_artifact_repository(provider, environment="test") is None


def test_artifact_config_builds_only_for_explicit_https_provider(
    monkeypatch: pytest.MonkeyPatch,
    artifact_tmp_path: Path,
) -> None:
    """Configured Tushare retention rejects HTTP and accepts a credential-free HTTPS origin."""

    key = Fernet.generate_key().decode("ascii")
    values: dict[str, object] = {
        ARTIFACT_ENABLED_KEY: True,
        ARTIFACT_ROOT_KEY: str(artifact_tmp_path),
        ARTIFACT_KEY_VERSION_KEY: "v1",
        ARTIFACT_MAX_BODY_BYTES_KEY: 1024,
    }
    monkeypatch.setattr(
        config_module,
        "get_runtime_config_value",
        lambda key_name, **_kwargs: values.get(key_name),
    )
    monkeypatch.setattr(config_module, "get_active_runtime_secret_ref", lambda **_kwargs: "ref")
    monkeypatch.setattr(config_module, "resolve_config_secret", lambda _ref: key)

    repository = build_financial_response_artifact_repository(_provider(), environment="test")
    assert repository is not None
    insecure = ProviderConfig(
        **{**_provider().__dict__, "http_url": "http://provider.example.test/tushare"}
    )
    with pytest.raises(FinancialResponseArtifactConfigurationError):
        build_financial_response_artifact_repository(insecure, environment="test")


def test_reference_from_audit_requires_the_versioned_link_schema() -> None:
    """A non-financial or unversioned audit row cannot be treated as an artifact link."""

    audit = RawAudit(
        provider_name="Tushare Pro",
        capability="financial",
        request_params={},
        status="ok",
        extra={"financial_response_artifact": {"schema": "legacy"}},
    )
    with pytest.raises(ValueError):
        reference_from_audit(audit)
    with pytest.raises(ValueError):
        reference_from_audit(replace(audit, status="error"))


def test_activation_validates_all_options_before_registering_definitions(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An incomplete activation cannot mutate even the Config Center registry."""

    registered = False

    def register() -> tuple[str, ...]:
        """Record whether the command reached its write boundary."""

        nonlocal registered
        registered = True
        return ()

    monkeypatch.setattr(Command, "_register_definitions", staticmethod(register))
    with pytest.raises(CommandError):
        Command().handle(
            register=False,
            activate=True,
            environment="test",
            enabled="true",
            root="",
            encryption_key_ref="",
            encryption_key_version="",
            max_body_bytes=None,
            actor="operator",
            reason="enable artifact retention",
        )
    assert registered is False


def test_raw_audit_artifact_lookup_uses_one_json_selector_query(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Artifact replay lookup filters JSON in SQL instead of scanning audit rows."""

    expected = object()

    class _Query:
        def __init__(self) -> None:
            self.ordering: tuple[str, ...] = ()

        def order_by(self, *fields: str) -> _Query:
            self.ordering = fields
            return self

        def first(self) -> object:
            return object()

        def __iter__(self) -> Iterable[object]:
            raise AssertionError("artifact lookup must not iterate all audit rows")

    class _Manager:
        def __init__(self, query: _Query) -> None:
            self.query = query
            self.filters: dict[str, object] = {}

        def filter(self, **filters: object) -> _Query:
            self.filters = filters
            return self.query

    query = _Query()
    manager = _Manager(query)

    class _RawAuditModelModule:
        objects = manager

    monkeypatch.setattr(provider_state_repositories, "RawAuditModel", _RawAuditModelModule)
    monkeypatch.setattr(
        RawAuditRepository,
        "_from_model",
        staticmethod(lambda _model: expected),
    )

    result = RawAuditRepository().find_by_artifact_capture_id(CAPTURE_ID)

    assert result is expected
    assert manager.filters == {
        "capability": "financial",
        "extra__financial_response_artifact__capture_id": str(CAPTURE_ID),
    }
    assert query.ordering == ("-fetched_at", "-pk")


def test_raw_audit_failure_lookup_uses_dedicated_json_selector_query(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Failure replay lookup remains separate from successful artifact rows."""

    expected = object()

    class _Query:
        def __init__(self) -> None:
            self.ordering: tuple[str, ...] = ()

        def order_by(self, *fields: str) -> _Query:
            self.ordering = fields
            return self

        def first(self) -> object:
            return object()

        def __iter__(self) -> Iterable[object]:
            raise AssertionError("failure lookup must not iterate all audit rows")

    class _Manager:
        def __init__(self, query: _Query) -> None:
            self.query = query
            self.filters: dict[str, object] = {}

        def filter(self, **filters: object) -> _Query:
            self.filters = filters
            return self.query

    query = _Query()
    manager = _Manager(query)

    class _RawAuditModelModule:
        objects = manager

    monkeypatch.setattr(provider_state_repositories, "RawAuditModel", _RawAuditModelModule)
    monkeypatch.setattr(
        RawAuditRepository,
        "_from_model",
        staticmethod(lambda _model: expected),
    )

    result = RawAuditRepository().find_by_failure_capture_id(CAPTURE_ID)

    assert result is expected
    assert manager.filters == {
        "capability": "financial_response_failure",
        "extra__financial_response_failure_artifact__capture_id": str(CAPTURE_ID),
    }
    assert query.ordering == ("-fetched_at", "-pk")
