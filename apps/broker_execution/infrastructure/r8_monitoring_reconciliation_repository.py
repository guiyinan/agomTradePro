"""Exact PIT repository for Broker-owned R8 monitoring reconciliation receipts."""

from __future__ import annotations

import hashlib
from collections.abc import Iterator
from contextlib import AbstractContextManager, contextmanager
from datetime import datetime
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.db.models import Q
from django.utils import timezone

from apps.broker_execution.domain.r8_monitoring_reconciliation import (
    R8BrokerMonitoringMetricKey,
    R8BrokerMonitoringPeriodReceipt,
    R8BrokerReconciliationDefinition,
    R8BrokerReconciliationSourceReceipt,
)
from apps.broker_execution.infrastructure.r8_monitoring_reconciliation_codec import (
    R8BrokerMonitoringCodecError,
    decode_r8_broker_monitoring_period_receipt,
    decode_r8_broker_reconciliation_definition,
    decode_r8_broker_reconciliation_source_receipt,
    encode_r8_broker_monitoring_period_receipt,
    encode_r8_broker_reconciliation_definition,
    encode_r8_broker_reconciliation_source_receipt,
)
from apps.broker_execution.infrastructure.r8_monitoring_reconciliation_models import (
    R8BrokerMonitoringPeriodReceiptModel,
    _activate_r8_broker_monitoring_uow,
    _claim_r8_broker_monitoring_insert,
    _require_active_r8_broker_monitoring_uow,
)


class R8BrokerMonitoringRegistryCorruption(ValueError):
    """Persisted Broker owner headers or strict payloads disagree."""


class R8BrokerMonitoringRegistryConflict(ValueError):
    """A stable Broker owner identity already seals different evidence."""


class DjangoR8BrokerMonitoringUnitOfWork:
    """Private transaction capability for exact Broker owner appends."""

    __slots__ = ("_token", "_using")

    def __init__(self, *, using: str = "default") -> None:
        self._using = using
        self._token = object()

    @property
    def using(self) -> str:
        """Return the configured database alias."""

        return self._using

    @property
    def unit_of_work_key(self) -> str:
        """Return the stable shared transaction identity."""

        return f"django:{self._using}"

    @contextmanager
    def atomic(self) -> Iterator[None]:
        """Open an atomic block and activate the private insert capability."""

        with transaction.atomic(using=self._using):
            with _activate_r8_broker_monitoring_uow(self._token):
                yield

    def _insert_claim_token(self) -> object:
        """Return the private exact-insert token to the repository only."""

        return self._token


class DjangoR8BrokerMonitoringRegistryClock:
    """Trusted Django server clock bound to one Broker database alias."""

    __slots__ = ("_using",)

    def __init__(self, *, using: str = "default") -> None:
        self._using = using

    @property
    def unit_of_work_key(self) -> str:
        """Return the stable shared transaction identity."""

        return f"django:{self._using}"

    def now(self) -> datetime:
        """Return one timezone-aware server timestamp."""

        return timezone.now()


class DjangoR8BrokerMonitoringPeriodReceiptRepository:
    """Public read-only exact PIT receipt provider without a write token."""

    __slots__ = ("_using",)

    def __init__(self, *, using: str = "default") -> None:
        self._using = using

    @property
    def unit_of_work_key(self) -> str:
        """Return the stable shared transaction identity."""

        return f"django:{self._using}"

    def get_exact(
        self,
        *,
        receipt_id: str,
        receipt_version: str,
        expected_receipt_hash: str,
        as_of: datetime,
    ) -> R8BrokerMonitoringPeriodReceipt | None:
        """Return one exact live receipt or preserve absence as ``None``."""

        _require_token(receipt_id, "Broker receipt query receipt_id")
        _require_token(receipt_version, "Broker receipt query receipt_version")
        _require_sha256(expected_receipt_hash, "Broker receipt query hash")
        _require_aware(as_of, "Broker receipt query as_of")
        rows = tuple(
            R8BrokerMonitoringPeriodReceiptModel._default_manager.using(self._using)
            .filter(
                Q(receipt_id=receipt_id) | Q(content_hash=expected_receipt_hash),
                recorded_at__lte=as_of,
                valid_until__gt=as_of,
            )
            .order_by("recorded_at")
        )
        if not rows:
            return None
        if len(rows) != 1:
            raise R8BrokerMonitoringRegistryCorruption(
                "R8 Broker monitoring receipt identity is aliased"
            )
        receipt = _receipt_from_model(rows[0])
        if (
            receipt.receipt_id != receipt_id
            or receipt.receipt_version != receipt_version
            or receipt.content_hash != expected_receipt_hash
        ):
            raise R8BrokerMonitoringRegistryCorruption(
                "R8 Broker monitoring receipt selector was substituted"
            )
        return receipt

    def list_exact(
        self,
        *,
        result_id: str,
        result_hash: str,
        portfolio_receipt_id: str,
        portfolio_receipt_hash: str,
        calendar_id: str,
        calendar_hash: str,
        period_ids: tuple[str, ...],
        as_of: datetime,
    ) -> tuple[R8BrokerMonitoringPeriodReceipt, ...] | None:
        """Return the exact ordered complete period set or explicit absence."""

        for label, value in (
            ("result_id", result_id),
            ("portfolio_receipt_id", portfolio_receipt_id),
            ("calendar_id", calendar_id),
        ):
            _require_token(value, f"Broker receipt query {label}")
        for label, value in (
            ("result_hash", result_hash),
            ("portfolio_receipt_hash", portfolio_receipt_hash),
            ("calendar_hash", calendar_hash),
        ):
            _require_sha256(value, f"Broker receipt query {label}")
        if type(period_ids) is not tuple or not period_ids:
            raise ValueError("Broker receipt query period_ids must be a non-empty tuple")
        for period_id in period_ids:
            _require_token(period_id, "Broker receipt query period_id")
        if len(set(period_ids)) != len(period_ids):
            raise ValueError("Broker receipt query period_ids must be unique")
        _require_aware(as_of, "Broker receipt query as_of")
        target_match = (
            Q(result_id=result_id)
            | Q(result_hash=result_hash)
            | Q(portfolio_receipt_id=portfolio_receipt_id)
            | Q(portfolio_receipt_hash=portfolio_receipt_hash)
            | Q(calendar_id=calendar_id)
            | Q(calendar_hash=calendar_hash)
        )
        rows = tuple(
            R8BrokerMonitoringPeriodReceiptModel._default_manager.using(self._using)
            .filter(
                target_match,
                period_id__in=period_ids,
                recorded_at__lte=as_of,
                valid_until__gt=as_of,
            )
            .order_by("period_end_at", "receipt_id")
        )
        if not rows:
            return None
        receipts = tuple(_receipt_from_model(row) for row in rows)
        by_period = {item.definition.period_id: item for item in receipts}
        if len(by_period) != len(receipts):
            raise R8BrokerMonitoringRegistryCorruption(
                "R8 Broker monitoring period identity is aliased"
            )
        if any(
            item.definition.result_id != result_id
            or item.definition.result_hash != result_hash
            or item.definition.portfolio_receipt_id != portfolio_receipt_id
            or item.definition.portfolio_receipt_hash != portfolio_receipt_hash
            or item.definition.calendar_id != calendar_id
            or item.definition.calendar_hash != calendar_hash
            for item in receipts
        ):
            raise R8BrokerMonitoringRegistryCorruption(
                "R8 Broker monitoring target selector was substituted"
            )
        if set(by_period) != set(period_ids):
            return None
        return tuple(by_period[period_id] for period_id in period_ids)


class _DjangoR8BrokerMonitoringPeriodStore(DjangoR8BrokerMonitoringPeriodReceiptRepository):
    """Private claimed-append surface used only by test owner composition."""

    __slots__ = ("_uow",)

    def __init__(self, *, unit_of_work: DjangoR8BrokerMonitoringUnitOfWork) -> None:
        super().__init__(using=unit_of_work.using)
        self._uow = unit_of_work

    @property
    def unit_of_work_key(self) -> str:
        """Return the private owner transaction identity."""

        return self._uow.unit_of_work_key

    def atomic(self) -> AbstractContextManager[None]:
        """Open one token-activated Broker owner transaction."""

        return self._uow.atomic()

    def append(
        self,
        receipt: R8BrokerMonitoringPeriodReceipt,
        *,
        definition: R8BrokerReconciliationDefinition,
        source_receipt: R8BrokerReconciliationSourceReceipt,
    ) -> R8BrokerMonitoringPeriodReceipt:
        """Append one fully replayable receipt or return its exact winner."""

        _require_active_r8_broker_monitoring_uow()
        try:
            exact_receipt = receipt.validated_copy()
            exact_definition = definition.validated_copy()
            exact_source = source_receipt.validated_copy()
            if (
                exact_receipt.definition != exact_definition
                or exact_receipt.source_receipt != exact_source
            ):
                raise ValueError("Broker monitoring owner graph differs")
        except (AttributeError, TypeError, ValueError) as error:
            raise R8BrokerMonitoringRegistryCorruption(
                "R8 Broker monitoring owner graph is invalid"
            ) from error
        winner = self._find_collision(
            exact_receipt,
            exact_definition,
            exact_source,
            lock=True,
        )
        if winner is not None:
            return self._match_winner(
                winner,
                exact_receipt,
                exact_definition,
                exact_source,
            )
        values = _receipt_model_values(exact_receipt, exact_definition, exact_source)
        try:
            with transaction.atomic(using=self._uow.using):
                model = R8BrokerMonitoringPeriodReceiptModel(**values)
                model.full_clean()
                with _claim_r8_broker_monitoring_insert(
                    token=self._uow._insert_claim_token(),
                    model_type=R8BrokerMonitoringPeriodReceiptModel,
                    expected_values=values,
                ):
                    model.save(force_insert=True, using=self._uow.using)
        except (IntegrityError, ValidationError) as error:
            winner = self._find_collision(
                exact_receipt,
                exact_definition,
                exact_source,
                lock=True,
            )
            if winner is None:
                raise R8BrokerMonitoringRegistryConflict(
                    "R8 Broker monitoring append has no exact winner"
                ) from error
            return self._match_winner(
                winner,
                exact_receipt,
                exact_definition,
                exact_source,
            )
        return _receipt_from_model(model)

    def _find_collision(
        self,
        receipt: R8BrokerMonitoringPeriodReceipt,
        definition: R8BrokerReconciliationDefinition,
        source: R8BrokerReconciliationSourceReceipt,
        *,
        lock: bool,
    ) -> R8BrokerMonitoringPeriodReceiptModel | None:
        queryset = R8BrokerMonitoringPeriodReceiptModel._default_manager.using(self._uow.using)
        if lock:
            queryset = queryset.select_for_update()
        rows = tuple(
            queryset.filter(
                Q(receipt_id=receipt.receipt_id)
                | Q(content_hash=receipt.content_hash)
                | Q(
                    definition_id=definition.definition_id,
                    definition_version=definition.definition_version,
                )
                | Q(definition_hash=definition.content_hash)
                | Q(
                    source_receipt_id=source.source_receipt_id,
                    source_receipt_version=source.source_receipt_version,
                )
                | Q(source_receipt_hash=source.content_hash)
                | Q(
                    result_id=definition.result_id,
                    calendar_id=definition.calendar_id,
                    period_id=definition.period_id,
                )
            )
        )
        if not rows:
            return None
        if len(rows) != 1:
            raise R8BrokerMonitoringRegistryConflict(
                "R8 Broker monitoring has multiple collision candidates"
            )
        return rows[0]

    @staticmethod
    def _match_winner(
        model: R8BrokerMonitoringPeriodReceiptModel,
        receipt: R8BrokerMonitoringPeriodReceipt,
        definition: R8BrokerReconciliationDefinition,
        source: R8BrokerReconciliationSourceReceipt,
    ) -> R8BrokerMonitoringPeriodReceipt:
        restored, restored_definition, restored_source = _owner_graph_from_model(model)
        if restored != receipt or restored_definition != definition or restored_source != source:
            raise R8BrokerMonitoringRegistryConflict(
                "R8 Broker monitoring identity forks to different evidence"
            )
        return restored


def _build_r8_broker_monitoring_period_store(
    *, using: str = "default"
) -> _DjangoR8BrokerMonitoringPeriodStore:
    """Build the private claimed-append store for test owner composition."""

    return _DjangoR8BrokerMonitoringPeriodStore(
        unit_of_work=DjangoR8BrokerMonitoringUnitOfWork(using=using)
    )


def _receipt_from_model(
    model: R8BrokerMonitoringPeriodReceiptModel,
) -> R8BrokerMonitoringPeriodReceipt:
    receipt, _, _ = _owner_graph_from_model(model)
    return receipt


def _owner_graph_from_model(
    model: R8BrokerMonitoringPeriodReceiptModel,
) -> tuple[
    R8BrokerMonitoringPeriodReceipt,
    R8BrokerReconciliationDefinition,
    R8BrokerReconciliationSourceReceipt,
]:
    try:
        definition = decode_r8_broker_reconciliation_definition(model.definition_payload)
        source = decode_r8_broker_reconciliation_source_receipt(model.source_receipt_payload)
        receipt = decode_r8_broker_monitoring_period_receipt(model.canonical_payload)
    except (R8BrokerMonitoringCodecError, TypeError, ValueError) as error:
        raise R8BrokerMonitoringRegistryCorruption(
            "R8 Broker monitoring payload cannot be restored"
        ) from error
    if receipt.definition != definition or receipt.source_receipt != source:
        raise R8BrokerMonitoringRegistryCorruption(
            "R8 Broker monitoring nested owner graph differs"
        )
    values = _receipt_model_values(receipt, definition, source)
    actual = {name: getattr(model, name) for name in values}
    if actual != values:
        raise R8BrokerMonitoringRegistryCorruption(
            "R8 Broker monitoring headers differ from strict payloads"
        )
    return receipt, definition, source


def _receipt_model_values(
    receipt: R8BrokerMonitoringPeriodReceipt,
    definition: R8BrokerReconciliationDefinition,
    source: R8BrokerReconciliationSourceReceipt,
) -> dict[str, object]:
    facts = {item.metric_key: item for item in definition.metric_facts}
    cost = facts[R8BrokerMonitoringMetricKey.TOTAL_COST_RATE]
    slippage = facts[R8BrokerMonitoringMetricKey.ADVERSE_SLIPPAGE_RATE]
    reconciliation = facts[R8BrokerMonitoringMetricKey.RECONCILIATION_BREAK_RATE]
    values: dict[str, object] = {
        "receipt_id": receipt.receipt_id,
        "receipt_version": receipt.receipt_version,
        "definition_id": definition.definition_id,
        "definition_version": definition.definition_version,
        "definition_hash": definition.content_hash,
        "definition_payload": encode_r8_broker_reconciliation_definition(definition),
        "source_receipt_id": source.source_receipt_id,
        "source_receipt_version": source.source_receipt_version,
        "source_receipt_hash": source.content_hash,
        "source_receipt_payload": encode_r8_broker_reconciliation_source_receipt(source),
        "result_id": definition.result_id,
        "result_hash": definition.result_hash,
        "portfolio_receipt_id": definition.portfolio_receipt_id,
        "portfolio_receipt_version": definition.portfolio_receipt_version,
        "portfolio_receipt_hash": definition.portfolio_receipt_hash,
        "calendar_id": definition.calendar_id,
        "calendar_version": definition.calendar_version,
        "calendar_hash": definition.calendar_hash,
        "period_id": definition.period_id,
        "period_start_at": definition.period_start_at,
        "period_end_at": definition.period_end_at,
        "planning_reference_id": definition.planning_reference_id,
        "planning_reference_version": definition.planning_reference_version,
        "planning_reference_hash": definition.planning_reference_hash,
        "reconciliation_manifest_id": definition.reconciliation_manifest_id,
        "reconciliation_manifest_version": definition.reconciliation_manifest_version,
        "reconciliation_manifest_hash": definition.reconciliation_manifest_hash,
        "source_observed_at": definition.observed_at,
        "source_available_at": definition.available_at,
        "recorded_at": receipt.recorded_at,
        "valid_until": receipt.valid_until,
        "total_cost_amount": cost.numerator,
        "total_cost_notional": cost.denominator,
        "adverse_slippage_amount": slippage.numerator,
        "adverse_slippage_notional": slippage.denominator,
        "reconciliation_break_count": int(reconciliation.numerator),
        "reconciliation_comparison_count": int(reconciliation.denominator),
        "canonical_payload": encode_r8_broker_monitoring_period_receipt(receipt),
        "content_hash": receipt.content_hash,
        "research_only": True,
        "must_not_use_for_decision": True,
        "must_not_publish_current": True,
        "must_not_execute": True,
    }
    values["ledger_header_hash"] = _ledger_header_hash(values)
    return values


def _ledger_header_hash(values: dict[str, object]) -> str:
    digest = hashlib.sha256()
    for key in sorted(item for item in values if not item.endswith("_payload")):
        value = values[key]
        if isinstance(value, datetime):
            text = value.isoformat(timespec="microseconds")
        elif isinstance(value, Decimal):
            text = format(value.normalize(), "f")
        else:
            text = str(value)
        encoded = f"{key}={text}".encode()
        digest.update(len(encoded).to_bytes(8, "big"))
        digest.update(encoded)
    return digest.hexdigest()


def _require_token(value: object, label: str) -> None:
    if type(value) is not str or not value.strip():
        raise ValueError(f"{label} must be a non-empty exact string")


def _require_sha256(value: object, label: str) -> None:
    if (
        type(value) is not str
        or len(value) != 64
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise ValueError(f"{label} must be a lowercase SHA-256 digest")


def _require_aware(value: datetime, label: str) -> None:
    if type(value) is not datetime or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{label} must be a timezone-aware datetime")


__all__ = [
    "DjangoR8BrokerMonitoringPeriodReceiptRepository",
    "R8BrokerMonitoringRegistryConflict",
    "R8BrokerMonitoringRegistryCorruption",
]
