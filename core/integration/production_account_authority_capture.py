"""Production composition for complete Account authority capture.

This module only prepares the complete authority proof used by a later
publication activation. It does not enter the activation fence or mutate any
publication pointer.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import AbstractContextManager, contextmanager
from dataclasses import dataclass, field, replace
from datetime import datetime
from typing import Literal, NoReturn, cast

from apps.account.application.owner_tenant_authority_v3 import (
    GetCurrentOwnerTenantAuthorityV3Command,
)
from apps.account.application.owner_tenant_authority_v3_contracts import (
    CurrentOwnerTenantAuthorityV3,
)
from apps.account.application.physical_account_row_observation_v2 import (
    ExactPhysicalSimulatedAccountRowV2Provider,
    PhysicalAccountRowProviderIdentity,
)
from apps.account.infrastructure.account_authority_final_revalidation_v3_repository import (
    DjangoAccountAuthorityV3RootRevocationRevalidationRepository,
)
from apps.account.infrastructure.account_authority_final_revalidator_v3 import (
    AccountAuthorityCompleteGraphFinalRevalidationProofV3,
    AccountAuthorityFinalRevalidatorV3,
    AccountAuthorityV3CompleteGraphRevalidationResult,
)
from apps.account.infrastructure.account_authority_shadow_scanner import (
    AccountAuthorityCurrentGraphReaderV3,
    AccountAuthorityCurrentGraphSelectorV3,
    AccountAuthorityShadowFingerprintV3,
    AccountAuthorityShadowScannerV3,
    AccountAuthorityShadowScanResultV3,
)
from apps.account.system_audit_authority_v3_composition import (
    AccountSystemAuditOwnerTenantAuthorityV3Reader,
)
from apps.audit.application.system_audit_authority_provider import (
    ExactScopedSystemAuditAuthorityProvider,
    SystemAuditAuthorityBundleSelector,
)
from apps.audit.application.system_audit_authority_schema import (
    SYSTEM_AUDIT_SCOPE_SCHEMA_V3,
)
from apps.audit.application.system_audit_composition import (
    SystemAuditCompositionUnavailable,
    get_system_audit_reader_context,
)
from apps.audit.application.system_audit_query import SystemAuditReaderContext
from apps.simulated_trading.account_physical_row_v2_composition import (
    build_account_physical_row_v2_provider,
)
from core.integration.system_audit_authority import (
    AccountSystemAuditScopeAuthorityV3Adapter,
    SystemAuditAuthorityReaders,
    build_system_audit_authority_readers,
)
from core.integration.system_audit_runtime_config import (
    SystemAuditRuntimeConfigBinding,
    load_system_audit_runtime_config,
)

_PRODUCTION_ENVIRONMENT = "production"
_GENERATION_FENCED_MODE: Literal["generation_fenced_read_committed_read_write"] = (
    "generation_fenced_read_committed_read_write"
)


@dataclass(frozen=True, slots=True)
class ProductionAccountAuthorityCapture:
    """Return the alias-bound activation fence and its opaque one-use proof."""

    database_alias: str
    authority_fence: ProductionAccountAuthorityFence
    authority_proof: AccountAuthorityCompleteGraphFinalRevalidationProofV3 = field(repr=False)

    def __post_init__(self) -> None:
        """Keep the fence and proof bound to the same explicit alias."""

        _require_database_alias(self.database_alias)
        if type(self.authority_fence) is not ProductionAccountAuthorityFence:
            raise TypeError("production authority fence type was substituted")
        if type(self.authority_proof) is not AccountAuthorityCompleteGraphFinalRevalidationProofV3:
            raise TypeError("complete Account authority proof type was substituted")
        if (
            self.authority_fence.database_alias != self.database_alias
            or self.authority_fence.authority_proof is not self.authority_proof
        ):
            raise ValueError("production authority capture components are not bound together")


@dataclass(frozen=True, slots=True)
class ProductionAccountAuthorityFence:
    """Bound the opaque proof to its preflight scope and expiry ceiling."""

    database_alias: str
    authority_proof: AccountAuthorityCompleteGraphFinalRevalidationProofV3 = field(repr=False)
    _delegate: AccountAuthorityFinalRevalidatorV3 = field(repr=False, compare=False)
    _tenant_id: str = field(repr=False)
    _owner_id: str = field(repr=False)
    _valid_until: datetime = field(repr=False)

    def __post_init__(self) -> None:
        """Reject mismatched proof, alias, or scope before a fence is entered."""

        _require_database_alias(self.database_alias)
        if type(self.authority_proof) is not AccountAuthorityCompleteGraphFinalRevalidationProofV3:
            raise TypeError("complete Account authority proof type was substituted")
        if type(self._delegate) is not AccountAuthorityFinalRevalidatorV3:
            raise TypeError("Account authority finalizer type was substituted")
        _require_scope_token(self._tenant_id, "tenant_id")
        _require_scope_token(self._owner_id, "owner_id")
        _require_aware_datetime(self._valid_until, "authority valid_until")

    def fence_complete(self, proof: object) -> AbstractContextManager[object]:
        """Enter the delegated complete-graph fence for this exact proof only."""

        if proof is not self.authority_proof:
            _unavailable("authority_proof_mismatch")
        return self._fence(self.authority_proof)

    @contextmanager
    def _fence(
        self,
        proof: AccountAuthorityCompleteGraphFinalRevalidationProofV3,
    ) -> Iterator[object]:
        """Keep the Account RC/RW fence open while bounding its activation lease."""

        with self._delegate.fence_complete(proof) as result:
            if type(result) is not AccountAuthorityV3CompleteGraphRevalidationResult:
                _unavailable("authority_fence_result_invalid")
            result.__post_init__()
            if (
                result.database_alias != self.database_alias
                or result.tenant_id != self._tenant_id
                or result.owner_id != self._owner_id
            ):
                _unavailable("authority_fence_identity_mismatch")
            bounded_valid_until = min(result.valid_until, self._valid_until)
            if result.checked_at >= bounded_valid_until:
                _unavailable("authority_expired")
            yield replace(result, valid_until=bounded_valid_until)


def capture_production_account_authority(
    *,
    using: str,
    as_of: datetime,
    preflight_context: SystemAuditReaderContext,
) -> ProductionAccountAuthorityCapture:
    """Capture a complete V3 proof against the production audit selector.

    The caller must pass the provider-issued preflight context from the same
    production request flow. This function rereads its exact actor/scope
    bundle, compares the V3 scope with the legacy current observation, runs an
    RR/RO complete shadow scan, and captures an opaque proof for a later RC/RW
    authority fence. It performs no publication activation.
    """

    alias = _require_database_alias(using)
    _require_aware_datetime(as_of, "authority cutoff")
    if type(preflight_context) is not SystemAuditReaderContext:
        _unavailable("preflight_context_invalid")
    preflight_context.__post_init__()
    if not preflight_context.can_read_at(as_of):
        _unavailable("preflight_context_unavailable")

    binding = load_system_audit_runtime_config(environment=_PRODUCTION_ENVIRONMENT)
    selector = _require_production_selector(binding)
    expected_bundle_identity = (
        selector.authority_source_id(),
        selector.authority_source_version(),
    )
    if (
        preflight_context.authority_source_id,
        preflight_context.authority_source_version,
    ) != expected_bundle_identity:
        _unavailable("preflight_selector_mismatch")

    readers = build_system_audit_authority_readers(using=alias, selector=selector)
    if type(readers) is not SystemAuditAuthorityReaders:
        _unavailable("authority_readers_invalid")
    readers.__post_init__()
    if readers.database_alias != alias:
        _unavailable("database_alias_mismatch")

    provider = ExactScopedSystemAuditAuthorityProvider(
        actor_reader=readers.actor,
        scope_reader=readers.scope,
        selector=selector,
    )
    current_context = get_system_audit_reader_context(provider, as_of=as_of)
    if type(current_context) is not SystemAuditReaderContext:
        _unavailable("current_authority_context_invalid")
    if current_context != preflight_context:
        _unavailable("preflight_authority_drift")

    scope_adapter, v3_reader = _require_v3_scope_reader(readers, selector, alias)
    del scope_adapter
    scope_command = GetCurrentOwnerTenantAuthorityV3Command(
        authority_id=selector.scope_source_id,
        authority_version=selector.scope_source_version,
        expected_content_hash=selector.scope_content_hash,
    )
    legacy_current = v3_reader.execute(scope_command)
    _require_legacy_current(
        legacy_current,
        selector=selector,
        context=preflight_context,
        as_of=as_of,
    )

    physical_row_provider = build_account_physical_row_v2_provider(using=alias)
    _require_physical_provider(physical_row_provider, alias)
    scanner = AccountAuthorityShadowScannerV3(
        actor_source_id=selector.actor_source_id,
        actor_source_version=selector.actor_source_version,
        actor_content_hash=selector.actor_content_hash,
        physical_row_provider=physical_row_provider,
        using=alias,
    )
    scan = scanner.scan(scope_command, legacy_current)
    _require_complete_scan(
        scan,
        selector=selector,
        alias=alias,
        preflight_context=preflight_context,
    )

    complete_graph_reader = AccountAuthorityCurrentGraphReaderV3(
        actor_source_id=selector.actor_source_id,
        actor_source_version=selector.actor_source_version,
        actor_content_hash=selector.actor_content_hash,
        physical_row_provider=physical_row_provider,
        using=alias,
        transaction_mode=_GENERATION_FENCED_MODE,
    )
    if (
        complete_graph_reader.database_alias != alias
        or complete_graph_reader.transaction_mode != _GENERATION_FENCED_MODE
    ):
        _unavailable("complete_graph_reader_mismatch")
    repository = DjangoAccountAuthorityV3RootRevocationRevalidationRepository(using=alias)
    if repository.database_alias != alias:
        _unavailable("database_alias_mismatch")
    finalizer = AccountAuthorityFinalRevalidatorV3(
        repository,
        using=alias,
        complete_graph_reader=complete_graph_reader,
    )
    proof = finalizer.capture_complete(scope_command, scan)
    if type(proof) is not AccountAuthorityCompleteGraphFinalRevalidationProofV3:
        _unavailable("complete_authority_proof_invalid")

    authority_fence = ProductionAccountAuthorityFence(
        database_alias=alias,
        authority_proof=proof,
        _delegate=finalizer,
        _tenant_id=preflight_context.tenant_id,
        _owner_id=preflight_context.owner_id,
        _valid_until=preflight_context.authority_valid_until,
    )
    return ProductionAccountAuthorityCapture(
        database_alias=alias,
        authority_fence=authority_fence,
        authority_proof=proof,
    )


def _require_production_selector(
    binding: SystemAuditRuntimeConfigBinding,
) -> SystemAuditAuthorityBundleSelector:
    """Require one active production binding and an exact V3 selector."""

    if type(binding) is not SystemAuditRuntimeConfigBinding:
        _unavailable("runtime_binding_invalid")
    try:
        binding.__post_init__()
    except (AttributeError, TypeError, ValueError):
        _unavailable("runtime_binding_invalid")
    if binding.environment != _PRODUCTION_ENVIRONMENT:
        _unavailable("runtime_binding_unavailable")
    selector = binding.authority_selector
    if type(selector) is not SystemAuditAuthorityBundleSelector:
        _unavailable("authority_selector_missing")
    if binding.mode == "off":
        _unavailable("runtime_binding_unavailable")
    selector.__post_init__()
    if selector.scope_schema != SYSTEM_AUDIT_SCOPE_SCHEMA_V3:
        _unavailable("authority_scope_schema_unsupported")
    return selector


def _require_v3_scope_reader(
    readers: SystemAuditAuthorityReaders,
    selector: SystemAuditAuthorityBundleSelector,
    alias: str,
) -> tuple[
    AccountSystemAuditScopeAuthorityV3Adapter,
    AccountSystemAuditOwnerTenantAuthorityV3Reader,
]:
    """Require the exact Account V3 reader wired for this actor and alias."""

    if type(readers.scope) is not AccountSystemAuditScopeAuthorityV3Adapter:
        _unavailable("v3_scope_reader_missing")
    adapter = readers.scope
    if adapter.database_alias != alias:
        _unavailable("database_alias_mismatch")
    reader = adapter.reader
    if type(reader) is not AccountSystemAuditOwnerTenantAuthorityV3Reader:
        _unavailable("v3_scope_reader_missing")
    reader.__post_init__()
    if (
        reader.actor_source_id,
        reader.actor_source_version,
        reader.actor_content_hash,
        reader.database_alias,
    ) != (
        selector.actor_source_id,
        selector.actor_source_version,
        selector.actor_content_hash,
        alias,
    ):
        _unavailable("v3_scope_reader_identity_mismatch")
    _require_physical_provider(reader.physical_row_provider, alias)
    return adapter, reader


def _require_legacy_current(
    current: CurrentOwnerTenantAuthorityV3 | None,
    *,
    selector: SystemAuditAuthorityBundleSelector,
    context: SystemAuditReaderContext,
    as_of: datetime,
) -> None:
    """Bind the legacy current observation to the preflight V3 scope."""

    if type(current) is not CurrentOwnerTenantAuthorityV3:
        _unavailable("legacy_current_unavailable")
    current.__post_init__()
    authority = current.authority
    if (
        authority.authority_id,
        authority.authority_version,
        authority.content_hash,
        authority.status,
        authority.actor_id,
        authority.actor_user_id,
        authority.tenant_id,
        authority.owner_id,
    ) != (
        selector.scope_source_id,
        selector.scope_source_version,
        selector.scope_content_hash,
        "active",
        context.actor_id,
        context.user_id,
        context.tenant_id,
        context.owner_id,
    ):
        _unavailable("legacy_current_identity_mismatch")
    if (
        authority.recorded_at > context.authority_recorded_at
        or current.valid_until < context.authority_valid_until
        or current.valid_until <= as_of
    ):
        _unavailable("legacy_current_expiry_mismatch")


def _require_complete_scan(
    scan: AccountAuthorityShadowScanResultV3,
    *,
    selector: SystemAuditAuthorityBundleSelector,
    alias: str,
    preflight_context: SystemAuditReaderContext,
) -> None:
    """Reject partial, mismatched, expired, or physically unbound shadow scans."""

    if type(scan) is not AccountAuthorityShadowScanResultV3:
        _unavailable("shadow_scan_invalid")
    comparison = scan.comparison
    if (
        scan.database_alias != alias
        or type(scan.proof_generation) is not int
        or scan.proof_generation < 0
        or comparison.matches is not True
        or comparison.differing_fields != ()
        or comparison.legacy is None
        or comparison.shadow is None
        or comparison.legacy != comparison.shadow
    ):
        _unavailable("shadow_scan_mismatch")
    graph_selector = scan.selector
    identity = scan.physical_identity
    checked_at = scan.checked_at
    if (
        type(graph_selector) is not AccountAuthorityCurrentGraphSelectorV3
        or graph_selector.database_alias != alias
        or graph_selector.authority_content_hash != selector.scope_content_hash
        or graph_selector.actor_source_content_hash != selector.actor_content_hash
        or type(identity) is not PhysicalAccountRowProviderIdentity
        or identity.using != alias
        or type(checked_at) is not datetime
        or checked_at.tzinfo is None
        or checked_at.utcoffset() is None
    ):
        _unavailable("shadow_scan_identity_mismatch")
    fingerprint = comparison.shadow
    if (
        type(fingerprint) is not AccountAuthorityShadowFingerprintV3
        or fingerprint.authority_content_hash != selector.scope_content_hash
        or fingerprint.complete_graph_hash is None
        or checked_at >= fingerprint.valid_until
        or fingerprint.valid_until > preflight_context.authority_valid_until
        or checked_at >= preflight_context.authority_valid_until
    ):
        _unavailable("authority_expiry_drift")


def _require_physical_provider(
    provider: ExactPhysicalSimulatedAccountRowV2Provider,
    alias: str,
) -> None:
    """Verify a physical provider is bound to the exact Django alias."""

    provider_object = cast(object, provider)
    if (
        getattr(provider_object, "database_alias", None) != alias
        or getattr(provider_object, "unit_of_work_key", None) != f"django:{alias}"
    ):
        _unavailable("physical_provider_alias_mismatch")
    for method_name in (
        "get_exact_final",
        "get_exact_current",
        "lock_current_sources",
        "lock_current_sources_for_read",
        "bind_physical_identity",
        "bind_read_clock",
    ):
        if not callable(getattr(provider_object, method_name, None)):
            _unavailable("physical_provider_unavailable")


def _require_database_alias(value: object) -> str:
    """Validate one exact, bounded database alias."""

    if (
        type(value) is not str
        or not value
        or value.strip() != value
        or len(value) > 64
        or any(character.isspace() for character in value)
    ):
        _unavailable("database_alias_invalid")
    return value


def _require_scope_token(value: object, field_name: str) -> str:
    """Validate one exact Account scope token without whitespace."""

    if (
        type(value) is not str
        or not value
        or value.strip() != value
        or len(value) > 192
        or any(character.isspace() for character in value)
    ):
        _unavailable(f"{field_name}_invalid")
    return value


def _require_aware_datetime(value: object, field_name: str) -> datetime:
    """Require one exact timezone-aware datetime."""

    if type(value) is not datetime or value.tzinfo is None or value.utcoffset() is None:
        _unavailable(f"{field_name.replace(' ', '_')}_invalid")
    return value


def _unavailable(reason_code: str) -> NoReturn:
    """Raise one stable fail-closed composition error."""

    raise SystemAuditCompositionUnavailable(
        "production Account authority capture is unavailable",
        reason_code=reason_code,
    )


__all__ = [
    "ProductionAccountAuthorityCapture",
    "ProductionAccountAuthorityFence",
    "capture_production_account_authority",
]
