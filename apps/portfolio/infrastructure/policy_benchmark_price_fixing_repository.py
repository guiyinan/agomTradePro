"""Append-only ledger and exact PIT reads for benchmark price-fixing definitions."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from typing import Protocol, cast

from django.db import IntegrityError, transaction
from django.utils import timezone

from apps.portfolio.domain.policy_benchmark_price_fixing import PortfolioPolicyBenchmarkPriceFixing
from apps.portfolio.infrastructure.policy_benchmark_price_fixing_codec import (
    PolicyBenchmarkPriceFixingCodecError,
    decode_policy_benchmark_price_fixing,
    encode_policy_benchmark_price_fixing,
)
from apps.portfolio.infrastructure.policy_benchmark_price_fixing_models import (
    _ACTIVE_PRICE_FIXING_UOW,
    PortfolioPolicyBenchmarkPriceFixingModel,
    _activate_price_fixing_uow,
    _claim_price_fixing_insert,
)


class PolicyBenchmarkPriceFixingUnavailable(ValueError):
    """An exact definition is unavailable at the requested cutoff."""


class PolicyBenchmarkPriceFixingConflict(ValueError):
    """An immutable definition anchor has another first winner."""


class PolicyBenchmarkPriceFixingCorruption(ValueError):
    """Persisted price-fixing data failed exact validation."""


class PolicyBenchmarkPriceFixingClock(Protocol):
    """Authoritative Portfolio price-fixing persistence clock."""

    def now(self) -> datetime:
        """Return one timezone-aware server timestamp."""


class DjangoPolicyBenchmarkPriceFixingClock:
    """Django timezone-backed production clock."""

    def now(self) -> datetime:
        """Return the current timezone-aware server timestamp."""
        return cast(datetime, timezone.now())


class DjangoPolicyBenchmarkPriceFixingRepository:
    """Private first-winner writer and strict historical exact reader."""

    __slots__ = ("_clock", "_using")

    def __init__(
        self, *, using: str = "default", clock: PolicyBenchmarkPriceFixingClock | None = None
    ) -> None:
        self._using = using
        self._clock = clock or DjangoPolicyBenchmarkPriceFixingClock()

    @contextmanager
    def atomic(self) -> Iterator[None]:
        """Open this capability's private append transaction."""
        token = object()
        with transaction.atomic(using=self._using), _activate_price_fixing_uow(token):
            yield

    def now(self) -> datetime:
        """Return the validated authoritative Portfolio clock."""
        value = self._clock.now()
        if value.tzinfo is None or value.utcoffset() is None:
            raise PolicyBenchmarkPriceFixingCorruption("price-fixing clock is naive")
        return value

    def append(
        self, value: PortfolioPolicyBenchmarkPriceFixing, *, recorded_at: datetime
    ) -> PortfolioPolicyBenchmarkPriceFixing:
        """Append or return the exact identity/content first winner."""
        token = _active_token()
        _validate(value)
        if recorded_at.tzinfo is None or recorded_at.utcoffset() is None:
            raise PolicyBenchmarkPriceFixingConflict("recorded_at must be timezone-aware")
        if value.recorded_at != recorded_at:
            raise PolicyBenchmarkPriceFixingConflict(
                "price-fixing recorded_at must equal the authoritative server clock"
            )
        if recorded_at >= value.valid_until:
            raise PolicyBenchmarkPriceFixingConflict(
                "price-fixing must be persisted within its validity window"
            )
        existing = _exact(self._all(), value)
        if existing is not None:
            return existing[0]
        values = _model_values(value, recorded_at)
        model = PortfolioPolicyBenchmarkPriceFixingModel(**values)
        try:
            with (
                transaction.atomic(using=self._using),
                _claim_price_fixing_insert(
                    token=token,
                    model_type=PortfolioPolicyBenchmarkPriceFixingModel,
                    expected_values=values,
                ),
            ):
                model.save(force_insert=True, using=self._using)
        except IntegrityError:
            winner = _exact(self._all(), value)
            if winner is None:
                raise PolicyBenchmarkPriceFixingConflict(
                    "price-fixing append conflicted without exact first winner"
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
    ) -> PortfolioPolicyBenchmarkPriceFixing | None:
        """Return one exact definition by full selector at a strict PIT cutoff."""
        self._require_cutoff(as_of)
        matches = tuple(
            value
            for value, _ in self._all()
            if value.methodology_id == methodology_id
            and value.methodology_version == methodology_version
            and value.content_hash == expected_content_hash
        )
        if len(matches) > 1:
            raise PolicyBenchmarkPriceFixingCorruption("price-fixing selector is ambiguous")
        if not matches:
            return None
        return matches[0] if matches[0].is_knowable_at(as_of) else None

    def _require_cutoff(self, as_of: datetime) -> None:
        if as_of.tzinfo is None or as_of.utcoffset() is None:
            raise PolicyBenchmarkPriceFixingUnavailable("price-fixing as_of is naive")
        if as_of > self.now():
            raise PolicyBenchmarkPriceFixingUnavailable("future price-fixing as_of is forbidden")

    def _all(
        self,
    ) -> tuple[
        tuple[PortfolioPolicyBenchmarkPriceFixing, PortfolioPolicyBenchmarkPriceFixingModel], ...
    ]:
        rows = tuple(
            PortfolioPolicyBenchmarkPriceFixingModel._default_manager.using(self._using).all()
        )
        return tuple((self._restore(row), row) for row in rows)

    def _restore(
        self, model: PortfolioPolicyBenchmarkPriceFixingModel
    ) -> PortfolioPolicyBenchmarkPriceFixing:
        try:
            value = decode_policy_benchmark_price_fixing(model.canonical_payload)
        except PolicyBenchmarkPriceFixingCodecError as error:
            raise PolicyBenchmarkPriceFixingCorruption(
                "price-fixing payload cannot be restored"
            ) from error
        if _headers(value) != _model_headers(model):
            raise PolicyBenchmarkPriceFixingCorruption("price-fixing headers do not match payload")
        if (
            model.identity_hash != value.identity_hash
            or model.content_hash != value.content_hash
            or model.ledger_header_hash != _ledger_hash(value, model.recorded_at)
        ):
            raise PolicyBenchmarkPriceFixingCorruption("price-fixing ledger seal is invalid")
        if (
            model.persisted_at.tzinfo is None
            or model.persisted_at.utcoffset() is None
            or model.persisted_at != model.recorded_at
            or value.recorded_at != model.recorded_at
            or model.recorded_at >= value.valid_until
        ):
            raise PolicyBenchmarkPriceFixingCorruption("price-fixing persistence clock is invalid")
        return value


PriceFixingState = tuple[
    PortfolioPolicyBenchmarkPriceFixing, PortfolioPolicyBenchmarkPriceFixingModel
]


def _active_token() -> object:
    token = _ACTIVE_PRICE_FIXING_UOW.get()
    if token is None:
        raise PolicyBenchmarkPriceFixingConflict(
            "price-fixing append requires an active private unit"
        )
    return token


def _validate(value: object) -> PortfolioPolicyBenchmarkPriceFixing:
    if type(value) is not PortfolioPolicyBenchmarkPriceFixing:
        raise PolicyBenchmarkPriceFixingConflict("price-fixing type substitution")
    try:
        PortfolioPolicyBenchmarkPriceFixing.__post_init__(value)
    except (TypeError, ValueError) as error:
        raise PolicyBenchmarkPriceFixingConflict("price-fixing is invalid") from error
    return value


def _exact(
    rows: tuple[PriceFixingState, ...], value: PortfolioPolicyBenchmarkPriceFixing
) -> PriceFixingState | None:
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
        raise PolicyBenchmarkPriceFixingConflict("price-fixing anchor has another first winner")
    return matches[0]


def _hash(payload: dict[str, object]) -> str:
    return hashlib.sha256(
        json.dumps(
            payload, allow_nan=False, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ).encode()
    ).hexdigest()


def _time(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _sources_hash(value: PortfolioPolicyBenchmarkPriceFixing) -> str:
    return _hash({"source_priority": [source.to_payload() for source in value.source_priority]})


def _ledger_hash(value: PortfolioPolicyBenchmarkPriceFixing, recorded_at: datetime) -> str:
    return _hash(
        {
            "identity_hash": value.identity_hash,
            "content_hash": value.content_hash,
            "methodology_id": value.methodology_id,
            "methodology_version": value.methodology_version,
            "sources_hash": _sources_hash(value),
            "recorded_at": _time(recorded_at),
            "valid_until": _time(value.valid_until),
        }
    )


def _model_values(
    value: PortfolioPolicyBenchmarkPriceFixing, recorded_at: datetime
) -> dict[str, object]:
    payload = encode_policy_benchmark_price_fixing(value)
    return {
        "owner": value.owner,
        "artifact_type": value.artifact_type,
        "schema": value.schema,
        "permission": value.permission,
        "methodology_id": value.methodology_id,
        "methodology_version": value.methodology_version,
        "price_identifier_namespace": value.price_identifier_namespace,
        "price_field": value.price_field,
        "adjustment_basis": value.adjustment_basis,
        "venue": value.venue,
        "timezone_name": value.timezone,
        "valuation_cutoff_local": payload["valuation_cutoff_local"],
        "source_count": len(value.source_priority),
        "sources_hash": _sources_hash(value),
        "stale_after_seconds": value.stale_after_seconds,
        "missing_price_policy": value.missing_price_policy,
        "source_failure_policy": value.source_failure_policy,
        "recorded_at": recorded_at,
        "valid_until": value.valid_until,
        "persisted_at": recorded_at,
        "canonical_payload": payload,
        "identity_hash": value.identity_hash,
        "content_hash": value.content_hash,
        "ledger_header_hash": _ledger_hash(value, recorded_at),
    }


def _headers(value: PortfolioPolicyBenchmarkPriceFixing) -> tuple[object, ...]:
    payload = encode_policy_benchmark_price_fixing(value)
    return (
        value.owner,
        value.artifact_type,
        value.schema,
        value.permission,
        value.methodology_id,
        value.methodology_version,
        value.price_identifier_namespace,
        value.price_field,
        value.adjustment_basis,
        value.venue,
        value.timezone,
        payload["valuation_cutoff_local"],
        len(value.source_priority),
        _sources_hash(value),
        value.stale_after_seconds,
        value.missing_price_policy,
        value.source_failure_policy,
        value.recorded_at,
        value.valid_until,
        value.identity_hash,
        value.content_hash,
    )


def _model_headers(model: PortfolioPolicyBenchmarkPriceFixingModel) -> tuple[object, ...]:
    return (
        model.owner,
        model.artifact_type,
        model.schema,
        model.permission,
        model.methodology_id,
        model.methodology_version,
        model.price_identifier_namespace,
        model.price_field,
        model.adjustment_basis,
        model.venue,
        model.timezone_name,
        model.valuation_cutoff_local,
        model.source_count,
        model.sources_hash,
        model.stale_after_seconds,
        model.missing_price_policy,
        model.source_failure_policy,
        model.recorded_at,
        model.valid_until,
        model.identity_hash,
        model.content_hash,
    )


__all__ = [
    "DjangoPolicyBenchmarkPriceFixingClock",
    "DjangoPolicyBenchmarkPriceFixingRepository",
    "PolicyBenchmarkPriceFixingClock",
    "PolicyBenchmarkPriceFixingConflict",
    "PolicyBenchmarkPriceFixingCorruption",
    "PolicyBenchmarkPriceFixingUnavailable",
]
