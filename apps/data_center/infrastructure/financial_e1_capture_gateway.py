"""Bounded egress and retained-body gateway for the isolated E1 candidate.

The adapter uses the normal Data Center financial egress runner and
FinancialResponseArtifactRepository. It does not supply endpoint policy,
metric units, row filters, Owner qualification, or production composition.
Only one send is permitted for each endpoint slot and the caller's shared
two-send budget is passed through unchanged.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Literal, Protocol
from uuid import UUID

from apps.data_center.application.egress_service import (
    FinancialResponseAttemptBudget,
    FinancialResponseCaptureProtocol,
    execute_financial_response_request,
)
from apps.data_center.application.financial_e1_capture_use_case import (
    FinancialE1RetainedResponse,
)
from apps.data_center.application.financial_numeric_verification import (
    FinancialNativeProviderIdentityPort,
)
from apps.data_center.domain.egress_routing import EgressRequestContext
from apps.data_center.domain.entities import RawAudit
from apps.data_center.domain.financial_e1_capture_contract import (
    FinancialE1EndpointRequest,
)
from apps.data_center.domain.financial_response_evidence import (
    FinancialRequestScope,
    FinancialResponseBodyScope,
    FinancialResponseEvidence,
    FinancialResponseScope,
    FinancialResponseScopeBasis,
    raw_body_sha256,
)
from apps.data_center.infrastructure.financial_response_artifact_repository import (
    FinancialResponseArtifactRepository,
    reference_from_audit,
)
from core.exceptions import DataFetchError


class FinancialE1CaptureInfrastructureError(DataFetchError):
    """Stable failure raised when E1 transport or retained evidence is invalid."""

    default_message = "E1 原始财报响应无法通过来源与留存校验。"
    default_code = "FINANCIAL_E1_RETAINED_CAPTURE_INVALID"


class FinancialE1RequestProjectionPort(Protocol):
    """Build the exact configured request context for one plan endpoint."""

    def project(self, request: FinancialE1EndpointRequest) -> FinancialE1RequestProjection:
        """Return request parameters and egress scope bound to this exact request."""
        ...


class FinancialE1ResponseScopeVerifierPort(Protocol):
    """Replay one exact response body and establish provider-derived coverage."""

    def verify(
        self,
        request: FinancialE1EndpointRequest,
        *,
        raw_body: bytes,
        payload: object,
        evidence: FinancialResponseEvidence,
    ) -> FinancialResponseEvidence:
        """Return provider-body-verified evidence or raise on any row mismatch."""
        ...


class FinancialE1AuditCollectionPort(Protocol):
    """Read every RawAudit row linked to one response capture UUID."""

    def list_by_artifact_capture_id(self, capture_id: UUID) -> list[RawAudit]:
        """Return all matching successful and failure audit events."""
        ...


class FinancialE1EgressRunnerPort(Protocol):
    """Execute one financial request through the existing governed egress."""

    def __call__(
        self,
        context: EgressRequestContext,
        *,
        request_id: UUID,
        method: Literal["GET", "POST"],
        params: Mapping[str, object] | None,
        json_body: Mapping[str, object] | None,
        headers: Mapping[str, str] | None,
        request_scope: FinancialRequestScope,
        response_scope: FinancialResponseScope,
        max_attempts: int,
        attempt_budget: FinancialResponseAttemptBudget,
    ) -> FinancialResponseCaptureProtocol:
        """Return captured transport bytes with the observed physical count."""
        ...


@dataclass(frozen=True, slots=True)
class FinancialE1RequestProjection:
    """Endpoint-specific safe request and route inputs prepared by composition."""

    request: FinancialE1EndpointRequest
    context: EgressRequestContext
    method: Literal["GET", "POST"]
    params: Mapping[str, object] | None
    json_body: Mapping[str, object] | None
    headers: Mapping[str, str] | None
    request_scope: FinancialRequestScope
    declared_response_scope: FinancialResponseScope
    provider_id: int

    def __post_init__(self) -> None:
        """Reject request projections that change endpoint identity or scope."""

        if type(self.request) is not FinancialE1EndpointRequest:
            raise ValueError("E1 projection requires a typed endpoint request")
        if type(self.context) is not EgressRequestContext:
            raise ValueError("E1 projection requires an explicit egress context")
        if self.method not in {"GET", "POST"}:
            raise ValueError("E1 projection method must be GET or POST")
        if type(self.request_scope) is not FinancialRequestScope:
            raise ValueError("E1 request scope must be typed")
        if type(self.declared_response_scope) is not FinancialResponseScope:
            raise ValueError("E1 declared response scope must be typed")
        if type(self.provider_id) is not int or self.provider_id <= 0:
            raise ValueError("E1 provider identity must be a positive persisted id")
        if (
            self.context.provider_id != self.provider_id
            or self.context.dataset_key != self.request.dataset_key
            or self.request_scope.provider_name != self.request.provider_name
            or self.request_scope.dataset_key != self.request.dataset_key
            or self.request_scope.asset_code != self.request.request_asset_code
        ):
            raise ValueError("E1 request projection does not match its persisted route identity")
        if (
            self.declared_response_scope.asset_codes != (self.request.request_asset_code,)
            or self.declared_response_scope.period_ends
            or self.declared_response_scope.row_count != 0
        ):
            raise ValueError("E1 transport must begin with an empty caller-declared scope")


class FinancialE1RetainedCaptureGateway:
    """Use normal egress, exact scope replay, successful RawAudit, and readback."""

    def __init__(
        self,
        *,
        projection_port: FinancialE1RequestProjectionPort,
        provider_identity_resolver: FinancialNativeProviderIdentityPort,
        scope_verifiers: Mapping[str, FinancialE1ResponseScopeVerifierPort],
        artifact_repository: FinancialResponseArtifactRepository,
        audit_repository: FinancialE1AuditCollectionPort,
        capture_runner: FinancialE1EgressRunnerPort = execute_financial_response_request,
    ) -> None:
        """Require explicit endpoint parsers and the existing retained artifact path."""

        if (
            projection_port is None
            or provider_identity_resolver is None
            or artifact_repository is None
            or audit_repository is None
        ):
            raise TypeError("E1 projection, provider, artifact, and audit ports are required")
        if not isinstance(scope_verifiers, Mapping) or not scope_verifiers:
            raise TypeError("E1 endpoint scope verifiers must be explicitly configured")
        normalized: dict[str, FinancialE1ResponseScopeVerifierPort] = {}
        for endpoint, verifier in scope_verifiers.items():
            if type(endpoint) is not str or not endpoint or endpoint != endpoint.strip():
                raise ValueError("E1 scope verifier endpoint keys must be exact text")
            if verifier is None:
                raise TypeError("E1 endpoint scope verifier cannot be missing")
            normalized[endpoint] = verifier
        self._projection_port = projection_port
        self._provider_identity_resolver = provider_identity_resolver
        self._scope_verifiers = normalized
        self._artifact_repository = artifact_repository
        self._audit_repository = audit_repository
        self._capture_runner = capture_runner

    def capture_one(
        self,
        request: FinancialE1EndpointRequest,
        *,
        request_id: UUID,
        attempt_budget: FinancialResponseAttemptBudget,
        run_id: UUID | None,
    ) -> FinancialE1RetainedResponse:
        """Capture exactly once, retain exact bytes, and verify their unique audit."""

        if type(request) is not FinancialE1EndpointRequest:
            raise FinancialE1CaptureInfrastructureError(code="FINANCIAL_E1_REQUEST_INVALID")
        if (
            type(request_id) is not UUID
            or type(attempt_budget) is not FinancialResponseAttemptBudget
        ):
            raise FinancialE1CaptureInfrastructureError(code="FINANCIAL_E1_ATTEMPT_BUDGET_INVALID")
        if run_id is not None and type(run_id) is not UUID:
            raise FinancialE1CaptureInfrastructureError(code="FINANCIAL_E1_RUN_ID_INVALID")
        if request.max_attempts != 1 or request.pagination_policy != "one_response":
            raise FinancialE1CaptureInfrastructureError(code="FINANCIAL_E1_RETRY_OR_PAGE_FORBIDDEN")
        if (
            attempt_budget.maximum_attempts != 2
            or attempt_budget.reserved_attempts >= attempt_budget.maximum_attempts
        ):
            raise FinancialE1CaptureInfrastructureError(code="FINANCIAL_E1_SEND_BUDGET_EXHAUSTED")
        try:
            projection = self._projection_port.project(request)
            request_params = _audit_params(request, projection)
        except (DataFetchError, OSError, RuntimeError, TypeError, ValueError) as exc:
            raise FinancialE1CaptureInfrastructureError(
                code="FINANCIAL_E1_REQUEST_PROJECTION_BLOCKED"
            ) from exc
        if type(projection) is not FinancialE1RequestProjection or projection.request != request:
            raise FinancialE1CaptureInfrastructureError(
                code="FINANCIAL_E1_REQUEST_PROJECTION_MISMATCH"
            )
        try:
            provider_identity = self._provider_identity_resolver.resolve_by_id(
                projection.provider_id
            )
        except (DataFetchError, OSError, RuntimeError, TypeError, ValueError) as exc:
            raise FinancialE1CaptureInfrastructureError(
                code="FINANCIAL_E1_PROVIDER_IDENTITY_UNAVAILABLE"
            ) from exc
        if (
            provider_identity is None
            or provider_identity.provider_id != projection.provider_id
            or provider_identity.source_type != request.provider_name
            or provider_identity.is_active is not True
        ):
            raise FinancialE1CaptureInfrastructureError(
                code="FINANCIAL_E1_PROVIDER_IDENTITY_MISMATCH"
            )
        verifier = self._scope_verifiers.get(request.endpoint)
        if verifier is None:
            raise FinancialE1CaptureInfrastructureError(code="FINANCIAL_E1_ENDPOINT_UNSUPPORTED")

        reserved_before = attempt_budget.reserved_attempts
        try:
            captured = self._capture_runner(
                projection.context,
                request_id=request_id,
                method=projection.method,
                params=projection.params,
                json_body=projection.json_body,
                headers=projection.headers,
                request_scope=projection.request_scope,
                response_scope=projection.declared_response_scope,
                max_attempts=request.max_attempts,
                attempt_budget=attempt_budget,
            )
        except (DataFetchError, OSError, RuntimeError, TimeoutError, TypeError, ValueError):
            raise
        attempt_delta = attempt_budget.reserved_attempts - reserved_before
        body = getattr(captured, "raw_body", None)
        evidence = getattr(captured, "evidence", None)
        payload = getattr(captured, "payload", None)
        physical_attempts = getattr(captured, "physical_request_attempts", None)
        if (
            attempt_delta != 1
            or physical_attempts != 1
            or type(body) is not bytes
            or not body
            or type(evidence) is not FinancialResponseEvidence
            or evidence.request_scope != projection.request_scope
            or evidence.response_scope != projection.declared_response_scope
            or evidence.response_scope_basis is not FinancialResponseScopeBasis.CALLER_DECLARED
            or evidence.body_scope is not FinancialResponseBodyScope.BATCH
            or evidence.body_size_bytes != len(body)
            or evidence.body_sha256 != raw_body_sha256(body)
            or type(physical_attempts) is not int
            or physical_attempts != 1
        ):
            raise FinancialE1CaptureInfrastructureError(
                code="FINANCIAL_E1_TRANSPORT_EVIDENCE_INVALID"
            )

        try:
            verified_evidence = verifier.verify(
                request,
                raw_body=body,
                payload=payload,
                evidence=evidence,
            )
            self._validate_verified_evidence(request, evidence, verified_evidence, body)
        except (DataFetchError, OSError, RuntimeError, TypeError, ValueError) as exc:
            self._retain_rejected(
                request=request,
                request_id=request_id,
                projection=projection,
                evidence=evidence,
                body=body,
                run_id=run_id,
            )
            raise FinancialE1CaptureInfrastructureError(
                code="FINANCIAL_E1_BODY_SCOPE_REPLAY_BLOCKED"
            ) from exc

        retention = self._artifact_repository.retain(
            capture_id=request_id,
            evidence=verified_evidence,
            body=body,
            provider_name=request.provider_name,
            request_params=request_params,
            row_count=verified_evidence.response_scope.row_count,
            provider_id=projection.provider_id,
            run_id=run_id,
        )
        stored_body = self._artifact_repository.read(retention.reference)
        if type(stored_body) is not bytes or stored_body != body:
            raise FinancialE1CaptureInfrastructureError(code="FINANCIAL_E1_BODY_READBACK_MISMATCH")
        audit_rows = self._audit_repository.list_by_artifact_capture_id(request_id)
        if (
            len(audit_rows) != 1
            or audit_rows[0] != retention.audit
            or reference_from_audit(audit_rows[0]) != retention.reference
            or retention.audit.provider_name != request.provider_name
            or retention.audit.request_params != request_params
            or retention.audit.fetched_at != verified_evidence.response_completed_at
            or retention.audit.row_count != verified_evidence.response_scope.row_count
            or retention.audit.payload_size_bytes != len(body)
            or not retention.audit.content_hash
        ):
            raise FinancialE1CaptureInfrastructureError(
                code="FINANCIAL_E1_AUDIT_CARDINALITY_INVALID"
            )
        return FinancialE1RetainedResponse(
            request=request,
            retention=retention,
            raw_body=stored_body,
            provider_id=projection.provider_id,
            provider_payload=payload,
            observed_attempts=physical_attempts,
        )

    def _validate_verified_evidence(
        self,
        request: FinancialE1EndpointRequest,
        original: FinancialResponseEvidence,
        verified: FinancialResponseEvidence,
        body: bytes,
    ) -> None:
        """Require the verifier to promote only exact requested response coverage."""

        if (
            type(verified) is not FinancialResponseEvidence
            or verified.body_sha256 != original.body_sha256
            or verified.body_size_bytes != original.body_size_bytes
            or verified.response_completed_at != original.response_completed_at
            or verified.request_scope != original.request_scope
            or verified.body_scope is not original.body_scope
            or verified.response_scope_basis
            is not FinancialResponseScopeBasis.PROVIDER_BODY_VERIFIED
            or verified.response_scope.row_count <= 0
            or verified.response_scope.asset_codes != (request.request_asset_code,)
            or request.request_period_end not in verified.response_scope.period_ends
            or len(body) != verified.body_size_bytes
        ):
            raise ValueError("provider-body replay did not prove this exact request")

    def _retain_rejected(
        self,
        *,
        request: FinancialE1EndpointRequest,
        request_id: UUID,
        projection: FinancialE1RequestProjection,
        evidence: FinancialResponseEvidence,
        body: bytes,
        run_id: UUID | None,
    ) -> None:
        """Preserve parser-rejected bytes through the shared failure-only audit path."""

        try:
            self._artifact_repository.retain_rejected(
                capture_id=request_id,
                evidence=evidence,
                body=body,
                provider_name=request.provider_name,
                request_params=_audit_params(request, projection),
                failure_code="FINANCIAL_E1_BODY_SCOPE_REPLAY_BLOCKED",
                provider_id=projection.provider_id,
            )
        except (DataFetchError, OSError, RuntimeError, TypeError, ValueError) as exc:
            raise FinancialE1CaptureInfrastructureError(
                code="FINANCIAL_E1_REJECTED_BODY_RETENTION_FAILED"
            ) from exc


def _audit_params(
    request: FinancialE1EndpointRequest,
    projection: FinancialE1RequestProjection,
) -> dict[str, object]:
    """Retain GET query fields in the canonical audit shape used by raw replay.

    The endpoint is an audit identity marker and never an upstream query
    parameter. Non-GET/body variants retain their explicit request envelope.
    """

    if projection.method == "GET" and projection.json_body is None:
        parameters = dict(projection.params or {})
        if "endpoint" in parameters:
            raise FinancialE1CaptureInfrastructureError(
                code="FINANCIAL_E1_AUDIT_ENDPOINT_COLLISION"
            )
        return {**parameters, "endpoint": request.endpoint}

    return {
        "endpoint": request.endpoint,
        "method": projection.method,
        "params": dict(projection.params or {}),
        "json_body": dict(projection.json_body or {}),
    }


__all__ = [
    "FinancialE1AuditCollectionPort",
    "FinancialE1CaptureInfrastructureError",
    "FinancialE1EgressRunnerPort",
    "FinancialE1RequestProjection",
    "FinancialE1RequestProjectionPort",
    "FinancialE1ResponseScopeVerifierPort",
    "FinancialE1RetainedCaptureGateway",
]
