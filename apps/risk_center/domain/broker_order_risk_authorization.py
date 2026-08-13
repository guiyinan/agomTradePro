"""Risk-owned immutable contracts for future Broker order authorization."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from uuid import UUID

BROKER_ORDER_RISK_AUTHORIZATION_OWNER = "risk_center"
BROKER_ORDER_RISK_AUTHORIZATION_CAPABILITY = "broker_order_risk_authorization"
BROKER_ORDER_RISK_SCOPE_VERSION = "broker-order-execution-scope.v1"
BROKER_ORDER_RISK_SUBJECT_VERSION = "broker-order-risk-subject.v1"
BROKER_ORDER_RISK_AUTHORIZATION_VERSION = "broker-order-risk-authorization.v1"


class BrokerOrderRiskAuthorizationActorKind(str, Enum):
    """Trusted server-side actor classifications for order-risk authorization."""

    HUMAN = "human"
    AI = "ai"
    SERVICE = "service"


def _require_token(value: object, field_name: str) -> None:
    if (
        type(value) is not str
        or not value
        or value.strip() != value
        or len(value) > 192
        or any(character.isspace() for character in value)
    ):
        raise ValueError(f"{field_name} must be a bounded canonical token")


def _require_hash(value: object, field_name: str) -> None:
    if (
        type(value) is not str
        or len(value) != 64
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise ValueError(f"{field_name} must be a lowercase SHA-256 digest")


def _require_aware(value: object, field_name: str) -> None:
    if type(value) is not datetime or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware")


def _utc_text(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


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
class BrokerOrderRiskAuthorizationActor:
    """Server-authenticated actor; never reconstructed from a request payload."""

    actor_id: str
    kind: BrokerOrderRiskAuthorizationActorKind
    is_staff: bool
    user_id: int | None = None

    def __post_init__(self) -> None:
        _require_token(self.actor_id, "actor_id")
        if type(self.kind) is not BrokerOrderRiskAuthorizationActorKind:
            raise TypeError("kind must be an exact BrokerOrderRiskAuthorizationActorKind")
        if type(self.is_staff) is not bool:
            raise TypeError("is_staff must be bool")
        if self.kind is BrokerOrderRiskAuthorizationActorKind.HUMAN:
            if type(self.user_id) is not int or self.user_id <= 0:
                raise ValueError("human actor user_id must be a positive integer")
        elif self.user_id is not None or self.is_staff:
            raise ValueError("non-human actors cannot claim staff user identity")

    @property
    def is_human_staff(self) -> bool:
        """Return whether this actor may request or approve authorization."""

        return self.kind is BrokerOrderRiskAuthorizationActorKind.HUMAN and self.is_staff

    def to_payload(self) -> dict[str, object]:
        """Return the immutable server actor identity."""

        return {
            "actor_id": self.actor_id,
            "kind": self.kind.value,
            "is_staff": self.is_staff,
            "user_id": self.user_id,
        }


@dataclass(frozen=True, slots=True)
class BrokerOrderRiskScope:
    """Risk Center's exact local seal of one Broker execution scope."""

    account_id: int
    execution_scope_id: str
    execution_scope_hash: str
    plan_id: str
    plan_version: str
    plan_content_hash: str
    plan_approval_hash: str
    plan_valid_until: datetime
    order_id: str
    order_version: str
    order_content_hash: str
    order_valid_until: datetime
    policy_id: str
    policy_version: str
    policy_content_hash: str
    policy_activation_hash: str
    policy_valid_until: datetime
    execution_scope_valid_until: datetime
    content_hash: str = ""
    execution_scope_version: str = BROKER_ORDER_RISK_SCOPE_VERSION

    def __post_init__(self) -> None:
        if type(self.account_id) is not int or self.account_id <= 0:
            raise ValueError("account_id must be a positive integer")
        if self.execution_scope_version != BROKER_ORDER_RISK_SCOPE_VERSION:
            raise ValueError("execution_scope_version is fixed")
        for field_name in (
            "execution_scope_id",
            "plan_id",
            "plan_version",
            "order_id",
            "order_version",
            "policy_id",
            "policy_version",
        ):
            _require_token(getattr(self, field_name), field_name)
        try:
            canonical_order_id = str(UUID(self.order_id))
        except (ValueError, AttributeError) as exc:
            raise ValueError("order_id must be a canonical UUID") from exc
        if canonical_order_id != self.order_id:
            raise ValueError("order_id must be a canonical UUID")
        for field_name in (
            "execution_scope_hash",
            "plan_content_hash",
            "plan_approval_hash",
            "order_content_hash",
            "policy_content_hash",
            "policy_activation_hash",
        ):
            _require_hash(getattr(self, field_name), field_name)
        for field_name in (
            "plan_valid_until",
            "order_valid_until",
            "policy_valid_until",
            "execution_scope_valid_until",
        ):
            _require_aware(getattr(self, field_name), field_name)
        expected = _canonical_hash(self._content_payload())
        if not self.content_hash:
            object.__setattr__(self, "content_hash", expected)
        else:
            _require_hash(self.content_hash, "content_hash")
            if self.content_hash != expected:
                raise ValueError("risk scope content_hash is invalid")

    @property
    def effective_valid_until(self) -> datetime:
        """Return the strict minimum of all sealed validity windows."""

        return min(
            self.plan_valid_until,
            self.order_valid_until,
            self.policy_valid_until,
            self.execution_scope_valid_until,
        )

    def _content_payload(self) -> dict[str, object]:
        return {
            "account_id": self.account_id,
            "execution_scope_id": self.execution_scope_id,
            "execution_scope_version": self.execution_scope_version,
            "execution_scope_hash": self.execution_scope_hash,
            "plan_id": self.plan_id,
            "plan_version": self.plan_version,
            "plan_content_hash": self.plan_content_hash,
            "plan_approval_hash": self.plan_approval_hash,
            "plan_valid_until": _utc_text(self.plan_valid_until),
            "order_id": self.order_id,
            "order_version": self.order_version,
            "order_content_hash": self.order_content_hash,
            "order_valid_until": _utc_text(self.order_valid_until),
            "policy_id": self.policy_id,
            "policy_version": self.policy_version,
            "policy_content_hash": self.policy_content_hash,
            "policy_activation_hash": self.policy_activation_hash,
            "policy_valid_until": _utc_text(self.policy_valid_until),
            "execution_scope_valid_until": _utc_text(self.execution_scope_valid_until),
        }

    def to_payload(self) -> dict[str, object]:
        """Return the sealed scope projection."""

        return {**self._content_payload(), "content_hash": self.content_hash}


@dataclass(frozen=True, slots=True)
class BrokerOrderRiskAuthorizationSubject:
    """Immutable two-person approval subject for one exact Risk scope."""

    subject_id: str
    scope: BrokerOrderRiskScope
    requested_by: BrokerOrderRiskAuthorizationActor
    requested_at: datetime
    valid_until: datetime
    supersedes_authorization_hash: str | None = None
    content_hash: str = ""
    subject_version: str = BROKER_ORDER_RISK_SUBJECT_VERSION

    def __post_init__(self) -> None:
        _require_token(self.subject_id, "subject_id")
        if self.subject_version != BROKER_ORDER_RISK_SUBJECT_VERSION:
            raise ValueError("subject_version is fixed")
        if type(self.scope) is not BrokerOrderRiskScope:
            raise TypeError("scope must be an exact BrokerOrderRiskScope")
        BrokerOrderRiskScope.__post_init__(self.scope)
        if type(self.requested_by) is not BrokerOrderRiskAuthorizationActor:
            raise TypeError("requested_by must be an exact BrokerOrderRiskAuthorizationActor")
        BrokerOrderRiskAuthorizationActor.__post_init__(self.requested_by)
        if not self.requested_by.is_human_staff:
            raise ValueError("risk authorization request requires human staff")
        _require_aware(self.requested_at, "requested_at")
        _require_aware(self.valid_until, "valid_until")
        if self.valid_until != self.scope.effective_valid_until:
            raise ValueError("subject validity must equal the strict scope minimum")
        if self.requested_at >= self.valid_until:
            raise ValueError("risk authorization subject validity window is invalid")
        if self.supersedes_authorization_hash is not None:
            _require_hash(self.supersedes_authorization_hash, "supersedes_authorization_hash")
        expected = _canonical_hash(self._content_payload())
        if not self.content_hash:
            object.__setattr__(self, "content_hash", expected)
        else:
            _require_hash(self.content_hash, "content_hash")
            if self.content_hash != expected:
                raise ValueError("risk authorization subject content_hash is invalid")

    def _content_payload(self) -> dict[str, object]:
        return {
            "subject_id": self.subject_id,
            "subject_version": self.subject_version,
            "scope": self.scope.to_payload(),
            "requested_by": self.requested_by.to_payload(),
            "requested_at": _utc_text(self.requested_at),
            "valid_until": _utc_text(self.valid_until),
            "supersedes_authorization_hash": self.supersedes_authorization_hash,
        }

    def is_valid_at(self, as_of: datetime) -> bool:
        """Return whether this subject may be approved at an exact cutoff."""

        _require_aware(as_of, "as_of")
        return self.requested_at <= as_of < self.valid_until


@dataclass(frozen=True, slots=True)
class BrokerOrderRiskAuthorizationRecord:
    """Risk Center's exact execution-eligible authorization record contract."""

    authorization_id: str
    subject: BrokerOrderRiskAuthorizationSubject
    approved_by: BrokerOrderRiskAuthorizationActor
    issued_at: datetime
    valid_until: datetime
    content_hash: str = ""
    owner: str = BROKER_ORDER_RISK_AUTHORIZATION_OWNER
    capability: str = BROKER_ORDER_RISK_AUTHORIZATION_CAPABILITY
    authorization_version: str = BROKER_ORDER_RISK_AUTHORIZATION_VERSION
    permission_cap: str = "execution_eligible"

    def __post_init__(self) -> None:
        _require_token(self.authorization_id, "authorization_id")
        if self.owner != BROKER_ORDER_RISK_AUTHORIZATION_OWNER:
            raise ValueError("authorization owner is fixed")
        if self.capability != BROKER_ORDER_RISK_AUTHORIZATION_CAPABILITY:
            raise ValueError("authorization capability is fixed")
        if self.authorization_version != BROKER_ORDER_RISK_AUTHORIZATION_VERSION:
            raise ValueError("authorization_version is fixed")
        if self.permission_cap != "execution_eligible":
            raise ValueError("permission_cap is fixed execution_eligible")
        if type(self.subject) is not BrokerOrderRiskAuthorizationSubject:
            raise TypeError("subject must be an exact BrokerOrderRiskAuthorizationSubject")
        BrokerOrderRiskAuthorizationSubject.__post_init__(self.subject)
        if type(self.approved_by) is not BrokerOrderRiskAuthorizationActor:
            raise TypeError("approved_by must be an exact BrokerOrderRiskAuthorizationActor")
        BrokerOrderRiskAuthorizationActor.__post_init__(self.approved_by)
        if not self.approved_by.is_human_staff:
            raise ValueError("risk authorization approval requires human staff")
        if self.approved_by.actor_id == self.subject.requested_by.actor_id:
            raise ValueError("self approval is forbidden")
        if self.approved_by.user_id == self.subject.requested_by.user_id:
            raise ValueError("self approval is forbidden")
        _require_aware(self.issued_at, "issued_at")
        _require_aware(self.valid_until, "valid_until")
        if self.valid_until != self.subject.valid_until:
            raise ValueError("authorization validity must match the subject")
        if not self.subject.requested_at <= self.issued_at < self.valid_until:
            raise ValueError("authorization issued outside its subject validity window")
        expected = _canonical_hash(self._content_payload())
        if not self.content_hash:
            object.__setattr__(self, "content_hash", expected)
        else:
            _require_hash(self.content_hash, "content_hash")
            if self.content_hash != expected:
                raise ValueError("risk authorization content_hash is invalid")

    def is_valid_at(self, as_of: datetime) -> bool:
        """Return whether this authorization is effective at an exact PIT cutoff."""

        _require_aware(as_of, "as_of")
        return self.issued_at <= as_of < self.valid_until

    def _content_payload(self) -> dict[str, object]:
        return {
            "owner": self.owner,
            "capability": self.capability,
            "authorization_id": self.authorization_id,
            "authorization_version": self.authorization_version,
            "subject_hash": self.subject.content_hash,
            "permission_cap": self.permission_cap,
            "approved_by": self.approved_by.to_payload(),
            "issued_at": _utc_text(self.issued_at),
            "valid_until": _utc_text(self.valid_until),
        }


def validate_risk_authorization_successor(
    previous: BrokerOrderRiskAuthorizationRecord,
    successor: BrokerOrderRiskAuthorizationRecord,
) -> None:
    """Validate one adjacent head link; future storage must prevent forks."""

    if type(previous) is not BrokerOrderRiskAuthorizationRecord:
        raise TypeError("previous must be an exact authorization record")
    if type(successor) is not BrokerOrderRiskAuthorizationRecord:
        raise TypeError("successor must be an exact authorization record")
    if successor.subject.supersedes_authorization_hash != previous.content_hash:
        raise ValueError("successor does not bind the exact previous authorization")
    if successor.subject.scope.account_id != previous.subject.scope.account_id:
        raise ValueError("authorization successor changed account identity")
    if successor.subject.scope.order_id != previous.subject.scope.order_id:
        raise ValueError("authorization successor changed order identity")
    if successor.issued_at <= previous.issued_at:
        raise ValueError("authorization successor clock must advance")


def broker_order_risk_subject_identity_hash(subject_id: str) -> str:
    """Return the stable lookup identity for one authorization subject."""

    _require_token(subject_id, "subject_id")
    return _canonical_hash(
        {
            "identity_kind": "broker_order_risk_authorization_subject",
            "subject_id": subject_id,
            "subject_version": BROKER_ORDER_RISK_SUBJECT_VERSION,
        }
    )


def broker_order_risk_authorization_identity_hash(authorization_id: str) -> str:
    """Return the stable lookup identity for one authorization record."""

    _require_token(authorization_id, "authorization_id")
    return _canonical_hash(
        {
            "identity_kind": "broker_order_risk_authorization",
            "authorization_id": authorization_id,
            "authorization_version": BROKER_ORDER_RISK_AUTHORIZATION_VERSION,
        }
    )


__all__ = [
    "BROKER_ORDER_RISK_AUTHORIZATION_CAPABILITY",
    "BROKER_ORDER_RISK_AUTHORIZATION_OWNER",
    "BrokerOrderRiskAuthorizationActor",
    "BrokerOrderRiskAuthorizationActorKind",
    "BrokerOrderRiskAuthorizationRecord",
    "BrokerOrderRiskAuthorizationSubject",
    "BrokerOrderRiskScope",
    "broker_order_risk_authorization_identity_hash",
    "broker_order_risk_subject_identity_hash",
    "validate_risk_authorization_successor",
]
