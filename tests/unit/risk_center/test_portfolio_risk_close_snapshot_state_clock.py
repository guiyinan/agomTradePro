"""Contracts for the finite ASH-03 quote-time state evidence mode."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from zoneinfo import ZoneInfo

import pytest

from apps.data_center.domain.sina_quote_capture import (
    SINA_QUOTE_SOURCE_ID,
    SinaQuoteCapture,
    build_sina_quote_request_url,
    parse_sina_quote_capture,
)
from apps.risk_center.application.close_snapshot_simulation import (
    CloseSnapshotSimulationInput,
    CloseSnapshotSimulationUseCase,
)
from apps.risk_center.application.portfolio_risk_assets import CloseSnapshotSessionEvidence
from apps.risk_center.application.portfolio_risk_clock_report_codec import (
    is_source_clock_evidence_proof,
)
from apps.risk_center.application.portfolio_risk_close_snapshot_state_clock import (
    qualify_policy_bounded_close_snapshot_state,
)
from apps.risk_center.application.portfolio_risk_deadlines import (
    portfolio_risk_execution_deadline_for_evidence,
)
from apps.risk_center.application.portfolio_risk_report import (
    _clock_proof_matches_current_report,
    _source_payload,
)
from apps.risk_center.application.portfolio_risk_source_admission import (
    PortfolioRiskSinaQuoteCaptureMetadata,
)
from apps.risk_center.domain.execution_trading_constraints import SessionState
from apps.risk_center.domain.local_simulated_market_policy import LocalSimulatedCalendarContext
from apps.risk_center.domain.portfolio_risk_clock_evidence import (
    PortfolioRiskCaptureReceipt,
    PortfolioRiskCloseSnapshotStateProof,
)
from apps.risk_center.domain.portfolio_risk_sources import (
    CoverageStatus,
    PortfolioRiskCoverage,
    PortfolioRiskSourceEvidence,
    SourceObservationPrecision,
    qualify_portfolio_risk_source,
)
from apps.risk_center.infrastructure.portfolio_risk_sina_capture_manifest import (
    rebuild_sina_quote_capture_from_manifest,
)
from tests.unit.risk_center.test_close_snapshot_simulation import _policy as _close_policy
from tests.unit.risk_center.test_close_snapshot_simulation import _rule as _close_rule
from tests.unit.risk_center.test_portfolio_risk_timestamp_snapshot_clock import (
    _AS_OF,
    _BUSINESS_DATE,
    _MANIFEST_HASH,
    _policy,
)

_ZONE = ZoneInfo("Asia/Shanghai")
_ASSET_CODE = "600036.SH"
_SECURITY_ID = "equity:SH:600036"
_SOURCE_RECORD_ID = "source-record-1"
_CAPTURE_ID = "capture-close-1"
_PURPOSE = "close_snapshot_simulation"
_RESTRICTIONS = ("vendor_reported_at_quote_time", "close_snapshot_only")


def _capture(*, status: str = "00") -> SinaQuoteCapture:
    """Parse one complete exact Sina body with independent quote and receipt clocks."""

    source_date = _BUSINESS_DATE.isoformat()
    fields = [
        "招商银行",
        "40.00",
        "39.95",
        "40.05",
        "40.10",
        "39.90",
        "40.00",
        "40.05",
        "123456",
        "4930000.00",
        *("" for _ in range(20)),
        source_date,
        "21:58:00",
        status,
        "D|11800|118236.00",
    ]
    body = f'var hq_str_sh600036="{",".join(fields)}";\n'.encode("gb18030")
    url = build_sina_quote_request_url(_ASSET_CODE)
    completed = _AS_OF - timedelta(seconds=30)
    return parse_sina_quote_capture(
        asset_code=_ASSET_CODE,
        requested_url=url,
        final_url=url,
        request_started_at=completed.astimezone(UTC) - timedelta(seconds=5),
        response_completed_at=completed.astimezone(UTC),
        http_status=200,
        http_date=None,
        content_type="application/javascript; charset=GB18030",
        charset="GB18030",
        content_encoding="identity",
        body=body,
    )


def _evaluation(*, status: str = "00") -> CloseSnapshotSessionEvidence:
    """Use the existing ASH-03 application use case for the exact quote source."""

    capture = _capture(status=status)
    policy = _close_policy(
        account_id=12,
        security_id=_SECURITY_ID,
        asset_code=_ASSET_CODE,
        trading_date=_BUSINESS_DATE,
        available_from=datetime(2026, 11, 3, 15, 0, tzinfo=_ZONE),
        available_until=datetime(2026, 11, 3, 23, 30, tzinfo=_ZONE),
    )
    calendar = LocalSimulatedCalendarContext(
        calendar_id="published-close-calendar",
        calendar_version="fixture-v1",
        calendar_source_hash="b" * 64,
        calendar_observed_at=datetime(2026, 11, 3, 14, 59, tzinfo=_ZONE),
        calendar_available_at=datetime(2026, 11, 3, 15, 0, 5, tzinfo=_ZONE),
        calendar_valid_until=datetime(2026, 11, 4, 0, 0, tzinfo=_ZONE),
        trading_date=_BUSINESS_DATE,
        session_id="sh-session-close-proof",
        session_timezone="Asia/Shanghai",
        session_open_at=datetime(2026, 11, 3, 9, 30, tzinfo=_ZONE),
        session_close_at=datetime(2026, 11, 3, 15, 0, tzinfo=_ZONE),
        session_state=SessionState.CLOSED,
    )
    base_rule = _close_rule()
    rule = replace(
        base_rule,
        execution_rule_v1=replace(
            base_rule.execution_rule_v1,
            security_id=_SECURITY_ID,
            valid_until=datetime(2026, 11, 4, 0, 0, tzinfo=_ZONE),
            content_hash="",
        ),
        content_hash="",
    )
    return CloseSnapshotSessionEvidence(
        evaluation=CloseSnapshotSimulationUseCase().evaluate(
            CloseSnapshotSimulationInput(
                capture=capture,
                policy=policy,
                calendar=calendar,
                rule=rule,
                account_id=12,
                security_id=_SECURITY_ID,
                asset_code=_ASSET_CODE,
                trading_date=_BUSINESS_DATE,
                requested_price=(capture.quote.last_price if capture.quote is not None else None),
                as_of=_AS_OF,
            )
        )
    )


def _risk_policy():
    """Return one exact source-pinned policy for close-only session state."""

    return _policy(
        kind="execution_session_state",
        clock_mode="policy_bounded_close_snapshot_state",
    )


def _source_evidence(
    capture: SinaQuoteCapture,
    *,
    known_at: datetime | None = None,
    available_at: datetime | None = None,
    valid_until: datetime | None = None,
    must_not_use: bool = False,
    restrictions: tuple[str, ...] = _RESTRICTIONS,
) -> PortfolioRiskSourceEvidence:
    """Bind exact Sina clocks and prohibited uses without local-clock substitution."""

    assert capture.quote is not None and capture.quote.source_observed_at is not None
    body_hash = sha256(capture.body).hexdigest()
    return PortfolioRiskSourceEvidence(
        source_id=SINA_QUOTE_SOURCE_ID,
        source_record_id=_SOURCE_RECORD_ID,
        original_payload_sha256=body_hash,
        observation_precision=SourceObservationPrecision.TIMESTAMP,
        observed_at=capture.quote.source_observed_at,
        observed_on=None,
        available_at=available_at,
        known_at=known_at or capture.response_completed_at + timedelta(seconds=10),
        decision_cutoff=_AS_OF,
        decision_date_cutoff=None,
        valid_until=valid_until,
        source_purpose=_PURPOSE,
        allowed_purposes=(_PURPOSE,),
        restrictions=restrictions,
        must_not_use_for_decision=must_not_use,
        coverage=PortfolioRiskCoverage(
            status=CoverageStatus.COMPLETE,
            precision_basis="close_quote_record",
            expected_item_count=1,
            observed_item_count=1,
        ),
        effective_on=_BUSINESS_DATE,
    )


def _qualify(
    *,
    session_evidence: CloseSnapshotSessionEvidence | None = None,
    source_evidence: PortfolioRiskSourceEvidence | None = None,
    account_id: int = 12,
    requested_purpose: str = _PURPOSE,
) -> tuple[PortfolioRiskCloseSnapshotStateProof | None, tuple[str, ...]]:
    """Run the production close-state adapter over one exact captured body."""

    capture = _capture()
    risk_policy = _risk_policy()
    receipt = PortfolioRiskCaptureReceipt(
        capture_id=_CAPTURE_ID,
        source_id=SINA_QUOTE_SOURCE_ID,
        source_record_id=_SOURCE_RECORD_ID,
        original_body_sha256=sha256(capture.body).hexdigest(),
        response_completed_at=capture.response_completed_at,
        http_status=capture.http_status,
        body_size_bytes=capture.body_size_bytes,
        body_complete=True,
    )
    result = qualify_policy_bounded_close_snapshot_state(
        policy=risk_policy,
        source_reference=risk_policy.source_references[0],
        retained_payload_hash=_MANIFEST_HASH,
        account_id=account_id,
        source_evidence=source_evidence or _source_evidence(capture),
        receipt=receipt,
        original_body=capture.body,
        source_capture=capture,
        session_evidence=session_evidence or _evaluation(),
        as_of=_AS_OF,
        business_date=_BUSINESS_DATE,
        execution_session=_BUSINESS_DATE,
        requested_purpose=requested_purpose,
    )
    return result.proof, result.reason_codes


def test_close_snapshot_clock_proof_preserves_limited_status_and_round_trips() -> None:
    proof, reasons = _qualify()

    assert reasons == ()
    assert proof is not None
    assert proof.state_basis == "vendor_reported_at_quote_time"
    assert proof.reported_trading_state == "TRADING"
    assert proof.full_session_state == "unknown"
    assert proof.source_available_at is None
    assert proof.source_valid_until is None
    assert proof.policy_known_at == _risk_policy().known_at <= proof.as_of
    assert proof.policy_effective_at == _risk_policy().effective_at <= proof.as_of
    assert proof.close_calendar_session_state == "CLOSED"
    assert proof.close_market_session_state == "CLOSED"
    assert proof.close_usage_deadline == proof.proven_available_at + timedelta(
        seconds=proof.close_usage_ttl_seconds
    )
    assert proof.policy_acceptance_deadline < proof.business_date_deadline

    evidence = _source_evidence(_capture())
    qualified, qualified_reasons = _qualify()
    assert qualified is not None and qualified_reasons == ()
    source_with_proof = replace(evidence, policy_clock_proof=qualified)
    payload = _source_payload(source_with_proof)
    assert payload["available_at"] is None
    assert payload["valid_until"] is None
    assert is_source_clock_evidence_proof(payload["clock_evidence_proof"], payload)


def test_close_snapshot_proof_rejects_known_at_after_decision_cutoff() -> None:
    proof, reasons = _qualify()
    assert proof is not None and reasons == ()

    with pytest.raises(ValueError, match="capture and known-at clocks are inconsistent"):
        replace(proof, known_at=proof.as_of + timedelta(seconds=1))


def test_sina_capture_metadata_rebuilds_only_the_pinned_original_transport() -> None:
    capture = _capture()
    receipt = PortfolioRiskCaptureReceipt(
        capture_id=_CAPTURE_ID,
        source_id=SINA_QUOTE_SOURCE_ID,
        source_record_id=_SOURCE_RECORD_ID,
        original_body_sha256=capture.body_sha256,
        response_completed_at=capture.response_completed_at,
        http_status=capture.http_status,
        body_size_bytes=capture.body_size_bytes,
        body_complete=True,
    )
    payload = capture.to_payload()
    metadata: PortfolioRiskSinaQuoteCaptureMetadata = {
        "asset_code": payload["asset_code"],
        "requested_url": payload["requested_url"],
        "final_url": payload["final_url"],
        "request_started_at": payload["request_started_at"],
        "response_completed_at": payload["response_completed_at"],
        "http_status": payload["http_status"],
        "http_date": payload["http_date"],
        "content_type": payload["content_type"],
        "charset": payload["charset"],
        "content_encoding": payload["content_encoding"],
    }

    rebuilt = rebuild_sina_quote_capture_from_manifest(
        metadata,
        asset_code=_ASSET_CODE,
        original_url=capture.requested_url,
        original_body=capture.body,
        receipt=receipt,
    )

    assert rebuilt == capture
    tampered = dict(metadata)
    tampered["response_completed_at"] = (_AS_OF - timedelta(seconds=10)).isoformat()
    with pytest.raises(ValueError, match="transport metadata differs"):
        rebuild_sina_quote_capture_from_manifest(
            tampered,
            asset_code=_ASSET_CODE,
            original_url=capture.requested_url,
            original_body=capture.body,
            receipt=receipt,
        )


def test_close_snapshot_proof_requires_exact_purpose_receipt_and_ash03_qualification() -> None:
    capture = _capture()
    assert _qualify(requested_purpose="ash07_capacity")[0] is None
    assert _qualify(account_id=13)[0] is None
    assert _qualify(
        source_evidence=_source_evidence(capture, known_at=capture.response_completed_at)
    )[0]
    assert (
        _qualify(
            source_evidence=_source_evidence(capture, available_at=capture.response_completed_at)
        )[0]
        is None
    )
    assert _qualify(source_evidence=_source_evidence(capture, must_not_use=True))[0] is None
    assert (
        _qualify(source_evidence=_source_evidence(capture, known_at=_AS_OF + timedelta(seconds=1)))[
            0
        ]
        is None
    )
    assert _qualify(source_evidence=_source_evidence(capture, restrictions=()))[0] is None
    assert _qualify(session_evidence=_evaluation(status="02"))[0] is None


def test_close_only_clock_proof_does_not_qualify_a_regular_execution_source() -> None:
    capture = _capture()
    proof, reasons = _qualify()
    assert proof is not None and reasons == ()
    evidence = replace(_source_evidence(capture), policy_clock_proof=proof)
    ordinary = qualify_portfolio_risk_source(
        evidence=evidence,
        requested_purpose="ash07_capacity",
        allowed_observation_precisions=(SourceObservationPrecision.TIMESTAMP,),
        as_of=_AS_OF,
        allowed_restrictions=_RESTRICTIONS,
        expected_source_kind="execution_session_state",
    )
    assert not ordinary.eligible
    assert "RISK_SOURCE_AVAILABLE_AT_UNKNOWN" in ordinary.reason_codes
    assert "RISK_SOURCE_VALID_UNTIL_UNKNOWN" in ordinary.reason_codes


def test_close_snapshot_deadline_is_rebound_to_account_policy_and_exact_reference() -> None:
    capture = _capture()
    proof, reasons = _qualify()
    assert proof is not None and reasons == ()
    evidence = replace(_source_evidence(capture), policy_clock_proof=proof)
    policy = _risk_policy()
    deadline = portfolio_risk_execution_deadline_for_evidence(
        evidence,
        policy,
        account_id=12,
        business_timezone=_ZONE,
        additional_policy_deadlines=(),
        requested_purpose=_PURPOSE,
    )
    assert deadline == proof.policy_acceptance_deadline
    assert (
        portfolio_risk_execution_deadline_for_evidence(
            evidence,
            policy,
            account_id=13,
            business_timezone=_ZONE,
            additional_policy_deadlines=(),
            requested_purpose=_PURPOSE,
        )
        is None
    )


def test_close_proof_report_rebind_rejects_account_and_policy_reference_reuse() -> None:
    capture = _capture()
    proof, reasons = _qualify()
    assert proof is not None and reasons == ()
    evidence = replace(_source_evidence(capture), policy_clock_proof=proof)
    policy = _risk_policy()
    reference = policy.source_references[0]
    assert _clock_proof_matches_current_report(
        proof=proof,
        reference=reference,
        policy=policy,
        evidence=evidence,
        account_id=12,
        as_of=_AS_OF,
        business_date=_BUSINESS_DATE,
        execution_session=_BUSINESS_DATE,
    )
    assert not _clock_proof_matches_current_report(
        proof=proof,
        reference=reference,
        policy=policy,
        evidence=evidence,
        account_id=13,
        as_of=_AS_OF,
        business_date=_BUSINESS_DATE,
        execution_session=_BUSINESS_DATE,
    )
    assert not _clock_proof_matches_current_report(
        proof=proof,
        reference=replace(reference, raw_payload_hash="sha256:" + "b" * 64),
        policy=policy,
        evidence=evidence,
        account_id=12,
        as_of=_AS_OF,
        business_date=_BUSINESS_DATE,
        execution_session=_BUSINESS_DATE,
    )
    assert not _clock_proof_matches_current_report(
        proof=replace(proof, profile_content_hash="d" * 64),
        reference=reference,
        policy=policy,
        evidence=evidence,
        account_id=12,
        as_of=_AS_OF,
        business_date=_BUSINESS_DATE,
        execution_session=_BUSINESS_DATE,
    )
    assert (
        portfolio_risk_execution_deadline_for_evidence(
            evidence,
            policy,
            account_id=12,
            business_timezone=_ZONE,
            additional_policy_deadlines=(),
            requested_purpose="ash07_capacity",
        )
        is None
    )


@pytest.mark.parametrize(
    "mutation", ("prohibited", "research_only", "purpose", "record", "policy_restrictions")
)
def test_close_deadline_rejects_rebound_or_prohibited_evidence(mutation: str) -> None:
    capture = _capture()
    proof, reasons = _qualify()
    assert proof is not None and reasons == ()
    evidence = replace(_source_evidence(capture), policy_clock_proof=proof)
    policy = _risk_policy()
    if mutation == "prohibited":
        evidence = replace(evidence, must_not_use_for_decision=True)
    elif mutation == "research_only":
        evidence = replace(evidence, restrictions=(*_RESTRICTIONS, "research_only"))
    elif mutation == "purpose":
        evidence = replace(evidence, allowed_purposes=("other_simulation",))
    elif mutation == "record":
        proof = replace(proof, source_record_id="different-record")
        evidence = replace(evidence, source_record_id="different-record", policy_clock_proof=proof)
    else:
        with pytest.raises(ValueError, match="explicitly restricted timestamp policy"):
            replace(
                policy,
                capacity_policy=replace(policy.capacity_policy, allowed_source_restrictions=()),
            )
        return
    assert (
        portfolio_risk_execution_deadline_for_evidence(
            evidence,
            policy,
            account_id=12,
            business_timezone=_ZONE,
            additional_policy_deadlines=(),
            requested_purpose=_PURPOSE,
        )
        is None
    )
