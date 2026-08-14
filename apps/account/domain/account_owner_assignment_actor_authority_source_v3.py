"""Pure Account-owned actor-authority source v3 evidence."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, fields
from datetime import UTC, datetime

OWNER = "account"
ARTIFACT_TYPE = "account_owner_assignment_actor_authority_source_v3"
SCHEMA = "account.owner_assignment_actor_authority_source.v3"
PERMISSION = "attestation_only"
STATUS = "inactive"
MUST_NOT_EXECUTE = True
TERMINAL_STATES = frozenset({"revoked", "deactivated"})
AUTHORITY_STATES = frozenset({"current", *TERMINAL_STATES})


def _token(value: object, name: str) -> str:
    if (
        type(value) is not str
        or not value
        or value.strip() != value
        or len(value) > 192
        or any(character.isspace() for character in value)
    ):
        raise ValueError(f"{name} must be a bounded canonical token")
    return value


def _digest(value: object, name: str) -> str:
    if (
        type(value) is not str
        or len(value) != 64
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise ValueError(f"{name} must be a lowercase SHA-256 digest")
    return value


def _aware(value: object, name: str) -> datetime:
    if type(value) is not datetime or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{name} must be an exact timezone-aware datetime")
    return value


def _utc_text(value: datetime) -> str:
    return value.astimezone(UTC).isoformat(timespec="microseconds").replace("+00:00", "Z")


def _hash(domain: str, payload: dict[str, object]) -> str:
    encoded = json.dumps(
        {"domain": domain, "payload": payload},
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


@dataclass(frozen=True, slots=True)
class AccountOwnerAssignmentActorAuthoritySourceV3:
    """Immutable attestation of one session-bound Account actor authority state."""

    source_id: str
    source_version: str
    principal_id: str
    user_id: int
    authentication_context_id: str
    authentication_context_version: str
    authentication_context_identity_hash: str
    authentication_context_content_hash: str
    user_source_id: str
    user_source_version: str
    user_source_content_hash: str
    rbac_source_id: str
    rbac_source_version: str
    rbac_source_content_hash: str
    actor_id: str
    is_authenticated: bool
    is_active: bool
    is_staff: bool
    is_superuser: bool
    rbac_role: str
    authority_state: str
    principal_authenticated_at: datetime
    principal_valid_until: datetime
    source_recorded_at: datetime
    source_valid_until: datetime
    issued_at: datetime
    recorded_at: datetime
    ttl_valid_until: datetime
    valid_until: datetime
    root_claim_hash: str | None = None
    supersedes_content_hash: str | None = None
    identity_hash: str = ""
    principal_seal: str = ""
    authentication_context_seal: str = ""
    user_seal: str = ""
    rbac_seal: str = ""
    facts_seal: str = ""
    clock_seal: str = ""
    chain_seal: str = ""
    fixed_authority_seal: str = ""
    record_seal: str = ""
    content_hash: str = ""
    owner: str = OWNER
    artifact_type: str = ARTIFACT_TYPE
    schema: str = SCHEMA
    permission: str = PERMISSION
    status: str = STATUS
    must_not_execute: bool = MUST_NOT_EXECUTE
    execution_allowed: bool = False

    def __post_init__(self) -> None:
        """Validate exact evidence, clocks, chain root, and every canonical seal."""

        self._validate_fixed()
        for name in (
            "source_id",
            "source_version",
            "principal_id",
            "authentication_context_id",
            "authentication_context_version",
            "user_source_id",
            "user_source_version",
            "rbac_source_id",
            "rbac_source_version",
            "actor_id",
            "rbac_role",
            "authority_state",
        ):
            _token(getattr(self, name), name)
        if self.authority_state not in AUTHORITY_STATES:
            raise ValueError("authority_state is invalid")
        if type(self.user_id) is not int or self.user_id <= 0:
            raise ValueError("user_id must be an exact positive integer")
        for name in ("is_authenticated", "is_active", "is_staff", "is_superuser"):
            if type(getattr(self, name)) is not bool:
                raise TypeError(f"{name} must be an exact boolean")
        if self.authority_state == "current" and (not self.is_authenticated or not self.is_active):
            raise ValueError("current authority facts must be authenticated and active")
        if self.authority_state in TERMINAL_STATES and self.is_authenticated:
            raise ValueError("terminal authority cannot remain authenticated")
        for name in (
            "authentication_context_identity_hash",
            "authentication_context_content_hash",
            "user_source_content_hash",
            "rbac_source_content_hash",
        ):
            _digest(getattr(self, name), name)
        for name in (
            "principal_authenticated_at",
            "principal_valid_until",
            "source_recorded_at",
            "source_valid_until",
            "issued_at",
            "recorded_at",
            "ttl_valid_until",
            "valid_until",
        ):
            _aware(getattr(self, name), name)
        if not (
            self.principal_authenticated_at
            <= self.source_recorded_at
            <= self.issued_at
            <= self.recorded_at
            < self.valid_until
        ):
            raise ValueError("actor authority source clock sequence is invalid")
        if self.valid_until != min(
            self.principal_valid_until, self.source_valid_until, self.ttl_valid_until
        ):
            raise ValueError("valid_until must equal all three authority upper bounds")
        self._validate_chain()
        self._seal("identity_hash", self._identity_payload())
        self._seal("principal_seal", self._principal_payload())
        self._seal("authentication_context_seal", self._context_payload())
        self._seal("user_seal", self._user_payload())
        self._seal("rbac_seal", self._rbac_payload())
        self._seal("facts_seal", self._facts_payload())
        self._seal("clock_seal", self._clock_payload())
        self._seal("chain_seal", self._chain_payload())
        self._seal("fixed_authority_seal", self._fixed_payload())
        self._seal("record_seal", self._record_payload())
        self._seal("content_hash", self._content_payload())

    def _validate_fixed(self) -> None:
        if (
            self.owner,
            self.artifact_type,
            self.schema,
            self.permission,
            self.status,
            self.must_not_execute,
            self.execution_allowed,
        ) != (OWNER, ARTIFACT_TYPE, SCHEMA, PERMISSION, STATUS, MUST_NOT_EXECUTE, False):
            raise ValueError("actor authority source fixed semantics are invalid")

    def _validate_chain(self) -> None:
        is_root = self.root_claim_hash is not None
        if is_root == (self.supersedes_content_hash is not None):
            raise ValueError("exactly one root claim or predecessor is required")
        if is_root:
            expected = _hash("actor-authority-v3/root-claim", self._root_claim_payload())
            if _digest(self.root_claim_hash, "root_claim_hash") != expected:
                raise ValueError("root_claim_hash is invalid")
        else:
            _digest(self.supersedes_content_hash, "supersedes_content_hash")

    def _seal(self, name: str, payload: dict[str, object]) -> None:
        expected = _hash(f"actor-authority-v3/{name}", payload)
        observed = getattr(self, name)
        if observed == "":
            object.__setattr__(self, name, expected)
        elif _digest(observed, name) != expected:
            raise ValueError(f"{name} is invalid")

    def _root_claim_payload(self) -> dict[str, object]:
        return {
            "artifact_type": self.artifact_type,
            "actor_id": self.actor_id,
            "authentication_context_identity_hash": self.authentication_context_identity_hash,
            "owner": self.owner,
            "principal_id": self.principal_id,
            "source_id": self.source_id,
            "user_id": self.user_id,
        }

    def _identity_payload(self) -> dict[str, object]:
        return {
            **self._root_claim_payload(),
            "source_version": self.source_version,
        }

    def _principal_payload(self) -> dict[str, object]:
        return {
            "principal_authenticated_at": _utc_text(self.principal_authenticated_at),
            "principal_id": self.principal_id,
            "principal_valid_until": _utc_text(self.principal_valid_until),
            "user_id": self.user_id,
        }

    def _context_payload(self) -> dict[str, object]:
        return {
            "authentication_context_content_hash": self.authentication_context_content_hash,
            "authentication_context_id": self.authentication_context_id,
            "authentication_context_identity_hash": self.authentication_context_identity_hash,
            "authentication_context_version": self.authentication_context_version,
        }

    def _user_payload(self) -> dict[str, object]:
        return {
            "user_source_content_hash": self.user_source_content_hash,
            "user_source_id": self.user_source_id,
            "user_source_version": self.user_source_version,
        }

    def _rbac_payload(self) -> dict[str, object]:
        return {
            "rbac_source_content_hash": self.rbac_source_content_hash,
            "rbac_source_id": self.rbac_source_id,
            "rbac_source_version": self.rbac_source_version,
        }

    def _facts_payload(self) -> dict[str, object]:
        return {
            "actor_id": self.actor_id,
            "authority_state": self.authority_state,
            "is_active": self.is_active,
            "is_authenticated": self.is_authenticated,
            "is_staff": self.is_staff,
            "is_superuser": self.is_superuser,
            "rbac_role": self.rbac_role,
        }

    def _clock_payload(self) -> dict[str, object]:
        return {
            "issued_at": _utc_text(self.issued_at),
            "recorded_at": _utc_text(self.recorded_at),
            "source_recorded_at": _utc_text(self.source_recorded_at),
            "source_valid_until": _utc_text(self.source_valid_until),
            "ttl_valid_until": _utc_text(self.ttl_valid_until),
            "valid_until": _utc_text(self.valid_until),
        }

    def _chain_payload(self) -> dict[str, object]:
        return {
            "root_claim_hash": self.root_claim_hash,
            "supersedes_content_hash": self.supersedes_content_hash,
        }

    def _fixed_payload(self) -> dict[str, object]:
        return {
            "artifact_type": self.artifact_type,
            "execution_allowed": self.execution_allowed,
            "must_not_execute": self.must_not_execute,
            "owner": self.owner,
            "permission": self.permission,
            "schema": self.schema,
            "status": self.status,
        }

    def _record_payload(self) -> dict[str, object]:
        return {
            "authentication_context_seal": self.authentication_context_seal,
            "chain_seal": self.chain_seal,
            "clock_seal": self.clock_seal,
            "facts_seal": self.facts_seal,
            "fixed_authority_seal": self.fixed_authority_seal,
            "identity_hash": self.identity_hash,
            "principal_seal": self.principal_seal,
            "rbac_seal": self.rbac_seal,
            "user_seal": self.user_seal,
        }

    def _content_payload(self) -> dict[str, object]:
        return {**self._record_payload(), "record_seal": self.record_seal}

    def is_knowable_at(self, as_of: datetime) -> bool:
        """Return whether this immutable version was recorded by the PIT cutoff."""

        return self.recorded_at <= _aware(as_of, "as_of")

    def is_temporally_current_at(self, as_of: datetime) -> bool:
        """Return temporal validity only; this does not prove ledger-head currentness."""

        cutoff = _aware(as_of, "as_of")
        return (
            self.authority_state == "current"
            and self.is_authenticated
            and self.is_active
            and self.recorded_at <= cutoff < self.valid_until
        )

    def to_payload(self) -> dict[str, object]:
        """Return a complete canonical payload containing no authentication secret."""

        payload: dict[str, object] = {}
        for field in fields(self):
            value = getattr(self, field.name)
            payload[field.name] = _utc_text(value) if type(value) is datetime else value
        return payload


def root_claim_hash_for_actor_authority_source_v3(
    *,
    source_id: str,
    principal_id: str,
    user_id: int,
    authentication_context_identity_hash: str,
    actor_id: str,
) -> str:
    """Return the candidate-independent root claim for one authenticated session chain."""

    _token(source_id, "source_id")
    _token(principal_id, "principal_id")
    if type(user_id) is not int or user_id <= 0:
        raise ValueError("user_id must be an exact positive integer")
    _digest(authentication_context_identity_hash, "authentication_context_identity_hash")
    _token(actor_id, "actor_id")
    return _hash(
        "actor-authority-v3/root-claim",
        {
            "artifact_type": ARTIFACT_TYPE,
            "actor_id": actor_id,
            "authentication_context_identity_hash": authentication_context_identity_hash,
            "owner": OWNER,
            "principal_id": principal_id,
            "source_id": source_id,
            "user_id": user_id,
        },
    )


def validate_account_owner_assignment_actor_authority_source_v3_successor(
    previous: AccountOwnerAssignmentActorAuthoritySourceV3,
    successor: AccountOwnerAssignmentActorAuthoritySourceV3,
) -> None:
    """Validate one adjacent version in the same authentication-session chain."""

    if (
        type(previous) is not AccountOwnerAssignmentActorAuthoritySourceV3
        or type(successor) is not AccountOwnerAssignmentActorAuthoritySourceV3
    ):
        raise TypeError("authority predecessor and successor must be exact v3 sources")
    previous.__post_init__()
    successor.__post_init__()
    if previous.authority_state in TERMINAL_STATES:
        raise ValueError("terminal authority cannot have a successor")
    if successor.supersedes_content_hash != previous.content_hash:
        raise ValueError("successor does not bind the exact authority predecessor")
    for name in (
        "source_id",
        "principal_id",
        "user_id",
        "authentication_context_id",
        "authentication_context_identity_hash",
        "actor_id",
    ):
        if getattr(successor, name) != getattr(previous, name):
            raise ValueError(f"successor changed session-chain {name}")
    if successor.source_version == previous.source_version:
        raise ValueError("successor source_version must advance")
    if successor.recorded_at <= previous.recorded_at:
        raise ValueError("successor recorded_at must advance")
    if not (
        previous.recorded_at
        < successor.source_recorded_at
        <= successor.issued_at
        <= successor.recorded_at
    ):
        raise ValueError("successor source and recording clocks must advance")


__all__ = [
    "AccountOwnerAssignmentActorAuthoritySourceV3",
    "root_claim_hash_for_actor_authority_source_v3",
    "validate_account_owner_assignment_actor_authority_source_v3_successor",
]
