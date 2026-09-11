"""Actual PostgreSQL coverage for the cross-app live physical row port."""

import pytest
from django.db import connections, transaction

from apps.account.application.owner_tenant_authority_v2_contracts import (
    CurrentOwnerPhysicalRow,
    OwnerTenantAuthorityV2Unavailable,
)
from apps.simulated_trading.infrastructure.models import SimulatedAccountModel
from core.integration.owner_tenant_physical_row_v2 import (
    build_simulated_account_owner_physical_row_v2_reader,
)
from tests.component.account.test_current_account_ownership_postgres import _row

pytest_plugins = ("tests.component.account.test_current_account_ownership_postgres",)


def test_cross_app_reader_preserves_live_source_and_exact_alias(ownership_alias):
    row = _row(ownership_alias)
    namespace = "local-simulated-account"
    reader = build_simulated_account_owner_physical_row_v2_reader(
        namespace=namespace, using=ownership_alias
    )
    assert reader.unit_of_work_key == f"django:{ownership_alias}"
    with pytest.raises(OwnerTenantAuthorityV2Unavailable):
        reader.read_locked(namespace=namespace, row_pk=row.pk)

    def reject_default(execute, sql, params, many, context):
        raise AssertionError("cross-app physical port queried the default alias")

    with connections["default"].execute_wrapper(reject_default):
        with transaction.atomic(using=ownership_alias):
            observed = reader.read_locked(namespace=namespace, row_pk=row.pk)
            assert type(observed) is CurrentOwnerPhysicalRow
            assert observed.namespace == namespace and observed.row_pk == row.pk
            assert observed.user_id == row.user_id
            assert observed.raw_account_type == row.account_type
            assert observed.row_created_at == row.created_at
            assert observed.row_updated_at == row.updated_at
            assert observed.observed_at >= observed.row_updated_at
            with pytest.raises(OwnerTenantAuthorityV2Unavailable, match="namespace"):
                reader.read_locked(namespace="different", row_pk=row.pk)
        SimulatedAccountModel._default_manager.using(ownership_alias).filter(pk=row.pk).update(
            user_id=None, is_active=False
        )
        with transaction.atomic(using=ownership_alias):
            current = reader.read_locked(namespace=namespace, row_pk=row.pk)
            assert current.user_id is None and current.is_active is False
            assert reader.read_locked(namespace=namespace, row_pk=row.pk + 1000) is None
