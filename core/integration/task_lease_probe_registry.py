"""Process-local registry for read-only domain task lease probes."""

from __future__ import annotations

from threading import RLock

from shared.domain.task_lease_evidence import DomainTaskLeaseProbeProtocol

_LOCK = RLock()
_PROBES: dict[str, DomainTaskLeaseProbeProtocol] = {}


def register_domain_task_lease_probe(
    name: str,
    probe: DomainTaskLeaseProbeProtocol,
) -> None:
    """Register or replace one named domain-owned lease probe."""

    if not name or not name.isidentifier():
        raise ValueError("task lease probe name must be a non-empty identifier")
    with _LOCK:
        _PROBES[name] = probe


def get_domain_task_lease_probes() -> tuple[DomainTaskLeaseProbeProtocol, ...]:
    """Return a stable snapshot of registered probes for read-only inspection."""

    with _LOCK:
        return tuple(_PROBES[name] for name in sorted(_PROBES))


__all__ = ["get_domain_task_lease_probes", "register_domain_task_lease_probe"]
