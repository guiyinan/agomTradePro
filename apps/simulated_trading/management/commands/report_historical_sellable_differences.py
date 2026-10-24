"""Emit a read-only, owner-scoped historical quantity difference report."""

from __future__ import annotations

import argparse
import json

from django.core.management.base import BaseCommand, CommandError
from django.db import connections
from django.utils import timezone

from apps.simulated_trading.domain.historical_sellable_difference import (
    HistoricalSellableDifferenceReport,
    HistoricalSellableDifferenceRow,
    format_ledger_quantity,
)
from apps.simulated_trading.historical_sellable_difference_composition import (
    build_historical_sellable_difference_service,
)


class Command(BaseCommand):
    """Print a diagnostic report without writing ledger or mapping rows."""

    help = "Report historical Account-to-Simulated Trading quantity differences (read-only)."

    def add_arguments(self, parser: argparse.ArgumentParser) -> None:
        """Require the operator to select one owner, one account, and one DB alias."""

        parser.add_argument("--user-id", type=int, required=True)
        parser.add_argument("--account-id", type=int, required=True)
        parser.add_argument("--database", default="default")

    def handle(self, *args: object, **options: object) -> None:
        """Build and print exactly one JSON report value."""

        user_id = options.get("user_id")
        account_id = options.get("account_id")
        database_alias = options.get("database")
        if not isinstance(user_id, int) or isinstance(user_id, bool) or user_id <= 0:
            raise CommandError("--user-id must be a positive integer")
        if not isinstance(account_id, int) or isinstance(account_id, bool) or account_id <= 0:
            raise CommandError("--account-id must be a positive integer")
        if not isinstance(database_alias, str) or not database_alias.strip():
            raise CommandError("--database must name a configured database alias")
        if database_alias != database_alias.strip():
            raise CommandError("--database cannot contain surrounding whitespace")
        if database_alias not in connections.databases:
            raise CommandError("--database must name a configured database alias")

        report = build_historical_sellable_difference_service().build_report(
            user_id=user_id,
            account_id=account_id,
            database_alias=database_alias,
            reported_at=timezone.now(),
        )
        self.stdout.write(json.dumps(_serialize_report(report), ensure_ascii=False, sort_keys=True))


def _serialize_report(report: HistoricalSellableDifferenceReport) -> dict[str, object]:
    """Convert the typed report to the stable JSON contract with Decimal strings."""

    return {
        "report_kind": "ash03.historical_sellable_difference.v1",
        "read_only": True,
        "must_not_execute": True,
        "must_not_use_for_decision": True,
        "repair_ready": False,
        "settled": False,
        "consistent_snapshot": False,
        "source_database_alias": report.database_alias,
        "target_database_alias": report.database_alias,
        "reported_at": report.reported_at.isoformat(),
        "source_observed_at": None,
        "owner_user_id": report.user_id,
        "account_id": report.account_id,
        "portfolio_mapping_id": report.portfolio_mapping_id,
        "scope_status": report.scope_status,
        "reason_codes": list(report.reason_codes),
        "rows": [_serialize_row(row) for row in report.rows],
    }


def _serialize_row(row: HistoricalSellableDifferenceRow) -> dict[str, object]:
    """Serialize one source/target row without exposing foreign position values."""

    return {
        "portfolio_id": row.portfolio_id,
        "source_position_id": row.source_position_id,
        "asset_code": (
            row.source_asset_code if row.source_asset_code is not None else row.target_asset_code
        ),
        "position_mapping_id": row.position_mapping_id,
        "mapping_target_table": row.mapping_target_table,
        "mapping_target_id": row.mapping_target_id,
        "target_position_id": row.target_position_id,
        "source_asset_code": row.source_asset_code,
        "target_asset_code": row.target_asset_code,
        "source_total_quantity": format_ledger_quantity(row.source_total_quantity),
        "source_quantity_known": row.source_quantity_known,
        "source_quantity_reason_code": row.source_quantity_reason_code,
        "source_position_closed": row.source_position_closed,
        "source_observed_at": None,
        "legacy_record_updated_at": (
            row.legacy_record_updated_at.isoformat()
            if row.legacy_record_updated_at is not None
            else None
        ),
        "target_total_quantity": format_ledger_quantity(row.target_total_quantity),
        "stored_available_quantity": format_ledger_quantity(row.stored_available_quantity),
        "stored_available_quantity_known": row.stored_available_quantity_known,
        "total_quantity_difference": format_ledger_quantity(row.total_quantity_difference),
        "supported_sellable_quantity": None,
        "requires_reconciliation": row.requires_reconciliation,
        "reason_codes": list(row.reason_codes),
    }
