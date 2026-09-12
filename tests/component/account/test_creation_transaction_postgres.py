"""Actual user-lock contention and rollback at the public creation boundary."""

from copy import deepcopy

import pytest
from django.db import connections, transaction

from apps.simulated_trading.application.canonical_account_creation_row import (
    CanonicalAccountCreationRowUnavailable,
)
from apps.simulated_trading.creation_composition import build_simulated_account_creation_stages
from apps.simulated_trading.creation_transaction_composition import account_creation_transaction
from apps.simulated_trading.infrastructure.models import SimulatedAccountModel
from tests.component.account.test_account_actor_authority_raw_source_publisher_postgres import (
    _new_user,
)
from tests.component.account.test_canonical_account_creation_row_postgres import _command
from tests.unit.simulated_trading.test_creation_composition import _settings

pytest_plugins = ("tests.component.account.test_current_account_ownership_postgres",)


def _reject_default(execute, sql, params, many, context):
    raise AssertionError("creation transaction queried default alias")


def test_same_user_serializes_different_users_do_not_and_lock_releases(ownership_alias):
    alias = ownership_alias
    user, _ = _new_user(alias)
    other_user, _ = _new_user(alias, username="independent-creation-user")
    competitor = "evid07_creation_transaction_competitor"
    assert competitor not in connections.databases
    connections.databases[competitor] = deepcopy(connections.databases[alias])
    try:
        with connections[competitor].cursor() as cursor:
            cursor.execute("SET lock_timeout = '250ms'")
        with connections["default"].execute_wrapper(_reject_default):
            with account_creation_transaction(using=alias, user_id=user.pk):
                with pytest.raises(CanonicalAccountCreationRowUnavailable) as caught:
                    with account_creation_transaction(using=competitor, user_id=user.pk):
                        pytest.fail("competing transaction acquired the held user row")
                database_error = caught.value.__cause__
                assert getattr(database_error.__cause__, "sqlstate", None) == "55P03"
                with account_creation_transaction(using=competitor, user_id=other_user.pk):
                    assert connections[competitor].in_atomic_block
            with account_creation_transaction(using=competitor, user_id=user.pk):
                assert connections[competitor].in_atomic_block
    finally:
        connections[competitor].close()
        connections.databases.pop(competitor, None)


def test_creation_body_failure_rolls_back_actual_row_and_allows_retry(ownership_alias):
    alias = ownership_alias
    user, _ = _new_user(alias)
    stages = build_simulated_account_creation_stages(using=alias, settings=_settings())
    with connections["default"].execute_wrapper(_reject_default):
        with pytest.raises(RuntimeError, match="abort creation body"):
            with account_creation_transaction(using=alias, user_id=user.pk):
                stages.row_writer.execute(_command(user.pk))
                raise RuntimeError("abort creation body")
        assert SimulatedAccountModel.objects.using(alias).count() == 0
        with account_creation_transaction(using=alias, user_id=user.pk):
            result = stages.row_writer.execute(_command(user.pk))
        assert (
            SimulatedAccountModel.objects.using(alias).get(pk=result.account.account_id).user_id
            == user.pk
        )


def test_missing_inactive_and_wrong_isolation_reject_before_yield(ownership_alias):
    alias = ownership_alias
    user, _ = _new_user(alias)
    user.is_active = False
    user.save(using=alias, update_fields=["is_active"])
    for user_id in (user.pk, user.pk + 1000000):
        with pytest.raises(CanonicalAccountCreationRowUnavailable):
            with account_creation_transaction(using=alias, user_id=user_id):
                pytest.fail("unavailable user entered creation body")
    user.is_active = True
    user.save(using=alias, update_fields=["is_active"])
    with transaction.atomic(using=alias):
        with connections[alias].cursor() as cursor:
            cursor.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ")
        with pytest.raises(CanonicalAccountCreationRowUnavailable, match="READ COMMITTED"):
            with account_creation_transaction(using=alias, user_id=user.pk):
                pytest.fail("wrong isolation entered creation body")
