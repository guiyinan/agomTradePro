"""No-database tests for source-bound, local-only market evidence."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal
from hashlib import sha256
from typing import cast
from zoneinfo import ZoneInfo

import pytest

from apps.data_center.domain.sina_quote_capture import (
    SINA_VENDOR_STATUS_MAPPING_SHA256,
    SinaQuoteCapture,
    SinaQuoteClockStatus,
    SinaReportedTradingState,
    build_sina_quote_request_url,
    parse_sina_quote_capture,
)
from apps.risk_center.application.local_simulated_market import (
    LocalSimulatedMarketBundle,
    LocalSimulatedMarketProvider,
    build_submission_market,
)
from apps.risk_center.domain.execution_submission_v2 import ExecutionSubmissionRuleV2
from apps.risk_center.domain.execution_trading_constraints import (
    AShareExecutionRule,
    ExecutionQuantityConstraint,
    PriceBoundaryMode,
    SecurityTradingState,
    SellOddLotMode,
    SessionState,
)
from apps.risk_center.domain.local_simulated_market_policy import (
    LocalSimulatedCalendarContext,
    LocalSimulatedMarketPolicy,
    LocalSimulatedMarketPolicyError,
    LocalSimulatedSessionWindow,
)
from apps.risk_center.domain.price_submission_range import (
    PriceRoundingMode,
    PriceSubmissionRangeRule,
    PriceSubmissionStage,
    QuoteValueState,
)

SHANGHAI = ZoneInfo("Asia/Shanghai")
AS_OF = datetime(2026, 11, 2, 10, 0, tzinfo=SHANGHAI)
TRADING_DATE = date(2026, 11, 2)


def _body(
    *,
    status: str = "00",
    source_date: str = "2026-11-02",
    source_time: str = "09:59:00",
    bid: str = "9.94",
    ask: str = "9.95",
) -> bytes:
    fields = [
        "浦发银行",
        "10.04",
        "9.98",
        "9.95",
        "10.05",
        "9.90",
        bid,
        ask,
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
    status: str = "00",
    source_date: str = "2026-11-02",
    source_time: str = "09:59:00",
    bid: str = "9.94",
    ask: str = "9.95",
    completed_at: datetime = datetime(2026, 11, 2, 9, 59, 5, tzinfo=SHANGHAI),
) -> SinaQuoteCapture:
    url = build_sina_quote_request_url("600000.SH")
    return parse_sina_quote_capture(
        asset_code="600000.SH",
        requested_url=url,
        final_url=url,
        request_started_at=completed_at.astimezone(UTC) - timedelta(seconds=2),
        response_completed_at=completed_at.astimezone(UTC),
        http_status=200,
        http_date="Mon, 02 Nov 2026 01:59:05 GMT",
        content_type="application/javascript; charset=GB18030",
        charset="GB18030",
        content_encoding="identity",
        body=_body(
            status=status,
            source_date=source_date,
            source_time=source_time,
            bid=bid,
            ask=ask,
        ),
    )


def _policy(
    *,
    price_boundary_mode: PriceBoundaryMode = PriceBoundaryMode.LIMITED,
    lower_factor: Decimal | None = Decimal("0.90"),
    upper_factor: Decimal | None = Decimal("1.10"),
    unrestricted_reason: str | None = None,
) -> LocalSimulatedMarketPolicy:
    has_boundary_rule = price_boundary_mode is not PriceBoundaryMode.UNKNOWN
    return LocalSimulatedMarketPolicy(
        policy_id="cash-equity-simulation",
        policy_version="policy-v1",
        security_id="600000.SH",
        asset_code="600000.SH",
        market="SH",
        board="MAIN",
        effective_from=date(2026, 11, 1),
        effective_until=date(2026, 11, 3),
        source_id="sina_public_quote",
        source_name="Sina public market quote",
        quote_ttl_seconds=300,
        status_mapping_sha256=SINA_VENDOR_STATUS_MAPPING_SHA256,
        trusted_vendor_status_codes=("00",),
        session_timezone="Asia/Shanghai",
        session_windows=(
            LocalSimulatedSessionWindow(
                stage=PriceSubmissionStage.CONTINUOUS,
                starts_at=time(9, 30),
                ends_at=time(11, 30),
            ),
            LocalSimulatedSessionWindow(
                stage=PriceSubmissionStage.CONTINUOUS,
                starts_at=time(13, 0),
                ends_at=time(15, 0),
            ),
        ),
        price_boundary_mode=price_boundary_mode,
        lower_boundary_factor=lower_factor,
        upper_boundary_factor=upper_factor,
        boundary_rule_source_id=("local_simulation_paper_boundary" if has_boundary_rule else None),
        boundary_rule_version=("fixture-v1" if has_boundary_rule else None),
        boundary_rule_source_hash=("e" * 64 if has_boundary_rule else None),
        unrestricted_reason_code=unrestricted_reason,
    )


def _calendar() -> LocalSimulatedCalendarContext:
    return LocalSimulatedCalendarContext(
        calendar_id="published_cn_equity_calendar",
        calendar_version="published-v1",
        calendar_source_hash="b" * 64,
        calendar_observed_at=AS_OF - timedelta(days=1),
        calendar_available_at=AS_OF - timedelta(hours=1),
        calendar_valid_until=AS_OF + timedelta(days=1),
        trading_date=TRADING_DATE,
        session_id="sh-2026-11-02-session",
        session_timezone="Asia/Shanghai",
        session_open_at=datetime(2026, 11, 2, 9, 30, tzinfo=SHANGHAI),
        session_close_at=datetime(2026, 11, 2, 15, 0, tzinfo=SHANGHAI),
        session_state=SessionState.OPEN,
    )


def _rule() -> ExecutionSubmissionRuleV2:
    quantity = ExecutionQuantityConstraint(
        minimum=Decimal("100"),
        step=Decimal("100"),
        maximum=Decimal("100000"),
    )
    execution_rule = AShareExecutionRule(
        rule_id="fixture-rule",
        rule_version="fixture-v1",
        security_id="600000.SH",
        market="SH",
        board="MAIN",
        buy_quantity=quantity,
        sell_quantity=quantity,
        sell_odd_lot_mode=SellOddLotMode.FORBID,
        price_tick=Decimal("0.05"),
        rule_source_id="published_rule_source",
        rule_source_version="fixture-v1",
        rule_source_hash="a" * 64,
        source_observed_at=AS_OF - timedelta(hours=2),
        source_available_at=AS_OF - timedelta(hours=1),
        effective_from=AS_OF - timedelta(days=1),
        valid_until=AS_OF + timedelta(days=1),
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


def test_policy_payload_is_strict_and_roundtrips_with_or_without_local_hash() -> None:
    policy = _policy()

    payload = policy.to_payload()
    assert LocalSimulatedMarketPolicy.from_payload(payload) == policy
    unsigned_config = {key: value for key, value in payload.items() if key != "content_hash"}
    assert LocalSimulatedMarketPolicy.from_payload(unsigned_config) == policy
    assert payload["purpose"] == "local_simulation_only"
    assert policy.purpose_value == "local_simulation_only"
    assert policy.purpose_value == "local_simulation_only"

    unsigned_config["unknown_policy_field"] = "must reject"
    with pytest.raises(LocalSimulatedMarketPolicyError, match="fields"):
        LocalSimulatedMarketPolicy.from_payload(unsigned_config)


def test_positive_market_bundle_is_paper_derived_and_binds_exact_inputs() -> None:
    capture = _capture()
    policy = _policy()
    calendar = _calendar()
    rule = _rule()

    result = build_submission_market(
        policy=policy,
        capture=capture,
        calendar=calendar,
        rule=rule,
        as_of=AS_OF,
    )

    assert isinstance(result, LocalSimulatedMarketBundle)
    assert result.purpose == "local_simulation_only"
    assert result.market.market_evidence_v1.security_state is SecurityTradingState.TRADING
    assert result.market.market_evidence_v1.price_boundary_mode is PriceBoundaryMode.LIMITED
    assert result.market.market_evidence_v1.lower_limit_price == Decimal("9.00")
    assert result.market.market_evidence_v1.upper_limit_price == Decimal("11.00")
    assert result.market.market_evidence_v1.market_observed_at == capture.quote.source_observed_at
    assert result.market.market_evidence_v1.market_available_at == capture.response_completed_at
    assert result.market.bid.state is QuoteValueState.PRESENT
    assert result.market.ask.state is QuoteValueState.PRESENT
    assert result.execution_rule_content_hash == rule.content_hash
    assert result.market.market_evidence_v1.market_source_hash != capture.body_sha256

    payload = result.to_payload()
    assert payload["purpose"] == "local_simulation_only"
    assert payload["market_available_at_basis"] == (
        "local_response_completed_at_not_vendor_published_at"
    )
    assert payload["capture"]["body_sha256"] == sha256(capture.body).hexdigest()
    assert payload["policy"]["content_hash"] == policy.content_hash
    provider = LocalSimulatedMarketProvider(bundle=result)
    assert (
        provider.get_submission_market(
            account_id=1,
            security_id="600000.SH",
            as_of=AS_OF,
        )
        == result.market
    )
    assert (
        provider.get_submission_market(
            account_id=1,
            security_id="600000.SH",
            as_of=AS_OF + timedelta(minutes=10),
        )
        is None
    )


def test_missing_bbo_stays_unknown_and_suspended_or_unknown_status_blocks() -> None:
    missing_bbo = _capture(bid="0", ask="0")
    result = build_submission_market(
        policy=_policy(),
        capture=missing_bbo,
        calendar=_calendar(),
        rule=_rule(),
        as_of=AS_OF,
    )
    assert isinstance(result, LocalSimulatedMarketBundle)
    assert result.market.bid.state is QuoteValueState.UNKNOWN
    assert result.market.ask.state is QuoteValueState.UNKNOWN

    suspended = _capture(status="02")
    assert suspended.quote is not None
    assert suspended.quote.reported_trading_state is SinaReportedTradingState.SUSPENDED
    assert (
        build_submission_market(
            policy=_policy(),
            capture=suspended,
            calendar=_calendar(),
            rule=_rule(),
            as_of=AS_OF,
        )
        is None
    )
    unknown = _capture(status="99")
    assert unknown.quote is not None
    assert unknown.quote.reported_trading_state is SinaReportedTradingState.UNKNOWN
    assert (
        build_submission_market(
            policy=_policy(),
            capture=unknown,
            calendar=_calendar(),
            rule=_rule(),
            as_of=AS_OF,
        )
        is None
    )


def test_stale_future_date_or_outside_configured_session_cannot_build_market() -> None:
    stale = _capture(source_time="09:50:00")
    future = _capture(source_time="10:01:00")
    old_session = replace(
        _calendar(),
        trading_date=date(2026, 10, 30),
        session_open_at=datetime(2026, 10, 30, 9, 30, tzinfo=SHANGHAI),
        session_close_at=datetime(2026, 10, 30, 15, 0, tzinfo=SHANGHAI),
    )
    lunch_cutoff = datetime(2026, 11, 2, 12, 0, tzinfo=SHANGHAI)

    assert stale.quote is not None and stale.quote.source_clock_status is SinaQuoteClockStatus.VALID
    assert (
        future.quote is not None and future.quote.source_clock_status is SinaQuoteClockStatus.FUTURE
    )
    assert (
        build_submission_market(
            policy=_policy(), capture=stale, calendar=_calendar(), rule=_rule(), as_of=AS_OF
        )
        is None
    )
    assert (
        build_submission_market(
            policy=_policy(), capture=future, calendar=_calendar(), rule=_rule(), as_of=AS_OF
        )
        is None
    )
    assert (
        build_submission_market(
            policy=_policy(),
            capture=_capture(),
            calendar=_calendar(),
            rule=_rule(),
            as_of=lunch_cutoff,
        )
        is None
    )
    assert (
        build_submission_market(
            policy=_policy(), capture=_capture(), calendar=old_session, rule=_rule(), as_of=AS_OF
        )
        is None
    )


def test_unknown_or_unconfigured_boundary_never_becomes_unrestricted() -> None:
    unknown_policy = _policy(
        price_boundary_mode=PriceBoundaryMode.UNKNOWN,
        lower_factor=None,
        upper_factor=None,
    )
    assert (
        build_submission_market(
            policy=unknown_policy,
            capture=_capture(),
            calendar=_calendar(),
            rule=_rule(),
            as_of=AS_OF,
        )
        is None
    )

    unrestricted = _policy(
        price_boundary_mode=PriceBoundaryMode.UNRESTRICTED,
        lower_factor=None,
        upper_factor=None,
        unrestricted_reason="explicit_asset_rule_has_no_daily_limit",
    )
    result = build_submission_market(
        policy=unrestricted,
        capture=_capture(),
        calendar=_calendar(),
        rule=_rule(),
        as_of=AS_OF,
    )
    assert isinstance(result, LocalSimulatedMarketBundle)
    assert result.market.market_evidence_v1.lower_limit_price is None
    assert result.market.market_evidence_v1.upper_limit_price is None


def test_capture_payload_in_policy_bundle_is_revalidated_before_use() -> None:
    capture = _capture()
    payload = capture.to_payload()
    payload["body_sha256"] = "0" * 64

    with pytest.raises(ValueError, match="SHA-256"):
        SinaQuoteCapture.from_payload(payload)


@pytest.mark.parametrize(
    "invalid_field",
    [
        "purpose",
        "token",
        "display_text",
        "date_type",
        "date_range",
        "ttl",
        "status_hash",
        "status_list_type",
        "duplicate_status",
        "timezone",
        "timezone_type",
        "windows_list_type",
        "window_type",
        "unordered_windows",
        "overlapping_windows",
        "boundary_hash",
        "inverted_factors",
        "limited_factor_type",
        "limited_with_unrestricted_reason",
        "unrestricted_with_factor",
        "unknown_with_values",
        "boundary_mode_type",
        "unrestricted_without_reason",
        "content_hash",
    ],
)
def test_policy_constructor_rejects_invalid_or_ambiguous_configuration(
    invalid_field: str,
) -> None:
    policy = _policy()
    if invalid_field == "purpose":
        changes: dict[str, object] = {"purpose": "live_execution"}
    elif invalid_field == "token":
        changes = {"policy_id": "has whitespace"}
    elif invalid_field == "display_text":
        changes = {"source_name": "source\nname"}
    elif invalid_field == "date_type":
        changes = {"effective_from": datetime(2026, 11, 1, tzinfo=UTC)}
    elif invalid_field == "date_range":
        changes = {"effective_from": date(2026, 11, 4)}
    elif invalid_field == "ttl":
        changes = {"quote_ttl_seconds": True}
    elif invalid_field == "status_hash":
        changes = {"status_mapping_sha256": "not-a-sha256"}
    elif invalid_field == "status_list_type":
        changes = {"trusted_vendor_status_codes": ["00"]}
    elif invalid_field == "duplicate_status":
        changes = {"trusted_vendor_status_codes": ("00", "00")}
    elif invalid_field == "timezone":
        changes = {"session_timezone": "UTC"}
    elif invalid_field == "timezone_type":
        changes = {"session_timezone": 7}
    elif invalid_field == "windows_list_type":
        changes = {"session_windows": list(policy.session_windows)}
    elif invalid_field == "window_type":
        changes = {"session_windows": (object(),)}
    elif invalid_field == "unordered_windows":
        changes = {"session_windows": tuple(reversed(policy.session_windows))}
    elif invalid_field == "overlapping_windows":
        changes = {
            "session_windows": (
                policy.session_windows[0],
                LocalSimulatedSessionWindow(
                    stage=PriceSubmissionStage.CONTINUOUS,
                    starts_at=time(11, 0),
                    ends_at=time(13, 30),
                ),
            )
        }
    elif invalid_field == "boundary_hash":
        changes = {"boundary_rule_source_hash": "short"}
    elif invalid_field == "inverted_factors":
        changes = {
            "lower_boundary_factor": Decimal("1.10"),
            "upper_boundary_factor": Decimal("0.90"),
        }
    elif invalid_field == "limited_factor_type":
        changes = {"lower_boundary_factor": "0.90"}
    elif invalid_field == "limited_with_unrestricted_reason":
        changes = {"unrestricted_reason_code": "invalid_for_limited_bounds"}
    elif invalid_field == "unrestricted_with_factor":
        policy = _policy(
            price_boundary_mode=PriceBoundaryMode.UNRESTRICTED,
            lower_factor=None,
            upper_factor=None,
            unrestricted_reason="explicit_fixture_reason",
        )
        changes = {"lower_boundary_factor": Decimal("0.90")}
    elif invalid_field == "unknown_with_values":
        changes = {"price_boundary_mode": PriceBoundaryMode.UNKNOWN}
    elif invalid_field == "boundary_mode_type":
        changes = {"price_boundary_mode": "limited"}
    elif invalid_field == "unrestricted_without_reason":
        policy = _policy(
            price_boundary_mode=PriceBoundaryMode.UNRESTRICTED,
            lower_factor=None,
            upper_factor=None,
            unrestricted_reason="explicit_fixture_reason",
        )
        changes = {"unrestricted_reason_code": None}
    else:
        changes = {"content_hash": "0" * 64}

    if invalid_field != "content_hash":
        changes["content_hash"] = ""
    with pytest.raises(LocalSimulatedMarketPolicyError):
        replace(policy, **changes)


@pytest.mark.parametrize(
    "mutation",
    [
        "schema",
        "purpose",
        "nontext_id",
        "ttl_bool",
        "status_list_type",
        "window_list_type",
        "noncanonical_date",
        "invalid_factor",
        "optional_text_type",
        "optional_factor_type",
        "not_decimal_factor",
        "noncanonical_factor",
        "invalid_boundary_mode",
        "compact_date",
        "window_keys",
        "window_clock",
        "content_hash_type",
        "content_hash_mismatch",
        "empty_content_hash",
    ],
)
def test_policy_payload_decoder_rejects_bad_shape_values_and_digest(mutation: str) -> None:
    payload: dict[str, object] = dict(_policy().to_payload())
    if mutation == "schema":
        payload["schema"] = "local-simulated-market-policy.v2"
    elif mutation == "purpose":
        payload["purpose"] = "live_execution"
    elif mutation == "nontext_id":
        payload["policy_id"] = 7
    elif mutation == "ttl_bool":
        payload["quote_ttl_seconds"] = True
    elif mutation == "status_list_type":
        payload["trusted_vendor_status_codes"] = "00"
    elif mutation == "window_list_type":
        payload["session_windows"] = {}
    elif mutation == "noncanonical_date":
        payload["effective_from"] = "2026-1-1"
    elif mutation == "invalid_factor":
        payload["lower_boundary_factor"] = "NaN"
    elif mutation == "optional_text_type":
        payload["boundary_rule_source_id"] = 7
    elif mutation == "optional_factor_type":
        payload["lower_boundary_factor"] = 0.90
    elif mutation == "not_decimal_factor":
        payload["lower_boundary_factor"] = "not-a-decimal"
    elif mutation == "noncanonical_factor":
        payload["lower_boundary_factor"] = "9e-1"
    elif mutation == "invalid_boundary_mode":
        payload["price_boundary_mode"] = "not-a-mode"
    elif mutation == "compact_date":
        payload["effective_from"] = "20261101"
    elif mutation == "window_keys":
        windows = cast(list[object], payload["session_windows"])
        cast(dict[str, object], windows[0])["unexpected"] = "reject"
    elif mutation == "window_clock":
        windows = cast(list[object], payload["session_windows"])
        cast(dict[str, object], windows[0])["starts_at"] = "9:30"
    elif mutation == "content_hash_type":
        payload["content_hash"] = 7
    elif mutation == "content_hash_mismatch":
        payload["content_hash"] = "0" * 64
    elif mutation == "empty_content_hash":
        payload["content_hash"] = ""

    with pytest.raises(LocalSimulatedMarketPolicyError):
        LocalSimulatedMarketPolicy.from_payload(payload)


@pytest.mark.parametrize(
    ("stage", "starts_at", "ends_at"),
    [
        ("continuous", time(9, 30), time(10, 0)),
        (PriceSubmissionStage.CONTINUOUS, time(9, 30, tzinfo=SHANGHAI), time(10, 0)),
        (PriceSubmissionStage.CONTINUOUS, time(10, 0), time(10, 0)),
        (PriceSubmissionStage.CONTINUOUS, time(10, 1), time(10, 0)),
    ],
)
def test_session_window_constructor_rejects_untyped_or_noncomparable_windows(
    stage: object,
    starts_at: time,
    ends_at: time,
) -> None:
    with pytest.raises(LocalSimulatedMarketPolicyError):
        LocalSimulatedSessionWindow(
            stage=cast(PriceSubmissionStage, stage),
            starts_at=starts_at,
            ends_at=ends_at,
        )


@pytest.mark.parametrize(
    "payload",
    [
        {"stage": "opening_call", "starts_at": "09:30:00", "ends_at": "10:00:00"},
        {"stage": "continuous", "starts_at": "09:30", "ends_at": "10:00:00"},
        {"stage": "continuous", "starts_at": "09:30:00", "ends_at": 100},
        {"stage": "continuous", "starts_at": "09:30:00", "ends_at": "10:00:00", "extra": 1},
    ],
)
def test_session_window_payload_decoder_rejects_unknown_or_noncanonical_fields(
    payload: dict[str, object],
) -> None:
    with pytest.raises(LocalSimulatedMarketPolicyError):
        LocalSimulatedSessionWindow.from_payload(payload)


@pytest.mark.parametrize(
    "invalid_field",
    [
        "calendar_hash",
        "naive_clock",
        "clock_order",
        "session_order",
        "date_type",
        "wrong_date",
        "timezone",
        "timezone_type",
        "state",
    ],
)
def test_calendar_context_rejects_unqualified_or_inconsistent_published_evidence(
    invalid_field: str,
) -> None:
    calendar = _calendar()
    if invalid_field == "calendar_hash":
        changes: dict[str, object] = {"calendar_source_hash": "not-a-hash"}
    elif invalid_field == "naive_clock":
        changes = {"calendar_observed_at": AS_OF.replace(tzinfo=None)}
    elif invalid_field == "clock_order":
        changes = {"calendar_available_at": AS_OF - timedelta(days=2)}
    elif invalid_field == "session_order":
        changes = {"session_close_at": calendar.session_open_at}
    elif invalid_field == "date_type":
        changes = {"trading_date": datetime(2026, 11, 2, tzinfo=SHANGHAI)}
    elif invalid_field == "wrong_date":
        changes = {"trading_date": date(2026, 11, 3)}
    elif invalid_field == "timezone":
        changes = {"session_timezone": "Unknown/Zone"}
    elif invalid_field == "timezone_type":
        changes = {"session_timezone": 7}
    else:
        changes = {"session_state": "OPEN"}

    with pytest.raises(LocalSimulatedMarketPolicyError):
        replace(calendar, **changes)


@pytest.mark.parametrize(
    ("previous_close", "price_tick"),
    [
        (None, Decimal("0.05")),
        (Decimal("0"), Decimal("0.05")),
        (Decimal("10"), Decimal("0")),
        (Decimal("NaN"), Decimal("0.05")),
    ],
)
def test_paper_boundary_derivation_requires_finite_same_day_reference_and_tick(
    previous_close: Decimal | None,
    price_tick: Decimal,
) -> None:
    with pytest.raises(LocalSimulatedMarketPolicyError):
        _policy().derive_price_boundaries(
            previous_close=previous_close,
            price_tick=price_tick,
        )


def test_unknown_tiny_and_unrestricted_boundary_modes_are_explicit() -> None:
    with pytest.raises(LocalSimulatedMarketPolicyError, match="unknown"):
        _policy(
            price_boundary_mode=PriceBoundaryMode.UNKNOWN,
            lower_factor=None,
            upper_factor=None,
        ).derive_price_boundaries(previous_close=Decimal("10"), price_tick=Decimal("0.05"))

    unrestricted = _policy(
        price_boundary_mode=PriceBoundaryMode.UNRESTRICTED,
        lower_factor=None,
        upper_factor=None,
        unrestricted_reason="instrument_rule_explicitly_unrestricted",
    )
    assert unrestricted.derive_price_boundaries(
        previous_close=None,
        price_tick=Decimal("0"),
    ) == (None, None)

    tiny = replace(
        _policy(),
        lower_boundary_factor=Decimal("0.0001"),
        upper_boundary_factor=Decimal("0.0002"),
        content_hash="",
    )
    with pytest.raises(LocalSimulatedMarketPolicyError, match="rounds to zero"):
        tiny.derive_price_boundaries(
            previous_close=Decimal("1"),
            price_tick=Decimal("0.05"),
        )


def test_policy_window_comparison_never_crosses_lunch_date_or_reversed_time() -> None:
    policy = _policy()
    assert policy.is_same_continuous_window(
        observed_at=datetime(2026, 11, 2, 9, 45, tzinfo=SHANGHAI),
        as_of=datetime(2026, 11, 2, 10, 0, tzinfo=SHANGHAI),
    )
    assert not policy.is_same_continuous_window(
        observed_at=datetime(2026, 11, 2, 11, 25, tzinfo=SHANGHAI),
        as_of=datetime(2026, 11, 2, 13, 15, tzinfo=SHANGHAI),
    )
    assert not policy.is_same_continuous_window(
        observed_at=datetime(2026, 11, 2, 14, 59, tzinfo=SHANGHAI),
        as_of=datetime(2026, 11, 3, 9, 31, tzinfo=SHANGHAI),
    )
    assert not policy.is_same_continuous_window(
        observed_at=datetime(2026, 11, 2, 10, 0, tzinfo=SHANGHAI),
        as_of=datetime(2026, 11, 2, 9, 59, tzinfo=SHANGHAI),
    )
    with pytest.raises(LocalSimulatedMarketPolicyError, match="timezone-aware"):
        policy.is_same_continuous_window(
            observed_at=datetime(2026, 11, 2, 10, 0),
            as_of=AS_OF,
        )


@pytest.mark.parametrize("binding", ["security", "source", "effective_date"])
def test_submission_market_refuses_policy_not_bound_to_exact_quote_scope(binding: str) -> None:
    policy = _policy()
    if binding == "security":
        policy = replace(
            policy,
            security_id="000001.SZ",
            asset_code="000001.SZ",
            market="SZ",
            content_hash="",
        )
    elif binding == "source":
        policy = replace(policy, source_id="unrelated_quote_provider", content_hash="")
    else:
        policy = replace(
            policy,
            effective_from=date(2026, 11, 3),
            effective_until=date(2026, 11, 3),
            content_hash="",
        )

    assert (
        build_submission_market(
            policy=policy,
            capture=_capture(),
            calendar=_calendar(),
            rule=_rule(),
            as_of=AS_OF,
        )
        is None
    )
