"""Composition root for isolated full-scope financial discovery."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, replace
from datetime import date, datetime
from pathlib import Path
from typing import Literal, cast

from apps.data_center.application.financial_scope_manifest_bootstrap import (
    FinancialScopeDiscoveryUseCase,
    independently_review_financial_scope_candidate,
)
from apps.data_center.domain.entities import ProviderConfig
from apps.data_center.domain.financial_scope_discovery import (
    FinancialScopeDiscoveryBinding,
    FinancialScopeDiscoveryCandidate,
    FinancialScopeDiscoveryError,
    FinancialScopeReviewedManifest,
)
from apps.data_center.infrastructure.akshare_financial_slice_sync import (
    akshare_financial_deployment_region,
)
from apps.data_center.infrastructure.financial_response_artifact_config import (
    resolve_financial_response_artifact_config,
)
from apps.data_center.infrastructure.financial_response_artifact_repository import (
    FinancialResponseArtifactRepository,
)
from apps.data_center.infrastructure.financial_response_body_store import (
    FinancialResponseBodyStore,
)
from apps.data_center.infrastructure.financial_scope_discovery_governance import (
    DjangoFinancialScopeDiscoveryAuthorizationSource,
    DjangoFinancialScopeManifestReviewSource,
)
from apps.data_center.infrastructure.financial_scope_discovery_reader import (
    AkshareFinancialScopeDiscoveryReader,
    financial_scope_discovery_parser_sha256,
    load_financial_scope_discovery_contract,
)
from apps.data_center.infrastructure.provider_state_repositories import RawAuditRepository
from apps.data_center.infrastructure.rehearsal_identity import (
    configured_akshare_financial_identity,
    rehearsal_identity_dict,
)
from apps.data_center.infrastructure.s6_rehearsal_artifact_root import (
    validate_s6_rehearsal_artifact_root,
)
from apps.data_center.target_date_universe_composition import (
    build_target_date_a_share_universe_scope,
)


@dataclass(frozen=True, slots=True)
class FinancialScopeDiscoveryComposition:
    """Composed use case plus the database/image isolation attestation digest."""

    use_case: FinancialScopeDiscoveryUseCase
    isolation_attestation_sha256: str


@dataclass(frozen=True, slots=True)
class TargetDateFinancialScopeDiscoveryUniverseSource:
    """Re-read the active A-share universe eligible on one frozen target date."""

    target_trade_date: date

    def __post_init__(self) -> None:
        """Reject datetimes and other ambiguous target-date values."""

        if not isinstance(self.target_trade_date, date) or isinstance(
            self.target_trade_date, datetime
        ):
            raise FinancialScopeDiscoveryError("FINANCIAL_SCOPE_DISCOVERY_CONTRACT_INVALID")

    def get_active_asset_codes(self) -> tuple[str, ...]:
        """Return the target-date requested universe, re-reading drift evidence."""

        return build_target_date_a_share_universe_scope(self.target_trade_date).requested_codes


def build_financial_scope_discovery_binding(
    *,
    provider: ProviderConfig,
    candidate_sha: str,
) -> FinancialScopeDiscoveryBinding:
    """Freeze candidate, live provider identity, query contract, parser, and region."""

    if (
        provider.id is None
        or isinstance(provider.id, bool)
        or provider.id <= 0
        or provider.is_active is not True
        or provider.source_type.casefold() != "akshare"
    ):
        raise FinancialScopeDiscoveryError("FINANCIAL_SCOPE_DISCOVERY_PROVIDER_IDENTITY_INVALID")
    contract = load_financial_scope_discovery_contract()
    identity = configured_akshare_financial_identity(provider_id=provider.id)
    identity_sha256 = _canonical_sha256(rehearsal_identity_dict(identity))
    return FinancialScopeDiscoveryBinding(
        candidate_sha=candidate_sha,
        provider_id=provider.id,
        provider_name="akshare",
        provider_identity_sha256=identity_sha256,
        contract_id=_required_text(contract, "contract_id"),
        contract_version=_required_text(contract, "contract_version"),
        contract_sha256=_required_text(contract, "contract_sha256"),
        parser_id=str(cast(dict[str, object], contract["parser"])["parser_id"]),
        parser_sha256=financial_scope_discovery_parser_sha256(),
        deployment_region=akshare_financial_deployment_region(),
    )


def make_financial_scope_discovery_use_case(
    *,
    provider: ProviderConfig,
    candidate_sha: str,
    expected_database_name: str,
    expected_database_host: str,
    artifact_storage_root: Path,
    target_trade_date: date,
    environment: Literal["development", "test", "staging", "production"] | None = None,
) -> FinancialScopeDiscoveryComposition:
    """Compose the isolated-only discovery workflow from existing egress and audit ports."""

    from apps.data_center.composition import preflight_financial_capacity_isolation

    isolation_attestation_sha256 = preflight_financial_capacity_isolation(
        candidate_sha=candidate_sha,
        expected_database_name=expected_database_name,
        expected_database_host=expected_database_host,
    )
    if artifact_storage_root.exists() or artifact_storage_root.is_symlink():
        raise FinancialScopeDiscoveryError("FINANCIAL_SCOPE_DISCOVERY_RAW_ARTIFACT_INVALID")
    if (
        provider.id is None
        or isinstance(provider.id, bool)
        or provider.is_active is not True
        or provider.source_type.casefold() != "akshare"
    ):
        raise FinancialScopeDiscoveryError("FINANCIAL_SCOPE_DISCOVERY_PROVIDER_IDENTITY_INVALID")
    if re.fullmatch(r"[0-9a-f]{40}", candidate_sha) is None:
        raise FinancialScopeDiscoveryError("FINANCIAL_SCOPE_DISCOVERY_CONTRACT_INVALID")
    runtime = resolve_financial_response_artifact_config(
        environment=environment,
    )
    if runtime is None:
        raise FinancialScopeDiscoveryError("FINANCIAL_SCOPE_DISCOVERY_RAW_ARTIFACT_INVALID")
    runtime = replace(
        runtime,
        root=validate_s6_rehearsal_artifact_root(
            artifact_storage_root,
            protected_root=runtime.root,
        ),
    )
    audits = RawAuditRepository()
    repository = FinancialResponseArtifactRepository(
        FinancialResponseBodyStore(
            runtime.root,
            encryption_key=runtime.encryption_key,
            encryption_key_ref=runtime.encryption_key_ref,
            encryption_key_version=runtime.encryption_key_version,
            max_body_bytes=runtime.max_body_bytes,
        ),
        audits,
        failure_audit_repository=audits,
    )
    reader = AkshareFinancialScopeDiscoveryReader(
        provider,
        deployment_region=akshare_financial_deployment_region(),
        artifact_repository=repository,
        maximum_body_bytes=runtime.max_body_bytes,
    )
    universe_source = TargetDateFinancialScopeDiscoveryUniverseSource(target_trade_date)
    return FinancialScopeDiscoveryComposition(
        use_case=FinancialScopeDiscoveryUseCase(
            reader=reader,
            authorization_source=DjangoFinancialScopeDiscoveryAuthorizationSource(),
            universe_source=universe_source,
        ),
        isolation_attestation_sha256=isolation_attestation_sha256,
    )


def review_financial_scope_candidate(
    candidate: FinancialScopeDiscoveryCandidate,
    *,
    environment: Literal["isolated", "production"],
    report_sha256: str,
    now: datetime,
) -> FinancialScopeReviewedManifest:
    """Require dual persisted approvals bound to the report and target environment."""

    return independently_review_financial_scope_candidate(
        candidate=candidate,
        source=DjangoFinancialScopeManifestReviewSource(),
        environment=environment,
        report_sha256=report_sha256,
        now=now,
    )


def _canonical_sha256(value: object) -> str:
    """Hash a non-secret canonical identity projection."""

    encoded = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _required_text(payload: dict[str, object], key: str) -> str:
    """Read one required non-secret contract token without coercion."""

    value = payload.get(key)
    if type(value) is not str or not value or value != value.strip():
        raise FinancialScopeDiscoveryError("FINANCIAL_SCOPE_DISCOVERY_CONTRACT_INVALID")
    return value


__all__ = [
    "FinancialScopeDiscoveryComposition",
    "TargetDateFinancialScopeDiscoveryUniverseSource",
    "build_financial_scope_discovery_binding",
    "make_financial_scope_discovery_use_case",
]
