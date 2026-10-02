from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import replace
from datetime import datetime, timedelta

import pytest

from apps.account.application.owner_tenant_authority_v3 import (
    GetCurrentOwnerTenantAuthorityV3Command,
)
from apps.account.application.owner_tenant_authority_v3_contracts import (
    CurrentOwnerTenantAuthorityV3,
)
from apps.account.application.physical_account_row_observation_v2 import (
    PhysicalAccountRowProviderIdentity,
)
from apps.account.infrastructure.account_authority_final_revalidator_v3 import (
    AccountAuthorityCompleteGraphFinalRevalidationProofV3,
    AccountAuthorityFinalRevalidatorV3,
)
from apps.account.infrastructure.account_authority_shadow_scanner import (
    AccountAuthorityCurrentGraphSelectorV3,
    AccountAuthorityShadowComparisonV3,
    AccountAuthorityShadowFingerprintV3,
    AccountAuthorityShadowScannerV3,
    AccountAuthorityShadowScanResultV3,
)
from apps.account.system_audit_authority_v3_composition import (
    AccountSystemAuditOwnerTenantAuthorityV3Reader,
)
from apps.audit.application.system_audit_authority_provider import (
    SystemAuditActorAuthorityFacts,
    SystemAuditAuthorityBundleSelector,
)
from apps.audit.application.system_audit_authority_schema import (
    SYSTEM_AUDIT_SCOPE_SCHEMA_V1,
    SYSTEM_AUDIT_SCOPE_SCHEMA_V3,
)
from apps.audit.application.system_audit_query import SystemAuditReaderContext
from core.integration import production_account_authority_capture as capture_module
from core.integration.production_account_authority_capture import (
    capture_production_account_authority,
)
from core.integration.system_audit_authority import (
    AccountSystemAuditScopeAuthorityV3Adapter,
    SystemAuditAuthorityReaders,
)
from core.integration.system_audit_runtime_config import SystemAuditRuntimeConfigBinding
from tests.unit.account.test_owner_tenant_authority_v3 import _authority
from tests.unit.account.test_owner_tenant_authority_v3_application import (
    _authority_source,
)


class _PhysicalProvider:
    def __init__(self, alias: str) -> None:
        self.database_alias = alias
        self.unit_of_work_key = f"django:{alias}"

    def get_exact_final(self, **kwargs: object) -> None:
        del kwargs

    def get_exact_current(self, **kwargs: object) -> None:
        del kwargs

    def lock_current_sources(self) -> None:
        return None

    def lock_current_sources_for_read(self) -> None:
        return None

    @contextmanager
    def bind_physical_identity(
        self, identity: PhysicalAccountRowProviderIdentity
    ) -> Iterator[None]:
        del identity
        yield

    @contextmanager
    def bind_read_clock(self, clock: object) -> Iterator[None]:
        del clock
        yield


class _ActorReader:
    database_alias = "audit"

    def get_current(
        self,
        *,
        source_id: str,
        source_version: str,
        expected_content_hash: str,
        as_of: datetime,
    ) -> SystemAuditActorAuthorityFacts | None:
        del source_id, source_version, expected_content_hash, as_of
        return None


@pytest.fixture
def production_capture_setup(monkeypatch: pytest.MonkeyPatch) -> dict[str, object]:
    alias = "audit"
    authority = _authority()
    authentication = _authority_source(authority.assignment, valid_until=authority.valid_until)
    current = CurrentOwnerTenantAuthorityV3(
        authority=authority,
        authentication=authentication,
        observed_at=authority.recorded_at + timedelta(seconds=1),
        valid_until=min(
            authority.valid_until,
            authority.assignment.valid_until,
            authority.policy.valid_until,
            authentication.valid_until,
        ),
    )
    as_of = current.observed_at + timedelta(seconds=1)
    selector = SystemAuditAuthorityBundleSelector(
        actor_source_id="actor-source-v3",
        actor_source_version="actor-v3.1",
        actor_content_hash="a" * 64,
        scope_source_id=authority.authority_id,
        scope_source_version=authority.authority_version,
        scope_content_hash=authority.content_hash,
        scope_schema=SYSTEM_AUDIT_SCOPE_SCHEMA_V3,
    )
    context = SystemAuditReaderContext._from_authority(
        authority_source_id=selector.authority_source_id(),
        authority_source_version=selector.authority_source_version(),
        actor_id=authority.actor_id,
        user_id=authority.actor_user_id,
        tenant_id=authority.tenant_id,
        owner_id=authority.owner_id,
        authority_content_hash="f" * 64,
        is_authenticated=True,
        is_staff=True,
        role="admin",
        authority_state="active",
        authority_recorded_at=authority.recorded_at,
        authority_valid_until=current.valid_until,
    )
    binding = SystemAuditRuntimeConfigBinding(
        mode="required",
        outbox_enabled=True,
        authority_selector=selector,
        issuer_id="audit-config:issuer",
        snapshot_id="snapshot-1",
        snapshot_hash="b" * 64,
        profile_id="profile-1",
        profile_key="profile-key-1",
        profile_version=1,
        environment="production",
    )
    physical_provider = _PhysicalProvider(alias)
    v3_reader = AccountSystemAuditOwnerTenantAuthorityV3Reader(
        actor_source_id=selector.actor_source_id,
        actor_source_version=selector.actor_source_version,
        actor_content_hash=selector.actor_content_hash,
        physical_row_provider=physical_provider,  # type: ignore[arg-type]
        database_alias=alias,
    )
    readers = SystemAuditAuthorityReaders(
        actor=_ActorReader(),  # type: ignore[arg-type]
        scope=AccountSystemAuditScopeAuthorityV3Adapter(v3_reader, alias),
        database_alias=alias,
    )
    provider_identity = PhysicalAccountRowProviderIdentity(
        using=alias,
        wrapper_token=object(),
        dbapi_token=object(),
        backend_pid=41,
        transaction_xid="1001",
        thread_id=1,
        task_token=None,
    )
    fingerprint = AccountAuthorityShadowFingerprintV3(
        authority_identity_hash=authority.identity_hash,
        authority_content_hash=authority.content_hash,
        assignment_identity_hash=authority.assignment.identity_hash,
        assignment_content_hash=authority.assignment.content_hash,
        policy_identity_hash=authority.policy.identity_hash,
        policy_content_hash=authority.policy.content_hash,
        actor_source_identity_hash="c" * 64,
        physical_source_identity_hash="d" * 64,
        valid_until=current.valid_until,
        complete_graph_hash="e" * 64,
    )
    scan = AccountAuthorityShadowScanResultV3(
        database_alias=alias,
        proof_generation=4,
        comparison=AccountAuthorityShadowComparisonV3(
            legacy=fingerprint,
            shadow=fingerprint,
            matches=True,
            differing_fields=(),
        ),
        selector=AccountAuthorityCurrentGraphSelectorV3(
            database_alias=alias,
            authority_selector_hash="1" * 64,
            authority_content_hash=authority.content_hash,
            actor_source_selector_hash="2" * 64,
            actor_source_content_hash=selector.actor_content_hash,
        ),
        checked_at=current.observed_at + timedelta(seconds=1),
        physical_identity=provider_identity,
    )
    proof = AccountAuthorityCompleteGraphFinalRevalidationProofV3()
    current_commands: list[GetCurrentOwnerTenantAuthorityV3Command] = []

    def execute_current(
        self: AccountSystemAuditOwnerTenantAuthorityV3Reader,
        command: GetCurrentOwnerTenantAuthorityV3Command,
    ) -> CurrentOwnerTenantAuthorityV3:
        del self
        current_commands.append(command)
        return current

    monkeypatch.setattr(capture_module, "load_system_audit_runtime_config", lambda **_: binding)
    monkeypatch.setattr(
        capture_module,
        "build_system_audit_authority_readers",
        lambda **_: readers,
    )
    monkeypatch.setattr(
        capture_module,
        "get_system_audit_reader_context",
        lambda provider, *, as_of: context,
    )
    monkeypatch.setattr(
        AccountSystemAuditOwnerTenantAuthorityV3Reader,
        "execute",
        execute_current,
    )
    monkeypatch.setattr(
        capture_module,
        "build_account_physical_row_v2_provider",
        lambda **_: physical_provider,
    )
    monkeypatch.setattr(AccountAuthorityShadowScannerV3, "scan", lambda self, command, row: scan)
    monkeypatch.setattr(AccountAuthorityFinalRevalidatorV3, "capture_complete", lambda *args: proof)
    return {
        "alias": alias,
        "as_of": as_of,
        "selector": selector,
        "context": context,
        "current": current,
        "scan": scan,
        "proof": proof,
        "binding": binding,
        "physical_provider": physical_provider,
        "readers": readers,
        "current_commands": current_commands,
    }


def test_capture_builds_bound_complete_proof_and_uses_scope_selector(
    production_capture_setup: dict[str, object],
) -> None:
    setup = production_capture_setup
    capture = capture_production_account_authority(
        using=setup["alias"],  # type: ignore[arg-type]
        as_of=setup["as_of"],  # type: ignore[arg-type]
        preflight_context=setup["context"],  # type: ignore[arg-type]
    )

    assert capture.database_alias == setup["alias"]
    assert capture.authority_fence.database_alias == setup["alias"]
    assert capture.authority_proof is setup["proof"]
    assert setup["current_commands"] == [
        GetCurrentOwnerTenantAuthorityV3Command(
            authority_id=setup["selector"].scope_source_id,  # type: ignore[union-attr]
            authority_version=setup["selector"].scope_source_version,  # type: ignore[union-attr]
            expected_content_hash=setup["selector"].scope_content_hash,  # type: ignore[union-attr]
        )
    ]


@pytest.mark.parametrize(
    ("failure", "reason"),
    [
        ("missing_selector", "authority_selector_missing"),
        ("legacy_schema", "authority_scope_schema_unsupported"),
    ],
)
def test_capture_rejects_missing_or_legacy_selector_before_scan(
    production_capture_setup: dict[str, object],
    monkeypatch: pytest.MonkeyPatch,
    failure: str,
    reason: str,
) -> None:
    binding = production_capture_setup["binding"]
    assert isinstance(binding, SystemAuditRuntimeConfigBinding)
    selector = binding.authority_selector
    assert selector is not None
    changed = (
        replace(binding, authority_selector=None, mode="off")
        if failure == "missing_selector"
        else replace(selector, scope_schema=SYSTEM_AUDIT_SCOPE_SCHEMA_V1)
    )
    if failure == "missing_selector":
        monkeypatch.setattr(capture_module, "load_system_audit_runtime_config", lambda **_: changed)
    else:
        monkeypatch.setattr(
            capture_module,
            "load_system_audit_runtime_config",
            lambda **_: replace(binding, authority_selector=changed),
        )
    with pytest.raises(capture_module.SystemAuditCompositionUnavailable) as error:
        capture_production_account_authority(
            using=production_capture_setup["alias"],  # type: ignore[arg-type]
            as_of=production_capture_setup["as_of"],  # type: ignore[arg-type]
            preflight_context=production_capture_setup["context"],  # type: ignore[arg-type]
        )
    assert error.value.reason_code == reason


def test_capture_rejects_context_scope_drift_and_database_alias_mismatch(
    production_capture_setup: dict[str, object],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    context = production_capture_setup["context"]
    assert isinstance(context, SystemAuditReaderContext)
    changed_context = SystemAuditReaderContext._from_authority(
        authority_source_id=context.authority_source_id,
        authority_source_version=context.authority_source_version,
        actor_id=context.actor_id,
        user_id=context.user_id,
        tenant_id="foreign-tenant",
        owner_id=context.owner_id,
        authority_content_hash=context.authority_content_hash,
        is_authenticated=True,
        is_staff=True,
        role=context.role,
        authority_state="active",
        authority_recorded_at=context.authority_recorded_at,
        authority_valid_until=context.authority_valid_until,
    )
    with pytest.raises(capture_module.SystemAuditCompositionUnavailable) as error:
        capture_production_account_authority(
            using=production_capture_setup["alias"],  # type: ignore[arg-type]
            as_of=production_capture_setup["as_of"],  # type: ignore[arg-type]
            preflight_context=changed_context,
        )
    assert error.value.reason_code == "preflight_authority_drift"

    with pytest.raises(capture_module.SystemAuditCompositionUnavailable) as alias_error:
        capture_production_account_authority(
            using="other",
            as_of=production_capture_setup["as_of"],  # type: ignore[arg-type]
            preflight_context=context,
        )
    assert alias_error.value.reason_code == "database_alias_mismatch"


def test_capture_rejects_legacy_identity_expiry_and_complete_scan_drift(
    production_capture_setup: dict[str, object],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    setup = production_capture_setup
    context = setup["context"]
    assert isinstance(context, SystemAuditReaderContext)
    current = setup["current"]
    assert isinstance(current, CurrentOwnerTenantAuthorityV3)
    foreign_authority = _authority(authority_id="foreign-authority")
    foreign_authentication = _authority_source(
        foreign_authority.assignment,
        valid_until=foreign_authority.valid_until,
    )
    mismatched = CurrentOwnerTenantAuthorityV3(
        authority=foreign_authority,
        authentication=foreign_authentication,
        observed_at=foreign_authority.recorded_at + timedelta(seconds=1),
        valid_until=min(
            foreign_authority.valid_until,
            foreign_authority.assignment.valid_until,
            foreign_authority.policy.valid_until,
            foreign_authentication.valid_until,
        ),
    )
    monkeypatch.setattr(
        AccountSystemAuditOwnerTenantAuthorityV3Reader,
        "execute",
        lambda self, command: mismatched,
    )
    with pytest.raises(capture_module.SystemAuditCompositionUnavailable) as legacy_error:
        capture_production_account_authority(
            using=setup["alias"],  # type: ignore[arg-type]
            as_of=setup["as_of"],  # type: ignore[arg-type]
            preflight_context=context,
        )
    assert legacy_error.value.reason_code == "legacy_current_identity_mismatch"

    monkeypatch.setattr(
        AccountSystemAuditOwnerTenantAuthorityV3Reader,
        "execute",
        lambda self, command: current,
    )
    scan = setup["scan"]
    assert isinstance(scan, AccountAuthorityShadowScanResultV3)
    expired_fingerprint = replace(
        scan.comparison.shadow,
        valid_until=context.authority_valid_until + timedelta(seconds=1),
    )
    drifted_scan = replace(
        scan,
        comparison=replace(scan.comparison, legacy=expired_fingerprint, shadow=expired_fingerprint),
    )
    monkeypatch.setattr(
        AccountAuthorityShadowScannerV3, "scan", lambda self, command, row: drifted_scan
    )
    with pytest.raises(capture_module.SystemAuditCompositionUnavailable) as expiry_error:
        capture_production_account_authority(
            using=setup["alias"],  # type: ignore[arg-type]
            as_of=setup["as_of"],  # type: ignore[arg-type]
            preflight_context=context,
        )
    assert expiry_error.value.reason_code == "authority_expiry_drift"


def test_capture_proof_failure_is_closed_without_returning_fence(
    production_capture_setup: dict[str, object],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail_capture(
        *args: object, **kwargs: object
    ) -> AccountAuthorityCompleteGraphFinalRevalidationProofV3:
        del args, kwargs
        raise RuntimeError("injected proof capture failure")

    monkeypatch.setattr(AccountAuthorityFinalRevalidatorV3, "capture_complete", fail_capture)
    with pytest.raises(RuntimeError, match="injected proof capture failure"):
        capture_production_account_authority(
            using=production_capture_setup["alias"],  # type: ignore[arg-type]
            as_of=production_capture_setup["as_of"],  # type: ignore[arg-type]
            preflight_context=production_capture_setup["context"],  # type: ignore[arg-type]
        )
