"""No-database contract tests for the separate close-snapshot simulation purpose."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import cast
from zoneinfo import ZoneInfo

import pytest

from apps.data_center.domain.sina_quote_capture import (
    SINA_VENDOR_STATUS_MAPPING_SHA256,
    SinaQuoteCapture,
    build_sina_quote_request_url,
    parse_sina_quote_capture,
)
from apps.risk_center.application.close_snapshot_simulation import (
    CloseSnapshotSimulationInput,
    CloseSnapshotSimulationUseCase,
)
from apps.risk_center.domain.close_snapshot_simulation import (
    CloseSnapshotSimulationEvaluation,
    CloseSnapshotSimulationPolicy,
    CloseSnapshotSimulationReason,
    CloseSnapshotSimulationStatus,
    CloseSnapshotSimulationValidationError,
    evaluate_close_snapshot_order,
    evaluate_close_snapshot_simulation,
)
from apps.risk_center.domain.execution_submission_v2 import (
    ExecutionSubmissionMarketV2,
    ExecutionSubmissionRuleV2,
    ExecutionSubmissionV2ValidationError,
    evaluate_execution_submission,
)
from apps.risk_center.domain.execution_trading_constraints import (
    AShareExecutionRule,
    ExecutionDenyCode,
    ExecutionOrder,
    ExecutionQuantityConstraint,
    ExecutionSide,
    PriceBoundaryMode,
    SellOddLotMode,
    SellPositionCompleteness,
    SellPositionEvidence,
    SessionState,
)
from apps.risk_center.domain.local_simulated_market_policy import (
    LocalSimulatedCalendarContext,
)
from apps.risk_center.domain.price_submission_range import (
    PriceRoundingMode,
    PriceSubmissionRangeRule,
    PriceSubmissionStage,
    QuoteValue,
    QuoteValueState,
)

SHANGHAI = ZoneInfo("Asia/Shanghai")
TRADING_DATE = date(2026, 11, 2)
SESSION_OPEN = datetime(2026, 11, 2, 9, 30, tzinfo=SHANGHAI)
SESSION_CLOSE = datetime(2026, 11, 2, 15, 0, tzinfo=SHANGHAI)
CAPTURE_COMPLETED = datetime(2026, 11, 2, 15, 20, 10, tzinfo=SHANGHAI)
AS_OF = datetime(2026, 11, 2, 15, 21, tzinfo=SHANGHAI)


def _body(
    *,
    source_date: str = "2026-11-02",
    source_time: str = "15:01:00",
    status: str = "00",
    last_price: str = "9.95",
    previous_close: str = "9.98",
) -> bytes:
    """Build a deterministic Sina response fixture, never a live-data claim."""

    fields = [
        "浦发银行",
        "10.04",
        previous_close,
        last_price,
        "10.05",
        "9.90",
        "9.94",
        "9.95",
        "123456",
        "1234567.00",
        *("" for _ in range(20)),
        source_date,
        source_time,
        status,
        "D|11800|118236.00",
    ]
    return f'var hq_str_sh600000="{",".join(fields)}";\n'.encode("gb18030")


def _capture(
    *,
    source_date: str = "2026-11-02",
    source_time: str = "15:01:00",
    status: str = "00",
    last_price: str = "9.95",
    previous_close: str = "9.98",
    completed_at: datetime = CAPTURE_COMPLETED,
    http_status: int = 200,
) -> SinaQuoteCapture:
    """Parse a same-response synthetic capture with independent local clocks."""

    url = build_sina_quote_request_url("600000.SH")
    completed_utc = completed_at.astimezone(UTC)
    return parse_sina_quote_capture(
        asset_code="600000.SH",
        requested_url=url,
        final_url=url,
        request_started_at=completed_utc - timedelta(seconds=5),
        response_completed_at=completed_utc,
        http_status=http_status,
        http_date="Mon, 02 Nov 2026 07:20:10 GMT",
        content_type="application/javascript; charset=GB18030",
        charset="GB18030",
        content_encoding="identity",
        body=_body(
            source_date=source_date,
            source_time=source_time,
            status=status,
            last_price=last_price,
            previous_close=previous_close,
        ),
    )


def _policy(**changes: object) -> CloseSnapshotSimulationPolicy:
    """Return one exact account/security/day policy with explicit paper rules."""

    values: dict[str, object] = {
        "policy_id": "fixture-close-paper-policy",
        "policy_version": "fixture-v1",
        "account_id": 42,
        "security_id": "600000.SH",
        "asset_code": "600000.SH",
        "market": "SH",
        "board": "MAIN",
        "trading_date": TRADING_DATE,
        "source_id": "sina_public_quote",
        "source_name": "Sina public quote; vendor last after close",
        "usage_ttl_seconds": 120,
        "status_mapping_sha256": SINA_VENDOR_STATUS_MAPPING_SHA256,
        "trusted_vendor_status_codes": ("00",),
        "available_from": SESSION_CLOSE,
        "available_until": datetime(2026, 11, 2, 16, 0, tzinfo=SHANGHAI),
        "price_rule": "exact_vendor_last_after_close.v1",
        "price_rule_source_hash": "d" * 64,
        "price_boundary_mode": PriceBoundaryMode.LIMITED,
        "lower_boundary_factor": Decimal("0.90"),
        "upper_boundary_factor": Decimal("1.10"),
        "boundary_rule_source_id": "explicit-paper-boundary",
        "boundary_rule_version": "fixture-v1",
        "boundary_rule_source_hash": "e" * 64,
        "unrestricted_reason_code": None,
    }
    values.update(changes)
    return CloseSnapshotSimulationPolicy(**values)  # type: ignore[arg-type]


def _calendar(*, state: SessionState = SessionState.CLOSED) -> LocalSimulatedCalendarContext:
    """Return an independently published calendar fixture with actual closed hours."""

    return LocalSimulatedCalendarContext(
        calendar_id="published-cn-equity-calendar",
        calendar_version="fixture-v1",
        calendar_source_hash="b" * 64,
        calendar_observed_at=datetime(2026, 11, 2, 14, 59, tzinfo=SHANGHAI),
        calendar_available_at=datetime(2026, 11, 2, 15, 0, 5, tzinfo=SHANGHAI),
        calendar_valid_until=datetime(2026, 11, 3, 0, 0, tzinfo=SHANGHAI),
        trading_date=TRADING_DATE,
        session_id="sh-session-2026-11-02",
        session_timezone="Asia/Shanghai",
        session_open_at=SESSION_OPEN,
        session_close_at=SESSION_CLOSE,
        session_state=state,
    )


def _rule(*, sell_mode: SellOddLotMode = SellOddLotMode.FORBID) -> ExecutionSubmissionRuleV2:
    """Build a test-only execution rule with explicit lot and tick terms."""

    quantity = ExecutionQuantityConstraint(
        minimum=Decimal("100"), step=Decimal("100"), maximum=Decimal("100000")
    )
    execution_rule = AShareExecutionRule(
        rule_id="fixture-rule",
        rule_version="fixture-v1",
        security_id="600000.SH",
        market="SH",
        board="MAIN",
        buy_quantity=quantity,
        sell_quantity=quantity,
        sell_odd_lot_mode=sell_mode,
        price_tick=Decimal("0.05"),
        rule_source_id="fixture-rule-source",
        rule_source_version="fixture-v1",
        rule_source_hash="a" * 64,
        source_observed_at=datetime(2026, 11, 2, 14, 0, tzinfo=SHANGHAI),
        source_available_at=datetime(2026, 11, 2, 14, 1, tzinfo=SHANGHAI),
        effective_from=datetime(2026, 11, 2, 0, 0, tzinfo=SHANGHAI),
        valid_until=datetime(2026, 11, 3, 0, 0, tzinfo=SHANGHAI),
    )
    range_rule = PriceSubmissionRangeRule(
        market="SH",
        board="MAIN",
        price_tick=Decimal("0.05"),
        buy_deviation_ratio=Decimal("0.02"),
        sell_deviation_ratio=Decimal("0.02"),
        buy_widening_ticks=10,
        sell_widening_ticks=10,
        minimum_distance_ticks=1,
        lower_floor_ticks=1,
        rounding_mode=PriceRoundingMode.HALF_UP,
    )
    return ExecutionSubmissionRuleV2(
        execution_rule_v1=execution_rule,
        price_submission_range=range_rule,
        allowed_stages=(PriceSubmissionStage.CONTINUOUS,),
    )


def _evaluate(
    *,
    capture: SinaQuoteCapture | None = None,
    policy: CloseSnapshotSimulationPolicy | None = None,
    calendar: LocalSimulatedCalendarContext | None = None,
    rule: ExecutionSubmissionRuleV2 | None = None,
    requested_price: Decimal | None = Decimal("9.95"),
    as_of: datetime = AS_OF,
):
    """Call the public close-purpose function for one explicit fixture scope."""

    return evaluate_close_snapshot_simulation(
        capture=capture if capture is not None else _capture(),
        policy=policy if policy is not None else _policy(),
        calendar=calendar if calendar is not None else _calendar(),
        rule=rule if rule is not None else _rule(),
        account_id=42,
        security_id="600000.SH",
        asset_code="600000.SH",
        trading_date=TRADING_DATE,
        requested_price=requested_price,
        as_of=as_of,
    )


def test_close_snapshot_keeps_real_clocks_and_closed_state_without_claiming_freshness() -> None:
    result = _evaluate()

    assert result.decision.status is CloseSnapshotSimulationStatus.QUALIFIED
    assert result.bundle is not None
    evidence = result.bundle.market.market_evidence_v1
    assert evidence.session_state is SessionState.CLOSED
    assert evidence.session_open_at == SESSION_OPEN
    assert evidence.session_close_at == SESSION_CLOSE
    assert evidence.market_observed_at == datetime(2026, 11, 2, 15, 1, tzinfo=SHANGHAI)
    assert evidence.market_available_at == CAPTURE_COMPLETED
    assert result.bundle.to_payload()["market_available_at_basis"] == (
        "local_response_completed_at_not_vendor_published_at"
    )
    assert result.bundle.market.price_observation_kind == (
        "vendor_last_quote_after_close_not_official_close"
    )
    assert result.bundle.market.price_boundary_basis == (
        "policy_derived_paper_bounds_not_exchange_limits"
    )
    assert result.bundle.market.security_state_basis == (
        "vendor_reported_sina_status_mapping_not_exchange_confirmation"
    )
    assert "stage" not in result.bundle.market.to_payload()
    assert result.bundle.capture.to_payload()["body_sha256"] == result.decision.capture_body_sha256


def test_application_use_case_roundtrips_strict_policy_and_exact_capture_bundle() -> None:
    policy = _policy()
    payload = policy.to_payload()
    assert CloseSnapshotSimulationPolicy.from_payload(payload) == policy
    unsigned_payload = {key: value for key, value in payload.items() if key != "content_hash"}
    assert CloseSnapshotSimulationPolicy.from_payload(unsigned_payload) == policy
    result = CloseSnapshotSimulationUseCase().evaluate(
        CloseSnapshotSimulationInput(
            capture=_capture(),
            policy=policy,
            calendar=_calendar(),
            rule=_rule(),
            account_id=42,
            security_id="600000.SH",
            asset_code="600000.SH",
            trading_date=TRADING_DATE,
            requested_price=Decimal("9.95"),
            as_of=AS_OF,
        )
    )
    assert result.decision.to_payload()["purpose"] == "close_snapshot_simulation"
    assert result.bundle is not None
    assert result.bundle.capture.body_sha256 == _capture().body_sha256


@pytest.mark.parametrize(
    ("capture", "expected"),
    [
        (_capture(source_time="14:59:00"), CloseSnapshotSimulationReason.SOURCE_PRE_CLOSE),
        (_capture(source_date="2026-11-01"), CloseSnapshotSimulationReason.SOURCE_DATE_MISMATCH),
        (
            _capture(source_time="15:25:00"),
            CloseSnapshotSimulationReason.SOURCE_CLOCK_FUTURE,
        ),
        (
            _capture(source_time=""),
            CloseSnapshotSimulationReason.SOURCE_CLOCK_UNKNOWN,
        ),
        (_capture(status="02"), CloseSnapshotSimulationReason.SOURCE_NOT_TRADING),
        (_capture(status="99"), CloseSnapshotSimulationReason.SOURCE_STATUS_UNTRUSTED),
        (_capture(http_status=503), CloseSnapshotSimulationReason.CAPTURE_UNUSABLE),
        (
            _capture(completed_at=datetime(2026, 11, 2, 15, 0, tzinfo=SHANGHAI)),
            CloseSnapshotSimulationReason.USAGE_TTL_EXPIRED,
        ),
    ],
)
def test_unqualified_source_or_expired_local_usage_window_blocks(
    capture: SinaQuoteCapture,
    expected: CloseSnapshotSimulationReason,
) -> None:
    result = _evaluate(capture=capture)

    assert result.bundle is None
    assert result.decision.status is CloseSnapshotSimulationStatus.BLOCKED
    assert expected in result.decision.reason_codes


def test_unknown_session_state_and_wrong_account_date_or_price_block() -> None:
    wrong_account = replace(_policy(), account_id=43, content_hash="")
    wrong_date = replace(
        _policy(),
        trading_date=date(2026, 11, 3),
        available_from=datetime(2026, 11, 3, 15, 0, tzinfo=SHANGHAI),
        available_until=datetime(2026, 11, 3, 16, 0, tzinfo=SHANGHAI),
        content_hash="",
    )

    assert (
        CloseSnapshotSimulationReason.CALENDAR_NOT_CLOSED
        in _evaluate(calendar=_calendar(state=SessionState.OPEN)).decision.reason_codes
    )
    assert (
        CloseSnapshotSimulationReason.POLICY_SCOPE_MISMATCH
        in _evaluate(policy=wrong_account).decision.reason_codes
    )
    assert (
        CloseSnapshotSimulationReason.POLICY_SCOPE_MISMATCH
        in _evaluate(policy=wrong_date).decision.reason_codes
    )
    assert (
        CloseSnapshotSimulationReason.PRICE_DIFFERS_FROM_SNAPSHOT
        in _evaluate(requested_price=Decimal("9.90")).decision.reason_codes
    )


def test_price_tick_and_paper_bounds_are_explicit_fail_closed() -> None:
    off_tick = _evaluate(capture=_capture(last_price="9.96"), requested_price=Decimal("9.96"))
    # 9.98 * 0.99 = 9.8802, rounded outward to 9.90 on the explicit 0.05 tick.
    outside_paper_bound = _evaluate(
        capture=_capture(last_price="9.95"),
        policy=_policy(upper_boundary_factor=Decimal("0.99")),
        requested_price=Decimal("9.95"),
    )

    assert CloseSnapshotSimulationReason.PRICE_NOT_ON_TICK in off_tick.decision.reason_codes
    assert (
        CloseSnapshotSimulationReason.PRICE_OUTSIDE_PAPER_BOUNDARY
        in outside_paper_bound.decision.reason_codes
    )


def test_policy_rejects_unknown_bounds_tampering_and_unexpected_payload_fields() -> None:
    with pytest.raises(CloseSnapshotSimulationValidationError, match="unknown"):
        _policy(price_boundary_mode=PriceBoundaryMode.UNKNOWN)
    with pytest.raises(CloseSnapshotSimulationValidationError, match="reversed"):
        _policy(
            lower_boundary_factor=Decimal("1.10"),
            upper_boundary_factor=Decimal("0.90"),
        )
    altered = _policy().to_payload()
    altered["usage_ttl_seconds"] = 121
    with pytest.raises(CloseSnapshotSimulationValidationError, match="hash"):
        CloseSnapshotSimulationPolicy.from_payload(altered)
    altered = _policy().to_payload()
    altered["unregistered_field"] = "must not be ignored"  # type: ignore[typeddict-unknown-key]
    with pytest.raises(CloseSnapshotSimulationValidationError, match="fields"):
        CloseSnapshotSimulationPolicy.from_payload(altered)


def test_order_evaluator_reuses_full_lot_and_position_terms_without_v2_open_claim() -> None:
    rule = _rule()
    source = _evaluate(rule=rule)
    assert source.bundle is not None
    order = ExecutionOrder(
        order_id="close-buy-1",
        account_id=42,
        security_id="600000.SH",
        side=ExecutionSide.BUY,
        quantity=Decimal("100"),
        limit_price=Decimal("9.95"),
        sell_position_evidence=None,
    )
    qualified = evaluate_close_snapshot_order(
        rule=rule, bundle=source.bundle, order=order, as_of=AS_OF
    )
    assert qualified.status is CloseSnapshotSimulationStatus.QUALIFIED
    assert qualified.order_id == order.order_id
    assert qualified.order_content_hash

    off_step = replace(order, order_id="close-buy-off-step", quantity=Decimal("105"))
    blocked = evaluate_close_snapshot_order(
        rule=rule, bundle=source.bundle, order=off_step, as_of=AS_OF
    )
    assert blocked.status is CloseSnapshotSimulationStatus.BLOCKED
    assert ExecutionDenyCode.QUANTITY_NOT_ON_STEP in blocked.reason_codes

    changed_rule = replace(
        rule,
        execution_rule_v1=replace(
            rule.execution_rule_v1, price_tick=Decimal("0.01"), content_hash=""
        ),
        price_submission_range=replace(rule.price_submission_range, price_tick=Decimal("0.01")),
        content_hash="",
    )
    mismatched_rule = evaluate_close_snapshot_order(
        rule=changed_rule, bundle=source.bundle, order=order, as_of=AS_OF
    )
    assert CloseSnapshotSimulationReason.RULE_CONTENT_HASH_MISMATCH in mismatched_rule.reason_codes

    with pytest.raises(ExecutionSubmissionV2ValidationError, match="market must be"):
        evaluate_execution_submission(
            rule=rule,
            market=cast(ExecutionSubmissionMarketV2, source.bundle.market),
            order=order,
            as_of=AS_OF,
        )


def test_full_sellable_odd_lot_requires_fresh_complete_zero_restricted_evidence() -> None:
    rule = _rule(sell_mode=SellOddLotMode.SELLABLE_BALANCE_TO_ZERO)
    source = _evaluate(rule=rule)
    assert source.bundle is not None
    position = SellPositionEvidence(
        security_id="600000.SH",
        account_id=42,
        available_to_sell_quantity=Decimal("150"),
        restricted_quantity=Decimal("0"),
        completeness=SellPositionCompleteness.COMPLETE,
        source_id="fixture-position-source",
        source_version="fixture-v1",
        source_hash="f" * 64,
        observed_at=AS_OF - timedelta(seconds=10),
        available_at=AS_OF - timedelta(seconds=5),
        valid_until=AS_OF + timedelta(seconds=30),
    )
    order = ExecutionOrder(
        order_id="close-sell-full-balance",
        account_id=42,
        security_id="600000.SH",
        side=ExecutionSide.SELL,
        quantity=Decimal("150"),
        limit_price=Decimal("9.95"),
        sell_position_evidence=position,
    )
    qualified = evaluate_close_snapshot_order(
        rule=rule, bundle=source.bundle, order=order, as_of=AS_OF
    )
    assert qualified.status is CloseSnapshotSimulationStatus.QUALIFIED

    too_large = replace(order, order_id="close-sell-too-large", quantity=Decimal("200"))
    blocked = evaluate_close_snapshot_order(
        rule=rule, bundle=source.bundle, order=too_large, as_of=AS_OF
    )
    assert blocked.status is CloseSnapshotSimulationStatus.BLOCKED
    assert ExecutionDenyCode.SELLABLE_BALANCE_INSUFFICIENT in blocked.reason_codes


@pytest.mark.parametrize(
    "changes",
    [
        {"purpose": "local_simulation_only"},
        {"account_id": 0},
        {"trading_date": datetime(2026, 11, 2, tzinfo=SHANGHAI)},
        {"source_name": ""},
        {"source_name": "invalid\u0001source"},
        {"usage_ttl_seconds": 0},
        {"usage_ttl_seconds": 86_400},
        {"source_id": "unverified_quote_source"},
        {"status_mapping_sha256": "e" * 64},
        {"trusted_vendor_status_codes": ()},
        {"trusted_vendor_status_codes": ("00", "00")},
        {
            "available_from": SESSION_CLOSE,
            "available_until": SESSION_CLOSE,
        },
        {
            "available_from": datetime(2026, 11, 3, 15, 0, tzinfo=SHANGHAI),
            "available_until": datetime(2026, 11, 3, 16, 0, tzinfo=SHANGHAI),
        },
        {"price_rule": "exchange_official_close"},
        {"lower_boundary_factor": None},
        {"unrestricted_reason_code": "not_limited"},
        {
            "price_boundary_mode": PriceBoundaryMode.UNRESTRICTED,
            "lower_boundary_factor": Decimal("0.90"),
            "upper_boundary_factor": Decimal("1.10"),
        },
        {
            "price_boundary_mode": PriceBoundaryMode.UNRESTRICTED,
            "lower_boundary_factor": None,
            "upper_boundary_factor": None,
            "unrestricted_reason_code": None,
        },
    ],
)
def test_policy_constructor_rejects_unqualified_scope_clocks_and_boundary_rules(
    changes: dict[str, object],
) -> None:
    with pytest.raises(CloseSnapshotSimulationValidationError):
        _policy(**changes)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("schema", "unknown-close-policy.v1"),
        ("purpose", "local_simulation_only"),
        ("account_id", True),
        ("trading_date", "2026-11-2"),
        ("source_name", None),
        ("trusted_vendor_status_codes", "00"),
        ("available_from", "2026-11-02T15:00:00+08:00"),
        ("lower_boundary_factor", "1e0"),
        ("price_boundary_mode", "UNKNOWN_FUTURE_MODE"),
        ("boundary_rule_source_hash", "not-a-sha256"),
    ],
)
def test_policy_decoder_rejects_malformed_public_wire_fields(field: str, value: object) -> None:
    payload = _policy().to_payload()
    payload.pop("content_hash")
    payload[field] = value

    with pytest.raises(CloseSnapshotSimulationValidationError):
        CloseSnapshotSimulationPolicy.from_payload(payload)


def test_close_evaluator_blocks_missing_and_untyped_source_material() -> None:
    missing = evaluate_close_snapshot_simulation(
        capture=None,
        policy=None,
        calendar=None,
        rule=None,
        account_id=42,
        security_id="600000.SH",
        asset_code="600000.SH",
        trading_date=TRADING_DATE,
        requested_price=Decimal("9.95"),
        as_of=AS_OF,
    )
    assert missing.bundle is None
    assert missing.decision.reason_codes == (
        CloseSnapshotSimulationReason.CAPTURE_MISSING,
        CloseSnapshotSimulationReason.POLICY_MISSING,
        CloseSnapshotSimulationReason.CALENDAR_MISSING,
        CloseSnapshotSimulationReason.RULE_MISSING,
    )

    invalid_capture = evaluate_close_snapshot_simulation(
        capture=cast(SinaQuoteCapture, object()),
        policy=_policy(),
        calendar=_calendar(),
        rule=_rule(),
        account_id=42,
        security_id="600000.SH",
        asset_code="600000.SH",
        trading_date=TRADING_DATE,
        requested_price=Decimal("9.95"),
        as_of=AS_OF,
    )
    assert invalid_capture.bundle is None
    assert CloseSnapshotSimulationReason.INVALID_INPUT in invalid_capture.decision.reason_codes

    with pytest.raises(CloseSnapshotSimulationValidationError, match="account_id"):
        evaluate_close_snapshot_simulation(
            capture=_capture(),
            policy=_policy(),
            calendar=_calendar(),
            rule=_rule(),
            account_id=0,
            security_id="600000.SH",
            asset_code="600000.SH",
            trading_date=TRADING_DATE,
            requested_price=Decimal("9.95"),
            as_of=AS_OF,
        )
    with pytest.raises(CloseSnapshotSimulationValidationError, match="trading_date"):
        evaluate_close_snapshot_simulation(
            capture=_capture(),
            policy=_policy(),
            calendar=_calendar(),
            rule=_rule(),
            account_id=42,
            security_id="600000.SH",
            asset_code="600000.SH",
            trading_date=cast(date, datetime(2026, 11, 2, tzinfo=SHANGHAI)),
            requested_price=Decimal("9.95"),
            as_of=AS_OF,
        )


def test_close_evaluator_blocks_market_scope_availability_and_freshness_failures() -> None:
    assert (
        CloseSnapshotSimulationReason.POLICY_SCOPE_MISMATCH
        in _evaluate(policy=_policy(account_id=43)).decision.reason_codes
    )

    rule = _rule()
    mismatched_execution_rule = replace(
        rule.execution_rule_v1,
        security_id="000001.SZ",
        content_hash="",
    )
    mismatched_rule = replace(
        rule,
        execution_rule_v1=mismatched_execution_rule,
        content_hash="",
    )
    assert (
        CloseSnapshotSimulationReason.RULE_SCOPE_MISMATCH
        in _evaluate(rule=mismatched_rule).decision.reason_codes
    )

    wrong_calendar_timezone = replace(_calendar(), session_timezone="UTC")
    assert (
        CloseSnapshotSimulationReason.CALENDAR_SCOPE_MISMATCH
        in _evaluate(calendar=wrong_calendar_timezone).decision.reason_codes
    )

    calendar_not_yet_available = replace(
        _calendar(), calendar_available_at=AS_OF + timedelta(seconds=1)
    )
    assert (
        CloseSnapshotSimulationReason.CALENDAR_NOT_AVAILABLE
        in _evaluate(calendar=calendar_not_yet_available).decision.reason_codes
    )

    expired_calendar = replace(_calendar(), calendar_valid_until=AS_OF + timedelta(seconds=1))
    assert (
        CloseSnapshotSimulationReason.CALENDAR_EXPIRED
        in _evaluate(
            calendar=expired_calendar, as_of=AS_OF + timedelta(seconds=2)
        ).decision.reason_codes
    )

    not_started_policy = _policy(available_from=AS_OF + timedelta(seconds=1))
    assert (
        CloseSnapshotSimulationReason.POLICY_WINDOW_NOT_STARTED
        in _evaluate(policy=not_started_policy).decision.reason_codes
    )

    expired_policy = _policy(available_until=AS_OF - timedelta(seconds=1))
    assert (
        CloseSnapshotSimulationReason.POLICY_WINDOW_EXPIRED
        in _evaluate(policy=expired_policy).decision.reason_codes
    )

    future_capture = _capture(completed_at=AS_OF + timedelta(seconds=1))
    assert (
        CloseSnapshotSimulationReason.CAPTURE_CLOCK_IN_FUTURE
        in _evaluate(capture=future_capture).decision.reason_codes
    )

    before_close_capture = _capture(completed_at=SESSION_CLOSE + timedelta(seconds=2))
    assert (
        CloseSnapshotSimulationReason.CAPTURE_NOT_AFTER_CLOSE
        in _evaluate(capture=before_close_capture).decision.reason_codes
    )

    late_rule = replace(
        rule.execution_rule_v1,
        source_available_at=AS_OF + timedelta(seconds=1),
        content_hash="",
    )
    rule_not_yet_available = replace(rule, execution_rule_v1=late_rule, content_hash="")
    assert (
        CloseSnapshotSimulationReason.RULE_NOT_AVAILABLE
        in _evaluate(rule=rule_not_yet_available).decision.reason_codes
    )

    expired_rule = replace(
        rule.execution_rule_v1,
        valid_until=AS_OF - timedelta(seconds=1),
        content_hash="",
    )
    rule_expired = replace(rule, execution_rule_v1=expired_rule, content_hash="")
    assert (
        CloseSnapshotSimulationReason.RULE_EXPIRED
        in _evaluate(rule=rule_expired).decision.reason_codes
    )

    assert (
        CloseSnapshotSimulationReason.PRICE_MISSING
        in _evaluate(
            capture=_capture(last_price=""),
            requested_price=None,
        ).decision.reason_codes
    )
    assert (
        CloseSnapshotSimulationReason.PREVIOUS_CLOSE_MISSING
        in _evaluate(capture=_capture(previous_close="")).decision.reason_codes
    )


def test_close_snapshot_market_bundle_decision_and_evaluation_reject_inconsistent_states() -> None:
    qualified = _evaluate()
    assert qualified.bundle is not None
    bundle = qualified.bundle

    open_evidence = replace(
        bundle.market.market_evidence_v1,
        session_state=SessionState.OPEN,
        content_hash="",
    )
    with pytest.raises(CloseSnapshotSimulationValidationError, match="CLOSED"):
        replace(bundle.market, market_evidence_v1=open_evidence, content_hash="")

    with pytest.raises(CloseSnapshotSimulationValidationError, match="observation kind"):
        replace(bundle.market, price_observation_kind="official_close", content_hash="")

    missing_latest = QuoteValue(state=QuoteValueState.CONFIRMED_ABSENT, value=None)
    with pytest.raises(
        CloseSnapshotSimulationValidationError, match="latest quote must be present"
    ):
        replace(bundle.market, latest=missing_latest, content_hash="")

    mismatched_policy = _policy(security_id="SH.WRONG-SECURITY")
    with pytest.raises(CloseSnapshotSimulationValidationError, match="bundle scopes"):
        replace(bundle, policy=mismatched_policy)

    with pytest.raises(CloseSnapshotSimulationValidationError, match="bundle purpose"):
        replace(bundle, purpose="intraday_market")

    with pytest.raises(CloseSnapshotSimulationValidationError, match="blocked decision"):
        replace(
            qualified.decision,
            status=CloseSnapshotSimulationStatus.BLOCKED,
            reason_codes=(),
            content_hash="",
        )

    with pytest.raises(CloseSnapshotSimulationValidationError, match="unique"):
        replace(
            qualified.decision,
            reason_codes=(
                CloseSnapshotSimulationReason.PRICE_MISSING,
                CloseSnapshotSimulationReason.PRICE_MISSING,
            ),
            content_hash="",
        )

    blocked = evaluate_close_snapshot_simulation(
        capture=None,
        policy=_policy(),
        calendar=_calendar(),
        rule=_rule(),
        account_id=42,
        security_id="600000.SH",
        asset_code="600000.SH",
        trading_date=TRADING_DATE,
        requested_price=Decimal("9.95"),
        as_of=AS_OF,
    )
    with pytest.raises(CloseSnapshotSimulationValidationError, match="state differ"):
        CloseSnapshotSimulationEvaluation(decision=blocked.decision, bundle=bundle)
