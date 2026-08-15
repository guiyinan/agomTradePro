"""Strict canonical codec for the dormant Evidence scope source v1."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import cast

from apps.research.domain.evidence_contracts import ArtifactRef
from apps.research.domain.evidence_scope_source_v1 import EvidenceScopeSourceV1


class EvidenceScopeSourceV1CodecError(ValueError):
    """A persisted scope-source payload is malformed or noncanonical."""


_ARTIFACT_KEYS = frozenset(
    {"owner", "artifact_type", "artifact_id", "artifact_version", "content_hash"}
)
_SOURCE_KEYS = frozenset(
    {
        "source_id",
        "source_version",
        "owner_id",
        "tenant_id",
        "account_id",
        "actor_id",
        "artifact",
        "status",
        "recorded_at",
        "valid_until",
        "root_claim_hash",
        "supersedes_content_hash",
        "identity_hash",
        "content_hash",
        "owner",
        "artifact_type",
        "schema",
        "permission",
        "must_not_execute",
        "execution_allowed",
    }
)


def _mapping(value: object, keys: frozenset[str], label: str) -> dict[str, object]:
    if type(value) is not dict or any(type(key) is not str for key in value):
        raise EvidenceScopeSourceV1CodecError(f"{label} must be an exact object")
    payload = cast(dict[str, object], value)
    if frozenset(payload) != keys:
        raise EvidenceScopeSourceV1CodecError(f"{label} keys differ")
    return payload


def _text(value: object, label: str) -> str:
    if type(value) is not str or not value or value.strip() != value:
        raise EvidenceScopeSourceV1CodecError(f"{label} must be a canonical token")
    return value


def _digest(value: object, label: str) -> str:
    if (
        type(value) is not str
        or len(value) != 64
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise EvidenceScopeSourceV1CodecError(f"{label} must be a lowercase SHA-256 digest")
    return value


def _optional_digest(value: object, label: str) -> str | None:
    if value is None:
        return None
    return _digest(value, label)


def _flag(value: object, label: str) -> bool:
    if type(value) is not bool:
        raise EvidenceScopeSourceV1CodecError(f"{label} must be an exact boolean")
    return value


def _utc_text(value: datetime, label: str) -> str:
    if type(value) is not datetime or value.tzinfo is None or value.utcoffset() is None:
        raise EvidenceScopeSourceV1CodecError(f"{label} must be timezone-aware")
    return value.astimezone(UTC).isoformat(timespec="microseconds").replace("+00:00", "Z")


def _clock(value: object, label: str) -> datetime:
    text = _text(value, label)
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as error:
        raise EvidenceScopeSourceV1CodecError(f"{label} is not canonical ISO-8601") from error
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise EvidenceScopeSourceV1CodecError(f"{label} must be timezone-aware")
    canonical = parsed.astimezone(UTC)
    if text != canonical.isoformat(timespec="microseconds").replace("+00:00", "Z"):
        raise EvidenceScopeSourceV1CodecError(f"{label} must use UTC Z microseconds")
    return canonical


def encode_evidence_scope_source_v1(value: EvidenceScopeSourceV1) -> dict[str, object]:
    """Encode one exact source after revalidating every Domain invariant."""

    if type(value) is not EvidenceScopeSourceV1:
        raise EvidenceScopeSourceV1CodecError("source must be an exact EvidenceScopeSourceV1")
    try:
        value.__post_init__()
        payload = value.to_payload()
        _mapping(payload, _SOURCE_KEYS, "scope source")
        _mapping(payload["artifact"], _ARTIFACT_KEYS, "scope source artifact")
        return payload
    except EvidenceScopeSourceV1CodecError:
        raise
    except (TypeError, ValueError, AttributeError) as error:
        raise EvidenceScopeSourceV1CodecError("scope source is invalid") from error


def decode_evidence_scope_source_v1(value: object) -> EvidenceScopeSourceV1:
    """Decode only an exact canonical source payload; reject all substitutions."""

    payload = _mapping(value, _SOURCE_KEYS, "scope source")
    artifact_payload = _mapping(payload["artifact"], _ARTIFACT_KEYS, "scope source artifact")
    try:
        artifact = ArtifactRef(
            owner=_text(artifact_payload["owner"], "artifact.owner"),
            artifact_type=_text(artifact_payload["artifact_type"], "artifact.artifact_type"),
            artifact_id=_text(artifact_payload["artifact_id"], "artifact.artifact_id"),
            artifact_version=_text(
                artifact_payload["artifact_version"], "artifact.artifact_version"
            ),
            content_hash=_digest(artifact_payload["content_hash"], "artifact.content_hash"),
        )
        source = EvidenceScopeSourceV1(
            source_id=_text(payload["source_id"], "source_id"),
            source_version=_text(payload["source_version"], "source_version"),
            owner_id=_text(payload["owner_id"], "owner_id"),
            tenant_id=_text(payload["tenant_id"], "tenant_id"),
            account_id=_text(payload["account_id"], "account_id"),
            actor_id=_text(payload["actor_id"], "actor_id"),
            artifact=artifact,
            status=_text(payload["status"], "status"),
            recorded_at=_clock(payload["recorded_at"], "recorded_at"),
            valid_until=_clock(payload["valid_until"], "valid_until"),
            root_claim_hash=_optional_digest(payload["root_claim_hash"], "root_claim_hash"),
            supersedes_content_hash=_optional_digest(
                payload["supersedes_content_hash"], "supersedes_content_hash"
            ),
            identity_hash=_digest(payload["identity_hash"], "identity_hash"),
            content_hash=_digest(payload["content_hash"], "content_hash"),
            owner=_text(payload["owner"], "owner"),
            artifact_type=_text(payload["artifact_type"], "artifact_type"),
            schema=_text(payload["schema"], "schema"),
            permission=_text(payload["permission"], "permission"),
            must_not_execute=_flag(payload["must_not_execute"], "must_not_execute"),
            execution_allowed=_flag(payload["execution_allowed"], "execution_allowed"),
        )
        encoded = encode_evidence_scope_source_v1(source)
    except EvidenceScopeSourceV1CodecError:
        raise
    except (TypeError, ValueError, AttributeError) as error:
        raise EvidenceScopeSourceV1CodecError("scope source payload is invalid") from error
    if encoded != payload:
        raise EvidenceScopeSourceV1CodecError("scope source payload is not canonical")
    return source


__all__ = [
    "EvidenceScopeSourceV1CodecError",
    "decode_evidence_scope_source_v1",
    "encode_evidence_scope_source_v1",
]
