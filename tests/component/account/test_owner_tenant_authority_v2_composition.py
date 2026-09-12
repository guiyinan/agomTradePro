"""Actual auth and physical reads around synthetic local creation provenance."""

from datetime import timedelta

import pytest
from django.contrib.auth.models import User
from django.db import connections, transaction

from apps.account.account_actor_authority_capture_composition import (
    build_account_actor_authority_request_reader,
)
from apps.account.application.account_owner_assignment_actor_authority_v3 import (
    AuthenticatedAccountPrincipalV3,
)
from apps.account.application.owner_tenant_authority_v2 import (
    GetCurrentOwnerTenantAuthorityV2Command,
    IssueOwnerTenantAuthorityV2Command,
    RevokeOwnerTenantAuthorityV2Command,
)
from apps.account.application.owner_tenant_authority_v2_contracts import (
    OwnerTenantAuthorityV2Corruption,
)
from apps.account.application.single_owner_actor_authority import SingleOwnerPolicyBinding
from apps.account.infrastructure.account_owner_assignment_actor_authority_source_v3_models import (
    AccountOwnerAssignmentActorAuthoritySourceV3Model,
)
from apps.account.infrastructure.owner_tenant_authority_v2_models import (
    OwnerTenantAuthorityV2Model,
)
from apps.account.owner_tenant_authority_v2_composition import (
    build_owner_tenant_authority_v2_facade,
)
from apps.simulated_trading.infrastructure.models import SimulatedAccountModel
from core.integration.owner_tenant_physical_row_v2 import (
    build_simulated_account_owner_physical_row_v2_reader,
)
from tests.component.account.test_account_actor_authority_raw_source_publisher_postgres import (
    _gateway,
    _session_for_user,
)
from tests.component.account.test_owner_tenant_authority_v2_repository import _owner_seed
from tests.unit.account import test_allocated_physical_account_row_observation_v3 as root_fixtures
from tests.unit.account import test_canonical_account_creation as creation_fixtures

pytest_plugins = ["tests.component.account.test_owner_tenant_authority_v2_repository"]


@pytest.fixture
def owner_physical_alias(owner_alias):
    with connections[owner_alias].schema_editor() as editor:
        editor.create_model(SimulatedAccountModel)
    try:
        yield owner_alias
    finally:
        with connections[owner_alias].schema_editor() as editor:
            editor.delete_model(SimulatedAccountModel)


def _physical_fixture(alias, record):
    sealed = record.authority.assignment.subject.physical_root.physical_observation
    row = SimulatedAccountModel.objects.using(alias).create(
        id=sealed.underlying_unified_account_id,
        user_id=sealed.row_user_id,
        account_name="explicit synthetic provenance fixture",
        account_type=sealed.raw_account_type,
        initial_capital=100,
        current_cash=100,
        total_value=100,
        auto_trading_enabled=False,
    )
    # Deliberately synthetic historical fixture, never a claim of real creation.
    SimulatedAccountModel.objects.using(alias).filter(pk=row.pk).update(
        created_at=sealed.row_created_at,
        updated_at=sealed.row_updated_at,
    )
    return row


def _seed_live_compatible(alias, monkeypatch):
    # Choose the actual model's lowercase enum before constructing any fixture hashes.
    raw_type = creation_fixtures.SimulatedAccountRawObservation

    def simulated_raw(**values):
        values["raw_account_type"] = "simulated"
        return raw_type(**values)

    monkeypatch.setattr(creation_fixtures, "SimulatedAccountRawObservation", simulated_raw)
    monkeypatch.setattr(
        root_fixtures,
        "_allocation",
        lambda: creation_fixtures._allocation(requested_raw_account_type="simulated"),
    )
    return _owner_seed(alias, monkeypatch)


def _facade(alias, record, authentication=None):
    auth = authentication or record.authentication
    policy = record.authority.policy
    sealed = record.authority.assignment.subject.physical_root.physical_observation
    return build_owner_tenant_authority_v2_facade(
        principal=AuthenticatedAccountPrincipalV3(
            principal_id=auth.principal_id,
            user_id=auth.user_id,
            authentication_context_hash=auth.authentication_context_hash,
            authenticated_at=auth.recorded_at,
            valid_until=auth.valid_until,
        ),
        policy_binding=SingleOwnerPolicyBinding(
            policy.policy_id,
            policy.policy_version,
            policy.content_hash,
            policy.tenant_id,
            policy.owner_id,
            policy.account_namespace,
            policy.account_id,
        ),
        actor_source_id=auth.source_id,
        actor_source_version=auth.source_version,
        actor_source_content_hash=auth.source_content_hash,
        physical=build_simulated_account_owner_physical_row_v2_reader(
            namespace=sealed.underlying_unified_account_namespace,
            using=alias,
        ),
        validity_period=timedelta(hours=1),
        using=alias,
    )


def test_locked_facade_real_source_rollback_and_live_owner_recheck(
    owner_physical_alias, monkeypatch
):
    alias = owner_physical_alias
    record = _seed_live_compatible(alias, monkeypatch)
    row = _physical_fixture(alias, record)
    facade = _facade(alias, record)
    assignment = record.authority.assignment
    command = IssueOwnerTenantAuthorityV2Command(
        "facade-owner-root",
        "v2.1",
        assignment.evidence_id,
        assignment.evidence_version,
        assignment.content_hash,
    )
    with pytest.raises(RuntimeError, match="rollback authenticated decision"):
        with transaction.atomic(using=alias):
            facade.issue(command)
            raise RuntimeError("rollback authenticated decision")
    assert OwnerTenantAuthorityV2Model.objects.using(alias).count() == 0

    def reject_default(execute, sql, params, many, context):
        raise AssertionError("owner facade queried default alias")

    with connections["default"].execute_wrapper(reject_default):
        root = facade.issue(command)
        selector = GetCurrentOwnerTenantAuthorityV2Command(
            root.authority_id,
            root.authority_version,
            root.content_hash,
        )
        assert facade.get_current(selector).authority == root
        assert facade.issue(command) == root
        SimulatedAccountModel.objects.using(alias).filter(pk=row.pk).update(user_id=None)
        assert facade.get_current(selector) is None
        SimulatedAccountModel.objects.using(alias).filter(pk=row.pk).update(
            user_id=record.authentication.user_id
        )
        with transaction.atomic(using=alias):
            table = AccountOwnerAssignmentActorAuthoritySourceV3Model._meta.db_table
            with connections[alias].cursor() as cursor:
                cursor.execute(f'UPDATE "{table}" SET facts_seal = %s', ["0" * 64])
            with pytest.raises(OwnerTenantAuthorityV2Corruption):
                facade.get_current(selector)
            transaction.set_rollback(True, using=alias)
    assert OwnerTenantAuthorityV2Model.objects.using(alias).count() == 1


def test_new_actual_session_after_assignment_expiry_reads_decision_then_revokes(
    owner_physical_alias, monkeypatch
):
    alias = owner_physical_alias
    record = _seed_live_compatible(alias, monkeypatch)
    _physical_fixture(alias, record)
    facade = _facade(alias, record)
    assignment = record.authority.assignment
    root = facade.issue(
        IssueOwnerTenantAuthorityV2Command(
            "session-owner-root",
            "v2.1",
            assignment.evidence_id,
            assignment.evidence_version,
            assignment.content_hash,
        )
    )
    selector = GetCurrentOwnerTenantAuthorityV2Command(
        root.authority_id, root.authority_version, root.content_hash
    )
    now = record.authentication.valid_until + timedelta(seconds=1)
    monkeypatch.setattr("django.utils.timezone.now", lambda: now)
    assert not assignment.is_current_at(now)
    assert facade.get_current(selector) is None
    user = User.objects.using(alias).get(pk=record.authentication.user_id)
    session = _session_for_user(alias, user, expires_at=now + timedelta(hours=1))
    published = _gateway(alias, user, session).publish()
    authentication = build_account_actor_authority_request_reader(
        source_id=published.actor.source_id,
        source_version=published.actor.source_version,
        expected_content_hash=published.actor.content_hash,
        using=alias,
    ).get_exact_current(
        principal_id=published.principal_id,
        user_id=published.user_id,
        expected_authentication_context_hash=published.authentication_context.content_hash,
        as_of=now,
    )
    assert authentication is not None
    assert authentication.source_content_hash != record.authentication.source_content_hash
    fresh = _facade(alias, record, authentication)
    observed = fresh.get_current(selector)
    assert observed is not None and observed.authority == root
    assert observed.authentication == authentication
    fresh.revoke(
        RevokeOwnerTenantAuthorityV2Command(
            root.authority_id,
            root.authority_version,
            root.content_hash,
            "owner-request",
        )
    )
    assert fresh.get_current(selector) is None
