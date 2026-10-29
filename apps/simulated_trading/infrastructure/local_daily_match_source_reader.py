"""Qualify retained sources for an explicitly configured historical simulation.

These reads do not publish data, capture a provider response, or establish live
execution authority. Source-only flags and unknown supplier clocks remain on
the original records. The simulation policy states how those records may be
interpreted for this one purpose.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Protocol
from uuid import UUID

from apps.data_center.application.price_limit_publication_operations import (
    PriceLimitPublicationReadResult,
    PriceLimitPublicationScope,
)
from apps.data_center.application.published_price_source import PublishedPriceSourceEvidence
from apps.data_center.application.qmt_daily_status import QmtDailyStatusResult
from apps.data_center.domain.enums import PriceAdjustment
from apps.data_center.domain.instrument_reference_snapshot import InstrumentReferenceSnapshotRecord
from apps.data_center.domain.market_time import CN_MARKET_TIMEZONE, cn_market_session_close_utc
from apps.data_center.domain.qmt_daily_status import QmtDailyStatusState
from apps.simulated_trading.application.execution_settlement_uow import (
    PublishedExecutionCalendarReader,
    SimulatedTradeExecutionBlocked,
)
from apps.simulated_trading.application.local_daily_match import (
    LocalDailyMatchCommand,
    LocalDailyMatchEvidenceKind,
    LocalDailyMatchSourceReference,
    QualifiedLocalDailyMatchInput,
    stable_local_daily_observation_id,
)
from apps.simulated_trading.application.order_reservation_fill import OrderFillContext
from apps.simulated_trading.domain.execution_settlement_primitives import (
    _require_aware,
    _require_hash,
)
from apps.simulated_trading.domain.local_daily_simulation_policy import (
    LocalDailySimulationPolicy,
    LocalDailySimulationPolicyBinding,
)
from apps.simulated_trading.domain.local_order_matching import (
    LocalMatchLimitState,
    LocalMatchObservation,
    LocalMatchPriceAdjustment,
    LocalMatchTradingState,
    LocalMatchVolumeUnit,
)
from apps.simulated_trading.infrastructure.published_price_initial_position_mark_reader import (
    PublishedPriceSourceReader,
)
from core.exceptions import DataFetchError, DataValidationError


class LocalDailySimulationPolicyReader(Protocol):
    """Read the explicit simulation policy and its original runtime provenance."""

    def read_policy(self, *, as_of: datetime) -> LocalDailySimulationPolicyBinding | None:
        """Return a verified active binding at this exact cutoff, or no policy."""


class InstrumentSnapshotReader(Protocol):
    """Read one immutable source snapshot with its raw bodies revalidated."""

    def __call__(self, *, snapshot_id: UUID) -> InstrumentReferenceSnapshotRecord | None:
        """Read only the selected source identity without a latest fallback."""


class OwnerQmtStatusReader(Protocol):
    """Read retained normalized assertions within the current owner's binding."""

    def __call__(
        self, *, owner_id: int, binding_id: str, asset_code: str, bar_date: date, as_of: datetime
    ) -> QmtDailyStatusResult:
        """Return owner-authenticated original assertions for the exact security/day."""


class PublishedLimitReferenceReader(Protocol):
    """Read verified global market references without publisher impersonation."""

    def __call__(
        self, *, scope: PriceLimitPublicationScope, as_of: datetime
    ) -> PriceLimitPublicationReadResult | None:
        """Verify exact scope, raw source and publication history at the cutoff."""


class RetainedLocalDailyMatchSourceReader:
    """Combine typed public source reads under one explicit simulation policy."""

    def __init__(
        self,
        *,
        policy_reader: LocalDailySimulationPolicyReader,
        calendar_reader: PublishedExecutionCalendarReader,
        get_price_source: PublishedPriceSourceReader,
        read_instrument_snapshot: InstrumentSnapshotReader,
        read_qmt_status: OwnerQmtStatusReader,
        read_limit_reference: PublishedLimitReferenceReader,
    ) -> None:
        """Bind read-only ports; construction performs no I/O or activation."""
        self._policy_reader = policy_reader
        self._calendar_reader = calendar_reader
        self._get_price_source = get_price_source
        self._read_instrument_snapshot = read_instrument_snapshot
        self._read_qmt_status = read_qmt_status
        self._read_limit_reference = read_limit_reference

    def read(
        self, *, command: LocalDailyMatchCommand, context: OrderFillContext, as_of: datetime
    ) -> QualifiedLocalDailyMatchInput:
        """Qualify exact retained evidence or raise a stable block without writes."""
        try:
            return self._read(command=command, context=context, as_of=as_of)
        except SimulatedTradeExecutionBlocked:
            raise
        except (
            DataFetchError,
            DataValidationError,
            ValueError,
            TypeError,
            ArithmeticError,
            AttributeError,
        ) as error:
            raise _blocked("SOURCE_INVALID") from error

    def _read(
        self, *, command: LocalDailyMatchCommand, context: OrderFillContext, as_of: datetime
    ) -> QualifiedLocalDailyMatchInput:
        _require_aware(as_of, "as_of")
        _need(
            type(command) is LocalDailyMatchCommand
            and type(context) is OrderFillContext
            and command.account_id == context.account_id == context.reservation.identity.account_id
            and command.user_id == context.owner_user_id
            and command.order_idempotency_key == context.order_idempotency_key
            and context.order_idempotency_key == context.reservation.identity.idempotency_key,
            "ORDER_SCOPE_MISMATCH",
        )
        context.reservation.__post_init__()
        command.__post_init__()
        _need(
            type(command.session_date) is date
            and command.session_date < as_of.astimezone(CN_MARKET_TIMEZONE).date(),
            "SESSION_NOT_HISTORICAL",
        )
        binding = self._policy_reader.read_policy(as_of=as_of)
        _need(type(binding) is LocalDailySimulationPolicyBinding, "POLICY_UNAVAILABLE")
        if binding is None:
            raise _blocked("POLICY_UNAVAILABLE")
        binding.validate_at(as_of=as_of)
        policy = binding.policy
        references: list[LocalDailyMatchSourceReference] = []
        self._currency(policy, command, context, as_of, references)
        self._calendar(command, context, as_of, references)
        price = self._price(policy, command, context, as_of, references)
        self._qmt(policy, command, context, as_of, references)
        limits = self._limits(policy, command, context, as_of, references)
        _need(self._policy_reader.read_policy(as_of=as_of) == binding, "POLICY_CHANGED")
        known_at = max(
            *(item.recorded_at for item in references),
            binding.provenance.profile_activated_at,
            binding.provenance.snapshot_generated_at,
            binding.provenance.snapshot_effective_from,
        )
        interval_end = cn_market_session_close_utc(command.session_date)
        _need(interval_end <= known_at <= as_of, "KNOWLEDGE_TIME_INVALID")
        _need(
            context.reservation.reserved_at < interval_end, "ORDER_NOT_ACCEPTED_BEFORE_SESSION_END"
        )
        observation = LocalMatchObservation(
            security_id=context.reservation.identity.security_id,
            session_date=command.session_date,
            observation_id=stable_local_daily_observation_id(
                context.reservation.identity.security_id, command.session_date
            ),
            observed_at=interval_end,
            available_at=known_at,
            close_price=price.values.close,
            price_adjustment=LocalMatchPriceAdjustment.UNADJUSTED,
            traded_volume=price.values.volume,
            volume_unit=LocalMatchVolumeUnit.CANONICAL_SHARES,
            trading_state=LocalMatchTradingState.TRADING,
            limit_state=LocalMatchLimitState.BOUNDED,
            lower_limit_price=limits.record.seal.snapshot.candidate.lower_limit_price,
            upper_limit_price=limits.record.seal.snapshot.candidate.upper_limit_price,
        )
        return QualifiedLocalDailyMatchInput(
            as_of=as_of,
            policy_binding=binding,
            observation=observation,
            evidence=tuple(sorted(references, key=lambda item: (item.kind, item.identity))),
        )

    def _currency(
        self,
        policy: LocalDailySimulationPolicy,
        command: LocalDailyMatchCommand,
        context: OrderFillContext,
        as_of: datetime,
        refs: list[LocalDailyMatchSourceReference],
    ) -> None:
        snapshot = self._read_instrument_snapshot(snapshot_id=UUID(policy.instrument_snapshot_id))
        _need(type(snapshot) is InstrumentReferenceSnapshotRecord, "CURRENCY_SNAPSHOT_MISSING")
        if snapshot is None:
            raise _blocked("CURRENCY_SNAPSHOT_MISSING")
        snapshot.__post_init__()
        _need(
            str(snapshot.snapshot_id) == policy.instrument_snapshot_id, "CURRENCY_IDENTITY_MISMATCH"
        )
        classification = snapshot.content.classify_security(context.asset_code)
        _need(
            classification is not None
            and classification.blocked_reason is None
            and classification.source_currency == policy.currency
            and classification.source_exchange == context.settlement_exchange
            and classification.source_list_status == "L"
            and classification.list_date is not None
            and classification.list_date <= command.session_date
            and (
                classification.delist_date is None
                or classification.delist_date > command.session_date
            ),
            "CURRENCY_OR_LISTING_UNQUALIFIED",
        )
        refs.append(
            _ref(
                "instrument_snapshot",
                str(snapshot.snapshot_id),
                snapshot.record_digest,
                snapshot.recorded_at,
                as_of,
            )
        )
        for fetch in snapshot.content.fetch_rounds:
            candidate = fetch.candidate
            _need(
                candidate.provider_contract.provider_name == "tushare"
                and candidate.provider_contract.dataset_key == "tushare.stock_basic.reference"
                and candidate.provider_contract.api_name == "stock_basic"
                and "curr_type" in candidate.provider_contract.fields,
                "CURRENCY_SOURCE_MISMATCH",
            )
            for occurrence in candidate.occurrences:
                _need(
                    occurrence.response_completed_at.astimezone(CN_MARKET_TIMEZONE).date()
                    == command.session_date,
                    "CURRENCY_NOT_SAME_SESSION",
                )
                refs.append(
                    _ref(
                        "instrument_raw",
                        occurrence.raw_payload_id,
                        occurrence.raw_payload_hash,
                        occurrence.response_completed_at,
                        as_of,
                    )
                )
                audit = occurrence.raw_audit_reference
                refs.append(
                    _ref(
                        "instrument_audit",
                        audit.raw_audit_id,
                        audit.content_hash,
                        occurrence.response_completed_at,
                        as_of,
                    )
                )

    def _calendar(
        self,
        command: LocalDailyMatchCommand,
        context: OrderFillContext,
        as_of: datetime,
        refs: list[LocalDailyMatchSourceReference],
    ) -> None:
        calendar = self._calendar_reader.get_effective_execution_calendar(
            exchange=context.settlement_exchange,
            as_of=as_of,
            coverage_start=command.session_date,
        )
        _need(calendar is not None, "CALENDAR_UNAVAILABLE")
        if calendar is None:
            raise _blocked("CALENDAR_UNAVAILABLE")
        calendar.validate_for(as_of)
        publication = calendar.publication
        _need(
            publication is not None and calendar.snapshot.exchange == context.settlement_exchange,
            "CALENDAR_SCOPE_MISMATCH",
        )
        if publication is None:
            raise _blocked("CALENDAR_UNAVAILABLE")
        # The formal daily-price source uses the mainland market interval anchor.
        _need(publication.timezone_name == "Asia/Shanghai", "CALENDAR_TIMEZONE_MISMATCH")
        _need(
            any(
                day.calendar_date == command.session_date and day.is_open
                for day in calendar.snapshot.days
            ),
            "SESSION_NOT_OPEN",
        )
        refs.append(
            _ref(
                "calendar",
                calendar.publication_reference,
                calendar.evidence_hash,
                max(
                    calendar.snapshot.recorded_at,
                    calendar.snapshot.first_seen_at,
                    publication.recorded_at,
                    publication.published_at,
                ),
                as_of,
            )
        )

    def _price(
        self,
        policy: LocalDailySimulationPolicy,
        command: LocalDailyMatchCommand,
        context: OrderFillContext,
        as_of: datetime,
        refs: list[LocalDailyMatchSourceReference],
    ) -> PublishedPriceSourceEvidence:
        result = self._get_price_source(
            context.asset_code,
            trade_date=command.session_date,
            knowledge_cutoff=as_of,
            publication_key=policy.price_publication_key,
        )
        evidence = result.evidence
        _need(
            type(evidence) is PublishedPriceSourceEvidence and not result.must_not_use_for_decision,
            "PRICE_UNAVAILABLE",
        )
        if evidence is None:
            raise _blocked("PRICE_UNAVAILABLE")
        _need(
            evidence.asset_code == context.asset_code
            and evidence.trade_date == command.session_date
            and evidence.knowledge_cutoff == as_of
            and evidence.publication_key == policy.price_publication_key
            and type(evidence.provider_configuration_id) is int
            and evidence.provider_configuration_id == policy.provider_configuration_id
            and evidence.source == "tushare"
            and evidence.adjustment is PriceAdjustment.NONE
            and evidence.volume_unit == policy.volume_unit
            and evidence.raw_payload_reference.provider_name == policy.provider_name,
            "PRICE_SCOPE_MISMATCH",
        )
        _need(
            evidence.interval_end_at == cn_market_session_close_utc(command.session_date)
            and evidence.source_observed_at is None
            and evidence.source_published_at is None
            and evidence.availability_basis == "local_response_body_completion"
            and evidence.available_at == evidence.raw_payload_reference.response_completed_at,
            "PRICE_CLOCK_BASIS_INVALID",
        )
        for stamp in (
            evidence.available_at,
            evidence.fact_recorded_at,
            evidence.publication_as_of,
            evidence.publication_published_at,
        ):
            _require_aware(stamp, "price_clock")
            _need(evidence.interval_end_at <= stamp <= as_of, "PRICE_NOT_KNOWN")
        refs.extend(
            (
                _ref(
                    "price_publication",
                    evidence.publication_id,
                    evidence.publication_hash,
                    evidence.publication_published_at,
                    as_of,
                ),
                _ref(
                    "price_manifest",
                    evidence.manifest_id,
                    evidence.manifest_hash,
                    evidence.publication_published_at,
                    as_of,
                ),
                _ref(
                    "price_fact",
                    evidence.fact_pk,
                    evidence.fact_content_hash,
                    evidence.fact_recorded_at,
                    as_of,
                ),
                _ref(
                    "price_raw",
                    evidence.raw_payload_reference.payload_id,
                    evidence.raw_payload_reference.record_digest,
                    evidence.available_at,
                    as_of,
                ),
                _ref(
                    "price_audit",
                    evidence.raw_audit_reference.raw_audit_id,
                    evidence.raw_audit_reference.content_hash,
                    evidence.publication_published_at,
                    as_of,
                ),
            )
        )
        return evidence

    def _qmt(
        self,
        policy: LocalDailySimulationPolicy,
        command: LocalDailyMatchCommand,
        context: OrderFillContext,
        as_of: datetime,
        refs: list[LocalDailyMatchSourceReference],
    ) -> None:
        status = self._read_qmt_status(
            owner_id=command.user_id,
            binding_id=command.qmt_binding_id,
            asset_code=context.asset_code,
            bar_date=command.session_date,
            as_of=as_of,
        )
        _need(
            type(status) is QmtDailyStatusResult
            and status.binding_id == command.qmt_binding_id
            and status.asset_code == context.asset_code
            and status.bar_date == command.session_date
            and status.as_of == as_of
            and status.blocked_reason == "qmt_daily_status_requires_publication_validation"
            and type(status.suspend_flag) is int
            and status.suspend_flag in policy.allowed_qmt_suspend_flags
            and (
                (status.suspend_flag == 0 and status.state is QmtDailyStatusState.NORMAL)
                or (status.suspend_flag == -1 and status.state is QmtDailyStatusState.RESUMED)
            )
            and bool(status.evidence)
            and status.recorded_at is not None
            and status.local_known_at is not None,
            "QMT_STATUS_UNQUALIFIED",
        )
        if status.recorded_at is None or status.local_known_at is None:
            raise _blocked("QMT_STATUS_UNQUALIFIED")
        _need(status.local_known_at <= status.recorded_at <= as_of, "QMT_CLOCK_INVALID")
        _need(
            any(
                item.recorded_at == status.recorded_at
                and item.collected_at == status.local_known_at
                for item in status.evidence
            ),
            "QMT_SELECTED_EVIDENCE_MISSING",
        )
        for item in status.evidence:
            _require_aware(item.collected_at, "qmt_collection")
            _need(item.collected_at <= item.recorded_at <= as_of, "QMT_CLOCK_INVALID")
            refs.append(
                _ref("qmt_batch", item.batch_id, item.content_hash, item.recorded_at, as_of)
            )

    def _limits(
        self,
        policy: LocalDailySimulationPolicy,
        command: LocalDailyMatchCommand,
        context: OrderFillContext,
        as_of: datetime,
        refs: list[LocalDailyMatchSourceReference],
    ) -> PriceLimitPublicationReadResult:
        scope = PriceLimitPublicationScope(
            provider_id=policy.provider_configuration_id,
            provider_name=policy.provider_name,
            asset_code=context.asset_code,
            effective_trade_date=command.session_date,
        )
        selected = self._read_limit_reference(scope=scope, as_of=as_of)
        _need(type(selected) is PriceLimitPublicationReadResult, "LIMIT_REFERENCE_UNAVAILABLE")
        if selected is None:
            raise _blocked("LIMIT_REFERENCE_UNAVAILABLE")
        selected.record.validate()
        snapshot = selected.record.seal.snapshot
        candidate = snapshot.candidate
        _need(
            selected.as_of == as_of
            and selected.lookup_basis == "visible_at_cutoff"
            and selected.visible_from is not None
            and candidate.provider_id == scope.provider_id
            and candidate.provider_name == scope.provider_name
            and candidate.asset_code == scope.asset_code
            and candidate.effective_trade_date == scope.effective_trade_date
            and candidate.price_unit == "provider_native_price"
            and candidate.currency is None,
            "LIMIT_REFERENCE_SCOPE_MISMATCH",
        )
        if selected.visible_from is None:
            raise _blocked("LIMIT_REFERENCE_UNAVAILABLE")
        _need(
            selected.record.first_published_at <= selected.visible_from <= as_of,
            "LIMIT_REFERENCE_NOT_KNOWN",
        )
        refs.extend(
            (
                _ref(
                    "limit_publication",
                    selected.record.publication_id,
                    selected.record.publication_hash,
                    selected.visible_from,
                    as_of,
                ),
                _ref(
                    "limit_snapshot",
                    snapshot.snapshot_id,
                    snapshot.record_digest,
                    snapshot.recorded_at,
                    as_of,
                ),
                _ref(
                    "limit_raw",
                    candidate.raw_reference.payload_id,
                    candidate.raw_reference.record_digest,
                    candidate.response_completed_at,
                    as_of,
                ),
            )
        )
        return selected


def _blocked(reason: str) -> SimulatedTradeExecutionBlocked:
    """Return a stable local qualification block using the existing business error."""
    return SimulatedTradeExecutionBlocked(
        "历史日线模拟所需的留存来源不能精确核对", code=f"LOCAL_DAILY_MATCH_{reason}"
    )


def _need(condition: bool, reason: str) -> None:
    """Stop qualification at the first missing or contradictory source fact."""
    if not condition:
        raise _blocked(reason)


def _ref(
    kind: str, identity: str, content_hash: str, recorded_at: datetime, as_of: datetime
) -> LocalDailyMatchSourceReference:
    """Normalize only the hash envelope while preserving source identity and time."""
    _require_aware(recorded_at, "source_recorded_at")
    _need(recorded_at <= as_of, "SOURCE_NOT_KNOWN")
    bare_hash = content_hash.removeprefix("sha256:")
    _require_hash(bare_hash, "source_content_hash")
    return LocalDailyMatchSourceReference(
        LocalDailyMatchEvidenceKind(kind), identity, bare_hash, recorded_at
    )
