"""Data Center-owned assembly of the exact asset maintenance infrastructure."""

from django.contrib.auth.base_user import AbstractBaseUser

from apps.data_center.application.asset_active_maintenance import (
    AssetActiveMaintenance,
    AssetMaintenanceAuditPort,
    AssetMaintenanceAuthorityPort,
    AssetMaintenanceClock,
    AssetMaintenanceOwnerPort,
)
from apps.data_center.application.sync_transaction import DataCenterSyncAuditWriter
from apps.data_center.infrastructure.asset_active_maintenance import (
    DjangoAssetMasterMaintenanceRepository,
    DjangoAssetMasterMaintenanceSourceReader,
)
from apps.data_center.infrastructure.asset_active_maintenance_owner import (
    DjangoAssetMaintenanceOwnerPort,
)
from apps.data_center.infrastructure.audited_sync_runtime import DjangoDataCenterSyncUnitOfWork


def create_asset_maintenance_owner_port(
    *,
    authenticated_user: AbstractBaseUser,
) -> AssetMaintenanceOwnerPort:
    """Bind current credential and model-permission reads inside Data Center infrastructure."""

    return DjangoAssetMaintenanceOwnerPort(authenticated_user=authenticated_user)


def compose_asset_active_maintenance(
    *,
    owner_port: AssetMaintenanceOwnerPort,
    authority_port: AssetMaintenanceAuthorityPort,
    audit: AssetMaintenanceAuditPort,
    audit_writer: DataCenterSyncAuditWriter,
    clock: AssetMaintenanceClock,
) -> AssetActiveMaintenance:
    """Assemble same-alias repositories and UOW with externally supplied public audit ports."""

    repository = DjangoAssetMasterMaintenanceRepository(using="default")
    source_reader = DjangoAssetMasterMaintenanceSourceReader(using="default")
    unit_of_work = DjangoDataCenterSyncUnitOfWork(
        participants=(repository, source_reader),
        audit_writer=audit_writer,
        using="default",
    )
    return AssetActiveMaintenance(
        source_reader=source_reader,
        owner_port=owner_port,
        authority_port=authority_port,
        repository=repository,
        unit_of_work=unit_of_work,
        audit=audit,
        clock=clock,
    )
