"""
Management command to encrypt existing plaintext API keys.

Usage:
    python manage.py encrypt_api_keys --dry-run  # Preview changes
    python manage.py encrypt_api_keys             # Encrypt and migrate
"""

import os
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from apps.ai_provider.infrastructure.models import AIProviderConfig
from shared.infrastructure.crypto import FieldEncryptionService


class Command(BaseCommand):
    help = 'Encrypt existing plaintext API keys in AIProviderConfig model'

    def add_arguments(self, parser):
        parser.add_argument(
            '--dry-run',
            action='store_true',
            dest='dry_run',
            help='Preview changes without modifying the database',
        )
        parser.add_argument(
            '--force',
            action='store_true',
            dest='force',
            help='Force re-encryption of already encrypted keys',
        )

    def handle(self, *args, **options):
        dry_run = options.get('dry_run', False)
        force = options.get('force', False)

        # Check if encryption key is configured
        try:
            crypto = FieldEncryptionService()
            self.stdout.write(self.style.SUCCESS('Encryption service initialized successfully'))
        except ValueError as e:
            raise CommandError(f"Encryption key not configured: {e}\n"
                             "Please set AGOMSAAF_ENCRYPTION_KEY environment variable.\n"
                             "Generate a key with: python -c \"from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())\"")

        # Get all providers with plaintext API keys
        providers = AIProviderConfig._default_manager.filter(api_key__gt='')

        if not providers:
            self.stdout.write(self.style.WARNING('No providers with plaintext API keys found'))
            return

        self.stdout.write(f'Found {providers.count()} provider(s) with plaintext API keys')

        for provider in providers:
            api_key = provider.api_key

            # Check if already encrypted (unless force is enabled)
            if provider.api_key_encrypted and not force:
                self.stdout.write(
                    self.style.WARNING(f"  [{provider.id}] {provider.name}: Already encrypted, skipping (use --force to re-encrypt)")
                )
                continue

            # Display what will be done
            masked = FieldEncryptionService.mask(api_key)
            if dry_run:
                self.stdout.write(
                    f"  [DRY-RUN] [{provider.id}] {provider.name}: {api_key[:20]}... -> ENCRYPTED ({masked})"
                )
            else:
                # Perform encryption
                encrypted = crypto.encrypt(api_key)

                # Update the model
                with transaction.atomic():
                    provider.api_key_encrypted = encrypted
                    provider.api_key = ''  # Clear plaintext field
                    provider.save(update_fields=['api_key_encrypted', 'api_key'])

                self.stdout.write(
                    self.style.SUCCESS(f"  [{provider.id}] {provider.name}: Encrypted (showing as {masked})")
                )

        # Summary
        if dry_run:
            self.stdout.write(self.style.WARNING('\nDry run completed. No changes were made.'))
            self.stdout.write('Run without --dry-run to apply changes.')
        else:
            self.stdout.write(self.style.SUCCESS('\nEncryption migration completed successfully!'))
            self.stdout.write('Plaintext API keys have been cleared from the database.')
