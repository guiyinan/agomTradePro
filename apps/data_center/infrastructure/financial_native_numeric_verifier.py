"""Verify exact native financial values against retained, audited provider bytes."""

from __future__ import annotations

import hashlib
from collections.abc import Mapping
from decimal import Decimal
from typing import Protocol
from uuid import UUID

from django.db import DatabaseError

from apps.data_center.application.financial_numeric_verification import (
    FinancialMetricSourceContractCatalogPort,
    FinancialNativeProviderIdentityPort,
    FinancialProviderIdentity,
    FinancialRetainedFinancialBodyPort,
)
from apps.data_center.application.financial_response_artifact import (
    matches_financial_response_body_digest,
)
from apps.data_center.domain.entities import (
    FinancialFact,
    RawAudit,
    raw_audit_content_hash,
)
from apps.data_center.domain.financial_numeric_evidence import (
    FinancialMetricSourceContract,
    NativeFinancialMetricObservation,
)
from apps.data_center.domain.financial_response_artifact import FinancialResponseArtifactRef
from apps.data_center.domain.financial_response_evidence import (
    FinancialResponseScopeBasis,
)
from apps.data_center.domain.financial_source_evidence import FINANCIAL_FACT_DATASET_KEY
from apps.data_center.infrastructure._provider_adapter_base import (
    _period_type_from_period_end,
)
from apps.data_center.infrastructure.financial_response_artifact_config import (
    resolve_financial_response_artifact_config,
)
from apps.data_center.infrastructure.financial_response_artifact_repository import (
    FinancialResponseArtifactRepository,
    reference_from_audit,
)
from apps.data_center.infrastructure.financial_response_body_store import (
    FinancialResponseBodyStore,
)
from apps.data_center.infrastructure.financial_source_time_matchers import (
    AKSHARE_MAIN_FINANCIAL_DATA_ENDPOINT,
    AKSHARE_PROVIDER_NAME,
    _composite_row_id,
    _main_financial_data_rows,
    _row_asset,
    _row_period_end,
)
from apps.data_center.infrastructure.models import ProviderConfigModel
from apps.data_center.infrastructure.provider_state_repositories import RawAuditRepository
from core.exceptions import DataFetchError, DataValidationError


class FinancialNumericEvidenceVerificationError(DataValidationError):
    """Raised when an exact numeric claim cannot be bound to approved bytes."""

    default_message = "金融原生数值证据未能独立验证。"
    default_code = "FINANCIAL_NATIVE_NUMERIC_EVIDENCE_BLOCKED"


class _FinancialArtifactBodyRepository(Protocol):
    """Narrow body read port required by the retained-body verifier."""

    def read(self, reference: FinancialResponseArtifactRef) -> bytes:
        """Return the authenticated exact response buffer."""
        ...


class _FinancialArtifactAuditRepository(Protocol):
    """Exact-cardinality audit lookup port required for one artifact."""

    def list_by_artifact_capture_id(self, capture_id: UUID) -> list[RawAudit]:
        """Return all audit rows attached to an artifact capture UUID."""
        ...


class DjangoFinancialNativeProviderIdentityResolver:
    """Resolve a provider id against the persisted provider catalog."""

    def resolve_by_id(self, provider_id: int) -> FinancialProviderIdentity | None:
        """Return only non-secret provider identity from its exact database row."""

        if type(provider_id) is not int or provider_id <= 0:
            return None
        row = ProviderConfigModel._default_manager.filter(pk=provider_id).first()
        if row is None:
            return None
        return FinancialProviderIdentity(
            provider_id=row.pk,
            name=row.name,
            source_type=row.source_type,
            is_active=row.is_active,
        )


class FinancialNativeRawBodyReader:
    """Read an audited AKShare main-financial body and verify its provider.

    The encrypted body store verifies the artifact envelope and bytes. This
    reader independently binds the reference to the sole successful RawAudit,
    requires the exact owner-approved main-financial endpoint, checks the audit
    content hash and response metadata, resolves its provider id against the
    persisted provider row, then checks the returned bytes again. Current
    provider activation is deliberately not treated as historical evidence. It
    never trusts a caller-supplied hash or body claim alone.
    """

    def __init__(
        self,
        *,
        artifact_repository: _FinancialArtifactBodyRepository,
        audit_repository: _FinancialArtifactAuditRepository,
        provider_identity_resolver: FinancialNativeProviderIdentityPort,
    ) -> None:
        """Bind the encrypted artifact store and exact provider/audit readers."""

        if artifact_repository is None or audit_repository is None:
            raise TypeError("financial retained body and audit readers are required")
        if provider_identity_resolver is None:
            raise TypeError("financial provider identity resolver is required")
        self._artifact_repository = artifact_repository
        self._audit_repository = audit_repository
        self._provider_identity_resolver = provider_identity_resolver

    def read_verified_body(self, reference: FinancialResponseArtifactRef) -> bytes:
        """Return exact bytes only when artifact, audit, and provider all agree."""

        if type(reference) is not FinancialResponseArtifactRef:
            raise FinancialNumericEvidenceVerificationError()
        evidence = reference.evidence
        request_scope = evidence.request_scope
        response_scope = evidence.response_scope
        if (
            request_scope.dataset_key != FINANCIAL_FACT_DATASET_KEY
            or evidence.response_scope_basis
            is not FinancialResponseScopeBasis.PROVIDER_BODY_VERIFIED
            or response_scope.row_count <= 0
        ):
            raise FinancialNumericEvidenceVerificationError()
        try:
            audits = self._audit_repository.list_by_artifact_capture_id(reference.capture_id)
        except DatabaseError as exc:
            raise FinancialNumericEvidenceVerificationError() from exc
        if len(audits) != 1:
            raise FinancialNumericEvidenceVerificationError()
        audit = audits[0]
        request_params: object = audit.request_params
        if (
            audit.capability != "financial"
            or audit.status != "ok"
            or audit.redacted is not True
            or audit.provider_name != request_scope.provider_name
            or not isinstance(request_params, Mapping)
            or request_params.get("endpoint") != AKSHARE_MAIN_FINANCIAL_DATA_ENDPOINT
            or not matches_financial_response_body_digest(audit, reference)
            or audit.payload_size_bytes != reference.body_size_bytes
            or audit.row_count != response_scope.row_count
            or not audit.content_hash
            or audit.content_hash != raw_audit_content_hash(audit)
        ):
            raise FinancialNumericEvidenceVerificationError()
        try:
            audit_reference = reference_from_audit(audit)
        except (KeyError, TypeError, ValueError) as exc:
            raise FinancialNumericEvidenceVerificationError() from exc
        if audit_reference != reference:
            raise FinancialNumericEvidenceVerificationError()

        link_raw: object = audit.extra.get("financial_response_artifact")
        if not isinstance(link_raw, Mapping):
            raise FinancialNumericEvidenceVerificationError()
        provider_id_raw = link_raw.get("provider_id")
        if type(provider_id_raw) is not int or provider_id_raw <= 0:
            raise FinancialNumericEvidenceVerificationError()
        try:
            provider = self._provider_identity_resolver.resolve_by_id(provider_id_raw)
        except DatabaseError as exc:
            raise FinancialNumericEvidenceVerificationError() from exc
        if (
            provider is None
            or provider.provider_id != provider_id_raw
            or provider.source_type != request_scope.provider_name
        ):
            raise FinancialNumericEvidenceVerificationError()

        try:
            body = self._artifact_repository.read(reference)
        except (DataFetchError, OSError, TypeError, ValueError) as exc:
            raise FinancialNumericEvidenceVerificationError() from exc
        if (
            type(body) is not bytes
            or len(body) != reference.body_size_bytes
            or hashlib.sha256(body).hexdigest() != reference.body_sha256
        ):
            raise FinancialNumericEvidenceVerificationError()
        return body


class FinancialNativeNumericEvidenceVerifier:
    """Recompute native exact evidence from an approved contract and raw body.

    This implementation currently understands only the retained AKShare main
    financial-data endpoint named by ``AKSHARE_MAIN_FINANCIAL_DATA_ENDPOINT``.
    Other endpoints and providers remain blocked until their exact native-row
    contracts and parsers are implemented.
    """

    def __init__(
        self,
        catalog: FinancialMetricSourceContractCatalogPort,
        body_reader: FinancialRetainedFinancialBodyPort,
    ) -> None:
        """Require the real exact catalog resolver and retained-body reader."""

        if catalog is None or body_reader is None:
            raise TypeError("financial metric catalog and retained body reader are required")
        self._catalog = catalog
        self._body_reader = body_reader

    def __call__(self, fact: FinancialFact) -> bool:
        """Return true only when original bytes reproduce the exact v2 value."""

        try:
            return self._verify(fact)
        except (
            DatabaseError,
            DataFetchError,
            FinancialNumericEvidenceVerificationError,
            OSError,
            TypeError,
            ValueError,
            LookupError,
            AttributeError,
        ):
            return False

    def _verify(self, fact: FinancialFact) -> bool:
        """Apply exact identity, catalog, body, row, field, and value checks."""

        if type(fact) is not FinancialFact or fact.numeric_schema != "native-decimal-v2":
            return False
        observation = fact.numeric_evidence
        source = fact.source_evidence
        decision = fact.decision_evidence
        value = fact.value
        if (
            type(observation) is not NativeFinancialMetricObservation
            or type(value) is not Decimal
            or not value.is_finite()
            or source is None
            or decision is None
        ):
            return False
        reference = decision.artifact_reference
        contract = observation.contract
        request_scope = reference.evidence.request_scope
        if (
            fact.fetched_at.tzinfo is None
            or fact.fetched_at.utcoffset() is None
            or reference.evidence.response_completed_at > fact.fetched_at
            or fact.period_type != _period_type_from_period_end(fact.period_end)
            or contract.origin != "native"
            or contract.provider != fact.source
            or contract.metric_code != fact.metric_code
            or contract.canonical_unit != fact.unit
            or contract.dataset_key != FINANCIAL_FACT_DATASET_KEY
            or request_scope.dataset_key != contract.dataset_key
            or request_scope.provider_name != contract.provider
            or request_scope.asset_code != fact.asset_code
            or observation.body_sha256 != reference.body_sha256
            or source.raw_payload_hash != reference.body_sha256
            or source.source_record_id != observation.native_row_id
            or decision.native_row_id != observation.native_row_id
            or decision.native_asset_code != fact.asset_code
            or decision.native_period_end != fact.period_end
        ):
            return False

        resolved_contract = self._catalog.resolve_exact(
            observation.contract_identity,
            known_at=fact.fetched_at,
        )
        if (
            type(resolved_contract) is not FinancialMetricSourceContract
            or resolved_contract != contract
            or resolved_contract.identity != observation.contract_identity
            or resolved_contract.content_hash != observation.contract_hash
        ):
            return False
        if contract.provider != AKSHARE_PROVIDER_NAME:
            return False

        body = self._body_reader.read_verified_body(reference)
        rows = _main_financial_data_rows(body)
        if rows is None or len(rows) != reference.evidence.response_scope.row_count:
            return False
        matching_rows = tuple(
            row for row in rows if _composite_row_id(row) == observation.native_row_id
        )
        if len(matching_rows) != 1:
            return False
        row = matching_rows[0]
        if _row_asset(row) != fact.asset_code or _row_period_end(row) != fact.period_end:
            return False
        raw_value: object = row.get(contract.source_field)
        if raw_value is None or isinstance(raw_value, bool) or isinstance(raw_value, float):
            return False
        replayed = NativeFinancialMetricObservation.from_raw_value(
            contract=resolved_contract,
            raw_value=raw_value,
            source_field=contract.source_field,
            body_sha256=reference.body_sha256,
            native_row_id=observation.native_row_id,
        )
        if replayed != observation or value != Decimal(replayed.canonical_value):
            return False
        return True


def build_django_financial_native_numeric_verifier(
    catalog: FinancialMetricSourceContractCatalogPort,
    *,
    environment: str | None = None,
) -> FinancialNativeNumericEvidenceVerifier:
    """Build an exact verifier from explicitly configured retained artifact storage.

    Missing encryption or storage configuration is a stable block. This
    builder performs no provider request and does not invent catalog rows.
    """

    runtime = resolve_financial_response_artifact_config(environment=environment)
    if runtime is None:
        raise FinancialNumericEvidenceVerificationError(
            "金融原始响应保留未显式配置，原生数值验证已阻断。"
        )
    audits = RawAuditRepository()
    store = FinancialResponseBodyStore(
        runtime.root,
        encryption_key=runtime.encryption_key,
        encryption_key_ref=runtime.encryption_key_ref,
        encryption_key_version=runtime.encryption_key_version,
        max_body_bytes=runtime.max_body_bytes,
    )
    artifact_repository = FinancialResponseArtifactRepository(
        store,
        audits,
        failure_audit_repository=audits,
    )
    body_reader = FinancialNativeRawBodyReader(
        artifact_repository=artifact_repository,
        audit_repository=audits,
        provider_identity_resolver=DjangoFinancialNativeProviderIdentityResolver(),
    )
    return FinancialNativeNumericEvidenceVerifier(catalog, body_reader)


__all__ = [
    "DjangoFinancialNativeProviderIdentityResolver",
    "FinancialNativeNumericEvidenceVerifier",
    "FinancialNativeRawBodyReader",
    "FinancialNumericEvidenceVerificationError",
    "build_django_financial_native_numeric_verifier",
]
