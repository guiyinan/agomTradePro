"""Read an exact current daily close as a simulation-only raw NAV mark."""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import UTC, date, datetime, timedelta
from typing import Protocol
from zoneinfo import ZoneInfo

from apps.data_center.application.price_response_capture import ExactPriceBarValues
from apps.data_center.application.published_price_source import (
    PublishedPriceSourceEvidence,
    PublishedPriceSourceResult,
)
from apps.data_center.domain.enums import PriceAdjustment
from apps.data_center.domain.market_time import (
    cn_market_session_close_utc,
    latest_closed_cn_market_session,
)
from apps.simulated_trading.application.corporate_action_nav_mark import (
    SimulatedCorporateActionNavRawMarkContractError,
    SimulatedCorporateActionNavRawMarkPolicyBinding,
    SimulatedCorporateActionNavRawMarkPolicyReader,
    SimulatedCorporateActionNavRawMarkProof,
    SimulatedCorporateActionNavRawMarkQuery,
)
from apps.simulated_trading.application.execution_current_reference_classification import (
    CurrentReferenceClassificationReader,
)
from apps.simulated_trading.application.execution_settlement_uow import (
    PublishedExecutionCalendarReader,
    SimulatedTradeExecutionBlocked,
)
from apps.simulated_trading.domain.corporate_action_nav_mark_policy import (
    SimulatedCorporateActionNavRawMarkPolicyError,
)
from apps.simulated_trading.domain.execution_instrument_classification import (
    SimulatedInstrumentClassificationEvidenceV1,
)
from apps.simulated_trading.domain.execution_settlement_calendar import ExecutionCalendarEvidence
from apps.simulated_trading.domain.execution_settlement_identity import (
    IdentityEvidenceValidationError,
)
from apps.simulated_trading.domain.execution_settlement_primitives import (
    CalendarEvidenceValidationError,
)
from core.exceptions import DataFetchError, DataValidationError


class PublishedDailyPriceReader(Protocol):
    """Read one exact retained published daily price through Data Center's public port."""

    def __call__(
        self,
        asset_code: str,
        *,
        trade_date: date,
        knowledge_cutoff: datetime,
        publication_key: str,
    ) -> PublishedPriceSourceResult:
        """Return verified source evidence for the exact asset, date, and cutoff."""


class SimulatedCorporateActionNavRawMarkClock(Protocol):
    """Supply a trusted timezone-aware clock for start, reread, and completion checks."""

    def now(self) -> datetime:
        """Return the current aware clock without consulting caller input."""


@dataclass(frozen=True, slots=True)
class _ReadState:
    """Keep one internally consistent policy, identity, calendar, and price read."""

    policy_binding: SimulatedCorporateActionNavRawMarkPolicyBinding
    classification: SimulatedInstrumentClassificationEvidenceV1
    calendar: ExecutionCalendarEvidence
    trade_date: date
    interval_end_at: datetime
    source_result: PublishedPriceSourceResult


class PublishedPriceCorporateActionNavRawMarkReader:
    """Double-read current policy and source evidence before returning one raw mark.

    The result is an exact raw price only. This adapter does not prove account
    NAV, missing corporate actions, tax coverage, spendable value, or financial
    permission, and it never reads legacy position prices or market values.
    """

    def __init__(
        self,
        *,
        policy_reader: SimulatedCorporateActionNavRawMarkPolicyReader,
        classification_reader: CurrentReferenceClassificationReader,
        calendar_reader: PublishedExecutionCalendarReader,
        get_price_source: PublishedDailyPriceReader,
        clock: SimulatedCorporateActionNavRawMarkClock,
    ) -> None:
        """Bind the five read-only ports without selecting any default source policy."""

        self._policy_reader = policy_reader
        self._classification_reader = classification_reader
        self._calendar_reader = calendar_reader
        self._get_price_source = get_price_source
        self._clock = clock

    def read_current_mark(
        self, query: SimulatedCorporateActionNavRawMarkQuery
    ) -> SimulatedCorporateActionNavRawMarkProof | None:
        """Return a still-current raw mark or ``None`` after any failed fence."""

        try:
            query.validate()
            started_at = self._read_clock()
            first = self._read_state(query, as_of=started_at)
            reread_started_at = self._read_clock()
            if reread_started_at < started_at:
                return None
            final = self._read_state(query, as_of=reread_started_at)
            checked_at = self._read_clock()
            if checked_at < reread_started_at:
                return None
            if not self._same_selected_evidence(first, final):
                return None
            final.policy_binding.validate_for(as_of=checked_at)
            final.classification.validate_at(as_of=checked_at)
            final.calendar.validate_for(checked_at)
            checked_trade_date = self._latest_trade_date(final.calendar, checked_at)
            if checked_trade_date is None or checked_trade_date != final.trade_date:
                return None
            source_evidence = final.source_result.evidence
            if source_evidence is None:
                return None
            deadline = self._deadline(
                final.interval_end_at,
                final.policy_binding.policy.freshness_window_seconds,
            )
            if checked_at >= deadline:
                return None
            return SimulatedCorporateActionNavRawMarkProof(
                query=query,
                policy_binding=final.policy_binding,
                classification=final.classification,
                calendar=final.calendar,
                source_evidence=source_evidence,
                trade_date=final.trade_date,
                interval_end_at=final.interval_end_at,
                reading_started_at=started_at,
                checked_at=checked_at,
                valid_until=deadline,
            )
        except (
            CalendarEvidenceValidationError,
            DataFetchError,
            DataValidationError,
            IdentityEvidenceValidationError,
            SimulatedCorporateActionNavRawMarkContractError,
            SimulatedCorporateActionNavRawMarkPolicyError,
            SimulatedTradeExecutionBlocked,
            ArithmeticError,
            AttributeError,
            TypeError,
            ValueError,
        ):
            return None

    def _read_clock(self) -> datetime:
        """Read and validate the adapter-owned clock without accepting request time."""

        value = self._clock.now()
        if type(value) is not datetime or value.tzinfo is None or value.utcoffset() is None:
            raise SimulatedCorporateActionNavRawMarkContractError(
                "raw mark reader clock is not timezone-aware"
            )
        value.astimezone(UTC)
        return value

    def _read_state(
        self, query: SimulatedCorporateActionNavRawMarkQuery, *, as_of: datetime
    ) -> _ReadState:
        """Read and cross-bind policy, classification, full calendar, and price evidence."""

        binding = self._policy_reader.read_policy(query=query, as_of=as_of)
        if type(binding) is not SimulatedCorporateActionNavRawMarkPolicyBinding:
            raise SimulatedCorporateActionNavRawMarkContractError(
                "raw mark current policy is unavailable"
            )
        completed = self._read_clock()
        if completed < as_of:
            raise SimulatedCorporateActionNavRawMarkContractError(
                "raw mark clock reversed during policy read"
            )
        as_of = completed
        binding.validate_for(as_of=as_of)
        classification = self._classification_reader.resolve_simulated_instrument_classification(
            security_id=query.security_id,
            asset_code=query.asset_code,
            as_of=as_of,
        )
        if type(classification) is not SimulatedInstrumentClassificationEvidenceV1:
            raise SimulatedCorporateActionNavRawMarkContractError(
                "raw mark current classification is unavailable"
            )
        classification.validate_at(as_of=as_of)
        self._validate_classification(query, binding, classification)

        identity = classification.identity_evidence.source_evidence
        calendar = self._calendar_reader.get_effective_execution_calendar(
            exchange=identity.source_exchange,
            as_of=as_of,
            coverage_start=None,
        )
        if type(calendar) is not ExecutionCalendarEvidence:
            raise SimulatedCorporateActionNavRawMarkContractError(
                "raw mark published execution calendar is unavailable"
            )
        if calendar.snapshot.exchange != identity.source_exchange:
            raise SimulatedCorporateActionNavRawMarkContractError(
                "raw mark execution calendar has a different exchange"
            )
        calendar.validate_for(as_of)
        trade_date = self._latest_trade_date(calendar, as_of)
        if trade_date is None:
            raise SimulatedCorporateActionNavRawMarkContractError(
                "raw mark published calendar has no closed open session"
            )
        interval_end_at = cn_market_session_close_utc(trade_date)
        if interval_end_at > as_of:
            raise SimulatedCorporateActionNavRawMarkContractError(
                "raw mark selected a session that has not closed"
            )

        result = self._get_price_source(
            query.asset_code,
            trade_date=trade_date,
            knowledge_cutoff=as_of,
            publication_key=binding.policy.publication_key,
        )
        self._validate_price_result(
            result,
            binding=binding,
            query=query,
            trade_date=trade_date,
            interval_end_at=interval_end_at,
            cutoff=as_of,
        )
        return _ReadState(
            policy_binding=binding,
            classification=classification,
            calendar=calendar,
            trade_date=trade_date,
            interval_end_at=interval_end_at,
            source_result=result,
        )

    @staticmethod
    def _validate_classification(
        query: SimulatedCorporateActionNavRawMarkQuery,
        binding: SimulatedCorporateActionNavRawMarkPolicyBinding,
        classification: SimulatedInstrumentClassificationEvidenceV1,
    ) -> None:
        """Require exact query type and runtime profile selection from source evidence."""

        identity = classification.identity_evidence.source_evidence
        selection = classification.identity_evidence.selection
        if (
            identity.security_id != query.security_id
            or identity.asset_code != query.asset_code
            or classification.simulated_asset_type != query.asset_type
            or query.asset_type not in binding.policy.supported_asset_types
            or selection.profile_id != binding.profile_id
            or selection.profile_key != binding.profile_key
            or selection.environment != binding.runtime_environment
            or selection.profile_version != binding.profile_version
            or selection.profile_content_hash != binding.profile_content_sha256
            or selection.runtime_snapshot_id != binding.snapshot_id
            or selection.runtime_snapshot_hash != binding.snapshot_content_sha256
            or selection.profile_activated_at != binding.profile_activated_at
            or selection.runtime_snapshot_generated_at != binding.snapshot_generated_at
        ):
            raise SimulatedCorporateActionNavRawMarkContractError(
                "raw mark classification is outside its explicit policy and query scope"
            )

    @staticmethod
    def _latest_trade_date(calendar: ExecutionCalendarEvidence, as_of: datetime) -> date | None:
        """Resolve the latest closed session only from the complete published calendar."""

        publication = calendar.publication
        if publication is None or publication.timezone_name != "Asia/Shanghai":
            return None
        local_date = as_of.astimezone(ZoneInfo(publication.timezone_name)).date()
        day_rows = {item.calendar_date: item for item in calendar.snapshot.days}
        if local_date not in day_rows:
            return None
        open_sessions = frozenset(day for day, row in day_rows.items() if row.is_open)
        selected = latest_closed_cn_market_session(as_of, open_sessions=open_sessions)
        if selected is None or selected not in day_rows or not day_rows[selected].is_open:
            return None
        return selected

    @classmethod
    def _validate_price_result(
        cls,
        result: PublishedPriceSourceResult,
        *,
        binding: SimulatedCorporateActionNavRawMarkPolicyBinding,
        query: SimulatedCorporateActionNavRawMarkQuery,
        trade_date: date,
        interval_end_at: datetime,
        cutoff: datetime,
    ) -> None:
        """Require verified exact daily source evidence, CNY units, and known clocks."""

        if type(result) is not PublishedPriceSourceResult or result.evidence is None:
            raise SimulatedCorporateActionNavRawMarkContractError(
                "raw mark daily price source evidence is unavailable"
            )
        if result.freshness_status not in {"fresh", "latest_completed_session"}:
            raise SimulatedCorporateActionNavRawMarkContractError(
                "raw mark daily price source is not current"
            )
        evidence = result.evidence
        policy = binding.policy
        if (
            type(evidence) is not PublishedPriceSourceEvidence
            or type(evidence.values) is not ExactPriceBarValues
        ):
            raise SimulatedCorporateActionNavRawMarkContractError(
                "raw mark daily source value contract is invalid"
            )
        evidence.values.__post_init__()
        if (
            evidence.asset_code != query.asset_code
            or evidence.trade_date != trade_date
            or evidence.publication_key != policy.publication_key
            or evidence.source != policy.source
            or type(evidence.adjustment) is not PriceAdjustment
            or evidence.adjustment is not PriceAdjustment.NONE
            or policy.frequency != "1d"
            or policy.adjustment != "none"
            or evidence.observation_basis != "daily_interval_end"
            or policy.observation_basis != "daily_interval_end"
            or evidence.interval_end_at != interval_end_at
            or evidence.local_known_at != evidence.available_at
            or evidence.source_observed_at is not None
            or evidence.volume_unit != "shares"
            or evidence.amount_unit != "CNY"
            or policy.currency != "CNY"
            or evidence.availability_basis != "local_response_body_completion"
            or evidence.knowledge_cutoff != cutoff
        ):
            raise SimulatedCorporateActionNavRawMarkContractError(
                "raw mark price source differs from its policy, date, or exact units"
            )
        clocks = (
            evidence.interval_end_at,
            evidence.local_known_at,
            evidence.fact_recorded_at,
            evidence.publication_as_of,
            evidence.publication_published_at,
            evidence.knowledge_cutoff,
        )
        for value in clocks:
            cls._require_clock_at_or_before(value, cutoff)
        if evidence.source_published_at is not None:
            cls._require_clock_at_or_before(evidence.source_published_at, cutoff)
        if not (
            evidence.interval_end_at
            <= evidence.publication_as_of
            <= evidence.publication_published_at
            <= cutoff
            and evidence.interval_end_at <= evidence.local_known_at <= cutoff
            and evidence.fact_recorded_at <= cutoff
        ):
            raise SimulatedCorporateActionNavRawMarkContractError(
                "raw mark source or capture clock ordering is invalid"
            )
        if evidence.source_published_at is not None and not (
            evidence.interval_end_at <= evidence.source_published_at <= evidence.local_known_at
        ):
            raise SimulatedCorporateActionNavRawMarkContractError(
                "raw mark source publication clock is inconsistent"
            )

    @staticmethod
    def _require_clock_at_or_before(value: datetime, cutoff: datetime) -> None:
        """Reject a missing or future retained clock without substituting another one."""

        if type(value) is not datetime or value.tzinfo is None or value.utcoffset() is None:
            raise SimulatedCorporateActionNavRawMarkContractError(
                "raw mark source contains an invalid clock"
            )
        if value > cutoff:
            raise SimulatedCorporateActionNavRawMarkContractError(
                "raw mark source contains a clock later than its knowledge cutoff"
            )

    @staticmethod
    def _deadline(interval_end_at: datetime, freshness_window_seconds: int) -> datetime:
        """Anchor the finite price age at the daily interval end, not retrieval time."""

        try:
            return interval_end_at.astimezone(UTC) + timedelta(seconds=freshness_window_seconds)
        except (OverflowError, TypeError, ValueError) as error:
            raise SimulatedCorporateActionNavRawMarkContractError(
                "raw mark freshness deadline is not representable"
            ) from error

    @staticmethod
    def _same_selected_evidence(first: _ReadState, final: _ReadState) -> bool:
        """Reject policy, identity, calendar, or publication changes during the read."""

        first_price = first.source_result.evidence
        final_price = final.source_result.evidence
        if first_price is None or final_price is None:
            return False
        first_identity = first.classification.identity_evidence
        final_identity = final.classification.identity_evidence
        first_selection = first_identity.selection
        final_selection = final_identity.selection
        stable_selection = replace(first_selection, selected_at=final_selection.selected_at)
        return (
            first.policy_binding.selection_sha256 == final.policy_binding.selection_sha256
            and first.classification.selector.content_hash
            == final.classification.selector.content_hash
            and first_identity.source_evidence == final_identity.source_evidence
            and first_identity.security_id == final_identity.security_id
            and first_identity.asset_code == final_identity.asset_code
            and first_identity.source_occurrence_id == final_identity.source_occurrence_id
            and first_identity.reference_response_completed_at
            == final_identity.reference_response_completed_at
            and stable_selection == final_selection
            and first.calendar.evidence_hash == final.calendar.evidence_hash
            and first.trade_date == final.trade_date
            and first.interval_end_at == final.interval_end_at
            and replace(first_price, knowledge_cutoff=final_price.knowledge_cutoff) == final_price
        )


__all__ = (
    "PublishedDailyPriceReader",
    "PublishedPriceCorporateActionNavRawMarkReader",
    "SimulatedCorporateActionNavRawMarkClock",
)
