"""Public composition boundary for global transactional Audit/Outbox readiness."""

from apps.audit.application.system_audit_authority_renewal_guard import (
    SystemAuditAuthorityLease,
)
from apps.audit.infrastructure.system_audit_outbox_runtime import (
    get_system_audit_authority_lease,
)


def read_system_audit_runtime_readiness(
    *, environment: str, using: str
) -> SystemAuditAuthorityLease:
    """Read current operational readiness without granting any account or staff scope."""
    return get_system_audit_authority_lease(environment=environment, using=using)
