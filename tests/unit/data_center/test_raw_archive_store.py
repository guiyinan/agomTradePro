"""Byte-level safety contracts for the encrypted RawPayload archive store."""

from __future__ import annotations

import gzip
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import pytest
from cryptography.fernet import Fernet

from apps.data_center.domain.raw_landing import RawPayload, raw_payload_record_digest
from apps.data_center.infrastructure.raw_archive_store import FilesystemRawArchiveStore

NOW = datetime(2026, 8, 7, 2, 0, tzinfo=UTC)


def _payload(*, offset: int, dataset_key: str = "market.raw") -> RawPayload:
    return RawPayload(
        payload_id=str(uuid4()),
        dataset_key=dataset_key,
        provider_name="fixture",
        payload_hash=f"sha256:payload-{offset}",
        schema_fingerprint=f"sha256:schema-{offset}",
        payload={"offset": offset, "text": "归档"},
        request_params={"page": offset},
        fetched_at=NOW + timedelta(minutes=offset),
        payload_size_bytes=100 + offset,
        retention_until=NOW + timedelta(days=1),
    )


def _store(root: Path, *, key: bytes | None = None) -> FilesystemRawArchiveStore:
    return FilesystemRawArchiveStore(
        root,
        encryption_key=key or Fernet.generate_key(),
        encryption_key_ref="config-center://archive/test-key",
        encryption_key_version="v1",
    )


def test_write_then_inspect_preserves_exact_members_and_is_retry_idempotent(
    tmp_path: Path,
) -> None:
    key = Fernet.generate_key()
    store = _store(tmp_path, key=key)
    archive_id = str(uuid4())
    newest = _payload(offset=2)
    oldest = _payload(offset=1)

    written = store.write(
        archive_id=archive_id,
        dataset_key="market.raw",
        contract_version="contract-v1",
        schema_version="schema-v1",
        payloads=(newest, oldest),
        created_at=NOW,
    )
    inspected = store.inspect(written.location)
    retried = store.write(
        archive_id=archive_id,
        dataset_key="market.raw",
        contract_version="contract-v1",
        schema_version="schema-v1",
        payloads=(newest, oldest),
        created_at=NOW + timedelta(hours=1),
    )

    assert inspected == written
    assert retried == written
    assert inspected.object_count == 2
    assert [member.payload_id for member in inspected.members] == [
        oldest.payload_id,
        newest.payload_id,
    ]
    assert [member.record_digest for member in inspected.members] == [
        raw_payload_record_digest(oldest),
        raw_payload_record_digest(newest),
    ]
    assert inspected.coverage_started_at == oldest.fetched_at
    assert inspected.coverage_ended_at == newest.fetched_at
    assert inspected.checksum.startswith("sha256:")
    assert inspected.size_bytes == next(tmp_path.rglob("*.jsonl.gz")).stat().st_size
    assert not list(tmp_path.rglob("*.partial"))


def test_restore_to_staging_reconstructs_every_record_and_cleans_isolation_dir(
    tmp_path: Path,
) -> None:
    store = _store(tmp_path)
    artifact = store.write(
        archive_id=str(uuid4()),
        dataset_key="market.raw",
        contract_version="contract-v1",
        schema_version="schema-v1",
        payloads=(_payload(offset=1), _payload(offset=2)),
        created_at=NOW,
    )

    restored = store.restore_to_staging(artifact.location)

    assert restored == artifact
    staging_root = tmp_path / ".staging"
    assert staging_root.is_dir()
    assert list(staging_root.iterdir()) == []


def test_inspect_with_wrong_encryption_key_fails_closed(tmp_path: Path) -> None:
    writer = _store(tmp_path, key=Fernet.generate_key())
    artifact = writer.write(
        archive_id=str(uuid4()),
        dataset_key="market.raw",
        contract_version="contract-v1",
        schema_version="schema-v1",
        payloads=(_payload(offset=1),),
        created_at=NOW,
    )
    wrong_reader = _store(tmp_path, key=Fernet.generate_key())

    with pytest.raises(ValueError, match="archive_record_authentication_failed"):
        wrong_reader.inspect(artifact.location)


def test_inspect_rejects_truncated_artifact(tmp_path: Path) -> None:
    store = _store(tmp_path)
    artifact = store.write(
        archive_id=str(uuid4()),
        dataset_key="market.raw",
        contract_version="contract-v1",
        schema_version="schema-v1",
        payloads=(_payload(offset=1),),
        created_at=NOW,
    )
    artifact_path = next(tmp_path.rglob("*.jsonl.gz"))
    original = artifact_path.read_bytes()
    artifact_path.write_bytes(original[: max(1, len(original) // 2)])

    with pytest.raises((EOFError, OSError, ValueError)):
        store.inspect(artifact.location)


def test_inspect_rejects_oversized_manifest_header_before_json_decode(tmp_path: Path) -> None:
    store = _store(tmp_path)
    artifact_path = tmp_path / "raw" / "oversized.jsonl.gz"
    artifact_path.parent.mkdir(parents=True)
    with gzip.open(artifact_path, mode="wb") as stream:
        stream.write(b"x" * (64 * 1024 + 1) + b"\n")

    with pytest.raises(ValueError, match="archive_header_line_limit_exceeded"):
        store.inspect("archive:///raw/oversized.jsonl.gz")


@pytest.mark.parametrize(
    "location",
    [
        "archive:///../outside.jsonl.gz",
        "archive:///%2e%2e/outside.jsonl.gz",
        "archive://attacker/outside.jsonl.gz",
        "file:///tmp/outside.jsonl.gz",
        "https://attacker.example/archive.jsonl.gz",
    ],
)
def test_inspect_rejects_path_traversal_and_non_archive_locations(
    tmp_path: Path,
    location: str,
) -> None:
    store = _store(tmp_path)

    with pytest.raises(ValueError, match="archive_location_"):
        store.inspect(location)


def test_write_rejects_cross_dataset_payloads_before_creating_files(tmp_path: Path) -> None:
    store = _store(tmp_path)

    with pytest.raises(ValueError, match="archive_cross_dataset_payload"):
        store.write(
            archive_id=str(uuid4()),
            dataset_key="market.raw",
            contract_version="contract-v1",
            schema_version="schema-v1",
            payloads=(_payload(offset=1, dataset_key="other.raw"),),
            created_at=NOW,
        )

    assert list(tmp_path.rglob("*.jsonl.gz")) == []
