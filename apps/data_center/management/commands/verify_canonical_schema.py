"""Verify the canonical Data Center schema before a deployment is released."""

from __future__ import annotations

import json
from typing import Any

from django.core.management.base import BaseCommand, CommandError, CommandParser
from django.db import connection
from django.db.migrations.recorder import MigrationRecorder

from apps.data_center.infrastructure.canonical_schema_contract import (
    build_canonical_schema_report,
)


class Command(BaseCommand):
    """Fail closed when canonical control-plane schema is incomplete."""

    help = "Verify canonical Data Center tables and migration markers."

    def add_arguments(self, parser: CommandParser) -> None:
        """Register machine-readable output mode."""

        parser.add_argument("--json", action="store_true", dest="as_json")

    def handle(self, *args: Any, **options: Any) -> None:
        """Inspect the live database and emit a deterministic schema report."""

        del args
        applied_migrations = MigrationRecorder.Migration._default_manager.filter(
            app="data_center"
        ).values_list("name", flat=True)
        report = build_canonical_schema_report(
            connection.introspection.table_names(),
            applied_migrations,
        )
        payload = {
            "ok": not any(report.values()),
            **report,
        }
        if bool(options.get("as_json")):
            self.stdout.write(json.dumps(payload, ensure_ascii=True, sort_keys=True))
        else:
            self.stdout.write(
                "canonical_control_plane_missing=" + ",".join(report["missing_tables"])
            )
            self.stdout.write(
                "canonical_migration_missing=" + ",".join(report["missing_migrations"])
            )
        if not payload["ok"]:
            raise CommandError("canonical_data_center_schema_incomplete")
