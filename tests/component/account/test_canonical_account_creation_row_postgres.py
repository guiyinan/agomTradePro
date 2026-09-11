"""Actual new-only account writes and savepoint rollback on local PostgreSQL."""

from datetime import UTC, date, datetime

import pytest
from django.db import connections, transaction
from django.utils import timezone

from apps.simulated_trading.application.canonical_account_creation_row import (
    CanonicalAccountCreationRowCommand,
    CanonicalAccountCreationRowCorruption,
    CanonicalAccountCreationRowUnavailable,
)
from apps.simulated_trading.domain.entities import AccountType, SimulatedAccount
from apps.simulated_trading.infrastructure.canonical_account_creation_row_writer import (
    DjangoCanonicalAccountCreationRowWriter,
)
from apps.simulated_trading.infrastructure.models import SimulatedAccountModel
from tests.component.account.test_account_actor_authority_raw_source_publisher_postgres import (
    _new_user,
)

pytest_plugins = ("tests.component.account.test_current_account_ownership_postgres",)


def _command(user_id: int) -> CanonicalAccountCreationRowCommand:
    return CanonicalAccountCreationRowCommand(
        requester_user_id=user_id,
        account=SimulatedAccount(
            account_id=0,
            account_name="actual local creation",
            account_type=AccountType.SIMULATED,
            initial_capital=100.25,
            current_cash=100.25,
            current_market_value=0.0,
            total_value=100.25,
            start_date=date(2000, 1, 1),
            auto_trading_enabled=False,
        ),
        observation_id="local-canonical-create-row",
        mutation_version="local-create-v1",
    )


def _reject_default(execute, sql, params, many, context):
    raise AssertionError("new-account writer queried the default database")


def test_new_row_preserves_actual_database_facts_and_outer_rollback(ownership_alias):
    alias = ownership_alias
    user, _ = _new_user(alias)
    command = _command(user.pk)
    writer = DjangoCanonicalAccountCreationRowWriter(using=alias)
    with connections["default"].execute_wrapper(_reject_default):
        with pytest.raises(CanonicalAccountCreationRowUnavailable):
            writer.execute(command)
        assert SimulatedAccountModel.objects.using(alias).count() == 0
        with transaction.atomic(using=alias):
            result = writer.execute(command)
            row = SimulatedAccountModel.objects.using(alias).get(pk=result.account.account_id)
            assert row.user_id == user.pk == result.mutation.row_user_id
            assert result.mutation.row_pk == row.pk
            assert result.mutation.raw_account_type == row.account_type == "simulated"
            assert result.mutation.is_active == row.is_active
            assert result.mutation.row_created_at == row.created_at
            assert result.mutation.row_updated_at == row.updated_at
            assert result.mutation.observed_at >= row.updated_at >= row.created_at
            assert result.mutation.observation_id == command.observation_id
            assert result.mutation.mutation_version == command.mutation_version
            assert result.account.start_date == row.start_date != command.account.start_date
            assert result.account.initial_capital == float(row.initial_capital) == 100.25
            assert not row.auto_trading_enabled and not result.account.auto_trading_enabled
            transaction.set_rollback(True, using=alias)
        assert SimulatedAccountModel.objects.using(alias).count() == 0

        user.is_active = False
        user.save(using=alias, update_fields=["is_active"])
        with transaction.atomic(using=alias):
            with pytest.raises(CanonicalAccountCreationRowUnavailable):
                writer.execute(command)
            assert SimulatedAccountModel.objects.using(alias).count() == 0
        user.is_active = True
        user.save(using=alias, update_fields=["is_active"])
        with transaction.atomic(using=alias):
            with pytest.raises(CanonicalAccountCreationRowUnavailable):
                writer.execute(_command(user.pk + 1000000))
            assert SimulatedAccountModel.objects.using(alias).count() == 0

        with transaction.atomic(using=alias):
            committed = writer.execute(command)
        assert (
            SimulatedAccountModel.objects.using(alias).get(pk=committed.account.account_id).user_id
            == user.pk
        )
        assert SimulatedAccountModel.objects.using(alias).count() == 1


def test_observation_failure_rolls_back_insert_even_when_caller_commits(ownership_alias):
    alias = ownership_alias
    user, _ = _new_user(alias)
    inserted = []

    class ClockInvalidAfterInsert:
        def now(self) -> datetime:
            if SimulatedAccountModel.objects.using(alias).exists():
                return datetime(1970, 1, 1, tzinfo=UTC)
            return timezone.now()

    def record_insert(execute, sql, params, many, context):
        result = execute(sql, params, many, context)
        if sql.lstrip().upper().startswith('INSERT INTO "SIMULATED_ACCOUNT"'):
            inserted.append(True)
        return result

    writer = DjangoCanonicalAccountCreationRowWriter(using=alias, clock=ClockInvalidAfterInsert())
    with (
        connections["default"].execute_wrapper(_reject_default),
        connections[alias].execute_wrapper(record_insert),
    ):
        with transaction.atomic(using=alias):
            with pytest.raises(CanonicalAccountCreationRowCorruption):
                writer.execute(_command(user.pk))
            assert inserted == [True]
            assert not transaction.get_rollback(using=alias)
            assert SimulatedAccountModel.objects.using(alias).count() == 0
        assert SimulatedAccountModel.objects.using(alias).count() == 0
