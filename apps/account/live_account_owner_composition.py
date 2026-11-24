"""Resolve formal Account ownership and its physical real account in one transaction."""

from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime

from django.contrib.auth.models import User
from django.db import connections
from django.utils import timezone
from rest_framework.authentication import SessionAuthentication
from rest_framework.request import Request

from apps.account.infrastructure.account_identity_raw_source_repository import (
    DjangoAccountIdentityRawSourceRepository,
)
from apps.account.infrastructure.account_identity_snapshot_repository import (
    DjangoAccountIdentitySnapshotRepository,
)
from apps.account.infrastructure.creation_authentication_transaction import (
    authenticated_creation_transaction,
)
from apps.account.infrastructure.single_owner_authority_policy_v1_repository import (
    DjangoSingleOwnerAuthorityPolicyV1Repository,
)
from core.exceptions import AuthenticationError
from core.integration.owner_tenant_physical_row_v2 import (
    build_simulated_account_owner_physical_row_v2_reader,
)


@contextmanager
def locked_account_owner_session(
    *, request: Request, using: str, before_commit: Callable[[], None]
) -> Iterator[User]:
    """Authenticate a real human session, lock credentials and recheck before commit."""
    if not isinstance(request, Request):
        raise AuthenticationError("Account owner consent requires an authenticated request")
    authenticator = request.successful_authenticator
    if request.method != "POST" or type(authenticator) is not SessionAuthentication:
        raise AuthenticationError("Account owner consent requires a Session-authenticated POST")

    def reauthenticate() -> tuple[object, object]:
        result = authenticator.authenticate(request)
        if result is None:
            raise AuthenticationError("Account owner session expired")
        return result

    with authenticated_creation_transaction(
        using=using,
        mode="session",
        authenticated_user=request.user,
        session=getattr(request._request, "session", None),
        token=None,
        reauthenticate=reauthenticate,
        before_commit=before_commit,
    ) as identity:
        yield User.objects.using(using).select_related("account_profile").get(
            pk=identity.user_id, is_active=True
        )


@dataclass(frozen=True, slots=True)
class LiveAccountOwner:
    """Verified logical scope, underlying physical PK and sealed owner receipts."""

    account_namespace: str
    account_id: str
    owner_user_id: int
    tenant_id: str
    owner_id: str
    physical_row_pk: int
    source_id: str
    source_version: str
    identity_hash: str
    policy_id: str
    policy_version: str
    policy_hash: str
    valid_until: datetime


def read_live_account_owner(
    *, account_namespace: str, account_id: str, owner_user_id: int, using: str
) -> LiveAccountOwner | None:
    """Fence identity and policy successors, then lock the physical PK sealed by Account."""
    db = connections[using]
    if not db.in_atomic_block or db.vendor != "postgresql" or type(owner_user_id) is not int:
        return None
    with db.cursor() as cursor:
        cursor.execute("SHOW transaction_isolation")
        if cursor.fetchone()[0] != "read committed":
            return None
        cursor.execute(
            "LOCK TABLE account_identity_raw_source_ledger, account_identity_snapshot_ledger, account_single_owner_authority_policy_v1 IN SHARE MODE NOWAIT"
        )
    now = timezone.now()
    identity = DjangoAccountIdentitySnapshotRepository(using=using).get_current_head(
        account_namespace=account_namespace, account_id=account_id, as_of=now
    )
    raw = DjangoAccountIdentityRawSourceRepository(using=using).get_current_head(
        account_namespace=account_namespace, account_id=account_id, as_of=now
    )
    if identity is None or raw is None:
        return None
    snapshot = identity.snapshot
    source = raw.source
    if (source.source_id, source.source_version, source.content_hash) != (
        snapshot.underlying_source_id,
        snapshot.underlying_source_version,
        snapshot.underlying_source_content_hash,
    ):
        return None
    if (
        not snapshot.is_knowable_at(now)
        or not source.is_active
        or snapshot.owner_user_id != owner_user_id
        or (source.assignment_state == "authoritative" and source.owner_user_id != owner_user_id)
        or (
            source.assignment_state == "legacy_default"
            and snapshot.provenance_kind != "manual_reclaim"
        )
        or (
            source.account_namespace,
            source.account_id,
            source.underlying_unified_account_namespace,
            source.underlying_unified_account_id,
        )
        != (
            snapshot.account_namespace,
            snapshot.account_id,
            snapshot.underlying_unified_account_namespace,
            snapshot.underlying_unified_account_id,
        )
    ):
        return None
    policies = DjangoSingleOwnerAuthorityPolicyV1Repository(using=using).get_current_for_scope(
        account_namespace=account_namespace, account_id=account_id, as_of=now
    )
    if len(policies) != 1 or policies[0].owner_user_id != owner_user_id:
        return None
    policy = policies[0]
    namespace = snapshot.underlying_unified_account_namespace
    # Account's canonical allocator binds its physical rows to this namespace.
    if namespace != "simulated-account-row":
        return None
    row = build_simulated_account_owner_physical_row_v2_reader(
        namespace=namespace, using=using
    ).read_locked(namespace=namespace, row_pk=snapshot.underlying_unified_account_id)
    deadline = min(snapshot.valid_until, source.valid_until, policy.valid_until)
    if (
        row is None
        or row.user_id != owner_user_id
        or not row.is_active
        or row.raw_account_type != "real"
        or deadline <= timezone.now()
    ):
        return None
    if (
        not User.objects.using(using)
        .select_for_update(nowait=True)
        .filter(pk=owner_user_id, is_active=True)
        .exists()
    ):
        return None
    return LiveAccountOwner(
        account_namespace,
        account_id,
        owner_user_id,
        policy.tenant_id,
        policy.owner_id,
        row.row_pk,
        snapshot.source_id,
        snapshot.source_version,
        snapshot.content_hash,
        policy.policy_id,
        policy.policy_version,
        policy.content_hash,
        deadline,
    )


def read_current_order_owner_role(*, owner_user_id: int, using: str) -> str | None:
    """Fence the active account owner's current approved Broker role through the caller transaction."""
    from apps.account.application.rbac import normalize_role
    from apps.account.infrastructure.identity_models import AccountProfileModel

    db = connections[using]
    if db.vendor != "postgresql" or not db.in_atomic_block:
        return None
    users, profiles = (db.ops.quote_name(m._meta.db_table) for m in (User, AccountProfileModel))
    with db.cursor() as cursor:
        cursor.execute(
            f"""
            SELECT u.is_superuser, p.rbac_role FROM {users} u JOIN {profiles} p ON p.user_id=u.id
            WHERE u.id=%s AND u.is_active AND p.approval_status='approved'
            FOR SHARE OF u, p NOWAIT
        """,
            [owner_user_id],
        )
        result = cursor.fetchone()
    return None if result is None else ("admin" if result[0] else normalize_role(result[1]))
