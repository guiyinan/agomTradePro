"""
Bootstrap the local .env file and secure keys for first-run installs.
"""

from django.core.management.base import BaseCommand

from apps.setup_wizard.infrastructure.encryption_setup import bootstrap_local_environment


class Command(BaseCommand):
    """Prepare local configuration for first-run development installs."""

    help = "Create .env from .env.example when missing and generate secure local keys."

    def add_arguments(self, parser) -> None:
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

    def handle(self, *args, **options) -> None:
        """Run the bootstrap workflow and print a concise summary."""
        result = bootstrap_local_environment(
            generate_secret_key=not options["skip_secret_key"],
            generate_encryption_key=not options["skip_encryption_key"],
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
            self.stdout.write(
                self.style.SUCCESS("Generated AGOMTRADEPRO_ENCRYPTION_KEY")
            )
        else:
            self.stdout.write("AGOMTRADEPRO_ENCRYPTION_KEY already configured")
