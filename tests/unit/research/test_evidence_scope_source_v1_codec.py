"""Strict codec tests for the dormant Evidence scope source v1."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime, timedelta

import pytest

from apps.research.domain.evidence_contracts import ArtifactRef
from apps.research.domain.evidence_scope_source_v1 import (
    EvidenceScopeSourceV1,
    root_claim_hash_for_evidence_scope_source_v1,
)
from apps.research.infrastructure.evidence_scope_source_v1_codec import (
    EvidenceScopeSourceV1CodecError,
    decode_evidence_scope_source_v1,
    encode_evidence_scope_source_v1,
)

AS_OF = datetime(2026, 8, 15, 10, 0, 0, 123456, tzinfo=UTC)


def _artifact() -> ArtifactRef:
    return ArtifactRef(
        owner="research",
        artifact_type="evidence_operator_spec",
        artifact_id="operator-1",
        artifact_version="v1",
        content_hash="a" * 64,
    )


def _root(**changes: object) -> EvidenceScopeSourceV1:
    values: dict[str, object] = {
        "source_id": "scope-source-1",
        "source_version": "v1",
        "owner_id": "owner-1",
        "tenant_id": "tenant-1",
        "account_id": "account-1",
        "actor_id": "actor-1",
        "artifact": _artifact(),
        "status": "active",
        "recorded_at": AS_OF - timedelta(minutes=1),
        "valid_until": AS_OF + timedelta(hours=1),
        "root_claim_hash": "",
        "supersedes_content_hash": None,
        "identity_hash": "",
        "content_hash": "",
    }
    values.update(changes)
    if values["root_claim_hash"] == "":
        values["root_claim_hash"] = root_claim_hash_for_evidence_scope_source_v1(
            source_id=values["source_id"],
            owner_id=values["owner_id"],
            tenant_id=values["tenant_id"],
            account_id=values["account_id"],
            actor_id=values["actor_id"],
            artifact=values["artifact"],
        )
    return EvidenceScopeSourceV1(**values)  # type: ignore[arg-type]


def _successor(previous: EvidenceScopeSourceV1) -> EvidenceScopeSourceV1:
    return EvidenceScopeSourceV1(
        source_id=previous.source_id,
        source_version="v2",
        owner_id=previous.owner_id,
        tenant_id=previous.tenant_id,
        account_id=previous.account_id,
        actor_id=previous.actor_id,
        artifact=previous.artifact,
        status="active",
        recorded_at=previous.recorded_at + timedelta(minutes=1),
        valid_until=previous.valid_until + timedelta(minutes=1),
        root_claim_hash=None,
        supersedes_content_hash=previous.content_hash,
        identity_hash="",
        content_hash="",
    )


def _add_unknown(payload: dict[str, object]) -> None:
    payload["unknown"] = True


def _remove_owner(payload: dict[str, object]) -> None:
    del payload["owner"]


def _bool_as_int(payload: dict[str, object]) -> None:
    payload["must_not_execute"] = 1


def _bool_as_text(payload: dict[str, object]) -> None:
    payload["execution_allowed"] = "false"


def _noncanonical_clock(payload: dict[str, object]) -> None:
    payload["recorded_at"] = "2026-08-15T10:00:00+00:00"


def _nested_hash_tamper(payload: dict[str, object]) -> None:
    artifact = payload["artifact"]
    assert type(artifact) is dict
    artifact["content_hash"] = "B" * 64


def _content_hash_tamper(payload: dict[str, object]) -> None:
    payload["content_hash"] = "b" * 64


def test_roundtrip_root_and_successor() -> None:
    root = _root()
    successor = _successor(root)

    for source in (root, successor):
        payload = encode_evidence_scope_source_v1(source)
        restored = decode_evidence_scope_source_v1(payload)
        assert restored == source
        assert encode_evidence_scope_source_v1(restored) == payload


@pytest.mark.parametrize(
    "mutate",
    [
        _add_unknown,
        _remove_owner,
        _bool_as_int,
        _bool_as_text,
        _noncanonical_clock,
        _nested_hash_tamper,
        _content_hash_tamper,
    ],
)
def test_unknown_type_clock_and_hash_tamper_fail_closed(
    mutate: Callable[[dict[str, object]], None],
) -> None:
    payload = encode_evidence_scope_source_v1(_root())
    mutate(payload)

    with pytest.raises(EvidenceScopeSourceV1CodecError):
        decode_evidence_scope_source_v1(payload)


def test_non_mapping_and_noncanonical_nested_payloads_fail_closed() -> None:
    with pytest.raises(EvidenceScopeSourceV1CodecError):
        decode_evidence_scope_source_v1([])

    payload = encode_evidence_scope_source_v1(_root())
    payload["artifact"] = []
    with pytest.raises(EvidenceScopeSourceV1CodecError):
        decode_evidence_scope_source_v1(payload)


def test_successor_payload_preserves_root_xor_and_rejects_missing_predecessor() -> None:
    payload = encode_evidence_scope_source_v1(_successor(_root()))
    payload["supersedes_content_hash"] = None

    with pytest.raises(EvidenceScopeSourceV1CodecError):
        decode_evidence_scope_source_v1(payload)


def test_encode_revalidates_object_tamper() -> None:
    source = _root()
    object.__setattr__(source, "tenant_id", "tenant-tampered")

    with pytest.raises(EvidenceScopeSourceV1CodecError):
        encode_evidence_scope_source_v1(source)


def test_payload_contains_no_secret_fields() -> None:
    payload = encode_evidence_scope_source_v1(_root())
    assert not {"session_key", "cookie", "csrf", "password", "token"}.intersection(payload)
