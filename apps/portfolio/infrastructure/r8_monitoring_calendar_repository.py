"""Exact PIT repository for the Portfolio R8 monitoring calendar registry."""

from __future__ import annotations

from contextlib import AbstractContextManager
from datetime import datetime

from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.db.models import Q
from django.utils import timezone

from apps.portfolio.domain._optimization_canonical import (
    hash_components,
    require_aware,
    require_sha256,
    require_token,
    utc_text,
)
from apps.portfolio.domain.governed_optimization_monitoring import (
    GovernedOptimizationMonitoringCalendar,
)
from apps.portfolio.domain.r8_monitoring_calendar_registry import (
    R8MonitoringCalendarDefinition,
    R8MonitoringCalendarSourceReceipt,
)
from apps.portfolio.infrastructure.governed_optimization_monitoring_codec import (
    GovernedOptimizationMonitoringCodecError,
    decode_monitoring_calendar,
    encode_monitoring_calendar,
)
from apps.portfolio.infrastructure.optimization_input_receipt_repository import (
    DjangoGovernedOptimizationUnitOfWork,
)
from apps.portfolio.infrastructure.optimization_research_models import (
    _claim_governed_optimization_insert,
    _require_active_governed_optimization_uow,
)
from apps.portfolio.infrastructure.r8_monitoring_calendar_codec import (
    R8MonitoringCalendarRegistryCodecError,
    decode_r8_monitoring_calendar_definition,
    decode_r8_monitoring_calendar_source_receipt,
    encode_r8_monitoring_calendar_definition,
    encode_r8_monitoring_calendar_source_receipt,
)
from apps.portfolio.infrastructure.r8_monitoring_calendar_models import (
    R8MonitoringCalendarRegistryModel,
)


class R8MonitoringCalendarRegistryCorruption(ValueError):
    """Persisted calendar headers or strict payloads disagree."""


class R8MonitoringCalendarRegistryConflict(ValueError):
    """A stable calendar/source identity already seals different evidence."""


class DjangoR8MonitoringCalendarRegistryClock:
    """Trusted Django server clock bound to one Portfolio database alias."""

    __slots__ = ("_unit_of_work", "_using")

    def __init__(
        self,
        *,
        using: str = "default",
        unit_of_work: DjangoGovernedOptimizationUnitOfWork | None = None,
    ) -> None:
        self._using = using
        self._unit_of_work = unit_of_work

    @property
    def unit_of_work_key(self) -> str:
        """Return the shared database transaction identity."""

        if self._unit_of_work is not None:
            return self._unit_of_work.unit_of_work_key
        return f"django:{self._using}"

    def now(self) -> datetime:
        """Return one timezone-aware server timestamp."""

        return timezone.now()


class DjangoR8MonitoringCalendarRegistryRepository:
    """Public read-only exact calendar provider without a write token."""

    __slots__ = ("_using",)

    def __init__(self, *, using: str = "default") -> None:
        self._using = using

    @property
    def unit_of_work_key(self) -> str:
        """Return the shared database transaction identity."""

        return f"django:{self._using}"

    def get_exact(
        self,
        *,
        calendar_id: str,
        calendar_version: str,
        expected_calendar_hash: str,
        as_of: datetime,
    ) -> GovernedOptimizationMonitoringCalendar | None:
        """Return one exact live calendar or preserve absence as ``None``."""

        require_token(calendar_id, "R8 calendar query calendar_id")
        require_token(calendar_version, "R8 calendar query calendar_version")
        require_sha256(expected_calendar_hash, "R8 calendar query expected_calendar_hash")
        require_aware(as_of, "R8 calendar query as_of")
        rows = tuple(
            R8MonitoringCalendarRegistryModel._default_manager.using(self._using)
            .filter(
                Q(calendar_id=calendar_id, calendar_version=calendar_version)
                | Q(content_hash=expected_calendar_hash),
                recorded_at__lte=as_of,
                valid_until__gt=as_of,
            )
            .order_by("recorded_at")
        )
        if not rows:
            return None
        if len(rows) != 1:
            raise R8MonitoringCalendarRegistryCorruption(
                "R8 monitoring calendar identity is aliased"
            )
        calendar = _calendar_from_model(rows[0])
        if (
            calendar.calendar_id != calendar_id
            or calendar.calendar_version != calendar_version
            or calendar.content_hash != expected_calendar_hash
        ):
            raise R8MonitoringCalendarRegistryCorruption(
                "R8 monitoring calendar selector was substituted"
            )
        return calendar


class _DjangoR8MonitoringCalendarStore(DjangoR8MonitoringCalendarRegistryRepository):
    """Private claimed-append surface used only by owner composition."""

    __slots__ = ("_uow",)

    def __init__(self, *, unit_of_work: DjangoGovernedOptimizationUnitOfWork) -> None:
        super().__init__(using=unit_of_work.using)
        self._uow = unit_of_work

    @property
    def unit_of_work_key(self) -> str:
        """Return the private owner transaction identity."""

        return self._uow.unit_of_work_key

    def atomic(self) -> AbstractContextManager[None]:
        """Open one token-activated Portfolio owner transaction."""

        return self._uow.atomic()

    def append(
        self,
        calendar: GovernedOptimizationMonitoringCalendar,
        *,
        definition: R8MonitoringCalendarDefinition,
        source_receipt: R8MonitoringCalendarSourceReceipt,
    ) -> GovernedOptimizationMonitoringCalendar:
        """Append one fully replayable owner record or an exact winner."""

        _require_active_governed_optimization_uow()
        try:
            if type(calendar) is not GovernedOptimizationMonitoringCalendar:
                raise TypeError("calendar must use the exact Domain type")
            calendar = decode_monitoring_calendar(encode_monitoring_calendar(calendar))
            definition = definition.validated_copy()
            source_receipt = source_receipt.validated_copy()
            if (
                definition.content_hash != source_receipt.definition_hash
                or definition.build(owner_recorded_at=calendar.recorded_at) != calendar
                or not source_receipt.available_at <= calendar.recorded_at
                or source_receipt.valid_until < calendar.valid_until
            ):
                raise ValueError("R8 calendar owner graph differs")
        except (AttributeError, TypeError, ValueError) as error:
            raise R8MonitoringCalendarRegistryCorruption(
                "R8 monitoring calendar owner graph is invalid"
            ) from error
        winner = self._find_collision(calendar, definition, source_receipt, lock=True)
        if winner is not None:
            return self._match_winner(winner, calendar, definition, source_receipt)
        values = _calendar_model_values(calendar, definition, source_receipt)
        try:
            with transaction.atomic(using=self._uow.using):
                model = R8MonitoringCalendarRegistryModel(**values)
                model.full_clean()
                with _claim_governed_optimization_insert(
                    token=self._uow._insert_claim_token(),
                    model_type=R8MonitoringCalendarRegistryModel,
                    expected_values=values,
                ):
                    model.save(force_insert=True, using=self._uow.using)
        except (IntegrityError, ValidationError) as error:
            winner = self._find_collision(calendar, definition, source_receipt, lock=True)
            if winner is None:
                raise R8MonitoringCalendarRegistryConflict(
                    "R8 monitoring calendar append has no exact winner"
                ) from error
            return self._match_winner(winner, calendar, definition, source_receipt)
        return _calendar_from_model(model)

    def _find_collision(
        self,
        calendar: GovernedOptimizationMonitoringCalendar,
        definition: R8MonitoringCalendarDefinition,
        source: R8MonitoringCalendarSourceReceipt,
        *,
        lock: bool,
    ) -> R8MonitoringCalendarRegistryModel | None:
        queryset = R8MonitoringCalendarRegistryModel._default_manager.using(self._uow.using)
        if lock:
            queryset = queryset.select_for_update()
        rows = tuple(
            queryset.filter(
                Q(calendar_id=calendar.calendar_id, calendar_version=calendar.calendar_version)
                | Q(content_hash=calendar.content_hash)
                | Q(definition_hash=definition.content_hash)
                | Q(
                    source_receipt_id=source.source_receipt_id,
                    source_receipt_version=source.source_receipt_version,
                )
            )
        )
        if not rows:
            return None
        if len(rows) != 1:
            raise R8MonitoringCalendarRegistryConflict(
                "R8 monitoring calendar has multiple collision candidates"
            )
        return rows[0]

    @staticmethod
    def _match_winner(
        model: R8MonitoringCalendarRegistryModel,
        calendar: GovernedOptimizationMonitoringCalendar,
        definition: R8MonitoringCalendarDefinition,
        source: R8MonitoringCalendarSourceReceipt,
    ) -> GovernedOptimizationMonitoringCalendar:
        restored, restored_definition, restored_source = _registry_graph_from_model(model)
        if (
            restored != calendar
            or restored_definition != definition
            or restored_source != source
        ):
            raise R8MonitoringCalendarRegistryConflict(
                "R8 monitoring calendar identity forks to different evidence"
            )
        return restored


def _build_r8_monitoring_calendar_store(
    *,
    using: str = "default",
    unit_of_work: DjangoGovernedOptimizationUnitOfWork | None = None,
) -> _DjangoR8MonitoringCalendarStore:
    """Build the private claimed-append store for owner composition only."""

    return _DjangoR8MonitoringCalendarStore(
        unit_of_work=unit_of_work or DjangoGovernedOptimizationUnitOfWork(using=using)
    )


def _calendar_from_model(
    model: R8MonitoringCalendarRegistryModel,
) -> GovernedOptimizationMonitoringCalendar:
    calendar, _, _ = _registry_graph_from_model(model)
    return calendar


def _registry_graph_from_model(
    model: R8MonitoringCalendarRegistryModel,
) -> tuple[
    GovernedOptimizationMonitoringCalendar,
    R8MonitoringCalendarDefinition,
    R8MonitoringCalendarSourceReceipt,
]:
    try:
        definition = decode_r8_monitoring_calendar_definition(model.definition_payload)
        source = decode_r8_monitoring_calendar_source_receipt(model.source_receipt_payload)
        calendar = decode_monitoring_calendar(model.canonical_payload)
    except (
        GovernedOptimizationMonitoringCodecError,
        R8MonitoringCalendarRegistryCodecError,
        TypeError,
        ValueError,
    ) as error:
        raise R8MonitoringCalendarRegistryCorruption(
            "R8 monitoring calendar payload cannot be restored"
        ) from error
    values = _calendar_model_values(calendar, definition, source)
    actual = {name: getattr(model, name) for name in values}
    if actual != values:
        raise R8MonitoringCalendarRegistryCorruption(
            "R8 monitoring calendar headers differ from strict payloads"
        )
    if (
        definition.content_hash != source.definition_hash
        or definition.build(owner_recorded_at=calendar.recorded_at) != calendar
        or source.valid_until < calendar.valid_until
    ):
        raise R8MonitoringCalendarRegistryCorruption(
            "R8 monitoring calendar owner graph seal differs"
        )
    return calendar, definition, source


def _calendar_model_values(
    calendar: GovernedOptimizationMonitoringCalendar,
    definition: R8MonitoringCalendarDefinition,
    source: R8MonitoringCalendarSourceReceipt,
) -> dict[str, object]:
    values: dict[str, object] = {
        "calendar_id": calendar.calendar_id,
        "calendar_version": calendar.calendar_version,
        "definition_hash": definition.content_hash,
        "definition_payload": encode_r8_monitoring_calendar_definition(definition),
        "source_receipt_id": source.source_receipt_id,
        "source_receipt_version": source.source_receipt_version,
        "source_receipt_hash": source.content_hash,
        "source_receipt_payload": encode_r8_monitoring_calendar_source_receipt(source),
        "source_available_at": source.available_at,
        "source_valid_until": source.valid_until,
        "source_evidence_ref": source.evidence_ref,
        "recorded_at": calendar.recorded_at,
        "first_period_start": calendar.periods[0].start_at,
        "last_period_end": calendar.periods[-1].end_at,
        "valid_until": calendar.valid_until,
        "period_count": len(calendar.periods),
        "canonical_payload": encode_monitoring_calendar(calendar),
        "content_hash": calendar.content_hash,
        "research_only": True,
        "must_not_use_for_decision": True,
        "must_not_publish_current": True,
        "must_not_execute": True,
    }
    values["ledger_header_hash"] = _ledger_header_hash(calendar, definition, source)
    return values


def _ledger_header_hash(
    calendar: GovernedOptimizationMonitoringCalendar,
    definition: R8MonitoringCalendarDefinition,
    source: R8MonitoringCalendarSourceReceipt,
) -> str:
    return hash_components(
        "portfolio-r8-monitoring-calendar-ledger-header.v1",
        calendar.calendar_id,
        calendar.calendar_version,
        definition.content_hash,
        source.source_receipt_id,
        source.source_receipt_version,
        source.content_hash,
        utc_text(source.available_at),
        utc_text(source.valid_until),
        source.evidence_ref,
        utc_text(calendar.recorded_at),
        utc_text(calendar.periods[0].start_at),
        utc_text(calendar.periods[-1].end_at),
        utc_text(calendar.valid_until),
        str(len(calendar.periods)),
        calendar.content_hash,
        "true",
        "true",
        "true",
        "true",
    )


__all__ = [
    "DjangoR8MonitoringCalendarRegistryClock",
    "DjangoR8MonitoringCalendarRegistryRepository",
    "R8MonitoringCalendarRegistryConflict",
    "R8MonitoringCalendarRegistryCorruption",
]
