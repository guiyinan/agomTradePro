"""Append-only persistence and exact PIT reads for account namespace bindings."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from typing import Protocol, cast

from django.db import IntegrityError, transaction
from django.utils import timezone

from apps.broker_execution.application.portfolio_broker_account_binding import (
    BrokerPortfolioAccountBindingConflict,
    BrokerPortfolioAccountBindingCorruption,
    BrokerPortfolioAccountBindingUnavailable,
)
from apps.broker_execution.domain.portfolio_broker_account_binding import (
    BrokerPortfolioAccountNamespaceBinding,
    validate_broker_portfolio_account_binding_successor,
)
from apps.broker_execution.infrastructure.portfolio_broker_account_binding_codec import (
    BrokerPortfolioAccountBindingCodecError,
    decode_broker_portfolio_account_binding,
    encode_broker_portfolio_account_binding,
)
from apps.broker_execution.infrastructure.portfolio_broker_account_binding_models import (
    _ACTIVE_PORTFOLIO_BROKER_BINDING_UOW,
    BrokerPortfolioAccountBindingModel,
    _activate_portfolio_broker_binding_uow,
    _claim_portfolio_broker_binding_insert,
)


class BrokerPortfolioAccountBindingClock(Protocol):
    """Authoritative Broker persistence clock."""

    def now(self) -> datetime:
        """Return one timezone-aware server timestamp."""


class DjangoBrokerPortfolioAccountBindingClock:
    """Django timezone-backed production clock."""

    def now(self) -> datetime:
        """Return the current timezone-aware server timestamp."""

        return cast(datetime, timezone.now())


class DjangoBrokerPortfolioAccountBindingRepository:
    """Private first-winner ledger with closed-world inactive PIT restore."""

    __slots__ = ("_clock", "_using")

    def __init__(
        self,
        *,
        using: str = "default",
        clock: BrokerPortfolioAccountBindingClock | None = None,
    ) -> None:
        self._using = using
        self._clock = clock or DjangoBrokerPortfolioAccountBindingClock()

    @contextmanager
    def atomic(self) -> Iterator[None]:
        """Open this ledger's independent private append transaction."""

        token = object()
        with (
            transaction.atomic(using=self._using),
            _activate_portfolio_broker_binding_uow(token),
        ):
            yield

    def now(self) -> datetime:
        """Return the validated authoritative Broker clock."""

        value = self._clock.now()
        _require_aware(value, "Broker binding clock")
        return value

    def append(
        self,
        binding: BrokerPortfolioAccountNamespaceBinding,
        *,
        expected_predecessor_hash: str | None,
        recorded_at: datetime,
    ) -> BrokerPortfolioAccountNamespaceBinding:
        """CAS-append or return the exact binding first winner."""

        token = _active_token()
        value = _require_binding(binding)
        _require_aware(recorded_at, "recorded_at")
        if recorded_at > self.now():
            raise BrokerPortfolioAccountBindingUnavailable(
                "future binding persistence clock is forbidden"
            )
        if recorded_at != value.recorded_at:
            raise BrokerPortfolioAccountBindingConflict(
                "persisted_at and binding recorded_at must be identical"
            )
        if expected_predecessor_hash != value.supersedes_binding_hash:
            raise BrokerPortfolioAccountBindingConflict(
                "binding does not bind the expected predecessor"
            )
        if not value.is_knowable_at(recorded_at):
            raise BrokerPortfolioAccountBindingConflict(
                "binding must be persisted inside its validity window"
            )
        existing = self._exact_model(value)
        if existing is not None:
            return self._restore(existing)
        current = self._current_head(
            broker_account_namespace=value.broker_account_namespace,
            broker_account_id=value.broker_account_id,
            as_of=recorded_at,
            lock=True,
        )
        actual_predecessor = current.content_hash if current is not None else None
        if actual_predecessor != expected_predecessor_hash:
            raise BrokerPortfolioAccountBindingConflict("binding predecessor CAS conflict")
        if current is not None:
            try:
                validate_broker_portfolio_account_binding_successor(current, value)
            except (TypeError, ValueError) as error:
                raise BrokerPortfolioAccountBindingConflict(
                    "binding successor is invalid"
                ) from error
        values = _model_values(value, recorded_at=recorded_at)
        model = BrokerPortfolioAccountBindingModel(**values)
        try:
            with transaction.atomic(using=self._using):
                with _claim_portfolio_broker_binding_insert(
                    token=token,
                    model_type=BrokerPortfolioAccountBindingModel,
                    expected_values=values,
                ):
                    model.save(force_insert=True, using=self._using)
        except IntegrityError:
            winner = self._exact_model(value)
            if winner is None:
                raise BrokerPortfolioAccountBindingConflict(
                    "binding append conflicted without an exact visible first winner"
                ) from None
            return self._restore(winner)
        return self._restore(model)

    def get_binding_winner(
        self, *, binding_id: str, binding_version: str, as_of: datetime
    ) -> BrokerPortfolioAccountNamespaceBinding | None:
        """Return the immutable identity winner when knowable at the cutoff."""

        self._require_cutoff(as_of)
        values = self._visible_bindings(as_of=as_of, lock=False)
        matches = tuple(
            value
            for value in values
            if value.binding_id == binding_id and value.binding_version == binding_version
        )
        if not matches:
            return None
        if len(matches) != 1:
            raise BrokerPortfolioAccountBindingCorruption(
                "binding identity first winner is ambiguous"
            )
        return matches[0] if matches[0].is_knowable_at(as_of) else None

    def get_exact_by_hash(
        self,
        *,
        binding_id: str,
        binding_version: str,
        expected_content_hash: str,
        as_of: datetime,
    ) -> BrokerPortfolioAccountNamespaceBinding | None:
        """Return one exact inactive identity/hash/PIT binding."""

        self._require_cutoff(as_of)
        values = self._visible_bindings(as_of=as_of, lock=False)
        anchors = tuple(
            value
            for value in values
            if (
                (value.binding_id == binding_id and value.binding_version == binding_version)
                or value.content_hash == expected_content_hash
            )
        )
        if not anchors:
            return None
        matches = tuple(
            value
            for value in anchors
            if value.binding_id == binding_id
            and value.binding_version == binding_version
            and value.content_hash == expected_content_hash
        )
        if len(anchors) != 1 or len(matches) != 1:
            raise BrokerPortfolioAccountBindingCorruption(
                "binding exact identity/content anchors are ambiguous"
            )
        return matches[0] if matches[0].is_knowable_at(as_of) else None

    def get_current_head(
        self,
        *,
        broker_account_namespace: str,
        broker_account_id: int,
        as_of: datetime,
    ) -> BrokerPortfolioAccountNamespaceBinding | None:
        """Return the exact inactive PIT head without expired fallback."""

        self._require_cutoff(as_of)
        return self._current_head(
            broker_account_namespace=broker_account_namespace,
            broker_account_id=broker_account_id,
            as_of=as_of,
            lock=False,
        )

    def _current_head(
        self,
        *,
        broker_account_namespace: str,
        broker_account_id: int,
        as_of: datetime,
        lock: bool,
    ) -> BrokerPortfolioAccountNamespaceBinding | None:
        visible = self._visible_bindings(as_of=as_of, lock=lock)
        chain = tuple(
            value
            for value in visible
            if value.broker_account_namespace == broker_account_namespace
            and value.broker_account_id == broker_account_id
        )
        if not chain:
            return None
        head = _restore_full_chain(chain)
        return head if head.is_knowable_at(as_of) else None

    def _visible_bindings(
        self, *, as_of: datetime, lock: bool
    ) -> tuple[BrokerPortfolioAccountNamespaceBinding, ...]:
        """Restore the closed world before trusting mutable selector headers."""

        queryset = BrokerPortfolioAccountBindingModel._default_manager.using(self._using).all()
        if lock:
            queryset = queryset.select_for_update()
        rows = list(queryset.order_by("recorded_at", "pk"))
        restored = tuple(self._restore(row) for row in rows)
        visible = tuple(value for value in restored if value.recorded_at <= as_of)
        _validate_closed_world(visible)
        return visible

    def _require_cutoff(self, as_of: datetime) -> None:
        _require_aware(as_of, "binding as_of")
        if as_of > self.now():
            raise BrokerPortfolioAccountBindingUnavailable("future binding as_of is forbidden")

    def _exact_model(
        self, binding: BrokerPortfolioAccountNamespaceBinding
    ) -> BrokerPortfolioAccountBindingModel | None:
        rows = list(BrokerPortfolioAccountBindingModel._default_manager.using(self._using).all())
        if not rows:
            return None
        restored = tuple((row, self._restore(row)) for row in rows)
        _validate_closed_world(tuple(value for _, value in restored))
        root_claim = _root_claim_hash(binding)
        anchors = tuple(
            (row, value)
            for row, value in restored
            if (
                (
                    value.binding_id == binding.binding_id
                    and value.binding_version == binding.binding_version
                )
                or value.content_hash == binding.content_hash
                or (binding.supersedes_binding_hash is None and row.root_claim_hash == root_claim)
                or (
                    binding.supersedes_binding_hash is not None
                    and value.supersedes_binding_hash == binding.supersedes_binding_hash
                )
            )
        )
        if not anchors:
            return None
        matches = tuple(row for row, value in anchors if value == binding)
        if len(anchors) != 1 or len(matches) != 1:
            raise BrokerPortfolioAccountBindingConflict(
                "binding uniqueness or logical-chain claim has another first winner"
            )
        return cast(BrokerPortfolioAccountBindingModel, matches[0])

    def _restore(
        self, model: BrokerPortfolioAccountBindingModel
    ) -> BrokerPortfolioAccountNamespaceBinding:
        try:
            binding = decode_broker_portfolio_account_binding(model.canonical_payload)
        except BrokerPortfolioAccountBindingCodecError as error:
            raise BrokerPortfolioAccountBindingCorruption(
                "binding canonical payload cannot be restored"
            ) from error
        if _binding_headers(binding) != _model_headers(model):
            raise BrokerPortfolioAccountBindingCorruption(
                "binding headers do not match canonical payload"
            )
        if model.root_claim_hash != (
            _root_claim_hash(binding) if binding.supersedes_binding_hash is None else None
        ):
            raise BrokerPortfolioAccountBindingCorruption(
                "binding root logical-chain claim is invalid"
            )
        if model.ledger_header_hash != _ledger_header_hash(binding, recorded_at=model.recorded_at):
            raise BrokerPortfolioAccountBindingCorruption("binding ledger header seal is invalid")
        if (
            model.persisted_at.tzinfo is None
            or model.persisted_at.utcoffset() is None
            or model.persisted_at != model.recorded_at
            or model.recorded_at != binding.recorded_at
        ):
            raise BrokerPortfolioAccountBindingCorruption(
                "binding database persistence clock is invalid"
            )
        return binding


def _active_token() -> object:
    token = _ACTIVE_PORTFOLIO_BROKER_BINDING_UOW.get()
    if token is None:
        raise BrokerPortfolioAccountBindingConflict(
            "binding append requires an active private unit of work"
        )
    return token


def _require_binding(value: object) -> BrokerPortfolioAccountNamespaceBinding:
    if type(value) is not BrokerPortfolioAccountNamespaceBinding:
        raise BrokerPortfolioAccountBindingCorruption("binding type substitution")
    BrokerPortfolioAccountNamespaceBinding.__post_init__(value)
    return value


def _require_aware(value: datetime, field_name: str) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise BrokerPortfolioAccountBindingUnavailable(f"{field_name} must be timezone-aware")


def _hash_payload(payload: dict[str, object]) -> str:
    return hashlib.sha256(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode(
            "utf-8"
        )
    ).hexdigest()


def _time(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _root_claim_hash(binding: BrokerPortfolioAccountNamespaceBinding) -> str:
    return _hash_payload(
        {
            "broker_account_namespace": binding.broker_account_namespace,
            "broker_account_id": binding.broker_account_id,
        }
    )


def _ledger_header_hash(
    binding: BrokerPortfolioAccountNamespaceBinding, *, recorded_at: datetime
) -> str:
    return _hash_payload(
        {
            "canonical_payload": encode_broker_portfolio_account_binding(binding),
            "root_claim_hash": (
                _root_claim_hash(binding) if binding.supersedes_binding_hash is None else None
            ),
            "persisted_at": _time(recorded_at),
        }
    )


def _model_values(
    binding: BrokerPortfolioAccountNamespaceBinding, *, recorded_at: datetime
) -> dict[str, object]:
    actor = binding.asserted_by
    return {
        "owner": binding.owner,
        "binding_id": binding.binding_id,
        "binding_version": binding.binding_version,
        "permission": binding.permission,
        "blocker_codes": list(binding.blocker_codes),
        "identity_hash": binding.identity_hash,
        "content_hash": binding.content_hash,
        "broker_account_namespace": binding.broker_account_namespace,
        "broker_account_id": binding.broker_account_id,
        "portfolio_account_namespace": binding.portfolio_account_namespace,
        "portfolio_account_id": binding.portfolio_account_id,
        "owner_user_id": binding.owner_user_id,
        "account_type": binding.account_type,
        "source_accounts_active": binding.source_accounts_active,
        "broker_source_owner": binding.broker_source_owner,
        "broker_source_artifact_type": binding.broker_source_artifact_type,
        "broker_source_id": binding.broker_source_id,
        "broker_source_version": binding.broker_source_version,
        "broker_source_content_hash": binding.broker_source_content_hash,
        "portfolio_source_owner": binding.portfolio_source_owner,
        "portfolio_source_artifact_type": binding.portfolio_source_artifact_type,
        "portfolio_source_id": binding.portfolio_source_id,
        "portfolio_source_version": binding.portfolio_source_version,
        "portfolio_source_content_hash": binding.portfolio_source_content_hash,
        "actor_id": actor.actor_id,
        "actor_user_id": actor.user_id,
        "actor_role": actor.role,
        "actor_kind": actor.kind,
        "actor_is_staff": actor.is_staff,
        "issued_at": binding.issued_at,
        "recorded_at": recorded_at,
        "valid_until": binding.valid_until,
        "supersedes_binding_hash": binding.supersedes_binding_hash,
        "root_claim_hash": (
            _root_claim_hash(binding) if binding.supersedes_binding_hash is None else None
        ),
        "canonical_payload": encode_broker_portfolio_account_binding(binding),
        "ledger_header_hash": _ledger_header_hash(binding, recorded_at=recorded_at),
        "persisted_at": recorded_at,
    }


def _binding_headers(binding: BrokerPortfolioAccountNamespaceBinding) -> tuple[object, ...]:
    actor = binding.asserted_by
    return (
        binding.owner,
        binding.binding_id,
        binding.binding_version,
        binding.permission,
        list(binding.blocker_codes),
        binding.identity_hash,
        binding.content_hash,
        binding.broker_account_namespace,
        binding.broker_account_id,
        binding.portfolio_account_namespace,
        binding.portfolio_account_id,
        binding.owner_user_id,
        binding.account_type,
        binding.source_accounts_active,
        binding.broker_source_owner,
        binding.broker_source_artifact_type,
        binding.broker_source_id,
        binding.broker_source_version,
        binding.broker_source_content_hash,
        binding.portfolio_source_owner,
        binding.portfolio_source_artifact_type,
        binding.portfolio_source_id,
        binding.portfolio_source_version,
        binding.portfolio_source_content_hash,
        actor.actor_id,
        actor.user_id,
        actor.role,
        actor.kind,
        actor.is_staff,
        binding.issued_at,
        binding.recorded_at,
        binding.valid_until,
        binding.supersedes_binding_hash,
    )


def _model_headers(model: BrokerPortfolioAccountBindingModel) -> tuple[object, ...]:
    return (
        model.owner,
        model.binding_id,
        model.binding_version,
        model.permission,
        model.blocker_codes,
        model.identity_hash,
        model.content_hash,
        model.broker_account_namespace,
        model.broker_account_id,
        model.portfolio_account_namespace,
        model.portfolio_account_id,
        model.owner_user_id,
        model.account_type,
        model.source_accounts_active,
        model.broker_source_owner,
        model.broker_source_artifact_type,
        model.broker_source_id,
        model.broker_source_version,
        model.broker_source_content_hash,
        model.portfolio_source_owner,
        model.portfolio_source_artifact_type,
        model.portfolio_source_id,
        model.portfolio_source_version,
        model.portfolio_source_content_hash,
        model.actor_id,
        model.actor_user_id,
        model.actor_role,
        model.actor_kind,
        model.actor_is_staff,
        model.issued_at,
        model.recorded_at,
        model.valid_until,
        model.supersedes_binding_hash,
    )


def _validate_closed_world(
    values: tuple[BrokerPortfolioAccountNamespaceBinding, ...],
) -> None:
    """Validate every visible chain before any selector can hide a bad link."""

    groups: dict[tuple[str, int], list[BrokerPortfolioAccountNamespaceBinding]] = {}
    by_hash = {value.content_hash: value for value in values}
    if len(by_hash) != len(values):
        raise BrokerPortfolioAccountBindingCorruption("binding ledger has duplicate content")
    successors: set[str] = set()
    for value in values:
        groups.setdefault((value.broker_account_namespace, value.broker_account_id), []).append(
            value
        )
        predecessor_hash = value.supersedes_binding_hash
        if predecessor_hash is None:
            continue
        predecessor = by_hash.get(predecessor_hash)
        if predecessor is None:
            raise BrokerPortfolioAccountBindingCorruption(
                "binding chain predecessor is missing at cutoff"
            )
        if predecessor_hash in successors:
            raise BrokerPortfolioAccountBindingCorruption(
                "binding chain predecessor has multiple successors"
            )
        try:
            validate_broker_portfolio_account_binding_successor(predecessor, value)
        except (TypeError, ValueError) as error:
            raise BrokerPortfolioAccountBindingCorruption(
                "binding chain successor link is invalid"
            ) from error
        successors.add(predecessor_hash)
    for group in groups.values():
        _restore_full_chain(tuple(group))


def _restore_full_chain(
    values: tuple[BrokerPortfolioAccountNamespaceBinding, ...],
) -> BrokerPortfolioAccountNamespaceBinding:
    by_hash = {value.content_hash: value for value in values}
    roots = tuple(value for value in values if value.supersedes_binding_hash is None)
    if len(by_hash) != len(values) or len(roots) != 1:
        raise BrokerPortfolioAccountBindingCorruption(
            "binding chain must have unique content and exactly one root"
        )
    successors: dict[str, BrokerPortfolioAccountNamespaceBinding] = {}
    for value in values:
        predecessor_hash = value.supersedes_binding_hash
        if predecessor_hash is None:
            continue
        if predecessor_hash not in by_hash:
            raise BrokerPortfolioAccountBindingCorruption(
                "binding chain predecessor is missing at cutoff"
            )
        if predecessor_hash in successors:
            raise BrokerPortfolioAccountBindingCorruption(
                "binding chain predecessor has multiple successors"
            )
        successors[predecessor_hash] = value
    visited: set[str] = set()
    current = roots[0]
    while current.content_hash not in visited:
        visited.add(current.content_hash)
        successor = successors.get(current.content_hash)
        if successor is None:
            break
        current = successor
    if len(visited) != len(values):
        raise BrokerPortfolioAccountBindingCorruption("binding chain is disconnected or cyclic")
    return current


__all__ = [
    "BrokerPortfolioAccountBindingClock",
    "DjangoBrokerPortfolioAccountBindingClock",
    "DjangoBrokerPortfolioAccountBindingRepository",
]
