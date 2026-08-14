"""Append-only exact/PIT ledger for benchmark cost/tax methodologies."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from typing import Protocol, cast

from django.db import IntegrityError, transaction
from django.utils import timezone

from apps.portfolio.domain.policy_benchmark_cost_tax import (
    PortfolioPolicyBenchmarkCostTax,
)
from apps.portfolio.infrastructure.policy_benchmark_cost_tax_codec import (
    PolicyBenchmarkCostTaxCodecError,
    decode_policy_benchmark_cost_tax,
    encode_policy_benchmark_cost_tax,
)
from apps.portfolio.infrastructure.policy_benchmark_cost_tax_models import (
    _ACTIVE_COST_TAX_UOW,
    PortfolioPolicyBenchmarkCostTaxModel,
    _activate_cost_tax_uow,
    _claim_cost_tax_insert,
)


class PolicyBenchmarkCostTaxUnavailable(ValueError):
    """An exact methodology is unavailable at the requested cutoff."""


class PolicyBenchmarkCostTaxConflict(ValueError):
    """An immutable methodology anchor has another first winner."""


class PolicyBenchmarkCostTaxCorruption(ValueError):
    """Persisted methodology data failed closed-world validation."""


class PolicyBenchmarkCostTaxClock(Protocol):
    """Authoritative Portfolio persistence clock."""

    def now(self) -> datetime:
        """Return one timezone-aware server timestamp."""


class DjangoPolicyBenchmarkCostTaxClock:
    """Django timezone-backed production clock."""

    def now(self) -> datetime:
        """Return the current timezone-aware server timestamp."""

        return cast(datetime, timezone.now())


class DjangoPolicyBenchmarkCostTaxRepository:
    """Private first-winner writer and strict historical exact/PIT reader."""

    __slots__ = ("_clock", "_using")

    def __init__(
        self,
        *,
        using: str = "default",
        clock: PolicyBenchmarkCostTaxClock | None = None,
    ) -> None:
        self._using = using
        self._clock = clock or DjangoPolicyBenchmarkCostTaxClock()

    @contextmanager
    def atomic(self) -> Iterator[None]:
        """Open this capability's private append transaction."""

        token = object()
        with transaction.atomic(using=self._using), _activate_cost_tax_uow(token):
            yield

    def now(self) -> datetime:
        """Return the validated authoritative Portfolio clock."""

        value = self._clock.now()
        if value.tzinfo is None or value.utcoffset() is None:
            raise PolicyBenchmarkCostTaxCorruption("cost/tax clock is naive")
        return value

    def append(
        self,
        value: PortfolioPolicyBenchmarkCostTax,
        *,
        recorded_at: datetime,
    ) -> PortfolioPolicyBenchmarkCostTax:
        """Append or return the exact identity/content first winner."""

        token = _active_token()
        _validate(value)
        if recorded_at.tzinfo is None or recorded_at.utcoffset() is None:
            raise PolicyBenchmarkCostTaxConflict("recorded_at must be timezone-aware")
        if value.recorded_at != recorded_at:
            raise PolicyBenchmarkCostTaxConflict(
                "methodology recorded_at must equal the authoritative server clock"
            )
        if recorded_at >= value.valid_until:
            raise PolicyBenchmarkCostTaxConflict(
                "methodology must be persisted within its validity window"
            )
        existing = _exact(self._all(), value)
        if existing is not None:
            return existing[0]
        values = _model_values(value, recorded_at)
        model = PortfolioPolicyBenchmarkCostTaxModel(**values)
        try:
            with (
                transaction.atomic(using=self._using),
                _claim_cost_tax_insert(
                    token=token,
                    model_type=PortfolioPolicyBenchmarkCostTaxModel,
                    expected_values=values,
                ),
            ):
                model.save(force_insert=True, using=self._using)
        except IntegrityError:
            winner = _exact(self._all(), value)
            if winner is None:
                raise PolicyBenchmarkCostTaxConflict(
                    "cost/tax append conflicted without exact first winner"
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
    ) -> PortfolioPolicyBenchmarkCostTax | None:
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
            raise PolicyBenchmarkCostTaxCorruption("cost/tax selector is ambiguous")
        if not matches:
            return None
        return matches[0] if matches[0].is_knowable_at(as_of) else None

    def _require_cutoff(self, as_of: datetime) -> None:
        if as_of.tzinfo is None or as_of.utcoffset() is None:
            raise PolicyBenchmarkCostTaxUnavailable("cost/tax as_of is naive")
        if as_of > self.now():
            raise PolicyBenchmarkCostTaxUnavailable("future cost/tax as_of is forbidden")

    def _all(
        self,
    ) -> tuple[tuple[PortfolioPolicyBenchmarkCostTax, PortfolioPolicyBenchmarkCostTaxModel], ...]:
        rows = tuple(PortfolioPolicyBenchmarkCostTaxModel._default_manager.using(self._using).all())
        return tuple((self._restore(row), row) for row in rows)

    def _restore(
        self, model: PortfolioPolicyBenchmarkCostTaxModel
    ) -> PortfolioPolicyBenchmarkCostTax:
        try:
            value = decode_policy_benchmark_cost_tax(model.canonical_payload)
        except PolicyBenchmarkCostTaxCodecError as error:
            raise PolicyBenchmarkCostTaxCorruption("cost/tax payload cannot be restored") from error
        if _headers(value) != _model_headers(model):
            raise PolicyBenchmarkCostTaxCorruption("cost/tax headers do not match payload")
        if (
            model.identity_hash != value.identity_hash
            or model.content_hash != value.content_hash
            or model.ledger_header_hash != _ledger_hash(value, model.recorded_at)
        ):
            raise PolicyBenchmarkCostTaxCorruption("cost/tax ledger seal is invalid")
        if (
            model.persisted_at.tzinfo is None
            or model.persisted_at.utcoffset() is None
            or model.recorded_at.tzinfo is None
            or model.recorded_at.utcoffset() is None
            or model.persisted_at != model.recorded_at
            or value.recorded_at != model.recorded_at
            or model.recorded_at >= value.valid_until
        ):
            raise PolicyBenchmarkCostTaxCorruption("cost/tax persistence clock is invalid")
        return value


CostTaxState = tuple[PortfolioPolicyBenchmarkCostTax, PortfolioPolicyBenchmarkCostTaxModel]


def _active_token() -> object:
    token = _ACTIVE_COST_TAX_UOW.get()
    if token is None:
        raise PolicyBenchmarkCostTaxConflict("cost/tax append requires an active private unit")
    return token


def _validate(value: object) -> PortfolioPolicyBenchmarkCostTax:
    if type(value) is not PortfolioPolicyBenchmarkCostTax:
        raise PolicyBenchmarkCostTaxConflict("cost/tax methodology type substitution")
    try:
        PortfolioPolicyBenchmarkCostTax.__post_init__(value)
    except (TypeError, ValueError) as error:
        raise PolicyBenchmarkCostTaxConflict("cost/tax methodology is invalid") from error
    return value


def _exact(
    rows: tuple[CostTaxState, ...], value: PortfolioPolicyBenchmarkCostTax
) -> CostTaxState | None:
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
        raise PolicyBenchmarkCostTaxConflict("cost/tax anchor has another first winner")
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


def _sources_hash(value: PortfolioPolicyBenchmarkCostTax) -> str:
    return _hash({"source_priority": [source.to_payload() for source in value.source_priority]})


def _charge_rules_hash(value: PortfolioPolicyBenchmarkCostTax) -> str:
    return _hash({"charge_rules": [rule.to_payload() for rule in value.charge_rules]})


def _source_counts(value: PortfolioPolicyBenchmarkCostTax) -> tuple[int, int]:
    return (
        sum(source.charge_kind == "fee" for source in value.source_priority),
        sum(source.charge_kind == "tax" for source in value.source_priority),
    )


def _rule_counts(value: PortfolioPolicyBenchmarkCostTax) -> tuple[int, int]:
    return (
        sum(rule.charge_kind == "fee" for rule in value.charge_rules),
        sum(rule.charge_kind == "tax" for rule in value.charge_rules),
    )


def _ledger_hash(value: PortfolioPolicyBenchmarkCostTax, recorded_at: datetime) -> str:
    return _hash(
        {
            "identity_hash": value.identity_hash,
            "content_hash": value.content_hash,
            "methodology_id": value.methodology_id,
            "methodology_version": value.methodology_version,
            "sources_hash": _sources_hash(value),
            "charge_rules_hash": _charge_rules_hash(value),
            "recorded_at": _time(recorded_at),
            "valid_until": _time(value.valid_until),
        }
    )


def _model_values(
    value: PortfolioPolicyBenchmarkCostTax, recorded_at: datetime
) -> dict[str, object]:
    payload = encode_policy_benchmark_cost_tax(value)
    fee_sources, tax_sources = _source_counts(value)
    fee_rules, tax_rules = _rule_counts(value)
    return {
        "owner": value.owner,
        "artifact_type": value.artifact_type,
        "schema": value.schema,
        "permission": value.permission,
        "methodology_id": value.methodology_id,
        "methodology_version": value.methodology_version,
        "source_count": len(value.source_priority),
        "fee_source_count": fee_sources,
        "tax_source_count": tax_sources,
        "sources_hash": _sources_hash(value),
        "charge_rule_count": len(value.charge_rules),
        "fee_rule_count": fee_rules,
        "tax_rule_count": tax_rules,
        "charge_rules_hash": _charge_rules_hash(value),
        "business_date_policy": value.business_date_policy,
        "currency_basis_policy": value.currency_basis_policy,
        "currency_conversion_policy": value.currency_conversion_policy,
        "missing_fx_policy": value.missing_fx_policy,
        "unknown_asset_policy": value.unknown_asset_policy,
        "unknown_fee_policy": value.unknown_fee_policy,
        "unknown_tax_policy": value.unknown_tax_policy,
        "missing_source_policy": value.missing_source_policy,
        "source_failure_policy": value.source_failure_policy,
        "estimation_policy": value.estimation_policy,
        "silent_zero_policy": value.silent_zero_policy,
        "duplicate_charge_policy": value.duplicate_charge_policy,
        "cash_dividend_charge_policy": value.cash_dividend_charge_policy,
        "cash_dividend_payment_policy": value.cash_dividend_payment_policy,
        "corporate_action_charge_policy": value.corporate_action_charge_policy,
        "already_net_amount_policy": value.already_net_amount_policy,
        "recorded_at": recorded_at,
        "valid_until": value.valid_until,
        "persisted_at": recorded_at,
        "canonical_payload": payload,
        "identity_hash": value.identity_hash,
        "content_hash": value.content_hash,
        "ledger_header_hash": _ledger_hash(value, recorded_at),
    }


def _headers(value: PortfolioPolicyBenchmarkCostTax) -> tuple[object, ...]:
    fee_sources, tax_sources = _source_counts(value)
    fee_rules, tax_rules = _rule_counts(value)
    return (
        value.owner,
        value.artifact_type,
        value.schema,
        value.permission,
        value.methodology_id,
        value.methodology_version,
        len(value.source_priority),
        fee_sources,
        tax_sources,
        _sources_hash(value),
        len(value.charge_rules),
        fee_rules,
        tax_rules,
        _charge_rules_hash(value),
        value.business_date_policy,
        value.currency_basis_policy,
        value.currency_conversion_policy,
        value.missing_fx_policy,
        value.unknown_asset_policy,
        value.unknown_fee_policy,
        value.unknown_tax_policy,
        value.missing_source_policy,
        value.source_failure_policy,
        value.estimation_policy,
        value.silent_zero_policy,
        value.duplicate_charge_policy,
        value.cash_dividend_charge_policy,
        value.cash_dividend_payment_policy,
        value.corporate_action_charge_policy,
        value.already_net_amount_policy,
        value.recorded_at,
        value.valid_until,
        value.identity_hash,
        value.content_hash,
    )


def _model_headers(model: PortfolioPolicyBenchmarkCostTaxModel) -> tuple[object, ...]:
    return (
        model.owner,
        model.artifact_type,
        model.schema,
        model.permission,
        model.methodology_id,
        model.methodology_version,
        model.source_count,
        model.fee_source_count,
        model.tax_source_count,
        model.sources_hash,
        model.charge_rule_count,
        model.fee_rule_count,
        model.tax_rule_count,
        model.charge_rules_hash,
        model.business_date_policy,
        model.currency_basis_policy,
        model.currency_conversion_policy,
        model.missing_fx_policy,
        model.unknown_asset_policy,
        model.unknown_fee_policy,
        model.unknown_tax_policy,
        model.missing_source_policy,
        model.source_failure_policy,
        model.estimation_policy,
        model.silent_zero_policy,
        model.duplicate_charge_policy,
        model.cash_dividend_charge_policy,
        model.cash_dividend_payment_policy,
        model.corporate_action_charge_policy,
        model.already_net_amount_policy,
        model.recorded_at,
        model.valid_until,
        model.identity_hash,
        model.content_hash,
    )


__all__ = [
    "DjangoPolicyBenchmarkCostTaxClock",
    "DjangoPolicyBenchmarkCostTaxRepository",
    "PolicyBenchmarkCostTaxClock",
    "PolicyBenchmarkCostTaxConflict",
    "PolicyBenchmarkCostTaxCorruption",
    "PolicyBenchmarkCostTaxUnavailable",
]
