"""Preview or execute the fail-closed decision-runtime activation workflow."""

from __future__ import annotations

import json
from typing import Any

from django.core.management.base import BaseCommand, CommandError, CommandParser

from apps.config_center.application.decision_runtime_activation import (
    DecisionRuntimeActivationError,
    make_decision_runtime_activation_use_case,
)


class Command(BaseCommand):
    """Expose candidate-bound activation without allowing a bare active write."""

    help = (
        "Preview strict decision readiness; use --execute with operator and release "
        "identities for compare-and-set activation plus automatic re-blocking."
    )

    def add_arguments(self, parser: CommandParser) -> None:
        """Register dry-run-first activation arguments."""

        parser.add_argument("--execute", action="store_true")
        parser.add_argument("--operator", default="")
        parser.add_argument("--release-ref", required=True)

    def handle(self, *args: object, **options: Any) -> None:
        """Run preflight or the guarded activation transition."""

        del args
        execute = bool(options.get("execute", False))
        operator = str(options.get("operator") or "")
        release_ref = str(options.get("release_ref") or "")
        if execute and not operator.strip():
            raise CommandError("--operator is required with --execute")
        if not execute and operator.strip():
            raise CommandError("--operator is accepted only together with --execute")

        use_case = make_decision_runtime_activation_use_case()
        try:
            if execute:
                result = use_case.execute(
                    release_ref=release_ref,
                    changed_by=operator,
                )
                payload = {"mode": "execute", **result.to_dict()}
            else:
                preview = use_case.preview(release_ref=release_ref)
                payload = {"mode": "dry_run", **preview.to_dict()}
        except (DecisionRuntimeActivationError, TypeError, ValueError) as exc:
            raise CommandError(str(exc)) from exc

        self.stdout.write(
            json.dumps(
                payload,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            )
        )
        if execute and not bool(payload.get("activated")):
            raise CommandError("activation verification failed; runtime was re-blocked")
