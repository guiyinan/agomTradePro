"""Append-only ledger and exact PIT reads for policy-benchmark definitions."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from typing import Protocol

from django.db import IntegrityError, transaction
from django.utils import timezone

from apps.portfolio.domain.policy_benchmark_definition import (
    PortfolioPolicyBenchmarkDefinition,
)
from apps.portfolio.infrastructure.policy_benchmark_definition_codec import (
    PolicyBenchmarkDefinitionCodecError,
    decode_policy_benchmark_definition,
    encode_policy_benchmark_definition,
)
from apps.portfolio.infrastructure.policy_benchmark_definition_models import (
    _ACTIVE_POLICY_BENCHMARK_DEFINITION_UOW,
    PortfolioPolicyBenchmarkDefinitionModel,
    _activate_policy_benchmark_definition_uow,
    _claim_policy_benchmark_definition_insert,
)


class PolicyBenchmarkDefinitionUnavailable(ValueError):
    """An exact benchmark definition is unavailable at a requested cutoff."""


class PolicyBenchmarkDefinitionConflict(ValueError):
    """An immutable definition anchor has another first winner."""


class PolicyBenchmarkDefinitionCorruption(ValueError):
    """Persisted benchmark definition data failed exact validation."""


class PolicyBenchmarkDefinitionClock(Protocol):
    """Authoritative Portfolio benchmark-definition persistence clock."""

    def now(self) -> datetime:
        """Return one timezone-aware server timestamp."""


class DjangoPolicyBenchmarkDefinitionClock:
    """Django timezone-backed production clock."""

    def now(self) -> datetime:
        """Return the current timezone-aware server timestamp."""

        return timezone.now()


class DjangoPolicyBenchmarkDefinitionRepository:
    """Private first-winner writer and strict historical exact reader."""

    __slots__ = ("_clock", "_using")

    def __init__(
        self,
        *,
        using: str = "default",
        clock: PolicyBenchmarkDefinitionClock | None = None,
    ) -> None:
        self._using = using
        self._clock = clock or DjangoPolicyBenchmarkDefinitionClock()

    @contextmanager
    def atomic(self) -> Iterator[None]:
        """Open this capability's private append transaction."""

        token = object()
        with (
            transaction.atomic(using=self._using),
            _activate_policy_benchmark_definition_uow(token),
        ):
            yield

    def now(self) -> datetime:
        """Return the validated authoritative Portfolio clock."""

        value = self._clock.now()
        if value.tzinfo is None or value.utcoffset() is None:
            raise PolicyBenchmarkDefinitionCorruption("benchmark definition clock is naive")
        return value

    def append(
        self,
        definition: PortfolioPolicyBenchmarkDefinition,
        *,
        recorded_at: datetime,
    ) -> PortfolioPolicyBenchmarkDefinition:
        """Append or return the exact identity/content first winner."""

        token = _active_token()
        _validate_definition(definition)
        if recorded_at.tzinfo is None or recorded_at.utcoffset() is None:
            raise PolicyBenchmarkDefinitionConflict("recorded_at must be timezone-aware")
        if definition.recorded_at != recorded_at:
            raise PolicyBenchmarkDefinitionConflict(
                "definition recorded_at must equal the authoritative server clock"
            )
        if recorded_at >= definition.valid_until:
            raise PolicyBenchmarkDefinitionConflict(
                "definition must be persisted within its validity window"
            )
        rows = self._all()
        existing = _exact(rows, definition)
        if existing is not None:
            return existing[0]
        values = _model_values(definition, recorded_at)
        model = PortfolioPolicyBenchmarkDefinitionModel(**values)
        try:
            with transaction.atomic(using=self._using):
                with _claim_policy_benchmark_definition_insert(
                    token=token,
                    model_type=PortfolioPolicyBenchmarkDefinitionModel,
                    expected_values=values,
                ):
                    model.save(force_insert=True, using=self._using)
        except IntegrityError:
            winner = _exact(self._all(), definition)
            if winner is None:
                raise PolicyBenchmarkDefinitionConflict(
                    "benchmark definition append conflicted without exact first winner"
                ) from None
            return winner[0]
        return self._restore(model)

    def get_exact(
        self,
        *,
        definition_id: str,
        definition_version: str,
        expected_content_hash: str,
        as_of: datetime,
    ) -> PortfolioPolicyBenchmarkDefinition | None:
        """Return one exact definition by full selector and strict PIT cutoff."""

        self._require_cutoff(as_of)
        rows = self._all()
        matches = tuple(
            value
            for value, _ in rows
            if value.definition_id == definition_id
            and value.definition_version == definition_version
            and value.content_hash == expected_content_hash
        )
        if len(matches) > 1:
            raise PolicyBenchmarkDefinitionCorruption("benchmark definition selector is ambiguous")
        if not matches:
            return None
        value = matches[0]
        return value if value.is_knowable_at(as_of) else None

    def _require_cutoff(self, as_of: datetime) -> None:
        if as_of.tzinfo is None or as_of.utcoffset() is None:
            raise PolicyBenchmarkDefinitionUnavailable("benchmark definition as_of is naive")
        if as_of > self.now():
            raise PolicyBenchmarkDefinitionUnavailable(
                "future benchmark definition as_of is forbidden"
            )

    def _all(
        self,
    ) -> tuple[
        tuple[
            PortfolioPolicyBenchmarkDefinition,
            PortfolioPolicyBenchmarkDefinitionModel,
        ],
        ...,
    ]:
        rows = tuple(
            PortfolioPolicyBenchmarkDefinitionModel._default_manager.using(self._using).all()
        )
        return tuple((self._restore(row), row) for row in rows)

    def _restore(
        self, model: PortfolioPolicyBenchmarkDefinitionModel
    ) -> PortfolioPolicyBenchmarkDefinition:
        try:
            value = decode_policy_benchmark_definition(model.canonical_payload)
        except PolicyBenchmarkDefinitionCodecError as error:
            raise PolicyBenchmarkDefinitionCorruption(
                "benchmark definition payload cannot be restored"
            ) from error
        if _definition_headers(value) != _model_headers(model):
            raise PolicyBenchmarkDefinitionCorruption(
                "benchmark definition headers do not match payload"
            )
        if (
            model.identity_hash != value.identity_hash
            or model.content_hash != value.content_hash
            or model.ledger_header_hash != _ledger_header_hash(value, model.recorded_at)
        ):
            raise PolicyBenchmarkDefinitionCorruption("benchmark definition ledger seal is invalid")
        if (
            model.persisted_at.tzinfo is None
            or model.persisted_at.utcoffset() is None
            or model.persisted_at != model.recorded_at
            or value.recorded_at != model.recorded_at
            or model.recorded_at >= value.valid_until
        ):
            raise PolicyBenchmarkDefinitionCorruption(
                "benchmark definition persistence clock is invalid"
            )
        return value


DefinitionState = tuple[PortfolioPolicyBenchmarkDefinition, PortfolioPolicyBenchmarkDefinitionModel]


def _active_token() -> object:
    token = _ACTIVE_POLICY_BENCHMARK_DEFINITION_UOW.get()
    if token is None:
        raise PolicyBenchmarkDefinitionConflict(
            "benchmark definition append requires an active private unit"
        )
    return token


def _validate_definition(value: object) -> PortfolioPolicyBenchmarkDefinition:
    if type(value) is not PortfolioPolicyBenchmarkDefinition:
        raise PolicyBenchmarkDefinitionConflict("benchmark definition type substitution")
    try:
        PortfolioPolicyBenchmarkDefinition.__post_init__(value)
    except (TypeError, ValueError) as error:
        raise PolicyBenchmarkDefinitionConflict("benchmark definition is invalid") from error
    return value


def _exact(
    rows: tuple[DefinitionState, ...], definition: PortfolioPolicyBenchmarkDefinition
) -> DefinitionState | None:
    candidates = tuple(
        item
        for item in rows
        if (
            (item[0].definition_id, item[0].definition_version)
            == (definition.definition_id, definition.definition_version)
            or item[0].identity_hash == definition.identity_hash
            or item[0].content_hash == definition.content_hash
        )
    )
    if not candidates:
        return None
    matches = tuple(item for item in candidates if item[0] == definition)
    if len(candidates) != 1 or len(matches) != 1:
        raise PolicyBenchmarkDefinitionConflict(
            "benchmark definition anchor has another first winner"
        )
    return matches[0]


def _hash(payload: dict[str, object]) -> str:
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


def _section_hash(name: str, values: object) -> str:
    return _hash({name: values})


def _ledger_header_hash(value: PortfolioPolicyBenchmarkDefinition, recorded_at: datetime) -> str:
    return _hash(
        {
            "identity_hash": value.identity_hash,
            "content_hash": value.content_hash,
            "definition_id": value.definition_id,
            "definition_version": value.definition_version,
            "recorded_at": _time(recorded_at),
            "valid_until": _time(value.valid_until),
        }
    )


def _model_values(
    value: PortfolioPolicyBenchmarkDefinition, recorded_at: datetime
) -> dict[str, object]:
    payload = encode_policy_benchmark_definition(value)
    constituents = payload["constituents"]
    refs = payload["methodology_refs"]
    blockers = payload["blocker_codes"]
    return {
        "owner": value.owner,
        "artifact_type": value.artifact_type,
        "schema": value.schema,
        "permission": value.permission,
        "definition_id": value.definition_id,
        "definition_version": value.definition_version,
        "base_currency": value.base_currency,
        "constituent_count": len(value.constituents),
        "constituents_hash": _section_hash("constituents", constituents),
        "methodology_refs_hash": _section_hash("methodology_refs", refs),
        "valuation_timezone": value.valuation_timezone,
        "valuation_cutoff": value.valuation_cutoff,
        "evaluation_window_days": value.evaluation_window_days,
        "max_price_age_seconds": value.max_price_age_seconds,
        "max_fx_age_seconds": value.max_fx_age_seconds,
        "missing_price_policy": value.missing_price_policy,
        "missing_fx_policy": value.missing_fx_policy,
        "blocker_codes_hash": _section_hash("blocker_codes", blockers),
        "recorded_at": recorded_at,
        "valid_until": value.valid_until,
        "persisted_at": recorded_at,
        "canonical_payload": payload,
        "identity_hash": value.identity_hash,
        "content_hash": value.content_hash,
        "ledger_header_hash": _ledger_header_hash(value, recorded_at),
    }


def _definition_headers(value: PortfolioPolicyBenchmarkDefinition) -> tuple[object, ...]:
    payload = encode_policy_benchmark_definition(value)
    return (
        value.owner,
        value.artifact_type,
        value.schema,
        value.permission,
        value.definition_id,
        value.definition_version,
        value.base_currency,
        len(value.constituents),
        _section_hash("constituents", payload["constituents"]),
        _section_hash("methodology_refs", payload["methodology_refs"]),
        value.valuation_timezone,
        value.valuation_cutoff,
        value.evaluation_window_days,
        value.max_price_age_seconds,
        value.max_fx_age_seconds,
        value.missing_price_policy,
        value.missing_fx_policy,
        _section_hash("blocker_codes", payload["blocker_codes"]),
        value.recorded_at,
        value.valid_until,
        value.identity_hash,
        value.content_hash,
    )


def _model_headers(model: PortfolioPolicyBenchmarkDefinitionModel) -> tuple[object, ...]:
    return (
        model.owner,
        model.artifact_type,
        model.schema,
        model.permission,
        model.definition_id,
        model.definition_version,
        model.base_currency,
        model.constituent_count,
        model.constituents_hash,
        model.methodology_refs_hash,
        model.valuation_timezone,
        model.valuation_cutoff,
        model.evaluation_window_days,
        model.max_price_age_seconds,
        model.max_fx_age_seconds,
        model.missing_price_policy,
        model.missing_fx_policy,
        model.blocker_codes_hash,
        model.recorded_at,
        model.valid_until,
        model.identity_hash,
        model.content_hash,
    )


__all__ = [
    "DjangoPolicyBenchmarkDefinitionClock",
    "DjangoPolicyBenchmarkDefinitionRepository",
    "PolicyBenchmarkDefinitionClock",
    "PolicyBenchmarkDefinitionConflict",
    "PolicyBenchmarkDefinitionCorruption",
    "PolicyBenchmarkDefinitionUnavailable",
]
