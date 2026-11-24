"""Current authenticated human staff eligible for Portfolio benchmark governance."""

from dataclasses import dataclass

from django.contrib.auth.models import User
from django.db import connections

from apps.account.application.rbac import normalize_role, role_allows_by_matrix
from apps.account.infrastructure.identity_models import AccountProfileModel


@dataclass(frozen=True, slots=True)
class BenchmarkGovernanceActor:
    """Actor and canonical RBAC role established from the live identity tables."""

    user_id: int
    role: str


def read_benchmark_governance_actor(
    *, user_id: int, owner_user_id: int, using: str
) -> BenchmarkGovernanceActor | None:
    """Require current strategy-write staff with existing owner/superuser account access."""
    return _read_governance_actor(
        user_id=user_id, owner_user_id=owner_user_id, capability="strategy", using=using
    )


def read_order_risk_actor(
    *, user_id: int, owner_user_id: int, using: str
) -> BenchmarkGovernanceActor | None:
    """Lock and verify a human staff account with risk-write access to this owner."""
    return _read_governance_actor(
        user_id=user_id, owner_user_id=owner_user_id, capability="risk", using=using
    )


def _read_governance_actor(
    *, user_id: int, owner_user_id: int, capability: str, using: str
) -> BenchmarkGovernanceActor | None:
    db = connections[using]
    if db.vendor != "postgresql" or not db.in_atomic_block:
        return None
    users = db.ops.quote_name(User._meta.db_table)
    profiles = db.ops.quote_name(AccountProfileModel._meta.db_table)
    # Concurrent checkpoints may share signers. Profile/identity replacement must wait.
    with db.cursor() as c:
        c.execute(
            f"""
            SELECT u.id, u.is_superuser, p.rbac_role FROM {users} u
            JOIN {profiles} p ON p.user_id = u.id
            WHERE u.id = %s AND u.is_active AND u.is_staff AND p.approval_status = %s
                  AND (u.id = %s OR u.is_superuser)
            FOR SHARE OF u, p NOWAIT
        """,
            (user_id, "approved", owner_user_id),
        )
        actor = c.fetchone()
    if actor is None:
        return None
    role = "admin" if actor[1] else normalize_role(actor[2])
    if not role_allows_by_matrix(role, "write", capability):
        return None
    return BenchmarkGovernanceActor(user_id=actor[0], role=role)
