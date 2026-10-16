"""Alias-bound storage for immutable, exact-case simulated FeeConfig versions."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta
from decimal import Decimal
from math import isfinite
from typing import cast

from django.db import DatabaseError, connections, transaction
from django.db.backends.base.base import BaseDatabaseWrapper
from django.db.models import F, QuerySet
from django.utils.connection import ConnectionDoesNotExist

from apps.simulated_trading.application.fee_policy_v2 import (
    FeePolicyVersionCommand,
    FeePolicyVersionConflict,
    FeePolicyVersionStorageUnavailable,
)
from apps.simulated_trading.domain.execution_fee_policy_v2 import (
    FeePolicyAccountScope,
    FeeTransactionCase,
    FeeTransactionCaseUnavailable,
    SimulatedFeePolicyV2,
)
from apps.simulated_trading.domain.execution_settlement_uow import (
    ExecutionFeeSchedule,
    FeeCalculationPurpose,
    FeeRateStoragePrecision,
    FeeRoundingPolicy,
    SimulatedSettlementContractError,
    SimulatedTradeSide,
)
from apps.simulated_trading.infrastructure.models import (
    FeeConfigModel,
    SimulatedAccountModel,
)

_FEE_RATE_FIELDS: tuple[str, ...] = (
    "commission_rate_buy",
    "commission_rate_sell",
    "min_commission",
    "stamp_duty_rate",
    "transfer_fee_rate",
    "min_transfer_fee",
    "slippage_rate",
)
_FEE_SNAPSHOT_PRECISION = FeeRateStoragePrecision.DATABASE_BINARY64
_FEE_SNAPSHOT_PURPOSE = FeeCalculationPurpose.NORMAL_SIM_ESTIMATED
_FEE_SNAPSHOT_ROUNDING = FeeRoundingPolicy.COMPONENT_HALF_EVEN_CENTS_V1


def _stored_binary64(value: object, field_name: str) -> Decimal:
    """Preserve one persisted finite FloatField value without decimal re-authoring."""

    if type(value) is not float or not isfinite(value):
        raise FeePolicyVersionStorageUnavailable(
            f"persisted FeeConfig {field_name} is not a finite binary64 value"
        )
    return Decimal.from_float(value)


def _command_rate(value: float, field_name: str) -> Decimal:
    """Convert an explicitly supplied FloatField input to its exact binary64 value."""

    try:
        converted = float(value)
    except OverflowError as error:
        raise FeePolicyVersionConflict(
            f"FeeConfig {field_name} cannot be represented as binary64"
        ) from error
    if not isfinite(converted):
        raise FeePolicyVersionConflict(f"FeeConfig {field_name} is not finite")
    return Decimal.from_float(converted)


class DjangoFeePolicyV2Repository:
    """Create immutable exact-case FeeConfig rows and read them by exact scope."""

    def __init__(self, *, using: str) -> None:
        """Bind every fee-policy operation to one explicit database alias."""

        if type(using) is not str or not using or using.strip() != using:
            raise FeePolicyVersionStorageUnavailable("database alias must be explicit")
        self._using = using

    def create_fee_policy_version(self, command: FeePolicyVersionCommand) -> SimulatedFeePolicyV2:
        """Create one complete row or return an exact same-identity retry."""

        if type(command) is not FeePolicyVersionCommand:
            raise FeePolicyVersionConflict("fee policy command has an invalid type")
        try:
            FeePolicyVersionCommand.__post_init__(command)
        except (ArithmeticError, AttributeError, TypeError, ValueError) as error:
            raise FeePolicyVersionConflict("fee policy command failed validation") from error

        connection = self._connection()
        if connection.in_atomic_block or not connection.get_autocommit():
            raise FeePolicyVersionStorageUnavailable(
                "fee policy writer requires its own outer transaction"
            )
        try:
            with transaction.atomic(using=self._using):
                self._establish_write_fence(connection)
                self._acquire_policy_locks(connection, command)
                identity_row = (
                    FeeConfigModel._base_manager.using(self._using)
                    .filter(
                        fee_policy_id=command.policy_id,
                        fee_policy_version=command.policy_version,
                    )
                    .first()
                )
                if identity_row is not None:
                    existing = self._decode_model(identity_row)
                    if self._matches_command(identity_row, existing, command):
                        return existing
                    raise FeePolicyVersionConflict(
                        "one policy identity/version cannot be rewritten with new content"
                    )

                name_row = (
                    FeeConfigModel._base_manager.using(self._using)
                    .filter(config_name=command.config_name)
                    .first()
                )
                if name_row is not None:
                    raise FeePolicyVersionConflict(
                        "config_name is already bound to another FeeConfig row"
                    )
                self._reject_overlapping_cases(command)
                row = FeeConfigModel(
                    config_name=command.config_name,
                    asset_type=command.asset_type,
                    commission_rate_buy=float(command.commission_rate_buy),
                    commission_rate_sell=float(command.commission_rate_sell),
                    min_commission=float(command.min_commission),
                    stamp_duty_rate=float(command.stamp_duty_rate),
                    transfer_fee_rate=float(command.transfer_fee_rate),
                    min_transfer_fee=float(command.min_transfer_fee),
                    slippage_rate=float(command.slippage_rate),
                    is_default=False,
                    is_active=False,
                    description=command.description,
                )
                row.save(using=self._using, force_insert=True)
                row.refresh_from_db(using=self._using)
                if type(row.pk) is not int or type(row.created_at) is not datetime:
                    raise FeePolicyVersionStorageUnavailable(
                        "database did not return the created FeeConfig identity and clock"
                    )
                schedule = self._schedule_from_model(row)
                policy = SimulatedFeePolicyV2(
                    fee_schedule_v1=schedule,
                    policy_id=command.policy_id,
                    policy_version=command.policy_version,
                    account_scope=command.account_scope,
                    effective_from=command.effective_from,
                    valid_until=command.valid_until,
                    recorded_at=row.created_at,
                    transaction_cases=command.transaction_cases,
                )
                self._finalize_new_shell(row=row, policy=policy)
                return policy
        except FeePolicyVersionConflict:
            raise
        except FeePolicyVersionStorageUnavailable:
            raise
        except DatabaseError as error:
            raise FeePolicyVersionStorageUnavailable(
                "database could not serialize or persist this fee policy version"
            ) from error
        except (ArithmeticError, AttributeError, TypeError, ValueError) as error:
            raise FeePolicyVersionStorageUnavailable(
                "persisted fee policy row failed exact validation"
            ) from error

    def get_execution_fee_policy(
        self,
        *,
        account_id: int,
        user_id: int,
        asset_type: str,
        market: str,
        board: str,
        side: SimulatedTradeSide,
        as_of: datetime,
    ) -> SimulatedFeePolicyV2 | None:
        """Return one exact active policy after account, row, and hash validation."""

        if (
            type(account_id) is not int
            or account_id <= 0
            or type(user_id) is not int
            or user_id <= 0
            or type(as_of) is not datetime
            or as_of.tzinfo is None
            or type(side) is not SimulatedTradeSide
        ):
            raise FeePolicyVersionStorageUnavailable("fee policy read scope is invalid")
        self._connection()
        try:
            if as_of.utcoffset() is None:
                raise FeePolicyVersionStorageUnavailable("fee policy read cutoff is not aware")
        except (OverflowError, TypeError, ValueError) as error:
            raise FeePolicyVersionStorageUnavailable(
                "fee policy read cutoff is not aware"
            ) from error
        if any(
            type(value) is not str
            or not value
            or value.strip() != value
            or any(character.isspace() for character in value)
            for value in (asset_type, market, board)
        ):
            raise FeePolicyVersionStorageUnavailable("fee policy transaction scope is invalid")
        account_exists = (
            SimulatedAccountModel._base_manager.using(self._using)
            .filter(
                pk=account_id,
                user_id=user_id,
                account_type="simulated",
            )
            .exists()
        )
        if not account_exists:
            raise FeePolicyVersionStorageUnavailable(
                "fee policy read is outside the exact simulated-account owner scope"
            )

        rows = list(
            FeeConfigModel._base_manager.using(self._using)
            .filter(
                fee_policy_id__isnull=False,
                fee_policy_effective_from__lte=as_of,
                fee_policy_valid_until__gt=as_of,
                created_at__lte=as_of,
            )
            .order_by("fee_policy_id", "fee_policy_version", "pk")
        )
        matches: list[SimulatedFeePolicyV2] = []
        for row in rows:
            policy = self._decode_model(row)
            try:
                policy.validate_at(as_of)
                policy.case_for(
                    asset_type=asset_type,
                    market=market,
                    board=board,
                    side=side,
                    as_of=as_of,
                )
            except FeeTransactionCaseUnavailable:
                continue
            except SimulatedSettlementContractError as error:
                raise FeePolicyVersionStorageUnavailable(
                    "effective FeeConfig row failed policy integrity validation"
                ) from error
            matches.append(policy)
        if len(matches) > 1:
            raise FeePolicyVersionStorageUnavailable(
                "multiple active exact fee policies match one transaction"
            )
        return matches[0] if matches else None

    def _establish_write_fence(self, connection: BaseDatabaseWrapper) -> None:
        """Take an alias-local write reservation before SQLite overlap reads."""

        vendor = getattr(connection, "vendor", None)
        if vendor == "sqlite":
            query: QuerySet[FeeConfigModel] = FeeConfigModel._base_manager.using(
                self._using
            ).filter(pk__lt=0)
            query.update(id=F("id"))
            return
        if vendor == "postgresql":
            self._configure_postgresql_fence(connection)
            return
        raise FeePolicyVersionStorageUnavailable(
            "fee policy writes support only SQLite or PostgreSQL databases"
        )

    def _connection(self) -> BaseDatabaseWrapper:
        """Resolve this configured alias and translate only a missing-alias failure."""

        try:
            return connections[self._using]
        except ConnectionDoesNotExist as error:
            raise FeePolicyVersionStorageUnavailable("database alias is not configured") from error

    def _configure_postgresql_fence(self, connection: BaseDatabaseWrapper) -> None:
        """Require READ COMMITTED and retain stricter configured lock timeouts."""

        with connection.cursor() as cursor:
            cursor.execute("SHOW transaction_isolation")
            isolation_row = cursor.fetchone()
            if isolation_row is None or isolation_row[0] != "read committed":
                raise FeePolicyVersionStorageUnavailable(
                    "fee policy writer requires PostgreSQL READ COMMITTED isolation"
                )
            cursor.execute("SELECT current_setting('lock_timeout')::interval")
            timeout_row = cursor.fetchone()
            if timeout_row is None or type(timeout_row[0]) is not timedelta:
                raise FeePolicyVersionStorageUnavailable(
                    "PostgreSQL lock timeout could not be read"
                )
            configured_timeout = timeout_row[0]
            if configured_timeout == timedelta(0) or configured_timeout > timedelta(seconds=2):
                cursor.execute("SET LOCAL lock_timeout = '2s'")

    def _acquire_policy_locks(
        self,
        connection: BaseDatabaseWrapper,
        command: FeePolicyVersionCommand,
    ) -> None:
        """Acquire deterministic PostgreSQL identity and exact-case advisory locks."""

        if getattr(connection, "vendor", None) != "postgresql":
            return
        lock_material: set[str] = {
            json.dumps(
                ["fee-policy-identity-v2", command.policy_id, command.policy_version],
                separators=(",", ":"),
                ensure_ascii=True,
            )
        }
        for case in command.transaction_cases:
            lock_material.add(
                json.dumps(
                    ["fee-policy-case-v2", *case.key],
                    separators=(",", ":"),
                    ensure_ascii=True,
                )
            )
        with connection.cursor() as cursor:
            for material in sorted(lock_material):
                digest = hashlib.sha256(material.encode("ascii")).digest()[:8]
                cursor.execute("SELECT pg_advisory_xact_lock(%s)", [_signed_bigint(digest)])

    def _reject_overlapping_cases(self, command: FeePolicyVersionCommand) -> None:
        """Reject overlapping windows that share any exact transaction tuple."""

        candidate_keys = {case.key for case in command.transaction_cases}
        rows = list(
            FeeConfigModel._base_manager.using(self._using)
            .filter(
                fee_policy_id__isnull=False,
                fee_policy_effective_from__lt=command.valid_until,
                fee_policy_valid_until__gt=command.effective_from,
            )
            .order_by("fee_policy_id", "fee_policy_version", "pk")
        )
        for row in rows:
            existing = self._decode_model(row)
            if (
                existing.effective_from < command.valid_until
                and command.effective_from < existing.valid_until
                and candidate_keys.intersection(case.key for case in existing.transaction_cases)
            ):
                raise FeePolicyVersionConflict(
                    "exact fee transaction cases cannot overlap in effective time"
                )

    def _decode_model(self, row: FeeConfigModel) -> SimulatedFeePolicyV2:
        """Rebuild the complete typed policy from persisted row values and verify hash."""

        required = (
            row.fee_policy_id,
            row.fee_policy_version,
            row.fee_policy_account_scope,
            row.fee_policy_effective_from,
            row.fee_policy_valid_until,
            row.fee_policy_transaction_cases,
            row.fee_policy_content_hash,
            row.created_at,
        )
        if any(value is None for value in required) or type(row.pk) is not int:
            raise FeePolicyVersionStorageUnavailable("strict FeeConfig row is incomplete")
        if type(row.fee_policy_transaction_cases) is not list:
            raise FeePolicyVersionStorageUnavailable("strict FeeConfig cases are not a JSON array")
        try:
            cases = tuple(
                FeeTransactionCase.from_payload(case)
                for case in cast(list[object], row.fee_policy_transaction_cases)
            )
            policy = SimulatedFeePolicyV2(
                fee_schedule_v1=self._schedule_from_model(row),
                policy_id=cast(str, row.fee_policy_id),
                policy_version=cast(int, row.fee_policy_version),
                account_scope=FeePolicyAccountScope(cast(str, row.fee_policy_account_scope)),
                effective_from=cast(datetime, row.fee_policy_effective_from),
                valid_until=cast(datetime, row.fee_policy_valid_until),
                recorded_at=row.created_at,
                transaction_cases=cases,
                content_hash=cast(str, row.fee_policy_content_hash),
            )
        except (ArithmeticError, TypeError, ValueError) as error:
            raise FeePolicyVersionStorageUnavailable(
                "strict FeeConfig row failed canonical hash or schema validation"
            ) from error
        if policy.fee_schedule_v1.config_id != row.pk:
            raise FeePolicyVersionStorageUnavailable("V1 schedule identity differs from FeeConfig")
        return policy

    def _schedule_from_model(self, row: FeeConfigModel) -> ExecutionFeeSchedule:
        """Build the immutable V1 numeric schedule from the exact stored binary64 values."""

        if type(row.pk) is not int or row.pk <= 0:
            raise FeePolicyVersionStorageUnavailable("FeeConfig row has no positive identity")
        return ExecutionFeeSchedule(
            config_id=row.pk,
            asset_type=row.asset_type,
            commission_rate_buy=_stored_binary64(row.commission_rate_buy, "commission_rate_buy"),
            commission_rate_sell=_stored_binary64(row.commission_rate_sell, "commission_rate_sell"),
            min_commission=_stored_binary64(row.min_commission, "min_commission"),
            stamp_duty_rate=_stored_binary64(row.stamp_duty_rate, "stamp_duty_rate"),
            transfer_fee_rate=_stored_binary64(row.transfer_fee_rate, "transfer_fee_rate"),
            min_transfer_fee=_stored_binary64(row.min_transfer_fee, "min_transfer_fee"),
            slippage_rate=_stored_binary64(row.slippage_rate, "slippage_rate"),
            precision_basis=_FEE_SNAPSHOT_PRECISION,
            calculation_purpose=_FEE_SNAPSHOT_PURPOSE,
            rounding_policy=_FEE_SNAPSHOT_ROUNDING,
        )

    def _matches_command(
        self,
        row: FeeConfigModel,
        existing: SimulatedFeePolicyV2,
        command: FeePolicyVersionCommand,
    ) -> bool:
        """Compare exact immutable policy content while ignoring retry timestamp."""

        schedule = existing.fee_schedule_v1
        expected_rates = tuple(
            _command_rate(getattr(command, field_name), field_name)
            for field_name in _FEE_RATE_FIELDS
        )
        existing_rates = tuple(getattr(schedule, field_name) for field_name in _FEE_RATE_FIELDS)
        return (
            row.config_name == command.config_name
            and row.description == command.description
            and row.asset_type == command.asset_type
            and existing.policy_id == command.policy_id
            and existing.policy_version == command.policy_version
            and existing.account_scope is command.account_scope
            and existing.effective_from == command.effective_from
            and existing.valid_until == command.valid_until
            and existing.transaction_cases == command.transaction_cases
            and all(
                stored == requested
                for stored, requested in zip(existing_rates, expected_rates, strict=True)
            )
        )

    def _finalize_new_shell(
        self,
        *,
        row: FeeConfigModel,
        policy: SimulatedFeePolicyV2,
    ) -> None:
        """Write strict metadata only onto the uncommitted shell created in this call."""

        if row.fee_policy_id is not None:
            raise FeePolicyVersionStorageUnavailable("only a newly created shell can be finalized")
        new_shell: QuerySet[FeeConfigModel] = FeeConfigModel._base_manager.using(
            self._using
        ).filter(
            pk=row.pk,
            fee_policy_id__isnull=True,
        )
        changed = new_shell.update(
            fee_policy_id=policy.policy_id,
            fee_policy_version=policy.policy_version,
            fee_policy_account_scope=policy.account_scope.value,
            fee_policy_effective_from=policy.effective_from,
            fee_policy_valid_until=policy.valid_until,
            fee_policy_transaction_cases=[case.to_payload() for case in policy.transaction_cases],
            fee_policy_content_hash=policy.content_hash,
        )
        if changed != 1:
            raise FeePolicyVersionStorageUnavailable("new FeeConfig shell was not finalized")


def _signed_bigint(value: bytes) -> int:
    """Convert eight stable hash bytes to PostgreSQL's signed advisory-key domain."""

    return int.from_bytes(value, byteorder="big", signed=True)


__all__: tuple[str, ...] = ("DjangoFeePolicyV2Repository",)
