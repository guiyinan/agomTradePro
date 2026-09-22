"""Fail-closed composition for independent financial source-time verification."""

from __future__ import annotations

from pathlib import Path

from django.conf import settings
from django.db import DatabaseError

from apps.data_center.application.financial_source_time_verifier import (
    FinancialSourceTimeContractMatcher,
    FinancialSourceTimeEvidenceVerifier,
)
from apps.data_center.domain.entities import ProviderConfig
from apps.data_center.domain.financial_source_evidence import FinancialFactDecisionEvidence
from apps.data_center.infrastructure.financial_response_artifact_config import (
    resolve_financial_response_artifact_config,
)
from apps.data_center.infrastructure.financial_response_body_store import (
    FinancialResponseBodyStore,
)
from apps.data_center.infrastructure.financial_source_time_audit import (
    DjangoFinancialSourceTimeAuditReader,
    StrictFinancialSourceTimeAuditLinkVerifier,
)
from apps.data_center.infrastructure.financial_source_time_body_store import (
    FinancialSourceTimeBodyStore,
)
from apps.data_center.infrastructure.financial_source_time_contract_registry import (
    load_financial_source_time_contract_registry,
)
from apps.data_center.infrastructure.provider_state_repositories import RawAuditRepository
from core.exceptions import DataFetchError

_MATCHERS: dict[str, FinancialSourceTimeContractMatcher] = {}


def verify_retained_financial_source_time_evidence(
    decision_evidence: FinancialFactDecisionEvidence,
) -> bool:
    """Verify both encrypted artifacts and audits under an active parser contract.

    The checked-in registry and matcher table are intentionally empty. The
    function is still injected into every canonical write/publication path so
    those paths share one fail-closed boundary before the first real provider
    contract is approved.
    """

    return _verify_source_time_evidence(
        decision_evidence,
        environment=None,
        expected_provider_id=None,
    )


def verify_provider_financial_source_time_evidence(
    provider: ProviderConfig,
    evidence: FinancialFactDecisionEvidence,
) -> bool:
    """Bind source-time verification to the active provider configuration row."""

    request_provider = evidence.artifact_reference.evidence.request_scope.provider_name
    if (
        not isinstance(provider, ProviderConfig)
        or provider.id is None
        or isinstance(provider.id, bool)
        or provider.id <= 0
        or provider.name != request_provider
    ):
        return False
    return _verify_source_time_evidence(
        evidence,
        environment=None,
        expected_provider_id=int(provider.id),
    )


def _verify_source_time_evidence(
    decision_evidence: FinancialFactDecisionEvidence,
    *,
    environment: str | None,
    expected_provider_id: int | None,
) -> bool:
    """Build and execute the shared read-only verifier implementation."""

    try:
        witness = decision_evidence.source_time_witness
        if witness is None:
            return False
        registry = load_financial_source_time_contract_registry(
            Path(settings.BASE_DIR) / "governance" / "financial_source_time_match_contracts.json"
        )
        provider_name = decision_evidence.artifact_reference.evidence.request_scope.provider_name
        contract = registry.get(
            provider_name=provider_name,
            contract_id=witness.governed_match_contract_id,
            contract_version=witness.governed_match_contract_version,
            contract_sha256=witness.governed_match_contract_sha256,
        )
        if contract is None:
            return False
        matcher = _MATCHERS.get(contract.parser_version)
        if matcher is None:
            return False
        runtime = resolve_financial_response_artifact_config(environment=environment)
        if runtime is None:
            return False
        financial_store = FinancialResponseBodyStore(
            runtime.root,
            encryption_key=runtime.encryption_key,
            encryption_key_ref=runtime.encryption_key_ref,
            encryption_key_version=runtime.encryption_key_version,
            max_body_bytes=runtime.max_body_bytes,
        )
        source_time_store = FinancialSourceTimeBodyStore(
            runtime.root,
            encryption_key=runtime.encryption_key,
            encryption_key_ref=runtime.encryption_key_ref,
            encryption_key_version=runtime.encryption_key_version,
            max_body_bytes=runtime.max_body_bytes,
        )
        audit_reader = DjangoFinancialSourceTimeAuditReader(RawAuditRepository())
        verifier = FinancialSourceTimeEvidenceVerifier(
            financial_body_reader=financial_store.read,
            source_time_body_reader=source_time_store.read,
            audit_reader=audit_reader,
            contract_reader=registry,
            audit_link_verifier=StrictFinancialSourceTimeAuditLinkVerifier(
                expected_provider_id=expected_provider_id
            ),
            matcher=matcher,
        )
        return verifier.verify(decision_evidence)
    except (DatabaseError, DataFetchError, LookupError, OSError, TypeError, ValueError):
        return False


__all__ = [
    "verify_provider_financial_source_time_evidence",
    "verify_retained_financial_source_time_evidence",
]
