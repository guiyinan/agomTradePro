"""Compose explicit simulated fee policies and settlement-bound ledger use cases."""

from __future__ import annotations

from datetime import date, datetime, timedelta

from apps.data_center.application.formal_exchange_calendar_publication import (
    CalendarFormalPublicationApplicationError,
    CurrentPublishedExchangeCalendar,
    ReadCurrentExchangeCalendarPublicationQuery,
)
from apps.data_center.calendar_publication_operations_composition import (
    read_current_exchange_calendar_at,
)
from apps.data_center.domain.exchange_calendar import (
    ExchangeCalendarDay as DataCenterExchangeCalendarDay,
)
from apps.data_center.domain.exchange_calendar import (
    ExchangeCalendarRawReference as DataCenterExchangeCalendarRawReference,
)
from apps.data_center.domain.exchange_calendar import (
    ExchangeCalendarSnapshot as DataCenterExchangeCalendarSnapshot,
)
from apps.data_center.domain.exchange_calendar import (
    ExchangeCalendarSnapshotCandidate as DataCenterExchangeCalendarSnapshotCandidate,
)
from apps.simulated_trading.application.execution_settlement_uow import (
    ExecuteSettlementBoundSimulatedTradeUseCase,
    ExecutionCalendarUnavailable,
    ExecutionInstrumentIdentityReader,
    PublishedExecutionCalendarReader,
    ReleaseDueSimulatedSettlementsUseCase,
    SettlementV3RuleReader,
    SimulatedTradeExecutionBlocked,
    SimulatedTradeExecutionClock,
)
from apps.simulated_trading.application.fee_policy_v2 import (
    CreateFeePolicyVersionUseCase,
)
from apps.simulated_trading.application.order_reservation import (
    CancelSimulatedOrderReservationUseCase,
    ReserveSimulatedOrderUseCase,
)
from apps.simulated_trading.domain.execution_settlement_calendar import (
    CalendarPublicationReference,
    ExchangeCalendarDay,
    ExchangeCalendarSnapshot,
    ExecutionCalendarEvidence,
    RawCalendarReference,
)
from apps.simulated_trading.domain.execution_settlement_primitives import (
    CalendarEvidenceValidationError,
)
from apps.simulated_trading.infrastructure.execution_settlement_uow_repository import (
    DjangoSimulatedTradeExecutionRepository,
)
from apps.simulated_trading.infrastructure.fee_policy_v2_repository import (
    DjangoFeePolicyV2Repository,
)
from apps.simulated_trading.infrastructure.order_reservation_repository import (
    DjangoSimulatedOrderReservationRepository,
)
from core.exceptions import AgomTradeProException
from core.integration.config_center_runtime import get_active_runtime_value


def build_execute_settlement_bound_simulated_trade_use_case(
    *,
    using: str,
    rule_reader: SettlementV3RuleReader,
    identity_reader: ExecutionInstrumentIdentityReader,
    calendar_reader: PublishedExecutionCalendarReader,
    clock: SimulatedTradeExecutionClock,
) -> ExecuteSettlementBoundSimulatedTradeUseCase:
    """Compose one trade use case with explicit source ports and DB alias.

    No rule, identity, calendar, or clock provider is selected here. Callers
    must inject adapters that enforce their own source and database scope; the
    identity adapter must supply the exact source exchange without inference.
    The ledger and FeeConfig reads share one repository instance bound to
    ``using``.
    """

    repository = DjangoSimulatedTradeExecutionRepository(using=using)
    return ExecuteSettlementBoundSimulatedTradeUseCase(
        rule_reader=rule_reader,
        identity_reader=identity_reader,
        calendar_reader=calendar_reader,
        fee_policy_reader=repository,
        repository=repository,
        clock=clock,
    )


def build_reserve_simulated_order_use_case(
    *,
    using: str,
    rule_reader: SettlementV3RuleReader,
    identity_reader: ExecutionInstrumentIdentityReader,
    calendar_reader: PublishedExecutionCalendarReader,
    clock: SimulatedTradeExecutionClock,
) -> ReserveSimulatedOrderUseCase:
    """Compose local order commitments with the ordinary execution source readers.

    The caller must complete its market/session/price and authority checks.
    Construction neither reads sources nor activates execution.
    """
    preparer = build_execute_settlement_bound_simulated_trade_use_case(
        using=using,
        rule_reader=rule_reader,
        identity_reader=identity_reader,
        calendar_reader=calendar_reader,
        clock=clock,
    )
    return ReserveSimulatedOrderUseCase(
        preparer=preparer,
        repository=DjangoSimulatedOrderReservationRepository(using=using),
        clock=clock,
    )


def build_cancel_simulated_order_reservation_use_case(
    *,
    using: str,
    clock: SimulatedTradeExecutionClock,
) -> CancelSimulatedOrderReservationUseCase:
    """Compose idempotent local cancellation without requiring fresh market sources."""
    return CancelSimulatedOrderReservationUseCase(
        repository=DjangoSimulatedOrderReservationRepository(using=using),
        clock=clock,
    )


def build_release_due_simulated_settlements_use_case(
    *,
    using: str,
    calendar_reader: PublishedExecutionCalendarReader,
    clock: SimulatedTradeExecutionClock,
) -> ReleaseDueSimulatedSettlementsUseCase:
    """Compose explicit settlement release ports and one ledger DB alias.

    No calendar adapter or clock is selected implicitly. The returned use case
    blocks when the injected calendar reader cannot provide valid evidence.
    """

    repository = DjangoSimulatedTradeExecutionRepository(using=using)
    return ReleaseDueSimulatedSettlementsUseCase(
        calendar_reader=calendar_reader,
        repository=repository,
        clock=clock,
    )


def build_create_fee_policy_version_use_case(
    *,
    using: str,
) -> CreateFeePolicyVersionUseCase:
    """Compose the operator use case with one explicit FeeConfig database alias."""

    repository = DjangoFeePolicyV2Repository(using=using)
    return CreateFeePolicyVersionUseCase(repository=repository)


class _CurrentPublishedExecutionCalendarReader:
    """Map exact Data Center publication reads into validated simulated evidence."""

    def __init__(self, *, dataset_key: str, runtime_environment: str) -> None:
        """Bind explicit owner scopes without reading configuration or source data."""

        self._dataset_key = dataset_key
        self._runtime_environment = runtime_environment

    def get_effective_execution_calendar(
        self,
        *,
        exchange: str,
        as_of: datetime,
        coverage_start: date | None,
    ) -> ExecutionCalendarEvidence | None:
        """Return the complete current published calendar for one exact cutoff.

        The Data Center exact-current read remains the source of truth. The
        optional runtime timezone map supplies only the exchange's configured
        ZoneInfo name; it never changes source dates, clocks, hashes, or TTL.
        """

        if type(exchange) is not str or not exchange or exchange.strip() != exchange:
            raise SimulatedTradeExecutionBlocked(
                "Calendar exchange scope must be an exact nonempty token"
            )
        if type(as_of) is not datetime or as_of.tzinfo is None:
            raise SimulatedTradeExecutionBlocked("Calendar cutoff must be aware UTC")
        try:
            offset = as_of.utcoffset()
        except (OverflowError, TypeError, ValueError) as error:
            raise SimulatedTradeExecutionBlocked("Calendar cutoff must be aware UTC") from error
        if offset != timedelta(0):
            raise SimulatedTradeExecutionBlocked("Calendar cutoff must be aware UTC")
        if coverage_start is not None and type(coverage_start) is not date:
            raise SimulatedTradeExecutionBlocked("Calendar coverage start must be an exact date")

        try:
            query = ReadCurrentExchangeCalendarPublicationQuery(
                dataset_key=self._dataset_key,
                exchange=exchange,
                as_of=as_of,
            )
            query.__post_init__()
        except CalendarFormalPublicationApplicationError as error:
            raise SimulatedTradeExecutionBlocked(
                "Calendar current-read scope is invalid"
            ) from error

        try:
            current = read_current_exchange_calendar_at(query)
        except CalendarFormalPublicationApplicationError as error:
            if error.code == "CALENDAR_CURRENT_PUBLICATION_MISSING":
                return None
            raise SimulatedTradeExecutionBlocked(
                "The exact current calendar publication could not be verified"
            ) from error
        except AgomTradeProException as error:
            raise SimulatedTradeExecutionBlocked(
                "The exact current calendar publication could not be verified"
            ) from error

        if type(current) is not CurrentPublishedExchangeCalendar:
            raise SimulatedTradeExecutionBlocked(
                "The calendar owner returned no exact current-publication value"
            )
        try:
            current.__post_init__()
            record = current.record
            seal = record.seal
            source_snapshot = seal.snapshot
            source_candidate = source_snapshot.candidate
            source_raw = source_candidate.raw_reference
            publication_window = record.window
        except CalendarFormalPublicationApplicationError as error:
            raise SimulatedTradeExecutionBlocked(
                "The exact current calendar publication failed revalidation"
            ) from error
        except AgomTradeProException as error:
            raise SimulatedTradeExecutionBlocked(
                "The exact current calendar publication failed revalidation"
            ) from error

        publication_recorded_at = current.pointer.updated_at
        if publication_recorded_at is None:
            raise SimulatedTradeExecutionBlocked(
                "The current calendar pointer has no publication knowledge clock"
            )

        if (
            current.as_of != as_of
            or seal.dataset.value != self._dataset_key
            or seal.exchange != exchange
            or source_snapshot.exchange != exchange
            or source_candidate.exchange != exchange
            or source_raw.dataset_key != self._dataset_key
            or current.pointer.dataset_key != self._dataset_key
            or current.pointer.publication_key != seal.publication_key
        ):
            raise SimulatedTradeExecutionBlocked(
                "The current calendar publication differs from the requested scope or cutoff"
            )
        if (
            type(source_snapshot) is not DataCenterExchangeCalendarSnapshot
            or type(source_candidate) is not DataCenterExchangeCalendarSnapshotCandidate
            or type(source_raw) is not DataCenterExchangeCalendarRawReference
            or type(source_candidate.days) is not tuple
            or any(type(day) is not DataCenterExchangeCalendarDay for day in source_candidate.days)
        ):
            raise SimulatedTradeExecutionBlocked(
                "The calendar source is not a complete set of exact typed values"
            )
        if coverage_start is not None and not (
            source_snapshot.coverage_start <= coverage_start <= source_snapshot.coverage_end
        ):
            raise SimulatedTradeExecutionBlocked(
                "Requested calendar coverage start is outside the complete source range"
            )

        try:
            runtime_value = get_active_runtime_value(
                environment=self._runtime_environment,
                definition_key="config_center.market.exchange_timezone_map",
                as_of=as_of,
            )
        except AgomTradeProException as error:
            raise SimulatedTradeExecutionBlocked(
                "The exchange timezone configuration could not be verified"
            ) from error
        if runtime_value is None:
            raise ExecutionCalendarUnavailable(
                "No active exchange timezone map is available at the requested cutoff"
            )
        if type(runtime_value) is not dict:
            raise SimulatedTradeExecutionBlocked(
                "The exchange timezone map must contain only exact string keys and values"
            )
        timezone_map: dict[str, str] = {}
        for key, value in runtime_value.items():
            if type(key) is not str or type(value) is not str:
                raise SimulatedTradeExecutionBlocked(
                    "The exchange timezone map must contain only exact string keys and values"
                )
            timezone_map[key] = value
        timezone_name = timezone_map.get(exchange)
        if timezone_name is None:
            raise ExecutionCalendarUnavailable(
                "No active timezone is configured for the requested exchange"
            )

        try:
            mapped_days = tuple(
                ExchangeCalendarDay(
                    exchange=day.exchange,
                    calendar_date=day.calendar_date,
                    is_open=day.is_open,
                    previous_open_date=day.previous_open_date,
                )
                for day in source_candidate.days
            )
            snapshot = ExchangeCalendarSnapshot(
                snapshot_id=source_snapshot.snapshot_id,
                exchange=source_snapshot.exchange,
                coverage_start=source_snapshot.coverage_start,
                coverage_end=source_snapshot.coverage_end,
                days=mapped_days,
                provider_name=source_snapshot.provider_name,
                raw_reference=RawCalendarReference(
                    payload_id=source_raw.payload_id,
                    payload_hash=source_raw.payload_hash,
                    record_digest=source_raw.record_digest,
                    body_sha256=source_raw.body_sha256,
                    retained_content_sha256=source_raw.retained_content_sha256,
                    request_scope_sha256=source_raw.request_scope_sha256,
                    original_body_retained=source_raw.original_body_retained,
                    response_completed_at=source_raw.response_completed_at,
                    provider_name=source_raw.provider_name,
                    dataset_key=source_raw.dataset_key,
                    transport=source_raw.transport,
                ),
                content_hash=source_snapshot.content_hash,
                record_digest=source_snapshot.record_digest,
                first_seen_at=source_snapshot.first_seen_at,
                recorded_at=source_snapshot.recorded_at,
                source_published_at=source_snapshot.source_published_at,
            )
            publication = CalendarPublicationReference(
                publication_id=record.publication_id,
                member_id=source_snapshot.snapshot_id,
                publication_hash=seal.publication_hash,
                fact_content_hash=seal.member_reference.member.fact_content_hash,
                policy_hash=seal.policy.content_hash,
                published_at=record.published_at,
                recorded_at=publication_recorded_at,
                reference_valid_from=publication_window.valid_from,
                reference_valid_until=publication_window.valid_until,
                timezone_name=timezone_name,
            )
            evidence = ExecutionCalendarEvidence(snapshot=snapshot, publication=publication)
            evidence.validate_for(as_of)
        except CalendarEvidenceValidationError as error:
            raise SimulatedTradeExecutionBlocked(
                "The published calendar evidence failed simulated-domain validation"
            ) from error
        return evidence


def build_current_published_execution_calendar_reader(
    *,
    dataset_key: str,
    runtime_environment: str,
) -> PublishedExecutionCalendarReader:
    """Compose an exact-current calendar reader from explicit owner scopes.

    The factory performs no configuration, calendar, or ledger reads. Callers
    must provide the active dataset and runtime environment explicitly.
    """

    if (
        type(dataset_key) is not str
        or not dataset_key
        or dataset_key.strip() != dataset_key
        or any(character.isspace() for character in dataset_key)
        or type(runtime_environment) is not str
        or not runtime_environment
        or runtime_environment.strip() != runtime_environment
        or any(character.isspace() for character in runtime_environment)
    ):
        raise SimulatedTradeExecutionBlocked(
            "Calendar dataset and runtime environment scopes must be explicit tokens"
        )
    return _CurrentPublishedExecutionCalendarReader(
        dataset_key=dataset_key,
        runtime_environment=runtime_environment,
    )
