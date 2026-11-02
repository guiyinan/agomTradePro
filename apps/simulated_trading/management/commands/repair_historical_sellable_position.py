"""Apply or roll back one explicitly selected native simulated sellable row."""

from __future__ import annotations

import argparse
import json
from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Literal, cast

from django.core.management.base import BaseCommand, CommandError
from django.db import connections

from apps.simulated_trading.application.execution_settlement_uow import (
    SimulatedTradeExecutionBlocked,
)
from apps.simulated_trading.application.historical_sellable_repair import (
    HistoricalSellableRepairCommand,
    HistoricalSellableRepairResult,
)
from apps.simulated_trading.historical_sellable_repair_composition import (
    build_historical_sellable_repair_service,
)
from core.exceptions import InvalidInputError


class Command(BaseCommand):
    """Perform one locked, idempotent, append-only G5 correction operation."""

    help = (
        "Apply or roll back one simulated Position correction. Apply requires the exact "
        "cutoff, proof hash, and stored available state from one read-only report."
    )

    def add_arguments(self, parser: argparse.ArgumentParser) -> None:
        """Require exact owner, simulated account, Position, actor and operation key."""

        parser.add_argument("--action", choices=("apply", "rollback"), required=True)
        parser.add_argument("--user-id", type=int, required=True)
        parser.add_argument("--simulated-account-id", type=int, required=True)
        parser.add_argument("--target-position-id", type=int, required=True)
        parser.add_argument("--actor-user-id", type=int, required=True)
        parser.add_argument("--idempotency-key", required=True)
        parser.add_argument("--apply-event-id", type=int)
        parser.add_argument(
            "--preview-evidence-cutoff-at",
            type=_parse_aware_datetime,
            help="Exact evidence cutoff copied from the read-only report; required for apply.",
        )
        parser.add_argument(
            "--preview-evidence-proof-hash",
            help="Exact evidence proof hash copied from the same report; required for apply.",
        )
        parser.add_argument(
            "--preview-available-quantity",
            type=_parse_decimal_quantity,
            help="Exact stored available quantity copied from the same report; required for apply.",
        )
        parser.add_argument(
            "--preview-available-quantity-known",
            type=_parse_boolean,
            help="Stored available-known flag copied from the same report; required for apply.",
        )
        parser.add_argument("--database", default="default")

    def handle(self, *args: object, **options: object) -> None:
        """Run only the explicitly selected owner operation and print its receipt."""

        del args
        action = options.get("action")
        user_id = options.get("user_id")
        account_id = options.get("simulated_account_id")
        target_position_id = options.get("target_position_id")
        actor_user_id = options.get("actor_user_id")
        idempotency_key = options.get("idempotency_key")
        apply_event_id = options.get("apply_event_id")
        database_alias = options.get("database")
        preview_cutoff = options.get("preview_evidence_cutoff_at")
        preview_hash = options.get("preview_evidence_proof_hash")
        preview_quantity = options.get("preview_available_quantity")
        preview_known = options.get("preview_available_quantity_known")
        if action not in ("apply", "rollback"):
            raise CommandError("--action must be apply or rollback")
        for option_name, value in (
            ("--user-id", user_id),
            ("--simulated-account-id", account_id),
            ("--target-position-id", target_position_id),
            ("--actor-user-id", actor_user_id),
        ):
            if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
                raise CommandError(f"{option_name} must be a positive integer")
        if not isinstance(idempotency_key, str) or not idempotency_key.strip():
            raise CommandError("--idempotency-key must be nonempty")
        if len(idempotency_key) > 128:
            raise CommandError("--idempotency-key exceeds 128 characters")
        if not isinstance(database_alias, str) or not database_alias.strip():
            raise CommandError("--database must name a configured database alias")
        if database_alias != database_alias.strip() or database_alias not in connections.databases:
            raise CommandError("--database must be an exact configured database alias")
        if action == "apply" and apply_event_id is not None:
            raise CommandError("--apply-event-id is only used with --action rollback")
        if action == "rollback" and (
            not isinstance(apply_event_id, int)
            or isinstance(apply_event_id, bool)
            or apply_event_id <= 0
        ):
            raise CommandError("rollback requires a positive --apply-event-id")
        if action == "apply" and (
            type(preview_cutoff) is not datetime
            or type(preview_hash) is not str
            or type(preview_quantity) is not Decimal
            or type(preview_known) is not bool
        ):
            raise CommandError("apply requires all four values from one read-only preview")
        if action == "rollback" and any(
            value is not None
            for value in (preview_cutoff, preview_hash, preview_quantity, preview_known)
        ):
            raise CommandError("preview values apply only to --action apply")

        command = HistoricalSellableRepairCommand(
            action=cast(Literal["apply", "rollback"], action),
            user_id=cast(int, user_id),
            account_id=cast(int, account_id),
            target_position_id=cast(int, target_position_id),
            actor_user_id=cast(int, actor_user_id),
            idempotency_key=idempotency_key,
            apply_event_id=(cast(int, apply_event_id) if action == "rollback" else None),
            preview_evidence_cutoff_at=cast(datetime | None, preview_cutoff),
            preview_evidence_proof_hash=cast(str | None, preview_hash),
            preview_available_quantity=cast(Decimal | None, preview_quantity),
            preview_available_quantity_known=cast(bool | None, preview_known),
        )
        try:
            result = build_historical_sellable_repair_service().execute(
                command=command,
                database_alias=database_alias,
            )
        except (InvalidInputError, SimulatedTradeExecutionBlocked) as error:
            code = getattr(error, "code", None)
            prefix = f"{code}: " if isinstance(code, str) and code else ""
            raise CommandError(f"{prefix}{error}") from error
        self.stdout.write(json.dumps(_serialize_result(result), ensure_ascii=False, sort_keys=True))


def _serialize_result(result: HistoricalSellableRepairResult) -> dict[str, object]:
    """Return a bounded receipt without exposing plan or provider evidence payloads."""

    return {
        "schema": "ash03.historical_sellable_repair_result.v1",
        "action": result.action,
        "outcome": result.outcome,
        "journal_event_id": result.journal_event_id,
        "apply_event_id": result.apply_event_id,
        "owner_user_id": result.user_id,
        "account_id": result.account_id,
        "source_scope": "simulated_position",
        "source_position_id": None,
        "position_mapping_id": None,
        "target_position_id": result.target_position_id,
        "before_available_quantity": str(result.before_available_quantity),
        "before_available_quantity_known": result.before_available_quantity_known,
        "after_available_quantity": str(result.after_available_quantity),
        "after_available_quantity_known": result.after_available_quantity_known,
        "evidence_cutoff_at": result.evidence_cutoff_at.isoformat(),
        "evidence_proof_hash": result.evidence_proof_hash,
        "must_not_execute": True,
    }


def _parse_aware_datetime(value: str) -> datetime:
    """Parse only an ISO timestamp with an explicit timezone offset."""

    normalized = f"{value[:-1]}+00:00" if value.endswith("Z") else value
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError as error:
        raise argparse.ArgumentTypeError("timestamp must be ISO 8601") from error
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise argparse.ArgumentTypeError("timestamp must include a timezone offset")
    return parsed


def _parse_decimal_quantity(value: str) -> Decimal:
    """Parse an exact decimal share quantity without routing through float."""

    try:
        return Decimal(value)
    except InvalidOperation as error:
        raise argparse.ArgumentTypeError("quantity must be an exact Decimal") from error


def _parse_boolean(value: str) -> bool:
    """Parse one explicit true/false preview flag."""

    normalized = value.lower()
    if normalized == "true":
        return True
    if normalized == "false":
        return False
    raise argparse.ArgumentTypeError("value must be true or false")
