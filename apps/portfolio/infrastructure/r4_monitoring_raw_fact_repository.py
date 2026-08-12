"""Append-only Portfolio repository for R4 monitoring raw-fact receipts."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from datetime import UTC, datetime
from enum import Enum

from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.utils import timezone

from apps.portfolio.domain.r4_monitoring_raw_fact_receipt import (
    PortfolioR4MonitoringRawFactReceipt,
    PortfolioR4MonitoringRawFactSourceReceipt,
    R4MonitoringRawFactDefinition,
)
from apps.portfolio.infrastructure.optimization_research_models import (
    _activate_governed_optimization_uow,
    _claim_governed_optimization_insert,
)
from apps.portfolio.infrastructure.r4_monitoring_raw_fact_codec import (
    decode_portfolio_r4_monitoring_raw_fact,
    encode_portfolio_r4_monitoring_raw_fact,
)
from apps.portfolio.infrastructure.r4_monitoring_raw_fact_models import (
    PortfolioR4MonitoringRawFactReceiptModel,
)


class PortfolioR4MonitoringRawFactConflict(RuntimeError):
    """One immutable Portfolio raw-fact identity forked."""


class PortfolioR4MonitoringRawFactCorruption(RuntimeError):
    """A stored Portfolio raw-fact seal was substituted."""


class DjangoPortfolioR4MonitoringRawFactClock:
    """Django-aware Portfolio owner receipt clock."""

    def __init__(self, *, using: str = "default") -> None:
        self._using = using

    @property
    def unit_of_work_key(self) -> str:
        """Return the database transaction identity shared by owner inputs."""

        return f"django:{self._using}"

    def now(self) -> datetime:
        """Return the current timezone-aware server timestamp."""

        return timezone.now()


def _time_text(value: datetime) -> str:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("raw-fact ledger datetime must be timezone-aware")
    return value.astimezone(UTC).isoformat(timespec="microseconds")


def _ledger_value(value: object) -> object:
    if isinstance(value, datetime):
        return _time_text(value)
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, Mapping):
        return {str(key): _ledger_value(item) for key, item in sorted(value.items())}
    if isinstance(value, (tuple, list)):
        return [_ledger_value(item) for item in value]
    if isinstance(value, (str, int, bool)) or value is None:
        return value
    raise TypeError(f"unsupported Portfolio raw ledger value: {type(value).__name__}")


def _header_hash(values: Mapping[str, object]) -> str:
    payload = {
        "schema": "portfolio-r4-monitoring-raw-fact-ledger-header.v1",
        "values": _ledger_value(values),
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _source_payload(source: PortfolioR4MonitoringRawFactSourceReceipt) -> dict[str, object]:
    return {
        "source_owner": source.source_owner,
        "source_receipt_id": source.source_receipt_id,
        "source_receipt_version": source.source_receipt_version,
        "definition_hash": source.definition_hash,
        "available_at": _time_text(source.available_at),
        "valid_until": _time_text(source.valid_until),
        "content_hash": source.content_hash,
    }


def _restore_source(payload: object) -> PortfolioR4MonitoringRawFactSourceReceipt:
    required = {
        "source_owner",
        "source_receipt_id",
        "source_receipt_version",
        "definition_hash",
        "available_at",
        "valid_until",
        "content_hash",
    }
    if not isinstance(payload, dict) or set(payload) != required:
        raise PortfolioR4MonitoringRawFactCorruption("raw source payload shape changed")
    try:
        return PortfolioR4MonitoringRawFactSourceReceipt(
            source_owner=str(payload["source_owner"]),
            source_receipt_id=str(payload["source_receipt_id"]),
            source_receipt_version=str(payload["source_receipt_version"]),
            definition_hash=str(payload["definition_hash"]),
            available_at=datetime.fromisoformat(str(payload["available_at"])),
            valid_until=datetime.fromisoformat(str(payload["valid_until"])),
            content_hash=str(payload["content_hash"]),
        )
    except (TypeError, ValueError) as error:
        raise PortfolioR4MonitoringRawFactCorruption("raw source payload invalid") from error


class DjangoPortfolioR4MonitoringRawFactRepository:
    """Exact read-only Portfolio raw-fact owner repository."""

    def __init__(self, *, using: str = "default") -> None:
        self._using = using

    @property
    def unit_of_work_key(self) -> str:
        return f"django:{self._using}"

    @contextmanager
    def atomic(self) -> Iterator[None]:
        """Open one read-only Portfolio database transaction."""

        with transaction.atomic(using=self._using):
            yield

    def list_exact(
        self,
        *,
        active_decision_id: str,
        active_decision_version: str,
        active_decision_hash: str,
        policy_id: str,
        policy_version: str,
        policy_hash: str,
        calendar_id: str,
        calendar_version: str,
        calendar_hash: str,
        as_of: datetime,
    ) -> tuple[PortfolioR4MonitoringRawFactReceipt, ...]:
        """Return only exact owner facts known and valid at the PIT cutoff."""

        with self.atomic():
            rows = tuple(
                PortfolioR4MonitoringRawFactReceiptModel._default_manager.using(self._using)
                .filter(
                    active_decision_id=active_decision_id,
                    active_decision_version=active_decision_version,
                    active_decision_hash__iexact=active_decision_hash,
                    policy_id=policy_id,
                    policy_version=policy_version,
                    policy_hash__iexact=policy_hash,
                    calendar_id=calendar_id,
                    calendar_version=calendar_version,
                    calendar_hash__iexact=calendar_hash,
                    owner_recorded_at__lte=as_of,
                    valid_until__gt=as_of,
                )
                .order_by("observed_at", "observation_id")
            )
            return tuple(self._restore(row) for row in rows)

    def _restore(
        self, row: PortfolioR4MonitoringRawFactReceiptModel
    ) -> PortfolioR4MonitoringRawFactReceipt:
        try:
            receipt = decode_portfolio_r4_monitoring_raw_fact(row.canonical_payload)
            definition = _definition_from_receipt(receipt)
            source = _restore_source(row.source_receipt_payload)
            values = _model_values(receipt, definition.content_hash, source)
            if any(getattr(row, key) != expected for key, expected in values.items()):
                raise ValueError("raw-fact ledger columns changed")
            if row.ledger_header_hash.lower() != _header_hash(values):
                raise ValueError("raw-fact ledger header changed")
            return receipt
        except (TypeError, ValueError) as error:
            raise PortfolioR4MonitoringRawFactCorruption(
                "Portfolio R4 raw-fact receipt is corrupted"
            ) from error


class _DjangoPortfolioR4MonitoringRawFactStore(DjangoPortfolioR4MonitoringRawFactRepository):
    """Private claimed append capability retained only by composition."""

    def __init__(self, *, using: str = "default") -> None:
        super().__init__(using=using)
        self._token = object()

    @contextmanager
    def atomic(self) -> Iterator[None]:
        """Open one claimed Portfolio owner-registration transaction."""

        with (
            transaction.atomic(using=self._using),
            _activate_governed_optimization_uow(self._token),
        ):
            yield

    def append(
        self,
        receipt: PortfolioR4MonitoringRawFactReceipt,
        *,
        definition_hash: str,
        source_receipt: PortfolioR4MonitoringRawFactSourceReceipt,
    ) -> PortfolioR4MonitoringRawFactReceipt:
        """Append idempotently or reject a same-identity/period fork."""

        values = _model_values(receipt, definition_hash, source_receipt)
        existing = (
            PortfolioR4MonitoringRawFactReceiptModel._default_manager.using(self._using)
            .filter(
                observation_id=receipt.observation_id,
                observation_version=receipt.observation_version,
            )
            .first()
        )
        if existing is not None:
            restored = self._restore(existing)
            if restored != receipt:
                raise PortfolioR4MonitoringRawFactConflict("raw-fact identity fork")
            return restored
        model_values = {**values, "ledger_header_hash": _header_hash(values)}
        model = PortfolioR4MonitoringRawFactReceiptModel(**model_values)
        try:
            model.full_clean()
            with _claim_governed_optimization_insert(
                token=self._token,
                model_type=PortfolioR4MonitoringRawFactReceiptModel,
                expected_values=model_values,
            ):
                model.save(force_insert=True, using=self._using)
        except (IntegrityError, ValidationError) as error:
            winner = (
                PortfolioR4MonitoringRawFactReceiptModel._default_manager.using(self._using)
                .filter(
                    observation_id=receipt.observation_id,
                    observation_version=receipt.observation_version,
                )
                .first()
            )
            if winner is None or self._restore(winner) != receipt:
                raise PortfolioR4MonitoringRawFactConflict("raw-fact append conflict") from error
        return receipt


def _definition_from_receipt(
    receipt: PortfolioR4MonitoringRawFactReceipt,
) -> R4MonitoringRawFactDefinition:
    return R4MonitoringRawFactDefinition(
        observation_id=receipt.observation_id,
        observation_version=receipt.observation_version,
        period_id=receipt.period_id,
        calendar_id=receipt.calendar_id,
        calendar_version=receipt.calendar_version,
        calendar_hash=receipt.calendar_hash,
        period_start=receipt.period_start,
        period_end=receipt.period_end,
        active_decision_id=receipt.active_decision_id,
        active_decision_version=receipt.active_decision_version,
        active_decision_hash=receipt.active_decision_hash,
        policy_id=receipt.policy_id,
        policy_version=receipt.policy_version,
        policy_hash=receipt.policy_hash,
        portfolio_record_id=receipt.portfolio_record_id,
        portfolio_record_hash=receipt.portfolio_record_hash,
        portfolio_record_content_hash=receipt.portfolio_record_content_hash,
        r3_attestation_content_hash=receipt.r3_attestation_content_hash,
        observed_at=receipt.observed_at,
        available_at=receipt.available_at,
        valid_until=receipt.valid_until,
        pit_manifest_id=receipt.pit_manifest_id,
        pit_manifest_hash=receipt.pit_manifest_hash,
        evidence_ref=receipt.evidence_ref,
        label_protocol_version=receipt.label_protocol_version,
        observed_label_set_hash=receipt.observed_label_set_hash,
        observed_data_schema_hash=receipt.observed_data_schema_hash,
        metrics=receipt.metrics,
    )


def _model_values(
    receipt: PortfolioR4MonitoringRawFactReceipt,
    definition_hash: str,
    source: PortfolioR4MonitoringRawFactSourceReceipt,
) -> dict[str, object]:
    return {
        "observation_id": receipt.observation_id,
        "observation_version": receipt.observation_version,
        "active_decision_id": receipt.active_decision_id,
        "active_decision_version": receipt.active_decision_version,
        "active_decision_hash": receipt.active_decision_hash,
        "policy_id": receipt.policy_id,
        "policy_version": receipt.policy_version,
        "policy_hash": receipt.policy_hash,
        "calendar_id": receipt.calendar_id,
        "calendar_version": receipt.calendar_version,
        "calendar_hash": receipt.calendar_hash,
        "period_id": receipt.period_id,
        "source_owner": receipt.owner,
        "definition_hash": definition_hash,
        "source_receipt_id": source.source_receipt_id,
        "source_receipt_version": source.source_receipt_version,
        "source_receipt_hash": source.content_hash,
        "source_receipt_payload": _source_payload(source),
        "observed_at": receipt.observed_at,
        "available_at": receipt.available_at,
        "owner_recorded_at": receipt.owner_recorded_at,
        "valid_until": receipt.valid_until,
        "canonical_payload": encode_portfolio_r4_monitoring_raw_fact(receipt),
        "content_hash": receipt.content_hash,
        "research_only": True,
        "must_not_use_for_decision": True,
        "must_not_publish_current": True,
        "must_not_execute": True,
    }


def _build_portfolio_r4_monitoring_raw_fact_store(
    *, using: str = "default"
) -> _DjangoPortfolioR4MonitoringRawFactStore:
    """Return the private claimed store for composition/tests only."""

    return _DjangoPortfolioR4MonitoringRawFactStore(using=using)


__all__ = [
    "DjangoPortfolioR4MonitoringRawFactClock",
    "DjangoPortfolioR4MonitoringRawFactRepository",
]
