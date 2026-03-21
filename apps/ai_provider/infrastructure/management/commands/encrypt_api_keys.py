"""
Django management command to encrypt existing API keys.

Encrypts all plaintext API keys in the AIProviderConfig model.
Run after setting up AGOMTRADEPRO_ENCRYPTION_KEY in your environment.

Usage:
    python manage.py encrypt_api_keys
    python manage.py encrypt_api_keys --dry-run
    python manage.py encrypt_api_keys --force
"""
import logging
from typing import Optional

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from apps.ai_provider.infrastructure.models import AIProviderConfig
from shared.infrastructure.crypto import FieldEncryptionService, get_encryption_service

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = 'Encrypt existing plaintext API keys in AIProviderConfig'

    def add_arguments(self, parser):
        parser.add_argument(
            '--dry-run',
            action='store_true',
            dest='dry_run',
            help='Show what would be encrypted without making changes',
        )
        parser.add_argument(
            '--force',
            action='store_true',
            dest='force',
            help='Encrypt even if api_key_encrypted already has a value',
        )

    def handle(self, *args, **options):
        """Execute the encryption command."""
        dry_run = options.get('dry_run', False)
        force = options.get('force', False)

        # Check encryption service availability
        try:
            crypto_service = get_encryption_service()
            if crypto_service is None:
                raise CommandError(
                    "Encryption service not available. "
                    "Please set AGOMTRADEPRO_ENCRYPTION_KEY environment variable."
                )
        except Exception as e:
            raise CommandError(f"Failed to initialize encryption service: {e}")

        # Find all providers with plaintext API keys
        providers_to_encrypt = AIProviderConfig.objects.exclude(
            api_key=''
        ).filter(
            api_key__isnull=False
        )

        if force:
            # Also include providers that already have encrypted keys
            providers_to_encrypt = AIProviderConfig.objects.all()

        count = providers_to_encrypt.count()

        if count == 0:
            self.stdout.write(self.style.WARNING("No API keys found to encrypt."))
            return

        self.stdout.write(f"Found {count} provider(s) with API keys to process.")

        encrypted_count = 0
        skipped_count = 0
        error_count = 0

        for provider in providers_to_encrypt:
            result = self._encrypt_provider(
                provider,
                crypto_service,
                dry_run=dry_run,
                force=force
            )

            if result == 'encrypted':
                encrypted_count += 1
            elif result == 'skipped':
                skipped_count += 1
            elif result == 'error':
                error_count += 1

        # Summary
        self.stdout.write("\n" + "=" * 50)
        self.stdout.write("Encryption Summary:")
        self.stdout.write(f"  Total providers: {count}")
        self.stdout.write(self.style.SUCCESS(f"  Encrypted: {encrypted_count}"))
        self.stdout.write(f"  Skipped: {skipped_count}")
        if error_count > 0:
            self.stdout.write(self.style.ERROR(f"  Errors: {error_count}"))

        if dry_run:
            self.stdout.write("\nDry run complete. No changes were made.")
            self.stdout.write("Run without --dry-run to apply encryption.")

    def _encrypt_provider(
        self,
        provider: AIProviderConfig,
        crypto_service: FieldEncryptionService,
        dry_run: bool = False,
        force: bool = False
    ) -> str:
        """
        Encrypt a single provider's API key.

        Returns:
            'encrypted', 'skipped', or 'error'
        """
        provider_name = provider.name

        try:
            # Check if already encrypted
            if provider.api_key_encrypted and not force:
                self.stdout.write(
                    f"  [{provider_name}] Already encrypted, use --force to re-encrypt"
                )
                return 'skipped'

            # Check if plaintext key exists
            if not provider.api_key:
                self.stdout.write(
                    f"  [{provider_name}] No plaintext API key to encrypt"
                )
                return 'skipped'

            # Display what will be encrypted
            masked_key = self._mask_key(provider.api_key)
            self.stdout.write(
                f"  [{provider_name}] Encrypting: {masked_key}"
            )

            if not dry_run:
                with transaction.atomic():
                    # Encrypt the API key
                    encrypted_key = crypto_service.encrypt(provider.api_key)

                    # Update the provider
                    provider.api_key_encrypted = encrypted_key
                    provider.api_key = ''  # Clear plaintext
                    provider.save(update_fields=['api_key_encrypted', 'api_key'])

            return 'encrypted'

        except Exception as e:
            self.stdout.write(
                self.style.ERROR(
                    f"  [{provider_name}] Error: {e}"
                )
            )
            return 'error'

    @staticmethod
    def _mask_key(api_key: str, visible_chars: int = 8) -> str:
        """Mask an API key for display."""
        if not api_key:
            return '(empty)'
        if len(api_key) <= visible_chars:
            return '***'
        return f"{api_key[:visible_chars]}{'*' * 10}..."
