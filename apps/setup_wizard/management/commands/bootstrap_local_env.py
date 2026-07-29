"""
Bootstrap the local .env file and secure keys for first-run installs.
"""

from typing import Any

from django.core.management.base import BaseCommand, CommandError, CommandParser

from apps.setup_wizard.infrastructure.encryption_setup import bootstrap_local_environment


class Command(BaseCommand):
    """Prepare local configuration for first-run development installs."""

    help = "Create .env from .env.example when missing and generate secure local keys."

    def add_arguments(self, parser: CommandParser) -> None:
        """Register command-line arguments."""
        parser.add_argument(
            "--skip-secret-key",
            action="store_true",
            help="Do not generate a Django SECRET_KEY.",
        )
        parser.add_argument(
            "--skip-encryption-key",
            action="store_true",
            help="Do not generate AGOMTRADEPRO_ENCRYPTION_KEY.",
        )

    def handle(self, *args: Any, **options: Any) -> None:
        """Run the bootstrap workflow and print a concise summary."""
        skip_secret_key = options.get("skip_secret_key", False)
        skip_encryption_key = options.get("skip_encryption_key", False)
        if not isinstance(skip_secret_key, bool) or not isinstance(skip_encryption_key, bool):
            raise CommandError("Bootstrap skip options must be boolean values.")
        result = bootstrap_local_environment(
            generate_secret_key=not skip_secret_key,
            generate_encryption_key=not skip_encryption_key,
        )

        if result["env_created"]:
            self.stdout.write(self.style.SUCCESS("Created .env for local development"))
        else:
            self.stdout.write("Local .env already exists")

        if result["secret_key_generated"]:
            self.stdout.write(self.style.SUCCESS("Generated secure Django SECRET_KEY"))
        else:
            self.stdout.write("Django SECRET_KEY already configured")

        if result["encryption_key_generated"]:
            self.stdout.write(self.style.SUCCESS("Generated AGOMTRADEPRO_ENCRYPTION_KEY"))
        else:
            self.stdout.write("AGOMTRADEPRO_ENCRYPTION_KEY already configured")
