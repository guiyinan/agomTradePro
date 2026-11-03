"""Compose read-only Risk evidence from an already retained close capture."""

from __future__ import annotations

import hashlib
import logging
from datetime import date, datetime

from apps.data_center.domain.sina_quote_capture import (
    SINA_QUOTE_SOURCE_ID,
    SinaQuoteCapture,
)
from apps.risk_center.application.execution_settlement_v3 import (
    ReadEffectiveExecutionSettlementV3UseCase,
)
from apps.risk_center.application.portfolio_risk_assets import (
    CloseSnapshotSessionEvidence,
    CloseSnapshotSessionEvidenceProvider,
)
from apps.risk_center.application.portfolio_risk_policy import PortfolioRiskSourceReference
from apps.risk_center.domain.portfolio_risk_clock_evidence import PortfolioRiskCaptureReceipt
from apps.simulated_trading.application.portfolio_risk_calendar import (
    PortfolioRiskCurrentIdentityReader,
    PortfolioRiskPublishedCalendarReader,
)
from apps.simulated_trading.close_snapshot_submission_composition import (
    CloseSnapshotPolicyBindingReader,
    build_current_close_snapshot_policy_binding_reader,
    evaluate_close_snapshot_for_stop_loss,
)
from apps.simulated_trading.domain.execution_current_reference import (
    ExecutionInstrumentIdentityEvidenceV2,
)
from apps.simulated_trading.domain.execution_settlement_calendar import ExecutionCalendarEvidence
from core.exceptions import AgomTradeProException

logger = logging.getLogger(__name__)


class _RetainedCloseSnapshotSessionEvidenceProvider:
    """Evaluate the pinned capture against current identity, calendar, and rule reads."""

    def __init__(
        self,
        *,
        binding_reader: CloseSnapshotPolicyBindingReader,
        identity_reader: PortfolioRiskCurrentIdentityReader,
        calendar_reader: PortfolioRiskPublishedCalendarReader,
        settlement_reader: ReadEffectiveExecutionSettlementV3UseCase,
    ) -> None:
        """Keep the exact public readers composed for the owner risk service."""

        self._binding_reader = binding_reader
        self._identity_reader = identity_reader
        self._calendar_reader = calendar_reader
        self._settlement_reader = settlement_reader

    def read_evidence(
        self,
        *,
        capture: SinaQuoteCapture,
        source_reference: PortfolioRiskSourceReference,
        receipt: PortfolioRiskCaptureReceipt,
        retained_payload_hash: str,
        account_id: int,
        asset_code: str,
        security_id: str,
        trading_date: date,
        as_of: datetime,
    ) -> CloseSnapshotSessionEvidence | None:
        """Evaluate one exact admitted capture without fetching or creating an order."""

        if not _capture_matches_reference(
            capture=capture,
            source_reference=source_reference,
            receipt=receipt,
            retained_payload_hash=retained_payload_hash,
            account_id=account_id,
            asset_code=asset_code,
            security_id=security_id,
            trading_date=trading_date,
            as_of=as_of,
        ):
            return None
        try:
            binding = self._binding_reader.read_binding(
                account_id=account_id,
                security_id=security_id,
                asset_code=asset_code,
                as_of=as_of,
            )
            identity = self._identity_reader.get_execution_instrument_identity(
                security_id=security_id,
                asset_code=asset_code,
                as_of=as_of,
            )
            if type(identity) is not ExecutionInstrumentIdentityEvidenceV2:
                return None
            calendar = self._calendar_reader.get_effective_execution_calendar(
                exchange=identity.source_exchange,
                as_of=as_of,
                coverage_start=trading_date,
            )
            if type(calendar) is not ExecutionCalendarEvidence:
                return None
            execution_bundle = self._settlement_reader.execute(
                security_id=security_id,
                as_of=as_of,
            )
            evaluation = evaluate_close_snapshot_for_stop_loss(
                binding_reader=self._binding_reader,
                binding=binding,
                capture=capture,
                account_id=account_id,
                identity=identity,
                calendar_evidence=calendar,
                execution_bundle=execution_bundle,
                as_of=as_of,
            )
        except (
            AgomTradeProException,
            ArithmeticError,
            TypeError,
            ValueError,
        ) as error:
            logger.info(
                "close-snapshot portfolio-risk evaluation is unavailable",
                extra={"reason_code": _reason_code(error)},
            )
            return None
        return CloseSnapshotSessionEvidence(evaluation=evaluation)


def build_portfolio_risk_close_snapshot_session_provider(
    *,
    environment: str,
    identity_reader: PortfolioRiskCurrentIdentityReader,
    calendar_reader: PortfolioRiskPublishedCalendarReader,
    settlement_reader: ReadEffectiveExecutionSettlementV3UseCase,
) -> CloseSnapshotSessionEvidenceProvider:
    """Build the exact read-only close evaluator used by ordinary risk consumers."""

    return _RetainedCloseSnapshotSessionEvidenceProvider(
        binding_reader=build_current_close_snapshot_policy_binding_reader(environment=environment),
        identity_reader=identity_reader,
        calendar_reader=calendar_reader,
        settlement_reader=settlement_reader,
    )


def _capture_matches_reference(
    *,
    capture: SinaQuoteCapture,
    source_reference: PortfolioRiskSourceReference,
    receipt: PortfolioRiskCaptureReceipt,
    retained_payload_hash: str,
    account_id: int,
    asset_code: str,
    security_id: str,
    trading_date: date,
    as_of: datetime,
) -> bool:
    """Reject captures whose bytes, transport receipt, pin, or request scope differ."""

    try:
        capture.__post_init__()
        source_reference.__post_init__()
        receipt.__post_init__()
    except (ArithmeticError, TypeError, ValueError):
        return False
    if (
        source_reference.kind != "execution_session_state"
        or source_reference.clock_evidence_mode != "policy_bounded_close_snapshot_state"
        or source_reference.asset_code != asset_code
        or source_reference.security_id != security_id
        or source_reference.raw_payload_hash != retained_payload_hash
        or source_reference.source_record_id != receipt.source_record_id
        or type(account_id) is not int
        or account_id < 1
        or type(trading_date) is not date
        or type(as_of) is not datetime
        or as_of.tzinfo is None
        or as_of.utcoffset() is None
        or capture.asset_code != asset_code
        or receipt.source_id != SINA_QUOTE_SOURCE_ID
        or receipt.original_body_sha256 != hashlib.sha256(capture.body).hexdigest()
        or receipt.original_body_sha256 != capture.body_sha256
        or receipt.response_completed_at != capture.response_completed_at
        or receipt.http_status != capture.http_status
        or receipt.body_size_bytes != capture.body_size_bytes
        or not receipt.body_complete
        or not 200 <= capture.http_status < 300
    ):
        return False
    return True


def _reason_code(error: Exception) -> str:
    """Return an exception's stable application code without leaking payloads."""

    if isinstance(error, AgomTradeProException):
        return error.code
    return type(error).__name__


__all__: tuple[str, ...] = ("build_portfolio_risk_close_snapshot_session_provider",)
