"""Reject unavailable write aliases before querying any receipt or authority source."""

from datetime import timedelta

import pytest

from apps.account.account_owner_assignment_provenance_receipt_v4_composition import (
    build_account_owner_assignment_provenance_receipt_v4_issuer,
)
from apps.account.application.account_owner_assignment_actor_authority_v3 import (
    AuthenticatedAccountPrincipalV3,
)
from apps.account.application.account_owner_assignment_evidence import (
    AccountOwnerAssignmentUnavailable,
)
from apps.account.application.single_owner_actor_authority import SingleOwnerPolicyBinding
from tests.unit.account.test_account_owner_assignment_provenance_receipt_v4_application import (
    _command,
    _record,
)


def test_unknown_alias_returns_typed_unavailable_without_default_database_access():
    record = _record()
    actor = record.authority
    policy = record.receipt.policy
    issuer = build_account_owner_assignment_provenance_receipt_v4_issuer(
        principal=AuthenticatedAccountPrincipalV3(
            actor.principal_id,
            actor.user_id,
            actor.authentication_context_hash,
            actor.recorded_at,
            actor.valid_until,
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
        actor_source_id=actor.source_id,
        actor_source_version=actor.source_version,
        actor_source_content_hash=actor.source_content_hash,
        validity_period=timedelta(minutes=4),
        using="receipt_v4_missing_alias",
    )
    with pytest.raises(AccountOwnerAssignmentUnavailable, match="alias is unavailable"):
        issuer.execute(_command(record.receipt.binding))
