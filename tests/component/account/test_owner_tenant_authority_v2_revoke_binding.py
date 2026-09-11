"""A different real administrator cannot append another owner's revocation."""

from dataclasses import replace
from datetime import timedelta

import pytest

from apps.account.account_actor_authority_capture_composition import (
    build_account_actor_authority_request_reader,
)
from apps.account.application.owner_tenant_authority_v2_contracts import (
    OwnerTenantAuthorityV2Conflict,
    PersistedOwnerTenantAuthorityV2Revocation,
)
from apps.account.domain.account_owner_assignment_evidence import AccountOwnerAssignmentActor
from apps.account.domain.owner_tenant_authority_v2 import REVOKER_ROLE
from apps.account.infrastructure.owner_tenant_authority_v2_models import (
    OwnerTenantAuthorityV2RevocationModel,
)
from apps.account.infrastructure.owner_tenant_authority_v2_repository import (
    DjangoOwnerTenantAuthorityV2Repository,
)
from tests.component.account.test_account_actor_authority_raw_source_publisher_postgres import (
    _gateway,
    _new_user,
    _session_for_user,
)
from tests.component.account.test_owner_tenant_authority_v2_repository import (
    _append_owner,
    _owner_seed,
    _revocation,
)

pytest_plugins = ["tests.component.account.test_owner_tenant_authority_v2_repository"]


def test_other_real_admin_cannot_leave_invalid_revocation_when_error_is_caught(
    owner_alias, monkeypatch
):
    record = _owner_seed(owner_alias, monkeypatch)
    repository = DjangoOwnerTenantAuthorityV2Repository(using=owner_alias)
    _append_owner(repository, record)
    now = record.authority.recorded_at + timedelta(seconds=1)
    monkeypatch.setattr("django.utils.timezone.now", lambda: now)
    other, _ = _new_user(owner_alias, username="other-real-admin")
    assert other.pk != record.authentication.user_id
    session = _session_for_user(owner_alias, other, expires_at=now + timedelta(hours=1))
    published = _gateway(owner_alias, other, session).publish()
    authentication = build_account_actor_authority_request_reader(
        source_id=published.actor.source_id,
        source_version=published.actor.source_version,
        expected_content_hash=published.actor.content_hash,
        using=owner_alias,
    ).get_exact_current(
        principal_id=published.principal_id,
        user_id=published.user_id,
        expected_authentication_context_hash=published.authentication_context.content_hash,
        as_of=now,
    )
    assert authentication is not None
    original = _revocation(record).revocation
    candidate = PersistedOwnerTenantAuthorityV2Revocation(
        replace(
            original,
            revoked_by=AccountOwnerAssignmentActor(
                actor_id=authentication.actor_id,
                user_id=authentication.user_id,
                role=REVOKER_ROLE,
                is_staff=authentication.is_staff,
            ),
            identity_hash="",
            content_hash="",
        ),
        authentication,
    )
    # Catch inside the UOW: rejection must precede INSERT, not rely on its caller rolling back.
    with repository.atomic():
        with pytest.raises(OwnerTenantAuthorityV2Conflict):
            repository.append_revocation(
                candidate,
                expected_authority_content_hash=record.authority.content_hash,
                recorded_at=now,
            )
    assert OwnerTenantAuthorityV2RevocationModel.objects.using(owner_alias).count() == 0
