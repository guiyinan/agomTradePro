"""Current owner and inactive-name checks on actual creation rows."""

import pytest
from django.db import connections

from apps.simulated_trading.application.canonical_account_creation_row import (
    CanonicalAccountCreationRowUnavailable,
)
from apps.simulated_trading.creation_composition import build_simulated_account_creation_stages
from apps.simulated_trading.creation_transaction_composition import account_creation_transaction
from apps.simulated_trading.domain.entities import AccountType
from apps.simulated_trading.infrastructure.models import SimulatedAccountModel
from tests.component.account.test_account_actor_authority_raw_source_publisher_postgres import (
    _new_user,
)
from tests.component.account.test_canonical_account_creation_row_postgres import _command
from tests.unit.simulated_trading.test_creation_composition import _settings

pytest_plugins = ("tests.component.account.test_current_account_ownership_postgres",)


def test_creation_reads_use_current_owner_type_active_state_and_owner_scoped_name(ownership_alias):
    alias = ownership_alias
    user, _ = _new_user(alias)
    other, _ = _new_user(alias, username="creation-reader-other")
    stages = build_simulated_account_creation_stages(using=alias, settings=_settings())
    reader = stages.account_reader
    command = _command(user.pk)

    def reject_default(execute, sql, params, many, context):
        raise AssertionError("creation reader queried default alias")

    with connections["default"].execute_wrapper(reject_default):
        with pytest.raises(CanonicalAccountCreationRowUnavailable):
            reader.name_exists(user_id=user.pk, account_name=command.account.account_name)
        with account_creation_transaction(using=alias, user_id=user.pk):
            assert not reader.name_exists(
                user_id=user.pk, account_name=command.account.account_name
            )
            created = stages.row_writer.execute(command)
            account_id = created.account.account_id
            assert reader.name_exists(user_id=user.pk, account_name=command.account.account_name)
            restored = reader.read_owned(
                user_id=user.pk, account_id=account_id, account_type=AccountType.SIMULATED
            )
            assert restored == created.account
            assert (
                reader.read_owned(
                    user_id=user.pk, account_id=account_id, account_type=AccountType.REAL
                )
                is None
            )
            assert (
                reader.read_owned(
                    user_id=user.pk,
                    account_id=account_id + 1000000,
                    account_type=AccountType.SIMULATED,
                )
                is None
            )
        with account_creation_transaction(using=alias, user_id=other.pk):
            assert not reader.name_exists(
                user_id=other.pk, account_name=command.account.account_name
            )
            assert (
                reader.read_owned(
                    user_id=other.pk, account_id=account_id, account_type=AccountType.SIMULATED
                )
                is None
            )
        SimulatedAccountModel.objects.using(alias).filter(pk=account_id).update(user_id=other.pk)
        with account_creation_transaction(using=alias, user_id=user.pk):
            assert (
                reader.read_owned(
                    user_id=user.pk, account_id=account_id, account_type=AccountType.SIMULATED
                )
                is None
            )
        with account_creation_transaction(using=alias, user_id=other.pk):
            assert (
                reader.read_owned(
                    user_id=other.pk, account_id=account_id, account_type=AccountType.SIMULATED
                )
                is not None
            )
        SimulatedAccountModel.objects.using(alias).filter(pk=account_id).update(is_active=False)
        with account_creation_transaction(using=alias, user_id=other.pk):
            assert reader.name_exists(user_id=other.pk, account_name=command.account.account_name)
            assert (
                reader.read_owned(
                    user_id=other.pk, account_id=account_id, account_type=AccountType.SIMULATED
                )
                is None
            )
