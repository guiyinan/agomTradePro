"""Fail-closed composition boundary for system-audit outbox dispatch.

The repository and application dispatcher already preserve the immutable
``SystemAuditEvent`` object.  No external sink has yet been selected that can
carry its canonical payload, content hash, stream predecessor, and idempotency
identity unchanged.  In particular, the generic ``events`` Celery bus is not
an acceptable substitute: it can fall back to an in-memory publish and its
task reconstructs a different DomainEvent envelope.

Keep this boundary explicit so a future publisher cannot accidentally be
introduced by importing the generic event bus or by claiming rows before a
durable broker/sink preflight has passed.
"""

from __future__ import annotations

from typing import NoReturn


class SystemAuditOutboxPublisherUnavailable(RuntimeError):
    """No canonical, durable system-audit publisher is configured."""

    def __init__(self, message: str, *, reason_code: str) -> None:
        super().__init__(message)
        self.reason_code = reason_code


def get_system_audit_outbox_dispatcher() -> NoReturn:
    """Refuse dispatch until a canonical publisher composition is available."""

    raise SystemAuditOutboxPublisherUnavailable(
        "system audit outbox publisher is not wired",
        reason_code="publisher_not_wired",
    )


__all__ = [
    "SystemAuditOutboxPublisherUnavailable",
    "get_system_audit_outbox_dispatcher",
]
