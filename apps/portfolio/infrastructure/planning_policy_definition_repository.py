"""Append-only ledger and exact PIT reads for planning-policy definitions."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from decimal import Decimal
from typing import Protocol, cast

from django.db import IntegrityError, transaction
from django.utils import timezone

from apps.portfolio.domain.planning_policy_definition import PlanningPolicyDefinition
from apps.portfolio.infrastructure.planning_policy_definition_codec import (
    PlanningPolicyDefinitionCodecError,
    decode_planning_policy_definition,
    encode_planning_policy_definition,
)
from apps.portfolio.infrastructure.planning_policy_definition_models import (
    _ACTIVE_PLANNING_POLICY_DEFINITION_UOW,
    PortfolioPlanningPolicyDefinitionModel,
    _activate_planning_policy_definition_uow,
    _claim_planning_policy_definition_insert,
)


class PlanningPolicyDefinitionUnavailable(ValueError):
    """An exact definition is unavailable at a requested cutoff."""


class PlanningPolicyDefinitionConflict(ValueError):
    """An immutable identity or content anchor has another first winner."""


class PlanningPolicyDefinitionCorruption(ValueError):
    """Persisted planning-policy definition data failed exact validation."""


class PlanningPolicyDefinitionClock(Protocol):
    """Authoritative Portfolio definition persistence clock."""

    def now(self) -> datetime:
        """Return one timezone-aware server timestamp."""


class DjangoPlanningPolicyDefinitionClock:
    """Django timezone-backed production clock."""

    def now(self) -> datetime:
        """Return the current timezone-aware server timestamp."""

        return cast(datetime, timezone.now())


class DjangoPlanningPolicyDefinitionRepository:
    """Private first-winner writer and strict historical exact reader."""

    __slots__ = ("_clock", "_using")

    def __init__(
        self,
        *,
        using: str = "default",
        clock: PlanningPolicyDefinitionClock | None = None,
    ) -> None:
        self._using = using
        self._clock = clock or DjangoPlanningPolicyDefinitionClock()

    @contextmanager
    def atomic(self) -> Iterator[None]:
        """Open this capability's private append transaction."""

        token = object()
        with (
            transaction.atomic(using=self._using),
            _activate_planning_policy_definition_uow(token),
        ):
            yield

    def now(self) -> datetime:
        """Return the validated authoritative Portfolio clock."""

        value = self._clock.now()
        if value.tzinfo is None or value.utcoffset() is None:
            raise PlanningPolicyDefinitionCorruption("Portfolio definition clock is naive")
        return value

    def append(
        self, definition: PlanningPolicyDefinition, *, recorded_at: datetime
    ) -> PlanningPolicyDefinition:
        """Append or return the exact identity/content first winner."""

        token = _active_token()
        if type(definition) is not PlanningPolicyDefinition:
            raise PlanningPolicyDefinitionConflict("definition type substitution")
        PlanningPolicyDefinition.__post_init__(definition)
        if recorded_at.tzinfo is None or recorded_at.utcoffset() is None:
            raise PlanningPolicyDefinitionConflict("recorded_at must be timezone-aware")
        if definition.recorded_at != recorded_at:
            raise PlanningPolicyDefinitionConflict(
                "definition recorded_at must equal the authoritative server clock"
            )
        if recorded_at >= definition.valid_until:
            raise PlanningPolicyDefinitionConflict(
                "definition must be persisted within its validity window"
            )
        existing = self._exact_model(definition)
        if existing is not None:
            return self._restore(existing)
        values = _model_values(definition, recorded_at=recorded_at)
        model = PortfolioPlanningPolicyDefinitionModel(**values)
        try:
            with transaction.atomic(using=self._using):
                with _claim_planning_policy_definition_insert(
                    token=token,
                    model_type=PortfolioPlanningPolicyDefinitionModel,
                    expected_values=values,
                ):
                    model.save(force_insert=True, using=self._using)
        except IntegrityError:
            winner = self._exact_model(definition)
            if winner is None:
                raise PlanningPolicyDefinitionConflict(
                    "definition append conflicted without an exact visible first winner"
                ) from None
            return self._restore(winner)
        return self._restore(model)

    def get_exact(
        self,
        *,
        policy_id: str,
        policy_version: str,
        expected_content_hash: str,
        as_of: datetime,
    ) -> PlanningPolicyDefinition | None:
        """Return one exact historical definition by identity, hash, and PIT cutoff."""

        self._require_cutoff(as_of)
        rows = list(
            PortfolioPlanningPolicyDefinitionModel._default_manager.using(self._using).all()
        )
        if not rows:
            return None
        values = tuple(self._restore(row) for row in rows)
        matches = tuple(
            value
            for value in values
            if value.policy_id == policy_id
            and value.policy_version == policy_version
            and value.content_hash == expected_content_hash
        )
        if len(matches) != 1:
            if not matches:
                return None
            raise PlanningPolicyDefinitionCorruption(
                "exact definition identity/content anchors are ambiguous"
            )
        value = matches[0]
        if not value.recorded_at <= as_of < value.valid_until:
            return None
        return value

    def _require_cutoff(self, as_of: datetime) -> None:
        if as_of.tzinfo is None or as_of.utcoffset() is None:
            raise PlanningPolicyDefinitionUnavailable("definition as_of is naive")
        if as_of > self.now():
            raise PlanningPolicyDefinitionUnavailable("future definition as_of is forbidden")

    def _exact_model(
        self, definition: PlanningPolicyDefinition
    ) -> PortfolioPlanningPolicyDefinitionModel | None:
        rows = list(
            PortfolioPlanningPolicyDefinitionModel._default_manager.using(self._using).all()
        )
        if not rows:
            return None
        restored = tuple((self._restore(row), row) for row in rows)
        candidates = tuple(
            (value, row)
            for value, row in restored
            if (
                (value.policy_id, value.policy_version)
                == (definition.policy_id, definition.policy_version)
                or value.identity_hash == definition.identity_hash
                or value.content_hash == definition.content_hash
            )
        )
        if not candidates:
            return None
        matches = tuple(row for value, row in candidates if value == definition)
        if len(candidates) != 1 or len(matches) != 1:
            raise PlanningPolicyDefinitionConflict(
                "planning-policy definition anchor has another first winner"
            )
        return cast(PortfolioPlanningPolicyDefinitionModel, matches[0])

    def _restore(self, model: PortfolioPlanningPolicyDefinitionModel) -> PlanningPolicyDefinition:
        try:
            value = decode_planning_policy_definition(model.canonical_payload)
        except PlanningPolicyDefinitionCodecError as error:
            raise PlanningPolicyDefinitionCorruption(
                "definition canonical payload cannot be restored"
            ) from error
        if _definition_headers(value) != _model_headers(model):
            raise PlanningPolicyDefinitionCorruption(
                "definition headers do not match canonical payload"
            )
        if (
            model.identity_hash != value.identity_hash
            or model.content_hash != value.content_hash
            or model.ledger_header_hash != _ledger_header_hash(value, model.recorded_at)
        ):
            raise PlanningPolicyDefinitionCorruption("definition ledger seal is invalid")
        if (
            model.persisted_at.tzinfo is None
            or model.persisted_at.utcoffset() is None
            or model.persisted_at != model.recorded_at
            or value.recorded_at != model.recorded_at
            or model.recorded_at >= value.valid_until
        ):
            raise PlanningPolicyDefinitionCorruption(
                "definition database persistence clock is invalid"
            )
        return value


def _active_token() -> object:
    token = _ACTIVE_PLANNING_POLICY_DEFINITION_UOW.get()
    if token is None:
        raise PlanningPolicyDefinitionConflict("definition append requires an active private unit")
    return token


def _hash_payload(payload: dict[str, object]) -> str:
    return hashlib.sha256(
        json.dumps(
            payload,
            allow_nan=False,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()


def _time(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _ledger_header_hash(definition: PlanningPolicyDefinition, recorded_at: datetime) -> str:
    return _hash_payload(
        {
            "identity_hash": definition.identity_hash,
            "content_hash": definition.content_hash,
            "policy_id": definition.policy_id,
            "policy_version": definition.policy_version,
            "recorded_at": _time(recorded_at),
            "valid_until": _time(definition.valid_until),
        }
    )


def _model_values(
    definition: PlanningPolicyDefinition, *, recorded_at: datetime
) -> dict[str, object]:
    return {
        "owner": definition.owner,
        "artifact_type": definition.artifact_type,
        "schema": definition.schema,
        "permission": definition.permission,
        "policy_id": definition.policy_id,
        "policy_version": definition.policy_version,
        "buy_lot_size": definition.buy_lot_size,
        "fee_rate": _decimal_text(definition.fee_rate),
        "slippage_rate": _decimal_text(definition.slippage_rate),
        "min_rebalance_value": _decimal_text(definition.min_rebalance_value),
        "max_asset_weight": _decimal_text(definition.max_asset_weight),
        "max_volume_participation": _decimal_text(definition.max_volume_participation),
        "valid_until": definition.valid_until,
        "recorded_at": recorded_at,
        "persisted_at": recorded_at,
        "canonical_payload": encode_planning_policy_definition(definition),
        "identity_hash": definition.identity_hash,
        "content_hash": definition.content_hash,
        "ledger_header_hash": _ledger_header_hash(definition, recorded_at),
    }


def _definition_headers(definition: PlanningPolicyDefinition) -> tuple[object, ...]:
    return (
        definition.owner,
        definition.artifact_type,
        definition.schema,
        definition.permission,
        definition.policy_id,
        definition.policy_version,
        definition.buy_lot_size,
        _decimal_text(definition.fee_rate),
        _decimal_text(definition.slippage_rate),
        _decimal_text(definition.min_rebalance_value),
        _decimal_text(definition.max_asset_weight),
        _decimal_text(definition.max_volume_participation),
        definition.valid_until,
        definition.recorded_at,
        definition.identity_hash,
        definition.content_hash,
    )


def _decimal_text(value: Decimal) -> str:
    text = format(value, "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return text or "0"


def _model_headers(
    model: PortfolioPlanningPolicyDefinitionModel,
) -> tuple[object, ...]:
    return (
        model.owner,
        model.artifact_type,
        model.schema,
        model.permission,
        model.policy_id,
        model.policy_version,
        model.buy_lot_size,
        model.fee_rate,
        model.slippage_rate,
        model.min_rebalance_value,
        model.max_asset_weight,
        model.max_volume_participation,
        model.valid_until,
        model.recorded_at,
        model.identity_hash,
        model.content_hash,
    )


__all__ = [
    "DjangoPlanningPolicyDefinitionClock",
    "DjangoPlanningPolicyDefinitionRepository",
    "PlanningPolicyDefinitionClock",
    "PlanningPolicyDefinitionConflict",
    "PlanningPolicyDefinitionCorruption",
    "PlanningPolicyDefinitionUnavailable",
]
