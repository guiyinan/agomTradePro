"""Composition provider for read-only Data Center task lease evidence."""

from shared.domain.task_lease_evidence import DomainTaskLeaseProbeProtocol


def get_data_center_task_orphan_lease_probe() -> DomainTaskLeaseProbeProtocol:
    """Return the Data Center-owned lease probe through its public application boundary."""

    from apps.data_center.infrastructure.task_monitor_lease_probe import (
        DjangoDataCenterTaskLeaseProbe,
    )

    return DjangoDataCenterTaskLeaseProbe()
