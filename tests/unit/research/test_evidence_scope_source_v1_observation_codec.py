"""Strict codec tests for the dormant Evidence scope observation DTO."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime, timedelta

import pytest

from apps.research.application.evidence_scope_source_v1_lifecycle import (
    EvidenceScopeSourceV1Observation,
)
from apps.research.domain.evidence_contracts import ArtifactRef
from apps.research.infrastructure.evidence_scope_source_v1_observation_codec import (
    EvidenceScopeSourceV1ObservationCodecError,
    decode_evidence_scope_source_v1_observation,
    encode_evidence_scope_source_v1_observation,
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


def _observation(**changes: object) -> EvidenceScopeSourceV1Observation:
    values: dict[str, object] = {
        "observation_id": "observation-1",
        "observation_version": "v1",
        "owner_id": "owner-1",
        "tenant_id": "tenant-1",
        "account_id": "account-1",
        "actor_id": "actor-1",
        "artifact": _artifact(),
        "status": "active",
        "recorded_at": AS_OF - timedelta(minutes=1),
        "valid_until": AS_OF + timedelta(hours=1),
        "content_hash": "",
    }
    values.update(changes)
    return EvidenceScopeSourceV1Observation(**values)  # type: ignore[arg-type]


def _add_unknown(payload: dict[str, object]) -> None:
    payload["unknown"] = True


def _remove_owner(payload: dict[str, object]) -> None:
    del payload["owner_id"]


def _noncanonical_clock(payload: dict[str, object]) -> None:
    payload["recorded_at"] = "2026-08-15T10:00:00+00:00"


def _nested_hash_tamper(payload: dict[str, object]) -> None:
    artifact = payload["artifact"]
    assert type(artifact) is dict
    artifact["content_hash"] = "b" * 64


def _content_hash_tamper(payload: dict[str, object]) -> None:
    payload["content_hash"] = "b" * 64


def test_roundtrip_preserves_exact_observation_payload() -> None:
    observation = _observation()
    payload = encode_evidence_scope_source_v1_observation(observation)

    assert set(payload) == {
        "observation_id",
        "observation_version",
        "owner_id",
        "tenant_id",
        "account_id",
        "actor_id",
        "artifact",
        "status",
        "recorded_at",
        "valid_until",
        "content_hash",
    }
    restored = decode_evidence_scope_source_v1_observation(payload)
    assert restored == observation
    assert encode_evidence_scope_source_v1_observation(restored) == payload


@pytest.mark.parametrize(
    "mutate",
    [
        _add_unknown,
        _remove_owner,
        _noncanonical_clock,
        _nested_hash_tamper,
        _content_hash_tamper,
    ],
)
def test_shape_clock_and_hash_tamper_fail_closed(
    mutate: Callable[[dict[str, object]], None],
) -> None:
    payload = encode_evidence_scope_source_v1_observation(_observation())
    mutate(payload)

    with pytest.raises(EvidenceScopeSourceV1ObservationCodecError):
        decode_evidence_scope_source_v1_observation(payload)


def test_non_mapping_and_invalid_domain_values_fail_closed() -> None:
    with pytest.raises(EvidenceScopeSourceV1ObservationCodecError):
        decode_evidence_scope_source_v1_observation([])

    payload = encode_evidence_scope_source_v1_observation(_observation())
    payload["status"] = "unknown"
    with pytest.raises(EvidenceScopeSourceV1ObservationCodecError):
        decode_evidence_scope_source_v1_observation(payload)

    payload = encode_evidence_scope_source_v1_observation(_observation())
    payload["artifact"] = []
    with pytest.raises(EvidenceScopeSourceV1ObservationCodecError):
        decode_evidence_scope_source_v1_observation(payload)


def test_encode_revalidates_frozen_object_tamper() -> None:
    observation = _observation()
    object.__setattr__(observation, "tenant_id", "tenant-tampered")

    with pytest.raises(EvidenceScopeSourceV1ObservationCodecError):
        encode_evidence_scope_source_v1_observation(observation)


def test_payload_contains_no_secret_fields() -> None:
    payload = encode_evidence_scope_source_v1_observation(_observation())
    assert not {
        "session_key",
        "session_data",
        "cookie",
        "csrf",
        "password",
        "token",
    }.intersection(payload)
