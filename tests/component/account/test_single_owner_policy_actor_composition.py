"""Use real session attestations and PostgreSQL policy history in the read facade."""

from dataclasses import replace
from datetime import UTC, datetime, timedelta

from apps.account.application.account_owner_assignment_actor_authority_v3 import (
    AuthenticatedAccountPrincipalV3,
)
from apps.account.application.single_owner_actor_authority import SingleOwnerPolicyBinding
from apps.account.domain.single_owner_authority_policy_v1 import SingleOwnerAuthorityPolicyV1
from apps.account.infrastructure.single_owner_authority_policy_v1_repository import (
    DjangoSingleOwnerAuthorityPolicyV1Repository,
)
from apps.account.single_owner_authority_policy_composition import (
    build_current_single_owner_participants_provider,
)
from tests.component.account.test_account_actor_authority_raw_source_publisher_postgres import (
    _gateway,
    _new_user,
    _session_for_user,
)
from tests.component.account.test_account_actor_authority_raw_source_publisher_postgres import (
    evid06_alias as evid06_alias,
)
from tests.component.account.test_single_owner_authority_policy_v1_repository import (
    policy_alias as policy_alias,
)


def test_real_actor_and_policy_read_then_revocation_rejects_the_same_binding(policy_alias: str):
    user, _ = _new_user(policy_alias, username="evid07-policy-owner")
    user.is_staff = True
    user.is_superuser = True
    user.save(using=policy_alias, update_fields=["is_staff", "is_superuser"])
    session = _session_for_user(
        policy_alias, user, expires_at=datetime.now(UTC) + timedelta(minutes=20)
    )
    publication = _gateway(policy_alias, user, session).publish()
    observed_at = datetime.now(UTC)
    policy = SingleOwnerAuthorityPolicyV1(
        policy_id="read-composition-policy",
        policy_version="1",
        tenant_id="tenant-test",
        owner_id="owner-test",
        account_namespace="account",
        account_id="account-test",
        owner_user_id=user.pk,
        authorization_content_hash="a" * 64,
        observed_at=observed_at,
        valid_from=observed_at,
        valid_until=publication.valid_until,
    )
    repository = DjangoSingleOwnerAuthorityPolicyV1Repository(using=policy_alias)
    with repository.atomic():
        repository.append(policy=policy, expected_previous_content_hash=None)
    principal = AuthenticatedAccountPrincipalV3(
        principal_id=publication.principal_id,
        user_id=publication.user_id,
        authentication_context_hash=publication.authentication_context.content_hash,
        authenticated_at=publication.observed_at,
        valid_until=publication.valid_until,
    )
    binding = SingleOwnerPolicyBinding(
        policy.policy_id,
        policy.policy_version,
        policy.content_hash,
        policy.tenant_id,
        policy.owner_id,
        policy.account_namespace,
        policy.account_id,
    )
    provider = build_current_single_owner_participants_provider(
        principal=principal,
        policy_binding=binding,
        actor_source_id=publication.actor.source_id,
        actor_source_version=publication.actor.source_version,
        actor_source_content_hash=publication.actor.content_hash,
        using=policy_alias,
    )
    current = provider.get_current(as_of=datetime.now(UTC))
    assert current is not None
    assert current.claimant.actor_id == current.approver.actor_id
    assert current.claimant.user_id == current.approver.user_id == user.pk
    assert current.claimant.is_staff is current.approver.is_staff is True
    revoked = replace(
        policy,
        policy_version="2",
        observed_at=datetime.now(UTC),
        status="revoked",
        identity_hash="",
        content_hash="",
    )
    with repository.atomic():
        repository.append(policy=revoked, expected_previous_content_hash=policy.content_hash)
    assert provider.get_current(as_of=datetime.now(UTC)) is None
