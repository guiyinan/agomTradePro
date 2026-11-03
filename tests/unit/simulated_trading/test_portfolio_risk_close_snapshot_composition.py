"""Focused contracts for close-only purpose selection at the Risk consumer boundary."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from typing import Literal

from apps.data_center.domain.sina_quote_capture import (
    SinaQuoteCapture,
    build_sina_quote_request_url,
    parse_sina_quote_capture,
)
from apps.risk_center.application.portfolio_risk_assets import PortfolioRiskAssetIdentity
from apps.risk_center.application.portfolio_risk_policy import (
    PortfolioRiskClockEvidenceMode,
    PortfolioRiskSourceReference,
)
from apps.risk_center.domain.portfolio_risk_clock_evidence import PortfolioRiskCaptureReceipt
from apps.simulated_trading.application.portfolio_risk_preparation import (
    CAPACITY_REQUESTED_PURPOSE,
    CLOSE_SNAPSHOT_REQUESTED_PURPOSE,
    _capacity_requested_purpose,
)
from apps.simulated_trading.portfolio_risk_close_snapshot_composition import (
    _capture_matches_reference,
)


def _reference(
    *,
    kind: Literal["execution_session_state", "capacity_window"] = "execution_session_state",
    asset_code: str = "600036.SH",
    security_id: str = "600036001",
    clock_evidence_mode: PortfolioRiskClockEvidenceMode = "policy_bounded_close_snapshot_state",
) -> PortfolioRiskSourceReference:
    return PortfolioRiskSourceReference(
        kind=kind,
        asset_code=asset_code,
        security_id=security_id,
        raw_payload_hash="sha256:" + ("a" * 64),
        source_record_id="capture-600036-session",
        clock_evidence_mode=clock_evidence_mode,
    )


def test_close_purpose_requires_exact_requested_asset_and_security_pin() -> None:
    references = (_reference(),)
    requested = (PortfolioRiskAssetIdentity("600036.SH", "600036001"),)

    assert _capacity_requested_purpose(references, requested) == CLOSE_SNAPSHOT_REQUESTED_PURPOSE


def test_unrequested_or_non_close_source_keeps_ordinary_capacity_purpose() -> None:
    requested = (PortfolioRiskAssetIdentity("601398.SH", "601398001"),)
    unrelated_close_reference = (_reference(),)
    wrong_security_reference = (_reference(security_id="600036002"),)
    non_close_reference = (_reference(clock_evidence_mode="source_clocks_required"),)
    wrong_kind_reference = (
        _reference(kind="capacity_window", clock_evidence_mode="source_clocks_required"),
    )

    for references in (
        unrelated_close_reference,
        wrong_security_reference,
        non_close_reference,
        wrong_kind_reference,
    ):
        assert _capacity_requested_purpose(references, requested) == CAPACITY_REQUESTED_PURPOSE


def test_capture_evidence_keeps_manifest_pin_separate_from_vendor_body_hash() -> None:
    capture = _capture()
    reference = _reference(asset_code="600036.SH", security_id="600036001")
    receipt = PortfolioRiskCaptureReceipt(
        capture_id="local-capture-600036-20261103",
        source_id="sina_public_quote",
        source_record_id=reference.source_record_id,
        original_body_sha256=capture.body_sha256,
        response_completed_at=capture.response_completed_at,
        http_status=capture.http_status,
        body_size_bytes=capture.body_size_bytes,
        body_complete=True,
    )

    assert reference.raw_payload_hash != f"sha256:{capture.body_sha256}"
    assert _capture_matches_reference(
        capture=capture,
        source_reference=reference,
        receipt=receipt,
        retained_payload_hash=reference.raw_payload_hash,
        account_id=615,
        asset_code="600036.SH",
        security_id="600036001",
        trading_date=datetime(2026, 11, 3, tzinfo=UTC).date(),
        as_of=datetime(2026, 11, 3, 7, 21, tzinfo=UTC),
    )

    tampered_receipt = replace(
        receipt,
        response_completed_at=receipt.response_completed_at + timedelta(seconds=1),
    )
    assert not _capture_matches_reference(
        capture=capture,
        source_reference=reference,
        receipt=tampered_receipt,
        retained_payload_hash=reference.raw_payload_hash,
        account_id=615,
        asset_code="600036.SH",
        security_id="600036001",
        trading_date=datetime(2026, 11, 3, tzinfo=UTC).date(),
        as_of=datetime(2026, 11, 3, 7, 21, tzinfo=UTC),
    )


def _capture() -> SinaQuoteCapture:
    """Build a synthetic exact source response for pin-binding unit tests."""

    asset_code = "600036.SH"
    url = build_sina_quote_request_url(asset_code)
    completed = datetime(2026, 11, 3, 7, 20, tzinfo=UTC)
    fields = [
        "浦发银行",
        "10.04",
        "9.98",
        "9.95",
        "10.05",
        "9.90",
        "9.94",
        "9.95",
        "123456",
        "1234567.00",
        *("" for _ in range(20)),
        "2026-11-03",
        "15:01:00",
        "00",
        "D|11800|118236.00",
    ]
    body = ("var hq_str_sh600036=" + '"' + ",".join(fields) + '"' + ";\n").encode("gb18030")
    return parse_sina_quote_capture(
        asset_code=asset_code,
        requested_url=url,
        final_url=url,
        request_started_at=completed - timedelta(seconds=2),
        response_completed_at=completed,
        http_status=200,
        http_date="Tue, 03 Nov 2026 07:20:00 GMT",
        content_type="application/javascript; charset=GB18030",
        charset="GB18030",
        content_encoding="identity",
        body=body,
    )
