"""
Database Backup Management Command

P1-2: Automated database backup with cross-platform support.

Supports:
- SQLite: Uses Python file copy (no external dependencies)
- PostgreSQL: Uses pg_dump with error handling

Usage:
    python manage.py backup_database
    python manage.py backup_database --keep 7
    python manage.py backup_database --output /custom/path
"""

import logging
import subprocess

from django.core.management.base import BaseCommand, CommandError

from apps.task_monitor.application.repository_provider import get_database_backup_service

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = "Backup the database (supports SQLite and PostgreSQL)"

    def add_arguments(self, parser):
        parser.add_argument(
            "--output",
            type=str,
            help="Custom output directory for backup files",
        )
        parser.add_argument(
            "--keep",
            type=int,
            default=7,
            help="Number of backups to keep (default: 7)",
        )
        parser.add_argument(
            "--compress",
            action="store_true",
            help="Compress the backup file (gzip)",
        )

    def handle(self, *args, **options):
        output_dir = options.get("output")
        keep_days = options["keep"]
        compress = options["compress"]

        try:
            result = get_database_backup_service().backup_database(
                keep_days=keep_days,
                compress=compress,
                output_dir=output_dir,
            )

            self.stdout.write(
                self.style.SUCCESS(f"Database backup created: {result.backup_file}")
            )
            if result.removed_old_backups:
                self.stdout.write(f"Cleaned up {result.removed_old_backups} old backup(s)")

            # Log success
            logger.info(
                "Database backup completed",
                extra={
                    "backup_file": result.backup_file,
                    "keep_days": result.keep_days,
                    "compressed": result.compressed,
                    "removed_old_backups": result.removed_old_backups,
                }
            )

        except (subprocess.CalledProcessError, FileNotFoundError, OSError, RuntimeError, ValueError) as e:
            logger.error(f"Database backup failed: {e}")
            raise CommandError(f"Backup failed: {e}")
