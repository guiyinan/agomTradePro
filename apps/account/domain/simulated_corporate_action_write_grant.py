"""Explicit finite grants for the simulated corporate-action service writer.

The records in this module seal facts supplied by a future trusted issuer. A
well-formed grant or evidence hash alone does not authenticate its issuer.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime

from apps.account.domain.simulated_corporate_action_write_capabilities import (
    SimulatedCorporateActionWriteCapability,
    validate_simulated_corporate_action_write_capabilities,
)

SIMULATED_CORPORATE_ACTION_STAGE_WRITE_PERMISSION = "simulated_corporate_action_stage_write"
SIMULATED_CORPORATE_ACTION_SERVICE_ACTOR_ID = "simulated-trading"
SIMULATED_CORPORATE_ACTION_WRITE_GRANT_SCHEMA = "account.simulated_corporate_action_write_grant.v1"
SIMULATED_CORPORATE_ACTION_WRITE_GRANT_V2_SCHEMA = (
    "account.simulated_corporate_action_write_grant.v2"
)
SIMULATED_CORPORATE_ACTION_WRITE_GRANT_V2_PERMISSION = (
    "simulated_corporate_action_capability_bundle"
)
SIMULATED_CORPORATE_ACTION_WRITE_GRANT_REVOCATION_SCHEMA = (
    "account.simulated_corporate_action_write_grant.revocation.v1"
)

_GRANT_IDENTITY_HASH_DOMAIN = "account.simulated-corporate-action-write-grant.v1/identity"
_GRANT_CONTENT_HASH_DOMAIN = "account.simulated-corporate-action-write-grant.v1/content"
_GRANT_V2_CONTENT_HASH_DOMAIN = "account.simulated-corporate-action-write-grant.v2/content"
_REVOCATION_IDENTITY_HASH_DOMAIN = (
    "account.simulated-corporate-action-write-grant-revocation.v1/identity"
)
_REVOCATION_CONTENT_HASH_DOMAIN = (
    "account.simulated-corporate-action-write-grant-revocation.v1/content"
)


def _token(value: object, name: str) -> str:
    """Validate one bounded canonical identity token."""

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
    """Validate one lowercase SHA-256 digest."""

    if (
        type(value) is not str
        or len(value) != 64
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise ValueError(f"{name} must be a lowercase SHA-256 digest")
    return value


def _aware(value: object, name: str) -> datetime:
    """Validate one exact timezone-aware timestamp."""

    if type(value) is not datetime or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{name} must be an exact timezone-aware datetime")
    return value


def _utc_text(value: datetime) -> str:
    """Serialize one aware timestamp with stable UTC microsecond precision."""

    return value.astimezone(UTC).isoformat(timespec="microseconds").replace("+00:00", "Z")


def _hash(domain: str, payload: dict[str, object]) -> str:
    """Hash canonical JSON under an independent domain separator."""

    encoded = json.dumps(
        {"domain": domain, "payload": payload},
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _set_or_validate_hash(instance: object, name: str, expected: str) -> None:
    """Fill one omitted frozen hash or reject a supplied value that differs."""

    observed = getattr(instance, name)
    if type(observed) is not str:
        raise TypeError(f"{name} must be an exact string")
    if observed == "":
        object.__setattr__(instance, name, expected)
    elif _digest(observed, name) != expected:
        raise ValueError(f"{name} does not match its exact facts")


@dataclass(frozen=True, slots=True)
class SimulatedCorporateActionWriteGrantBinding:
    """Bind one simulated account and owner/tenant scope to exact source and policy facts."""

    account_namespace: str
    account_id: str
    owner_user_id: int
    tenant_id: str
    owner_id: str
    account_source_id: str
    account_source_version: str
    account_source_content_hash: str
    policy_id: str
    policy_version: str
    policy_content_hash: str

    def __post_init__(self) -> None:
        """Reject physical-account aliases and incomplete source or policy identity."""

        if self.account_namespace != "simulated":
            raise ValueError("account_namespace must be the exact simulated namespace")
        for name in (
            "account_namespace",
            "account_id",
            "tenant_id",
            "owner_id",
            "account_source_id",
            "account_source_version",
            "policy_id",
            "policy_version",
        ):
            _token(getattr(self, name), name)
        if type(self.owner_user_id) is not int or self.owner_user_id <= 0:
            raise ValueError("owner_user_id must be an exact positive integer")
        _digest(self.account_source_content_hash, "account_source_content_hash")
        _digest(self.policy_content_hash, "policy_content_hash")

    def to_payload(self) -> dict[str, object]:
        """Return all exact account, owner/tenant, source and policy selectors."""

        self.__post_init__()
        return {
            "account_namespace": self.account_namespace,
            "account_id": self.account_id,
            "owner_user_id": self.owner_user_id,
            "tenant_id": self.tenant_id,
            "owner_id": self.owner_id,
            "account_source_id": self.account_source_id,
            "account_source_version": self.account_source_version,
            "account_source_content_hash": self.account_source_content_hash,
            "policy_id": self.policy_id,
            "policy_version": self.policy_version,
            "policy_content_hash": self.policy_content_hash,
        }


@dataclass(frozen=True, slots=True)
class SimulatedCorporateActionWriteGrantSelector:
    """Select one immutable grant version by exact identity, content and scope."""

    grant_id: str
    grant_version: str
    identity_hash: str
    content_hash: str
    binding: SimulatedCorporateActionWriteGrantBinding

    def __post_init__(self) -> None:
        """Validate every selector and its exact scope binding."""

        for name in ("grant_id", "grant_version"):
            _token(getattr(self, name), name)
        _digest(self.identity_hash, "identity_hash")
        _digest(self.content_hash, "content_hash")
        if type(self.binding) is not SimulatedCorporateActionWriteGrantBinding:
            raise TypeError("binding must be an exact simulated write grant binding")
        self.binding.__post_init__()


@dataclass(frozen=True, slots=True)
class SimulatedCorporateActionWriteGrant:
    """One immutable, finite, source-bound service permission with explicit evidence hashes."""

    grant_id: str
    grant_version: str
    binding: SimulatedCorporateActionWriteGrantBinding
    consent_evidence_id: str
    consent_evidence_version: str
    consent_evidence_hash: str
    issuer_evidence_id: str
    issuer_evidence_version: str
    issuer_evidence_hash: str
    consented_at: datetime
    issued_at: datetime
    recorded_at: datetime
    valid_until: datetime
    supersedes_content_hash: str | None = None
    permission: str = SIMULATED_CORPORATE_ACTION_STAGE_WRITE_PERMISSION
    service_actor_id: str = SIMULATED_CORPORATE_ACTION_SERVICE_ACTOR_ID
    schema: str = SIMULATED_CORPORATE_ACTION_WRITE_GRANT_SCHEMA
    identity_hash: str = ""
    content_hash: str = ""
    capabilities: tuple[SimulatedCorporateActionWriteCapability, ...] | None = None
    terms_version: str | None = None
    terms_sha256: str | None = None

    def __post_init__(self) -> None:
        """Validate fixed permission, exact scope, evidence, clocks and canonical hashes."""

        for name in ("grant_id", "grant_version"):
            _token(getattr(self, name), name)
        if type(self.binding) is not SimulatedCorporateActionWriteGrantBinding:
            raise TypeError("binding must be an exact simulated write grant binding")
        self.binding.__post_init__()
        if self.service_actor_id != SIMULATED_CORPORATE_ACTION_SERVICE_ACTOR_ID:
            raise ValueError("grant service actor is fixed")
        if self.schema == SIMULATED_CORPORATE_ACTION_WRITE_GRANT_SCHEMA:
            if self.permission != SIMULATED_CORPORATE_ACTION_STAGE_WRITE_PERMISSION:
                raise ValueError("grant permission is fixed")
            if any(
                value is not None
                for value in (self.capabilities, self.terms_version, self.terms_sha256)
            ):
                raise ValueError("V1 grants cannot contain V2 capability or terms fields")
            content_domain = _GRANT_CONTENT_HASH_DOMAIN
        elif self.schema == SIMULATED_CORPORATE_ACTION_WRITE_GRANT_V2_SCHEMA:
            if self.permission != SIMULATED_CORPORATE_ACTION_WRITE_GRANT_V2_PERMISSION:
                raise ValueError("V2 grant permission marker is fixed")
            if self.capabilities is None:
                raise ValueError("V2 grant capabilities are required")
            validate_simulated_corporate_action_write_capabilities(self.capabilities)
            if self.terms_version is None:
                raise ValueError("V2 grant terms_version is required")
            _token(self.terms_version, "terms_version")
            if self.terms_sha256 is None:
                raise ValueError("V2 grant terms_sha256 is required")
            _digest(self.terms_sha256, "terms_sha256")
            content_domain = _GRANT_V2_CONTENT_HASH_DOMAIN
        else:
            raise ValueError("grant schema is fixed")
        for name in (
            "consent_evidence_id",
            "consent_evidence_version",
            "issuer_evidence_id",
            "issuer_evidence_version",
        ):
            _token(getattr(self, name), name)
        _digest(self.consent_evidence_hash, "consent_evidence_hash")
        _digest(self.issuer_evidence_hash, "issuer_evidence_hash")
        consented_at = _aware(self.consented_at, "consented_at")
        issued_at = _aware(self.issued_at, "issued_at")
        recorded_at = _aware(self.recorded_at, "recorded_at")
        valid_until = _aware(self.valid_until, "valid_until")
        if not consented_at <= issued_at <= recorded_at < valid_until:
            raise ValueError("grant clock sequence or finite validity interval is invalid")
        if self.supersedes_content_hash is not None:
            _digest(self.supersedes_content_hash, "supersedes_content_hash")
        _set_or_validate_hash(
            self, "identity_hash", _hash(_GRANT_IDENTITY_HASH_DOMAIN, self._identity_payload())
        )
        _set_or_validate_hash(self, "content_hash", _hash(content_domain, self._content_payload()))

    @property
    def selector(self) -> SimulatedCorporateActionWriteGrantSelector:
        """Return the exact immutable selector expected by a current-grant reader."""

        self.__post_init__()
        return SimulatedCorporateActionWriteGrantSelector(
            grant_id=self.grant_id,
            grant_version=self.grant_version,
            identity_hash=self.identity_hash,
            content_hash=self.content_hash,
            binding=self.binding,
        )

    def is_active_at(self, as_of: datetime) -> bool:
        """Return whether this finite grant is current in its own half-open time interval."""

        self.__post_init__()
        cutoff = _aware(as_of, "as_of")
        return self.recorded_at <= cutoff < self.valid_until

    @property
    def effective_capabilities(self) -> tuple[SimulatedCorporateActionWriteCapability, ...]:
        """Return the explicit V2 set or the fixed legacy cash capability for V1."""

        self.__post_init__()
        if self.schema == SIMULATED_CORPORATE_ACTION_WRITE_GRANT_SCHEMA:
            return (SimulatedCorporateActionWriteCapability.CASH_STAGE_WRITE,)
        if self.capabilities is None:
            raise ValueError("V2 grant capabilities are required")
        return validate_simulated_corporate_action_write_capabilities(self.capabilities)

    def supports_capability(self, capability: SimulatedCorporateActionWriteCapability) -> bool:
        """Return whether this grant explicitly includes one exact known capability."""

        if type(capability) is not SimulatedCorporateActionWriteCapability:
            raise TypeError("capability must be an exact known enum value")
        return capability in self.effective_capabilities

    def to_payload(self) -> dict[str, object]:
        """Return every immutable grant fact and both canonical hashes."""

        self.__post_init__()
        return {
            **self._content_payload(),
            "identity_hash": self.identity_hash,
            "content_hash": self.content_hash,
        }

    def _identity_payload(self) -> dict[str, object]:
        """Return the stable chain identity, excluding renewable source/policy versions."""

        return {
            "grant_id": self.grant_id,
            # Chain identity is version-neutral: V2 changes the content marker, not the
            # owner/account chain identity established by the original V1 contract.
            "permission": SIMULATED_CORPORATE_ACTION_STAGE_WRITE_PERMISSION,
            "service_actor_id": self.service_actor_id,
            "account_namespace": self.binding.account_namespace,
            "account_id": self.binding.account_id,
            "owner_user_id": self.binding.owner_user_id,
            "tenant_id": self.binding.tenant_id,
            "owner_id": self.binding.owner_id,
        }

    def _content_payload(self) -> dict[str, object]:
        """Serialize the full grant, evidence hashes, source lineage and validity clocks."""

        payload: dict[str, object] = {
            "schema": self.schema,
            "grant_id": self.grant_id,
            "grant_version": self.grant_version,
            "permission": self.permission,
            "service_actor_id": self.service_actor_id,
            "binding": self.binding.to_payload(),
            "consent_evidence_id": self.consent_evidence_id,
            "consent_evidence_version": self.consent_evidence_version,
            "consent_evidence_hash": self.consent_evidence_hash,
            "issuer_evidence_id": self.issuer_evidence_id,
            "issuer_evidence_version": self.issuer_evidence_version,
            "issuer_evidence_hash": self.issuer_evidence_hash,
            "consented_at": _utc_text(self.consented_at),
            "issued_at": _utc_text(self.issued_at),
            "recorded_at": _utc_text(self.recorded_at),
            "valid_until": _utc_text(self.valid_until),
            "supersedes_content_hash": self.supersedes_content_hash,
        }
        if self.schema == SIMULATED_CORPORATE_ACTION_WRITE_GRANT_V2_SCHEMA:
            if self.capabilities is None or self.terms_version is None or self.terms_sha256 is None:
                raise ValueError("V2 grant capabilities and terms are required")
            capabilities = validate_simulated_corporate_action_write_capabilities(self.capabilities)
            payload.update(
                {
                    "capabilities": [capability.value for capability in capabilities],
                    "terms_version": self.terms_version,
                    "terms_sha256": self.terms_sha256,
                }
            )
        return payload


@dataclass(frozen=True, slots=True)
class SimulatedCorporateActionWriteGrantRevocation:
    """One immutable revocation event tied to a specific grant version and evidence hashes."""

    revocation_id: str
    revocation_version: str
    grant_id: str
    grant_version: str
    grant_identity_hash: str
    grant_content_hash: str
    revocation_evidence_id: str
    revocation_evidence_version: str
    revocation_evidence_hash: str
    issuer_evidence_id: str
    issuer_evidence_version: str
    issuer_evidence_hash: str
    revoked_at: datetime
    recorded_at: datetime
    permission: str = SIMULATED_CORPORATE_ACTION_STAGE_WRITE_PERMISSION
    service_actor_id: str = SIMULATED_CORPORATE_ACTION_SERVICE_ACTOR_ID
    schema: str = SIMULATED_CORPORATE_ACTION_WRITE_GRANT_REVOCATION_SCHEMA
    identity_hash: str = ""
    content_hash: str = ""

    def __post_init__(self) -> None:
        """Validate fixed permission, exact target, evidence hashes, clocks and seals."""

        for name in ("revocation_id", "revocation_version", "grant_id", "grant_version"):
            _token(getattr(self, name), name)
        for name in (
            "grant_identity_hash",
            "grant_content_hash",
            "revocation_evidence_hash",
            "issuer_evidence_hash",
        ):
            _digest(getattr(self, name), name)
        for name in (
            "revocation_evidence_id",
            "revocation_evidence_version",
            "issuer_evidence_id",
            "issuer_evidence_version",
        ):
            _token(getattr(self, name), name)
        if self.permission != SIMULATED_CORPORATE_ACTION_STAGE_WRITE_PERMISSION:
            raise ValueError("revocation permission is fixed")
        if self.service_actor_id != SIMULATED_CORPORATE_ACTION_SERVICE_ACTOR_ID:
            raise ValueError("revocation service actor is fixed")
        if self.schema != SIMULATED_CORPORATE_ACTION_WRITE_GRANT_REVOCATION_SCHEMA:
            raise ValueError("revocation schema is fixed")
        revoked_at = _aware(self.revoked_at, "revoked_at")
        recorded_at = _aware(self.recorded_at, "recorded_at")
        if revoked_at > recorded_at:
            raise ValueError("revocation clock sequence is invalid")
        _set_or_validate_hash(
            self,
            "identity_hash",
            _hash(_REVOCATION_IDENTITY_HASH_DOMAIN, self._identity_payload()),
        )
        _set_or_validate_hash(
            self,
            "content_hash",
            _hash(_REVOCATION_CONTENT_HASH_DOMAIN, self._content_payload()),
        )

    def to_payload(self) -> dict[str, object]:
        """Return every immutable revocation fact and both canonical hashes."""

        self.__post_init__()
        return {
            **self._content_payload(),
            "identity_hash": self.identity_hash,
            "content_hash": self.content_hash,
        }

    def _identity_payload(self) -> dict[str, object]:
        """Return the exact revocation event and target identity."""

        return {
            "revocation_id": self.revocation_id,
            "permission": self.permission,
            "service_actor_id": self.service_actor_id,
            "grant_id": self.grant_id,
            "grant_version": self.grant_version,
            "grant_identity_hash": self.grant_identity_hash,
            "grant_content_hash": self.grant_content_hash,
        }

    def _content_payload(self) -> dict[str, object]:
        """Serialize the full revocation evidence and event clocks."""

        return {
            "schema": self.schema,
            **self._identity_payload(),
            "revocation_version": self.revocation_version,
            "revocation_evidence_id": self.revocation_evidence_id,
            "revocation_evidence_version": self.revocation_evidence_version,
            "revocation_evidence_hash": self.revocation_evidence_hash,
            "issuer_evidence_id": self.issuer_evidence_id,
            "issuer_evidence_version": self.issuer_evidence_version,
            "issuer_evidence_hash": self.issuer_evidence_hash,
            "revoked_at": _utc_text(self.revoked_at),
            "recorded_at": _utc_text(self.recorded_at),
        }


@dataclass(frozen=True, slots=True)
class SimulatedCorporateActionWriteGrantCurrent:
    """Projection of one exact head and any revocation known by a repository read."""

    grant: SimulatedCorporateActionWriteGrant
    revocation: SimulatedCorporateActionWriteGrantRevocation | None = None

    def __post_init__(self) -> None:
        """Validate the immutable grant and any revocation against its precise target."""

        if type(self.grant) is not SimulatedCorporateActionWriteGrant:
            raise TypeError("grant must be an exact simulated corporate-action write grant")
        self.grant.__post_init__()
        if self.revocation is not None:
            if type(self.revocation) is not SimulatedCorporateActionWriteGrantRevocation:
                raise TypeError("revocation must be an exact simulated write grant revocation")
            validate_simulated_corporate_action_write_grant_revocation(self.grant, self.revocation)

    @property
    def selector(self) -> SimulatedCorporateActionWriteGrantSelector:
        """Return the exact immutable selector represented by this current read."""

        self.__post_init__()
        return self.grant.selector

    def is_active_at(self, as_of: datetime) -> bool:
        """Return current grant authority only if it is unrevoked and within its finite interval."""

        self.__post_init__()
        cutoff = _aware(as_of, "as_of")
        return self.grant.is_active_at(cutoff) and (
            self.revocation is None or self.revocation.recorded_at > cutoff
        )


@dataclass(frozen=True, slots=True)
class SimulatedCorporateActionWriteGrantRecord:
    """Exact historical withdrawal metadata with no current-authority semantics."""

    grant: SimulatedCorporateActionWriteGrant
    revocation: SimulatedCorporateActionWriteGrantRevocation | None = None

    def __post_init__(self) -> None:
        """Validate the immutable target without claiming that it is a current head."""
        if type(self.grant) is not SimulatedCorporateActionWriteGrant:
            raise TypeError("grant record requires an exact grant")
        self.grant.__post_init__()
        if self.revocation is not None:
            if type(self.revocation) is not SimulatedCorporateActionWriteGrantRevocation:
                raise TypeError("grant record revocation is invalid")
            validate_simulated_corporate_action_write_grant_revocation(self.grant, self.revocation)


def validate_simulated_corporate_action_write_grant_successor(
    predecessor: SimulatedCorporateActionWriteGrant,
    successor: SimulatedCorporateActionWriteGrant,
) -> None:
    """Require one immutable successor of the same exact account-owner chain."""

    predecessor.__post_init__()
    successor.__post_init__()
    if (
        predecessor.schema == SIMULATED_CORPORATE_ACTION_WRITE_GRANT_V2_SCHEMA
        and successor.schema != SIMULATED_CORPORATE_ACTION_WRITE_GRANT_V2_SCHEMA
    ):
        raise ValueError("successor grant schema downgrade is forbidden")
    if successor.grant_id != predecessor.grant_id:
        raise ValueError("successor grant_id differs from its predecessor")
    if successor.grant_version == predecessor.grant_version:
        raise ValueError("successor grant_version must be new")
    if successor.identity_hash != predecessor.identity_hash:
        raise ValueError("successor stable grant identity differs")
    if successor.supersedes_content_hash != predecessor.content_hash:
        raise ValueError("successor predecessor content hash differs")
    if successor.recorded_at <= predecessor.recorded_at:
        raise ValueError("successor must be recorded after its predecessor")
    if _grant_scope(successor) != _grant_scope(predecessor):
        raise ValueError("successor account owner/tenant scope differs")


def validate_simulated_corporate_action_write_grant_revocation(
    grant: SimulatedCorporateActionWriteGrant,
    revocation: SimulatedCorporateActionWriteGrantRevocation,
) -> None:
    """Require an immutable revocation to identify one exact grant version."""

    grant.__post_init__()
    revocation.__post_init__()
    if (
        revocation.grant_id != grant.grant_id
        or revocation.grant_version != grant.grant_version
        or revocation.grant_identity_hash != grant.identity_hash
        or revocation.grant_content_hash != grant.content_hash
    ):
        raise ValueError("revocation target differs from its exact grant")
    if revocation.revoked_at < grant.recorded_at:
        raise ValueError("revocation predates its target grant")


def _grant_scope(grant: SimulatedCorporateActionWriteGrant) -> tuple[object, ...]:
    """Return chain-stable exact account, owner and tenant scope values."""

    binding = grant.binding
    return (
        SIMULATED_CORPORATE_ACTION_STAGE_WRITE_PERMISSION,
        grant.service_actor_id,
        binding.account_namespace,
        binding.account_id,
        binding.owner_user_id,
        binding.tenant_id,
        binding.owner_id,
    )


__all__ = [
    "SIMULATED_CORPORATE_ACTION_SERVICE_ACTOR_ID",
    "SIMULATED_CORPORATE_ACTION_STAGE_WRITE_PERMISSION",
    "SIMULATED_CORPORATE_ACTION_WRITE_GRANT_REVOCATION_SCHEMA",
    "SIMULATED_CORPORATE_ACTION_WRITE_GRANT_SCHEMA",
    "SIMULATED_CORPORATE_ACTION_WRITE_GRANT_V2_PERMISSION",
    "SIMULATED_CORPORATE_ACTION_WRITE_GRANT_V2_SCHEMA",
    "SimulatedCorporateActionWriteGrant",
    "SimulatedCorporateActionWriteGrantBinding",
    "SimulatedCorporateActionWriteGrantCurrent",
    "SimulatedCorporateActionWriteGrantRevocation",
    "SimulatedCorporateActionWriteGrantRecord",
    "SimulatedCorporateActionWriteGrantSelector",
    "validate_simulated_corporate_action_write_grant_revocation",
    "validate_simulated_corporate_action_write_grant_successor",
]
