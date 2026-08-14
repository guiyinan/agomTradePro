"""ID-only activation workflow for Risk-owned Broker execution policies."""

from __future__ import annotations

import hashlib
import json
from contextlib import AbstractContextManager
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol

from apps.risk_center.application.broker_order_risk_authorization import (
    BrokerOrderRiskPolicyDefinition,
)
from apps.risk_center.domain.broker_order_execution_policy import (
    BrokerOrderExecutionRiskControls,
    BrokerOrderExecutionRiskPolicy,
    validate_broker_order_execution_policy_successor,
)

_SOURCE_SCHEMA = "broker-order-execution-risk-policy-source.v1"
_ACTIVATION_SCHEMA = "broker-order-execution-risk-policy-activation.v1"
_REQUIRED_SOURCE_KINDS = (
    "account_override",
    "account_exceptions",
    "floor",
    "global_exceptions",
    "template",
)


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
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _hash_payload(payload: dict[str, object]) -> str:
    return hashlib.sha256(
        json.dumps(
            payload,
            allow_nan=False,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    ).hexdigest()


class BrokerOrderExecutionPolicyUnavailable(ValueError):
    """An exact active source or policy is unavailable."""


class BrokerOrderExecutionPolicyConflict(ValueError):
    """An immutable identity or logical head has another first winner."""


class BrokerOrderExecutionPolicyCorruption(ValueError):
    """A trusted provider or repository returned an invalid value."""


@dataclass(frozen=True, slots=True)
class BrokerOrderExecutionPolicyActor:
    """Server-authenticated human staff identity for policy activation."""

    actor_id: str
    user_id: int
    kind: str = "human"
    is_staff: bool = True

    def __post_init__(self) -> None:
        _require_token(self.actor_id, "actor_id")
        if type(self.user_id) is not int or self.user_id <= 0:
            raise ValueError("user_id must be a positive integer")
        if self.kind != "human" or self.is_staff is not True:
            raise ValueError("policy activation actor must be human staff")

    def to_payload(self) -> dict[str, object]:
        """Return the immutable server-authenticated actor identity."""

        return {
            "actor_id": self.actor_id,
            "user_id": self.user_id,
            "kind": self.kind,
            "is_staff": self.is_staff,
        }


@dataclass(frozen=True, slots=True)
class BrokerOrderExecutionPolicySourceRef:
    """Exact immutable ref for one component of the resolved policy bundle."""

    source_kind: str
    source_id: str
    source_version: str
    source_content_hash: str
    recorded_at: datetime
    valid_until: datetime

    def __post_init__(self) -> None:
        if self.source_kind not in _REQUIRED_SOURCE_KINDS:
            raise ValueError("source_kind is not part of the exact policy bundle")
        _require_token(self.source_id, "source_id")
        _require_token(self.source_version, "source_version")
        _require_hash(self.source_content_hash, "source_content_hash")
        _require_aware(self.recorded_at, "source recorded_at")
        _require_aware(self.valid_until, "source valid_until")
        if self.recorded_at >= self.valid_until:
            raise ValueError("source component validity window is invalid")

    def to_payload(self) -> dict[str, object]:
        """Return the exact component identity and knowledge window."""

        return {
            "source_kind": self.source_kind,
            "source_id": self.source_id,
            "source_version": self.source_version,
            "source_content_hash": self.source_content_hash,
            "recorded_at": _utc_text(self.recorded_at),
            "valid_until": _utc_text(self.valid_until),
        }


@dataclass(frozen=True, slots=True)
class BrokerOrderExecutionPolicySourceSnapshot:
    """Trusted exact snapshot used to build one immutable policy version."""

    source_snapshot_id: str
    source_snapshot_version: str
    account_id: int
    controls: BrokerOrderExecutionRiskControls
    sources: tuple[BrokerOrderExecutionPolicySourceRef, ...]
    recorded_at: datetime
    valid_until: datetime
    content_hash: str = ""
    schema: str = _SOURCE_SCHEMA

    def __post_init__(self) -> None:
        _require_token(self.source_snapshot_id, "source_snapshot_id")
        _require_token(self.source_snapshot_version, "source_snapshot_version")
        if type(self.account_id) is not int or self.account_id <= 0:
            raise ValueError("account_id must be a positive integer")
        if type(self.controls) is not BrokerOrderExecutionRiskControls:
            raise TypeError("controls must be exact BrokerOrderExecutionRiskControls")
        BrokerOrderExecutionRiskControls.__post_init__(self.controls)
        if type(self.sources) is not tuple or any(
            type(item) is not BrokerOrderExecutionPolicySourceRef for item in self.sources
        ):
            raise TypeError("sources must contain exact policy source refs")
        for source in self.sources:
            BrokerOrderExecutionPolicySourceRef.__post_init__(source)
        if tuple(source.source_kind for source in self.sources) != _REQUIRED_SOURCE_KINDS:
            raise ValueError("source snapshot must bind the complete ordered source bundle")
        _require_aware(self.recorded_at, "recorded_at")
        _require_aware(self.valid_until, "valid_until")
        if self.recorded_at >= self.valid_until:
            raise ValueError("source snapshot validity window is invalid")
        if self.recorded_at < max(source.recorded_at for source in self.sources):
            raise ValueError("source snapshot predates a source component")
        if self.valid_until != min(source.valid_until for source in self.sources):
            raise ValueError("source snapshot validity must equal the component intersection")
        if self.schema != _SOURCE_SCHEMA:
            raise ValueError("source snapshot schema is invalid")
        expected = _hash_payload(self._content_payload())
        if not self.content_hash:
            object.__setattr__(self, "content_hash", expected)
        else:
            _require_hash(self.content_hash, "content_hash")
            if self.content_hash != expected:
                raise ValueError("source snapshot content_hash is invalid")

    def is_active_at(self, as_of: datetime) -> bool:
        """Return whether this exact snapshot is knowable and active."""

        _require_aware(as_of, "as_of")
        return self.recorded_at <= as_of < self.valid_until

    def _content_payload(self) -> dict[str, object]:
        return {
            "schema": self.schema,
            "source_snapshot_id": self.source_snapshot_id,
            "source_snapshot_version": self.source_snapshot_version,
            "account_id": self.account_id,
            "controls": self.controls.to_payload(),
            "sources": [source.to_payload() for source in self.sources],
            "recorded_at": _utc_text(self.recorded_at),
            "valid_until": _utc_text(self.valid_until),
        }


@dataclass(frozen=True, slots=True)
class BrokerOrderExecutionPolicyActivation:
    """Persisted first winner binding one policy to its server actor."""

    policy: BrokerOrderExecutionRiskPolicy
    activated_by: BrokerOrderExecutionPolicyActor
    recorded_at: datetime
    content_hash: str = ""
    schema: str = _ACTIVATION_SCHEMA

    def __post_init__(self) -> None:
        if type(self.policy) is not BrokerOrderExecutionRiskPolicy:
            raise TypeError("policy must be an exact BrokerOrderExecutionRiskPolicy")
        BrokerOrderExecutionRiskPolicy.__post_init__(self.policy)
        if type(self.activated_by) is not BrokerOrderExecutionPolicyActor:
            raise TypeError("activated_by must be an exact BrokerOrderExecutionPolicyActor")
        BrokerOrderExecutionPolicyActor.__post_init__(self.activated_by)
        _require_aware(self.recorded_at, "recorded_at")
        if self.recorded_at != self.policy.recorded_at:
            raise ValueError("activation persistence clock must match the policy")
        if self.schema != _ACTIVATION_SCHEMA:
            raise ValueError("activation schema is invalid")
        expected = _hash_payload(self._content_payload())
        if not self.content_hash:
            object.__setattr__(self, "content_hash", expected)
        else:
            _require_hash(self.content_hash, "activation content_hash")
            if self.content_hash != expected:
                raise ValueError("activation content_hash is invalid")

    def _content_payload(self) -> dict[str, object]:
        return {
            "schema": self.schema,
            "policy_content_hash": self.policy.content_hash,
            "activated_by": self.activated_by.to_payload(),
            "recorded_at": _utc_text(self.recorded_at),
        }


@dataclass(frozen=True, slots=True)
class ActivateBrokerOrderExecutionPolicyCommand:
    """ID-only activation selector; content, account, clocks, and head are trusted."""

    policy_id: str
    policy_version: str
    source_snapshot_id: str
    source_snapshot_version: str

    def __post_init__(self) -> None:
        for field_name in (
            "policy_id",
            "policy_version",
            "source_snapshot_id",
            "source_snapshot_version",
        ):
            _require_token(getattr(self, field_name), field_name)


class ExactActiveBrokerOrderExecutionPolicySourceProvider(Protocol):
    """Trusted Risk-owned exact source snapshot reader."""

    def get_exact_active(
        self,
        *,
        source_snapshot_id: str,
        source_snapshot_version: str,
        as_of: datetime,
    ) -> BrokerOrderExecutionPolicySourceSnapshot | None:
        """Return one exact active source snapshot at the cutoff."""


class BrokerOrderExecutionPolicyRepository(Protocol):
    """Private append-only activation and logical-head persistence port."""

    def atomic(self) -> AbstractContextManager[None]:
        """Open one private first-winner transaction."""

    def now(self) -> datetime:
        """Return the authoritative Risk Center server clock."""

    def get_activation_winner(
        self, *, policy_id: str, policy_version: str, as_of: datetime
    ) -> BrokerOrderExecutionPolicyActivation | None:
        """Return the immutable activation identity winner."""

    def get_current_head(
        self, *, account_id: int, as_of: datetime
    ) -> BrokerOrderExecutionPolicyActivation | None:
        """Return the logical policy head knowable at the cutoff."""

    def append_source(
        self,
        source: BrokerOrderExecutionPolicySourceSnapshot,
        *,
        recorded_at: datetime,
    ) -> BrokerOrderExecutionPolicySourceSnapshot:
        """Append or return one exact trusted source-snapshot first winner."""

    def append(
        self,
        activation: BrokerOrderExecutionPolicyActivation,
        *,
        expected_predecessor_hash: str | None,
        recorded_at: datetime,
    ) -> BrokerOrderExecutionPolicyActivation:
        """Append or return one exact first winner using predecessor CAS."""


class ActivateBrokerOrderExecutionPolicy:
    """Activate one Risk-owned policy using IDs and trusted current state only."""

    def __init__(
        self,
        *,
        source_provider: ExactActiveBrokerOrderExecutionPolicySourceProvider,
        repository: BrokerOrderExecutionPolicyRepository,
        actor: BrokerOrderExecutionPolicyActor,
    ) -> None:
        BrokerOrderExecutionPolicyActor.__post_init__(actor)
        self._source_provider = source_provider
        self._repository = repository
        self._actor = actor

    def execute(
        self, command: ActivateBrokerOrderExecutionPolicyCommand
    ) -> BrokerOrderExecutionPolicyActivation:
        """Double-read the source and append one actor-owned first winner."""

        with self._repository.atomic():
            recorded_at = self._repository.now()
            _require_aware(recorded_at, "Risk Center server clock")
            first = self._read_source(command, recorded_at)
            winner = self._repository.get_activation_winner(
                policy_id=command.policy_id,
                policy_version=command.policy_version,
                as_of=recorded_at,
            )
            head = self._repository.get_current_head(
                account_id=first.account_id,
                as_of=recorded_at,
            )
            final = self._read_source(command, recorded_at)
            if first != final:
                raise BrokerOrderExecutionPolicyCorruption(
                    "execution policy source changed during activation"
                )
            persisted_source = self._repository.append_source(
                final,
                recorded_at=recorded_at,
            )
            if persisted_source != final:
                raise BrokerOrderExecutionPolicyConflict(
                    "execution policy source identity has another first winner"
                )
            if winner is not None:
                self._validate_winner(winner, command, final, head, recorded_at)
                return winner
            predecessor_hash = head.policy.content_hash if head is not None else None
            candidate_policy = BrokerOrderExecutionRiskPolicy(
                policy_id=command.policy_id,
                policy_version=command.policy_version,
                account_id=final.account_id,
                controls=final.controls,
                source_snapshot_id=final.source_snapshot_id,
                source_snapshot_version=final.source_snapshot_version,
                source_snapshot_hash=final.content_hash,
                recorded_at=recorded_at,
                activated_at=recorded_at,
                valid_until=final.valid_until,
                supersedes_policy_hash=predecessor_hash,
            )
            if head is not None:
                try:
                    validate_broker_order_execution_policy_successor(head.policy, candidate_policy)
                except (TypeError, ValueError) as error:
                    raise BrokerOrderExecutionPolicyCorruption(
                        "execution policy successor is invalid"
                    ) from error
            candidate = BrokerOrderExecutionPolicyActivation(
                policy=candidate_policy,
                activated_by=self._actor,
                recorded_at=recorded_at,
            )
            persisted = self._repository.append(
                candidate,
                expected_predecessor_hash=predecessor_hash,
                recorded_at=recorded_at,
            )
            _validate_activation(persisted)
            if persisted != candidate:
                raise BrokerOrderExecutionPolicyConflict(
                    "concurrent execution policy first winner differs"
                )
            return persisted

    def _read_source(
        self, command: ActivateBrokerOrderExecutionPolicyCommand, as_of: datetime
    ) -> BrokerOrderExecutionPolicySourceSnapshot:
        value = self._source_provider.get_exact_active(
            source_snapshot_id=command.source_snapshot_id,
            source_snapshot_version=command.source_snapshot_version,
            as_of=as_of,
        )
        if value is None:
            raise BrokerOrderExecutionPolicyUnavailable(
                "exact active execution policy source is unavailable"
            )
        if type(value) is not BrokerOrderExecutionPolicySourceSnapshot:
            raise BrokerOrderExecutionPolicyCorruption("policy source type substitution")
        try:
            BrokerOrderExecutionPolicySourceSnapshot.__post_init__(value)
        except (TypeError, ValueError) as error:
            raise BrokerOrderExecutionPolicyCorruption("policy source is invalid") from error
        if (
            value.source_snapshot_id != command.source_snapshot_id
            or value.source_snapshot_version != command.source_snapshot_version
        ):
            raise BrokerOrderExecutionPolicyCorruption("policy source identity substitution")
        if not value.is_active_at(as_of):
            raise BrokerOrderExecutionPolicyUnavailable(
                "exact active execution policy source is unavailable"
            )
        return value

    def _validate_winner(
        self,
        winner: BrokerOrderExecutionPolicyActivation,
        command: ActivateBrokerOrderExecutionPolicyCommand,
        source: BrokerOrderExecutionPolicySourceSnapshot,
        head: BrokerOrderExecutionPolicyActivation | None,
        as_of: datetime,
    ) -> None:
        value = _validate_activation(winner)
        if value.activated_by != self._actor:
            raise BrokerOrderExecutionPolicyConflict(
                "execution policy identity was activated by another actor"
            )
        policy = value.policy
        if (
            policy.policy_id != command.policy_id
            or policy.policy_version != command.policy_version
            or policy.account_id != source.account_id
            or policy.controls != source.controls
            or policy.source_snapshot_id != source.source_snapshot_id
            or policy.source_snapshot_version != source.source_snapshot_version
            or policy.source_snapshot_hash != source.content_hash
            or policy.valid_until != source.valid_until
        ):
            raise BrokerOrderExecutionPolicyConflict(
                "execution policy identity has another first winner"
            )
        if head is None:
            raise BrokerOrderExecutionPolicyCorruption("execution policy ledger has no head")
        checked_head = _validate_activation(head)
        if checked_head.policy.content_hash != policy.content_hash:
            raise BrokerOrderExecutionPolicyConflict(
                "execution policy identity is no longer the current head"
            )
        if checked_head != value:
            raise BrokerOrderExecutionPolicyCorruption(
                "execution policy head activation differs from its identity winner"
            )
        if not policy.is_active_at(as_of):
            raise BrokerOrderExecutionPolicyUnavailable(
                "persisted execution policy is no longer active"
            )


class ExactCurrentBrokerOrderRiskPolicyProvider:
    """Project only exact, active, logical-current policies for authorization."""

    def __init__(self, repository: BrokerOrderExecutionPolicyRepository) -> None:
        self._repository = repository

    def get_exact_active(
        self,
        *,
        policy_id: str,
        policy_version: str,
        as_of: datetime,
    ) -> BrokerOrderRiskPolicyDefinition | None:
        """Return the authorization DTO only when the exact policy is current."""

        _require_token(policy_id, "policy_id")
        _require_token(policy_version, "policy_version")
        _require_aware(as_of, "as_of")
        value = self._repository.get_activation_winner(
            policy_id=policy_id,
            policy_version=policy_version,
            as_of=as_of,
        )
        if value is None:
            return None
        activation = _validate_activation(value)
        policy = activation.policy
        if policy.policy_id != policy_id or policy.policy_version != policy_version:
            raise BrokerOrderExecutionPolicyCorruption("policy identity substitution")
        head = self._repository.get_current_head(account_id=policy.account_id, as_of=as_of)
        if head is None:
            raise BrokerOrderExecutionPolicyCorruption("execution policy ledger has no head")
        current = _validate_activation(head)
        if current.policy.content_hash != policy.content_hash:
            return None
        if current != activation:
            raise BrokerOrderExecutionPolicyCorruption(
                "execution policy head activation differs from its identity winner"
            )
        if not policy.is_active_at(as_of):
            return None
        return BrokerOrderRiskPolicyDefinition(
            policy_id=policy.policy_id,
            policy_version=policy.policy_version,
            policy_content_hash=policy.content_hash,
            policy_activation_hash=activation.content_hash,
            account_id=policy.account_id,
            activated_at=policy.activated_at,
            valid_until=policy.valid_until,
            recorded_at=policy.recorded_at,
            permission_cap=policy.permission_cap,
        )


def _validate_activation(value: object) -> BrokerOrderExecutionPolicyActivation:
    if type(value) is not BrokerOrderExecutionPolicyActivation:
        raise BrokerOrderExecutionPolicyCorruption("policy activation type substitution")
    try:
        BrokerOrderExecutionPolicyActivation.__post_init__(value)
    except (TypeError, ValueError) as error:
        raise BrokerOrderExecutionPolicyCorruption("policy activation is invalid") from error
    return value


__all__ = [
    "ActivateBrokerOrderExecutionPolicy",
    "ActivateBrokerOrderExecutionPolicyCommand",
    "BrokerOrderExecutionPolicyActivation",
    "BrokerOrderExecutionPolicyActor",
    "BrokerOrderExecutionPolicyConflict",
    "BrokerOrderExecutionPolicyCorruption",
    "BrokerOrderExecutionPolicyRepository",
    "BrokerOrderExecutionPolicySourceSnapshot",
    "BrokerOrderExecutionPolicySourceRef",
    "BrokerOrderExecutionPolicyUnavailable",
    "ExactActiveBrokerOrderExecutionPolicySourceProvider",
    "ExactCurrentBrokerOrderRiskPolicyProvider",
]
