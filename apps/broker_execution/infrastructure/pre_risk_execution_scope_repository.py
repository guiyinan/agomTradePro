"""Append-only persistence and exact PIT reads for Broker pre-Risk scopes."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from typing import Protocol, cast

from django.db import IntegrityError, transaction
from django.utils import timezone

from apps.broker_execution.application.pre_risk_execution_scope import (
    BrokerPreRiskScopeConflict,
    BrokerPreRiskScopeCorruption,
    BrokerPreRiskScopeUnavailable,
)
from apps.broker_execution.domain.pre_risk_execution_scope import (
    BrokerPreRiskExecutionScope,
    validate_pre_risk_scope_successor,
)
from apps.broker_execution.infrastructure.pre_risk_execution_scope_codec import (
    BrokerPreRiskExecutionScopeCodecError,
    decode_broker_pre_risk_execution_scope,
    encode_broker_pre_risk_execution_scope,
)
from apps.broker_execution.infrastructure.pre_risk_execution_scope_models import (
    _ACTIVE_PRE_RISK_SCOPE_UOW,
    BrokerPreRiskExecutionScopeModel,
    _activate_pre_risk_scope_uow,
    _claim_pre_risk_scope_insert,
)


class BrokerPreRiskExecutionScopeUnavailable(BrokerPreRiskScopeUnavailable):
    """An exact historical inactive scope is unavailable at a cutoff."""


class BrokerPreRiskExecutionScopeConflict(BrokerPreRiskScopeConflict):
    """An immutable identity or logical-chain claim has another winner."""


class BrokerPreRiskExecutionScopeCorruption(BrokerPreRiskScopeCorruption):
    """Persisted scope data or chain structure failed exact validation."""


class BrokerPreRiskExecutionScopeClock(Protocol):
    """Authoritative Broker persistence clock."""

    def now(self) -> datetime:
        """Return one timezone-aware server timestamp."""


class DjangoBrokerPreRiskExecutionScopeClock:
    """Django timezone-backed production clock."""

    def now(self) -> datetime:
        """Return the current timezone-aware server timestamp."""

        return cast(datetime, timezone.now())


class DjangoBrokerPreRiskExecutionScopeRepository:
    """Private first-winner ledger with full-chain inactive PIT restore."""

    __slots__ = ("_clock", "_using")

    def __init__(
        self,
        *,
        using: str = "default",
        clock: BrokerPreRiskExecutionScopeClock | None = None,
    ) -> None:
        self._using = using
        self._clock = clock or DjangoBrokerPreRiskExecutionScopeClock()

    @contextmanager
    def atomic(self) -> Iterator[None]:
        """Open this ledger's independent private append transaction."""

        token = object()
        with (
            transaction.atomic(using=self._using),
            _activate_pre_risk_scope_uow(token),
        ):
            yield

    def now(self) -> datetime:
        """Return the validated authoritative Broker clock."""

        value = self._clock.now()
        if value.tzinfo is None or value.utcoffset() is None:
            raise BrokerPreRiskExecutionScopeCorruption("Broker scope clock is naive")
        return value

    def append(
        self,
        scope: BrokerPreRiskExecutionScope,
        *,
        expected_predecessor_hash: str | None,
        recorded_at: datetime,
    ) -> BrokerPreRiskExecutionScope:
        """CAS-append or return the exact identity/logical-claim first winner."""

        token = _active_token()
        _require_aware(recorded_at, "recorded_at")
        if recorded_at != scope.recorded_at:
            raise BrokerPreRiskExecutionScopeConflict(
                "persisted_at and scope recorded_at must be identical"
            )
        if expected_predecessor_hash != scope.supersedes_scope_hash:
            raise BrokerPreRiskExecutionScopeConflict(
                "scope does not bind the expected predecessor"
            )
        if not scope.is_knowable_at(recorded_at):
            raise BrokerPreRiskExecutionScopeConflict(
                "scope must be persisted inside its validity window"
            )
        existing = self._exact_model(scope)
        if existing is not None:
            return self._restore(existing)
        current = self._current_head(
            broker_account_id=scope.broker_account_id,
            order_artifact_id=scope.order_artifact_id,
            as_of=recorded_at,
            lock=True,
        )
        actual_predecessor = current.content_hash if current is not None else None
        if actual_predecessor != expected_predecessor_hash:
            raise BrokerPreRiskExecutionScopeConflict("pre-Risk scope predecessor CAS conflict")
        if current is not None:
            try:
                validate_pre_risk_scope_successor(current, scope)
            except (TypeError, ValueError) as error:
                raise BrokerPreRiskExecutionScopeConflict(
                    "pre-Risk scope successor is invalid"
                ) from error
        values = _model_values(scope, recorded_at=recorded_at)
        model = BrokerPreRiskExecutionScopeModel(**values)
        try:
            with transaction.atomic(using=self._using):
                with _claim_pre_risk_scope_insert(
                    token=token,
                    model_type=BrokerPreRiskExecutionScopeModel,
                    expected_values=values,
                ):
                    model.save(force_insert=True, using=self._using)
        except IntegrityError:
            winner = self._exact_model(scope)
            if winner is None:
                raise BrokerPreRiskExecutionScopeConflict(
                    "scope append conflicted without an exact visible first winner"
                ) from None
            return self._restore(winner)
        return self._restore(model)

    def get_scope_winner(
        self, *, scope_id: str, scope_version: str, as_of: datetime
    ) -> BrokerPreRiskExecutionScope | None:
        """Return the identity first winner only when exactly knowable at the cutoff."""

        self._require_cutoff(as_of)
        values = self._visible_scopes(as_of=as_of, lock=False)
        matches = tuple(
            value
            for value in values
            if value.scope_id == scope_id and value.scope_version == scope_version
        )
        if not matches:
            return None
        if len(matches) != 1:
            raise BrokerPreRiskExecutionScopeCorruption("scope identity first winner is ambiguous")
        value = matches[0]
        return value if value.is_knowable_at(as_of) else None

    def get_exact_by_hash(
        self,
        *,
        scope_id: str,
        scope_version: str,
        expected_content_hash: str,
        as_of: datetime,
    ) -> BrokerPreRiskExecutionScope | None:
        """Return one exact inactive identity/hash/PIT scope."""

        self._require_cutoff(as_of)
        values = self._visible_scopes(as_of=as_of, lock=False)
        anchors = tuple(
            value
            for value in values
            if (
                (value.scope_id == scope_id and value.scope_version == scope_version)
                or value.content_hash == expected_content_hash
            )
        )
        if not anchors:
            return None
        matches = tuple(
            value
            for value in anchors
            if value.scope_id == scope_id
            and value.scope_version == scope_version
            and value.content_hash == expected_content_hash
        )
        if len(anchors) != 1 or len(matches) != 1:
            raise BrokerPreRiskExecutionScopeCorruption(
                "scope exact identity/content anchors are ambiguous"
            )
        value = matches[0]
        return value if value.is_knowable_at(as_of) else None

    def get_current_head(
        self, *, broker_account_id: int, order_artifact_id: str, as_of: datetime
    ) -> BrokerPreRiskExecutionScope | None:
        """Restore the full visible chain and return its exact inactive PIT head."""

        self._require_cutoff(as_of)
        return self._current_head(
            broker_account_id=broker_account_id,
            order_artifact_id=order_artifact_id,
            as_of=as_of,
            lock=False,
        )

    def _current_head(
        self,
        *,
        broker_account_id: int,
        order_artifact_id: str,
        as_of: datetime,
        lock: bool,
    ) -> BrokerPreRiskExecutionScope | None:
        visible = self._visible_scopes(as_of=as_of, lock=lock)
        chain = tuple(
            value
            for value in visible
            if value.broker_account_id == broker_account_id
            and value.order_artifact_id == order_artifact_id
        )
        if not chain:
            return None
        head = _restore_full_chain(chain)
        return head if head.is_knowable_at(as_of) else None

    def _visible_scopes(
        self, *, as_of: datetime, lock: bool
    ) -> tuple[BrokerPreRiskExecutionScope, ...]:
        """Restore the closed world before trusting any mutable DB selector header."""

        queryset = BrokerPreRiskExecutionScopeModel._default_manager.using(self._using).all()
        if lock:
            queryset = queryset.select_for_update()
        rows = list(queryset.order_by("recorded_at", "pk"))
        restored = tuple(self._restore(row) for row in rows)
        return tuple(value for value in restored if value.recorded_at <= as_of)

    def _require_cutoff(self, as_of: datetime) -> None:
        _require_aware(as_of, "scope as_of")
        if as_of > self.now():
            raise BrokerPreRiskExecutionScopeUnavailable("future pre-Risk scope as_of is forbidden")

    def _exact_model(
        self, scope: BrokerPreRiskExecutionScope
    ) -> BrokerPreRiskExecutionScopeModel | None:
        root_claim = _root_claim_hash(scope)
        rows = list(BrokerPreRiskExecutionScopeModel._default_manager.using(self._using).all())
        if not rows:
            return None
        restored = tuple((row, self._restore(row)) for row in rows)
        anchors = tuple(
            (row, value)
            for row, value in restored
            if (
                (value.scope_id == scope.scope_id and value.scope_version == scope.scope_version)
                or value.content_hash == scope.content_hash
                or (scope.supersedes_scope_hash is None and row.root_claim_hash == root_claim)
                or (
                    scope.supersedes_scope_hash is not None
                    and value.supersedes_scope_hash == scope.supersedes_scope_hash
                )
            )
        )
        if not anchors:
            return None
        matches = tuple(row for row, value in anchors if value == scope)
        if len(anchors) != 1 or len(matches) != 1:
            raise BrokerPreRiskExecutionScopeConflict(
                "scope uniqueness or logical-chain claim has another first winner"
            )
        return cast(BrokerPreRiskExecutionScopeModel, matches[0])

    def _restore(self, model: BrokerPreRiskExecutionScopeModel) -> BrokerPreRiskExecutionScope:
        try:
            scope = decode_broker_pre_risk_execution_scope(model.canonical_payload)
        except BrokerPreRiskExecutionScopeCodecError as error:
            raise BrokerPreRiskExecutionScopeCorruption(
                "scope canonical payload cannot be restored"
            ) from error
        if _scope_headers(scope) != _model_headers(model):
            raise BrokerPreRiskExecutionScopeCorruption(
                "scope headers do not match canonical payload"
            )
        if model.root_claim_hash != (
            _root_claim_hash(scope) if scope.supersedes_scope_hash is None else None
        ):
            raise BrokerPreRiskExecutionScopeCorruption("scope root logical-chain claim is invalid")
        if model.ledger_header_hash != _ledger_header_hash(scope, recorded_at=model.recorded_at):
            raise BrokerPreRiskExecutionScopeCorruption("scope ledger header seal is invalid")
        if (
            model.persisted_at.tzinfo is None
            or model.persisted_at.utcoffset() is None
            or model.persisted_at != model.recorded_at
            or model.recorded_at != scope.recorded_at
        ):
            raise BrokerPreRiskExecutionScopeCorruption(
                "scope database persistence clock is invalid"
            )
        return scope


def _active_token() -> object:
    token = _ACTIVE_PRE_RISK_SCOPE_UOW.get()
    if token is None:
        raise BrokerPreRiskExecutionScopeConflict(
            "scope append requires an active private unit of work"
        )
    return token


def _require_aware(value: datetime, field_name: str) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise BrokerPreRiskExecutionScopeUnavailable(f"{field_name} must be timezone-aware")


def _hash_payload(payload: dict[str, object]) -> str:
    return hashlib.sha256(
        json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()


def _time(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _root_claim_hash(scope: BrokerPreRiskExecutionScope) -> str:
    return _hash_payload(
        {
            "broker_account_id": scope.broker_account_id,
            "order_artifact_id": scope.order_artifact_id,
        }
    )


def _ledger_header_hash(scope: BrokerPreRiskExecutionScope, *, recorded_at: datetime) -> str:
    return _hash_payload(
        {
            "scope_id": scope.scope_id,
            "scope_version": scope.scope_version,
            "content_hash": scope.content_hash,
            "broker_account_id": scope.broker_account_id,
            "portfolio_account_id": scope.portfolio_account_id,
            "plan_id": scope.plan_id,
            "plan_version": scope.plan_version,
            "plan_content_hash": scope.plan_content_hash,
            "portfolio_receipt_id": scope.portfolio_receipt_id,
            "portfolio_receipt_version": scope.portfolio_receipt_version,
            "portfolio_receipt_content_hash": scope.portfolio_receipt_content_hash,
            "order_artifact_id": scope.order_artifact_id,
            "order_artifact_version": scope.order_artifact_version,
            "order_artifact_content_hash": scope.order_artifact_content_hash,
            "supersedes_scope_hash": scope.supersedes_scope_hash,
            "recorded_at": _time(recorded_at),
            "valid_until": _time(scope.valid_until),
        }
    )


def _model_values(
    scope: BrokerPreRiskExecutionScope, *, recorded_at: datetime
) -> dict[str, object]:
    return {
        "owner": scope.owner,
        "scope_id": scope.scope_id,
        "scope_version": scope.scope_version,
        "permission": scope.permission,
        "broker_account_id": scope.broker_account_id,
        "portfolio_account_id": scope.portfolio_account_id,
        "plan_id": scope.plan_id,
        "plan_version": scope.plan_version,
        "plan_content_hash": scope.plan_content_hash,
        "portfolio_receipt_id": scope.portfolio_receipt_id,
        "portfolio_receipt_version": scope.portfolio_receipt_version,
        "portfolio_receipt_content_hash": scope.portfolio_receipt_content_hash,
        "order_artifact_id": scope.order_artifact_id,
        "order_artifact_version": scope.order_artifact_version,
        "order_artifact_content_hash": scope.order_artifact_content_hash,
        "recorded_at": recorded_at,
        "valid_until": scope.valid_until,
        "supersedes_scope_hash": scope.supersedes_scope_hash,
        "root_claim_hash": (
            _root_claim_hash(scope) if scope.supersedes_scope_hash is None else None
        ),
        "canonical_payload": encode_broker_pre_risk_execution_scope(scope),
        "content_hash": scope.content_hash,
        "ledger_header_hash": _ledger_header_hash(scope, recorded_at=recorded_at),
        "persisted_at": recorded_at,
    }


def _scope_headers(scope: BrokerPreRiskExecutionScope) -> tuple[object, ...]:
    return (
        scope.owner,
        scope.scope_id,
        scope.scope_version,
        scope.permission,
        scope.broker_account_id,
        scope.portfolio_account_id,
        scope.plan_id,
        scope.plan_version,
        scope.plan_content_hash,
        scope.portfolio_receipt_id,
        scope.portfolio_receipt_version,
        scope.portfolio_receipt_content_hash,
        scope.order_artifact_id,
        scope.order_artifact_version,
        scope.order_artifact_content_hash,
        scope.recorded_at,
        scope.valid_until,
        scope.supersedes_scope_hash,
        scope.content_hash,
    )


def _model_headers(model: BrokerPreRiskExecutionScopeModel) -> tuple[object, ...]:
    return (
        model.owner,
        model.scope_id,
        model.scope_version,
        model.permission,
        model.broker_account_id,
        model.portfolio_account_id,
        model.plan_id,
        model.plan_version,
        model.plan_content_hash,
        model.portfolio_receipt_id,
        model.portfolio_receipt_version,
        model.portfolio_receipt_content_hash,
        str(model.order_artifact_id),
        model.order_artifact_version,
        model.order_artifact_content_hash,
        model.recorded_at,
        model.valid_until,
        model.supersedes_scope_hash,
        model.content_hash,
    )


def _restore_full_chain(
    values: tuple[BrokerPreRiskExecutionScope, ...],
) -> BrokerPreRiskExecutionScope:
    by_hash = {value.content_hash: value for value in values}
    if len(by_hash) != len(values):
        raise BrokerPreRiskExecutionScopeCorruption("scope chain has duplicate content")
    roots = tuple(value for value in values if value.supersedes_scope_hash is None)
    if len(roots) != 1:
        raise BrokerPreRiskExecutionScopeCorruption(
            "scope chain must have exactly one visible root"
        )
    successor_by_predecessor: dict[str, BrokerPreRiskExecutionScope] = {}
    for value in values:
        predecessor_hash = value.supersedes_scope_hash
        if predecessor_hash is None:
            continue
        predecessor = by_hash.get(predecessor_hash)
        if predecessor is None:
            raise BrokerPreRiskExecutionScopeCorruption(
                "scope chain predecessor is missing at cutoff"
            )
        if predecessor_hash in successor_by_predecessor:
            raise BrokerPreRiskExecutionScopeCorruption(
                "scope chain predecessor has multiple successors"
            )
        try:
            validate_pre_risk_scope_successor(predecessor, value)
        except (TypeError, ValueError) as error:
            raise BrokerPreRiskExecutionScopeCorruption(
                "scope chain successor link is invalid"
            ) from error
        successor_by_predecessor[predecessor_hash] = value
    visited: set[str] = set()
    current = roots[0]
    while current.content_hash not in visited:
        visited.add(current.content_hash)
        successor = successor_by_predecessor.get(current.content_hash)
        if successor is None:
            break
        current = successor
    if len(visited) != len(values):
        raise BrokerPreRiskExecutionScopeCorruption("scope chain is disconnected or cyclic")
    return current


__all__ = [
    "BrokerPreRiskExecutionScopeClock",
    "BrokerPreRiskExecutionScopeConflict",
    "BrokerPreRiskExecutionScopeCorruption",
    "BrokerPreRiskExecutionScopeUnavailable",
    "DjangoBrokerPreRiskExecutionScopeClock",
    "DjangoBrokerPreRiskExecutionScopeRepository",
]
