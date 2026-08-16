"""Append-only persistence and exact PIT reads for Plan-to-Order bindings."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from typing import Protocol

from django.db import IntegrityError, transaction
from django.utils import timezone

from apps.broker_execution.application.plan_order_binding import (
    BrokerPlanOrderBindingConflict,
    BrokerPlanOrderBindingCorruption,
    BrokerPlanOrderBindingUnavailable,
)
from apps.broker_execution.domain.plan_order_binding import (
    BrokerPlanOrderBinding,
    canonical_plan_order_payload_hash_v1,
    validate_plan_order_binding_successor,
)
from apps.broker_execution.infrastructure.plan_order_binding_codec import (
    BrokerPlanOrderBindingCodecError,
    decode_broker_plan_order_binding,
    encode_broker_plan_order_binding,
)
from apps.broker_execution.infrastructure.plan_order_binding_models import (
    _ACTIVE_PLAN_ORDER_BINDING_UOW,
    BrokerPlanOrderBindingModel,
    _activate_plan_order_binding_uow,
    _claim_plan_order_binding_insert,
)


class BrokerPlanOrderBindingClock(Protocol):
    """Authoritative Broker persistence clock."""

    def now(self) -> datetime:
        """Return one timezone-aware server timestamp."""


class DjangoBrokerPlanOrderBindingClock:
    """Django timezone-backed production clock."""

    def now(self) -> datetime:
        """Return the current timezone-aware server timestamp."""

        return timezone.now()


class DjangoBrokerPlanOrderBindingRepository:
    """Private first-winner ledger with closed-world inactive PIT restore."""

    __slots__ = ("_clock", "_using")

    def __init__(
        self,
        *,
        using: str = "default",
        clock: BrokerPlanOrderBindingClock | None = None,
    ) -> None:
        self._using = using
        self._clock = clock or DjangoBrokerPlanOrderBindingClock()

    @contextmanager
    def atomic(self) -> Iterator[None]:
        """Open this ledger's independent private append transaction."""

        token = object()
        with transaction.atomic(using=self._using), _activate_plan_order_binding_uow(token):
            yield

    def now(self) -> datetime:
        """Return the validated authoritative Broker clock."""

        value = self._clock.now()
        _require_aware(value, "Broker Plan-to-Order clock")
        return value

    def append(
        self,
        binding: BrokerPlanOrderBinding,
        *,
        expected_predecessor_hash: str | None,
        recorded_at: datetime,
    ) -> BrokerPlanOrderBinding:
        """CAS-append or return the exact binding first winner."""

        token = _active_token()
        value = _require_binding(binding)
        _require_aware(recorded_at, "recorded_at")
        if recorded_at > self.now():
            raise BrokerPlanOrderBindingUnavailable(
                "future Plan-to-Order persistence clock is forbidden"
            )
        if recorded_at != value.recorded_at:
            raise BrokerPlanOrderBindingConflict(
                "persisted_at and binding recorded_at must be identical"
            )
        if expected_predecessor_hash != value.supersedes_binding_hash:
            raise BrokerPlanOrderBindingConflict("binding does not bind the expected predecessor")
        if not value.is_knowable_at(recorded_at):
            raise BrokerPlanOrderBindingConflict(
                "binding must be persisted inside its validity window"
            )
        existing = self._exact_model(value)
        if existing is not None:
            return self._restore(existing)
        current = self._current_head(value, as_of=recorded_at, lock=True)
        actual_predecessor = current.content_hash if current is not None else None
        if actual_predecessor != expected_predecessor_hash:
            raise BrokerPlanOrderBindingConflict("Plan-to-Order predecessor CAS conflict")
        if current is not None:
            try:
                validate_plan_order_binding_successor(current, value)
            except (TypeError, ValueError) as error:
                raise BrokerPlanOrderBindingConflict(
                    "Plan-to-Order successor is invalid"
                ) from error
        values = _model_values(value, recorded_at=recorded_at)
        model = BrokerPlanOrderBindingModel(**values)
        try:
            with transaction.atomic(using=self._using):
                with _claim_plan_order_binding_insert(
                    token=token,
                    model_type=BrokerPlanOrderBindingModel,
                    expected_values=values,
                ):
                    model.save(force_insert=True, using=self._using)
        except IntegrityError:
            winner = self._exact_model(value)
            if winner is None:
                raise BrokerPlanOrderBindingConflict(
                    "binding append conflicted without an exact visible first winner"
                ) from None
            return self._restore(winner)
        return self._restore(model)

    def get_binding_winner(
        self, *, binding_id: str, binding_version: str, as_of: datetime
    ) -> BrokerPlanOrderBinding | None:
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
            raise BrokerPlanOrderBindingCorruption(
                "Plan-to-Order identity first winner is ambiguous"
            )
        return matches[0] if matches[0].is_knowable_at(as_of) else None

    def get_exact_by_hash(
        self,
        *,
        binding_id: str,
        binding_version: str,
        expected_content_hash: str,
        as_of: datetime,
    ) -> BrokerPlanOrderBinding | None:
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
            raise BrokerPlanOrderBindingCorruption(
                "Plan-to-Order exact identity/content anchors are ambiguous"
            )
        return matches[0] if matches[0].is_knowable_at(as_of) else None

    def get_current_head(
        self,
        *,
        plan_id: str,
        plan_version: int,
        plan_order_ordinal: int,
        order_artifact_id: str,
        as_of: datetime,
    ) -> BrokerPlanOrderBinding | None:
        """Return the exact inactive PIT head without expired fallback."""

        self._require_cutoff(as_of)
        selector = (plan_id, plan_version, plan_order_ordinal, order_artifact_id)
        visible = self._visible_bindings(as_of=as_of, lock=False)
        chain = tuple(value for value in visible if _subject(value) == selector)
        if not chain:
            return None
        head = _restore_full_chain(chain)
        return head if head.is_knowable_at(as_of) else None

    def _current_head(
        self, binding: BrokerPlanOrderBinding, *, as_of: datetime, lock: bool
    ) -> BrokerPlanOrderBinding | None:
        visible = self._visible_bindings(as_of=as_of, lock=lock)
        chain = tuple(value for value in visible if _subject(value) == _subject(binding))
        if not chain:
            return None
        head = _restore_full_chain(chain)
        return head if head.is_knowable_at(as_of) else None

    def _visible_bindings(
        self, *, as_of: datetime, lock: bool
    ) -> tuple[BrokerPlanOrderBinding, ...]:
        """Restore the closed world before trusting mutable selector headers."""

        queryset = BrokerPlanOrderBindingModel._default_manager.using(self._using).all()
        if lock:
            queryset = queryset.select_for_update()
        restored = tuple(self._restore(row) for row in queryset.order_by("recorded_at", "pk"))
        visible = tuple(value for value in restored if value.recorded_at <= as_of)
        _validate_closed_world(visible)
        return visible

    def _require_cutoff(self, as_of: datetime) -> None:
        _require_aware(as_of, "Plan-to-Order as_of")
        if as_of > self.now():
            raise BrokerPlanOrderBindingUnavailable("future Plan-to-Order as_of is forbidden")

    def _exact_model(self, binding: BrokerPlanOrderBinding) -> BrokerPlanOrderBindingModel | None:
        rows = list(BrokerPlanOrderBindingModel._default_manager.using(self._using).all())
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
            raise BrokerPlanOrderBindingConflict(
                "binding uniqueness or logical subject claim has another first winner"
            )
        return matches[0]

    def _restore(self, model: BrokerPlanOrderBindingModel) -> BrokerPlanOrderBinding:
        try:
            binding = decode_broker_plan_order_binding(model.canonical_payload)
        except BrokerPlanOrderBindingCodecError as error:
            raise BrokerPlanOrderBindingCorruption(
                "Plan-to-Order canonical payload cannot be restored"
            ) from error
        if _binding_headers(binding) != _model_headers(model):
            raise BrokerPlanOrderBindingCorruption(
                "Plan-to-Order headers do not match canonical payload"
            )
        expected_row_hash = canonical_plan_order_payload_hash_v1(model.plan_order_payload_json)
        if (
            model.canonical_row_byte_hash != expected_row_hash
            or model.plan_order_content_hash != expected_row_hash
        ):
            raise BrokerPlanOrderBindingCorruption(
                "canonical-v1 Plan order row byte seal is invalid"
            )
        expected_root = (
            _root_claim_hash(binding) if binding.supersedes_binding_hash is None else None
        )
        if model.root_claim_hash != expected_root:
            raise BrokerPlanOrderBindingCorruption("logical subject root claim is invalid")
        if model.ledger_header_hash != _ledger_header_hash(binding, recorded_at=model.recorded_at):
            raise BrokerPlanOrderBindingCorruption("ledger header seal is invalid")
        if (
            model.persisted_at.tzinfo is None
            or model.persisted_at.utcoffset() is None
            or model.persisted_at != model.recorded_at
            or model.recorded_at != binding.recorded_at
        ):
            raise BrokerPlanOrderBindingCorruption("database persistence clock is invalid")
        return binding


def _active_token() -> object:
    token = _ACTIVE_PLAN_ORDER_BINDING_UOW.get()
    if token is None:
        raise BrokerPlanOrderBindingConflict(
            "Plan-to-Order append requires an active private unit of work"
        )
    return token


def _require_binding(value: object) -> BrokerPlanOrderBinding:
    if type(value) is not BrokerPlanOrderBinding:
        raise BrokerPlanOrderBindingCorruption("binding type substitution")
    try:
        BrokerPlanOrderBinding.__post_init__(value)
    except (TypeError, ValueError) as error:
        raise BrokerPlanOrderBindingCorruption("binding is invalid") from error
    return value


def _require_aware(value: datetime, field_name: str) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise BrokerPlanOrderBindingUnavailable(f"{field_name} must be timezone-aware")


def _hash_payload(payload: dict[str, object]) -> str:
    return hashlib.sha256(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode(
            "utf-8"
        )
    ).hexdigest()


def _time(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _subject(binding: BrokerPlanOrderBinding) -> tuple[str, int, int, str]:
    return (
        binding.portfolio_plan_id,
        binding.portfolio_plan_version,
        binding.plan_order_ordinal,
        binding.order_artifact_id,
    )


def _root_claim_hash(binding: BrokerPlanOrderBinding) -> str:
    return _hash_payload(
        {
            "portfolio_plan_id": binding.portfolio_plan_id,
            "portfolio_plan_version": binding.portfolio_plan_version,
            "plan_order_ordinal": binding.plan_order_ordinal,
            "order_artifact_id": binding.order_artifact_id,
        }
    )


def _ledger_header_hash(binding: BrokerPlanOrderBinding, *, recorded_at: datetime) -> str:
    return _hash_payload(
        {
            "canonical_payload": encode_broker_plan_order_binding(binding),
            "canonical_row_bytes": binding.plan_order_payload_json,
            "canonical_row_byte_hash": binding.plan_order_content_hash,
            "root_claim_hash": (
                _root_claim_hash(binding) if binding.supersedes_binding_hash is None else None
            ),
            "persisted_at": _time(recorded_at),
        }
    )


def _model_values(binding: BrokerPlanOrderBinding, *, recorded_at: datetime) -> dict[str, object]:
    return {
        name: value
        for name, value in (
            ("owner", binding.owner),
            ("artifact_type", binding.artifact_type),
            ("schema", binding.schema),
            ("permission", binding.permission),
            ("blocker_codes", list(binding.blocker_codes)),
            ("binding_id", binding.binding_id),
            ("binding_version", binding.binding_version),
            ("identity_hash", binding.identity_hash),
            ("content_hash", binding.content_hash),
            ("portfolio_plan_owner", binding.portfolio_plan_owner),
            ("portfolio_plan_artifact_type", binding.portfolio_plan_artifact_type),
            ("portfolio_plan_id", binding.portfolio_plan_id),
            ("portfolio_plan_version", binding.portfolio_plan_version),
            ("portfolio_plan_content_hash", binding.portfolio_plan_content_hash),
            ("portfolio_plan_valid_until", binding.portfolio_plan_valid_until),
            ("portfolio_account_id", binding.portfolio_account_id),
            ("portfolio_receipt_owner", binding.portfolio_receipt_owner),
            ("portfolio_receipt_capability", binding.portfolio_receipt_capability),
            ("portfolio_receipt_id", binding.portfolio_receipt_id),
            ("portfolio_receipt_version", binding.portfolio_receipt_version),
            ("portfolio_receipt_content_hash", binding.portfolio_receipt_content_hash),
            ("portfolio_receipt_valid_until", binding.portfolio_receipt_valid_until),
            ("portfolio_subject_id", binding.portfolio_subject_id),
            ("portfolio_subject_version", binding.portfolio_subject_version),
            ("portfolio_subject_content_hash", binding.portfolio_subject_content_hash),
            ("plan_order_ordinal", binding.plan_order_ordinal),
            ("plan_order_payload_json", binding.plan_order_payload_json),
            ("plan_order_content_hash", binding.plan_order_content_hash),
            ("broker_account_id", binding.broker_account_id),
            ("order_artifact_owner", binding.order_artifact_owner),
            ("order_artifact_type", binding.order_artifact_type),
            ("order_artifact_id", binding.order_artifact_id),
            ("order_artifact_version", binding.order_artifact_version),
            ("order_artifact_identity_hash", binding.order_artifact_identity_hash),
            ("order_artifact_content_hash", binding.order_artifact_content_hash),
            ("order_artifact_valid_until", binding.order_artifact_valid_until),
            ("order_approval_digest", binding.order_approval_digest),
            ("order_version", binding.order_version),
            ("recorded_at", recorded_at),
            ("valid_until", binding.valid_until),
            ("supersedes_binding_hash", binding.supersedes_binding_hash),
            (
                "root_claim_hash",
                _root_claim_hash(binding) if binding.supersedes_binding_hash is None else None,
            ),
            ("canonical_payload", encode_broker_plan_order_binding(binding)),
            ("canonical_row_byte_hash", binding.plan_order_content_hash),
            ("ledger_header_hash", _ledger_header_hash(binding, recorded_at=recorded_at)),
            ("persisted_at", recorded_at),
        )
    }


_HEADER_FIELDS = (
    "owner",
    "artifact_type",
    "schema",
    "permission",
    "blocker_codes",
    "binding_id",
    "binding_version",
    "identity_hash",
    "content_hash",
    "portfolio_plan_owner",
    "portfolio_plan_artifact_type",
    "portfolio_plan_id",
    "portfolio_plan_version",
    "portfolio_plan_content_hash",
    "portfolio_plan_valid_until",
    "portfolio_account_id",
    "portfolio_receipt_owner",
    "portfolio_receipt_capability",
    "portfolio_receipt_id",
    "portfolio_receipt_version",
    "portfolio_receipt_content_hash",
    "portfolio_receipt_valid_until",
    "portfolio_subject_id",
    "portfolio_subject_version",
    "portfolio_subject_content_hash",
    "plan_order_ordinal",
    "plan_order_payload_json",
    "plan_order_content_hash",
    "broker_account_id",
    "order_artifact_owner",
    "order_artifact_type",
    "order_artifact_id",
    "order_artifact_version",
    "order_artifact_identity_hash",
    "order_artifact_content_hash",
    "order_artifact_valid_until",
    "order_approval_digest",
    "order_version",
    "recorded_at",
    "valid_until",
    "supersedes_binding_hash",
)


def _binding_headers(binding: BrokerPlanOrderBinding) -> tuple[object, ...]:
    payload = _model_values(binding, recorded_at=binding.recorded_at)
    return tuple(payload[field] for field in _HEADER_FIELDS)


def _model_headers(model: BrokerPlanOrderBindingModel) -> tuple[object, ...]:
    values: list[object] = []
    for field in _HEADER_FIELDS:
        value = getattr(model, field)
        if field == "order_artifact_id":
            value = str(value)
        values.append(value)
    return tuple(values)


def _validate_closed_world(values: tuple[BrokerPlanOrderBinding, ...]) -> None:
    """Validate every visible chain before any selector can hide a bad link."""

    by_hash = {value.content_hash: value for value in values}
    if len(by_hash) != len(values):
        raise BrokerPlanOrderBindingCorruption("binding ledger has duplicate content")
    groups: dict[tuple[str, int, int, str], list[BrokerPlanOrderBinding]] = {}
    successors: set[str] = set()
    for value in values:
        groups.setdefault(_subject(value), []).append(value)
        predecessor_hash = value.supersedes_binding_hash
        if predecessor_hash is None:
            continue
        predecessor = by_hash.get(predecessor_hash)
        if predecessor is None:
            raise BrokerPlanOrderBindingCorruption("binding chain predecessor is missing at cutoff")
        if predecessor_hash in successors:
            raise BrokerPlanOrderBindingCorruption(
                "binding chain predecessor has multiple successors"
            )
        try:
            validate_plan_order_binding_successor(predecessor, value)
        except (TypeError, ValueError) as error:
            raise BrokerPlanOrderBindingCorruption(
                "binding chain successor link is invalid"
            ) from error
        successors.add(predecessor_hash)
    for group in groups.values():
        _restore_full_chain(tuple(group))


def _restore_full_chain(
    values: tuple[BrokerPlanOrderBinding, ...],
) -> BrokerPlanOrderBinding:
    by_hash = {value.content_hash: value for value in values}
    roots = tuple(value for value in values if value.supersedes_binding_hash is None)
    if len(by_hash) != len(values) or len(roots) != 1:
        raise BrokerPlanOrderBindingCorruption(
            "binding chain must have unique content and exactly one root"
        )
    successors: dict[str, BrokerPlanOrderBinding] = {}
    for value in values:
        predecessor_hash = value.supersedes_binding_hash
        if predecessor_hash is None:
            continue
        if predecessor_hash not in by_hash:
            raise BrokerPlanOrderBindingCorruption("binding chain predecessor is missing at cutoff")
        if predecessor_hash in successors:
            raise BrokerPlanOrderBindingCorruption(
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
        raise BrokerPlanOrderBindingCorruption("binding chain is disconnected or cyclic")
    return current


__all__ = [
    "BrokerPlanOrderBindingClock",
    "DjangoBrokerPlanOrderBindingClock",
    "DjangoBrokerPlanOrderBindingRepository",
]
