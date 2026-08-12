"""Strict append-only repositories for canonical R5 monitoring owners."""

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

from apps.research.application.r5_monitoring_owner_registry import (
    R5MonitoringOwnerRegistryClock,
)
from apps.research.domain.r5_monitoring_owner_registry import (
    R5MonitoringCalendarDefinition,
    R5MonitoringOwnerRecordKind,
    R5MonitoringOwnerSourceReceipt,
    R5MonitoringPolicyDefinition,
)
from apps.research.domain.r5_relative_value_monitoring_contracts import (
    R5MonitoringCalendar,
    R5MonitoringPolicy,
    _require_aware,
    _require_hash,
    _require_token,
)
from apps.research.infrastructure.r5_monitoring_owner_models import (
    R5MonitoringCalendarRegistryModel,
    R5MonitoringPolicyRegistryModel,
)
from apps.research.infrastructure.r5_relative_value_monitoring_codec import (
    decode_r5_monitoring_period_calendar,
    decode_r5_monitoring_policy,
    encode_r5_monitoring_period_calendar,
    encode_r5_monitoring_policy,
)
from apps.research.infrastructure.r5_relative_value_monitoring_models import (
    _activate_r5_monitoring_uow,
    _claim_r5_monitoring_insert,
)


class R5MonitoringOwnerRepositoryConflict(RuntimeError):
    """An immutable owner identity already has another winner."""


class R5MonitoringOwnerRepositoryCorruption(RuntimeError):
    """A persisted owner row cannot be strictly reconstructed."""


class DjangoR5MonitoringOwnerClock:
    """Django-backed clock bound to one database alias identity."""

    def __init__(self, *, using: str = "default") -> None:
        self._using = using

    @property
    def unit_of_work_key(self) -> str:
        return f"django:{self._using}"

    def now(self) -> datetime:
        """Return the timezone-aware server timestamp."""

        return timezone.now()


class DjangoR5MonitoringOwnerRegistryRepository:
    """Public exact PIT reader with no insert capability token."""

    def __init__(
        self,
        *,
        using: str = "default",
        clock: R5MonitoringOwnerRegistryClock | None = None,
    ) -> None:
        self._using = using
        self._clock = clock or DjangoR5MonitoringOwnerClock(using=using)

    @property
    def unit_of_work_key(self) -> str:
        return f"django:{self._using}"

    def atomic(self) -> AbstractContextManager[None]:
        """Open a read-only transaction boundary."""

        return transaction.atomic(using=self._using)

    def get_exact_policy(
        self,
        *,
        policy_id: str,
        policy_version: str,
        expected_policy_hash: str,
        as_of: datetime,
    ) -> R5MonitoringPolicy | None:
        """Return one exact policy known and active at the cutoff."""

        _validate_query(policy_id, policy_version, expected_policy_hash, as_of)
        self._require_cutoff(as_of)
        rows = tuple(
            R5MonitoringPolicyRegistryModel._default_manager.using(self._using)
            .filter(ledger_recorded_at__lte=as_of)
            .filter(
                Q(policy_id=policy_id, policy_version=policy_version)
                | Q(policy_hash=expected_policy_hash)
            )
        )
        if not rows:
            return None
        restored = tuple(_policy_from_model(item) for item in rows)
        matches = tuple(
            item
            for item in restored
            if item.policy_id == policy_id
            and item.policy_version == policy_version
            and item.content_hash == expected_policy_hash
            and item.recorded_at <= as_of < item.valid_until
        )
        if len(rows) != 1 or len(matches) != 1:
            raise R5MonitoringOwnerRepositoryCorruption(
                "R5 monitoring policy identity is aliased or substituted"
            )
        return matches[0]

    def get_exact_calendar(
        self,
        *,
        calendar_id: str,
        calendar_version: str,
        expected_calendar_hash: str,
        as_of: datetime,
    ) -> R5MonitoringCalendar | None:
        """Return one exact calendar known and active at the cutoff."""

        _validate_query(calendar_id, calendar_version, expected_calendar_hash, as_of)
        self._require_cutoff(as_of)
        rows = tuple(
            R5MonitoringCalendarRegistryModel._default_manager.using(self._using)
            .filter(ledger_recorded_at__lte=as_of)
            .filter(
                Q(calendar_id=calendar_id, calendar_version=calendar_version)
                | Q(calendar_hash=expected_calendar_hash)
            )
        )
        if not rows:
            return None
        restored = tuple(_calendar_from_model(item) for item in rows)
        matches = tuple(
            item
            for item in restored
            if item.owner.owner_id == calendar_id
            and item.owner.owner_version == calendar_version
            and item.content_hash == expected_calendar_hash
            and item.recorded_at <= as_of < item.valid_until
        )
        if len(rows) != 1 or len(matches) != 1:
            raise R5MonitoringOwnerRepositoryCorruption(
                "R5 monitoring calendar identity is aliased or substituted"
            )
        return matches[0]

    def _require_cutoff(self, as_of: datetime) -> None:
        try:
            now = self._clock.now()
            _require_aware(now, "R5 monitoring registry server clock")
        except Exception as error:
            raise R5MonitoringOwnerRepositoryCorruption(
                "R5 monitoring registry server clock is unavailable"
            ) from error
        if as_of > now:
            raise R5MonitoringOwnerRepositoryCorruption(
                "R5 monitoring registry cutoff is in the future"
            )


class _DjangoR5MonitoringOwnerRegistryStore(DjangoR5MonitoringOwnerRegistryRepository):
    """Private append capability used only by the registration composition."""

    def __init__(
        self,
        *,
        token: object,
        using: str = "default",
        clock: R5MonitoringOwnerRegistryClock | None = None,
    ) -> None:
        super().__init__(using=using, clock=clock)
        self._token = token

    @contextmanager
    def atomic(self) -> Iterator[None]:
        """Open one claimed Research owner-registration transaction."""

        with (
            transaction.atomic(using=self._using),
            _activate_r5_monitoring_uow(self._token),
        ):
            yield

    def append_policy(
        self,
        *,
        definition: R5MonitoringPolicyDefinition,
        source: R5MonitoringOwnerSourceReceipt,
        ledger_recorded_at: datetime,
    ) -> R5MonitoringPolicy:
        """Append or replay the exact policy winner."""

        canonical_definition = definition.validated_copy()
        canonical_source = source.validated_copy()
        policy = canonical_definition.policy
        _validate_append(
            source=canonical_source,
            definition_hash=canonical_definition.content_hash,
            kind=R5MonitoringOwnerRecordKind.POLICY,
            owner_id=policy.policy_id,
            owner_version=policy.policy_version,
            owner_recorded_at=policy.recorded_at,
            owner_valid_until=policy.valid_until,
            ledger_recorded_at=ledger_recorded_at,
        )
        rows = self._policy_collisions(policy, canonical_definition, canonical_source)
        if rows:
            return _exact_policy_winner(
                rows,
                policy=policy,
                definition=canonical_definition,
                source=canonical_source,
                ledger_recorded_at=ledger_recorded_at,
            )
        values = _policy_values(
            policy=policy,
            definition=canonical_definition,
            source=canonical_source,
            ledger_recorded_at=ledger_recorded_at,
        )
        model = R5MonitoringPolicyRegistryModel(**values)
        try:
            model.full_clean()
            with transaction.atomic(using=self._using):
                with _claim_r5_monitoring_insert(
                    token=self._token,
                    model_type=R5MonitoringPolicyRegistryModel,
                    expected_values=values,
                ):
                    model.save(force_insert=True, using=self._using)
        except (IntegrityError, ValidationError) as error:
            rows = self._policy_collisions(policy, canonical_definition, canonical_source)
            if not rows:
                raise R5MonitoringOwnerRepositoryConflict(
                    "R5 monitoring policy append lost without a winner"
                ) from error
            return _exact_policy_winner(
                rows,
                policy=policy,
                definition=canonical_definition,
                source=canonical_source,
                ledger_recorded_at=ledger_recorded_at,
            )
        restored = _policy_from_model(model)
        if restored != policy:
            raise R5MonitoringOwnerRepositoryCorruption("R5 monitoring policy did not round-trip")
        return restored

    def append_calendar(
        self,
        *,
        definition: R5MonitoringCalendarDefinition,
        source: R5MonitoringOwnerSourceReceipt,
        ledger_recorded_at: datetime,
    ) -> R5MonitoringCalendar:
        """Append or replay the exact calendar winner."""

        canonical_definition = definition.validated_copy()
        canonical_source = source.validated_copy()
        calendar = canonical_definition.calendar
        _validate_append(
            source=canonical_source,
            definition_hash=canonical_definition.content_hash,
            kind=R5MonitoringOwnerRecordKind.CALENDAR,
            owner_id=calendar.owner.owner_id,
            owner_version=calendar.owner.owner_version,
            owner_recorded_at=calendar.recorded_at,
            owner_valid_until=calendar.valid_until,
            ledger_recorded_at=ledger_recorded_at,
        )
        rows = self._calendar_collisions(calendar, canonical_definition, canonical_source)
        if rows:
            return _exact_calendar_winner(
                rows,
                calendar=calendar,
                definition=canonical_definition,
                source=canonical_source,
                ledger_recorded_at=ledger_recorded_at,
            )
        values = _calendar_values(
            calendar=calendar,
            definition=canonical_definition,
            source=canonical_source,
            ledger_recorded_at=ledger_recorded_at,
        )
        model = R5MonitoringCalendarRegistryModel(**values)
        try:
            model.full_clean()
            with transaction.atomic(using=self._using):
                with _claim_r5_monitoring_insert(
                    token=self._token,
                    model_type=R5MonitoringCalendarRegistryModel,
                    expected_values=values,
                ):
                    model.save(force_insert=True, using=self._using)
        except (IntegrityError, ValidationError) as error:
            rows = self._calendar_collisions(calendar, canonical_definition, canonical_source)
            if not rows:
                raise R5MonitoringOwnerRepositoryConflict(
                    "R5 monitoring calendar append lost without a winner"
                ) from error
            return _exact_calendar_winner(
                rows,
                calendar=calendar,
                definition=canonical_definition,
                source=canonical_source,
                ledger_recorded_at=ledger_recorded_at,
            )
        restored = _calendar_from_model(model)
        if restored != calendar:
            raise R5MonitoringOwnerRepositoryCorruption("R5 monitoring calendar did not round-trip")
        return restored

    def _policy_collisions(
        self,
        policy: R5MonitoringPolicy,
        definition: R5MonitoringPolicyDefinition,
        source: R5MonitoringOwnerSourceReceipt,
    ) -> tuple[R5MonitoringPolicyRegistryModel, ...]:
        return tuple(
            R5MonitoringPolicyRegistryModel._default_manager.using(self._using).filter(
                Q(policy_id=policy.policy_id, policy_version=policy.policy_version)
                | Q(policy_hash=policy.content_hash)
                | Q(definition_hash=definition.content_hash)
                | Q(source_receipt_hash=source.content_hash)
            )
        )

    def _calendar_collisions(
        self,
        calendar: R5MonitoringCalendar,
        definition: R5MonitoringCalendarDefinition,
        source: R5MonitoringOwnerSourceReceipt,
    ) -> tuple[R5MonitoringCalendarRegistryModel, ...]:
        return tuple(
            R5MonitoringCalendarRegistryModel._default_manager.using(self._using).filter(
                Q(
                    calendar_id=calendar.owner.owner_id,
                    calendar_version=calendar.owner.owner_version,
                )
                | Q(calendar_hash=calendar.content_hash)
                | Q(definition_hash=definition.content_hash)
                | Q(source_receipt_hash=source.content_hash)
            )
        )


class DjangoR5MonitoringPolicyProvider:
    """Phase-A compatible exact policy provider."""

    def __init__(self, repository: DjangoR5MonitoringOwnerRegistryRepository) -> None:
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
        as_of: datetime,
    ) -> R5MonitoringPolicy | None:
        """Return one exact registered policy."""

        return self._repository.get_exact_policy(
            policy_id=policy_id,
            policy_version=policy_version,
            expected_policy_hash=expected_policy_hash,
            as_of=as_of,
        )


class DjangoR5MonitoringCalendarProvider:
    """Phase-A compatible exact calendar provider."""

    def __init__(self, repository: DjangoR5MonitoringOwnerRegistryRepository) -> None:
        self._repository = repository

    @property
    def unit_of_work_key(self) -> str:
        return self._repository.unit_of_work_key

    def get_exact(
        self,
        *,
        calendar_id: str,
        calendar_version: str,
        expected_calendar_hash: str,
        as_of: datetime,
    ) -> R5MonitoringCalendar | None:
        """Return one exact registered calendar."""

        return self._repository.get_exact_calendar(
            calendar_id=calendar_id,
            calendar_version=calendar_version,
            expected_calendar_hash=expected_calendar_hash,
            as_of=as_of,
        )


def _policy_values(
    *,
    policy: R5MonitoringPolicy,
    definition: R5MonitoringPolicyDefinition,
    source: R5MonitoringOwnerSourceReceipt,
    ledger_recorded_at: datetime,
) -> dict[str, object]:
    values: dict[str, object] = {
        "policy_id": policy.policy_id,
        "policy_version": policy.policy_version,
        "policy_hash": policy.content_hash,
        "definition_hash": definition.content_hash,
        "source_receipt_id": source.source_receipt_id,
        "source_receipt_version": source.source_receipt_version,
        "source_receipt_hash": source.content_hash,
        "source_available_at": source.available_at,
        "source_valid_until": source.valid_until,
        "policy_recorded_at": policy.recorded_at,
        "policy_valid_until": policy.valid_until,
        "ledger_recorded_at": ledger_recorded_at,
        "policy_payload": encode_r5_monitoring_policy(policy),
        "source_payload": _source_payload(source),
        "research_only": True,
        "must_not_publish_current": True,
        "must_not_use_for_decision": True,
        "must_not_execute": True,
    }
    values["ledger_header_hash"] = _header_hash("policy", values)
    return values


def _calendar_values(
    *,
    calendar: R5MonitoringCalendar,
    definition: R5MonitoringCalendarDefinition,
    source: R5MonitoringOwnerSourceReceipt,
    ledger_recorded_at: datetime,
) -> dict[str, object]:
    values: dict[str, object] = {
        "calendar_id": calendar.owner.owner_id,
        "calendar_version": calendar.owner.owner_version,
        "calendar_hash": calendar.content_hash,
        "definition_hash": definition.content_hash,
        "source_receipt_id": source.source_receipt_id,
        "source_receipt_version": source.source_receipt_version,
        "source_receipt_hash": source.content_hash,
        "source_available_at": source.available_at,
        "source_valid_until": source.valid_until,
        "calendar_recorded_at": calendar.recorded_at,
        "calendar_valid_until": calendar.valid_until,
        "ledger_recorded_at": ledger_recorded_at,
        "calendar_payload": encode_r5_monitoring_period_calendar(calendar),
        "source_payload": _source_payload(source),
        "research_only": True,
        "must_not_publish_current": True,
        "must_not_use_for_decision": True,
        "must_not_execute": True,
    }
    values["ledger_header_hash"] = _header_hash("calendar", values)
    return values


def _policy_from_model(row: R5MonitoringPolicyRegistryModel) -> R5MonitoringPolicy:
    try:
        policy = decode_r5_monitoring_policy(row.policy_payload)
        definition = R5MonitoringPolicyDefinition.from_policy(policy)
        source = _restore_source(row.source_payload)
        values = _policy_values(
            policy=policy,
            definition=definition,
            source=source,
            ledger_recorded_at=row.ledger_recorded_at,
        )
        _require_row(row, values)
        return policy
    except R5MonitoringOwnerRepositoryCorruption:
        raise
    except Exception as error:
        raise R5MonitoringOwnerRepositoryCorruption(
            "R5 monitoring policy row is invalid"
        ) from error


def _calendar_from_model(
    row: R5MonitoringCalendarRegistryModel,
) -> R5MonitoringCalendar:
    try:
        calendar = decode_r5_monitoring_period_calendar(row.calendar_payload)
        definition = R5MonitoringCalendarDefinition.from_calendar(calendar)
        source = _restore_source(row.source_payload)
        values = _calendar_values(
            calendar=calendar,
            definition=definition,
            source=source,
            ledger_recorded_at=row.ledger_recorded_at,
        )
        _require_row(row, values)
        return calendar
    except R5MonitoringOwnerRepositoryCorruption:
        raise
    except Exception as error:
        raise R5MonitoringOwnerRepositoryCorruption(
            "R5 monitoring calendar row is invalid"
        ) from error


def _source_payload(source: R5MonitoringOwnerSourceReceipt) -> dict[str, object]:
    return {
        "record_kind": source.record_kind.value,
        "source_owner": source.source_owner,
        "source_receipt_id": source.source_receipt_id,
        "source_receipt_version": source.source_receipt_version,
        "owner_id": source.owner_id,
        "owner_version": source.owner_version,
        "definition_hash": source.definition_hash,
        "available_at": _time_text(source.available_at),
        "valid_until": _time_text(source.valid_until),
        "content_hash": source.content_hash,
    }


def _restore_source(payload: object) -> R5MonitoringOwnerSourceReceipt:
    if type(payload) is not dict:
        raise TypeError("R5 monitoring source payload is not an exact dict")
    expected = {
        "record_kind",
        "source_owner",
        "source_receipt_id",
        "source_receipt_version",
        "owner_id",
        "owner_version",
        "definition_hash",
        "available_at",
        "valid_until",
        "content_hash",
    }
    if set(payload) != expected or any(type(key) is not str for key in payload):
        raise ValueError("R5 monitoring source payload shape differs")
    return R5MonitoringOwnerSourceReceipt(
        record_kind=R5MonitoringOwnerRecordKind(str(payload["record_kind"])),
        source_owner=str(payload["source_owner"]),
        source_receipt_id=str(payload["source_receipt_id"]),
        source_receipt_version=str(payload["source_receipt_version"]),
        owner_id=str(payload["owner_id"]),
        owner_version=str(payload["owner_version"]),
        definition_hash=str(payload["definition_hash"]),
        available_at=_parse_time(payload["available_at"]),
        valid_until=_parse_time(payload["valid_until"]),
        content_hash=str(payload["content_hash"]),
    )


def _header_hash(kind: str, values: Mapping[str, object]) -> str:
    payload = {
        "schema": f"research-r5-monitoring-{kind}-registry-row.v1",
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
    raise TypeError(f"unsupported R5 monitoring owner ledger value: {type(value).__name__}")


def _require_row(row: object, values: Mapping[str, object]) -> None:
    for key, expected in values.items():
        if getattr(row, key) != expected:
            raise R5MonitoringOwnerRepositoryCorruption(
                f"R5 monitoring owner row field {key} differs"
            )


def _validate_append(
    *,
    source: R5MonitoringOwnerSourceReceipt,
    definition_hash: str,
    kind: R5MonitoringOwnerRecordKind,
    owner_id: str,
    owner_version: str,
    owner_recorded_at: datetime,
    owner_valid_until: datetime,
    ledger_recorded_at: datetime,
) -> None:
    _require_aware(ledger_recorded_at, "R5 monitoring ledger_recorded_at")
    if not (
        source.record_kind is kind
        and source.owner_id == owner_id
        and source.owner_version == owner_version
        and source.definition_hash == definition_hash
        and source.available_at <= ledger_recorded_at < source.valid_until
        and owner_recorded_at <= ledger_recorded_at < owner_valid_until
    ):
        raise R5MonitoringOwnerRepositoryConflict(
            "R5 monitoring owner definition/source clocks or identity differ"
        )


def _exact_policy_winner(
    rows: tuple[R5MonitoringPolicyRegistryModel, ...],
    *,
    policy: R5MonitoringPolicy,
    definition: R5MonitoringPolicyDefinition,
    source: R5MonitoringOwnerSourceReceipt,
    ledger_recorded_at: datetime,
) -> R5MonitoringPolicy:
    if len(rows) != 1:
        raise R5MonitoringOwnerRepositoryConflict("R5 monitoring policy has a fork")
    row = rows[0]
    restored = _policy_from_model(row)
    expected = _policy_values(
        policy=policy,
        definition=definition,
        source=source,
        ledger_recorded_at=row.ledger_recorded_at,
    )
    _require_row(row, expected)
    if restored != policy or row.ledger_recorded_at > ledger_recorded_at:
        raise R5MonitoringOwnerRepositoryConflict("R5 monitoring policy winner differs")
    return restored


def _exact_calendar_winner(
    rows: tuple[R5MonitoringCalendarRegistryModel, ...],
    *,
    calendar: R5MonitoringCalendar,
    definition: R5MonitoringCalendarDefinition,
    source: R5MonitoringOwnerSourceReceipt,
    ledger_recorded_at: datetime,
) -> R5MonitoringCalendar:
    if len(rows) != 1:
        raise R5MonitoringOwnerRepositoryConflict("R5 monitoring calendar has a fork")
    row = rows[0]
    restored = _calendar_from_model(row)
    expected = _calendar_values(
        calendar=calendar,
        definition=definition,
        source=source,
        ledger_recorded_at=row.ledger_recorded_at,
    )
    _require_row(row, expected)
    if restored != calendar or row.ledger_recorded_at > ledger_recorded_at:
        raise R5MonitoringOwnerRepositoryConflict("R5 monitoring calendar winner differs")
    return restored


def _validate_query(
    owner_id: str,
    owner_version: str,
    expected_hash: str,
    as_of: datetime,
) -> None:
    _require_token(owner_id, "R5 monitoring owner_id")
    _require_token(owner_version, "R5 monitoring owner_version")
    _require_hash(expected_hash, "R5 monitoring expected owner hash")
    _require_aware(as_of, "R5 monitoring owner as_of")


def _time_text(value: datetime) -> str:
    return value.astimezone(UTC).isoformat(timespec="microseconds")


def _parse_time(value: object) -> datetime:
    if type(value) is not str:
        raise TypeError("R5 monitoring source time is not a string")
    parsed = datetime.fromisoformat(value)
    _require_aware(parsed, "R5 monitoring source time")
    return parsed


def _build_r5_monitoring_owner_store(
    *,
    using: str = "default",
    clock: R5MonitoringOwnerRegistryClock | None = None,
) -> _DjangoR5MonitoringOwnerRegistryStore:
    """Build the private insert-capable store for trusted composition tests."""

    return _DjangoR5MonitoringOwnerRegistryStore(
        token=object(),
        using=using,
        clock=clock,
    )


__all__ = [
    "DjangoR5MonitoringCalendarProvider",
    "DjangoR5MonitoringOwnerClock",
    "DjangoR5MonitoringOwnerRegistryRepository",
    "DjangoR5MonitoringPolicyProvider",
    "R5MonitoringOwnerRepositoryConflict",
    "R5MonitoringOwnerRepositoryCorruption",
]
