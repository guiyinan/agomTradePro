"""Canonical Research owner repository for R4 monitoring policy/calendar."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from datetime import UTC, datetime
from decimal import Decimal
from enum import Enum

from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.utils import timezone

from apps.research.domain.r4_promotion_lifecycle import R4PromotionDecisionIdentity
from apps.research.domain.r4_promotion_monitoring import (
    R4MonitoringPeriodCalendar,
    R4MonitoringPolicy,
)
from apps.research.domain.r4_promotion_monitoring_owner_registry import (
    R4MonitoringCalendarDefinition,
    R4MonitoringOwnerRecordKind,
    R4MonitoringOwnerSourceReceipt,
    R4MonitoringPolicyDefinition,
)
from apps.research.infrastructure.r4_promotion_monitoring_codec import (
    decode_r4_monitoring_period_calendar,
    decode_r4_monitoring_policy,
    encode_r4_monitoring_period_calendar,
    encode_r4_monitoring_policy,
)
from apps.research.infrastructure.r4_promotion_monitoring_models import (
    _activate_r4_monitoring_uow,
    _claim_r4_monitoring_insert,
)
from apps.research.infrastructure.r4_promotion_monitoring_owner_models import (
    R4MonitoringCalendarLedgerModel,
    R4MonitoringPolicyLedgerModel,
)


class R4MonitoringOwnerRepositoryConflict(RuntimeError):
    """One immutable owner identity collided with different evidence."""


class R4MonitoringOwnerRepositoryCorruption(RuntimeError):
    """A stored header, payload, definition, or source seal was substituted."""


class DjangoR4MonitoringOwnerClock:
    """Django-aware server clock for canonical Research owner receipts."""

    def __init__(self, *, using: str = "default") -> None:
        self._using = using

    @property
    def unit_of_work_key(self) -> str:
        """Return the database transaction identity shared by owner inputs."""

        return f"django:{self._using}"

    def now(self) -> datetime:
        """Return the current timezone-aware timestamp."""

        return timezone.now()


def _utc_text(value: datetime) -> str:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("ledger datetime must be timezone-aware")
    return value.astimezone(UTC).isoformat(timespec="microseconds")


def _ledger_value(value: object) -> object:
    if isinstance(value, datetime):
        return _utc_text(value)
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
    raise TypeError(f"unsupported owner ledger value: {type(value).__name__}")


def _header_hash(row_kind: str, values: Mapping[str, object]) -> str:
    payload = {
        "schema": "research-r4-monitoring-owner-ledger-header.v1",
        "row_kind": row_kind,
        "values": _ledger_value(values),
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _source_payload(source: R4MonitoringOwnerSourceReceipt) -> dict[str, object]:
    return {
        "record_kind": source.record_kind.value,
        "source_owner": source.source_owner,
        "source_receipt_id": source.source_receipt_id,
        "source_receipt_version": source.source_receipt_version,
        "definition_hash": source.definition_hash,
        "available_at": _utc_text(source.available_at),
        "valid_until": _utc_text(source.valid_until),
        "content_hash": source.content_hash,
    }


def _restore_source(payload: object) -> R4MonitoringOwnerSourceReceipt:
    if not isinstance(payload, dict) or set(payload) != {
        "record_kind",
        "source_owner",
        "source_receipt_id",
        "source_receipt_version",
        "definition_hash",
        "available_at",
        "valid_until",
        "content_hash",
    }:
        raise R4MonitoringOwnerRepositoryCorruption("owner source payload shape changed")
    try:
        return R4MonitoringOwnerSourceReceipt(
            record_kind=R4MonitoringOwnerRecordKind(str(payload["record_kind"])),
            source_owner=str(payload["source_owner"]),
            source_receipt_id=str(payload["source_receipt_id"]),
            source_receipt_version=str(payload["source_receipt_version"]),
            definition_hash=str(payload["definition_hash"]),
            available_at=datetime.fromisoformat(str(payload["available_at"])),
            valid_until=datetime.fromisoformat(str(payload["valid_until"])),
            content_hash=str(payload["content_hash"]),
        )
    except (TypeError, ValueError) as error:
        raise R4MonitoringOwnerRepositoryCorruption("owner source payload is invalid") from error


class DjangoR4MonitoringOwnerRegistryRepository:
    """Read exact policy/calendar records with full live seal verification."""

    def __init__(self, *, using: str = "default") -> None:
        self._using = using

    @property
    def unit_of_work_key(self) -> str:
        """Return the database transaction identity shared by all owner adapters."""

        return f"django:{self._using}"

    @contextmanager
    def atomic(self) -> Iterator[None]:
        """Open one read-only Research database transaction context."""

        with transaction.atomic(using=self._using):
            yield

    def get_exact_policy(
        self,
        *,
        policy_id: str,
        policy_version: str,
        expected_policy_hash: str,
        as_of: datetime,
    ) -> R4MonitoringPolicy | None:
        """Return one exact PIT-active policy or explicit absence."""

        with self.atomic():
            row = (
                R4MonitoringPolicyLedgerModel._default_manager.using(self._using)
                .filter(
                    policy_id=policy_id,
                    policy_version=policy_version,
                    content_hash__iexact=expected_policy_hash,
                    recorded_at__lte=as_of,
                    active_from__lte=as_of,
                    active_until__gt=as_of,
                )
                .first()
            )
            return None if row is None else self._restore_policy(row)

    def get_exact_calendar(
        self,
        *,
        source_owner: str,
        calendar_id: str,
        calendar_version: str,
        expected_calendar_hash: str,
        as_of: datetime,
    ) -> R4MonitoringPeriodCalendar | None:
        """Return one exact PIT-active calendar or explicit absence."""

        with self.atomic():
            row = (
                R4MonitoringCalendarLedgerModel._default_manager.using(self._using)
                .filter(
                    source_owner=source_owner,
                    calendar_id=calendar_id,
                    calendar_version=calendar_version,
                    content_hash__iexact=expected_calendar_hash,
                    recorded_at__lte=as_of,
                    valid_from__lte=as_of,
                    valid_until__gt=as_of,
                )
                .first()
            )
            return None if row is None else self._restore_calendar(row)

    def _restore_policy(self, row: R4MonitoringPolicyLedgerModel) -> R4MonitoringPolicy:
        try:
            policy = decode_r4_monitoring_policy(row.canonical_payload)
            source = _restore_source(row.source_receipt_payload)
            definition = R4MonitoringPolicyDefinition.from_policy(policy)
            values = _policy_values(policy, definition.content_hash, source)
            _require_row_values(row, values, "policy")
            if row.ledger_header_hash.lower() != _header_hash("policy", values):
                raise ValueError("policy ledger header mismatch")
            return policy
        except (TypeError, ValueError) as error:
            raise R4MonitoringOwnerRepositoryCorruption(
                "canonical R4 monitoring policy is corrupted"
            ) from error

    def _restore_calendar(self, row: R4MonitoringCalendarLedgerModel) -> R4MonitoringPeriodCalendar:
        try:
            calendar = decode_r4_monitoring_period_calendar(row.canonical_payload)
            source = _restore_source(row.source_receipt_payload)
            definition = R4MonitoringCalendarDefinition.from_calendar(calendar)
            values = _calendar_values(calendar, definition.content_hash, source)
            _require_row_values(row, values, "calendar")
            if row.ledger_header_hash.lower() != _header_hash("calendar", values):
                raise ValueError("calendar ledger header mismatch")
            return calendar
        except (TypeError, ValueError) as error:
            raise R4MonitoringOwnerRepositoryCorruption(
                "canonical R4 monitoring calendar is corrupted"
            ) from error


class _DjangoR4MonitoringOwnerRegistryStore(DjangoR4MonitoringOwnerRegistryRepository):
    """Private claimed append capability retained only by composition."""

    def __init__(self, *, using: str = "default") -> None:
        super().__init__(using=using)
        self._token = object()

    @contextmanager
    def atomic(self) -> Iterator[None]:
        """Open one claimed Research owner-registration transaction."""

        with transaction.atomic(using=self._using), _activate_r4_monitoring_uow(self._token):
            yield

    def append_policy(
        self,
        policy: R4MonitoringPolicy,
        *,
        definition_hash: str,
        source_receipt: R4MonitoringOwnerSourceReceipt,
    ) -> R4MonitoringPolicy:
        """Append idempotently or reject a same-identity fork."""

        values = _policy_values(policy, definition_hash, source_receipt)
        return self._append_policy_values(policy, values)

    def _append_policy_values(
        self, policy: R4MonitoringPolicy, values: dict[str, object]
    ) -> R4MonitoringPolicy:
        existing = (
            R4MonitoringPolicyLedgerModel._default_manager.using(self._using)
            .filter(policy_id=policy.policy_id, policy_version=policy.policy_version)
            .first()
        )
        if existing is not None:
            restored = self._restore_policy(existing)
            if restored != policy:
                raise R4MonitoringOwnerRepositoryConflict("policy identity fork")
            return restored
        model_values = {**values, "ledger_header_hash": _header_hash("policy", values)}
        model = R4MonitoringPolicyLedgerModel(**model_values)
        try:
            model.full_clean()
            with _claim_r4_monitoring_insert(
                token=self._token,
                model_type=R4MonitoringPolicyLedgerModel,
                expected_values=model_values,
            ):
                model.save(force_insert=True, using=self._using)
        except (IntegrityError, ValidationError) as error:
            winner = (
                R4MonitoringPolicyLedgerModel._default_manager.using(self._using)
                .filter(policy_id=policy.policy_id, policy_version=policy.policy_version)
                .first()
            )
            if winner is None or self._restore_policy(winner) != policy:
                raise R4MonitoringOwnerRepositoryConflict("policy append conflict") from error
        return policy

    def append_calendar(
        self,
        calendar: R4MonitoringPeriodCalendar,
        *,
        definition_hash: str,
        source_receipt: R4MonitoringOwnerSourceReceipt,
    ) -> R4MonitoringPeriodCalendar:
        """Append idempotently or reject a same-identity fork."""

        values = _calendar_values(calendar, definition_hash, source_receipt)
        existing = (
            R4MonitoringCalendarLedgerModel._default_manager.using(self._using)
            .filter(
                source_owner=calendar.source_owner,
                calendar_id=calendar.calendar_id,
                calendar_version=calendar.calendar_version,
            )
            .first()
        )
        if existing is not None:
            restored = self._restore_calendar(existing)
            if restored != calendar:
                raise R4MonitoringOwnerRepositoryConflict("calendar identity fork")
            return restored
        model_values = {**values, "ledger_header_hash": _header_hash("calendar", values)}
        model = R4MonitoringCalendarLedgerModel(**model_values)
        try:
            model.full_clean()
            with _claim_r4_monitoring_insert(
                token=self._token,
                model_type=R4MonitoringCalendarLedgerModel,
                expected_values=model_values,
            ):
                model.save(force_insert=True, using=self._using)
        except (IntegrityError, ValidationError) as error:
            winner = (
                R4MonitoringCalendarLedgerModel._default_manager.using(self._using)
                .filter(
                    source_owner=calendar.source_owner,
                    calendar_id=calendar.calendar_id,
                    calendar_version=calendar.calendar_version,
                )
                .first()
            )
            if winner is None or self._restore_calendar(winner) != calendar:
                raise R4MonitoringOwnerRepositoryConflict("calendar append conflict") from error
        return calendar


class DjangoR4MonitoringPolicyProvider:
    """Application exact-read adapter for the Research policy owner ledger."""

    def __init__(self, repository: DjangoR4MonitoringOwnerRegistryRepository) -> None:
        self._repository = repository

    @property
    def unit_of_work_key(self) -> str:
        return self._repository.unit_of_work_key

    def get_exact(
        self,
        *,
        policy_id: str,
        policy_version: str,
        expected_policy_hash: str,
        active_decision: R4PromotionDecisionIdentity,
        as_of: datetime,
    ) -> R4MonitoringPolicy | None:
        policy = self._repository.get_exact_policy(
            policy_id=policy_id,
            policy_version=policy_version,
            expected_policy_hash=expected_policy_hash,
            as_of=as_of,
        )
        return policy if policy is not None and policy.active_decision == active_decision else None


class DjangoR4MonitoringCalendarProvider:
    """Application exact-read adapter for the Research calendar owner ledger."""

    def __init__(self, repository: DjangoR4MonitoringOwnerRegistryRepository) -> None:
        self._repository = repository

    @property
    def unit_of_work_key(self) -> str:
        return self._repository.unit_of_work_key

    def get_exact(
        self,
        *,
        source_owner: str,
        calendar_id: str,
        calendar_version: str,
        expected_calendar_hash: str,
        as_of: datetime,
    ) -> R4MonitoringPeriodCalendar | None:
        return self._repository.get_exact_calendar(
            source_owner=source_owner,
            calendar_id=calendar_id,
            calendar_version=calendar_version,
            expected_calendar_hash=expected_calendar_hash,
            as_of=as_of,
        )


def _policy_values(
    policy: R4MonitoringPolicy,
    definition_hash: str,
    source: R4MonitoringOwnerSourceReceipt,
) -> dict[str, object]:
    return {
        "policy_id": policy.policy_id,
        "policy_version": policy.policy_version,
        "active_decision_id": policy.active_decision.decision_id,
        "active_decision_version": policy.active_decision.decision_version,
        "active_decision_hash": policy.active_decision.content_hash,
        "definition_hash": definition_hash,
        "source_receipt_id": source.source_receipt_id,
        "source_receipt_version": source.source_receipt_version,
        "source_receipt_hash": source.content_hash,
        "source_receipt_payload": _source_payload(source),
        "recorded_at": policy.recorded_at,
        "active_from": policy.active_from,
        "active_until": policy.active_until,
        "canonical_payload": encode_r4_monitoring_policy(policy),
        "content_hash": policy.content_hash,
        "research_only": True,
        "must_not_use_for_decision": True,
        "must_not_publish_current": True,
        "must_not_execute": True,
    }


def _calendar_values(
    calendar: R4MonitoringPeriodCalendar,
    definition_hash: str,
    source: R4MonitoringOwnerSourceReceipt,
) -> dict[str, object]:
    return {
        "source_owner": calendar.source_owner,
        "calendar_id": calendar.calendar_id,
        "calendar_version": calendar.calendar_version,
        "definition_hash": definition_hash,
        "source_receipt_id": source.source_receipt_id,
        "source_receipt_version": source.source_receipt_version,
        "source_receipt_hash": source.content_hash,
        "source_receipt_payload": _source_payload(source),
        "recorded_at": calendar.recorded_at,
        "valid_from": calendar.valid_from,
        "valid_until": calendar.valid_until,
        "entry_count": len(calendar.entries),
        "canonical_payload": encode_r4_monitoring_period_calendar(calendar),
        "content_hash": calendar.content_hash,
        "research_only": True,
        "must_not_use_for_decision": True,
        "must_not_publish_current": True,
        "must_not_execute": True,
    }


def _require_row_values(row: object, values: Mapping[str, object], label: str) -> None:
    if any(getattr(row, name) != expected for name, expected in values.items()):
        raise ValueError(f"{label} owner ledger columns differ from canonical payload")


def _build_r4_monitoring_owner_store(
    *, using: str = "default"
) -> _DjangoR4MonitoringOwnerRegistryStore:
    """Return the private claimed store for composition/test assembly only."""

    return _DjangoR4MonitoringOwnerRegistryStore(using=using)


__all__ = [
    "DjangoR4MonitoringCalendarProvider",
    "DjangoR4MonitoringOwnerClock",
    "DjangoR4MonitoringOwnerRegistryRepository",
    "DjangoR4MonitoringPolicyProvider",
]
