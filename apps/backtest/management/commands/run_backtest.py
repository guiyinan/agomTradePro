"""Run a persisted backtest through the canonical Application use case."""

from __future__ import annotations

import json
from datetime import date
from typing import Any

from django.core.management.base import BaseCommand, CommandError, CommandParser

from apps.backtest.application.interface_services import run_backtest_payload


class Command(BaseCommand):
    """Execute the same governed backtest path used by HTTP interfaces."""

    help = "Run a persisted backtest without synthetic price or regime fallbacks."

    def add_arguments(self, parser: CommandParser) -> None:
        """Register an explicit, bounded exploratory backtest contract."""

        parser.add_argument("--start", required=True, help="Start date (YYYY-MM-DD)")
        parser.add_argument("--end", required=True, help="End date (YYYY-MM-DD)")
        parser.add_argument("--name", default="CLI Backtest", help="Persisted run name")
        parser.add_argument("--capital", type=float, default=100000.0)
        parser.add_argument(
            "--frequency",
            choices=("monthly", "quarterly", "yearly"),
            default="monthly",
        )
        parser.add_argument("--pit", action="store_true", dest="use_pit_data")
        parser.add_argument(
            "--data-manifest-id",
            default="",
            help="Required canonical PIT manifest when --pit is enabled",
        )
        parser.add_argument(
            "--decision-snapshot-id",
            default="",
            help="Required decision snapshot when --pit is enabled",
        )
        parser.add_argument("--transaction-cost-bps", type=float, default=10.0)
        parser.add_argument("--json", action="store_true", dest="as_json")

    def handle(self, *args: str, **options: Any) -> None:
        """Validate CLI input and invoke the Backtest Application facade."""

        del args
        start_date = self._parse_date(options.get("start"), "backtest_start_date_invalid")
        end_date = self._parse_date(options.get("end"), "backtest_end_date_invalid")
        if start_date >= end_date:
            raise CommandError("backtest_date_range_invalid")
        name = str(options.get("name") or "").strip()
        if not name or len(name) > 200:
            raise CommandError("backtest_name_invalid")
        if not isinstance(options.get("use_pit_data", False), bool):
            raise CommandError("backtest_pit_option_invalid")
        if not isinstance(options.get("as_json", False), bool):
            raise CommandError("backtest_json_option_invalid")
        use_pit_data = bool(options.get("use_pit_data", False))
        data_manifest_id = str(options.get("data_manifest_id") or "").strip()
        decision_snapshot_id = str(options.get("decision_snapshot_id") or "").strip()
        if use_pit_data and (not data_manifest_id or not decision_snapshot_id):
            raise CommandError("backtest_pit_evidence_required")

        response = run_backtest_payload(
            {
                "name": name,
                "start_date": start_date,
                "end_date": end_date,
                "initial_capital": options.get("capital"),
                "rebalance_frequency": str(options.get("frequency") or "monthly"),
                "use_pit_data": use_pit_data,
                "transaction_cost_bps": options.get("transaction_cost_bps"),
                "trust_status": "pit_verified" if use_pit_data else "exploratory",
                "data_manifest_id": data_manifest_id or None,
                "decision_snapshot_id": decision_snapshot_id or None,
            },
            user_id=None,
        )
        payload = {
            "backtest_id": response.backtest_id,
            "status": response.status,
            "result": response.result,
            "errors": list(response.errors),
            "warnings": list(response.warnings),
            "audit_status": response.audit_status,
            "audit_report_id": response.audit_report_id,
        }
        if bool(options.get("as_json", False)):
            self.stdout.write(json.dumps(payload, ensure_ascii=True, sort_keys=True, default=str))
        elif response.status == "completed":
            self.stdout.write(self.style.SUCCESS(f"Backtest completed: id={response.backtest_id}"))
        if response.status != "completed":
            raise CommandError("backtest_execution_failed")

    @staticmethod
    def _parse_date(value: object, error_code: str) -> date:
        """Parse one ISO date without accepting implicit date coercion."""

        if isinstance(value, date):
            return value
        if not isinstance(value, str) or not value.strip():
            raise CommandError(error_code)
        try:
            return date.fromisoformat(value.strip())
        except ValueError as exc:
            raise CommandError(error_code) from exc
