"""Append the minimum native Account ownership sources needed by Portfolio benchmark tests."""

from datetime import datetime, timedelta
from uuid import uuid4

from django.db import connections, transaction
from django.utils import timezone

from apps.account.infrastructure.account_identity_raw_source_repository import (
    DjangoAccountIdentityRawSourceRepository,
)
from apps.account.infrastructure.account_identity_snapshot_repository import (
    DjangoAccountIdentitySnapshotRepository,
)
from apps.account.infrastructure.single_owner_authority_policy_v1_repository import (
    DjangoSingleOwnerAuthorityPolicyV1Repository,
)
from apps.account.live_account_owner_composition import LiveAccountOwner, read_live_account_owner
from tests.component.account import test_account_identity_raw_source_repository as raw_factory
from tests.component.account import test_account_identity_snapshot_repository as identity_factory
from tests.component.account.test_single_owner_authority_policy_v1_repository import _policy
from tests.support.native_postgres_database import assert_native_postgres_test_database


def persist_benchmark_account(
    *,
    owner_user_id: int,
    physical_row_pk: int,
    portfolio_account_id: str,
    valid_until: datetime | None = None,
    using: str = "default",
) -> LiveAccountOwner:
    """Seed raw identity, its exact snapshot and single owner policy for an existing real row."""
    db = connections[using]
    assert_native_postgres_test_database(database=db)
    uid = owner_user_id
    now = timezone.now()
    end = valid_until or now + timedelta(hours=2)
    tag = uuid4().hex
    logical = {
        "account_namespace": "account",
        "account_id": portfolio_account_id,
        "owner_user_id": uid,
    }
    raw = raw_factory._source(
        **logical,
        source_id=f"raw-{tag}",
        underlying_unified_account_id=physical_row_pk,
        observed_at=now,
        recorded_at=now,
        valid_until=end,
        ttl_valid_until=end,
        row_source_valid_until=end,
    )
    raw_store = DjangoAccountIdentityRawSourceRepository(using=using)
    with raw_store.atomic():
        raw_store.append(raw_factory._record(raw), expected_predecessor_hash=None, recorded_at=now)
    ident = identity_factory._snapshot(
        **logical,
        source_id=f"identity-{tag}",
        underlying_unified_account_namespace=raw.underlying_unified_account_namespace,
        underlying_unified_account_id=physical_row_pk,
        underlying_source_id=raw.source_id,
        underlying_source_version=raw.source_version,
        underlying_source_content_hash=raw.content_hash,
        underlying_source_recorded_at=now,
        underlying_source_valid_until=end,
        issued_at=now,
        recorded_at=now,
        valid_until=end,
        ttl_valid_until=end,
    )
    identity_store = DjangoAccountIdentitySnapshotRepository(using=using)
    with identity_store.atomic():
        identity_store.append(
            identity_factory._record(ident), expected_predecessor_hash=None, recorded_at=now
        )
    policy = _policy(
        **logical,
        policy_id=f"policy-{tag}",
        tenant_id=f"tenant-{uid}",
        owner_id=f"owner-{uid}",
        observed_at=now,
        valid_from=now,
        valid_until=end,
    )
    policy_store = DjangoSingleOwnerAuthorityPolicyV1Repository(using=using)
    with policy_store.atomic():
        policy_store.append(policy=policy, expected_previous_content_hash=None)
    with transaction.atomic(using=using):
        owner = read_live_account_owner(
            account_namespace="account",
            account_id=portfolio_account_id,
            owner_user_id=owner_user_id,
            using=using,
        )
        assert owner is not None and owner.physical_row_pk == physical_row_pk
        return owner
