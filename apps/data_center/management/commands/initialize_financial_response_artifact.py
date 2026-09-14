"""Register and explicitly activate encrypted financial response retention."""

from __future__ import annotations

from django.core.management.base import BaseCommand, CommandError, CommandParser

from apps.data_center.infrastructure.financial_response_artifact_config import (
    ARTIFACT_ENABLED_KEY,
    ARTIFACT_ENCRYPTION_KEY,
    ARTIFACT_KEY_VERSION_KEY,
    ARTIFACT_MAX_BODY_BYTES_KEY,
    ARTIFACT_ROOT_KEY,
    financial_response_artifact_definitions,
)
from core.integration.config_center_runtime import (
    activate_runtime_profile_patch,
    register_runtime_definitions,
)


class Command(BaseCommand):
    """Register definitions or activate an explicitly supplied profile patch."""

    help = "Register or explicitly activate encrypted financial response retention."

    def add_arguments(self, parser: CommandParser) -> None:
        """Expose preview, registration, and fully explicit activation options."""

        parser.add_argument(
            "--register",
            action="store_true",
            help="Persist the owned definitions without changing a runtime profile.",
        )
        parser.add_argument(
            "--activate",
            action="store_true",
            help="Activate an explicit profile patch after registering definitions.",
        )
        parser.add_argument("--environment", default="")
        enabled_group = parser.add_mutually_exclusive_group()
        enabled_group.add_argument("--enabled", choices=("true", "false"))
        enabled_group.add_argument("--disabled", action="store_true")
        parser.add_argument("--root", default="")
        parser.add_argument("--encryption-key-ref", default="")
        parser.add_argument("--encryption-key-version", default="")
        parser.add_argument("--max-body-bytes", type=int)
        parser.add_argument("--actor", default="")
        parser.add_argument("--reason", default="")

    def handle(self, *args: object, **options: object) -> None:
        """Perform only the requested registry/profile write; default is preview."""

        del args
        register = bool(options.get("register"))
        activate = bool(options.get("activate"))
        if not register and not activate:
            self.stdout.write(
                "financial response artifact definitions are available; "
                "pass --register or --activate to write"
            )
            return

        activation: tuple[dict[str, object], dict[str, str], str, str, str] | None = None
        if activate:
            activation = self._activation_input(options)
        if register or activate:
            saved = self._register_definitions()
            self.stdout.write(
                self.style.SUCCESS(
                    "Registered financial response artifact definitions: " + ", ".join(saved)
                )
            )
        if not activate:
            return

        if activation is None:  # pragma: no cover - guarded by the branch above
            raise CommandError("activation input is unavailable")
        patch, secret_ref_patch, environment, actor, reason = activation
        try:
            evidence = activate_runtime_profile_patch(
                environment=environment,
                patch=patch,
                secret_ref_patch=secret_ref_patch,
                bootstrap_values=None,
                actor=actor,
                reason=reason,
            )
        except (OSError, RuntimeError, TypeError, ValueError) as exc:
            raise CommandError("financial response artifact activation failed") from exc
        self.stdout.write(
            self.style.SUCCESS(
                f"Activated runtime profile {evidence['profile_key']} "
                f"v{evidence['profile_version']}; snapshot={evidence['snapshot_hash']}"
            )
        )

    @staticmethod
    def _register_definitions() -> tuple[str, ...]:
        """Persist the stable definitions through Config Center's repository port."""

        return register_runtime_definitions(financial_response_artifact_definitions())

    @staticmethod
    def _activation_input(
        options: dict[str, object],
    ) -> tuple[dict[str, object], dict[str, str], str, str, str]:
        """Validate explicit activation values without reading secrets or defaults."""

        environment = _required_option(options, "environment")
        actor = _required_option(options, "actor")
        reason = _required_option(options, "reason")
        enabled = options.get("enabled")
        disabled = bool(options.get("disabled"))
        if enabled is None and not disabled:
            raise CommandError("activation requires --enabled true|false or --disabled")
        if disabled or enabled == "false":
            return {ARTIFACT_ENABLED_KEY: False}, {}, environment, actor, reason
        root = _required_option(options, "root")
        key_ref = _required_option(options, "encryption-key-ref")
        key_version = _required_option(options, "encryption-key-version")
        max_body_bytes = options.get("max_body_bytes")
        if (
            isinstance(max_body_bytes, bool)
            or not isinstance(max_body_bytes, int)
            or max_body_bytes <= 0
        ):
            raise CommandError("--max-body-bytes must be a positive integer")
        return (
            {
                ARTIFACT_ENABLED_KEY: True,
                ARTIFACT_ROOT_KEY: root,
                ARTIFACT_KEY_VERSION_KEY: key_version,
                ARTIFACT_MAX_BODY_BYTES_KEY: max_body_bytes,
            },
            {ARTIFACT_ENCRYPTION_KEY: key_ref},
            environment,
            actor,
            reason,
        )


def _required_option(options: dict[str, object], name: str) -> str:
    """Read one non-empty command option."""

    value = options.get(name.replace("-", "_"), options.get(name, ""))
    if not isinstance(value, str) or not value.strip():
        raise CommandError(f"--{name} is required")
    return value.strip()


__all__ = ["Command"]
