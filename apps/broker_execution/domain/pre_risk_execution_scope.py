"""Immutable inactive scope joining Portfolio approval and Broker order facts.

This is deliberately a pre-Risk artifact.  It does not contain a Risk authorization,
Research evidence, or a policy benchmark and therefore cannot authorize execution.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID

BROKER_PRE_RISK_SCOPE_OWNER = "broker_execution"
BROKER_PRE_RISK_SCOPE_VERSION = "broker-pre-risk-execution-scope.v1"
BROKER_PRE_RISK_SCOPE_PERMISSION = "inactive"
BROKER_PRE_RISK_SCOPE_BLOCKERS = (
    "broker_order_approval_artifact_inactive",
    "broker_order_plan_binding_unproven",
    "broker_order_risk_policy_identity_unbound",
    "portfolio_broker_account_binding_unverified",
    "portfolio_execution_approval_inactive",
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
    encoded = json.dumps(
        payload,
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


@dataclass(frozen=True, slots=True)
class BrokerPreRiskExecutionScope:
    """Content-addressed pre-Risk candidate with permanently inactive semantics."""

    scope_id: str
    broker_account_id: int
    portfolio_account_id: str
    plan_id: str
    plan_version: int
    plan_content_hash: str
    plan_valid_until: datetime
    portfolio_receipt_id: str
    portfolio_receipt_version: str
    portfolio_receipt_content_hash: str
    portfolio_subject_id: str
    portfolio_subject_version: str
    portfolio_subject_content_hash: str
    portfolio_receipt_valid_until: datetime
    order_artifact_id: str
    order_artifact_version: str
    order_artifact_content_hash: str
    order_artifact_identity_hash: str
    order_version: int
    order_approval_digest: str
    order_valid_until: datetime
    order_risk_policy_version: str
    recorded_at: datetime
    valid_until: datetime
    supersedes_scope_hash: str | None = None
    content_hash: str = ""
    owner: str = BROKER_PRE_RISK_SCOPE_OWNER
    scope_version: str = BROKER_PRE_RISK_SCOPE_VERSION
    permission: str = BROKER_PRE_RISK_SCOPE_PERMISSION
    blocker_codes: tuple[str, ...] = BROKER_PRE_RISK_SCOPE_BLOCKERS

    def __post_init__(self) -> None:
        if self.owner != BROKER_PRE_RISK_SCOPE_OWNER:
            raise ValueError("pre-Risk scope owner is fixed")
        if self.scope_version != BROKER_PRE_RISK_SCOPE_VERSION:
            raise ValueError("pre-Risk scope version is fixed")
        if self.permission != BROKER_PRE_RISK_SCOPE_PERMISSION:
            raise ValueError("pre-Risk scope permission is fixed inactive")
        if self.blocker_codes != BROKER_PRE_RISK_SCOPE_BLOCKERS:
            raise ValueError("pre-Risk scope blocker_codes are fixed")
        for field_name in (
            "scope_id",
            "portfolio_account_id",
            "plan_id",
            "portfolio_receipt_id",
            "portfolio_receipt_version",
            "portfolio_subject_id",
            "portfolio_subject_version",
            "order_artifact_version",
            "order_risk_policy_version",
        ):
            _require_token(getattr(self, field_name), field_name)
        try:
            canonical_order_id = str(UUID(self.order_artifact_id))
        except (TypeError, ValueError, AttributeError) as error:
            raise ValueError("order_artifact_id must be a canonical UUID") from error
        if canonical_order_id != self.order_artifact_id:
            raise ValueError("order_artifact_id must be a canonical UUID")
        if type(self.broker_account_id) is not int or self.broker_account_id <= 0:
            raise ValueError("broker_account_id must be a positive integer")
        if type(self.plan_version) is not int or self.plan_version <= 0:
            raise ValueError("plan_version must be a positive integer")
        if type(self.order_version) is not int or self.order_version <= 0:
            raise ValueError("order_version must be a positive integer")
        for field_name in (
            "plan_content_hash",
            "portfolio_receipt_content_hash",
            "portfolio_subject_content_hash",
            "order_artifact_content_hash",
            "order_artifact_identity_hash",
            "order_approval_digest",
        ):
            _require_hash(getattr(self, field_name), field_name)
        for field_name in (
            "plan_valid_until",
            "portfolio_receipt_valid_until",
            "order_valid_until",
            "recorded_at",
            "valid_until",
        ):
            _require_aware(getattr(self, field_name), field_name)
        expected_valid_until = min(
            self.plan_valid_until,
            self.portfolio_receipt_valid_until,
            self.order_valid_until,
        )
        if self.valid_until != expected_valid_until:
            raise ValueError("valid_until must equal the strict three-source minimum")
        if self.recorded_at >= self.valid_until:
            raise ValueError("pre-Risk scope validity window is invalid")
        if self.supersedes_scope_hash is not None:
            _require_hash(self.supersedes_scope_hash, "supersedes_scope_hash")
        expected_hash = _canonical_hash(self._content_payload())
        if not self.content_hash:
            object.__setattr__(self, "content_hash", expected_hash)
        else:
            _require_hash(self.content_hash, "content_hash")
            if self.content_hash != expected_hash:
                raise ValueError("pre-Risk scope content_hash is invalid")

    @property
    def activation_available(self) -> bool:
        """Remain false until every blocked upstream gains active authority."""

        return False

    @property
    def must_not_execute(self) -> bool:
        """Remain true because this artifact is an inactive audit candidate."""

        return True

    def is_knowable_at(self, as_of: datetime) -> bool:
        """Return whether this immutable candidate is knowable and unexpired."""

        _require_aware(as_of, "as_of")
        return self.recorded_at <= as_of < self.valid_until

    def _content_payload(self) -> dict[str, object]:
        return {
            "owner": self.owner,
            "scope_id": self.scope_id,
            "scope_version": self.scope_version,
            "broker_account_id": self.broker_account_id,
            "portfolio_account_id": self.portfolio_account_id,
            "plan_id": self.plan_id,
            "plan_version": self.plan_version,
            "plan_content_hash": self.plan_content_hash,
            "plan_valid_until": _utc_text(self.plan_valid_until),
            "portfolio_receipt_id": self.portfolio_receipt_id,
            "portfolio_receipt_version": self.portfolio_receipt_version,
            "portfolio_receipt_content_hash": self.portfolio_receipt_content_hash,
            "portfolio_subject_id": self.portfolio_subject_id,
            "portfolio_subject_version": self.portfolio_subject_version,
            "portfolio_subject_content_hash": self.portfolio_subject_content_hash,
            "portfolio_receipt_valid_until": _utc_text(self.portfolio_receipt_valid_until),
            "order_artifact_id": self.order_artifact_id,
            "order_artifact_version": self.order_artifact_version,
            "order_artifact_content_hash": self.order_artifact_content_hash,
            "order_artifact_identity_hash": self.order_artifact_identity_hash,
            "order_version": self.order_version,
            "order_approval_digest": self.order_approval_digest,
            "order_valid_until": _utc_text(self.order_valid_until),
            "order_risk_policy_version": self.order_risk_policy_version,
            "recorded_at": _utc_text(self.recorded_at),
            "valid_until": _utc_text(self.valid_until),
            "supersedes_scope_hash": self.supersedes_scope_hash,
            "permission": self.permission,
            "blocker_codes": list(self.blocker_codes),
        }

    def to_payload(self) -> dict[str, object]:
        """Return the canonical projection with explicit inactive safety flags."""

        return {
            **self._content_payload(),
            "content_hash": self.content_hash,
            "activation_available": False,
            "must_not_execute": True,
        }


def validate_pre_risk_scope_successor(
    previous: BrokerPreRiskExecutionScope,
    successor: BrokerPreRiskExecutionScope,
) -> None:
    """Validate one adjacent logical-chain link for the same account and order."""

    if type(previous) is not BrokerPreRiskExecutionScope:
        raise TypeError("previous must be an exact BrokerPreRiskExecutionScope")
    if type(successor) is not BrokerPreRiskExecutionScope:
        raise TypeError("successor must be an exact BrokerPreRiskExecutionScope")
    BrokerPreRiskExecutionScope.__post_init__(previous)
    BrokerPreRiskExecutionScope.__post_init__(successor)
    if successor.supersedes_scope_hash != previous.content_hash:
        raise ValueError("successor does not bind the exact previous scope")
    if successor.broker_account_id != previous.broker_account_id:
        raise ValueError("scope successor changed broker account identity")
    if successor.order_artifact_id != previous.order_artifact_id:
        raise ValueError("scope successor changed order identity")
    if successor.recorded_at <= previous.recorded_at:
        raise ValueError("scope successor clock must advance")


__all__ = [
    "BROKER_PRE_RISK_SCOPE_BLOCKERS",
    "BROKER_PRE_RISK_SCOPE_OWNER",
    "BROKER_PRE_RISK_SCOPE_PERMISSION",
    "BROKER_PRE_RISK_SCOPE_VERSION",
    "BrokerPreRiskExecutionScope",
    "validate_pre_risk_scope_successor",
]
