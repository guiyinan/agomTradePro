"""Current single-owner resolution preserves server identity and scope."""

from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest

from apps.account.application.account_owner_assignment_actor_authority_v3 import (
    AuthenticatedAccountPrincipalV3,
    CurrentAccountActorAuthorityV3,
)
from apps.account.application.account_owner_assignment_evidence import (
    AccountOwnerAssignmentCorruption,
)
from apps.account.application.single_owner_actor_authority import (
    CurrentSingleOwnerParticipantsProvider,
    SingleOwnerPolicyBinding,
)
from apps.account.domain.single_owner_authority_policy_v1 import SingleOwnerAuthorityPolicyV1

NOW = datetime(2026, 9, 10, 12, tzinfo=UTC)


def policy():
    return SingleOwnerAuthorityPolicyV1(
        policy_id="personal-project",
        policy_version="1",
        tenant_id="tenant-a",
        owner_id="owner-a",
        account_namespace="account",
        account_id="account-a",
        owner_user_id=17,
        authorization_content_hash="a" * 64,
        observed_at=NOW,
        valid_from=NOW,
        valid_until=NOW + timedelta(hours=1),
    )


class PolicyReader:
    def __init__(self, value):
        self.value = value
        self.calls = []

    def get_exact_current(self, **selector):
        self.calls.append(selector)
        return self.value


class ActorReader:
    def __init__(self, value):
        self.value = value
        self.calls = []

    def get_exact_current(self, **selector):
        self.calls.append(selector)
        return self.value


def setup_provider():
    current_policy = policy()
    principal = AuthenticatedAccountPrincipalV3(
        "principal-a", 17, "b" * 64, NOW, NOW + timedelta(minutes=5)
    )
    actor = CurrentAccountActorAuthorityV3(
        "principal-a",
        17,
        "b" * 64,
        "actor-a",
        True,
        True,
        True,
        True,
        "admin",
        "source-a",
        "1",
        "c" * 64,
        NOW,
        NOW + timedelta(minutes=5),
    )
    policies, actors = PolicyReader(current_policy), ActorReader(actor)
    binding = SingleOwnerPolicyBinding(
        current_policy.policy_id,
        current_policy.policy_version,
        current_policy.content_hash,
        "tenant-a",
        "owner-a",
        "account",
        "account-a",
    )
    return (
        CurrentSingleOwnerParticipantsProvider(principal, binding, policies, actors),
        policies,
        actors,
    )


def test_real_admin_remains_same_staff_actor_in_both_roles():
    provider, policies, actors = setup_provider()
    result = provider.get_current(as_of=NOW)
    assert result is not None
    assert result.claimant.actor_id == result.approver.actor_id == "actor-a"
    assert result.claimant.user_id == result.approver.user_id == 17
    assert result.claimant.is_staff is result.approver.is_staff is True
    assert result.claimant.role == "account_owner_claimant"
    assert result.approver.role == "account_owner_assignment_approver"
    assert result.valid_until == NOW + timedelta(minutes=5)
    assert len(policies.calls) == len(actors.calls) == 1


def test_policy_revocation_is_reread_instead_of_cached():
    provider, policies, actors = setup_provider()
    assert provider.get_current(as_of=NOW) is not None
    policies.value = None
    assert provider.get_current(as_of=NOW) is None
    assert len(policies.calls) == 2
    assert len(actors.calls) == 1


@pytest.mark.parametrize(
    "field,value", [("tenant_id", "tenant-b"), ("owner_id", "owner-b"), ("account_id", "account-b")]
)
def test_server_binding_cannot_cross_scope(field, value):
    provider, _, _ = setup_provider()
    provider = replace(provider, binding=replace(provider.binding, **{field: value}))
    with pytest.raises(AccountOwnerAssignmentCorruption):
        provider.get_current(as_of=NOW)


@pytest.mark.parametrize(
    "field,value",
    [
        ("is_active", False),
        ("is_authenticated", False),
        ("is_staff", False),
        ("rbac_role", "viewer"),
    ],
)
def test_current_actor_must_still_be_an_authenticated_active_admin(field, value):
    provider, _, actors = setup_provider()
    actors.value = replace(actors.value, **{field: value})
    assert provider.get_current(as_of=NOW) is None


def test_principal_expiry_prevents_source_reads():
    provider, policies, actors = setup_provider()
    assert provider.get_current(as_of=NOW + timedelta(minutes=5)) is None
    assert not policies.calls and not actors.calls


def test_actor_selector_substitution_is_corruption():
    provider, _, actors = setup_provider()
    actors.value = replace(actors.value, user_id=18)
    with pytest.raises(AccountOwnerAssignmentCorruption):
        provider.get_current(as_of=NOW)


def test_wrong_policy_hash_is_rejected():
    provider, _, _ = setup_provider()
    provider = replace(provider, binding=replace(provider.binding, expected_content_hash="d" * 64))
    with pytest.raises(AccountOwnerAssignmentCorruption):
        provider.get_current(as_of=NOW)


def test_actor_permission_change_is_reread_without_reusing_a_prior_resolution():
    provider, _, actors = setup_provider()
    assert provider.get_current(as_of=NOW) is not None
    actors.value = replace(actors.value, rbac_role="viewer")
    assert provider.get_current(as_of=NOW) is None
    assert len(actors.calls) == 2


def test_designated_owner_must_match_the_authenticated_principal():
    provider, policies, actors = setup_provider()
    policies.value = replace(policy(), owner_user_id=18, identity_hash="", content_hash="")
    provider = replace(
        provider,
        binding=replace(provider.binding, expected_content_hash=policies.value.content_hash),
    )
    assert provider.get_current(as_of=NOW) is None
    assert not actors.calls


@pytest.mark.parametrize("source", ["policy", "actor"])
def test_untyped_source_values_cannot_be_accepted_as_authority(source):
    provider, policies, actors = setup_provider()
    if source == "policy":
        policies.value = {"mode": "single_owner"}
    else:
        actors.value = {"is_staff": True}
    with pytest.raises(AccountOwnerAssignmentCorruption):
        provider.get_current(as_of=NOW)


def test_future_actor_observation_cannot_be_laundered_into_current_authority():
    provider, _, actors = setup_provider()
    actors.value = replace(actors.value, recorded_at=NOW + timedelta(seconds=1))
    with pytest.raises(AccountOwnerAssignmentCorruption):
        provider.get_current(as_of=NOW)


def test_naive_observation_time_is_rejected_before_reading_sources():
    provider, policies, actors = setup_provider()
    with pytest.raises(ValueError):
        provider.get_current(as_of=NOW.replace(tzinfo=None))
    assert not policies.calls and not actors.calls


def test_future_policy_observation_does_not_authorize_an_earlier_request():
    provider, policies, actors = setup_provider()
    policies.value = replace(policy(), observed_at=NOW + timedelta(seconds=1), content_hash="")
    provider = replace(
        provider,
        binding=replace(provider.binding, expected_content_hash=policies.value.content_hash),
    )
    assert provider.get_current(as_of=NOW) is None
    assert not actors.calls
