"""Prove existing creation UOWs can share a real outer PostgreSQL transaction."""

import pytest
from django.db import connections, transaction

from apps.account.infrastructure.allocated_physical_account_row_observation_v3_repository import (
    DjangoAllocatedPhysicalAccountRowObservationV3Repository,
)
from apps.account.infrastructure.canonical_account_creation_consumption_repository import (
    DjangoCanonicalAccountCreationConsumptionRepository,
)
from tests.component.account.test_account_actor_authority_raw_source_publisher_postgres import (
    evid06_alias as evid06_alias,
)


def test_creation_uows_share_outer_commit_rollback_and_remain_reusable(evid06_alias: str):
    connection = connections[evid06_alias]
    physical = DjangoAllocatedPhysicalAccountRowObservationV3Repository(using=evid06_alias)
    consumption = DjangoCanonicalAccountCreationConsumptionRepository(using=evid06_alias)
    with connection.cursor() as cursor:
        cursor.execute("CREATE TEMP TABLE evid07_uow_probe (stage integer NOT NULL)")
    try:
        with pytest.raises(RuntimeError, match="abort outer creation"):
            with transaction.atomic(using=evid06_alias):
                with physical.atomic():
                    with connection.cursor() as cursor:
                        cursor.execute("INSERT INTO evid07_uow_probe VALUES (1)")
                with consumption.atomic():
                    with connection.cursor() as cursor:
                        cursor.execute("INSERT INTO evid07_uow_probe VALUES (2)")
                with connection.cursor() as cursor:
                    cursor.execute("SELECT count(*) FROM evid07_uow_probe")
                    assert cursor.fetchone()[0] == 2
                raise RuntimeError("abort outer creation")
        with connection.cursor() as cursor:
            cursor.execute("SELECT count(*) FROM evid07_uow_probe")
            assert cursor.fetchone()[0] == 0
        with transaction.atomic(using=evid06_alias):
            with physical.atomic():
                with connection.cursor() as cursor:
                    cursor.execute("INSERT INTO evid07_uow_probe VALUES (3)")
            with consumption.atomic():
                with connection.cursor() as cursor:
                    cursor.execute("INSERT INTO evid07_uow_probe VALUES (4)")
        with connection.cursor() as cursor:
            cursor.execute("SELECT stage FROM evid07_uow_probe ORDER BY stage")
            assert cursor.fetchall() == [(3,), (4,)]
    finally:
        with connection.cursor() as cursor:
            cursor.execute("DROP TABLE evid07_uow_probe")
