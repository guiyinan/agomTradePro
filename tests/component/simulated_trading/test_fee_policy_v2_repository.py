"""Targeted database tests for immutable exact-case simulated fee policies."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import connections, models, transaction

from apps.account.infrastructure.identity_models import AccountProfileModel
from apps.simulated_trading.application.fee_policy_v2 import (
    FeePolicyVersionCommand,
    FeePolicyVersionConflict,
    FeePolicyVersionStorageUnavailable,
)
from apps.simulated_trading.domain.execution_fee_policy_v2 import (
    FeeApplicability,
    FeePolicyAccountScope,
    FeeTransactionCase,
    FeeTransactionCaseUnavailable,
)
from apps.simulated_trading.domain.execution_settlement_uow import SimulatedTradeSide
from apps.simulated_trading.infrastructure.fee_policy_v2_repository import (
    DjangoFeePolicyV2Repository,
)
from apps.simulated_trading.infrastructure.models import FeeConfigModel, SimulatedAccountModel
from tests.support.isolated_schema import isolated_schema

pytestmark = pytest.mark.django_db(
    transaction=True,
    available_apps=[
        "apps.simulated_trading",
        "django.contrib.auth",
        "django.contrib.contenttypes",
    ],
)


def _case(
    *,
    asset_type: str = "fund",
    market: str = "BJ",
    board: str = "STAR",
    side: SimulatedTradeSide = SimulatedTradeSide.BUY,
) -> FeeTransactionCase:
    """Build one exact transaction case with every component declared."""

    return FeeTransactionCase(
        asset_type=asset_type,
        market=market,
        board=board,
        side=side,
        commission=FeeApplicability.APPLIES,
        transfer_fee=FeeApplicability.NOT_APPLICABLE,
        stamp_duty=FeeApplicability.NOT_APPLICABLE,
        slippage=FeeApplicability.APPLIES,
    )


def _command(
    *,
    policy_id: str = "test-policy",
    policy_version: int = 1,
    config_name: str = "test-policy-v1",
    case: FeeTransactionCase | None = None,
    effective_from: datetime | None = None,
    valid_until: datetime | None = None,
    commission_rate_buy: float = 0.0003,
) -> FeePolicyVersionCommand:
    """Create one explicitly rated exact-case command around a current test clock."""

    now = datetime.now(UTC)
    return FeePolicyVersionCommand(
        config_name=config_name,
        asset_type="all",
        commission_rate_buy=commission_rate_buy,
        commission_rate_sell=0.0004,
        min_commission=5.0,
        stamp_duty_rate=0.001,
        transfer_fee_rate=0.00002,
        min_transfer_fee=0.0,
        slippage_rate=0.001,
        policy_id=policy_id,
        policy_version=policy_version,
        account_scope=FeePolicyAccountScope.ALL_SIMULATED_ACCOUNTS,
        effective_from=effective_from or now - timedelta(days=1),
        valid_until=valid_until or now + timedelta(days=10),
        transaction_cases=(case or _case(),),
        description="explicitly configured test policy",
    )


@pytest.fixture
def account_scope() -> object:
    """Create only the authentication/profile/account tables this repository reads."""

    user_model = get_user_model()
    with isolated_schema((user_model, AccountProfileModel, SimulatedAccountModel, FeeConfigModel)):
        user = user_model.objects.create_user(username="fee-policy-owner", password="unused")
        account = SimulatedAccountModel.objects.create(
            user=user,
            account_name="fee-policy-account",
            account_type="simulated",
            initial_capital=Decimal("10000.00"),
            current_cash=Decimal("10000.00"),
            current_market_value=Decimal("0.00"),
            total_value=Decimal("10000.00"),
            is_active=True,
        )
        yield user, account


def test_repository_creates_binary64_policy_and_reads_exact_case(account_scope: object) -> None:
    user, account = account_scope
    command = _command()
    repository = DjangoFeePolicyV2Repository(using="default")

    policy = repository.create_fee_policy_version(command)
    read_policy = repository.get_execution_fee_policy(
        account_id=account.pk,
        user_id=user.pk,
        asset_type="fund",
        market="BJ",
        board="STAR",
        side=SimulatedTradeSide.BUY,
        as_of=datetime.now(UTC),
    )

    row = FeeConfigModel.objects.get(pk=policy.fee_schedule_v1.config_id)
    assert read_policy == policy
    assert policy.fee_schedule_v1.commission_rate_buy == Decimal.from_float(row.commission_rate_buy)
    assert row.is_default is False
    assert row.is_active is False
    assert row.fee_policy_content_hash == policy.content_hash
    assert row.fee_policy_transaction_cases == [command.transaction_cases[0].to_payload()]


def test_repository_same_identity_and_same_binary64_content_is_idempotent(
    account_scope: object,
) -> None:
    repository = DjangoFeePolicyV2Repository(using="default")
    command = _command()

    first = repository.create_fee_policy_version(command)
    retry = repository.create_fee_policy_version(command)

    assert retry == first
    assert FeeConfigModel.objects.count() == 1
    assert retry.recorded_at == first.recorded_at
    assert retry.fee_schedule_v1.content_hash == first.fee_schedule_v1.content_hash


def test_repository_rejects_rewriting_an_existing_identity(account_scope: object) -> None:
    repository = DjangoFeePolicyV2Repository(using="default")
    command = _command()
    repository.create_fee_policy_version(command)

    changed = _command(commission_rate_buy=0.00031)
    with pytest.raises(FeePolicyVersionConflict):
        repository.create_fee_policy_version(changed)

    assert FeeConfigModel.objects.count() == 1


def test_repository_rejects_exact_case_overlap_but_allows_adjacent_window(
    account_scope: object,
) -> None:
    repository = DjangoFeePolicyV2Repository(using="default")
    now = datetime.now(UTC)
    first_until = now + timedelta(days=3)
    repository.create_fee_policy_version(
        _command(effective_from=now - timedelta(days=1), valid_until=first_until)
    )

    with pytest.raises(FeePolicyVersionConflict):
        repository.create_fee_policy_version(
            _command(
                policy_id="different-policy",
                config_name="different-overlap",
                effective_from=first_until - timedelta(seconds=1),
                valid_until=first_until + timedelta(days=2),
            )
        )

    adjacent = repository.create_fee_policy_version(
        _command(
            policy_id="adjacent-policy",
            config_name="adjacent-version",
            effective_from=first_until,
            valid_until=first_until + timedelta(days=2),
        )
    )
    assert adjacent.effective_from == first_until
    assert FeeConfigModel.objects.count() == 2


def test_repository_allows_overlapping_windows_for_disjoint_exact_cases(
    account_scope: object,
) -> None:
    repository = DjangoFeePolicyV2Repository(using="default")
    now = datetime.now(UTC)
    end = now + timedelta(days=5)
    repository.create_fee_policy_version(_command(effective_from=now, valid_until=end))

    other_case = _case(asset_type="equity", market="SH", board="MAIN")
    other = repository.create_fee_policy_version(
        _command(
            policy_id="other-case-policy",
            config_name="other-case-config",
            case=other_case,
            effective_from=now,
            valid_until=end,
        )
    )

    assert other.transaction_cases == (other_case,)
    assert FeeConfigModel.objects.count() == 2


def test_repository_does_not_fall_back_for_unmatched_case_or_foreign_account(
    account_scope: object,
) -> None:
    user, account = account_scope
    repository = DjangoFeePolicyV2Repository(using="default")
    repository.create_fee_policy_version(_command())

    unmatched = repository.get_execution_fee_policy(
        account_id=account.pk,
        user_id=user.pk,
        asset_type="equity",
        market="BJ",
        board="STAR",
        side=SimulatedTradeSide.BUY,
        as_of=datetime.now(UTC),
    )
    assert unmatched is None

    with pytest.raises(FeePolicyVersionStorageUnavailable):
        repository.get_execution_fee_policy(
            account_id=account.pk,
            user_id=user.pk + 1,
            asset_type="fund",
            market="BJ",
            board="STAR",
            side=SimulatedTradeSide.BUY,
            as_of=datetime.now(UTC),
        )


def test_repository_ignores_legacy_null_policy_rows(account_scope: object) -> None:
    user, account = account_scope
    FeeConfigModel.objects.create(
        config_name="legacy-fee-config",
        asset_type="equity",
        commission_rate_buy=0.0003,
        commission_rate_sell=0.0003,
        min_commission=5.0,
        is_default=False,
        is_active=True,
    )

    policy = DjangoFeePolicyV2Repository(using="default").get_execution_fee_policy(
        account_id=account.pk,
        user_id=user.pk,
        asset_type="equity",
        market="SH",
        board="MAIN",
        side=SimulatedTradeSide.BUY,
        as_of=datetime.now(UTC),
    )

    assert policy is None


def test_repository_blocks_caller_owned_transaction(account_scope: object) -> None:
    repository = DjangoFeePolicyV2Repository(using="default")

    with transaction.atomic():
        with pytest.raises(FeePolicyVersionStorageUnavailable):
            repository.create_fee_policy_version(_command())


def test_repository_blocks_manually_disabled_autocommit_without_writing(
    account_scope: object,
) -> None:
    repository = DjangoFeePolicyV2Repository(using="default")
    database_connection = connections["default"]
    original_autocommit = database_connection.get_autocommit()
    assert original_autocommit

    database_connection.set_autocommit(False)
    try:
        with pytest.raises(FeePolicyVersionStorageUnavailable):
            repository.create_fee_policy_version(_command())
    finally:
        database_connection.rollback()
        database_connection.set_autocommit(original_autocommit)

    assert FeeConfigModel.objects.count() == 0


def test_strict_feeconfig_rejects_model_and_queryset_mutation(account_scope: object) -> None:
    policy = DjangoFeePolicyV2Repository(using="default").create_fee_policy_version(_command())
    row = FeeConfigModel.objects.get(pk=policy.fee_schedule_v1.config_id)

    row.commission_rate_buy = 0.25
    with pytest.raises(ValidationError):
        row.save()
    with pytest.raises(ValidationError):
        FeeConfigModel.objects.filter(pk=row.pk).update(commission_rate_buy=0.25)
    with pytest.raises(ValidationError):
        FeeConfigModel.objects.filter(pk=row.pk).delete()
    with pytest.raises(ValidationError):
        row.delete()


def test_repository_detects_a_raw_mutated_case_payload(account_scope: object) -> None:
    user, account = account_scope
    repository = DjangoFeePolicyV2Repository(using="default")
    policy = repository.create_fee_policy_version(_command())
    query = FeeConfigModel._base_manager.filter(pk=policy.fee_schedule_v1.config_id)
    models.QuerySet.update(query, fee_policy_transaction_cases=[])

    with pytest.raises(FeePolicyVersionStorageUnavailable):
        repository.get_execution_fee_policy(
            account_id=account.pk,
            user_id=user.pk,
            asset_type="fund",
            market="BJ",
            board="STAR",
            side=SimulatedTradeSide.BUY,
            as_of=datetime.now(UTC),
        )


def test_repository_does_not_make_future_known_policy_visible(account_scope: object) -> None:
    user, account = account_scope
    repository = DjangoFeePolicyV2Repository(using="default")
    policy = repository.create_fee_policy_version(_command())

    result = repository.get_execution_fee_policy(
        account_id=account.pk,
        user_id=user.pk,
        asset_type="fund",
        market="BJ",
        board="STAR",
        side=SimulatedTradeSide.BUY,
        as_of=policy.recorded_at - timedelta(microseconds=1),
    )

    assert result is None


def test_repository_rejects_identity_rows_with_damaged_hash(account_scope: object) -> None:
    repository = DjangoFeePolicyV2Repository(using="default")
    policy = repository.create_fee_policy_version(_command())
    query = FeeConfigModel._base_manager.filter(pk=policy.fee_schedule_v1.config_id)
    models.QuerySet.update(query, fee_policy_content_hash="0" * 64)

    with pytest.raises(FeePolicyVersionStorageUnavailable):
        repository.create_fee_policy_version(_command())


def test_v2_payload_reader_rejects_duplicate_cases_in_persisted_json(
    account_scope: object,
) -> None:
    user, account = account_scope
    repository = DjangoFeePolicyV2Repository(using="default")
    policy = repository.create_fee_policy_version(_command())
    duplicate_case = policy.transaction_cases[0].to_payload()
    query = FeeConfigModel._base_manager.filter(pk=policy.fee_schedule_v1.config_id)
    models.QuerySet.update(
        query,
        fee_policy_transaction_cases=[duplicate_case, duplicate_case],
    )

    with pytest.raises(FeePolicyVersionStorageUnavailable):
        repository.get_execution_fee_policy(
            account_id=account.pk,
            user_id=user.pk,
            asset_type="fund",
            market="BJ",
            board="STAR",
            side=SimulatedTradeSide.BUY,
            as_of=datetime.now(UTC),
        )


def test_fee_case_unavailable_is_a_stable_business_subtype() -> None:
    assert issubclass(FeeTransactionCaseUnavailable, ValueError)


def _manifest(command: FeePolicyVersionCommand) -> dict[str, object]:
    """Serialize one command using the operator-facing strict JSON schema."""

    return {
        "schema": "simulated-fee-policy-command.v1",
        "config_name": command.config_name,
        "asset_type": command.asset_type,
        "commission_rate_buy": command.commission_rate_buy,
        "commission_rate_sell": command.commission_rate_sell,
        "min_commission": command.min_commission,
        "stamp_duty_rate": command.stamp_duty_rate,
        "transfer_fee_rate": command.transfer_fee_rate,
        "min_transfer_fee": command.min_transfer_fee,
        "slippage_rate": command.slippage_rate,
        "policy_id": command.policy_id,
        "policy_version": command.policy_version,
        "account_scope": command.account_scope.value,
        "effective_from": command.effective_from.isoformat(),
        "valid_until": command.valid_until.isoformat(),
        "transaction_cases": [case.to_payload() for case in command.transaction_cases],
        "description": command.description,
    }


def test_command_preview_then_apply_and_exact_replay(
    account_scope: object,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    command = _command()
    manifest_path = tmp_path / "fee-policy.json"
    manifest_path.write_text(json.dumps(_manifest(command)), encoding="utf-8")

    call_command(
        "create_simulated_fee_policy_v2",
        manifest=str(manifest_path),
        database="default",
    )
    assert FeeConfigModel.objects.count() == 0
    assert "does not check the database or write rows" in capsys.readouterr().out

    call_command(
        "create_simulated_fee_policy_v2",
        manifest=str(manifest_path),
        database="default",
        apply=True,
    )
    first = FeeConfigModel.objects.get(config_name=command.config_name)
    call_command(
        "create_simulated_fee_policy_v2",
        manifest=str(manifest_path),
        database="default",
        apply=True,
    )

    assert FeeConfigModel.objects.count() == 1
    assert FeeConfigModel.objects.get(pk=first.pk).fee_policy_content_hash == (
        first.fee_policy_content_hash
    )


def test_command_rejects_invalid_manifest_without_writing(
    account_scope: object,
    tmp_path: Path,
) -> None:
    command = _command()
    manifest = _manifest(command)
    manifest["commission_rate_buy"] = 10**1000
    manifest_path = tmp_path / "invalid-fee-policy.json"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    with pytest.raises(CommandError):
        call_command(
            "create_simulated_fee_policy_v2",
            manifest=str(manifest_path),
            database="default",
            apply=True,
        )

    assert FeeConfigModel.objects.count() == 0


def test_command_rejects_unconfigured_database_alias_without_writing(
    account_scope: object,
    tmp_path: Path,
) -> None:
    command = _command()
    manifest_path = tmp_path / "fee-policy.json"
    manifest_path.write_text(json.dumps(_manifest(command)), encoding="utf-8")
    database_alias = "fee_policy_alias_must_not_exist"
    assert database_alias not in connections.databases

    with pytest.raises(CommandError, match="database alias is not configured"):
        call_command(
            "create_simulated_fee_policy_v2",
            manifest=str(manifest_path),
            database=database_alias,
            apply=True,
        )

    assert FeeConfigModel.objects.count() == 0
