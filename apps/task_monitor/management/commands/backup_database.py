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
import os
import shutil
import subprocess
from datetime import UTC, datetime, timezone
from pathlib import Path
from typing import Optional

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import connection

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
        output_dir = options.get("output") or self._get_default_backup_dir()
        keep_days = options["keep"]
        compress = options["compress"]

        # Create output directory if needed
        output_path = Path(output_dir)
        output_path.mkdir(parents=True, exist_ok=True)

        # Determine database type
        db_engine = settings.DATABASES["default"]["ENGINE"]

        try:
            if "sqlite" in db_engine:
                backup_file = self._backup_sqlite(output_path, compress)
            elif "postgresql" in db_engine or "postgis" in db_engine:
                backup_file = self._backup_postgresql(output_path, compress)
            else:
                raise CommandError(f"Unsupported database engine: {db_engine}")

            self.stdout.write(
                self.style.SUCCESS(f"Database backup created: {backup_file}")
            )

            # Cleanup old backups
            self._cleanup_old_backups(output_path, keep_days)

            # Log success
            logger.info(
                "Database backup completed",
                extra={
                    "backup_file": str(backup_file),
                    "keep_days": keep_days,
                    "compressed": compress,
                }
            )

        except Exception as e:
            logger.error(f"Database backup failed: {e}")
            raise CommandError(f"Backup failed: {e}")

    def _get_default_backup_dir(self) -> str:
        """Get the default backup directory."""
        base_dir = Path(settings.BASE_DIR)
        return str(base_dir / "backups" / "database")

    def _backup_sqlite(self, output_path: Path, compress: bool) -> Path:
        """
        Backup SQLite database using Python file copy.

        This approach is cross-platform and doesn't depend on external tools.
        """
        db_path = settings.DATABASES["default"]["NAME"]

        if not os.path.exists(db_path):
            raise CommandError(f"Database file not found: {db_path}")

        # Generate backup filename
        timestamp = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
        backup_name = f"db_backup_{timestamp}.sqlite3"
        if compress:
            backup_name += ".gz"
        backup_file = output_path / backup_name

        # Ensure database is in a consistent state
        with connection.cursor() as cursor:
            cursor.execute("PRAGMA wal_checkpoint(TRUNCATE);")

        # Copy the database file
        if compress:
            import gzip
            with open(db_path, "rb") as src:
                with gzip.open(backup_file, "wb") as dst:
                    shutil.copyfileobj(src, dst)
        else:
            shutil.copy2(db_path, backup_file)

        self.stdout.write(f"SQLite backup created: {backup_file}")
        return backup_file

    def _backup_postgresql(self, output_path: Path, compress: bool) -> Path:
        """
        Backup PostgreSQL database using pg_dump.

        Requires pg_dump to be available in PATH.
        """
        db_config = settings.DATABASES["default"]
        db_name = db_config["NAME"]
        db_user = db_config.get("USER", "")
        db_host = db_config.get("HOST", "localhost")
        db_port = db_config.get("PORT", "5432")
        db_password = db_config.get("PASSWORD", "")

        # Generate backup filename
        timestamp = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
        backup_name = f"db_backup_{timestamp}.sql"
        if compress:
            backup_name += ".gz"
        backup_file = output_path / backup_name

        # Build pg_dump command
        env = os.environ.copy()
        if db_password:
            env["PGPASSWORD"] = db_password

        cmd = [
            "pg_dump",
            "-h", db_host,
            "-p", str(db_port),
            "-U", db_user,
            "-F", "p",  # Plain SQL format
            "-f", str(backup_file) if not compress else "-",
            db_name,
        ]

        try:
            if compress:
                # Pipe through gzip
                import gzip
                process = subprocess.Popen(
                    cmd,
                    env=env,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                )
                with gzip.open(backup_file, "wb") as f:
                    for chunk in process.stdout:
                        f.write(chunk)
                _, stderr = process.communicate()
                if process.returncode != 0:
                    raise CommandError(f"pg_dump failed: {stderr.decode()}")
            else:
                result = subprocess.run(
                    cmd,
                    env=env,
                    capture_output=True,
                    text=True,
                )
                if result.returncode != 0:
                    raise CommandError(f"pg_dump failed: {result.stderr}")

            self.stdout.write(f"PostgreSQL backup created: {backup_file}")
            return backup_file

        except FileNotFoundError:
            raise CommandError(
                "pg_dump not found. Please install PostgreSQL client tools."
            )

    def _cleanup_old_backups(self, output_path: Path, keep_days: int) -> int:
        """
        Remove backups older than keep_days.

        Returns the number of files removed.
        """
        removed_count = 0
        cutoff = datetime.now(UTC).timestamp() - (keep_days * 86400)

        # Find and remove old backup files
        for backup_file in output_path.glob("db_backup_*"):
            if backup_file.is_file():
                file_mtime = backup_file.stat().st_mtime
                if file_mtime < cutoff:
                    backup_file.unlink()
                    removed_count += 1
                    self.stdout.write(f"Removed old backup: {backup_file}")

        if removed_count > 0:
            self.stdout.write(f"Cleaned up {removed_count} old backup(s)")

        return removed_count
