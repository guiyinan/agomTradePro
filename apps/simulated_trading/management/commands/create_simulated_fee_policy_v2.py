"""Create one explicit simulated fee-policy version from an operator JSON file."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any, NoReturn, cast

from django.core.management.base import BaseCommand, CommandError, CommandParser

from apps.simulated_trading.application.fee_policy_v2 import (
    FeePolicyVersionCommand,
    FeePolicyVersionConflict,
    FeePolicyVersionInputError,
    FeePolicyVersionStorageUnavailable,
)
from apps.simulated_trading.domain.execution_fee_policy_v2 import (
    FeePolicyAccountScope,
    FeeTransactionCase,
)
from apps.simulated_trading.execution_settlement_composition import (
    build_create_fee_policy_version_use_case,
)
from shared.numeric import safe_float

_COMMAND_SCHEMA = "simulated-fee-policy-command.v1"
_COMMAND_FIELDS = frozenset(
    {
        "schema",
        "config_name",
        "asset_type",
        "commission_rate_buy",
        "commission_rate_sell",
        "min_commission",
        "stamp_duty_rate",
        "transfer_fee_rate",
        "min_transfer_fee",
        "slippage_rate",
        "policy_id",
        "policy_version",
        "account_scope",
        "effective_from",
        "valid_until",
        "transaction_cases",
        "description",
    }
)


class FeePolicyManifestError(ValueError):
    """Raised when the operator file is not a strict V2 fee-policy command."""


class Command(BaseCommand):
    """Preview or explicitly create a fee policy without seeding defaults."""

    help = "Create one exact-case simulated fee policy from an operator-supplied JSON file."

    def add_arguments(self, parser: CommandParser) -> None:
        """Require both the input path and an explicit database alias."""

        parser.add_argument("--manifest", required=True, help="Path to one policy JSON object.")
        parser.add_argument(
            "--database",
            required=True,
            help="Django database alias to write; no default alias is selected implicitly.",
        )
        parser.add_argument(
            "--apply",
            action="store_true",
            help="Persist the validated policy; without this flag the command is preview-only.",
        )

    def handle(self, *args: Any, **options: Any) -> None:
        """Preview input by default; persist only after an explicit apply flag."""

        manifest_path = Path(str(options["manifest"]))
        database_alias = str(options["database"])
        try:
            command = decode_fee_policy_manifest(manifest_path.read_text(encoding="utf-8"))
        except (
            OSError,
            FeePolicyManifestError,
            FeePolicyVersionInputError,
        ) as error:
            raise CommandError(str(error)) from error
        if not options["apply"]:
            self.stdout.write(
                "Preview parsed fee policy manifest: "
                f"policy_id={command.policy_id}, version={command.policy_version}, "
                f"exact_cases={len(command.transaction_cases)}. Preview does not check the database "
                "or write rows; "
                "pass --apply to persist."
            )
            return
        try:
            result = build_create_fee_policy_version_use_case(using=database_alias).execute(command)
        except (
            FeePolicyVersionConflict,
            FeePolicyVersionInputError,
            FeePolicyVersionStorageUnavailable,
        ) as error:
            raise CommandError(str(error)) from error
        self.stdout.write(
            self.style.SUCCESS(
                "Simulated fee policy created or unchanged: "
                f"policy_id={result.policy_id}, version={result.policy_version}, "
                f"content_hash={result.content_hash}. No rates were seeded."
            )
        )


def decode_fee_policy_manifest(text: str) -> FeePolicyVersionCommand:
    """Decode one duplicate-safe JSON object, retaining required binary64 semantics."""

    try:
        payload: object = json.loads(
            text,
            object_pairs_hook=_pairs_to_object,
            parse_constant=_reject_nonfinite,
        )
    except (json.JSONDecodeError, FeePolicyManifestError, ValueError) as error:
        raise FeePolicyManifestError(
            "fee policy JSON is malformed or contains duplicate keys"
        ) from error
    if type(payload) is not dict:
        raise FeePolicyManifestError("fee policy manifest must be a JSON object")
    fields = cast(dict[str, object], payload)
    if set(fields) != _COMMAND_FIELDS or fields["schema"] != _COMMAND_SCHEMA:
        raise FeePolicyManifestError("fee policy manifest has an unknown schema or fields")

    rates: dict[str, float] = {}
    for field_name in (
        "commission_rate_buy",
        "commission_rate_sell",
        "min_commission",
        "stamp_duty_rate",
        "transfer_fee_rate",
        "min_transfer_fee",
        "slippage_rate",
    ):
        value = fields[field_name]
        if type(value) not in (int, float) or isinstance(value, bool):
            raise FeePolicyManifestError(f"{field_name} must be a JSON number")
        parsed = safe_float(value, default=None)
        if parsed is None:
            raise FeePolicyManifestError(f"{field_name} must be a finite representable number")
        rates[field_name] = parsed

    if type(fields["policy_id"]) is not str or type(fields["asset_type"]) is not str:
        raise FeePolicyManifestError("policy_id and asset_type must be strings")
    if type(fields["config_name"]) is not str or type(fields["description"]) is not str:
        raise FeePolicyManifestError("config_name and description must be strings")
    if type(fields["policy_version"]) is not int or type(fields["account_scope"]) is not str:
        raise FeePolicyManifestError("policy_version and account_scope have invalid types")
    if type(fields["effective_from"]) is not str or type(fields["valid_until"]) is not str:
        raise FeePolicyManifestError("policy windows must be ISO-8601 strings")
    if type(fields["transaction_cases"]) is not list:
        raise FeePolicyManifestError("transaction_cases must be a JSON array")
    try:
        return FeePolicyVersionCommand(
            config_name=fields["config_name"],
            asset_type=fields["asset_type"],
            commission_rate_buy=rates["commission_rate_buy"],
            commission_rate_sell=rates["commission_rate_sell"],
            min_commission=rates["min_commission"],
            stamp_duty_rate=rates["stamp_duty_rate"],
            transfer_fee_rate=rates["transfer_fee_rate"],
            min_transfer_fee=rates["min_transfer_fee"],
            slippage_rate=rates["slippage_rate"],
            policy_id=fields["policy_id"],
            policy_version=fields["policy_version"],
            account_scope=FeePolicyAccountScope(fields["account_scope"]),
            effective_from=_parse_aware_datetime(fields["effective_from"], "effective_from"),
            valid_until=_parse_aware_datetime(fields["valid_until"], "valid_until"),
            transaction_cases=tuple(
                FeeTransactionCase.from_payload(case)
                for case in cast(list[object], fields["transaction_cases"])
            ),
            description=fields["description"],
        )
    except (ArithmeticError, TypeError, ValueError) as error:
        if isinstance(error, FeePolicyVersionInputError):
            raise
        raise FeePolicyManifestError(
            "fee policy manifest contains an invalid typed value"
        ) from error


def _parse_aware_datetime(value: object, field_name: str) -> datetime:
    """Parse one timezone-aware ISO timestamp without supplying a default zone."""

    if type(value) is not str:
        raise FeePolicyManifestError(f"{field_name} must be an ISO-8601 string")
    try:
        normalized = f"{value[:-1]}+00:00" if value.endswith("Z") else value
        parsed = datetime.fromisoformat(normalized)
    except ValueError as error:
        raise FeePolicyManifestError(f"{field_name} is not a valid ISO-8601 timestamp") from error
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise FeePolicyManifestError(f"{field_name} must include a UTC offset")
    return parsed


def _pairs_to_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    """Reject duplicate keys at every JSON object depth."""

    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise FeePolicyManifestError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _reject_nonfinite(value: str) -> NoReturn:
    """Reject JSON's non-standard NaN and Infinity numeric spellings."""

    raise FeePolicyManifestError(f"non-finite JSON numeric token is forbidden: {value}")


__all__: tuple[str, ...] = ("Command", "FeePolicyManifestError", "decode_fee_policy_manifest")
