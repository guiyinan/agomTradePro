"""Append-only exact/PIT ledger for benchmark corporate-action methodologies."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from typing import Protocol, cast

from django.db import IntegrityError, transaction
from django.utils import timezone

from apps.portfolio.domain.policy_benchmark_corporate_action import (
    PortfolioPolicyBenchmarkCorporateAction,
)
from apps.portfolio.infrastructure.policy_benchmark_corporate_action_codec import (
    PolicyBenchmarkCorporateActionCodecError,
    decode_policy_benchmark_corporate_action,
    encode_policy_benchmark_corporate_action,
)
from apps.portfolio.infrastructure.policy_benchmark_corporate_action_models import (
    _ACTIVE_CORPORATE_ACTION_UOW,
    PortfolioPolicyBenchmarkCorporateActionModel,
    _activate_corporate_action_uow,
    _claim_corporate_action_insert,
)


class PolicyBenchmarkCorporateActionUnavailable(ValueError):
    """An exact methodology is unavailable at the requested cutoff."""


class PolicyBenchmarkCorporateActionConflict(ValueError):
    """An immutable methodology anchor has another first winner."""


class PolicyBenchmarkCorporateActionCorruption(ValueError):
    """Persisted methodology data failed closed-world validation."""


class PolicyBenchmarkCorporateActionClock(Protocol):
    """Authoritative Portfolio persistence clock."""

    def now(self) -> datetime:
        """Return one timezone-aware server timestamp."""


class DjangoPolicyBenchmarkCorporateActionClock:
    """Django timezone-backed production clock."""

    def now(self) -> datetime:
        """Return the current timezone-aware server timestamp."""

        return cast(datetime, timezone.now())


class DjangoPolicyBenchmarkCorporateActionRepository:
    """Private first-winner writer and strict historical exact/PIT reader."""

    __slots__ = ("_clock", "_using")

    def __init__(
        self,
        *,
        using: str = "default",
        clock: PolicyBenchmarkCorporateActionClock | None = None,
    ) -> None:
        self._using = using
        self._clock = clock or DjangoPolicyBenchmarkCorporateActionClock()

    @contextmanager
    def atomic(self) -> Iterator[None]:
        """Open this capability's private append transaction."""

        token = object()
        with transaction.atomic(using=self._using), _activate_corporate_action_uow(token):
            yield

    def now(self) -> datetime:
        """Return the validated authoritative Portfolio clock."""

        value = self._clock.now()
        if value.tzinfo is None or value.utcoffset() is None:
            raise PolicyBenchmarkCorporateActionCorruption("corporate-action clock is naive")
        return value

    def append(
        self,
        value: PortfolioPolicyBenchmarkCorporateAction,
        *,
        recorded_at: datetime,
    ) -> PortfolioPolicyBenchmarkCorporateAction:
        """Append or return the exact identity/content first winner."""

        token = _active_token()
        _validate(value)
        if recorded_at.tzinfo is None or recorded_at.utcoffset() is None:
            raise PolicyBenchmarkCorporateActionConflict("recorded_at must be timezone-aware")
        if value.recorded_at != recorded_at:
            raise PolicyBenchmarkCorporateActionConflict(
                "methodology recorded_at must equal the authoritative server clock"
            )
        if recorded_at >= value.valid_until:
            raise PolicyBenchmarkCorporateActionConflict(
                "methodology must be persisted within its validity window"
            )
        existing = _exact(self._all(), value)
        if existing is not None:
            return existing[0]
        values = _model_values(value, recorded_at)
        model = PortfolioPolicyBenchmarkCorporateActionModel(**values)
        try:
            with (
                transaction.atomic(using=self._using),
                _claim_corporate_action_insert(
                    token=token,
                    model_type=PortfolioPolicyBenchmarkCorporateActionModel,
                    expected_values=values,
                ),
            ):
                model.save(force_insert=True, using=self._using)
        except IntegrityError:
            winner = _exact(self._all(), value)
            if winner is None:
                raise PolicyBenchmarkCorporateActionConflict(
                    "methodology append conflicted without exact first winner"
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
    ) -> PortfolioPolicyBenchmarkCorporateAction | None:
        """Return one exact methodology by full selector at a strict PIT cutoff."""

        self._require_cutoff(as_of)
        matches = tuple(
            value
            for value, _ in self._all()
            if value.methodology_id == methodology_id
            and value.methodology_version == methodology_version
            and value.content_hash == expected_content_hash
        )
        if len(matches) > 1:
            raise PolicyBenchmarkCorporateActionCorruption("corporate-action selector is ambiguous")
        if not matches:
            return None
        return matches[0] if matches[0].is_knowable_at(as_of) else None

    def _require_cutoff(self, as_of: datetime) -> None:
        if as_of.tzinfo is None or as_of.utcoffset() is None:
            raise PolicyBenchmarkCorporateActionUnavailable("corporate-action as_of is naive")
        if as_of > self.now():
            raise PolicyBenchmarkCorporateActionUnavailable(
                "future corporate-action as_of is forbidden"
            )

    def _all(
        self,
    ) -> tuple[
        tuple[
            PortfolioPolicyBenchmarkCorporateAction,
            PortfolioPolicyBenchmarkCorporateActionModel,
        ],
        ...,
    ]:
        rows = tuple(
            PortfolioPolicyBenchmarkCorporateActionModel._default_manager.using(self._using).all()
        )
        return tuple((self._restore(row), row) for row in rows)

    def _restore(
        self, model: PortfolioPolicyBenchmarkCorporateActionModel
    ) -> PortfolioPolicyBenchmarkCorporateAction:
        try:
            value = decode_policy_benchmark_corporate_action(model.canonical_payload)
        except PolicyBenchmarkCorporateActionCodecError as error:
            raise PolicyBenchmarkCorporateActionCorruption(
                "corporate-action payload cannot be restored"
            ) from error
        if _headers(value) != _model_headers(model):
            raise PolicyBenchmarkCorporateActionCorruption(
                "corporate-action headers do not match payload"
            )
        if (
            model.identity_hash != value.identity_hash
            or model.content_hash != value.content_hash
            or model.ledger_header_hash != _ledger_hash(value, model.recorded_at)
        ):
            raise PolicyBenchmarkCorporateActionCorruption(
                "corporate-action ledger seal is invalid"
            )
        if (
            model.persisted_at.tzinfo is None
            or model.persisted_at.utcoffset() is None
            or model.recorded_at.tzinfo is None
            or model.recorded_at.utcoffset() is None
            or model.persisted_at != model.recorded_at
            or value.recorded_at != model.recorded_at
            or model.recorded_at >= value.valid_until
        ):
            raise PolicyBenchmarkCorporateActionCorruption(
                "corporate-action persistence clock is invalid"
            )
        return value


CorporateActionState = tuple[
    PortfolioPolicyBenchmarkCorporateAction,
    PortfolioPolicyBenchmarkCorporateActionModel,
]


def _active_token() -> object:
    token = _ACTIVE_CORPORATE_ACTION_UOW.get()
    if token is None:
        raise PolicyBenchmarkCorporateActionConflict(
            "methodology append requires an active private unit"
        )
    return token


def _validate(value: object) -> PortfolioPolicyBenchmarkCorporateAction:
    if type(value) is not PortfolioPolicyBenchmarkCorporateAction:
        raise PolicyBenchmarkCorporateActionConflict("methodology type substitution")
    try:
        PortfolioPolicyBenchmarkCorporateAction.__post_init__(value)
    except (TypeError, ValueError) as error:
        raise PolicyBenchmarkCorporateActionConflict(
            "corporate-action methodology is invalid"
        ) from error
    return value


def _exact(
    rows: tuple[CorporateActionState, ...],
    value: PortfolioPolicyBenchmarkCorporateAction,
) -> CorporateActionState | None:
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
        raise PolicyBenchmarkCorporateActionConflict(
            "corporate-action anchor has another first winner"
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


def _sources_hash(value: PortfolioPolicyBenchmarkCorporateAction) -> str:
    return _hash({"source_priority": [source.to_payload() for source in value.source_priority]})


def _event_rules_hash(value: PortfolioPolicyBenchmarkCorporateAction) -> str:
    return _hash({"event_rules": [rule.to_payload() for rule in value.event_rules]})


def _ledger_hash(value: PortfolioPolicyBenchmarkCorporateAction, recorded_at: datetime) -> str:
    return _hash(
        {
            "identity_hash": value.identity_hash,
            "content_hash": value.content_hash,
            "methodology_id": value.methodology_id,
            "methodology_version": value.methodology_version,
            "sources_hash": _sources_hash(value),
            "event_rules_hash": _event_rules_hash(value),
            "recorded_at": _time(recorded_at),
            "valid_until": _time(value.valid_until),
        }
    )


def _model_values(
    value: PortfolioPolicyBenchmarkCorporateAction, recorded_at: datetime
) -> dict[str, object]:
    payload = encode_policy_benchmark_corporate_action(value)
    return {
        "owner": value.owner,
        "artifact_type": value.artifact_type,
        "schema": value.schema,
        "permission": value.permission,
        "methodology_id": value.methodology_id,
        "methodology_version": value.methodology_version,
        "security_identifier_namespace": value.security_identifier_namespace,
        "timezone_name": value.timezone,
        "business_date_cutoff_local": payload["business_date_cutoff_local"],
        "business_date_policy": value.business_date_policy,
        "non_business_date_policy": value.non_business_date_policy,
        "source_count": len(value.source_priority),
        "sources_hash": _sources_hash(value),
        "event_rule_count": len(value.event_rules),
        "event_rules_hash": _event_rules_hash(value),
        "source_failure_policy": value.source_failure_policy,
        "missing_action_policy": value.missing_action_policy,
        "unknown_event_type_policy": value.unknown_event_type_policy,
        "price_input_adjustment_basis": value.price_input_adjustment_basis,
        "adjustment_application_policy": value.adjustment_application_policy,
        "duplicate_event_policy": value.duplicate_event_policy,
        "pre_adjusted_input_policy": value.pre_adjusted_input_policy,
        "recorded_at": recorded_at,
        "valid_until": value.valid_until,
        "persisted_at": recorded_at,
        "canonical_payload": payload,
        "identity_hash": value.identity_hash,
        "content_hash": value.content_hash,
        "ledger_header_hash": _ledger_hash(value, recorded_at),
    }


def _headers(value: PortfolioPolicyBenchmarkCorporateAction) -> tuple[object, ...]:
    payload = encode_policy_benchmark_corporate_action(value)
    return (
        value.owner,
        value.artifact_type,
        value.schema,
        value.permission,
        value.methodology_id,
        value.methodology_version,
        value.security_identifier_namespace,
        value.timezone,
        payload["business_date_cutoff_local"],
        value.business_date_policy,
        value.non_business_date_policy,
        len(value.source_priority),
        _sources_hash(value),
        len(value.event_rules),
        _event_rules_hash(value),
        value.source_failure_policy,
        value.missing_action_policy,
        value.unknown_event_type_policy,
        value.price_input_adjustment_basis,
        value.adjustment_application_policy,
        value.duplicate_event_policy,
        value.pre_adjusted_input_policy,
        value.recorded_at,
        value.valid_until,
        value.identity_hash,
        value.content_hash,
    )


def _model_headers(
    model: PortfolioPolicyBenchmarkCorporateActionModel,
) -> tuple[object, ...]:
    return (
        model.owner,
        model.artifact_type,
        model.schema,
        model.permission,
        model.methodology_id,
        model.methodology_version,
        model.security_identifier_namespace,
        model.timezone_name,
        model.business_date_cutoff_local,
        model.business_date_policy,
        model.non_business_date_policy,
        model.source_count,
        model.sources_hash,
        model.event_rule_count,
        model.event_rules_hash,
        model.source_failure_policy,
        model.missing_action_policy,
        model.unknown_event_type_policy,
        model.price_input_adjustment_basis,
        model.adjustment_application_policy,
        model.duplicate_event_policy,
        model.pre_adjusted_input_policy,
        model.recorded_at,
        model.valid_until,
        model.identity_hash,
        model.content_hash,
    )


__all__ = [
    "DjangoPolicyBenchmarkCorporateActionClock",
    "DjangoPolicyBenchmarkCorporateActionRepository",
    "PolicyBenchmarkCorporateActionClock",
    "PolicyBenchmarkCorporateActionConflict",
    "PolicyBenchmarkCorporateActionCorruption",
    "PolicyBenchmarkCorporateActionUnavailable",
]
