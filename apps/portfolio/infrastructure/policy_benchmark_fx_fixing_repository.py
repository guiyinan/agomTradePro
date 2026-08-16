"""Append-only ledger and exact PIT reads for benchmark FX-fixing definitions."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from typing import Protocol

from django.db import IntegrityError, transaction
from django.utils import timezone

from apps.portfolio.domain.policy_benchmark_fx_fixing import PortfolioPolicyBenchmarkFxFixing
from apps.portfolio.infrastructure.policy_benchmark_fx_fixing_codec import (
    PolicyBenchmarkFxFixingCodecError,
    decode_policy_benchmark_fx_fixing,
    encode_policy_benchmark_fx_fixing,
)
from apps.portfolio.infrastructure.policy_benchmark_fx_fixing_models import (
    _ACTIVE_FX_UOW,
    PortfolioPolicyBenchmarkFxFixingModel,
    _activate_fx_uow,
    _claim_fx_insert,
)


class PolicyBenchmarkFxFixingUnavailable(ValueError):
    """Exact FX definition unavailable."""


class PolicyBenchmarkFxFixingConflict(ValueError):
    """FX definition first-winner conflict."""


class PolicyBenchmarkFxFixingCorruption(ValueError):
    """Persisted FX definition is corrupt."""


class PolicyBenchmarkFxFixingClock(Protocol):
    """Authoritative server clock."""

    def now(self) -> datetime:
        """Return aware server time."""


class DjangoPolicyBenchmarkFxFixingClock:
    """Django production clock."""

    def now(self) -> datetime:
        return timezone.now()


class DjangoPolicyBenchmarkFxFixingRepository:
    """Private first-winner writer and exact PIT reader."""

    __slots__ = ("_clock", "_using")

    def __init__(
        self, *, using: str = "default", clock: PolicyBenchmarkFxFixingClock | None = None
    ) -> None:
        self._using = using
        self._clock = clock or DjangoPolicyBenchmarkFxFixingClock()

    @contextmanager
    def atomic(self) -> Iterator[None]:
        """Open private append transaction."""
        token = object()
        with transaction.atomic(using=self._using), _activate_fx_uow(token):
            yield

    def now(self) -> datetime:
        """Return validated server clock."""
        value = self._clock.now()
        if value.tzinfo is None or value.utcoffset() is None:
            raise PolicyBenchmarkFxFixingCorruption("FX-fixing clock is naive")
        return value

    def append(
        self, value: PortfolioPolicyBenchmarkFxFixing, *, recorded_at: datetime
    ) -> PortfolioPolicyBenchmarkFxFixing:
        """Append or return the exact first winner."""
        token = _active_token()
        _validate(value)
        if recorded_at.tzinfo is None or recorded_at.utcoffset() is None:
            raise PolicyBenchmarkFxFixingConflict("recorded_at must be timezone-aware")
        if value.recorded_at != recorded_at:
            raise PolicyBenchmarkFxFixingConflict(
                "FX-fixing recorded_at must equal the server clock"
            )
        existing = _exact(self._all(), value)
        if existing is not None:
            return existing[0]
        values = _model_values(value, recorded_at)
        model = PortfolioPolicyBenchmarkFxFixingModel(**values)
        try:
            with (
                transaction.atomic(using=self._using),
                _claim_fx_insert(
                    token=token,
                    model_type=PortfolioPolicyBenchmarkFxFixingModel,
                    expected_values=values,
                ),
            ):
                model.save(force_insert=True, using=self._using)
        except IntegrityError:
            winner = _exact(self._all(), value)
            if winner is None:
                raise PolicyBenchmarkFxFixingConflict(
                    "FX-fixing append conflicted without exact winner"
                ) from None
            return winner[0]
        return self._restore(model)

    def get_exact(
        self,
        *,
        methodology_id: str,
        methodology_version: str,
        expected_content_hash: str,
        as_of: datetime,
    ) -> PortfolioPolicyBenchmarkFxFixing | None:
        """Return an exact identity/hash definition at PIT."""
        if as_of.tzinfo is None or as_of.utcoffset() is None:
            raise PolicyBenchmarkFxFixingUnavailable("FX-fixing as_of is naive")
        if as_of > self.now():
            raise PolicyBenchmarkFxFixingUnavailable("future FX-fixing as_of is forbidden")
        matches = tuple(
            value
            for value, _ in self._all()
            if value.methodology_id == methodology_id
            and value.methodology_version == methodology_version
            and value.content_hash == expected_content_hash
        )
        if len(matches) > 1:
            raise PolicyBenchmarkFxFixingCorruption("FX-fixing selector is ambiguous")
        return matches[0] if matches and matches[0].is_knowable_at(as_of) else None

    def _all(
        self,
    ) -> tuple[tuple[PortfolioPolicyBenchmarkFxFixing, PortfolioPolicyBenchmarkFxFixingModel], ...]:
        return tuple(
            (self._restore(row), row)
            for row in PortfolioPolicyBenchmarkFxFixingModel._default_manager.using(
                self._using
            ).all()
        )

    def _restore(
        self, model: PortfolioPolicyBenchmarkFxFixingModel
    ) -> PortfolioPolicyBenchmarkFxFixing:
        try:
            value = decode_policy_benchmark_fx_fixing(model.canonical_payload)
        except PolicyBenchmarkFxFixingCodecError as error:
            raise PolicyBenchmarkFxFixingCorruption(
                "FX-fixing payload cannot be restored"
            ) from error
        if _headers(value) != _model_headers(model):
            raise PolicyBenchmarkFxFixingCorruption("FX-fixing headers do not match payload")
        if model.ledger_header_hash != _ledger_hash(value, model.recorded_at):
            raise PolicyBenchmarkFxFixingCorruption("FX-fixing ledger seal is invalid")
        if (
            model.persisted_at.tzinfo is None
            or model.persisted_at.utcoffset() is None
            or model.persisted_at != model.recorded_at
            or value.recorded_at != model.recorded_at
        ):
            raise PolicyBenchmarkFxFixingCorruption("FX-fixing persistence clock is invalid")
        return value


FxState = tuple[PortfolioPolicyBenchmarkFxFixing, PortfolioPolicyBenchmarkFxFixingModel]


def _active_token() -> object:
    token = _ACTIVE_FX_UOW.get()
    if token is None:
        raise PolicyBenchmarkFxFixingConflict("FX-fixing append requires an active private unit")
    return token


def _validate(value: object) -> None:
    if type(value) is not PortfolioPolicyBenchmarkFxFixing:
        raise PolicyBenchmarkFxFixingConflict("FX-fixing type substitution")
    try:
        PortfolioPolicyBenchmarkFxFixing.__post_init__(value)
    except (TypeError, ValueError) as error:
        raise PolicyBenchmarkFxFixingConflict("FX-fixing is invalid") from error


def _exact(rows: tuple[FxState, ...], value: PortfolioPolicyBenchmarkFxFixing) -> FxState | None:
    candidates = tuple(
        item
        for item in rows
        if (item[0].methodology_id, item[0].methodology_version)
        == (value.methodology_id, value.methodology_version)
        or item[0].identity_hash == value.identity_hash
        or item[0].content_hash == value.content_hash
    )
    if not candidates:
        return None
    matches = tuple(item for item in candidates if item[0] == value)
    if len(candidates) != 1 or len(matches) != 1:
        raise PolicyBenchmarkFxFixingConflict("FX-fixing anchor has another first winner")
    return matches[0]


def _hash(payload: dict[str, object]) -> str:
    return hashlib.sha256(
        json.dumps(
            payload, allow_nan=False, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ).encode()
    ).hexdigest()


def _time(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _sources_hash(value: PortfolioPolicyBenchmarkFxFixing) -> str:
    return _hash({"source_priority": [source.to_payload() for source in value.source_priority]})


def _ledger_hash(value: PortfolioPolicyBenchmarkFxFixing, recorded_at: datetime) -> str:
    return _hash(
        {
            "identity_hash": value.identity_hash,
            "content_hash": value.content_hash,
            "sources_hash": _sources_hash(value),
            "recorded_at": _time(recorded_at),
            "valid_until": _time(value.valid_until),
        }
    )


def _model_values(
    value: PortfolioPolicyBenchmarkFxFixing, recorded_at: datetime
) -> dict[str, object]:
    payload = encode_policy_benchmark_fx_fixing(value)
    return {
        "owner": value.owner,
        "artifact_type": value.artifact_type,
        "schema": value.schema,
        "permission": value.permission,
        "methodology_id": value.methodology_id,
        "methodology_version": value.methodology_version,
        "base_currency": value.base_currency,
        "quote_currency": value.quote_currency,
        "currency_pair": value.currency_pair,
        "fixing_convention": value.fixing_convention,
        "inverse_rate_allowed": value.inverse_rate_allowed,
        "timezone_name": value.timezone,
        "valuation_cutoff_local": payload["valuation_cutoff_local"],
        "source_count": len(value.source_priority),
        "sources_hash": _sources_hash(value),
        "stale_after_seconds": value.stale_after_seconds,
        "triangulation_policy": value.triangulation_policy,
        "triangulation_currency": value.triangulation_currency,
        "source_failure_policy": value.source_failure_policy,
        "missing_fx_policy": value.missing_fx_policy,
        "recorded_at": recorded_at,
        "valid_until": value.valid_until,
        "persisted_at": recorded_at,
        "canonical_payload": payload,
        "identity_hash": value.identity_hash,
        "content_hash": value.content_hash,
        "ledger_header_hash": _ledger_hash(value, recorded_at),
    }


def _headers(value: PortfolioPolicyBenchmarkFxFixing) -> tuple[object, ...]:
    payload = encode_policy_benchmark_fx_fixing(value)
    return (
        value.owner,
        value.artifact_type,
        value.schema,
        value.permission,
        value.methodology_id,
        value.methodology_version,
        value.base_currency,
        value.quote_currency,
        value.currency_pair,
        value.fixing_convention,
        value.inverse_rate_allowed,
        value.timezone,
        payload["valuation_cutoff_local"],
        len(value.source_priority),
        _sources_hash(value),
        value.stale_after_seconds,
        value.triangulation_policy,
        value.triangulation_currency,
        value.source_failure_policy,
        value.missing_fx_policy,
        value.recorded_at,
        value.valid_until,
        value.identity_hash,
        value.content_hash,
    )


def _model_headers(model: PortfolioPolicyBenchmarkFxFixingModel) -> tuple[object, ...]:
    return (
        model.owner,
        model.artifact_type,
        model.schema,
        model.permission,
        model.methodology_id,
        model.methodology_version,
        model.base_currency,
        model.quote_currency,
        model.currency_pair,
        model.fixing_convention,
        model.inverse_rate_allowed,
        model.timezone_name,
        model.valuation_cutoff_local,
        model.source_count,
        model.sources_hash,
        model.stale_after_seconds,
        model.triangulation_policy,
        model.triangulation_currency,
        model.source_failure_policy,
        model.missing_fx_policy,
        model.recorded_at,
        model.valid_until,
        model.identity_hash,
        model.content_hash,
    )


__all__ = [
    "DjangoPolicyBenchmarkFxFixingClock",
    "DjangoPolicyBenchmarkFxFixingRepository",
    "PolicyBenchmarkFxFixingClock",
    "PolicyBenchmarkFxFixingConflict",
    "PolicyBenchmarkFxFixingCorruption",
    "PolicyBenchmarkFxFixingUnavailable",
]
