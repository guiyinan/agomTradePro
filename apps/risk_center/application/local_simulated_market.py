"""Build exact local-simulation market evidence from a captured Sina response."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Literal, TypedDict, cast
from zoneinfo import ZoneInfo

from apps.data_center.application.sina_quote_capture import SinaQuoteCapture
from apps.data_center.domain.sina_quote_capture import (
    SINA_QUOTE_SOURCE_ID,
    SINA_VENDOR_STATUS_MAPPING_SHA256,
    SinaQuoteClockStatus,
    SinaQuoteObservation,
    SinaReportedTradingState,
)
from apps.risk_center.application.execution_submission_v2 import (
    ExecutionSubmissionMarketProvider,
)
from apps.risk_center.domain.execution_submission_v2 import (
    ExecutionSubmissionMarketV2,
    ExecutionSubmissionRuleV2,
)
from apps.risk_center.domain.execution_trading_constraints import (
    ExecutionMarketEvidence,
    SecurityTradingState,
    SessionState,
)
from apps.risk_center.domain.local_simulated_market_policy import (
    LocalSimulatedCalendarContext,
    LocalSimulatedMarketPolicy,
)
from apps.risk_center.domain.price_submission_range import (
    PriceSubmissionStage,
    QuoteValue,
    QuoteValueState,
)

_LOCAL_SIMULATION_PURPOSE = "local_simulation_only"
_MARKET_PROVENANCE_SCHEMA = "local-simulated-market-evidence.v1"
_MARKET_AVAILABLE_AT_BASIS: Literal["local_response_completed_at_not_vendor_published_at"] = (
    "local_response_completed_at_not_vendor_published_at"
)


class LocalSimulatedMarketBundlePayload(TypedDict):
    """Exact preview evidence to be retained in a server-signed token."""

    schema: str
    purpose: str
    policy: dict[str, object]
    capture: dict[str, object]
    calendar: dict[str, object]
    execution_rule_content_hash: str
    market: dict[str, object]
    market_available_at_basis: Literal["local_response_completed_at_not_vendor_published_at"]
    content_hash: str


@dataclass(frozen=True, slots=True)
class LocalSimulatedMarketBundle:
    """Attach simulation purpose and clocks to a V2 market.

    The V2 ``market_available_at`` field is the local HTTP response completion
    clock. Sina supplies no separate vendor publication/release timestamp for
    this quote; the source-native quote timestamp remains ``market_observed_at``.
    """

    policy: LocalSimulatedMarketPolicy
    capture: SinaQuoteCapture = field(repr=False)
    calendar: LocalSimulatedCalendarContext
    execution_rule_content_hash: str
    market: ExecutionSubmissionMarketV2
    purpose: str = _LOCAL_SIMULATION_PURPOSE

    def __post_init__(self) -> None:
        """Ensure the V2 object and all retained evidence share one local scope."""

        if self.purpose != _LOCAL_SIMULATION_PURPOSE:
            raise ValueError("local simulated market purpose is unsupported")
        if type(self.policy) is not LocalSimulatedMarketPolicy:
            raise ValueError("local simulated market policy is invalid")
        if type(self.capture) is not SinaQuoteCapture:
            raise ValueError("local simulated market capture is invalid")
        if type(self.calendar) is not LocalSimulatedCalendarContext:
            raise ValueError("local simulated market calendar context is invalid")
        if type(self.market) is not ExecutionSubmissionMarketV2:
            raise ValueError("local simulated market v2 evidence is invalid")
        evidence = self.market.market_evidence_v1
        if (
            evidence.security_id != self.policy.security_id
            or evidence.market != self.policy.market
            or evidence.board != self.policy.board
            or evidence.trading_date != self.calendar.trading_date
            or evidence.market_source_hash == ""
        ):
            raise ValueError("local simulated market bundle scope differs")
        _require_sha256(self.execution_rule_content_hash, "execution_rule_content_hash")

    @property
    def content_hash(self) -> str:
        """Return the digest of explicit purpose, raw capture, policy, calendar, and V2 market."""

        return _canonical_hash(self._content_payload())

    def _content_payload(self) -> dict[str, object]:
        """Build the signed evidence body without its outer digest."""

        return {
            "schema": _MARKET_PROVENANCE_SCHEMA,
            "purpose": self.purpose,
            "policy": self.policy.to_payload(),
            "capture": self.capture.to_payload(),
            "calendar": self.calendar.to_payload(),
            "execution_rule_content_hash": self.execution_rule_content_hash,
            "market": self.market.to_payload(),
            "market_available_at_basis": _MARKET_AVAILABLE_AT_BASIS,
        }

    def to_payload(self) -> LocalSimulatedMarketBundlePayload:
        """Return source bytes and all purpose/evidence hashes for preview signing."""

        payload = self._content_payload()
        payload["content_hash"] = self.content_hash
        return cast(LocalSimulatedMarketBundlePayload, payload)


class LocalSimulatedMarketProvider(ExecutionSubmissionMarketProvider):
    """Expose one prepared local-simulation bundle through the existing Risk port."""

    def __init__(self, *, bundle: LocalSimulatedMarketBundle) -> None:
        """Bind a market that was built from one captured response and explicit policy."""

        if type(bundle) is not LocalSimulatedMarketBundle:
            raise ValueError("local simulated market bundle is invalid")
        bundle.__post_init__()
        self._bundle = bundle

    def get_submission_market(
        self,
        *,
        account_id: int,
        security_id: str,
        as_of: datetime,
    ) -> ExecutionSubmissionMarketV2 | None:
        """Return the prepared market only for its security and live source windows."""

        if type(account_id) is not int or account_id <= 0:
            return None
        if type(security_id) is not str or security_id != self._bundle.policy.security_id:
            return None
        if type(as_of) is not datetime or as_of.tzinfo is None or as_of.utcoffset() is None:
            return None
        evidence = self._bundle.market.market_evidence_v1
        if not (
            evidence.calendar_available_at <= as_of < evidence.calendar_valid_until
            and evidence.session_open_at <= as_of < evidence.session_close_at
            and evidence.market_available_at <= as_of < evidence.market_valid_until
            and evidence.market_observed_at <= as_of
        ):
            return None
        return self._bundle.market


def build_submission_market(
    *,
    policy: LocalSimulatedMarketPolicy,
    capture: SinaQuoteCapture,
    calendar: LocalSimulatedCalendarContext,
    rule: ExecutionSubmissionRuleV2,
    as_of: datetime,
) -> LocalSimulatedMarketBundle | None:
    """Build source-bound paper market evidence or fail closed with ``None``.

    The returned market carries only the exact V2 quote contract. Its sibling
    bundle binds purpose and all retained source evidence for local preview
    signing; that purpose never grants QMT or broker execution authority.
    """

    if type(policy) is not LocalSimulatedMarketPolicy:
        return None
    if type(capture) is not SinaQuoteCapture or type(calendar) is not LocalSimulatedCalendarContext:
        return None
    if type(rule) is not ExecutionSubmissionRuleV2:
        return None
    if type(as_of) is not datetime or as_of.tzinfo is None or as_of.utcoffset() is None:
        return None
    try:
        policy.__post_init__()
        calendar.__post_init__()
        rule.__post_init__()
        capture.__post_init__()
    except (ArithmeticError, TypeError, ValueError):
        return None

    quote = capture.quote
    if not capture.usable_parse or quote is None:
        return None
    if policy.status_mapping_sha256 != SINA_VENDOR_STATUS_MAPPING_SHA256:
        return None
    if policy.source_id != SINA_QUOTE_SOURCE_ID or capture.asset_code != policy.asset_code:
        return None
    if not policy.effective_from <= calendar.trading_date <= policy.effective_until:
        return None
    if quote.source_clock_status is not SinaQuoteClockStatus.VALID:
        return None
    source_observed_at = quote.source_observed_at
    if source_observed_at is None or source_observed_at.astimezone(UTC) > as_of.astimezone(UTC):
        return None
    if capture.response_completed_at > as_of.astimezone(UTC):
        return None
    if source_observed_at.astimezone(ZoneInfo("Asia/Shanghai")).date() != calendar.trading_date:
        return None
    if quote.vendor_status_code not in policy.trusted_vendor_status_codes:
        return None
    if quote.reported_trading_state is not SinaReportedTradingState.TRADING:
        return None
    if quote.last_price is None:
        return None
    if calendar.session_state is not SessionState.OPEN:
        return None
    if policy.session_timezone != calendar.session_timezone:
        return None
    if not (
        calendar.calendar_available_at <= as_of < calendar.calendar_valid_until
        and calendar.session_open_at <= as_of < calendar.session_close_at
    ):
        return None
    if not policy.is_same_continuous_window(observed_at=source_observed_at, as_of=as_of):
        return None
    try:
        quote_ttl = timedelta(seconds=policy.quote_ttl_seconds)
        market_valid_until = source_observed_at + quote_ttl
    except OverflowError:
        return None
    age = as_of.astimezone(UTC) - source_observed_at.astimezone(UTC)
    if age < timedelta(0) or age >= quote_ttl:
        return None
    if capture.response_completed_at >= market_valid_until.astimezone(UTC):
        return None
    if not _rule_matches_policy(rule, policy):
        return None

    try:
        lower_limit, upper_limit = policy.derive_price_boundaries(
            previous_close=quote.previous_close,
            price_tick=rule.execution_rule_v1.price_tick,
        )
        market_source_hash = _market_source_hash(
            policy=policy,
            capture=capture,
            quote=quote,
            calendar=calendar,
            rule=rule,
            lower_limit=lower_limit,
            upper_limit=upper_limit,
        )
        market_evidence = ExecutionMarketEvidence(
            security_id=policy.security_id,
            market=policy.market,
            board=policy.board,
            trading_date=calendar.trading_date,
            calendar_id=calendar.calendar_id,
            calendar_version=calendar.calendar_version,
            calendar_source_hash=calendar.calendar_source_hash,
            calendar_observed_at=calendar.calendar_observed_at,
            calendar_available_at=calendar.calendar_available_at,
            calendar_valid_until=calendar.calendar_valid_until,
            session_id=calendar.session_id,
            session_timezone=calendar.session_timezone,
            session_open_at=calendar.session_open_at,
            session_close_at=calendar.session_close_at,
            session_state=calendar.session_state,
            security_state=SecurityTradingState.TRADING,
            market_source_id=policy.source_id,
            market_source_version=policy.policy_version,
            market_source_hash=market_source_hash,
            price_boundary_mode=policy.price_boundary_mode,
            lower_limit_price=lower_limit,
            upper_limit_price=upper_limit,
            reference_price=quote.last_price,
            market_observed_at=source_observed_at,
            market_available_at=capture.response_completed_at,
            market_valid_until=market_valid_until,
        )
        market = ExecutionSubmissionMarketV2(
            market_evidence_v1=market_evidence,
            stage=PriceSubmissionStage.CONTINUOUS,
            ask=_quote_value(quote.ask_price),
            bid=_quote_value(quote.bid_price),
            latest=_quote_value(quote.last_price),
            previous_close=_quote_value(quote.previous_close),
        )
        return LocalSimulatedMarketBundle(
            policy=policy,
            capture=capture,
            calendar=calendar,
            execution_rule_content_hash=rule.content_hash,
            market=market,
        )
    except (ArithmeticError, TypeError, ValueError):
        return None


def _rule_matches_policy(
    rule: ExecutionSubmissionRuleV2, policy: LocalSimulatedMarketPolicy
) -> bool:
    """Require both exact rule components to match the policy's market and board."""

    execution_rule = rule.execution_rule_v1
    cage_rule = rule.price_submission_range
    return (
        execution_rule.market == policy.market
        and execution_rule.board == policy.board
        and execution_rule.security_id == policy.security_id
        and cage_rule.market == policy.market
        and cage_rule.board == policy.board
        and PriceSubmissionStage.CONTINUOUS in rule.allowed_stages
    )


def _quote_value(value: Decimal | None) -> QuoteValue:
    """Keep missing/zero Sina values UNKNOWN; never imply confirmed absence."""

    if value is None:
        return QuoteValue(state=QuoteValueState.UNKNOWN, value=None)
    return QuoteValue(state=QuoteValueState.PRESENT, value=value)


def _market_source_hash(
    *,
    policy: LocalSimulatedMarketPolicy,
    capture: SinaQuoteCapture,
    quote: SinaQuoteObservation,
    calendar: LocalSimulatedCalendarContext,
    rule: ExecutionSubmissionRuleV2,
    lower_limit: Decimal | None,
    upper_limit: Decimal | None,
) -> str:
    """Bind the raw source, policy, calendar, V2 rule, and derived boundaries."""

    payload: dict[str, object] = {
        "purpose": _LOCAL_SIMULATION_PURPOSE,
        "policy_content_hash": policy.content_hash,
        "capture_body_sha256": capture.body_sha256,
        "capture_requested_url": capture.requested_url,
        "capture_final_url": capture.final_url,
        "capture_request_started_at": _utc_text(capture.request_started_at),
        "capture_response_completed_at": _utc_text(capture.response_completed_at),
        "market_available_at_basis": _MARKET_AVAILABLE_AT_BASIS,
        "capture_http_status": capture.http_status,
        "capture_http_date": capture.http_date,
        "capture_content_type": capture.content_type,
        "capture_charset": capture.charset,
        "capture_content_encoding": capture.content_encoding,
        "source_observed_at": _utc_text(quote.source_observed_at),
        "source_date_text": quote.source_date_text,
        "source_time_text": quote.source_time_text,
        "source_status_code": quote.vendor_status_code,
        "status_mapping_sha256": policy.status_mapping_sha256,
        "calendar_content_hash": calendar.content_hash,
        "execution_rule_content_hash": rule.content_hash,
        "boundary_mode": policy.price_boundary_mode.value,
        "boundary_rule_source_id": policy.boundary_rule_source_id,
        "boundary_rule_version": policy.boundary_rule_version,
        "boundary_rule_source_hash": policy.boundary_rule_source_hash,
        "lower_boundary": _decimal_text(lower_limit),
        "upper_boundary": _decimal_text(upper_limit),
    }
    return _canonical_hash(payload)


def _decimal_text(value: Decimal | None) -> str | None:
    """Serialize an exact boundary decimal without float conversion."""

    return None if value is None else format(value, "f")


def _require_sha256(value: object, field_name: str) -> None:
    """Validate one bare lowercase SHA-256 value."""

    if (
        type(value) is not str
        or len(value) != 64
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise ValueError(f"{field_name} must be lowercase SHA-256")


def _utc_text(value: datetime | None) -> str | None:
    """Format one known clock as canonical UTC, preserving missing evidence."""

    if value is None:
        return None
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("market source clock must be timezone-aware")
    return value.astimezone(UTC).isoformat(timespec="microseconds").replace("+00:00", "Z")


def _canonical_hash(payload: dict[str, object]) -> str:
    """Hash one typed JSON-compatible provenance payload."""

    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


__all__ = (
    "LocalSimulatedMarketBundle",
    "LocalSimulatedMarketBundlePayload",
    "LocalSimulatedMarketProvider",
    "build_submission_market",
)
