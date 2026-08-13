"""Inactive Broker assertion joining two owner-issued account namespaces."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime

BROKER_PORTFOLIO_ACCOUNT_BINDING_OWNER = "broker_execution"
BROKER_PORTFOLIO_ACCOUNT_BINDING_VERSION = "broker-portfolio-account-namespace-binding.v1"
BROKER_PORTFOLIO_ACCOUNT_BINDING_PERMISSION = "inactive"
BROKER_ACCOUNT_BINDING_SOURCE_OWNER = "broker_execution"
BROKER_ACCOUNT_BINDING_SOURCE_ARTIFACT_TYPE = "broker_account_identity_snapshot"
ACCOUNT_BINDING_SOURCE_OWNER = "account"
ACCOUNT_BINDING_SOURCE_ARTIFACT_TYPE = "account_identity_snapshot"
BROKER_PORTFOLIO_ACCOUNT_BINDING_BLOCKERS = (
    "broker_account_source_provider_not_integrated",
    "portfolio_account_source_provider_not_integrated",
    "namespace_binding_approval_not_integrated",
)


def _require_token(value: object, field_name: str, *, maximum: int = 192) -> str:
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
    if (
        type(value) is not str
        or len(value) != 64
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise ValueError(f"{field_name} must be a lowercase SHA-256 digest")
    return value


def _require_aware(value: object, field_name: str) -> datetime:
    if type(value) is not datetime or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware")
    return value


def _utc_text(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _canonical_hash(payload: dict[str, object]) -> str:
    return hashlib.sha256(
        json.dumps(
            payload,
            allow_nan=False,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    ).hexdigest()


@dataclass(frozen=True, slots=True)
class BrokerPortfolioAccountBindingActor:
    """Exact server-authenticated human staff identity making the assertion."""

    actor_id: str
    user_id: int
    role: str
    kind: str = "human"
    is_staff: bool = True

    def __post_init__(self) -> None:
        _require_token(self.actor_id, "actor_id")
        if type(self.user_id) is not int or self.user_id <= 0:
            raise ValueError("user_id must be a positive integer")
        _require_token(self.role, "role")
        if self.kind != "human" or self.is_staff is not True:
            raise ValueError("account namespace binding actor must be human staff")

    def to_payload(self) -> dict[str, object]:
        """Return both stable actor identities and fixed human-staff attributes."""

        return {
            "actor_id": self.actor_id,
            "user_id": self.user_id,
            "role": self.role,
            "kind": self.kind,
            "is_staff": self.is_staff,
        }


@dataclass(frozen=True, slots=True)
class BrokerPortfolioAccountNamespaceBinding:
    """Content-addressed but permanently inactive cross-namespace assertion."""

    binding_id: str
    broker_account_namespace: str
    broker_account_id: int
    portfolio_account_namespace: str
    portfolio_account_id: str
    broker_source_owner: str
    broker_source_artifact_type: str
    broker_source_id: str
    broker_source_version: str
    broker_source_content_hash: str
    portfolio_source_owner: str
    portfolio_source_artifact_type: str
    portfolio_source_id: str
    portfolio_source_version: str
    portfolio_source_content_hash: str
    asserted_by: BrokerPortfolioAccountBindingActor
    issued_at: datetime
    recorded_at: datetime
    valid_until: datetime
    supersedes_binding_hash: str | None = None
    identity_hash: str = ""
    content_hash: str = ""
    owner: str = BROKER_PORTFOLIO_ACCOUNT_BINDING_OWNER
    binding_version: str = BROKER_PORTFOLIO_ACCOUNT_BINDING_VERSION
    permission: str = BROKER_PORTFOLIO_ACCOUNT_BINDING_PERMISSION
    blocker_codes: tuple[str, ...] = BROKER_PORTFOLIO_ACCOUNT_BINDING_BLOCKERS

    def __post_init__(self) -> None:
        if self.owner != BROKER_PORTFOLIO_ACCOUNT_BINDING_OWNER:
            raise ValueError("account namespace binding owner is fixed")
        if self.binding_version != BROKER_PORTFOLIO_ACCOUNT_BINDING_VERSION:
            raise ValueError("account namespace binding version is fixed")
        if self.permission != BROKER_PORTFOLIO_ACCOUNT_BINDING_PERMISSION:
            raise ValueError("account namespace binding permission is fixed inactive")
        if self.blocker_codes != BROKER_PORTFOLIO_ACCOUNT_BINDING_BLOCKERS:
            raise ValueError("account namespace binding blocker_codes are fixed")
        if (
            self.broker_source_owner != BROKER_ACCOUNT_BINDING_SOURCE_OWNER
            or self.broker_source_artifact_type != BROKER_ACCOUNT_BINDING_SOURCE_ARTIFACT_TYPE
        ):
            raise ValueError("Broker source authority or artifact type is invalid")
        if (
            self.portfolio_source_owner != ACCOUNT_BINDING_SOURCE_OWNER
            or self.portfolio_source_artifact_type != ACCOUNT_BINDING_SOURCE_ARTIFACT_TYPE
        ):
            raise ValueError("Portfolio source authority or artifact type is invalid")
        for field_name in (
            "binding_id",
            "broker_account_namespace",
            "portfolio_account_namespace",
            "portfolio_account_id",
            "broker_source_owner",
            "broker_source_artifact_type",
            "broker_source_id",
            "broker_source_version",
            "portfolio_source_owner",
            "portfolio_source_artifact_type",
            "portfolio_source_id",
            "portfolio_source_version",
        ):
            _require_token(getattr(self, field_name), field_name)
        if type(self.broker_account_id) is not int or self.broker_account_id <= 0:
            raise TypeError("broker_account_id must be an exact positive integer")
        _require_hash(self.broker_source_content_hash, "broker_source_content_hash")
        _require_hash(
            self.portfolio_source_content_hash,
            "portfolio_source_content_hash",
        )
        if type(self.asserted_by) is not BrokerPortfolioAccountBindingActor:
            raise TypeError("asserted_by must be an exact binding actor")
        BrokerPortfolioAccountBindingActor.__post_init__(self.asserted_by)
        for field_name in ("issued_at", "recorded_at", "valid_until"):
            _require_aware(getattr(self, field_name), field_name)
        if not self.issued_at <= self.recorded_at < self.valid_until:
            raise ValueError("account namespace binding clock sequence is invalid")
        if self.supersedes_binding_hash is not None:
            _require_hash(self.supersedes_binding_hash, "supersedes_binding_hash")
        expected_identity_hash = _canonical_hash(self._identity_payload())
        if not self.identity_hash:
            object.__setattr__(self, "identity_hash", expected_identity_hash)
        else:
            _require_hash(self.identity_hash, "identity_hash")
            if self.identity_hash != expected_identity_hash:
                raise ValueError("account namespace binding identity_hash is invalid")
        expected_hash = _canonical_hash(self._content_payload())
        if not self.content_hash:
            object.__setattr__(self, "content_hash", expected_hash)
        else:
            _require_hash(self.content_hash, "content_hash")
            if self.content_hash != expected_hash:
                raise ValueError("account namespace binding content_hash is invalid")

    @property
    def activation_available(self) -> bool:
        """Remain false until both source providers and approval are integrated."""

        return False

    @property
    def must_not_execute(self) -> bool:
        """Remain true because this contract grants no execution authority."""

        return True

    def is_knowable_at(self, as_of: datetime) -> bool:
        """Return whether this inactive assertion is knowable and unexpired."""

        _require_aware(as_of, "as_of")
        return self.recorded_at <= as_of < self.valid_until

    def _identity_payload(self) -> dict[str, object]:
        return {
            "owner": self.owner,
            "binding_id": self.binding_id,
            "binding_version": self.binding_version,
        }

    def _content_payload(self) -> dict[str, object]:
        return {
            **self._identity_payload(),
            "broker_account_namespace": self.broker_account_namespace,
            "broker_account_id": self.broker_account_id,
            "portfolio_account_namespace": self.portfolio_account_namespace,
            "portfolio_account_id": self.portfolio_account_id,
            "broker_source_owner": self.broker_source_owner,
            "broker_source_artifact_type": self.broker_source_artifact_type,
            "broker_source_id": self.broker_source_id,
            "broker_source_version": self.broker_source_version,
            "broker_source_content_hash": self.broker_source_content_hash,
            "portfolio_source_owner": self.portfolio_source_owner,
            "portfolio_source_artifact_type": self.portfolio_source_artifact_type,
            "portfolio_source_id": self.portfolio_source_id,
            "portfolio_source_version": self.portfolio_source_version,
            "portfolio_source_content_hash": self.portfolio_source_content_hash,
            "asserted_by": self.asserted_by.to_payload(),
            "issued_at": _utc_text(self.issued_at),
            "recorded_at": _utc_text(self.recorded_at),
            "valid_until": _utc_text(self.valid_until),
            "supersedes_binding_hash": self.supersedes_binding_hash,
            "permission": self.permission,
            "blocker_codes": list(self.blocker_codes),
        }

    def to_payload(self) -> dict[str, object]:
        """Return canonical binding evidence with explicit inactive safety flags."""

        return {
            **self._content_payload(),
            "identity_hash": self.identity_hash,
            "content_hash": self.content_hash,
            "activation_available": False,
            "must_not_execute": True,
        }


def validate_broker_portfolio_account_binding_successor(
    previous: BrokerPortfolioAccountNamespaceBinding,
    successor: BrokerPortfolioAccountNamespaceBinding,
) -> None:
    """Validate one adjacent assertion in the same Broker-account logical chain."""

    if type(previous) is not BrokerPortfolioAccountNamespaceBinding:
        raise TypeError("previous must be an exact account namespace binding")
    if type(successor) is not BrokerPortfolioAccountNamespaceBinding:
        raise TypeError("successor must be an exact account namespace binding")
    BrokerPortfolioAccountNamespaceBinding.__post_init__(previous)
    BrokerPortfolioAccountNamespaceBinding.__post_init__(successor)
    if successor.supersedes_binding_hash != previous.content_hash:
        raise ValueError("successor does not bind the exact previous assertion")
    if successor.broker_account_namespace != previous.broker_account_namespace:
        raise ValueError("successor changed Broker account namespace")
    if successor.broker_account_id != previous.broker_account_id:
        raise ValueError("successor changed Broker account identity")
    if successor.recorded_at <= previous.recorded_at:
        raise ValueError("successor recorded_at must advance")


__all__ = [
    "BROKER_ACCOUNT_BINDING_SOURCE_ARTIFACT_TYPE",
    "BROKER_ACCOUNT_BINDING_SOURCE_OWNER",
    "BROKER_PORTFOLIO_ACCOUNT_BINDING_BLOCKERS",
    "BROKER_PORTFOLIO_ACCOUNT_BINDING_OWNER",
    "BROKER_PORTFOLIO_ACCOUNT_BINDING_PERMISSION",
    "BROKER_PORTFOLIO_ACCOUNT_BINDING_VERSION",
    "ACCOUNT_BINDING_SOURCE_ARTIFACT_TYPE",
    "ACCOUNT_BINDING_SOURCE_OWNER",
    "BrokerPortfolioAccountBindingActor",
    "BrokerPortfolioAccountNamespaceBinding",
    "validate_broker_portfolio_account_binding_successor",
]
