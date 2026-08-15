"""Pure, inactive owner/tenant scope facts for Research evidence.

The source in this module is an immutable Domain value.  It records the exact
owner, tenant, account, actor, and evidence artifact that a future trusted
scope provider must prove.  It deliberately has no Django, request, runtime
state, persistence, or execution dependency.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime

from apps.research.domain.evidence_contracts import ArtifactRef

EVIDENCE_SCOPE_SOURCE_OWNER = "research"
EVIDENCE_SCOPE_SOURCE_ARTIFACT_TYPE = "evidence_scope_source"
EVIDENCE_SCOPE_SOURCE_SCHEMA = "research.evidence_scope_source.v1"
EVIDENCE_SCOPE_SOURCE_PERMISSION = "read_only"
EVIDENCE_SCOPE_SOURCE_MUST_NOT_EXECUTE = True
EVIDENCE_SCOPE_SOURCE_EXECUTION_ALLOWED = False


def _require_token(value: object, field_name: str, *, maximum: int = 192) -> str:
    """Validate one bounded, whitespace-free identifier."""

    if (
        type(value) is not str
        or not value
        or value.strip() != value
        or len(value) > maximum
        or any(character.isspace() for character in value)
    ):
        raise ValueError(f"{field_name} must be a bounded canonical token")
    return value


def _require_hash(value: object, field_name: str) -> str:
    """Validate one lowercase SHA-256 digest."""

    if (
        type(value) is not str
        or len(value) != 64
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise ValueError(f"{field_name} must be a lowercase SHA-256 digest")
    return value


def _require_aware(value: object, field_name: str) -> datetime:
    """Validate one exact timezone-aware datetime."""

    if type(value) is not datetime or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be an exact timezone-aware datetime")
    return value


def _utc_text(value: datetime) -> str:
    """Serialize an aware datetime in canonical UTC microsecond notation."""

    return value.astimezone(UTC).isoformat(timespec="microseconds").replace("+00:00", "Z")


def _domain_hash(domain: str, payload: dict[str, object]) -> str:
    """Hash a canonical payload under an explicit domain separator."""

    _require_token(domain, "domain")
    encoded = json.dumps(
        {"domain": domain, "payload": payload},
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


@dataclass(frozen=True, slots=True)
class EvidenceScopeSourceV1:
    """Immutable owner/tenant evidence-scope fact.

    ``owner`` is the fixed Research namespace.  ``owner_id`` is the exact
    server-resolved owner identity; it is kept separate from the artifact's
    application owner so a caller cannot confuse a user scope with a module
    namespace.  The source is permanently read-only and cannot authorize
    execution, even when its temporal validity window is open.
    """

    source_id: str
    source_version: str
    owner_id: str
    tenant_id: str
    account_id: str
    actor_id: str
    artifact: ArtifactRef
    status: str
    recorded_at: datetime
    valid_until: datetime
    root_claim_hash: str | None = None
    supersedes_content_hash: str | None = None
    identity_hash: str = ""
    content_hash: str = ""
    owner: str = EVIDENCE_SCOPE_SOURCE_OWNER
    artifact_type: str = EVIDENCE_SCOPE_SOURCE_ARTIFACT_TYPE
    schema: str = EVIDENCE_SCOPE_SOURCE_SCHEMA
    permission: str = EVIDENCE_SCOPE_SOURCE_PERMISSION
    must_not_execute: bool = EVIDENCE_SCOPE_SOURCE_MUST_NOT_EXECUTE
    execution_allowed: bool = EVIDENCE_SCOPE_SOURCE_EXECUTION_ALLOWED

    def __post_init__(self) -> None:
        """Validate exact refs, clocks, chain anchor, and canonical hashes."""

        for field_name in (
            "source_id",
            "source_version",
            "owner_id",
            "tenant_id",
            "account_id",
            "actor_id",
        ):
            _require_token(getattr(self, field_name), field_name)

        if type(self.artifact) is not ArtifactRef:
            raise TypeError("artifact must be an exact ArtifactRef")
        ArtifactRef.__post_init__(self.artifact)
        if self.artifact.owner != EVIDENCE_SCOPE_SOURCE_OWNER:
            raise ValueError("artifact owner must be the fixed Research namespace")

        if (
            self.owner,
            self.artifact_type,
            self.schema,
            self.permission,
            self.must_not_execute,
            self.execution_allowed,
        ) != (
            EVIDENCE_SCOPE_SOURCE_OWNER,
            EVIDENCE_SCOPE_SOURCE_ARTIFACT_TYPE,
            EVIDENCE_SCOPE_SOURCE_SCHEMA,
            EVIDENCE_SCOPE_SOURCE_PERMISSION,
            EVIDENCE_SCOPE_SOURCE_MUST_NOT_EXECUTE,
            EVIDENCE_SCOPE_SOURCE_EXECUTION_ALLOWED,
        ):
            raise ValueError("evidence scope source fixed semantics are invalid")
        if type(self.status) is not str or self.status not in {"active", "revoked"}:
            raise ValueError("status must be active or revoked")

        recorded_at = _require_aware(self.recorded_at, "recorded_at")
        valid_until = _require_aware(self.valid_until, "valid_until")
        if not recorded_at < valid_until:
            raise ValueError("recorded_at must precede valid_until")

        is_root = self.root_claim_hash is not None
        has_predecessor = self.supersedes_content_hash is not None
        if is_root == has_predecessor:
            raise ValueError("exactly one root claim or predecessor is required")
        if is_root:
            _require_hash(self.root_claim_hash, "root_claim_hash")
            expected_root = root_claim_hash_for_evidence_scope_source_v1(
                source_id=self.source_id,
                owner_id=self.owner_id,
                tenant_id=self.tenant_id,
                account_id=self.account_id,
                actor_id=self.actor_id,
                artifact=self.artifact,
            )
            if self.root_claim_hash != expected_root:
                raise ValueError("root_claim_hash does not bind the exact scope identity")
        else:
            _require_hash(self.supersedes_content_hash, "supersedes_content_hash")

        expected_identity_hash = _domain_hash(
            "agomtradepro:research:evidence-scope-source:v1/identity",
            self._identity_payload(),
        )
        if not self.identity_hash:
            object.__setattr__(self, "identity_hash", expected_identity_hash)
        else:
            _require_hash(self.identity_hash, "identity_hash")
            if self.identity_hash != expected_identity_hash:
                raise ValueError("identity_hash does not match the exact scope identity")

        expected_content_hash = _domain_hash(
            "agomtradepro:research:evidence-scope-source:v1/content",
            {**self._content_payload(), "identity_hash": self.identity_hash},
        )
        if not self.content_hash:
            object.__setattr__(self, "content_hash", expected_content_hash)
        else:
            _require_hash(self.content_hash, "content_hash")
            if self.content_hash != expected_content_hash:
                raise ValueError("content_hash does not match the scope source")

    @property
    def artifact_ref(self) -> ArtifactRef:
        """Return the exact evidence artifact reference."""

        return self.artifact

    @property
    def scope_id(self) -> str:
        """Return the source identity under the scope vocabulary."""

        return self.source_id

    @property
    def scope_version(self) -> str:
        """Return the source version under the scope vocabulary."""

        return self.source_version

    @property
    def predecessor_content_hash(self) -> str | None:
        """Return the exact predecessor hash, or ``None`` for a root."""

        return self.supersedes_content_hash

    def _identity_payload(self) -> dict[str, object]:
        return {
            "owner": self.owner,
            "artifact_type": self.artifact_type,
            "schema": self.schema,
            "source_id": self.source_id,
            "source_version": self.source_version,
            "owner_id": self.owner_id,
            "tenant_id": self.tenant_id,
            "account_id": self.account_id,
            "actor_id": self.actor_id,
            "artifact": self.artifact.to_payload(),
        }

    def _content_payload(self) -> dict[str, object]:
        return {
            **self._identity_payload(),
            "status": self.status,
            "recorded_at": _utc_text(self.recorded_at),
            "valid_until": _utc_text(self.valid_until),
            "root_claim_hash": self.root_claim_hash,
            "supersedes_content_hash": self.supersedes_content_hash,
            "permission": self.permission,
            "must_not_execute": self.must_not_execute,
            "execution_allowed": self.execution_allowed,
        }

    def is_knowable_at(self, as_of: datetime) -> bool:
        """Return historical PIT knowability without falling back to another row."""

        return self.recorded_at <= _require_aware(as_of, "as_of")

    def is_historical_at(self, as_of: datetime) -> bool:
        """Alias for the historical PIT predicate."""

        return self.is_knowable_at(as_of)

    def is_temporally_current_at(self, as_of: datetime) -> bool:
        """Return whether this exact source is active at the supplied cutoff."""

        cutoff = _require_aware(as_of, "as_of")
        return self.status == "active" and self.recorded_at <= cutoff < self.valid_until

    def is_current_at(self, as_of: datetime) -> bool:
        """Alias for temporal currentness of this exact source."""

        return self.is_temporally_current_at(as_of)

    def to_payload(self) -> dict[str, object]:
        """Return the canonical secret-free source projection."""

        return {
            **self._content_payload(),
            "identity_hash": self.identity_hash,
            "content_hash": self.content_hash,
        }


def root_claim_hash_for_evidence_scope_source_v1(
    *,
    source_id: str,
    owner_id: str,
    tenant_id: str,
    account_id: str,
    actor_id: str,
    artifact: ArtifactRef,
) -> str:
    """Return the candidate-independent root claim for one exact scope."""

    for field_name, value in (
        ("source_id", source_id),
        ("owner_id", owner_id),
        ("tenant_id", tenant_id),
        ("account_id", account_id),
        ("actor_id", actor_id),
    ):
        _require_token(value, field_name)
    if type(artifact) is not ArtifactRef:
        raise TypeError("artifact must be an exact ArtifactRef")
    ArtifactRef.__post_init__(artifact)
    if artifact.owner != EVIDENCE_SCOPE_SOURCE_OWNER:
        raise ValueError("artifact owner must be the fixed Research namespace")
    return _domain_hash(
        "agomtradepro:research:evidence-scope-source:v1/root-claim",
        {
            "owner": EVIDENCE_SCOPE_SOURCE_OWNER,
            "artifact_type": EVIDENCE_SCOPE_SOURCE_ARTIFACT_TYPE,
            "schema": EVIDENCE_SCOPE_SOURCE_SCHEMA,
            "source_id": source_id,
            "owner_id": owner_id,
            "tenant_id": tenant_id,
            "account_id": account_id,
            "actor_id": actor_id,
            "artifact": artifact.to_payload(),
        },
    )


def validate_evidence_scope_source_v1_successor(
    previous: EvidenceScopeSourceV1,
    successor: EvidenceScopeSourceV1,
) -> None:
    """Validate one adjacent same-scope successor; persistence supplies CAS."""

    if type(previous) is not EvidenceScopeSourceV1:
        raise TypeError("previous must be an exact EvidenceScopeSourceV1")
    if type(successor) is not EvidenceScopeSourceV1:
        raise TypeError("successor must be an exact EvidenceScopeSourceV1")
    previous.__post_init__()
    successor.__post_init__()
    if previous.status == "revoked":
        raise ValueError("revoked evidence scope source is terminal")
    if successor.supersedes_content_hash != previous.content_hash:
        raise ValueError("successor does not bind the exact predecessor")
    for field_name in ("source_id", "owner_id", "tenant_id", "account_id", "actor_id"):
        if getattr(successor, field_name) != getattr(previous, field_name):
            raise ValueError(f"successor changed {field_name}")
    if successor.artifact != previous.artifact:
        raise ValueError("successor changed artifact identity")
    if successor.source_version == previous.source_version:
        raise ValueError("source_version must advance")
    if successor.recorded_at <= previous.recorded_at:
        raise ValueError("successor recorded_at must advance")


def validate_evidence_scope_source_successor(
    previous: EvidenceScopeSourceV1,
    successor: EvidenceScopeSourceV1,
) -> None:
    """Compatibility alias for the versioned successor validator."""

    validate_evidence_scope_source_v1_successor(previous, successor)


EvidenceOwnerTenantScopeSourceV1 = EvidenceScopeSourceV1

__all__ = [
    "EVIDENCE_SCOPE_SOURCE_ARTIFACT_TYPE",
    "EVIDENCE_SCOPE_SOURCE_EXECUTION_ALLOWED",
    "EVIDENCE_SCOPE_SOURCE_MUST_NOT_EXECUTE",
    "EVIDENCE_SCOPE_SOURCE_OWNER",
    "EVIDENCE_SCOPE_SOURCE_PERMISSION",
    "EVIDENCE_SCOPE_SOURCE_SCHEMA",
    "EvidenceOwnerTenantScopeSourceV1",
    "EvidenceScopeSourceV1",
    "root_claim_hash_for_evidence_scope_source_v1",
    "validate_evidence_scope_source_successor",
    "validate_evidence_scope_source_v1_successor",
]
