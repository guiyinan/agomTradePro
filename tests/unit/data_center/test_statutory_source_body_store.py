"""Exact public-body storage contracts; all source content is synthetic."""

from __future__ import annotations

import os
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from pathlib import Path
from uuid import uuid4

import pytest

from apps.data_center.infrastructure import statutory_source_body_store as storage_module
from apps.data_center.infrastructure.statutory_source_body_store import (
    StatutorySourceBodyStorageError,
    StatutorySourceBodyStore,
)

BODY = b"<html>Synthetic statutory source fixture</html>"


def test_store_and_exact_retry_preserve_one_immutable_capture(tmp_path: Path) -> None:
    store = StatutorySourceBodyStore(tmp_path / "bodies", max_body_bytes=4096)
    capture_id = uuid4()
    first = store.store(capture_id, BODY)
    assert first.capture_id == capture_id
    assert first.reference == f"statutory-source-body:///v1/{capture_id}.body"
    assert store.read(first) == BODY
    assert store.store(capture_id, BODY) == first
    assert len(list((tmp_path / "bodies").glob("*.body"))) == 1
    assert not list((tmp_path / "bodies").glob("*.partial"))


def test_same_capture_different_body_never_overwrites_original(tmp_path: Path) -> None:
    store = StatutorySourceBodyStore(tmp_path, max_body_bytes=4096)
    capture_id = uuid4()
    original = store.store(capture_id, BODY)
    with pytest.raises(StatutorySourceBodyStorageError):
        store.store(capture_id, BODY + b" changed")
    assert store.read(original) == BODY


def test_repeat_capture_keeps_separate_identity_for_identical_bytes(tmp_path: Path) -> None:
    store = StatutorySourceBodyStore(tmp_path, max_body_bytes=4096)
    first = store.store(uuid4(), BODY)
    second = store.store(uuid4(), BODY)
    assert first.capture_id != second.capture_id
    assert first.reference != second.reference
    assert first.body_sha256 == second.body_sha256
    assert store.read(first) == store.read(second) == BODY


def test_two_concurrent_writers_resolve_exact_first_winner(tmp_path: Path) -> None:
    store = StatutorySourceBodyStore(tmp_path, max_body_bytes=4096)
    capture_id = uuid4()
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: store.store(capture_id, BODY), range(2)))
    assert results[0] == results[1]
    assert store.read(results[0]) == BODY


def test_read_rejects_tampering_and_false_size(tmp_path: Path) -> None:
    store = StatutorySourceBodyStore(tmp_path, max_body_bytes=4096)
    reference = store.store(uuid4(), BODY)
    with pytest.raises(StatutorySourceBodyStorageError):
        store.read(replace(reference, body_size_bytes=reference.body_size_bytes + 1))
    (tmp_path / f"{reference.capture_id}.body").write_bytes(BODY + b" altered")
    with pytest.raises(StatutorySourceBodyStorageError):
        store.read(reference)


def test_read_rejects_oversized_and_missing_files(tmp_path: Path) -> None:
    store = StatutorySourceBodyStore(tmp_path, max_body_bytes=len(BODY))
    reference = store.store(uuid4(), BODY)
    path = tmp_path / f"{reference.capture_id}.body"
    path.write_bytes(b"x" * (len(BODY) + 1))
    with pytest.raises(StatutorySourceBodyStorageError):
        store.read(reference)
    path.unlink()
    with pytest.raises(StatutorySourceBodyStorageError):
        store.read(reference)


@pytest.mark.parametrize("location", ["../outside", "/outside", "file:///outside"])
def test_storage_never_uses_caller_reference_as_path(tmp_path: Path, location: str) -> None:
    store = StatutorySourceBodyStore(tmp_path, max_body_bytes=4096)
    reference = store.store(uuid4(), BODY)
    with pytest.raises(StatutorySourceBodyStorageError):
        store.read(replace(reference, reference=location))


def test_store_rejects_invalid_input_before_any_file_write(tmp_path: Path) -> None:
    store = StatutorySourceBodyStore(tmp_path, max_body_bytes=len(BODY))
    for body in (b"", BODY + b" too large", bytearray(BODY)):
        with pytest.raises(StatutorySourceBodyStorageError):
            store.store(uuid4(), body)  # type: ignore[arg-type]
    with pytest.raises(StatutorySourceBodyStorageError):
        store.store(str(uuid4()), BODY)  # type: ignore[arg-type]
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize("limit", [0, -1, True, sys.maxsize])
def test_store_requires_explicit_positive_byte_limit(tmp_path: Path, limit: int) -> None:
    with pytest.raises(StatutorySourceBodyStorageError):
        StatutorySourceBodyStore(tmp_path, max_body_bytes=limit)


def test_read_rejects_directory_at_capture_location(tmp_path: Path) -> None:
    store = StatutorySourceBodyStore(tmp_path, max_body_bytes=4096)
    reference = store.store(uuid4(), BODY)
    path = tmp_path / f"{reference.capture_id}.body"
    path.unlink()
    path.mkdir()
    with pytest.raises(StatutorySourceBodyStorageError):
        store.read(reference)


def test_replaced_root_does_not_receive_new_capture(tmp_path: Path) -> None:
    root = tmp_path / "bodies"
    store = StatutorySourceBodyStore(root, max_body_bytes=4096)
    root.rename(tmp_path / "original-bodies")
    root.mkdir()
    with pytest.raises(StatutorySourceBodyStorageError):
        store.store(uuid4(), BODY)
    assert list(root.iterdir()) == []


def test_root_and_target_symlinks_are_rejected(tmp_path: Path) -> None:
    actual = tmp_path / "actual"
    actual.mkdir()
    link = tmp_path / "linked"
    try:
        os.symlink(actual, link, target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("Native symlink creation is unavailable on this host")
    with pytest.raises(StatutorySourceBodyStorageError):
        StatutorySourceBodyStore(link, max_body_bytes=4096)
    store = StatutorySourceBodyStore(actual, max_body_bytes=4096)
    reference = store.store(uuid4(), BODY)
    path = actual / f"{reference.capture_id}.body"
    path.unlink()
    outside = tmp_path / "outside.body"
    outside.write_bytes(BODY)
    os.symlink(outside, path)
    with pytest.raises(StatutorySourceBodyStorageError):
        store.read(reference)


@pytest.mark.skipif(os.name != "nt", reason="Windows junction contract")
def test_windows_junction_root_is_rejected(tmp_path: Path) -> None:
    actual = tmp_path / "actual"
    actual.mkdir()
    link = tmp_path / "junction"
    subprocess.run(
        ["cmd.exe", "/d", "/c", "mklink", "/J", str(link), str(actual)],
        check=True,
        capture_output=True,
    )
    with pytest.raises(StatutorySourceBodyStorageError):
        StatutorySourceBodyStore(link, max_body_bytes=4096)


def test_disk_failure_does_not_publish_partial_body(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = StatutorySourceBodyStore(tmp_path, max_body_bytes=4096)

    def fail_link(*args: object, **kwargs: object) -> None:
        raise OSError("Synthetic storage failure")

    monkeypatch.setattr(os, "link", fail_link)
    with pytest.raises(StatutorySourceBodyStorageError):
        store.store(uuid4(), BODY)
    assert list(tmp_path.iterdir()) == []


def test_staging_name_collision_never_deletes_another_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = StatutorySourceBodyStore(tmp_path, max_body_bytes=4096)
    capture_id, staging_nonce = uuid4(), uuid4()
    existing = tmp_path / f".{capture_id}.{staging_nonce.hex}.partial"
    existing.write_bytes(b"Previously existing staging content")
    monkeypatch.setattr(storage_module, "uuid4", lambda: staging_nonce)
    with pytest.raises(StatutorySourceBodyStorageError):
        store.store(capture_id, BODY)
    assert existing.read_bytes() == b"Previously existing staging content"
