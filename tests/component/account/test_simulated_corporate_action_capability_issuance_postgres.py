"""Actual owner Session/CSRF and locked V2 policy; no financial or tax-date activation."""

from __future__ import annotations

import base64
from dataclasses import replace

import pytest
from django.contrib.auth.models import User
from django.db import connection
from django.utils import timezone
from rest_framework.exceptions import PermissionDenied

from apps.account import simulated_corporate_action_policy_scope_composition as policies
from apps.account.application.simulated_corporate_action_write_grant import (
    SimulatedCorporateActionWriteGrantConflict,
    SimulatedCorporateActionWriteGrantUnavailable,
)
from apps.account.domain.simulated_corporate_action_write_capabilities import (
    SimulatedCorporateActionWriteCapability as Capability,
)
from apps.account.domain.simulated_corporate_action_write_grant import (
    SIMULATED_CORPORATE_ACTION_WRITE_GRANT_V2_PERMISSION,
    SIMULATED_CORPORATE_ACTION_WRITE_GRANT_V2_SCHEMA,
)
from apps.account.infrastructure.identity_models import AccountProfileModel
from apps.account.infrastructure.simulated_corporate_action_write_grant_models import (
    SimulatedCorporateActionWriteGrantModel as GrantRow,
)
from apps.account.infrastructure.simulated_corporate_action_write_grant_repository import (
    DjangoSimulatedCorporateActionWriteGrantRepository as Repository,
)
from apps.account.infrastructure.simulated_corporate_action_write_grant_seal import (
    SimulatedCorporateActionWriteGrantSeal,
)
from apps.account.simulated_corporate_action_write_issuance_composition import (
    issue_authenticated_simulated_corporate_action_grant as issue,
)
from apps.account.simulated_corporate_action_write_issuance_composition import (
    revoke_authenticated_simulated_corporate_action_grant as revoke,
)
from apps.config_center.application.runtime_public import activate_runtime_profile_patch
from core.integration.config_center_runtime import get_active_runtime_value_evidence
from shared.config.secrets import get_secrets
from tests.component.account.test_simulated_corporate_action_write_issuance_postgres import (
    _request,
)
from tests.component.account.test_simulated_corporate_action_write_issuance_postgres import (
    owner_world as owner_world,
)
from tests.support.account_authority_generation_flush import (
    preserve_account_authority_generation as preserve_account_authority_generation,
)

pytestmark = [
    pytest.mark.django_db,
    pytest.mark.skipif(
        connection.vendor != "postgresql",
        reason="Native migrated PostgreSQL contract; executed by the required PostgreSQL workflow.",
    ),
]


def _v2_command(world, *, selected=(Capability.TAX_ASSESS,)):
    assert connection.vendor == "postgresql"
    evidence = get_active_runtime_value_evidence(
        environment="development",
        definition_key=policies.SIMULATED_ACTION_WRITE_POLICY_KEY,
        as_of=timezone.now(),
    )
    item = dict(evidence.value["policies"][0])
    item.update(
        policy_version="explicit-v2",
        permission=SIMULATED_CORPORATE_ACTION_WRITE_GRANT_V2_PERMISSION,
        capabilities=[Capability.TAX_ASSESS.value, Capability.TAX_WITHHOLD.value],
        terms_version="synthetic-owner-tax-terms-v2",
        terms_sha256="d" * 64,
    )
    activate_runtime_profile_patch(
        environment="development",
        patch={
            policies.SIMULATED_ACTION_WRITE_POLICY_KEY: {
                "schema_version": policies.SIMULATED_ACTION_WRITE_POLICY_SCHEMA_V2,
                "enabled": True,
                "policies": [item],
            }
        },
        actor="native-v2-owner-consent-test",
        reason="explicit isolated V2 capability scope; no production activation",
    )
    policy = policies.read_current_simulated_action_write_policy(
        canonical_account_id=world.source.account_id,
        owner_user_id=world.user.pk,
        environment="development",
        as_of=timezone.now(),
        expected_grant_schema=SIMULATED_CORPORATE_ACTION_WRITE_GRANT_V2_SCHEMA,
    )
    return replace(
        world.command,
        grant_version="explicit-v2",
        expected_binding=replace(
            world.command.expected_binding,
            policy_version=policy.policy_version,
            policy_content_hash=policy.content_hash,
        ),
        grant_schema=policy.grant_schema,
        capabilities=selected,
        terms_version=policy.terms_version,
        terms_sha256=policy.terms_sha256,
    )


def test_native_v2_session_owner_issues_only_selected_capability_and_retries_exactly(owner_world):
    world = owner_world
    command = _v2_command(world)
    request = _request(world.user)
    grant = issue(request, command=command, scope_locker=world.locker, using="default")
    assert grant.schema == SIMULATED_CORPORATE_ACTION_WRITE_GRANT_V2_SCHEMA
    assert grant.capabilities == (Capability.TAX_ASSESS,)
    assert not grant.supports_capability(Capability.CASH_STAGE_WRITE)
    assert not grant.supports_capability(Capability.TAX_WITHHOLD)
    assert grant.issuer_evidence_version == "2"
    assert SimulatedCorporateActionWriteGrantSeal().verify(grant)
    assert issue(request, command=command, scope_locker=world.locker, using="default") == grant
    with pytest.raises(SimulatedCorporateActionWriteGrantConflict):
        issue(
            request,
            command=replace(command, capabilities=(Capability.TAX_WITHHOLD,)),
            scope_locker=world.locker,
            using="default",
        )
    assert GrantRow._default_manager.count() == 1
    world.row.refresh_from_db()
    assert world.row.current_cash == 10000


@pytest.mark.django_db(
    transaction=True,
    available_apps=[
        "django.contrib.auth",
        "django.contrib.contenttypes",
        "django.contrib.sessions",
        "apps.account",
        "apps.simulated_trading",
        "apps.config_center",
        "apps.audit",
    ],
)
def test_native_v2_owner_upgrade_and_withdraw_survive_role_policy_and_key_loss(
    owner_world, monkeypatch
):
    world = owner_world
    old = issue(
        _request(world.user), command=world.command, scope_locker=world.locker, using="default"
    )
    command = replace(_v2_command(world), expected_predecessor_content_hash=old.content_hash)
    grant = issue(_request(world.user), command=command, scope_locker=world.locker, using="default")
    assert grant.identity_hash == old.identity_hash
    assert Repository().get_current_grant(selector=old.selector, as_of=timezone.now()) is None
    assert GrantRow._default_manager.count() == 2
    AccountProfileModel.objects.filter(user_id=world.user.pk).update(rbac_role="read_only")
    activate_runtime_profile_patch(
        environment="development",
        patch={
            policies.SIMULATED_ACTION_WRITE_POLICY_KEY: {
                "schema_version": policies.SIMULATED_ACTION_WRITE_POLICY_SCHEMA_V2,
                "enabled": False,
                "policies": [],
            }
        },
        actor="native-v2-policy-disabled",
        reason="withdrawal must remain possible without current service eligibility",
    )
    monkeypatch.setenv("AGOMTRADEPRO_ENCRYPTION_KEY", base64.urlsafe_b64encode(b"r" * 32).decode())
    get_secrets.cache_clear()
    assert not SimulatedCorporateActionWriteGrantSeal().verify(grant)
    withdrawal = revoke(
        _request(world.user),
        selector=grant.selector,
        revocation_id="native-v2-whole-withdrawal",
        revocation_version="1",
        using="default",
    )
    assert withdrawal.grant_content_hash == grant.content_hash
    record = Repository().get_exact_record(selector=grant.selector, as_of=timezone.now())
    assert record is not None and record.revocation == withdrawal
    assert (
        Repository().get_current_for_scope(
            "simulated", world.source.account_id, as_of=timezone.now()
        )
        == ()
    )


@pytest.mark.parametrize("denial", ["csrf", "other_owner"])
def test_native_v2_missing_csrf_or_another_owner_cannot_issue(owner_world, denial):
    world = owner_world
    command = _v2_command(world)
    requester = world.user
    expected = PermissionDenied
    if denial == "other_owner":
        requester = User.objects.create_user(username="other-native-v2-owner", is_staff=False)
        role = AccountProfileModel.objects.get(user_id=world.user.pk).rbac_role
        AccountProfileModel.objects.filter(user_id=requester.pk).update(rbac_role=role)
        expected = SimulatedCorporateActionWriteGrantUnavailable
    with pytest.raises(expected):
        issue(
            _request(requester, csrf=denial != "csrf"),
            command=command,
            scope_locker=world.locker,
            using="default",
        )
    assert GrantRow._default_manager.count() == 0


def test_native_v2_changed_locked_policy_terms_reject_original_confirmation(owner_world):
    world = owner_world
    command = _v2_command(world)
    evidence = get_active_runtime_value_evidence(
        environment="development",
        definition_key=policies.SIMULATED_ACTION_WRITE_POLICY_KEY,
        as_of=timezone.now(),
    )
    value = dict(evidence.value)
    item = dict(value["policies"][0], terms_sha256="e" * 64)
    value["policies"] = [item]
    activate_runtime_profile_patch(
        environment="development",
        patch={policies.SIMULATED_ACTION_WRITE_POLICY_KEY: value},
        actor="native-v2-terms-changed",
        reason="old terms must not authorize new current policy",
    )
    with pytest.raises(SimulatedCorporateActionWriteGrantUnavailable):
        issue(_request(world.user), command=command, scope_locker=world.locker, using="default")
    assert GrantRow._default_manager.count() == 0


def test_native_v2_cannot_select_a_capability_outside_current_policy(owner_world):
    world = owner_world
    command = _v2_command(world, selected=(Capability.CASH_STAGE_WRITE,))
    with pytest.raises(SimulatedCorporateActionWriteGrantUnavailable):
        issue(_request(world.user), command=command, scope_locker=world.locker, using="default")
    assert GrantRow._default_manager.count() == 0
