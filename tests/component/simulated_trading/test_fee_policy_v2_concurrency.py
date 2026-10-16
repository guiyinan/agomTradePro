"""Verify exact fee-policy identities and case overlap on real PostgreSQL."""

from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from threading import Barrier

import pytest
from django.db import close_old_connections, connection, connections

from apps.simulated_trading.application.fee_policy_v2 import (
    FeePolicyVersionCommand,
    FeePolicyVersionConflict,
)
from apps.simulated_trading.infrastructure.fee_policy_v2_repository import (
    DjangoFeePolicyV2Repository,
)
from apps.simulated_trading.infrastructure.models import FeeConfigModel
from tests.component.simulated_trading.test_fee_policy_v2_repository import _command
from tests.support.isolated_schema import isolated_schema

pytestmark = pytest.mark.django_db(transaction=True, available_apps=["apps.simulated_trading"])


@pytest.fixture(autouse=True)
def _schema() -> Iterator[None]:
    if connection.vendor != "postgresql":
        pytest.skip("fee-policy writer races require two real PostgreSQL connections")
    with isolated_schema((FeeConfigModel,)):
        yield


def _race(
    commands: tuple[FeePolicyVersionCommand, FeePolicyVersionCommand],
) -> list[tuple[str, str, int]]:
    rendezvous = Barrier(2, timeout=10)

    def write(command: FeePolicyVersionCommand) -> tuple[str, str, int]:
        close_old_connections()
        try:
            with connections["default"].cursor() as cursor:
                cursor.execute("SET statement_timeout = '10000ms'")
                cursor.execute("SELECT pg_backend_pid()")
                row = cursor.fetchone()
                assert row is not None
                backend_pid = int(row[0])
            rendezvous.wait()
            try:
                policy = DjangoFeePolicyV2Repository(using="default").create_fee_policy_version(
                    command
                )
            except FeePolicyVersionConflict:
                return "conflict", command.policy_id, backend_pid
            return "accepted", policy.content_hash, backend_pid
        finally:
            connections["default"].close()

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [executor.submit(write, command) for command in commands]
        results = [future.result(timeout=20) for future in futures]
    assert len({pid for _, _, pid in results}) == 2
    return results


def test_concurrent_identical_policy_creation_returns_one_immutable_version() -> None:
    """An exact retry returns the same sealed row and its original recorded time."""

    command = _command()
    results = _race((command, command))

    assert [status for status, _, _ in results] == ["accepted", "accepted"]
    assert len({content_hash for _, content_hash, _ in results}) == 1
    assert FeeConfigModel.objects.count() == 1
    row = FeeConfigModel.objects.get()
    assert row.fee_policy_id == command.policy_id
    assert row.fee_policy_content_hash == results[0][1]
    assert row.is_default is False
    assert row.is_active is False
    original_recorded_at = row.created_at
    replay = DjangoFeePolicyV2Repository(using="default").create_fee_policy_version(command)
    assert replay.recorded_at == original_recorded_at
    assert replay.content_hash == row.fee_policy_content_hash
    assert FeeConfigModel.objects.count() == 1


def test_concurrent_overlapping_cases_cannot_publish_two_policy_identities() -> None:
    """Different identities sharing one case/window must serialize and conflict."""

    first = _command()
    second = replace(first, policy_id="second-racing-policy", config_name="second-racing-config")
    results = _race((first, second))

    assert sorted(status for status, _, _ in results) == ["accepted", "conflict"]
    assert FeeConfigModel.objects.count() == 1
    row = FeeConfigModel.objects.get()
    loser = next(identity for status, identity, _ in results if status == "conflict")
    winner_hash = next(value for status, value, _ in results if status == "accepted")
    assert row.fee_policy_id in {first.policy_id, second.policy_id}
    assert row.fee_policy_id != loser
    assert row.fee_policy_content_hash == winner_hash
    assert row.fee_policy_transaction_cases == [first.transaction_cases[0].to_payload()]
