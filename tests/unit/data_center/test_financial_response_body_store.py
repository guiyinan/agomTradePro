"""TDD contracts for encrypted, byte-preserving financial response storage."""

from __future__ import annotations

import struct
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from io import BytesIO
from pathlib import Path
from threading import Barrier
from uuid import UUID

import pytest
from cryptography.fernet import Fernet

from apps.data_center.domain.financial_response_artifact import (
    FinancialResponseArtifact,
    FinancialResponseArtifactRef,
)
from apps.data_center.domain.financial_response_evidence import (
    FinancialRequestScope,
    FinancialResponseEvidence,
    FinancialResponseScope,
    raw_body_sha256,
)
from apps.data_center.infrastructure import financial_response_body_store as store_module
from apps.data_center.infrastructure.financial_response_body_store import (
    FinancialResponseArtifactConfigurationError,
    FinancialResponseArtifactConflictError,
    FinancialResponseArtifactError,
    FinancialResponseArtifactIncompleteError,
    FinancialResponseBodyStore,
)

BODY = b'{ "b": 2, "a": 1, "text": "\xe4\xb8\xad\xe6\x96\x87" }\n'
CAPTURE_ID = UUID("10000000-0000-4000-8000-000000000001")
COMPLETED_AT = datetime(2026, 9, 14, 9, 0, 0, 123456, tzinfo=UTC)


@pytest.mark.parametrize(
    "metadata", [b"\xff", b"{", b'{"a":1,"a":2}', b"[]", b'{"a":NaN}', b'{"a":1e400}']
)
def test_authenticated_invalid_metadata_has_recognizable_corruption_error(
    tmp_path: Path, metadata: bytes
) -> None:
    """Malformed authenticated metadata must not escape as a raw parser error."""

    store = _store(tmp_path)
    reference = store.store(_artifact(BODY))
    envelope = b"FRA1" + struct.pack(">Q", len(metadata)) + metadata + BODY
    path = next(tmp_path.rglob("*.frb"))
    path.write_bytes(store._fernet.encrypt(envelope))
    with pytest.raises(FinancialResponseArtifactIncompleteError) as caught:
        store.read(reference)
    assert caught.value.code == "FINANCIAL_RESPONSE_ARTIFACT_CORRUPT"


def test_file_growth_after_stat_cannot_trigger_unbounded_read(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A growing file is rejected while retaining a finite read budget."""

    store = _store(tmp_path)
    reference = store.store(_artifact(BODY))
    oversized = b"x" * (store._max_token_bytes * 2)
    read_sizes: list[int] = []

    class GrowingFile(BytesIO):
        """Expose content larger than the preceding filesystem size snapshot."""

        def read(self, size: int = -1) -> bytes:
            """Reject an unbounded read before allocating the returned bytes."""

            assert 0 < size < len(oversized)
            read_sizes.append(size)
            return super().read(size)

    def open_growing_file(path: Path, *args: object, **kwargs: object) -> GrowingFile:
        """Substitute a growing stream only for this operation's file read."""

        return GrowingFile(oversized)

    monkeypatch.setattr(Path, "open", open_growing_file)
    with pytest.raises(FinancialResponseArtifactIncompleteError):
        store.read(reference)
    assert len(read_sizes) == 1


def test_exact_bytes_round_trip_and_encrypted_at_rest(tmp_path: Path) -> None:
    """Storage returns the exact vendor bytes without exposing plaintext on disk."""

    store = _store(tmp_path)
    artifact = _artifact(BODY)

    reference = store.store(artifact)

    assert store.read(reference) == BODY
    assert store.inspect(reference) == reference
    assert reference.body_sha256 == raw_body_sha256(BODY)
    assert reference.body_size_bytes == len(BODY)
    encrypted_files = tuple(tmp_path.rglob("*.frb"))
    assert len(encrypted_files) == 1
    assert BODY not in encrypted_files[0].read_bytes()
    assert raw_body_sha256(BODY) != raw_body_sha256('{"a":1,"b":2,"text":"中文"}\n'.encode())


def test_domain_artifact_rejects_hash_or_size_mismatch() -> None:
    """The body cannot be presented with a digest or size from another buffer."""

    evidence = _evidence(BODY)

    with pytest.raises(ValueError):
        FinancialResponseArtifact(
            capture_id=CAPTURE_ID,
            evidence=replace(evidence, body_sha256="0" * 64),
            body=BODY,
        )
    with pytest.raises(ValueError):
        FinancialResponseArtifact(
            capture_id=CAPTURE_ID,
            evidence=replace(evidence, body_size_bytes=len(BODY) + 1),
            body=BODY,
        )


@pytest.mark.parametrize(
    ("field_name", "value"),
    [
        ("capture_id", "not-a-uuid"),
        ("evidence", None),
        ("body", bytearray(BODY)),
    ],
)
def test_domain_artifact_rejects_untyped_members(field_name: str, value: object) -> None:
    """The Domain value cannot be built by coercing untrusted members."""

    with pytest.raises(ValueError):
        replace(_artifact(BODY), **{field_name: value})  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("field_name", "value"),
    [
        ("capture_id", "not-a-uuid"),
        ("evidence", None),
        ("location", None),
        ("location", ""),
        ("location", " padded"),
        ("location", "x" * 513),
        ("location", "bad\nlocation"),
    ],
)
def test_domain_reference_rejects_untyped_or_unsafe_members(
    tmp_path: Path, field_name: str, value: object
) -> None:
    """An opaque reference validates every public field before storage use."""

    reference = _store(tmp_path).store(_artifact(BODY))

    with pytest.raises(ValueError):
        replace(reference, **{field_name: value})  # type: ignore[arg-type]


def test_domain_artifact_projection_never_contains_original_body() -> None:
    """The Domain metadata projection carries evidence only."""

    projection = _artifact(BODY).to_dict()

    assert "body" not in projection
    assert projection["body_sha256"] == raw_body_sha256(BODY)


def test_same_capture_replay_is_immutable_and_does_not_rewrite(tmp_path: Path) -> None:
    """An identical replay returns the existing artifact without last-writer wins."""

    store = _store(tmp_path)
    artifact = _artifact(BODY)
    first = store.store(artifact)
    final_path = next(tmp_path.rglob("*.frb"))
    first_bytes = final_path.read_bytes()
    first_mtime = final_path.stat().st_mtime_ns

    second = store.store(artifact)

    assert second == first
    assert final_path.read_bytes() == first_bytes
    assert final_path.stat().st_mtime_ns == first_mtime


@pytest.mark.parametrize(
    "changed",
    [
        lambda evidence: replace(
            evidence, response_completed_at=COMPLETED_AT + timedelta(seconds=1)
        ),
        lambda evidence: replace(
            evidence,
            request_scope=replace(evidence.request_scope, provider_name="other-provider"),
        ),
        lambda evidence: replace(
            evidence,
            response_scope=replace(evidence.response_scope, row_count=2),
        ),
    ],
)
def test_same_capture_metadata_drift_is_rejected(tmp_path: Path, changed: object) -> None:
    """Completion and declared scopes are immutable observation metadata."""

    store = _store(tmp_path)
    original = _artifact(BODY)
    store.store(original)
    changed_evidence = changed(original.evidence)  # type: ignore[operator]
    changed_artifact = FinancialResponseArtifact(
        capture_id=CAPTURE_ID,
        evidence=changed_evidence,
        body=BODY,
    )

    with pytest.raises(FinancialResponseArtifactConflictError) as caught:
        store.store(changed_artifact)

    assert caught.value.code == "FINANCIAL_RESPONSE_ARTIFACT_IMMUTABLE_CONFLICT"
    assert BODY.decode("utf-8") not in str(caught.value)


def test_same_body_with_different_capture_ids_is_independent(tmp_path: Path) -> None:
    """A body digest is evidence, not a global observation/idempotency key."""

    store = _store(tmp_path)
    first = store.store(_artifact(BODY))
    second = store.store(
        FinancialResponseArtifact(
            capture_id=UUID("10000000-0000-4000-8000-000000000002"),
            evidence=_evidence(BODY, completed_at=COMPLETED_AT + timedelta(minutes=1)),
            body=BODY,
        )
    )

    assert first.capture_id != second.capture_id
    assert first.body_sha256 == second.body_sha256
    assert len(tuple(tmp_path.rglob("*.frb"))) == 2


def test_concurrent_same_capture_has_one_immutable_winner(tmp_path: Path) -> None:
    """Concurrent publishers converge on one exact artifact without overwrite."""

    store = _store(tmp_path)
    artifact = _artifact(BODY)
    barrier = Barrier(2)
    write_partial = store._write_partial

    def synchronized_write(partial_path: Path, encrypted: bytes) -> None:
        """Make both workers reach the no-replace publish point together."""

        barrier.wait(timeout=5)
        write_partial(partial_path, encrypted)

    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setattr(store, "_write_partial", synchronized_write)

    try:
        with ThreadPoolExecutor(max_workers=2) as executor:
            references = tuple(executor.map(store.store, (artifact, artifact)))
    finally:
        monkeypatch.undo()

    assert references[0] == references[1]
    assert store.read(references[0]) == BODY
    assert len(tuple(tmp_path.rglob("*.frb"))) == 1
    assert not tuple(tmp_path.rglob("*.partial"))


def test_post_publish_inspection_failure_is_recoverable(tmp_path: Path) -> None:
    """A renamed winner remains inspectable when the publisher loses its reply."""

    store = _store(tmp_path)
    inspect_existing = store._inspect_existing
    failed = False

    def fail_once(
        expected: FinancialResponseArtifactRef, final_path: Path
    ) -> FinancialResponseArtifactRef:
        """Simulate a response loss after the final path was published."""

        nonlocal failed
        if not failed:
            failed = True
            raise FinancialResponseArtifactError(
                "金融响应原件校验暂时失败。", code="FINANCIAL_RESPONSE_ARTIFACT_VERIFY_FAILED"
            )
        return inspect_existing(expected, final_path)

    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setattr(store, "_inspect_existing", fail_once)
    try:
        with pytest.raises(FinancialResponseArtifactError):
            store.store(_artifact(BODY))
    finally:
        monkeypatch.undo()

    assert len(tuple(tmp_path.rglob("*.frb"))) == 1
    recovered = store.store(_artifact(BODY))
    assert recovered.body_sha256 == raw_body_sha256(BODY)


def test_tampered_or_wrong_key_artifact_fails_closed(tmp_path: Path) -> None:
    """Authenticated-envelope failures never return a body."""

    store = _store(tmp_path)
    reference = store.store(_artifact(BODY))
    final_path = next(tmp_path.rglob("*.frb"))
    token = final_path.read_bytes()
    final_path.write_bytes(token[:-1] + bytes([token[-1] ^ 1]))

    with pytest.raises(FinancialResponseArtifactError) as caught:
        store.read(reference)
    assert caught.value.code == "FINANCIAL_RESPONSE_ARTIFACT_CORRUPT"
    assert BODY.decode("utf-8") not in str(caught.value)

    clean_store = _store(tmp_path / "clean")
    clean_reference = clean_store.store(_artifact(BODY))
    wrong_key_store = _store(tmp_path / "clean", key=Fernet.generate_key())
    with pytest.raises(FinancialResponseArtifactError) as wrong_key:
        wrong_key_store.read(clean_reference)
    assert wrong_key.value.code == "FINANCIAL_RESPONSE_ARTIFACT_CORRUPT"


def test_partial_file_is_not_a_complete_artifact(tmp_path: Path) -> None:
    """A leftover staging file cannot be read or adopted implicitly."""

    store = _store(tmp_path)
    reference = store.store(_artifact(BODY))
    final_path = next(tmp_path.rglob("*.frb"))
    final_path.unlink()
    final_path.with_name(final_path.name + ".partial").write_bytes(b"partial")

    with pytest.raises(FinancialResponseArtifactError) as caught:
        store.read(reference)
    assert caught.value.code == "FINANCIAL_RESPONSE_ARTIFACT_MISSING"


def test_location_cannot_escape_configured_root(tmp_path: Path) -> None:
    """References accept only the opaque server-derived capture location."""

    store = _store(tmp_path)
    reference = store.store(_artifact(BODY))
    forged = replace(reference, location="financial-response:///../outside.frb")

    with pytest.raises(FinancialResponseArtifactError) as caught:
        store.inspect(forged)
    assert caught.value.code == "FINANCIAL_RESPONSE_ARTIFACT_LOCATION_INVALID"


def test_missing_configuration_fails_closed(tmp_path: Path) -> None:
    """The store cannot silently downgrade to plaintext or an implicit root."""

    with pytest.raises(FinancialResponseArtifactConfigurationError) as caught:
        FinancialResponseBodyStore(
            tmp_path,
            encryption_key=b"",
            encryption_key_ref="env:BODY_KEY",
            encryption_key_version="v1",
            max_body_bytes=1024,
        )
    assert caught.value.code == "FINANCIAL_RESPONSE_ARTIFACT_CONFIG_INVALID"


def test_reference_metadata_excludes_source_and_transport_secrets(tmp_path: Path) -> None:
    """The body reference cannot be mistaken for row or HTTP source evidence."""

    store = _store(tmp_path)
    reference = store.store(_artifact(BODY))
    serialized = reference.to_dict()
    serialized_text = repr(serialized)

    assert "announced_at" not in serialized
    assert "available_at" not in serialized
    assert "source_record_id" not in serialized
    assert "headers" not in serialized
    assert "authorization" not in serialized_text.lower()
    assert BODY.decode("utf-8") not in repr(reference)


def test_publish_failure_cleans_only_own_partial_and_can_retry(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A failed atomic publish returns no success and leaves no accepted partial."""

    store = _store(tmp_path)

    def fail_publish(_source: Path, _target: Path) -> None:
        """Simulate a filesystem publish failure without exposing payload data."""

        raise OSError("simulated filesystem failure")

    monkeypatch.setattr(store_module, "_publish_no_replace", fail_publish)
    with pytest.raises(FinancialResponseArtifactError) as caught:
        store.store(_artifact(BODY))
    assert caught.value.code == "FINANCIAL_RESPONSE_ARTIFACT_WRITE_FAILED"
    assert not tuple(tmp_path.rglob("*.frb"))
    assert not tuple(tmp_path.rglob("*.partial"))

    monkeypatch.undo()
    assert store.store(_artifact(BODY)).body_sha256 == raw_body_sha256(BODY)


def _store(tmp_path: Path, *, key: bytes | None = None) -> FinancialResponseBodyStore:
    """Build a test store with explicit non-production encryption settings."""

    return FinancialResponseBodyStore(
        tmp_path,
        encryption_key=key or Fernet.generate_key(),
        encryption_key_ref="test:financial-response-body",
        encryption_key_version="test-v1",
        max_body_bytes=1024 * 1024,
    )


def _artifact(body: bytes) -> FinancialResponseArtifact:
    """Build one server-issued artifact with caller-declared transport scope."""

    return FinancialResponseArtifact(
        capture_id=CAPTURE_ID,
        evidence=_evidence(body),
        body=body,
    )


def _evidence(
    body: bytes,
    *,
    completed_at: datetime = COMPLETED_AT,
) -> FinancialResponseEvidence:
    """Build transport evidence without source announcement or availability."""

    return FinancialResponseEvidence(
        body_sha256=raw_body_sha256(body),
        body_size_bytes=len(body),
        response_completed_at=completed_at,
        request_scope=FinancialRequestScope(
            provider_name="test-provider",
            dataset_key="financial.statement",
            asset_code="000001.SZ",
            period_limit=1,
        ),
        response_scope=FinancialResponseScope(
            asset_codes=("000001.SZ",),
            period_ends=(date(2026, 6, 30),),
            row_count=1,
        ),
    )
