"""Unit tests for the VPS PostgreSQL backup client."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

SCRIPT_PATH = Path(__file__).resolve().parents[2] / "scripts" / "backup-vps-postgres.py"
SPEC = importlib.util.spec_from_file_location("backup_vps_postgres", SCRIPT_PATH)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def test_parse_markers_ignores_unrelated_output() -> None:
    """Only parse the explicit machine-readable backup markers."""
    output = "\n".join(
        [
            "pg_dump: informational line",
            "AGOM_BACKUP_PATH=/opt/agomtradepro/backups/database/postgres-x.dump",
            "AGOM_BACKUP_SHA256=" + "a" * 64,
            "AGOM_BACKUP_SIZE=42",
        ]
    )

    assert MODULE._parse_markers(output) == {
        "PATH": "/opt/agomtradepro/backups/database/postgres-x.dump",
        "SHA256": "a" * 64,
        "SIZE": "42",
    }


def test_sha256_file_matches_known_digest(tmp_path: Path) -> None:
    """Calculate the digest used to verify an SFTP download."""
    path = tmp_path / "archive.dump"
    path.write_bytes(b"agomtradepro")

    assert MODULE._sha256_file(path) == (
        "e04a2b3406cfe424d4ebf7246a23442257d52d760b817f6f457db47945760fb2"
    )


@pytest.mark.parametrize(
    "name",
    ["backup.dump", "postgres-backup.sql", "../unexpected.dump"],
)
def test_validated_archive_name_rejects_unexpected_names(name: str) -> None:
    """Reject files that do not match the controlled PostgreSQL archive pattern."""
    with pytest.raises(ValueError):
        MODULE._validated_archive_name(name)


def test_remote_script_uses_custom_dump_and_restore_validation() -> None:
    """Keep the remote database backup and validation contract explicit."""
    script = MODULE._remote_backup_script(
        "/opt/agomtradepro/backups", download_latest=False, prune_older_than_days=0
    )

    assert "pg_dump" in script
    assert "--format=custom" in script
    assert "pg_restore --list" in script
    assert "docker volume prune" not in script
