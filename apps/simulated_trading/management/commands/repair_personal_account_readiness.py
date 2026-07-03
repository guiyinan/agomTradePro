"""Repair account prerequisites for personal readiness evidence."""

from __future__ import annotations

import json
from decimal import Decimal, InvalidOperation
from typing import Any

from django.core.management.base import BaseCommand, CommandError

from apps.simulated_trading.application.readiness_services import (
    AccountReadinessRepairRequest,
    repair_personal_account_readiness,
)


class Command(BaseCommand):
    help = "Ensure personal readiness runs have at least one positive-equity account."

    def add_arguments(self, parser) -> None:
        parser.add_argument("--user-id", type=int, default=None, help="Repair one user.")
        parser.add_argument(
            "--account-id",
            type=int,
            default=None,
            help="Use users owning this account as the target scope.",
        )
        parser.add_argument(
            "--initial-capital",
            default="1000000.00",
            help="Initial cash for created readiness simulated accounts.",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Only report missing decision-ready accounts.",
        )
        parser.add_argument(
            "--json",
            action="store_true",
            dest="print_json",
            help="Print full JSON result.",
        )

    def handle(self, *args: Any, **options: Any) -> None:
        initial_capital = _parse_capital(options["initial_capital"])
        payload = repair_personal_account_readiness(
            AccountReadinessRepairRequest(
                user_id=options.get("user_id"),
                account_id=options.get("account_id"),
                initial_capital=initial_capital,
                dry_run=bool(options.get("dry_run")),
            )
        )
        if options.get("print_json"):
            self.stdout.write(json.dumps(payload, ensure_ascii=False, indent=2))
            return

        self.stdout.write(
            self.style.SUCCESS(
                "Personal account readiness checked: "
                f"status={payload['status']}, targets={payload['target_count']}"
            )
        )
        for result in payload["results"]:
            self.stdout.write(
                "  user={user_id} status={status} ready={ready} zero={zero} created={created}".format(
                    user_id=result["user_id"],
                    status=result["status"],
                    ready=result["decision_ready_account_ids"],
                    zero=result["zero_equity_account_ids"],
                    created=result["created_account_id"],
                )
            )


def _parse_capital(value: Any) -> Decimal:
    try:
        capital = Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise CommandError("initial-capital must be a positive decimal") from exc
    if capital <= 0:
        raise CommandError("initial-capital must be positive")
    return capital
