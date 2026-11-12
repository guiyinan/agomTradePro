"""Unit contracts for the owner-granted corporate-action posting gate."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import timedelta
from typing import cast

import pytest

from apps.account.application.simulated_corporate_action_write_issuance import (
    LockedSimulatedCorporateActionWriteScope,
)
from apps.account.domain.simulated_corporate_action_write_capabilities import (
    SimulatedCorporateActionWriteCapability as Capability,
)
from apps.account.domain.simulated_corporate_action_write_grant import (
    SIMULATED_CORPORATE_ACTION_WRITE_GRANT_SCHEMA,
    SIMULATED_CORPORATE_ACTION_WRITE_GRANT_V2_SCHEMA,
    SimulatedCorporateActionWriteGrant,
    SimulatedCorporateActionWriteGrantSelector,
)
from apps.audit.application.system_audit_authority_renewal_guard import (
    SystemAuditAuthorityLease,
)
from apps.audit.domain.system_audit_event import AuditScopeRef
from apps.simulated_trading import audited_corporate_action_posting_composition as audited_module
from apps.simulated_trading import corporate_action_owner_grant_gate as gate_module
from apps.simulated_trading.application.corporate_action_posting import (
    CorporateActionPostingBlockedError,
    CorporateActionPostingReceipt,
)
from apps.simulated_trading.corporate_action_owner_grant_gate import (
    DjangoCorporateActionOwnerGrantGate,
    OwnerGrantedCorporateActionAuthority,
)
from apps.simulated_trading.corporate_action_write_scope_composition import (
    CorporateActionSourceTimestampReplayProof,
    CorporateActionSourceTimestampReplayVerifier,
    DjangoSimulatedCorporateActionWriteScopeLocker,
)
from apps.simulated_trading.domain.corporate_action_posting import CorporateActionStageRequest
from tests.unit.account.test_simulated_corporate_action_write_grant import (
    _AT,
    _grant,
    _grant_v2,
    _selector,
)
from tests.unit.simulated_trading.test_corporate_action_posting import _request


class _ReplayVerifier(CorporateActionSourceTimestampReplayVerifier):
    """Represent the closed audited composition verifier used by the owner gate."""

    def verify_exact_replay(
        self,
        *,
        request: CorporateActionStageRequest,
        grant: SimulatedCorporateActionWriteGrant,
    ) -> CorporateActionSourceTimestampReplayProof | None:
        del request, grant
        return None


class _Cursor:
    """Serve the transaction isolation check without opening PostgreSQL."""

    def __init__(self, connection: _Connection) -> None:
        self.connection = connection

    def __enter__(self) -> _Cursor:
        return self

    def __exit__(self, *_: object) -> None:
        return None

    def execute(self, sql: str) -> None:
        self.connection.last_sql = sql

    def fetchone(self) -> tuple[str, ...]:
        return ("read committed",)


class _Connection:
    """Represent the gate's fresh outer PostgreSQL transaction state."""

    vendor = "postgresql"
    in_atomic_block = False

    def __init__(self) -> None:
        self.autocommit = True
        self.last_sql = ""

    def get_autocommit(self) -> bool:
        return self.autocommit

    def cursor(self) -> _Cursor:
        return _Cursor(self)


@pytest.fixture
def owner_gate_world(monkeypatch: pytest.MonkeyPatch, request: pytest.FixtureRequest):
    """Install deterministic same-alias transaction and owner-grant contexts."""

    configuration = cast(dict[str, object], getattr(request, "param", {}))
    grant_value = configuration.get("grant", _grant())
    assert type(grant_value) is SimulatedCorporateActionWriteGrant
    grant = grant_value
    expected_grant_schema = cast(
        str,
        configuration.get("expected_grant_schema", SIMULATED_CORPORATE_ACTION_WRITE_GRANT_SCHEMA),
    )
    scope_schema = cast(str, configuration.get("scope_schema", expected_grant_schema))
    scope_capabilities = cast(
        tuple[Capability, ...] | None,
        configuration.get("scope_capabilities", grant.capabilities),
    )
    scope_terms_version = cast(
        str | None, configuration.get("scope_terms_version", grant.terms_version)
    )
    scope_terms_sha256 = cast(
        str | None, configuration.get("scope_terms_sha256", grant.terms_sha256)
    )
    selector: SimulatedCorporateActionWriteGrantSelector = _selector(grant)
    connection = _Connection()
    order: list[str] = []
    lease = SystemAuditAuthorityLease(
        mode="required", outbox_enabled=True, valid_until=_AT + timedelta(hours=3)
    )

    @contextmanager
    def atomic(*, using: str) -> Iterator[None]:
        assert using == "default"
        assert not connection.in_atomic_block and connection.autocommit
        connection.in_atomic_block = True
        connection.autocommit = False
        order.append("atomic-enter")
        try:
            yield
        finally:
            order.append("atomic-exit")
            connection.in_atomic_block = False
            connection.autocommit = True

    @contextmanager
    def eligibility(*, user_id: int, using: str) -> Iterator[None]:
        assert user_id == grant.binding.owner_user_id and using == "default"
        order.append("role-enter")
        try:
            yield
        finally:
            order.append("role-exit")

    @contextmanager
    def lock_scope(
        self: DjangoSimulatedCorporateActionWriteScopeLocker,
        *,
        physical_account_id: int,
        owner_user_id: int,
        expected_binding: object,
        request: CorporateActionStageRequest,
        expected_grant_schema: str,
    ) -> Iterator[LockedSimulatedCorporateActionWriteScope]:
        assert connection.in_atomic_block and not connection.autocommit
        assert physical_account_id == 11
        assert owner_user_id == grant.binding.owner_user_id
        assert expected_binding == grant.binding
        assert request.account_id == physical_account_id
        assert expected_grant_schema == gate_schema
        order.append("scope-enter")
        try:
            yield LockedSimulatedCorporateActionWriteScope(
                physical_account_id=physical_account_id,
                binding=grant.binding,
                valid_until=_AT + timedelta(hours=2),
                grant_schema=scope_schema,
                capabilities=scope_capabilities,
                terms_version=scope_terms_version,
                terms_sha256=scope_terms_sha256,
            )
        finally:
            order.append("scope-exit")

    def assert_source_timestamp(
        self: DjangoSimulatedCorporateActionWriteScopeLocker,
        *,
        request: CorporateActionStageRequest,
        grant: SimulatedCorporateActionWriteGrant,
        verifier: CorporateActionSourceTimestampReplayVerifier | None,
    ) -> None:
        assert request.account_id == 11
        assert grant == expected_grant
        assert verifier is None or isinstance(
            verifier, CorporateActionSourceTimestampReplayVerifier
        )
        order.append("source-timestamp-check")

    expected_grant = grant

    gate_schema = expected_grant_schema

    @contextmanager
    def current_grant(
        *,
        selector: SimulatedCorporateActionWriteGrantSelector,
        using: str,
        required_capability: Capability,
    ) -> Iterator[SimulatedCorporateActionWriteGrant]:
        assert connection.in_atomic_block and not connection.autocommit
        assert selector == grant.selector and using == "default"
        assert required_capability is Capability.CASH_STAGE_WRITE
        order.append("grant-enter")
        try:
            yield grant
        finally:
            order.append("grant-exit")

    def audit_lease(*, environment: str, using: str) -> SystemAuditAuthorityLease:
        assert environment == "test" and using == "default"
        order.append("audit-readiness")
        return lease

    monkeypatch.setattr(gate_module, "connections", {"default": connection})
    monkeypatch.setattr(gate_module.transaction, "atomic", atomic)
    monkeypatch.setattr(gate_module, "locked_simulated_action_trading_eligibility", eligibility)
    monkeypatch.setattr(
        DjangoSimulatedCorporateActionWriteScopeLocker, "lock_owned_scope", lock_scope
    )
    monkeypatch.setattr(
        DjangoSimulatedCorporateActionWriteScopeLocker,
        "assert_source_timestamp_current_or_proven",
        assert_source_timestamp,
    )
    monkeypatch.setattr(
        gate_module,
        "locked_current_simulated_corporate_action_write_grant",
        current_grant,
    )
    monkeypatch.setattr(gate_module, "get_system_audit_authority_lease", audit_lease)
    monkeypatch.setattr(gate_module.timezone, "now", lambda: _AT + timedelta(minutes=1))
    scope_locker = DjangoSimulatedCorporateActionWriteScopeLocker(
        database_alias="default", runtime_environment="test"
    )
    gate = DjangoCorporateActionOwnerGrantGate(
        selector=selector,
        scope_locker=scope_locker,
        using="default",
        environment="test",
        expected_grant_schema=expected_grant_schema,
    )
    return gate, grant, connection, order, lease


def test_owner_scope_comes_from_the_account_grant_not_a_staff_reader(
    owner_gate_world,
) -> None:
    gate, grant, connection, order, lease = owner_gate_world
    request = _request(account_id=11, owner_user_id=grant.binding.owner_user_id)

    with gate.atomic_authority(request) as authority:
        assert type(authority) is OwnerGrantedCorporateActionAuthority
        assert authority.user_id == grant.binding.owner_user_id
        assert authority.grant == grant
        assert authority.scope == AuditScopeRef(
            tenant_id=grant.binding.tenant_id,
            owner_id=grant.binding.owner_id,
        )
        assert authority.authority_valid_until == grant.valid_until
        assert gate.assert_live(as_of=_AT + timedelta(minutes=1)) is authority
        assert not connection.autocommit and connection.in_atomic_block

    assert connection.autocommit and not connection.in_atomic_block
    assert order.index("role-enter") < order.index("scope-enter") < order.index("grant-enter")
    assert order.index("grant-exit") < order.index("scope-exit") < order.index("role-exit")
    assert lease.valid_until == _AT + timedelta(hours=3)
    with pytest.raises(CorporateActionPostingBlockedError):
        gate.assert_live(as_of=_AT + timedelta(minutes=1))


def test_unavailable_account_grant_is_normalized_as_a_posting_block(owner_gate_world, monkeypatch):
    """Revocation must retain the posting port's stable error contract."""
    from apps.account.application.simulated_corporate_action_write_grant import (
        SimulatedCorporateActionWriteGrantUnavailable,
    )

    gate, grant, _, _, _ = owner_gate_world

    @contextmanager
    def unavailable(**kwargs):
        if kwargs:
            raise SimulatedCorporateActionWriteGrantUnavailable("revoked exact grant")
        yield grant

    monkeypatch.setattr(
        gate_module, "locked_current_simulated_corporate_action_write_grant", unavailable
    )
    with pytest.raises(CorporateActionPostingBlockedError) as blocked:
        with gate.atomic_authority(
            _request(account_id=11, owner_user_id=grant.binding.owner_user_id)
        ):
            pytest.fail("revoked grant reached posting body")
    assert blocked.value.code == "CORPORATE_ACTION_WRITE_AUTHORITY_UNAVAILABLE"


def test_gate_rejects_nested_use_and_expiry_at_half_open_boundary(owner_gate_world) -> None:
    gate, grant, _, _, _ = owner_gate_world
    request = _request(account_id=11, owner_user_id=grant.binding.owner_user_id)

    with gate.atomic_authority(request) as authority:
        with pytest.raises(CorporateActionPostingBlockedError):
            with gate.atomic_authority(request):
                pytest.fail("nested authority must not be issued")
        with pytest.raises(CorporateActionPostingBlockedError):
            gate.assert_live(as_of=authority.authority_valid_until)


def test_gate_rejects_wrong_owner_before_opening_the_transaction(owner_gate_world) -> None:
    gate, grant, connection, order, _ = owner_gate_world
    request = _request(account_id=11, owner_user_id=grant.binding.owner_user_id + 1)

    with pytest.raises(CorporateActionPostingBlockedError) as captured:
        with gate.atomic_authority(request):
            pytest.fail("request owner must be server-bound to the grant")

    assert captured.value.code == "CORPORATE_ACTION_ACCOUNT_SCOPE_INVALID"
    assert connection.autocommit and not connection.in_atomic_block
    assert order == []


def test_audit_runtime_readiness_is_global_and_staff_context_is_never_used(
    monkeypatch: pytest.MonkeyPatch,
    owner_gate_world,
) -> None:
    gate, grant, _, order, _ = owner_gate_world
    monkeypatch.setattr(
        gate_module,
        "get_system_audit_authority_lease",
        lambda **kwargs: SystemAuditAuthorityLease(
            mode="off", outbox_enabled=False, valid_until=None, reason_code="audit_runtime_disabled"
        ),
    )
    request = _request(account_id=11, owner_user_id=grant.binding.owner_user_id)

    with pytest.raises(CorporateActionPostingBlockedError) as captured:
        with gate.atomic_authority(request):
            pytest.fail("disabled Audit/Outbox readiness must block the write")

    assert captured.value.code == "CORPORATE_ACTION_AUDIT_AUTHORITY_UNAVAILABLE"
    assert "role-enter" in order and "scope-enter" in order
    assert "grant-exit" in order and "role-exit" in order


def test_invalid_alias_or_scope_locker_is_rejected_at_construction(
    owner_gate_world,
) -> None:
    _, grant, _, _, _ = owner_gate_world
    with pytest.raises(CorporateActionPostingBlockedError):
        DjangoCorporateActionOwnerGrantGate(
            selector=grant.selector,
            scope_locker=DjangoSimulatedCorporateActionWriteScopeLocker(
                database_alias="other", runtime_environment="test"
            ),
            using="default",
            environment="test",
        )

    with pytest.raises(CorporateActionPostingBlockedError):
        DjangoCorporateActionOwnerGrantGate(
            selector=grant.selector,
            scope_locker=DjangoSimulatedCorporateActionWriteScopeLocker(
                database_alias="other", runtime_environment="test"
            ),
            using="other",
            environment="test",
        )


@pytest.mark.parametrize("schema", [None, "account.simulated_corporate_action_write_grant.v3"])
def test_gate_requires_an_exact_server_selected_grant_schema(schema: object) -> None:
    grant = _grant()
    with pytest.raises(CorporateActionPostingBlockedError):
        DjangoCorporateActionOwnerGrantGate(
            selector=grant.selector,
            scope_locker=DjangoSimulatedCorporateActionWriteScopeLocker(
                database_alias="default", runtime_environment="test"
            ),
            using="default",
            environment="test",
            expected_grant_schema=cast(str, schema),
        )


def test_gate_rejects_a_caller_boolean_as_source_replay_authority(owner_gate_world) -> None:
    gate, grant, connection, order, _ = owner_gate_world
    request = _request(account_id=11, owner_user_id=grant.binding.owner_user_id)

    with pytest.raises(CorporateActionPostingBlockedError):
        with gate.atomic_authority(
            request,
            replay_timestamp_verifier=cast(CorporateActionSourceTimestampReplayVerifier, True),
        ):
            pytest.fail("a boolean cannot prove an audited stage replay")

    assert connection.autocommit and not connection.in_atomic_block
    assert order == []


def test_gate_replay_verifier_is_used_only_inside_the_active_owner_scope(owner_gate_world) -> None:
    gate, grant, _, order, _ = owner_gate_world
    request = _request(account_id=11, owner_user_id=grant.binding.owner_user_id)

    with gate.atomic_authority(request, replay_timestamp_verifier=_ReplayVerifier()):
        gate.assert_source_timestamp_current_or_proven(request=request)

    assert "source-timestamp-check" in order


def test_gate_keeps_initial_cutoff_when_current_audit_lease_is_renewed(
    monkeypatch: pytest.MonkeyPatch,
    owner_gate_world,
) -> None:
    gate, grant, _, _, initial_lease = owner_gate_world
    request = _request(account_id=11, owner_user_id=grant.binding.owner_user_id)
    renewed_lease = SystemAuditAuthorityLease(
        mode="required", outbox_enabled=True, valid_until=_AT + timedelta(hours=4)
    )
    calls = 0

    def read_lease(*, environment: str, using: str) -> SystemAuditAuthorityLease:
        nonlocal calls
        assert environment == "test" and using == "default"
        calls += 1
        return initial_lease if calls == 1 else renewed_lease

    monkeypatch.setattr(gate_module, "get_system_audit_authority_lease", read_lease)
    with gate.atomic_authority(request) as authority:
        assert authority.authority_valid_until == grant.valid_until
        assert gate.assert_live(as_of=_AT + timedelta(minutes=1)) is authority

    assert calls >= 3


def test_commit_deadline_is_rechecked_after_inner_lock_contexts_exit(
    monkeypatch: pytest.MonkeyPatch,
    owner_gate_world,
) -> None:
    gate, grant, connection, order, _ = owner_gate_world
    request = _request(account_id=11, owner_user_id=grant.binding.owner_user_id)
    current_time = [_AT + timedelta(minutes=1)]
    monkeypatch.setattr(gate_module.timezone, "now", lambda: current_time[0])

    @contextmanager
    def expire_after_role_recheck(*, user_id: int, using: str) -> Iterator[None]:
        assert user_id == grant.binding.owner_user_id and using == "default"
        order.append("role-enter-final-test")
        try:
            yield
        finally:
            order.append("role-exit-final-test")
            current_time[0] = grant.valid_until

    monkeypatch.setattr(
        gate_module, "locked_simulated_action_trading_eligibility", expire_after_role_recheck
    )
    body_returned = False
    with pytest.raises(CorporateActionPostingBlockedError) as captured:
        with gate.atomic_authority(request):
            body_returned = True

    assert body_returned
    assert captured.value.code == "CORPORATE_ACTION_WRITE_AUTHORITY_UNAVAILABLE"
    assert order.index("role-exit-final-test") < max(
        index for index, item in enumerate(order) if item == "grant-enter"
    )
    assert connection.autocommit and not connection.in_atomic_block


def test_owner_audit_event_binds_the_exact_account_grant_for_replay() -> None:
    grant = _grant()
    scope = AuditScopeRef(tenant_id=grant.binding.tenant_id, owner_id=grant.binding.owner_id)
    request = _request(owner_user_id=grant.binding.owner_user_id)
    receipt = CorporateActionPostingReceipt(
        entry_id=41,
        account_revision=41,
        stage_key=request.stage_key,
        request_payload_sha256=request.payload_sha256,
        replayed=True,
    )
    event = audited_module._build_event(
        request,
        receipt,
        recorded_at=request.posted_at + timedelta(seconds=1),
        sequence_no=1,
        predecessor_hash=None,
        scope=scope,
        owner_grant=grant,
    )

    assert any(
        ref.owner == "account"
        and ref.artifact_type == "simulated_corporate_action_write_grant"
        and ref.artifact_id == grant.grant_id
        and ref.artifact_version == grant.grant_version
        and ref.content_hash == grant.content_hash
        for ref in event.evidence_refs
    )
    assert audited_module.DjangoAuditedCorporateActionPostingRepository._matches_winner(
        event, request, receipt, scope, owner_grant=grant
    )
    replacement = _grant(grant_version="grant-v2")
    assert not audited_module.DjangoAuditedCorporateActionPostingRepository._matches_winner(
        event, request, receipt, scope, owner_grant=replacement
    )


def test_replay_timestamp_proof_requires_same_audit_and_outbox_hash() -> None:
    with pytest.raises(ValueError, match="exact Audit/Outbox"):
        CorporateActionSourceTimestampReplayProof(
            request_payload_sha256="a" * 64,
            grant_content_hash="b" * 64,
            audit_event_id="event-1",
            audit_event_content_hash="c" * 64,
            outbox_event_content_hash="d" * 64,
        )


@pytest.mark.parametrize(
    "owner_gate_world",
    [
        {
            "grant": _grant_v2(
                capabilities=(Capability.CASH_STAGE_WRITE,),
                recorded_at=_AT,
                supersedes_content_hash=None,
            ),
            "expected_grant_schema": SIMULATED_CORPORATE_ACTION_WRITE_GRANT_V2_SCHEMA,
        }
    ],
    indirect=True,
)
def test_v2_explicit_cash_grant_enters_cash_only_owner_authority(owner_gate_world) -> None:
    gate, grant, _, _, _ = owner_gate_world
    request = _request(account_id=11, owner_user_id=grant.binding.owner_user_id)

    with gate.atomic_authority(request) as authority:
        assert authority.grant == grant
        assert grant.supports_capability(Capability.CASH_STAGE_WRITE)
        assert authority.grant.schema == SIMULATED_CORPORATE_ACTION_WRITE_GRANT_V2_SCHEMA


@pytest.mark.parametrize(
    "owner_gate_world",
    [
        {
            "grant": _grant_v2(
                capabilities=(Capability.TAX_ASSESS,),
                recorded_at=_AT,
                supersedes_content_hash=None,
            ),
            "expected_grant_schema": SIMULATED_CORPORATE_ACTION_WRITE_GRANT_V2_SCHEMA,
        }
    ],
    indirect=True,
)
def test_tax_only_v2_grant_cannot_enter_cash_owner_authority(owner_gate_world) -> None:
    gate, grant, connection, _, _ = owner_gate_world
    request = _request(account_id=11, owner_user_id=grant.binding.owner_user_id)

    with pytest.raises(CorporateActionPostingBlockedError):
        with gate.atomic_authority(request):
            pytest.fail("tax assessment capability cannot authorize cash posting")
    assert connection.autocommit and not connection.in_atomic_block


@pytest.mark.parametrize(
    "owner_gate_world",
    [
        {
            "grant": _grant_v2(
                capabilities=(Capability.CASH_STAGE_WRITE,),
                recorded_at=_AT,
                supersedes_content_hash=None,
            ),
            "expected_grant_schema": SIMULATED_CORPORATE_ACTION_WRITE_GRANT_V2_SCHEMA,
            "scope_schema": SIMULATED_CORPORATE_ACTION_WRITE_GRANT_SCHEMA,
            "scope_capabilities": None,
            "scope_terms_version": None,
            "scope_terms_sha256": None,
        }
    ],
    indirect=True,
)
def test_policy_scope_schema_must_match_the_actual_v2_grant(owner_gate_world) -> None:
    gate, grant, connection, _, _ = owner_gate_world

    with pytest.raises(CorporateActionPostingBlockedError):
        with gate.atomic_authority(
            _request(account_id=11, owner_user_id=grant.binding.owner_user_id)
        ):
            pytest.fail("a V1 policy scope must not accompany a V2 current grant")
    assert connection.autocommit and not connection.in_atomic_block


@pytest.mark.parametrize(
    "owner_gate_world",
    [
        {
            "grant": _grant_v2(
                capabilities=tuple(
                    sorted(
                        (Capability.CASH_STAGE_WRITE, Capability.TAX_ASSESS),
                        key=lambda capability: capability.value,
                    )
                ),
                recorded_at=_AT,
                supersedes_content_hash=None,
            ),
            "expected_grant_schema": SIMULATED_CORPORATE_ACTION_WRITE_GRANT_V2_SCHEMA,
            "scope_capabilities": (Capability.CASH_STAGE_WRITE,),
        }
    ],
    indirect=True,
)
def test_v2_grant_capabilities_must_be_subset_of_locked_policy(owner_gate_world) -> None:
    gate, grant, connection, _, _ = owner_gate_world

    with pytest.raises(CorporateActionPostingBlockedError):
        with gate.atomic_authority(
            _request(account_id=11, owner_user_id=grant.binding.owner_user_id)
        ):
            pytest.fail("grant rights outside current policy cannot enter owner authority")
    assert connection.autocommit and not connection.in_atomic_block


@pytest.mark.parametrize(
    "owner_gate_world",
    [
        {
            "grant": _grant_v2(
                capabilities=(Capability.CASH_STAGE_WRITE,),
                recorded_at=_AT,
                supersedes_content_hash=None,
            ),
            "expected_grant_schema": SIMULATED_CORPORATE_ACTION_WRITE_GRANT_V2_SCHEMA,
            "scope_terms_version": "owner-terms-v3",
        },
        {
            "grant": _grant_v2(
                capabilities=(Capability.CASH_STAGE_WRITE,),
                recorded_at=_AT,
                supersedes_content_hash=None,
            ),
            "expected_grant_schema": SIMULATED_CORPORATE_ACTION_WRITE_GRANT_V2_SCHEMA,
            "scope_terms_sha256": "e" * 64,
        },
    ],
    indirect=True,
)
def test_v2_grant_terms_must_match_locked_policy(owner_gate_world) -> None:
    gate, grant, connection, _, _ = owner_gate_world
    with pytest.raises(CorporateActionPostingBlockedError):
        with gate.atomic_authority(
            _request(account_id=11, owner_user_id=grant.binding.owner_user_id)
        ):
            pytest.fail("a changed V2 consent terms pin cannot authorize cash posting")
    assert connection.autocommit and not connection.in_atomic_block


@pytest.mark.parametrize(
    "owner_gate_world",
    [
        {
            "grant": _grant_v2(
                capabilities=(Capability.CASH_STAGE_WRITE,),
                recorded_at=_AT,
                supersedes_content_hash=None,
            ),
            "expected_grant_schema": SIMULATED_CORPORATE_ACTION_WRITE_GRANT_V2_SCHEMA,
        }
    ],
    indirect=True,
)
def test_v2_cash_grant_is_rechecked_after_the_write_body(owner_gate_world, monkeypatch) -> None:
    _, grant, connection, _, _ = owner_gate_world
    assert grant.schema == SIMULATED_CORPORATE_ACTION_WRITE_GRANT_V2_SCHEMA
    tax_only = _grant_v2(
        capabilities=(Capability.TAX_ASSESS,),
        grant_version="grant-v2-tax-only",
        recorded_at=_AT,
        supersedes_content_hash=None,
    )
    gate, _, _, _, _ = owner_gate_world
    calls = 0

    @contextmanager
    def changing_current_grant(
        *,
        selector: SimulatedCorporateActionWriteGrantSelector,
        using: str,
        required_capability: Capability,
    ) -> Iterator[SimulatedCorporateActionWriteGrant]:
        nonlocal calls
        assert using == "default" and required_capability is Capability.CASH_STAGE_WRITE
        calls += 1
        yield grant if calls == 1 else tax_only

    monkeypatch.setattr(
        gate_module,
        "locked_current_simulated_corporate_action_write_grant",
        changing_current_grant,
    )
    request = _request(account_id=11, owner_user_id=grant.binding.owner_user_id)

    with pytest.raises(CorporateActionPostingBlockedError):
        with gate.atomic_authority(request):
            pass

    assert calls >= 2
    assert connection.autocommit and not connection.in_atomic_block
