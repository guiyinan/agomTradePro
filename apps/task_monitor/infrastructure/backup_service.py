"""Database backup infrastructure services for task_monitor."""

from __future__ import annotations

import gzip
import logging
import os
import shutil
import sqlite3
import subprocess
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from django.conf import settings  # type: ignore[import-untyped]

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class DatabaseBackupResult:
    """Outcome of one database backup run."""

    backup_file: str
    removed_old_backups: int
    keep_days: int
    compressed: bool
    engine: str


class DatabaseBackupService:
    """Create and prune database backups without going through management commands."""

    def backup_database(
        self,
        *,
        keep_days: int = 14,
        compress: bool = True,
        output_dir: str | None = None,
    ) -> DatabaseBackupResult:
        """Create a database backup and clean up expired files."""

        output_path = Path(output_dir or self._get_default_backup_dir())
        output_path.mkdir(parents=True, exist_ok=True)
        output_path.chmod(0o700)

        db_engine = settings.DATABASES["default"]["ENGINE"]
        if "sqlite" in db_engine:
            backup_file = self._backup_sqlite(output_path, compress)
        elif "postgresql" in db_engine or "postgis" in db_engine:
            backup_file = self._backup_postgresql(output_path, compress)
        else:
            raise ValueError(f"Unsupported database engine: {db_engine}")

        removed_old_backups = self._cleanup_old_backups(output_path, keep_days)
        logger.info(
            "Database backup completed",
            extra={
                "backup_file": str(backup_file),
                "keep_days": keep_days,
                "compressed": compress,
                "removed_old_backups": removed_old_backups,
            },
        )
        return DatabaseBackupResult(
            backup_file=str(backup_file),
            removed_old_backups=removed_old_backups,
            keep_days=keep_days,
            compressed=compress,
            engine=db_engine,
        )

    def _get_default_backup_dir(self) -> str:
        """Return the default backup directory."""

        base_dir = Path(settings.BASE_DIR)
        return str(base_dir / "backups" / "database")

    def _backup_sqlite(self, output_path: Path, compress: bool) -> Path:
        """Create and verify a transactionally consistent SQLite online backup."""

        db_path = settings.DATABASES["default"]["NAME"]
        if not os.path.exists(db_path):
            raise FileNotFoundError(f"Database file not found: {db_path}")

        timestamp = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
        backup_name = f"db_backup_{timestamp}.sqlite3"
        if compress:
            backup_name += ".gz"
        backup_file = output_path / backup_name
        raw_temp = output_path / f".{backup_name.removesuffix('.gz')}.tmp"
        compressed_temp = output_path / f".{backup_name}.tmp"
        raw_temp.unlink(missing_ok=True)
        compressed_temp.unlink(missing_ok=True)

        source = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True, timeout=60)
        destination = sqlite3.connect(raw_temp)
        try:
            source.backup(destination)
            result = destination.execute("PRAGMA integrity_check").fetchone()
            if not result or result[0] != "ok":
                raise RuntimeError(f"SQLite backup integrity check failed: {result}")
        finally:
            destination.close()
            source.close()

        try:
            if compress:
                with raw_temp.open("rb") as src, gzip.open(compressed_temp, "wb") as dst:
                    shutil.copyfileobj(src, dst)
                os.replace(compressed_temp, backup_file)
            else:
                os.replace(raw_temp, backup_file)
            backup_file.chmod(0o600)
        finally:
            raw_temp.unlink(missing_ok=True)
            compressed_temp.unlink(missing_ok=True)
        return backup_file

    def _backup_postgresql(self, output_path: Path, compress: bool) -> Path:
        """Backup PostgreSQL using pg_dump."""

        db_config = settings.DATABASES["default"]
        db_name = db_config["NAME"]
        db_user = db_config.get("USER", "")
        db_host = db_config.get("HOST", "localhost")
        db_port = db_config.get("PORT", "5432")
        db_password = db_config.get("PASSWORD", "")

        timestamp = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
        backup_name = f"db_backup_{timestamp}.sql"
        if compress:
            backup_name += ".gz"
        backup_file = output_path / backup_name

        env = os.environ.copy()
        if db_password:
            env["PGPASSWORD"] = db_password

        cmd = [
            "pg_dump",
            "-h",
            db_host,
            "-p",
            str(db_port),
            "-U",
            db_user,
            "-F",
            "p",
            "-f",
            str(backup_file) if not compress else "-",
            db_name,
        ]

        try:
            if compress:
                process = subprocess.Popen(
                    cmd,
                    env=env,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                )
                assert process.stdout is not None
                with gzip.open(backup_file, "wb") as dst:
                    for chunk in process.stdout:
                        dst.write(chunk)
                _, stderr = process.communicate()
                if process.returncode != 0:
                    raise subprocess.CalledProcessError(
                        process.returncode,
                        cmd,
                        stderr=stderr.decode("utf-8", errors="ignore"),
                    )
            else:
                subprocess.run(
                    cmd,
                    env=env,
                    capture_output=True,
                    text=True,
                    check=True,
                )
        except FileNotFoundError as exc:
            raise RuntimeError(
                "pg_dump not found. Please install PostgreSQL client tools."
            ) from exc

        return backup_file

    def _cleanup_old_backups(self, output_path: Path, keep_days: int) -> int:
        """Remove backup files older than the retention window."""

        removed_count = 0
        cutoff = datetime.now(UTC).timestamp() - (keep_days * 86400)
        for backup_file in output_path.glob("db_backup_*"):
            if backup_file.is_file() and backup_file.stat().st_mtime < cutoff:
                backup_file.unlink()
                removed_count += 1
        return removed_count
