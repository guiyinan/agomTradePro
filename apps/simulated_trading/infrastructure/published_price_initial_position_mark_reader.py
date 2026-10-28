"""Build an initial-position mark from explicitly configured published evidence."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from typing import Protocol

from apps.data_center.application.price_response_capture import ExactPriceBarValues
from apps.data_center.application.published_price_source import (
    PublishedPriceSourceEvidence,
    PublishedPriceSourceResult,
)
from apps.data_center.domain.enums import PriceAdjustment
from apps.data_center.domain.market_time import (
    CN_MARKET_TIMEZONE,
    cn_market_session_close_utc,
    latest_closed_cn_market_session,
)
from apps.simulated_trading.application.execution_current_reference_classification import (
    CurrentReferenceClassificationReader,
)
from apps.simulated_trading.application.execution_settlement_uow import (
    PublishedExecutionCalendarReader,
    SimulatedTradeExecutionBlocked,
)
from apps.simulated_trading.domain.execution_instrument_classification import (
    SimulatedInstrumentClassificationEvidenceV1,
)
from apps.simulated_trading.domain.execution_settlement_calendar import (
    ExecutionCalendarEvidence,
)
from apps.simulated_trading.domain.execution_settlement_identity import (
    IdentityEvidenceValidationError,
)
from apps.simulated_trading.domain.execution_settlement_primitives import (
    CalendarEvidenceValidationError,
)
from apps.simulated_trading.domain.initial_position_mark import (
    InitialPositionMarkProof,
    InitialPositionMarkValidationError,
    _require_mark_clock,
    _require_mark_hash,
    _require_mark_token,
)
from apps.simulated_trading.domain.initial_position_mark_policy import (
    InitialPositionMarkPolicy,
    InitialPositionMarkPolicyBinding,
)
from core.exceptions import DataFetchError, DataValidationError


class InitialPositionMarkPolicyReader(Protocol):
    """Read the explicit current policy together with verified runtime provenance."""

    def read_policy(self, *, as_of: datetime) -> InitialPositionMarkPolicyBinding | None:
        """Return the active policy at this cutoff, or ``None`` when it is unavailable."""


class PublishedPriceSourceReader(Protocol):
    """Read one exact daily-price publication through the public Data Center port."""

    def __call__(
        self,
        asset_code: str,
        *,
        trade_date: date,
        knowledge_cutoff: datetime,
        publication_key: str,
    ) -> PublishedPriceSourceResult:
        """Return verified source evidence or an explicit blocked result."""


class PublishedPriceInitialPositionMarkReader:
    """Read a sealed first-position mark from a source-backed daily close.

    The adapter requires an explicit runtime policy, a current source-derived
    instrument classification, a formally published execution calendar, and a
    price publication whose retained response was already verified by Data
    Center. It records a mark only; it does not represent execution, liquidity,
    trading authority, or a fill price. A failed or incomplete dependency
    returns ``None`` so the caller blocks first-position creation.
    """

    def __init__(
        self,
        *,
        policy_reader: InitialPositionMarkPolicyReader,
        classification_reader: CurrentReferenceClassificationReader,
        calendar_reader: PublishedExecutionCalendarReader,
        get_price_source: PublishedPriceSourceReader,
    ) -> None:
        """Bind explicit read-only application ports without reading at construction."""

        self._policy_reader = policy_reader
        self._classification_reader = classification_reader
        self._calendar_reader = calendar_reader
        self._get_price_source = get_price_source

    def read_initial_position_mark(
        self,
        *,
        security_id: str,
        asset_code: str,
        asset_type: str,
        market: str,
        board: str,
        read_at: datetime,
    ) -> InitialPositionMarkProof | None:
        """Return source-backed apply-time mark evidence or block with ``None``."""

        try:
            self._validate_request(
                security_id=security_id,
                asset_code=asset_code,
                asset_type=asset_type,
                market=market,
                board=board,
                read_at=read_at,
            )
            return self._read(
                security_id=security_id,
                asset_code=asset_code,
                asset_type=asset_type,
                market=market,
                board=board,
                read_at=read_at,
            )
        except (
            CalendarEvidenceValidationError,
            DataFetchError,
            DataValidationError,
            IdentityEvidenceValidationError,
            InitialPositionMarkValidationError,
            SimulatedTradeExecutionBlocked,
            ArithmeticError,
            AttributeError,
            TypeError,
            ValueError,
        ):
            return None

    def _read(
        self,
        *,
        security_id: str,
        asset_code: str,
        asset_type: str,
        market: str,
        board: str,
        read_at: datetime,
    ) -> InitialPositionMarkProof | None:
        """Resolve policy, classification, calendar and source at one read cutoff."""

        initial_binding = self._policy_reader.read_policy(as_of=read_at)
        if type(initial_binding) is not InitialPositionMarkPolicyBinding:
            return None
        initial_binding.validate_at(as_of=read_at)
        policy = initial_binding.policy

        classification = self._classification_reader.resolve_simulated_instrument_classification(
            security_id=security_id,
            asset_code=asset_code,
            as_of=read_at,
        )
        if type(classification) is not SimulatedInstrumentClassificationEvidenceV1:
            return None
        classification.validate_at(as_of=read_at)
        if classification.read_at != read_at:
            return None
        identity = classification.identity_evidence.source_evidence
        selection = classification.identity_evidence.selection
        provenance = initial_binding.provenance
        if (
            identity.security_id != security_id
            or identity.asset_code != asset_code
            or classification.simulated_asset_type != asset_type
            or identity.rule_market != market
            or identity.board != board
            or selection.profile_id != provenance.profile_id
            or selection.profile_key != provenance.profile_key
            or selection.environment != provenance.runtime_environment
            or selection.profile_version != provenance.profile_version
            or selection.profile_content_hash != provenance.profile_content_hash
            or selection.runtime_snapshot_id != provenance.snapshot_id
            or selection.runtime_snapshot_hash != provenance.snapshot_content_hash
            or selection.profile_activated_at != provenance.profile_activated_at
            or selection.runtime_snapshot_generated_at != provenance.snapshot_generated_at
            or asset_type not in policy.supported_asset_types
        ):
            return None

        calendar = self._calendar_reader.get_effective_execution_calendar(
            exchange=identity.source_exchange,
            as_of=read_at,
            coverage_start=None,
        )
        if type(calendar) is not ExecutionCalendarEvidence:
            return None
        if calendar.snapshot.exchange != identity.source_exchange:
            return None
        calendar.validate_for(read_at)
        publication = calendar.publication
        if publication is None or publication.timezone_name != "Asia/Shanghai":
            return None
        local_date = read_at.astimezone(CN_MARKET_TIMEZONE).date()
        calendar_days = {day.calendar_date: day for day in calendar.snapshot.days}
        if local_date not in calendar_days:
            return None
        open_sessions = frozenset(
            day.calendar_date for day in calendar.snapshot.days if day.is_open
        )
        trade_date = latest_closed_cn_market_session(read_at, open_sessions=open_sessions)
        if trade_date is None or trade_date not in open_sessions:
            return None
        observed_at = cn_market_session_close_utc(trade_date)
        if observed_at > read_at:
            return None

        source_result = self._get_price_source(
            asset_code=asset_code,
            trade_date=trade_date,
            knowledge_cutoff=read_at,
            publication_key=policy.publication_key,
        )
        if type(source_result) is not PublishedPriceSourceResult:
            return None
        evidence = source_result.evidence
        if evidence is None or source_result.freshness_status not in {
            "fresh",
            "latest_completed_session",
        }:
            return None
        self._validate_price_evidence(
            evidence,
            policy=policy,
            asset_code=asset_code,
            trade_date=trade_date,
            observed_at=observed_at,
            read_at=read_at,
        )

        final_binding = self._policy_reader.read_policy(as_of=read_at)
        if type(final_binding) is not InitialPositionMarkPolicyBinding:
            return None
        final_binding.validate_at(as_of=read_at)
        if final_binding != initial_binding:
            return None

        try:
            valid_until = evidence.observed_at.astimezone(UTC) + timedelta(
                seconds=policy.freshness_window_seconds
            )
        except (OverflowError, TypeError, ValueError) as error:
            raise InitialPositionMarkValidationError(
                "initial-position mark freshness deadline cannot be represented"
            ) from error
        return InitialPositionMarkProof(
            security_id=identity.security_id,
            asset_code=identity.asset_code,
            asset_type=classification.simulated_asset_type,
            market=identity.rule_market,
            board=identity.board,
            price=evidence.values.close,
            source_observed_at=evidence.observed_at,
            source_available_at=evidence.source_published_at,
            read_at=read_at,
            publication_as_of=evidence.publication_as_of,
            published_at=evidence.publication_published_at,
            valid_until=valid_until,
            freshness_window_seconds=policy.freshness_window_seconds,
            source_identity=evidence.source,
            source_record_id=evidence.fact_pk,
            source_content_hash=evidence.fact_content_hash,
            publication_id=evidence.publication_id,
            publication_hash=evidence.publication_hash,
            policy_identity=policy.identity,
            policy_content_hash=initial_binding.proof_content_hash,
        )

    @staticmethod
    def _validate_request(
        *,
        security_id: str,
        asset_code: str,
        asset_type: str,
        market: str,
        board: str,
        read_at: datetime,
    ) -> None:
        """Reject malformed caller identity before opening any external read port."""

        for field_name, value in (
            ("security_id", security_id),
            ("asset_code", asset_code),
            ("asset_type", asset_type),
            ("market", market),
            ("board", board),
        ):
            _require_mark_token(value, field_name)
        _require_mark_clock(read_at, "read_at")

    @staticmethod
    def _validate_price_evidence(
        evidence: PublishedPriceSourceEvidence,
        *,
        policy: InitialPositionMarkPolicy,
        asset_code: str,
        trade_date: date,
        observed_at: datetime,
        read_at: datetime,
    ) -> None:
        """Recheck source scope, exact units, adjustment, and known chronology."""

        if type(policy) is not InitialPositionMarkPolicy:
            raise InitialPositionMarkValidationError("initial-position mark policy is invalid")
        if type(evidence) is not PublishedPriceSourceEvidence:
            raise InitialPositionMarkValidationError("published price source evidence is invalid")
        if (
            evidence.asset_code != asset_code
            or evidence.trade_date != trade_date
            or evidence.publication_key != policy.publication_key
            or evidence.source != policy.source
            or type(evidence.adjustment) is not PriceAdjustment
            or evidence.adjustment.value != policy.adjustment
            or policy.frequency != "1d"
            or evidence.volume_unit != "shares"
            or evidence.amount_unit != "CNY"
            or evidence.availability_basis != "local_response_body_completion"
            or type(evidence.values) is not ExactPriceBarValues
            or evidence.observed_at != observed_at
        ):
            raise InitialPositionMarkValidationError(
                "published price source scope or exact bar semantics do not match policy"
            )
        evidence.values.__post_init__()
        _require_mark_token(evidence.publication_id, "publication_id")
        _require_mark_token(evidence.fact_pk, "source_record_id")
        _require_mark_token(evidence.source, "source_identity")
        for field_name in (
            "publication_hash",
            "fact_content_hash",
            "manifest_hash",
        ):
            _require_mark_hash(getattr(evidence, field_name), field_name)
        for field_name in (
            "observed_at",
            "available_at",
            "fact_recorded_at",
            "publication_as_of",
            "publication_published_at",
            "knowledge_cutoff",
        ):
            _require_mark_clock(getattr(evidence, field_name), field_name)
        if evidence.source_published_at is not None:
            _require_mark_clock(evidence.source_published_at, "source_published_at")
        if evidence.knowledge_cutoff != read_at:
            raise InitialPositionMarkValidationError(
                "published price source cutoff differs from the mark read time"
            )
        if not (
            evidence.observed_at
            <= evidence.publication_as_of
            <= evidence.publication_published_at
            <= read_at
        ):
            raise InitialPositionMarkValidationError(
                "published price publication chronology is invalid"
            )
        if not (
            evidence.observed_at <= evidence.available_at <= evidence.publication_published_at
            and evidence.fact_recorded_at <= read_at
        ):
            raise InitialPositionMarkValidationError(
                "published price local acquisition chronology is invalid"
            )
        if evidence.source_published_at is not None and not (
            evidence.observed_at <= evidence.source_published_at <= read_at
        ):
            raise InitialPositionMarkValidationError(
                "published price source publication clock is outside the cutoff"
            )


__all__ = (
    "InitialPositionMarkPolicyReader",
    "PublishedPriceInitialPositionMarkReader",
    "PublishedPriceSourceReader",
)
