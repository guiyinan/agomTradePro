"""Expose the canonical audit model to the isolated test app."""

from apps.audit.infrastructure.system_audit_models import SystemAuditEventModel

__all__ = ["SystemAuditEventModel"]
