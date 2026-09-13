"""Real raw-source parents for the disposable Authority V3 current graph."""

from datetime import datetime, timedelta

from apps.account.account_actor_authority_capture_composition import (
    build_account_actor_authority_capture,
)
from apps.account.application.account_actor_authority_raw_source_primitives_v3 import (
    AccountActorAuthorityRawSourceV3Recorder,
)
from apps.account.application.account_authentication_context_source_v3 import (
    PersistedAccountAuthenticationContextSourceV3,
)
from apps.account.application.account_owner_assignment_actor_authority_source_v3 import (
    CaptureAccountOwnerAssignmentActorAuthoritySourceV3Command,
)
from apps.account.application.account_rbac_authority_source_v3 import (
    PersistedAccountRbacAuthoritySourceV3,
)
from apps.account.application.account_user_authority_source_v3 import (
    PersistedAccountUserAuthoritySourceV3,
)
from apps.account.domain.account_actor_authority_raw_source_primitives_v3 import (
    AccountAuthorityRawSourceChainV3,
    AccountAuthorityRawSourceClockV3,
    AccountAuthorityRawSourceIdentityV3,
)
from apps.account.domain.account_authentication_context_source_v3 import (
    AccountAuthenticationContextSourceV3,
    root_claim_hash_for_account_authentication_context_source_v3,
)
from apps.account.domain.account_owner_assignment_actor_authority_source_v3 import (
    AccountOwnerAssignmentActorAuthoritySourceV3,
)
from apps.account.domain.account_rbac_authority_source_v3 import (
    AccountRbacAuthoritySourceV3,
    root_claim_hash_for_account_rbac_authority_source_v3,
)
from apps.account.domain.account_user_authority_source_v3 import (
    AccountUserAuthoritySourceV3,
    root_claim_hash_for_account_user_authority_source_v3,
)
from apps.account.infrastructure.account_authentication_context_source_v3_repository import (
    DjangoAccountAuthenticationContextSourceV3Repository,
)
from apps.account.infrastructure.account_rbac_authority_source_v3_repository import (
    DjangoAccountRbacAuthoritySourceV3Repository,
)
from apps.account.infrastructure.account_user_authority_source_v3_repository import (
    DjangoAccountUserAuthoritySourceV3Repository,
)


def seed_current_actor_source(
    alias: str,
    capture_at: datetime,
    valid_until: datetime,
) -> AccountOwnerAssignmentActorAuthoritySourceV3:
    """Append all three canonical raw roots, then capture their real aggregate.

    The caller fixes the Django clock at capture_at and creates the dedicated
    schema. These are local test facts, never production identity evidence.
    """
    if alias != "evid06_authority_test":
        raise ValueError("current source seed requires the dedicated disposable alias")
    clock = AccountAuthorityRawSourceClockV3(
        capture_at - timedelta(minutes=10),
        capture_at - timedelta(minutes=5),
        valid_until,
    )
    authentication = AccountAuthenticationContextSourceV3(
        identity=AccountAuthorityRawSourceIdentityV3("session-admin-42", "v1"),
        clock=clock,
        chain=AccountAuthorityRawSourceChainV3(
            root_claim_hash=root_claim_hash_for_account_authentication_context_source_v3(
                source_id="session-admin-42",
                principal_id="principal-42",
                user_id=42,
                actor_id="django-user:42",
            )
        ),
        principal_id="principal-42",
        user_id=42,
        actor_id="django-user:42",
        is_authenticated=True,
        authority_state="authenticated",
        authenticated_at=capture_at - timedelta(minutes=20),
    )
    user = AccountUserAuthoritySourceV3(
        identity=AccountAuthorityRawSourceIdentityV3("django-user-42", "v1"),
        clock=clock,
        chain=AccountAuthorityRawSourceChainV3(
            root_claim_hash=root_claim_hash_for_account_user_authority_source_v3(
                source_id="django-user-42", user_id=42, actor_id="django-user:42"
            )
        ),
        user_id=42,
        actor_id="django-user:42",
        is_active=True,
        is_staff=True,
        is_superuser=True,
        authority_state="current",
    )
    rbac = AccountRbacAuthoritySourceV3(
        identity=AccountAuthorityRawSourceIdentityV3("account-profile-42", "v1"),
        clock=clock,
        chain=AccountAuthorityRawSourceChainV3(
            root_claim_hash=root_claim_hash_for_account_rbac_authority_source_v3(
                source_id="account-profile-42", user_id=42, actor_id="django-user:42"
            )
        ),
        user_id=42,
        actor_id="django-user:42",
        rbac_role="admin",
        authority_state="current",
    )
    recorder = AccountActorAuthorityRawSourceV3Recorder("authority-current-component")
    contexts = DjangoAccountAuthenticationContextSourceV3Repository(using=alias)
    with contexts.atomic():
        contexts.append(
            PersistedAccountAuthenticationContextSourceV3(authentication, recorder),
            expected_predecessor_hash=None,
            recorded_at=clock.recorded_at,
        )
    users = DjangoAccountUserAuthoritySourceV3Repository(using=alias)
    with users.atomic():
        users.append(
            PersistedAccountUserAuthoritySourceV3(user, recorder),
            expected_predecessor_hash=None,
            recorded_at=clock.recorded_at,
        )
    roles = DjangoAccountRbacAuthoritySourceV3Repository(using=alias)
    with roles.atomic():
        roles.append(
            PersistedAccountRbacAuthoritySourceV3(rbac, recorder),
            expected_predecessor_hash=None,
            recorded_at=clock.recorded_at,
        )
    return build_account_actor_authority_capture(
        recorder_service_id="account-authority-attestor-v3",
        validity_period=valid_until - capture_at,
        using=alias,
    ).execute(
        CaptureAccountOwnerAssignmentActorAuthoritySourceV3Command(
            "account-authority-source",
            "v3",
            "principal-42",
            42,
            authentication.identity.source_id,
            authentication.identity.source_version,
            authentication.content_hash,
            user.identity.source_id,
            user.identity.source_version,
            user.content_hash,
            rbac.identity.source_id,
            rbac.identity.source_version,
            rbac.content_hash,
        )
    )
