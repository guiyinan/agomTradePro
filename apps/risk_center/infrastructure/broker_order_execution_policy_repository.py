"""Strict append-only persistence for Broker execution-risk policies."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from typing import Protocol, cast

from django.db import IntegrityError, transaction
from django.db.models import Q
from django.utils import timezone

from apps.risk_center.application.broker_order_execution_policy import (
    BrokerOrderExecutionPolicyActivation,
    BrokerOrderExecutionPolicyConflict,
    BrokerOrderExecutionPolicyCorruption,
    BrokerOrderExecutionPolicySourceSnapshot,
    BrokerOrderExecutionPolicyUnavailable,
)
from apps.risk_center.infrastructure.broker_order_execution_policy_codec import (
    BrokerOrderExecutionPolicyCodecError,
    decode_broker_order_execution_policy,
    decode_broker_order_execution_policy_activation,
    decode_broker_order_execution_policy_source,
    encode_broker_order_execution_policy,
    encode_broker_order_execution_policy_activation,
    encode_broker_order_execution_policy_source,
)
from apps.risk_center.infrastructure.broker_order_execution_policy_models import (
    _ACTIVE_BROKER_EXECUTION_POLICY_UOW,
    BrokerOrderExecutionPolicyActivationModel,
    BrokerOrderExecutionPolicySourceModel,
    _activate_broker_execution_policy_uow,
    _claim_broker_execution_policy_insert,
)


class BrokerOrderExecutionPolicyClock(Protocol):
    """Authoritative persistence clock."""

    def now(self) -> datetime:
        """Return one timezone-aware server timestamp."""


class DjangoBrokerOrderExecutionPolicyClock:
    """Django timezone-backed production clock."""

    def now(self) -> datetime:
        """Return the current timezone-aware server timestamp."""

        return cast(datetime, timezone.now())


class DjangoBrokerOrderExecutionPolicyRepository:
    """Private append store and strict identity/current/PIT reader."""

    __slots__ = ("_clock", "_using")

    def __init__(
        self,
        *,
        using: str = "default",
        clock: BrokerOrderExecutionPolicyClock | None = None,
    ) -> None:
        self._using = using
        self._clock = clock or DjangoBrokerOrderExecutionPolicyClock()

    @contextmanager
    def atomic(self) -> Iterator[None]:
        """Open this capability's distinct private first-winner transaction."""

        token = object()
        with (
            transaction.atomic(using=self._using),
            _activate_broker_execution_policy_uow(token),
        ):
            yield

    def now(self) -> datetime:
        """Return the validated authoritative Risk Center clock."""

        value = self._clock.now()
        if value.tzinfo is None or value.utcoffset() is None:
            raise BrokerOrderExecutionPolicyCorruption(
                "Risk Center Broker execution policy clock is naive"
            )
        return value

    def get_activation_winner(
        self, *, policy_id: str, policy_version: str, as_of: datetime
    ) -> BrokerOrderExecutionPolicyActivation | None:
        """Return one immutable activation identity winner knowable at the cutoff."""

        self._require_cutoff(as_of)
        seal = _policy_identity_hash(policy_id, policy_version)
        rows = list(
            BrokerOrderExecutionPolicyActivationModel._default_manager.using(self._using)
            .select_related("source")
            .filter(
                Q(policy_id=policy_id, policy_version=policy_version) | Q(policy_identity_hash=seal)
            )
        )
        if not rows:
            return None
        values = tuple(self._restore_activation(row) for row in rows)
        matches = tuple(
            (value, row)
            for value, row in zip(values, rows, strict=True)
            if value.policy.policy_id == policy_id and value.policy.policy_version == policy_version
        )
        if len(matches) != 1:
            raise BrokerOrderExecutionPolicyCorruption("policy activation identity is ambiguous")
        value, row = matches[0]
        return value if row.recorded_at <= as_of else None

    def get_current_head(
        self, *, account_id: int, as_of: datetime
    ) -> BrokerOrderExecutionPolicyActivation | None:
        """Restore the full ledger and return the unique account head at a cutoff."""

        self._require_cutoff(as_of)
        rows = list(
            BrokerOrderExecutionPolicyActivationModel._default_manager.using(self._using)
            .select_related("source")
            .filter(recorded_at__lte=as_of)
        )
        all_values = tuple(self._restore_activation(row) for row in rows)
        values = tuple(value for value in all_values if value.policy.account_id == account_id)
        if not values:
            return None
        by_hash = {value.policy.content_hash: value for value in values}
        if len(by_hash) != len(values):
            raise BrokerOrderExecutionPolicyCorruption("policy chain content hash is ambiguous")
        roots = tuple(value for value in values if value.policy.supersedes_policy_hash is None)
        if len(roots) != 1:
            raise BrokerOrderExecutionPolicyCorruption(
                "Broker execution policy chain must have exactly one root"
            )
        children: dict[str, BrokerOrderExecutionPolicyActivation] = {}
        for value in values:
            predecessor_hash = value.policy.supersedes_policy_hash
            if predecessor_hash is None:
                continue
            predecessor = by_hash.get(predecessor_hash)
            if predecessor is None:
                raise BrokerOrderExecutionPolicyCorruption(
                    "Broker execution policy chain has an orphan predecessor"
                )
            if predecessor.recorded_at >= value.recorded_at:
                raise BrokerOrderExecutionPolicyCorruption(
                    "Broker execution policy chain clock is not monotonic"
                )
            if predecessor_hash in children:
                raise BrokerOrderExecutionPolicyCorruption(
                    "Broker execution policy chain has a fork"
                )
            children[predecessor_hash] = value
        reachable: set[str] = set()
        cursor = roots[0]
        while cursor.policy.content_hash not in reachable:
            reachable.add(cursor.policy.content_hash)
            successor = children.get(cursor.policy.content_hash)
            if successor is None:
                break
            cursor = successor
        if len(reachable) != len(values):
            raise BrokerOrderExecutionPolicyCorruption(
                "Broker execution policy chain is disconnected or cyclic"
            )
        heads = tuple(value for value in values if value.policy.content_hash not in children)
        if len(heads) != 1:
            raise BrokerOrderExecutionPolicyCorruption(
                "Broker execution policy chain has multiple heads"
            )
        return heads[0]

    def append_source(
        self,
        source: BrokerOrderExecutionPolicySourceSnapshot,
        *,
        recorded_at: datetime,
    ) -> BrokerOrderExecutionPolicySourceSnapshot:
        """Append or return one exact complete source-bundle first winner."""

        if not source.recorded_at <= recorded_at < source.valid_until:
            raise BrokerOrderExecutionPolicyConflict(
                "policy source is not active at the authoritative transaction clock"
            )
        _active_token()
        existing = self._exact_source_model(source)
        if existing is not None:
            return self._restore_source(existing)
        values = _source_values(source, recorded_at=recorded_at)
        model = BrokerOrderExecutionPolicySourceModel(**values)
        try:
            with transaction.atomic(using=self._using):
                with _claim_broker_execution_policy_insert(
                    token=_active_token(),
                    model_type=BrokerOrderExecutionPolicySourceModel,
                    expected_values=values,
                ):
                    model.save(force_insert=True, using=self._using)
        except IntegrityError:
            winner = self._exact_source_model(source)
            if winner is None:
                raise BrokerOrderExecutionPolicyConflict(
                    "policy source append conflicted without an exact first winner"
                ) from None
            return self._restore_source(winner)
        return self._restore_source(model)

    def append(
        self,
        activation: BrokerOrderExecutionPolicyActivation,
        *,
        expected_predecessor_hash: str | None,
        recorded_at: datetime,
    ) -> BrokerOrderExecutionPolicyActivation:
        """Append one actor-bound activation using current-head CAS."""

        policy = activation.policy
        if recorded_at != activation.recorded_at or recorded_at != policy.recorded_at:
            raise BrokerOrderExecutionPolicyConflict(
                "policy activation must use the authoritative transaction clock"
            )
        if policy.supersedes_policy_hash != expected_predecessor_hash:
            raise BrokerOrderExecutionPolicyConflict("policy predecessor mismatch")
        _active_token()
        current = self.get_current_head(account_id=policy.account_id, as_of=recorded_at)
        if (current.policy.content_hash if current else None) != expected_predecessor_hash:
            raise BrokerOrderExecutionPolicyConflict("policy current head changed")
        source_model = self._bound_source_model(activation)
        values = _activation_values(activation)
        claimed = {**values, "source_id": source_model.pk}
        model = BrokerOrderExecutionPolicyActivationModel(**claimed)
        try:
            with transaction.atomic(using=self._using):
                with _claim_broker_execution_policy_insert(
                    token=_active_token(),
                    model_type=BrokerOrderExecutionPolicyActivationModel,
                    expected_values=claimed,
                ):
                    model.save(force_insert=True, using=self._using)
        except IntegrityError:
            winner = self._exact_activation_model(activation)
            if winner is None:
                raise BrokerOrderExecutionPolicyConflict(
                    "policy activation conflicted without an exact first winner"
                ) from None
            return self._restore_activation(winner)
        return self._restore_activation(model)

    def _require_cutoff(self, as_of: datetime) -> None:
        if as_of.tzinfo is None or as_of.utcoffset() is None:
            raise BrokerOrderExecutionPolicyUnavailable("policy as_of is naive")
        if as_of > self.now():
            raise BrokerOrderExecutionPolicyUnavailable("future policy as_of is not permitted")

    def _exact_source_model(
        self, source: BrokerOrderExecutionPolicySourceSnapshot
    ) -> BrokerOrderExecutionPolicySourceModel | None:
        rows = list(BrokerOrderExecutionPolicySourceModel._default_manager.using(self._using).all())
        restored = tuple((row, self._restore_source(row)) for row in rows)
        identity_matches = tuple(
            (row, value)
            for row, value in restored
            if value.source_snapshot_id == source.source_snapshot_id
            and value.source_snapshot_version == source.source_snapshot_version
        )
        if not identity_matches:
            return None
        exact_matches = tuple(row for row, value in identity_matches if value == source)
        if len(identity_matches) != 1 or len(exact_matches) != 1:
            raise BrokerOrderExecutionPolicyConflict(
                "policy source identity has another first winner"
            )
        return exact_matches[0]

    def _bound_source_model(
        self, activation: BrokerOrderExecutionPolicyActivation
    ) -> BrokerOrderExecutionPolicySourceModel:
        policy = activation.policy
        restored = tuple(
            (row, self._restore_source(row))
            for row in BrokerOrderExecutionPolicySourceModel._default_manager.using(
                self._using
            ).all()
        )
        matches = tuple(
            (row, source)
            for row, source in restored
            if source.source_snapshot_id == policy.source_snapshot_id
            and source.source_snapshot_version == policy.source_snapshot_version
        )
        if len(matches) != 1:
            raise BrokerOrderExecutionPolicyConflict(
                "policy activation requires its exact registered source"
            )
        row, source = matches[0]
        if (
            source.content_hash != policy.source_snapshot_hash
            or source.account_id != policy.account_id
            or source.controls != policy.controls
            or source.valid_until != policy.valid_until
            or source.recorded_at > policy.recorded_at
        ):
            raise BrokerOrderExecutionPolicyConflict(
                "policy activation does not bind the registered source"
            )
        return row

    def _exact_activation_model(
        self, activation: BrokerOrderExecutionPolicyActivation
    ) -> BrokerOrderExecutionPolicyActivationModel | None:
        policy = activation.policy
        seal = _policy_identity_hash(policy.policy_id, policy.policy_version)
        rows = list(
            BrokerOrderExecutionPolicyActivationModel._default_manager.using(self._using)
            .select_related("source")
            .filter(
                Q(policy_id=policy.policy_id, policy_version=policy.policy_version)
                | Q(policy_identity_hash=seal)
                | Q(policy_content_hash=policy.content_hash)
                | Q(activation_content_hash=activation.content_hash)
            )
        )
        if not rows:
            return None
        matches = tuple(row for row in rows if self._restore_activation(row) == activation)
        if len(rows) != 1 or len(matches) != 1:
            raise BrokerOrderExecutionPolicyConflict(
                "policy activation uniqueness anchor has another first winner"
            )
        return matches[0]

    def _restore_source(
        self, model: BrokerOrderExecutionPolicySourceModel
    ) -> BrokerOrderExecutionPolicySourceSnapshot:
        try:
            value = decode_broker_order_execution_policy_source(model.canonical_payload)
        except BrokerOrderExecutionPolicyCodecError as error:
            raise BrokerOrderExecutionPolicyCorruption(
                "policy source payload cannot be restored"
            ) from error
        if _source_headers(value) != _source_model_headers(model):
            raise BrokerOrderExecutionPolicyCorruption("policy source headers do not match payload")
        expected_identity = _source_identity_hash(
            value.source_snapshot_id, value.source_snapshot_version
        )
        if model.source_identity_hash != expected_identity:
            raise BrokerOrderExecutionPolicyCorruption("policy source identity seal is invalid")
        if model.ledger_header_hash != _source_ledger_hash(value, model.recorded_at):
            raise BrokerOrderExecutionPolicyCorruption("policy source ledger seal is invalid")
        if (
            model.persisted_at.tzinfo is None
            or model.persisted_at.utcoffset() is None
            or model.persisted_at != model.recorded_at
            or value.recorded_at > model.recorded_at
        ):
            raise BrokerOrderExecutionPolicyCorruption("policy source persistence clock is invalid")
        return value

    def _restore_activation(
        self, model: BrokerOrderExecutionPolicyActivationModel
    ) -> BrokerOrderExecutionPolicyActivation:
        source = self._restore_source(model.source)
        try:
            policy = decode_broker_order_execution_policy(model.canonical_policy)
            value = decode_broker_order_execution_policy_activation(model.canonical_activation)
        except BrokerOrderExecutionPolicyCodecError as error:
            raise BrokerOrderExecutionPolicyCorruption(
                "policy activation payload cannot be restored"
            ) from error
        if value.policy != policy or _activation_headers(value) != _activation_model_headers(model):
            raise BrokerOrderExecutionPolicyCorruption(
                "policy activation headers do not match payload"
            )
        if (
            source.source_snapshot_id != policy.source_snapshot_id
            or source.source_snapshot_version != policy.source_snapshot_version
            or source.content_hash != policy.source_snapshot_hash
            or source.account_id != policy.account_id
            or source.controls != policy.controls
            or source.valid_until != policy.valid_until
            or source.recorded_at > policy.recorded_at
        ):
            raise BrokerOrderExecutionPolicyCorruption(
                "policy activation source binding is invalid"
            )
        expected_identity = _policy_identity_hash(policy.policy_id, policy.policy_version)
        if model.policy_identity_hash != expected_identity:
            raise BrokerOrderExecutionPolicyCorruption("policy activation identity seal is invalid")
        if model.ledger_header_hash != _activation_ledger_hash(value):
            raise BrokerOrderExecutionPolicyCorruption("policy activation ledger seal is invalid")
        if (
            model.persisted_at.tzinfo is None
            or model.persisted_at.utcoffset() is None
            or model.persisted_at != model.recorded_at
        ):
            raise BrokerOrderExecutionPolicyCorruption(
                "policy activation persistence clock is invalid"
            )
        return value


def _active_token() -> object:
    token = _ACTIVE_BROKER_EXECUTION_POLICY_UOW.get()
    if token is None:
        raise BrokerOrderExecutionPolicyConflict(
            "policy append requires an active private unit of work"
        )
    return token


def _hash(payload: dict[str, object]) -> str:
    return hashlib.sha256(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def _time(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _source_identity_hash(source_id: str, source_version: str) -> str:
    return _hash(
        {"kind": "broker_execution_policy_source", "id": source_id, "version": source_version}
    )


def _policy_identity_hash(policy_id: str, policy_version: str) -> str:
    return _hash({"kind": "broker_execution_policy", "id": policy_id, "version": policy_version})


def _source_ledger_hash(
    value: BrokerOrderExecutionPolicySourceSnapshot, recorded_at: datetime
) -> str:
    return _hash(
        {
            "identity": _source_identity_hash(
                value.source_snapshot_id, value.source_snapshot_version
            ),
            "content": value.content_hash,
            "source_recorded_at": _time(value.recorded_at),
            "recorded_at": _time(recorded_at),
        }
    )


def _activation_ledger_hash(value: BrokerOrderExecutionPolicyActivation) -> str:
    policy = value.policy
    return _hash(
        {
            "identity": _policy_identity_hash(policy.policy_id, policy.policy_version),
            "policy_content": policy.content_hash,
            "activation_content": value.content_hash,
            "source_content": policy.source_snapshot_hash,
            "recorded_at": _time(value.recorded_at),
        }
    )


def _source_values(
    value: BrokerOrderExecutionPolicySourceSnapshot, *, recorded_at: datetime
) -> dict[str, object]:
    return {
        "source_snapshot_id": value.source_snapshot_id,
        "source_snapshot_version": value.source_snapshot_version,
        "source_identity_hash": _source_identity_hash(
            value.source_snapshot_id, value.source_snapshot_version
        ),
        "account_id": value.account_id,
        "source_recorded_at": value.recorded_at,
        "recorded_at": recorded_at,
        "valid_until": value.valid_until,
        "canonical_payload": encode_broker_order_execution_policy_source(value),
        "content_hash": value.content_hash,
        "ledger_header_hash": _source_ledger_hash(value, recorded_at),
        "persisted_at": recorded_at,
    }


def _activation_values(value: BrokerOrderExecutionPolicyActivation) -> dict[str, object]:
    policy = value.policy
    actor = value.activated_by
    return {
        "owner": policy.owner,
        "capability": policy.capability,
        "schema": policy.schema,
        "permission_cap": policy.permission_cap,
        "policy_id": policy.policy_id,
        "policy_version": policy.policy_version,
        "policy_identity_hash": _policy_identity_hash(policy.policy_id, policy.policy_version),
        "account_id": policy.account_id,
        "source_snapshot_id": policy.source_snapshot_id,
        "source_snapshot_version": policy.source_snapshot_version,
        "source_snapshot_hash": policy.source_snapshot_hash,
        "supersedes_policy_hash": policy.supersedes_policy_hash,
        "activated_actor_id": actor.actor_id,
        "activated_actor_user_id": actor.user_id,
        "activated_actor_kind": actor.kind,
        "activated_actor_is_staff": actor.is_staff,
        "recorded_at": value.recorded_at,
        "activated_at": policy.activated_at,
        "valid_until": policy.valid_until,
        "canonical_policy": encode_broker_order_execution_policy(policy),
        "canonical_activation": encode_broker_order_execution_policy_activation(value),
        "policy_content_hash": policy.content_hash,
        "activation_content_hash": value.content_hash,
        "ledger_header_hash": _activation_ledger_hash(value),
        "persisted_at": value.recorded_at,
    }


def _source_headers(value: BrokerOrderExecutionPolicySourceSnapshot) -> tuple[object, ...]:
    return (
        value.source_snapshot_id,
        value.source_snapshot_version,
        value.account_id,
        value.recorded_at,
        value.valid_until,
        value.content_hash,
    )


def _source_model_headers(model: BrokerOrderExecutionPolicySourceModel) -> tuple[object, ...]:
    return (
        model.source_snapshot_id,
        model.source_snapshot_version,
        model.account_id,
        model.source_recorded_at,
        model.valid_until,
        model.content_hash,
    )


def _activation_headers(value: BrokerOrderExecutionPolicyActivation) -> tuple[object, ...]:
    policy = value.policy
    actor = value.activated_by
    return (
        policy.owner,
        policy.capability,
        policy.schema,
        policy.permission_cap,
        policy.policy_id,
        policy.policy_version,
        policy.account_id,
        policy.source_snapshot_id,
        policy.source_snapshot_version,
        policy.source_snapshot_hash,
        policy.supersedes_policy_hash,
        actor.actor_id,
        actor.user_id,
        actor.kind,
        actor.is_staff,
        value.recorded_at,
        policy.activated_at,
        policy.valid_until,
        policy.content_hash,
        value.content_hash,
    )


def _activation_model_headers(
    model: BrokerOrderExecutionPolicyActivationModel,
) -> tuple[object, ...]:
    return (
        model.owner,
        model.capability,
        model.schema,
        model.permission_cap,
        model.policy_id,
        model.policy_version,
        model.account_id,
        model.source_snapshot_id,
        model.source_snapshot_version,
        model.source_snapshot_hash,
        model.supersedes_policy_hash,
        model.activated_actor_id,
        model.activated_actor_user_id,
        model.activated_actor_kind,
        model.activated_actor_is_staff,
        model.recorded_at,
        model.activated_at,
        model.valid_until,
        model.policy_content_hash,
        model.activation_content_hash,
    )


__all__ = [
    "BrokerOrderExecutionPolicyClock",
    "DjangoBrokerOrderExecutionPolicyClock",
    "DjangoBrokerOrderExecutionPolicyRepository",
]
