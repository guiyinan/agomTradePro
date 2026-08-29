"""Unit tests for the VPS PostgreSQL backup client."""

from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path

import pytest

SCRIPT_PATH = Path(__file__).resolve().parents[2] / "scripts" / "backup-vps-postgres.py"
SPEC = importlib.util.spec_from_file_location("backup_vps_postgres", SCRIPT_PATH)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class _FakeChannel:
    def settimeout(self, _timeout: int) -> None:
        return None


class _FakeRemoteFile:
    def __init__(self, content: bytes, fail_after: int | None = None) -> None:
        self._content = content
        self._fail_after = fail_after
        self._failed = False
        self._offset = 0

    def __enter__(self) -> _FakeRemoteFile:
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def prefetch(self, **_kwargs: object) -> None:
        return None

    def seek(self, offset: int) -> None:
        self._offset = offset

    def read(self, size: int) -> bytes:
        if self._fail_after is not None and not self._failed and self._offset >= self._fail_after:
            self._failed = True
            raise RuntimeError("simulated SFTP connection drop")
        block = self._content[self._offset : self._offset + size]
        self._offset += len(block)
        return block


class _FakeSftp:
    def __init__(self, content: bytes, fail_after: int | None = None) -> None:
        self._content = content
        self._fail_after = fail_after

    def get_channel(self) -> _FakeChannel:
        return _FakeChannel()

    def open(self, _remote_path: str, _mode: str) -> _FakeRemoteFile:
        return _FakeRemoteFile(self._content, self._fail_after)

    def close(self) -> None:
        return None


class _FakeSsh:
    def __init__(self, content: bytes, failing: bool = False) -> None:
        self._content = content
        self._failing = failing
        self.open_count = 0

    def open_sftp(self) -> _FakeSftp:
        self.open_count += 1
        fail_after = 4 * 1024 * 1024 if self._failing and self.open_count == 1 else None
        return _FakeSftp(self._content, fail_after)


def _sha256_bytes(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


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
    assert "AGOM_BACKUP_MTIME_EPOCH" in script
    assert "AGOM_BACKUP_MANIFEST_SHA256" in script
    assert "AGOM_BACKUP_MANIFEST_ENTRIES" in script
    assert "mkdir -p" in script
    assert "chmod 700" in script
    assert "pg_dump" in script
    assert 'mv "$temporary" "$archive"' in script
    assert "docker volume prune" not in script


def test_latest_download_script_is_remote_read_only_without_prune() -> None:
    """Latest auto-collect must not create, chmod, dump, move, or delete remotely."""
    script = MODULE._remote_backup_script(
        "/opt/agomtradepro/backups", download_latest=True, prune_older_than_days=0
    )

    assert "mkdir" not in script
    assert "chmod" not in script
    assert "pg_dump" not in script
    assert "mv " not in script
    assert "-delete" not in script
    assert "pg_restore --list" in script
    assert "AGOM_BACKUP_MANIFEST_ENTRIES" in script


def test_download_verified_resumes_after_sftp_drop(tmp_path: Path) -> None:
    """Resume from the verified partial offset after a transient stream drop."""
    content = bytes(range(256)) * (5 * 1024 * 1024 // 256)
    ssh = _FakeSsh(content, failing=True)
    reconnected_ssh = _FakeSsh(content, failing=False)

    destination = MODULE._download_verified(
        ssh=ssh,
        remote_path="/opt/agomtradepro/backups/postgres-resume.dump",
        expected_hash=_sha256_bytes(content),
        expected_size=len(content),
        output_dir=tmp_path,
        max_attempts=3,
        reconnect=lambda: reconnected_ssh,
    )

    assert destination.read_bytes() == content
    assert destination.with_suffix(".dump.sha256").read_text(encoding="ascii")
    assert not destination.with_name(f".{destination.name}.partial").exists()
    assert ssh.open_count == 1
    assert reconnected_ssh.open_count == 1


def test_download_verified_cleans_partial_after_retry_exhaustion(tmp_path: Path) -> None:
    """Never leave a misleading partial archive after bounded retries fail."""
    content = b"archive-content"
    ssh = _FakeSsh(content, failing=True)

    with pytest.raises(RuntimeError, match="SFTP download failed"):
        MODULE._download_verified(
            ssh=ssh,
            remote_path="/opt/agomtradepro/backups/postgres-fail.dump",
            expected_hash=_sha256_bytes(content),
            expected_size=len(content) + 1,
            output_dir=tmp_path,
            max_attempts=2,
        )

    destination = tmp_path / "postgres-fail.dump"
    assert not destination.exists()
    assert not destination.with_name(f".{destination.name}.partial").exists()


def test_write_backup_evidence_is_content_addressed_and_idempotent(tmp_path: Path) -> None:
    """Write exact archive/age/manifest evidence without overwriting another record."""
    archive = tmp_path / "postgres-20260820T000000Z.dump"
    archive.write_bytes(b"verified archive")
    evidence = tmp_path / "evidence.json"
    digest = _sha256_bytes(archive.read_bytes())

    written = MODULE._write_backup_evidence(
        evidence,
        host="demo.example",
        remote_path="/opt/agomtradepro/backups/database/postgres-20260820T000000Z.dump",
        remote_sha256=digest,
        remote_size_bytes=archive.stat().st_size,
        remote_mtime_epoch=1_000,
        remote_collected_epoch=1_360,
        remote_manifest_sha256="b" * 64,
        remote_manifest_entries=7_167,
        local_path=archive,
    )

    payload = json.loads(written.read_text(encoding="utf-8"))
    assert payload["schema"] == "data-backup-evidence.v1"
    assert payload["source"]["age_seconds"] == 360
    assert payload["archive"]["remote_manifest_entries"] == 7_167
    assert len(payload["content_hash"]) == 64
    assert (
        MODULE._write_backup_evidence(
            evidence,
            host="demo.example",
            remote_path="/opt/agomtradepro/backups/database/postgres-20260820T000000Z.dump",
            remote_sha256=digest,
            remote_size_bytes=archive.stat().st_size,
            remote_mtime_epoch=1_000,
            remote_collected_epoch=1_360,
            remote_manifest_sha256="b" * 64,
            remote_manifest_entries=7_167,
            local_path=archive,
        )
        == evidence.resolve()
    )

    with pytest.raises(RuntimeError, match="Refusing to overwrite"):
        MODULE._write_backup_evidence(
            evidence,
            host="demo.example",
            remote_path="/opt/agomtradepro/backups/database/postgres-20260820T000000Z.dump",
            remote_sha256=digest,
            remote_size_bytes=archive.stat().st_size,
            remote_mtime_epoch=1_001,
            remote_collected_epoch=1_360,
            remote_manifest_sha256="b" * 64,
            remote_manifest_entries=7_167,
            local_path=archive,
        )


def test_write_backup_evidence_rejects_partial_or_negative_age(tmp_path: Path) -> None:
    """A partial archive or impossible clock cannot become a success artifact."""
    archive = tmp_path / "postgres-20260820T000000Z.dump"
    archive.write_bytes(b"verified archive")
    partial = archive.with_name(f".{archive.name}.partial")
    partial.write_bytes(b"partial")
    digest = _sha256_bytes(archive.read_bytes())

    kwargs = {
        "host": "demo.example",
        "remote_path": "/opt/agomtradepro/backups/database/postgres-20260820T000000Z.dump",
        "remote_sha256": digest,
        "remote_size_bytes": archive.stat().st_size,
        "remote_mtime_epoch": 1_000,
        "remote_collected_epoch": 1_360,
        "remote_manifest_sha256": "b" * 64,
        "remote_manifest_entries": 1,
        "local_path": archive,
    }
    with pytest.raises(RuntimeError, match="partial archive"):
        MODULE._write_backup_evidence(tmp_path / "partial.json", **kwargs)

    partial.unlink()
    kwargs["remote_collected_epoch"] = 999
    with pytest.raises(RuntimeError, match="negative"):
        MODULE._write_backup_evidence(tmp_path / "negative.json", **kwargs)
