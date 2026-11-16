"""Register or explicitly activate retained statutory body-store settings."""

from __future__ import annotations

from argparse import ArgumentParser
from typing import Any

from django.core.management.base import BaseCommand, CommandError

from apps.data_center.infrastructure.financial_source_body_runtime import (
    STATUTORY_SOURCE_BODY_MAX_BYTES_KEY,
    STATUTORY_SOURCE_BODY_ROOT_KEY,
    parse_statutory_source_body_storage_config,
    statutory_source_body_storage_definitions,
)
from core.exceptions import DataValidationError
from core.integration.config_center_runtime import (
    activate_runtime_profile_patch,
    register_runtime_definitions,
)


class Command(BaseCommand):
    """Register definitions or activate a fully explicit Config Center patch."""

    help = "Register or explicitly activate the retained statutory source body store."

    def add_arguments(self, parser: ArgumentParser) -> None:
        """Expose non-mutating preview, definition registration, and activation options."""

        parser.add_argument(
            "--register",
            action="store_true",
            help="Register the Config Center definitions without activating values.",
        )
        parser.add_argument(
            "--activate",
            action="store_true",
            help="Activate explicit root and body-size values in one runtime profile.",
        )
        parser.add_argument("--environment", default="")
        parser.add_argument("--root", default="")
        parser.add_argument("--max-body-bytes", type=int)
        parser.add_argument("--actor", default="")
        parser.add_argument("--reason", default="")

    def handle(self, *args: Any, **options: Any) -> None:
        """Perform only requested Config Center writes; default operation is preview."""

        del args
        register = options.get("register") is True
        activate = options.get("activate") is True
        if not register and not activate:
            self.stdout.write(
                "statutory source body storage definitions are available; "
                "pass --register or --activate to write"
            )
            return

        activation: tuple[dict[str, object], str, str, str] | None = None
        if activate:
            activation = self._activation_input(options)
        if register or activate:
            saved = register_runtime_definitions(statutory_source_body_storage_definitions())
            self.stdout.write(
                self.style.SUCCESS(
                    "Registered statutory source body storage definitions: " + ", ".join(saved)
                )
            )
        if not activate:
            return
        if activation is None:  # pragma: no cover - guarded by the branch above
            raise CommandError("runtime activation input is unavailable")

        patch, environment, actor, reason = activation
        try:
            evidence = activate_runtime_profile_patch(
                environment=environment,
                patch=patch,
                bootstrap_values=None,
                actor=actor,
                reason=reason,
            )
        except (DataValidationError, OSError, RuntimeError, TypeError, ValueError) as error:
            raise CommandError("statutory source body storage activation failed") from error
        self.stdout.write(
            self.style.SUCCESS(
                f"Activated runtime profile {evidence['profile_key']} "
                f"v{evidence['profile_version']}; snapshot={evidence['snapshot_hash']}"
            )
        )

    @staticmethod
    def _activation_input(
        options: dict[str, object],
    ) -> tuple[dict[str, object], str, str, str]:
        """Validate all operational settings before registering or activating them."""

        environment = _required_option(options, "environment")
        actor = _required_option(options, "actor")
        reason = _required_option(options, "reason")
        root = _required_option(options, "root")
        max_body_bytes = options.get("max_body_bytes")
        try:
            config = parse_statutory_source_body_storage_config(root, max_body_bytes)
        except DataValidationError as error:
            raise CommandError("--root and --max-body-bytes are invalid") from error
        return (
            {
                STATUTORY_SOURCE_BODY_ROOT_KEY: str(config.root),
                STATUTORY_SOURCE_BODY_MAX_BYTES_KEY: config.max_body_bytes,
            },
            environment,
            actor,
            reason,
        )


def _required_option(options: dict[str, object], name: str) -> str:
    """Read one exact non-empty command option without coercing values."""

    value = options.get(name.replace("-", "_"), options.get(name, ""))
    if type(value) is not str or not value.strip() or value != value.strip():
        raise CommandError(f"--{name} is required")
    return value


__all__ = ["Command"]
