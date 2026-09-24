"""Activate an explicit reviewed history-volume rule file through Config Center."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from django.core.management.base import BaseCommand, CommandParser

from apps.data_center.infrastructure.tencent_history_units import (
    TENCENT_HISTORY_VOLUME_KEY,
    parse_history_volume_rules,
)
from core.integration.config_center_runtime import (
    RuntimeConfigDefinitionSpec,
    activate_runtime_profile_patch,
    register_runtime_definitions,
)


class Command(BaseCommand):
    help = "Validate Tencent unit rules; --apply creates an audited runtime profile revision."

    def add_arguments(self, parser: CommandParser) -> None:
        """Require an explicit rule file and audit identity."""
        parser.add_argument("--rules", required=True)
        parser.add_argument("--environment", required=True)
        parser.add_argument("--actor", required=True)
        parser.add_argument("--reason", required=True)
        parser.add_argument("--apply", action="store_true")

    def handle(self, *args: Any, **options: Any) -> None:
        """Validate first, then optionally activate just this key preserving other settings."""
        rules = parse_history_volume_rules(Path(str(options["rules"])).read_text(encoding="utf-8"))
        if options["apply"]:
            register_runtime_definitions(
                (
                    RuntimeConfigDefinitionSpec(
                        key=TENCENT_HISTORY_VOLUME_KEY,
                        namespace="data_center",
                        owner_app="data_center",
                        value_type="string",
                        criticality="critical",
                        description="Tencent historical volume multiplier by code prefix.exchange; JSON object",
                    ),
                )
            )
            profile = activate_runtime_profile_patch(
                environment=str(options["environment"]),
                patch={TENCENT_HISTORY_VOLUME_KEY: json.dumps(rules)},
                bootstrap_values=None,
                actor=str(options["actor"]),
                reason=str(options["reason"]),
            )
            self.stdout.write(f"Activated profile {profile['profile_id']}")
        self.stdout.write(json.dumps({"applied": bool(options["apply"]), "rules": rules}))
