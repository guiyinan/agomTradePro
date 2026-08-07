"""Database backup infrastructure services for task_monitor."""

from __future__ import annotations

import gzip
import hashlib
import logging
import os
import shutil
import sqlite3
import subprocess
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from django.conf import settings

from core.integration import runtime_settings

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class DatabaseBackupResult:
    """Outcome of one database backup run."""

    backup_file: str
    removed_old_backups: int
    keep_days: int
    compressed: bool
    engine: str
    sha256: str = ""
    size_bytes: int = 0
    backup_format: str = ""


class DatabaseBackupService:
    """Create and prune database backups without going through management commands."""

    def backup_database(
        self,
        *,
        keep_days: int | None = None,
        compress: bool = True,
        output_dir: str | None = None,
    ) -> DatabaseBackupResult:
        """Create a database backup and clean up expired files.

        ``keep_days`` is an explicit maintenance override.  Scheduled callers
        leave it unset so the active typed Config Center profile controls the
        retention window; a missing or invalid profile blocks the backup
        before an artifact is created.
        """

        resolved_keep_days = self._resolve_keep_days(keep_days)

        output_path = Path(output_dir or self._get_default_backup_dir())
        output_path.mkdir(parents=True, exist_ok=True)
        output_path.chmod(0o700)

        db_engine = settings.DATABASES["default"]["ENGINE"]
        superseded_backups = 0
        if "sqlite" in db_engine:
            backup_file = self._backup_sqlite(output_path, compress)
            backup_format = "sqlite-gzip" if compress else "sqlite"
        elif "postgresql" in db_engine or "postgis" in db_engine:
            backup_file = self._backup_postgresql(output_path, compress)
            backup_format = "postgresql-custom"
            superseded_backups = self._prune_superseded_postgresql_backups(
                output_path,
                keep=backup_file,
            )
        else:
            raise ValueError(f"Unsupported database engine: {db_engine}")

        removed_old_backups = superseded_backups + self._cleanup_old_backups(
            output_path,
            resolved_keep_days,
        )
        size_bytes = backup_file.stat().st_size
        sha256 = self._sha256_file(backup_file)
        logger.info(
            "Database backup completed",
            extra={
                "backup_file": str(backup_file),
                "keep_days": resolved_keep_days,
                "compressed": compress,
                "removed_old_backups": removed_old_backups,
            },
        )
        return DatabaseBackupResult(
            backup_file=str(backup_file),
            removed_old_backups=removed_old_backups,
            keep_days=resolved_keep_days,
            compressed=compress,
            engine=db_engine,
            sha256=sha256,
            size_bytes=size_bytes,
            backup_format=backup_format,
        )

    @staticmethod
    def _resolve_keep_days(keep_days: int | None) -> int:
        """Resolve an explicit override or the active typed runtime value."""

        if keep_days is None:
            try:
                configured = runtime_settings.get_runtime_config_value(
                    "task_monitor.retention_days"
                )
            except Exception as exc:
                raise RuntimeError("runtime_config_snapshot_unavailable") from exc
            if isinstance(configured, bool) or not isinstance(configured, int):
                raise RuntimeError("backup_retention_policy_missing_or_invalid")
            keep_days = configured
        if isinstance(keep_days, bool) or not isinstance(keep_days, int):
            raise ValueError("keep_days must be an integer")
        if not 1 <= keep_days <= 3650:
            raise ValueError("keep_days must be between 1 and 3650")
        return keep_days

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
        """Create an atomic, restorable PostgreSQL custom-format backup."""

        db_config = settings.DATABASES["default"]
        db_name = db_config["NAME"]
        db_user = db_config.get("USER", "")
        db_host = db_config.get("HOST", "localhost")
        db_port = db_config.get("PORT", "5432")
        db_password = db_config.get("PASSWORD", "")

        backup_file = output_path / "postgres-current.dump"
        backup_temp = output_path / ".postgres-current.dump.partial"
        backup_temp.unlink(missing_ok=True)

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
            "--format=custom",
            f"--compress={6 if compress else 0}",
            "--no-owner",
            "--no-acl",
            "-f",
            str(backup_temp),
            db_name,
        ]

        try:
            subprocess.run(
                cmd,
                env=env,
                capture_output=True,
                text=True,
                check=True,
            )
            if not backup_temp.is_file() or backup_temp.stat().st_size == 0:
                raise RuntimeError("postgresql_backup_empty")
            subprocess.run(
                ["pg_restore", "--list", str(backup_temp)],
                env=env,
                capture_output=True,
                text=True,
                check=True,
            )
            os.replace(backup_temp, backup_file)
            backup_file.chmod(0o600)
        except FileNotFoundError as exc:
            raise RuntimeError(
                "PostgreSQL client tools pg_dump and pg_restore are required."
            ) from exc
        finally:
            backup_temp.unlink(missing_ok=True)

        return backup_file

    @staticmethod
    def _prune_superseded_postgresql_backups(
        output_path: Path,
        *,
        keep: Path,
    ) -> int:
        """Keep exactly one completed local PostgreSQL backup artifact."""

        removed_count = 0
        candidates = {
            *output_path.glob("postgres-*.dump"),
            *output_path.glob("db_backup_*.sql"),
            *output_path.glob("db_backup_*.sql.gz"),
        }
        for backup_file in candidates:
            if backup_file.is_file() and backup_file != keep:
                backup_file.unlink()
                removed_count += 1
        return removed_count

    @staticmethod
    def _sha256_file(path: Path) -> str:
        """Return the streaming SHA-256 digest of one completed artifact."""

        digest = hashlib.sha256()
        with path.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()

    def _cleanup_old_backups(self, output_path: Path, keep_days: int) -> int:
        """Remove backup files older than the retention window."""

        removed_count = 0
        cutoff = datetime.now(UTC).timestamp() - (keep_days * 86400)
        for backup_file in output_path.glob("db_backup_*"):
            if backup_file.is_file() and backup_file.stat().st_mtime < cutoff:
                backup_file.unlink()
                removed_count += 1
        return removed_count
