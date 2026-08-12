"""Append-only Portfolio repository for canonical R5 monitoring raw facts."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterator, Mapping
from contextlib import AbstractContextManager, contextmanager
from datetime import UTC, datetime
from decimal import Decimal
from enum import Enum

from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.db.models import Q
from django.utils import timezone

from apps.portfolio.application.r5_monitoring_raw_fact_registry import (
    PortfolioR5MonitoringRawFactClock,
)
from apps.portfolio.domain.r5_monitoring_raw_fact_registry import (
    PortfolioR5MonitoringRawFactDefinition,
    PortfolioR5MonitoringRawFactSourceReceipt,
)
from apps.portfolio.infrastructure.optimization_research_models import (
    _activate_governed_optimization_uow,
    _claim_governed_optimization_insert,
)
from apps.portfolio.infrastructure.r5_monitoring_raw_fact_codec import (
    decode_portfolio_r5_monitoring_raw_fact,
    encode_portfolio_r5_monitoring_raw_fact,
)
from apps.portfolio.infrastructure.r5_monitoring_raw_fact_models import (
    PortfolioR5MonitoringRawFactReceiptModel,
)
from apps.research.domain.r5_relative_value_monitoring_contracts import (
    _require_aware,
    _require_hash,
    _require_token,
)
from apps.research.domain.r5_relative_value_monitoring_facts import (
    R5PostPromotionMonitoringFact,
)


class PortfolioR5MonitoringRawFactConflict(RuntimeError):
    """One immutable Portfolio fact identity or period has another winner."""


class PortfolioR5MonitoringRawFactCorruption(RuntimeError):
    """A stored Portfolio fact, source receipt, or ledger header was substituted."""


class DjangoPortfolioR5MonitoringRawFactClock:
    """Django-aware clock bound to the Portfolio database alias."""

    def __init__(self, *, using: str = "default") -> None:
        self._using = using

    @property
    def unit_of_work_key(self) -> str:
        """Return the database transaction identity."""

        return f"django:{self._using}"

    def now(self) -> datetime:
        """Return one timezone-aware server timestamp."""

        return timezone.now()


class DjangoPortfolioR5MonitoringRawFactRepository:
    """Public exact PIT reader retaining no append capability."""

    def __init__(
        self,
        *,
        using: str = "default",
        clock: PortfolioR5MonitoringRawFactClock | None = None,
    ) -> None:
        self._using = using
        self._clock = clock or DjangoPortfolioR5MonitoringRawFactClock(using=using)

    @property
    def unit_of_work_key(self) -> str:
        """Return the database transaction identity."""

        return f"django:{self._using}"

    def atomic(self) -> AbstractContextManager[None]:
        """Open one exact Portfolio read transaction."""

        return transaction.atomic(using=self._using)

    def list_exact(
        self,
        *,
        policy_id: str,
        policy_version: str,
        expected_policy_hash: str,
        target_hash: str,
        calendar_id: str,
        calendar_version: str,
        expected_calendar_hash: str,
        period_ids: tuple[str, ...],
        as_of: datetime,
    ) -> tuple[R5PostPromotionMonitoringFact, ...]:
        """Return exact facts in canonical period order or explicit incompleteness."""

        _validate_query(
            policy_id=policy_id,
            policy_version=policy_version,
            expected_policy_hash=expected_policy_hash,
            target_hash=target_hash,
            calendar_id=calendar_id,
            calendar_version=calendar_version,
            expected_calendar_hash=expected_calendar_hash,
            period_ids=period_ids,
            as_of=as_of,
        )
        self._require_cutoff(as_of)
        with self.atomic():
            rows = tuple(
                PortfolioR5MonitoringRawFactReceiptModel._default_manager.using(self._using)
                .filter(
                    policy_id=policy_id,
                    policy_version=policy_version,
                    calendar_id=calendar_id,
                    calendar_version=calendar_version,
                    period_id__in=period_ids,
                    ledger_recorded_at__lte=as_of,
                    fact_recorded_at__lte=as_of,
                    fact_valid_until__gt=as_of,
                    source_available_at__lte=as_of,
                    source_valid_until__gt=as_of,
                )
                .order_by("period_end", "fact_id")
            )
            restored = tuple(_fact_from_model(row) for row in rows)
        by_period: dict[str, R5PostPromotionMonitoringFact] = {}
        for fact in restored:
            if not (
                fact.policy_id == policy_id
                and fact.policy_version == policy_version
                and fact.policy_hash == expected_policy_hash
                and fact.target_hash == target_hash
                and fact.calendar_id == calendar_id
                and fact.calendar_version == calendar_version
                and fact.calendar_hash == expected_calendar_hash
                and fact.period_id in period_ids
                and fact.recorded_at <= as_of < fact.valid_until
            ):
                raise PortfolioR5MonitoringRawFactCorruption(
                    "Portfolio R5 monitoring owner graph was substituted"
                )
            if fact.period_id in by_period:
                raise PortfolioR5MonitoringRawFactCorruption(
                    "Portfolio R5 monitoring period has multiple winners"
                )
            by_period[fact.period_id] = fact
        return tuple(by_period[item] for item in period_ids if item in by_period)

    def _require_cutoff(self, as_of: datetime) -> None:
        try:
            now = self._clock.now()
            _require_aware(now, "Portfolio R5 monitoring server clock")
        except Exception as error:
            raise PortfolioR5MonitoringRawFactCorruption(
                "Portfolio R5 monitoring server clock is unavailable"
            ) from error
        if as_of > now:
            raise PortfolioR5MonitoringRawFactCorruption(
                "Portfolio R5 monitoring cutoff is in the future"
            )


class _DjangoPortfolioR5MonitoringRawFactStore(DjangoPortfolioR5MonitoringRawFactRepository):
    """Private append capability retained only by test composition."""

    def __init__(
        self,
        *,
        token: object,
        using: str = "default",
        clock: PortfolioR5MonitoringRawFactClock | None = None,
    ) -> None:
        super().__init__(using=using, clock=clock)
        self._token = token

    @contextmanager
    def atomic(self) -> Iterator[None]:
        """Open one claimed Portfolio owner transaction."""

        with (
            transaction.atomic(using=self._using),
            _activate_governed_optimization_uow(self._token),
        ):
            yield

    def append(
        self,
        *,
        definition: PortfolioR5MonitoringRawFactDefinition,
        source: PortfolioR5MonitoringRawFactSourceReceipt,
        ledger_recorded_at: datetime,
    ) -> R5PostPromotionMonitoringFact:
        """Append idempotently or reject an identity/period fork."""

        if type(definition) is not PortfolioR5MonitoringRawFactDefinition:
            raise TypeError("Portfolio R5 monitoring definition type differs")
        if type(source) is not PortfolioR5MonitoringRawFactSourceReceipt:
            raise TypeError("Portfolio R5 monitoring source type differs")
        canonical_definition = definition.validated_copy()
        canonical_source = source.validated_copy()
        fact = canonical_definition.fact
        _validate_append(
            fact=fact,
            definition_hash=canonical_definition.content_hash,
            source=canonical_source,
            ledger_recorded_at=ledger_recorded_at,
        )
        rows = self._winner_rows(fact)
        if rows:
            return _exact_winner(
                rows,
                fact=fact,
                definition=canonical_definition,
                source=canonical_source,
                ledger_recorded_at=ledger_recorded_at,
            )
        values = _model_values(
            fact=fact,
            definition=canonical_definition,
            source=canonical_source,
            ledger_recorded_at=ledger_recorded_at,
        )
        model = PortfolioR5MonitoringRawFactReceiptModel(**values)
        try:
            model.full_clean()
            with transaction.atomic(using=self._using):
                with _claim_governed_optimization_insert(
                    token=self._token,
                    model_type=PortfolioR5MonitoringRawFactReceiptModel,
                    expected_values=values,
                ):
                    model.save(force_insert=True, using=self._using)
        except (IntegrityError, ValidationError) as error:
            winner_rows = self._winner_rows(fact)
            if not winner_rows:
                raise PortfolioR5MonitoringRawFactConflict(
                    "Portfolio R5 monitoring raw-fact append failed"
                ) from error
            try:
                return _exact_winner(
                    winner_rows,
                    fact=fact,
                    definition=canonical_definition,
                    source=canonical_source,
                    ledger_recorded_at=ledger_recorded_at,
                )
            except PortfolioR5MonitoringRawFactConflict as conflict:
                raise conflict from error
        return fact.validated_copy()

    def _winner_rows(
        self,
        fact: R5PostPromotionMonitoringFact,
    ) -> tuple[PortfolioR5MonitoringRawFactReceiptModel, ...]:
        return tuple(
            PortfolioR5MonitoringRawFactReceiptModel._default_manager.using(self._using)
            .filter(
                Q(fact_id=fact.fact_id, fact_version=fact.fact_version)
                | Q(
                    policy_id=fact.policy_id,
                    policy_version=fact.policy_version,
                    policy_hash=fact.policy_hash,
                    target_hash=fact.target_hash,
                    calendar_id=fact.calendar_id,
                    calendar_version=fact.calendar_version,
                    calendar_hash=fact.calendar_hash,
                    period_id=fact.period_id,
                )
            )
            .order_by("pk")
        )


def _model_values(
    *,
    fact: R5PostPromotionMonitoringFact,
    definition: PortfolioR5MonitoringRawFactDefinition,
    source: PortfolioR5MonitoringRawFactSourceReceipt,
    ledger_recorded_at: datetime,
) -> dict[str, object]:
    values: dict[str, object] = {
        "fact_id": fact.fact_id,
        "fact_version": fact.fact_version,
        "fact_hash": fact.content_hash,
        "definition_hash": definition.content_hash,
        "period_id": fact.period_id,
        "period_end": fact.period_end,
        "calendar_id": fact.calendar_id,
        "calendar_version": fact.calendar_version,
        "calendar_hash": fact.calendar_hash,
        "policy_id": fact.policy_id,
        "policy_version": fact.policy_version,
        "policy_hash": fact.policy_hash,
        "target_hash": fact.target_hash,
        "scope_id": fact.scope_id,
        "decision_id": fact.decision_id,
        "decision_version": fact.decision_version,
        "lifecycle_hash": fact.lifecycle_hash,
        "source_receipt_id": source.source_receipt_id,
        "source_receipt_version": source.source_receipt_version,
        "source_receipt_hash": source.content_hash,
        "source_available_at": source.available_at,
        "source_valid_until": source.valid_until,
        "fact_recorded_at": fact.recorded_at,
        "fact_valid_until": fact.valid_until,
        "ledger_recorded_at": ledger_recorded_at,
        "fact_payload": encode_portfolio_r5_monitoring_raw_fact(fact),
        "source_payload": _source_payload(source),
        "research_only": True,
        "must_not_publish_current": True,
        "must_not_use_for_decision": True,
        "must_not_execute": True,
    }
    values["ledger_header_hash"] = _header_hash(values)
    return values


def _fact_from_model(
    row: PortfolioR5MonitoringRawFactReceiptModel,
) -> R5PostPromotionMonitoringFact:
    try:
        fact = decode_portfolio_r5_monitoring_raw_fact(row.fact_payload)
        definition = PortfolioR5MonitoringRawFactDefinition.from_fact(fact)
        source = _restore_source(row.source_payload)
        values = _model_values(
            fact=fact,
            definition=definition,
            source=source,
            ledger_recorded_at=row.ledger_recorded_at,
        )
        _require_row(row, values)
        return fact
    except PortfolioR5MonitoringRawFactCorruption:
        raise
    except Exception as error:
        raise PortfolioR5MonitoringRawFactCorruption(
            "Portfolio R5 monitoring raw-fact row is invalid"
        ) from error


def _source_payload(
    source: PortfolioR5MonitoringRawFactSourceReceipt,
) -> dict[str, object]:
    return {
        "source_owner": source.source_owner,
        "source_receipt_id": source.source_receipt_id,
        "source_receipt_version": source.source_receipt_version,
        "fact_id": source.fact_id,
        "fact_version": source.fact_version,
        "definition_hash": source.definition_hash,
        "available_at": _time_text(source.available_at),
        "valid_until": _time_text(source.valid_until),
        "content_hash": source.content_hash,
    }


def _restore_source(payload: object) -> PortfolioR5MonitoringRawFactSourceReceipt:
    expected = {
        "source_owner",
        "source_receipt_id",
        "source_receipt_version",
        "fact_id",
        "fact_version",
        "definition_hash",
        "available_at",
        "valid_until",
        "content_hash",
    }
    if type(payload) is not dict or set(payload) != expected:
        raise PortfolioR5MonitoringRawFactCorruption(
            "Portfolio R5 monitoring source receipt shape differs"
        )
    try:
        return PortfolioR5MonitoringRawFactSourceReceipt(
            source_owner=str(payload["source_owner"]),
            source_receipt_id=str(payload["source_receipt_id"]),
            source_receipt_version=str(payload["source_receipt_version"]),
            fact_id=str(payload["fact_id"]),
            fact_version=str(payload["fact_version"]),
            definition_hash=str(payload["definition_hash"]),
            available_at=_parse_time(payload["available_at"]),
            valid_until=_parse_time(payload["valid_until"]),
            content_hash=str(payload["content_hash"]),
        )
    except (TypeError, ValueError) as error:
        raise PortfolioR5MonitoringRawFactCorruption(
            "Portfolio R5 monitoring source receipt is invalid"
        ) from error


def _validate_append(
    *,
    fact: R5PostPromotionMonitoringFact,
    definition_hash: str,
    source: PortfolioR5MonitoringRawFactSourceReceipt,
    ledger_recorded_at: datetime,
) -> None:
    _require_aware(ledger_recorded_at, "Portfolio R5 monitoring ledger_recorded_at")
    if not (
        source.fact_id == fact.fact_id
        and source.fact_version == fact.fact_version
        and source.definition_hash == definition_hash
        and source.available_at <= ledger_recorded_at < source.valid_until
        and fact.recorded_at <= ledger_recorded_at < fact.valid_until
    ):
        raise PortfolioR5MonitoringRawFactConflict(
            "Portfolio R5 monitoring definition/source clocks or identity differ"
        )


def _exact_winner(
    rows: tuple[PortfolioR5MonitoringRawFactReceiptModel, ...],
    *,
    fact: R5PostPromotionMonitoringFact,
    definition: PortfolioR5MonitoringRawFactDefinition,
    source: PortfolioR5MonitoringRawFactSourceReceipt,
    ledger_recorded_at: datetime,
) -> R5PostPromotionMonitoringFact:
    if len(rows) != 1:
        raise PortfolioR5MonitoringRawFactConflict("Portfolio R5 monitoring raw-fact winner forked")
    row = rows[0]
    restored = _fact_from_model(row)
    expected = _model_values(
        fact=fact,
        definition=definition,
        source=source,
        ledger_recorded_at=row.ledger_recorded_at,
    )
    _require_row(row, expected)
    if restored != fact or row.ledger_recorded_at > ledger_recorded_at:
        raise PortfolioR5MonitoringRawFactConflict(
            "Portfolio R5 monitoring raw-fact winner differs"
        )
    return restored


def _header_hash(values: Mapping[str, object]) -> str:
    payload = {
        "schema": "portfolio-r5-monitoring-raw-fact-registry-row.v1",
        "values": _ledger_value(
            {key: value for key, value in values.items() if key != "ledger_header_hash"}
        ),
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _ledger_value(value: object) -> object:
    if isinstance(value, datetime):
        return _time_text(value)
    if isinstance(value, Decimal):
        normalized = value.normalize()
        return "0" if normalized == 0 else format(normalized, "f")
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, Mapping):
        return {str(key): _ledger_value(item) for key, item in sorted(value.items())}
    if isinstance(value, (tuple, list)):
        return [_ledger_value(item) for item in value]
    if isinstance(value, (str, int, bool)) or value is None:
        return value
    raise TypeError(f"unsupported Portfolio R5 raw-fact ledger value: {type(value).__name__}")


def _require_row(row: object, values: Mapping[str, object]) -> None:
    for key, expected in values.items():
        if getattr(row, key) != expected:
            raise PortfolioR5MonitoringRawFactCorruption(
                f"Portfolio R5 monitoring raw-fact row field {key} differs"
            )


def _validate_query(
    *,
    policy_id: str,
    policy_version: str,
    expected_policy_hash: str,
    target_hash: str,
    calendar_id: str,
    calendar_version: str,
    expected_calendar_hash: str,
    period_ids: tuple[str, ...],
    as_of: datetime,
) -> None:
    _require_token(policy_id, "Portfolio R5 monitoring policy_id")
    _require_token(policy_version, "Portfolio R5 monitoring policy_version")
    _require_hash(expected_policy_hash, "Portfolio R5 monitoring policy hash")
    _require_hash(target_hash, "Portfolio R5 monitoring target hash")
    _require_token(calendar_id, "Portfolio R5 monitoring calendar_id")
    _require_token(calendar_version, "Portfolio R5 monitoring calendar_version")
    _require_hash(expected_calendar_hash, "Portfolio R5 monitoring calendar hash")
    _require_aware(as_of, "Portfolio R5 monitoring as_of")
    if type(period_ids) is not tuple or not period_ids or len(set(period_ids)) != len(period_ids):
        raise ValueError("Portfolio R5 monitoring period identities differ")
    for period_id in period_ids:
        _require_hash(period_id, "Portfolio R5 monitoring period_id")


def _time_text(value: datetime) -> str:
    _require_aware(value, "Portfolio R5 monitoring source time")
    return value.astimezone(UTC).isoformat(timespec="microseconds")


def _parse_time(value: object) -> datetime:
    if type(value) is not str:
        raise TypeError("Portfolio R5 monitoring source time is not a string")
    parsed = datetime.fromisoformat(value)
    _require_aware(parsed, "Portfolio R5 monitoring source time")
    return parsed


def _build_portfolio_r5_monitoring_raw_fact_store(
    *,
    using: str = "default",
    clock: PortfolioR5MonitoringRawFactClock | None = None,
) -> _DjangoPortfolioR5MonitoringRawFactStore:
    """Build the private claimed append store for canonical tests."""

    return _DjangoPortfolioR5MonitoringRawFactStore(
        token=object(),
        using=using,
        clock=clock,
    )


__all__ = [
    "DjangoPortfolioR5MonitoringRawFactClock",
    "DjangoPortfolioR5MonitoringRawFactRepository",
    "PortfolioR5MonitoringRawFactConflict",
    "PortfolioR5MonitoringRawFactCorruption",
]
