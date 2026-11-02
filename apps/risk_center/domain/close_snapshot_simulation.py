"""Source-clocked close snapshot evidence for explicitly scoped simulation only."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from enum import StrEnum
from fractions import Fraction
from typing import TypedDict, cast
from zoneinfo import ZoneInfo

from apps.data_center.domain.sina_quote_capture import (
    SINA_QUOTE_SOURCE_ID,
    SINA_VENDOR_STATUS_MAPPING_SHA256,
    SinaQuoteCapture,
    SinaQuoteClockStatus,
    SinaReportedTradingState,
)
from apps.risk_center.domain.execution_submission_v2 import ExecutionSubmissionRuleV2
from apps.risk_center.domain.execution_trading_constraints import (
    ExecutionDenyCode,
    ExecutionMarketEvidence,
    ExecutionOrder,
    PriceBoundaryMode,
    SecurityTradingState,
    SessionState,
    evaluate_execution_terms,
)
from apps.risk_center.domain.local_simulated_market_policy import (
    LocalSimulatedCalendarContext,
)
from apps.risk_center.domain.price_submission_range import QuoteValue, QuoteValueState

_POLICY_SCHEMA = "close-snapshot-simulation-policy.v1"
_BUNDLE_SCHEMA = "close-snapshot-simulation-bundle.v1"
_DECISION_SCHEMA = "close-snapshot-simulation-decision.v1"
_PURPOSE = "close_snapshot_simulation"
_PRICE_RULE = "exact_vendor_last_after_close.v1"
_PRICE_OBSERVATION_KIND = "vendor_last_quote_after_close_not_official_close"
_PRICE_BOUNDARY_BASIS = "policy_derived_paper_bounds_not_exchange_limits"
_SECURITY_STATE_BASIS = "vendor_reported_sina_status_mapping_not_exchange_confirmation"
_MARKET_AVAILABLE_AT_BASIS = "local_response_completed_at_not_vendor_published_at"
_SHANGHAI = ZoneInfo("Asia/Shanghai")
_SHA256_RE = re.compile(r"[0-9a-f]{64}\Z")
_MAX_DECIMAL_DIGITS = 64
_MAX_DECIMAL_EXPONENT = 64


class CloseSnapshotSimulationValidationError(ValueError):
    """Raised when a close-snapshot policy or evidence payload is malformed."""


class CloseSnapshotSimulationStatus(StrEnum):
    """Local paper-simulation qualification result, never broker authorization."""

    QUALIFIED = "QUALIFIED"
    BLOCKED = "BLOCKED"


class CloseSnapshotSimulationReason(StrEnum):
    """Stable reasons a retained after-close quote cannot support this simulation."""

    CAPTURE_MISSING = "CAPTURE_MISSING"
    POLICY_MISSING = "POLICY_MISSING"
    CALENDAR_MISSING = "CALENDAR_MISSING"
    RULE_MISSING = "RULE_MISSING"
    INVALID_INPUT = "INVALID_INPUT"
    POLICY_SCOPE_MISMATCH = "POLICY_SCOPE_MISMATCH"
    SOURCE_UNSUPPORTED = "SOURCE_UNSUPPORTED"
    STATUS_MAPPING_MISMATCH = "STATUS_MAPPING_MISMATCH"
    CAPTURE_UNUSABLE = "CAPTURE_UNUSABLE"
    SOURCE_CLOCK_UNKNOWN = "SOURCE_CLOCK_UNKNOWN"
    SOURCE_CLOCK_FUTURE = "SOURCE_CLOCK_FUTURE"
    SOURCE_DATE_MISMATCH = "SOURCE_DATE_MISMATCH"
    SOURCE_PRE_CLOSE = "SOURCE_PRE_CLOSE"
    SOURCE_STATUS_UNTRUSTED = "SOURCE_STATUS_UNTRUSTED"
    SOURCE_NOT_TRADING = "SOURCE_NOT_TRADING"
    CALENDAR_NOT_CLOSED = "CALENDAR_NOT_CLOSED"
    CALENDAR_SCOPE_MISMATCH = "CALENDAR_SCOPE_MISMATCH"
    CALENDAR_NOT_AVAILABLE = "CALENDAR_NOT_AVAILABLE"
    CALENDAR_EXPIRED = "CALENDAR_EXPIRED"
    POLICY_WINDOW_NOT_STARTED = "POLICY_WINDOW_NOT_STARTED"
    POLICY_WINDOW_EXPIRED = "POLICY_WINDOW_EXPIRED"
    CAPTURE_NOT_AFTER_CLOSE = "CAPTURE_NOT_AFTER_CLOSE"
    CAPTURE_CLOCK_IN_FUTURE = "CAPTURE_CLOCK_IN_FUTURE"
    USAGE_TTL_EXPIRED = "USAGE_TTL_EXPIRED"
    RULE_SCOPE_MISMATCH = "RULE_SCOPE_MISMATCH"
    RULE_CONTENT_HASH_MISMATCH = "RULE_CONTENT_HASH_MISMATCH"
    RULE_NOT_AVAILABLE = "RULE_NOT_AVAILABLE"
    RULE_EXPIRED = "RULE_EXPIRED"
    PRICE_MISSING = "PRICE_MISSING"
    PREVIOUS_CLOSE_MISSING = "PREVIOUS_CLOSE_MISSING"
    PRICE_NOT_ON_TICK = "PRICE_NOT_ON_TICK"
    PRICE_OUTSIDE_PAPER_BOUNDARY = "PRICE_OUTSIDE_PAPER_BOUNDARY"
    PRICE_DIFFERS_FROM_SNAPSHOT = "PRICE_DIFFERS_FROM_SNAPSHOT"
    BOUNDARY_POLICY_UNKNOWN = "BOUNDARY_POLICY_UNKNOWN"
    VALIDITY_WINDOW_EMPTY = "VALIDITY_WINDOW_EMPTY"


class CloseSnapshotSimulationPolicyPayload(TypedDict):
    """Exact canonical wire shape for a close-only policy."""

    schema: str
    purpose: str
    policy_id: str
    policy_version: str
    account_id: int
    security_id: str
    asset_code: str
    market: str
    board: str
    trading_date: str
    source_id: str
    source_name: str
    usage_ttl_seconds: int
    status_mapping_sha256: str
    trusted_vendor_status_codes: list[str]
    available_from: str
    available_until: str
    price_rule: str
    price_rule_source_hash: str
    price_boundary_mode: str
    lower_boundary_factor: str | None
    upper_boundary_factor: str | None
    boundary_rule_source_id: str
    boundary_rule_version: str
    boundary_rule_source_hash: str
    unrestricted_reason_code: str | None
    content_hash: str


@dataclass(frozen=True, slots=True)
class CloseSnapshotSimulationPolicy:
    """Bind one account, security, trading date, source, and close-only price rule.

    This policy authorizes use only in a local close-snapshot simulation. It
    does not declare Sina's last quote to be an official closing price or grant
    intraday, live-trading, or broker-execution eligibility.
    """

    policy_id: str
    policy_version: str
    account_id: int
    security_id: str
    asset_code: str
    market: str
    board: str
    trading_date: date
    source_id: str
    source_name: str
    usage_ttl_seconds: int
    status_mapping_sha256: str
    trusted_vendor_status_codes: tuple[str, ...]
    available_from: datetime
    available_until: datetime
    price_rule: str
    price_rule_source_hash: str
    price_boundary_mode: PriceBoundaryMode
    lower_boundary_factor: Decimal | None
    upper_boundary_factor: Decimal | None
    boundary_rule_source_id: str
    boundary_rule_version: str
    boundary_rule_source_hash: str
    unrestricted_reason_code: str | None
    purpose: str = _PURPOSE
    content_hash: str = ""

    def __post_init__(self) -> None:
        """Validate exact scope, clocks, trusted mapping, and explicit bounds."""

        if self.purpose != _PURPOSE:
            raise CloseSnapshotSimulationValidationError("policy purpose is not close-only")
        for name in (
            "policy_id",
            "policy_version",
            "security_id",
            "asset_code",
            "market",
            "board",
            "source_id",
            "boundary_rule_source_id",
            "boundary_rule_version",
        ):
            _token(getattr(self, name), name)
        if not _is_positive_int(self.account_id):
            raise CloseSnapshotSimulationValidationError("account_id must be positive")
        if type(self.trading_date) is not date:
            raise CloseSnapshotSimulationValidationError("trading_date must be an exact date")
        if (
            type(self.source_name) is not str
            or not self.source_name.strip()
            or len(self.source_name) > 192
            or any(ord(character) < 32 for character in self.source_name)
        ):
            raise CloseSnapshotSimulationValidationError("source_name is required")
        if (
            type(self.usage_ttl_seconds) is not int
            or self.usage_ttl_seconds <= 0
            or self.usage_ttl_seconds >= 86_400
        ):
            raise CloseSnapshotSimulationValidationError(
                "usage TTL must be positive and shorter than the policy day"
            )
        _digest(self.status_mapping_sha256, "status_mapping_sha256")
        _digest(self.price_rule_source_hash, "price_rule_source_hash")
        _digest(self.boundary_rule_source_hash, "boundary_rule_source_hash")
        if self.source_id != SINA_QUOTE_SOURCE_ID:
            raise CloseSnapshotSimulationValidationError(
                "only the captured Sina source is supported"
            )
        if self.status_mapping_sha256 != SINA_VENDOR_STATUS_MAPPING_SHA256:
            raise CloseSnapshotSimulationValidationError("vendor status mapping hash differs")
        if (
            type(self.trusted_vendor_status_codes) is not tuple
            or not self.trusted_vendor_status_codes
            or len(set(self.trusted_vendor_status_codes)) != len(self.trusted_vendor_status_codes)
        ):
            raise CloseSnapshotSimulationValidationError("trusted status codes must be explicit")
        for code in self.trusted_vendor_status_codes:
            _token(code, "trusted vendor status code")
        _aware(self.available_from, "available_from")
        _aware(self.available_until, "available_until")
        if self.available_from >= self.available_until:
            raise CloseSnapshotSimulationValidationError("policy availability window is empty")
        if (
            self.available_from.astimezone(_SHANGHAI).date() != self.trading_date
            or self.available_until.astimezone(_SHANGHAI).date() != self.trading_date
        ):
            raise CloseSnapshotSimulationValidationError(
                "policy availability must be bounded to its trading date"
            )
        if self.price_rule != _PRICE_RULE:
            raise CloseSnapshotSimulationValidationError("unsupported close snapshot price rule")
        if self.price_boundary_mode is PriceBoundaryMode.UNKNOWN:
            raise CloseSnapshotSimulationValidationError("unknown price boundary cannot qualify")
        if self.price_boundary_mode is PriceBoundaryMode.LIMITED:
            lower_factor = _positive_decimal(self.lower_boundary_factor, "lower_boundary_factor")
            upper_factor = _positive_decimal(self.upper_boundary_factor, "upper_boundary_factor")
            if lower_factor >= upper_factor:
                raise CloseSnapshotSimulationValidationError("paper boundary factors are reversed")
            if self.unrestricted_reason_code is not None:
                raise CloseSnapshotSimulationValidationError(
                    "limited boundary cannot carry unrestricted reason"
                )
        elif self.price_boundary_mode is PriceBoundaryMode.UNRESTRICTED:
            if self.lower_boundary_factor is not None or self.upper_boundary_factor is not None:
                raise CloseSnapshotSimulationValidationError(
                    "unrestricted boundary cannot carry factors"
                )
            _token(self.unrestricted_reason_code, "unrestricted_reason_code")
        else:
            raise CloseSnapshotSimulationValidationError("price boundary mode is invalid")
        object.__setattr__(
            self, "content_hash", _seal_hash(self._content_payload(), self.content_hash)
        )

    def _content_payload(self) -> dict[str, object]:
        """Build the exact policy content that is covered by its hash."""

        return {
            "schema": _POLICY_SCHEMA,
            "purpose": self.purpose,
            "policy_id": self.policy_id,
            "policy_version": self.policy_version,
            "account_id": self.account_id,
            "security_id": self.security_id,
            "asset_code": self.asset_code,
            "market": self.market,
            "board": self.board,
            "trading_date": self.trading_date.isoformat(),
            "source_id": self.source_id,
            "source_name": self.source_name,
            "usage_ttl_seconds": self.usage_ttl_seconds,
            "status_mapping_sha256": self.status_mapping_sha256,
            "trusted_vendor_status_codes": list(self.trusted_vendor_status_codes),
            "available_from": _utc_text(self.available_from),
            "available_until": _utc_text(self.available_until),
            "price_rule": self.price_rule,
            "price_rule_source_hash": self.price_rule_source_hash,
            "price_boundary_mode": self.price_boundary_mode.value,
            "lower_boundary_factor": _decimal_text(self.lower_boundary_factor),
            "upper_boundary_factor": _decimal_text(self.upper_boundary_factor),
            "boundary_rule_source_id": self.boundary_rule_source_id,
            "boundary_rule_version": self.boundary_rule_version,
            "boundary_rule_source_hash": self.boundary_rule_source_hash,
            "unrestricted_reason_code": self.unrestricted_reason_code,
        }

    def to_payload(self) -> CloseSnapshotSimulationPolicyPayload:
        """Return strict JSON-safe policy fields and the canonical content hash."""

        self.__post_init__()
        return cast(
            CloseSnapshotSimulationPolicyPayload,
            {**self._content_payload(), "content_hash": self.content_hash},
        )

    @classmethod
    def from_payload(cls, payload: object) -> CloseSnapshotSimulationPolicy:
        """Rebuild an exact policy payload and reject unknown or changed fields."""

        if type(payload) is not dict:
            raise CloseSnapshotSimulationValidationError("policy must be a plain object")
        payload_keys = frozenset(payload)
        if payload_keys not in (_POLICY_KEYS, _POLICY_KEYS - {"content_hash"}):
            raise CloseSnapshotSimulationValidationError("policy fields are incomplete or unknown")
        values = cast(dict[str, object], payload)
        if values["schema"] != _POLICY_SCHEMA or values["purpose"] != _PURPOSE:
            raise CloseSnapshotSimulationValidationError("policy schema or purpose is invalid")
        codes = values["trusted_vendor_status_codes"]
        if type(codes) is not list or any(type(code) is not str for code in codes):
            raise CloseSnapshotSimulationValidationError("trusted status code payload is invalid")
        lower_factor = _parse_decimal_or_none(values["lower_boundary_factor"])
        upper_factor = _parse_decimal_or_none(values["upper_boundary_factor"])
        policy = cls(
            policy_id=_string(values["policy_id"], "policy_id"),
            policy_version=_string(values["policy_version"], "policy_version"),
            account_id=_integer(values["account_id"], "account_id"),
            security_id=_string(values["security_id"], "security_id"),
            asset_code=_string(values["asset_code"], "asset_code"),
            market=_string(values["market"], "market"),
            board=_string(values["board"], "board"),
            trading_date=_parse_date(values["trading_date"]),
            source_id=_string(values["source_id"], "source_id"),
            source_name=_string(values["source_name"], "source_name"),
            usage_ttl_seconds=_integer(values["usage_ttl_seconds"], "usage_ttl_seconds"),
            status_mapping_sha256=_string(values["status_mapping_sha256"], "status_mapping_sha256"),
            trusted_vendor_status_codes=tuple(codes),
            available_from=_parse_utc(values["available_from"]),
            available_until=_parse_utc(values["available_until"]),
            price_rule=_string(values["price_rule"], "price_rule"),
            price_rule_source_hash=_string(
                values["price_rule_source_hash"], "price_rule_source_hash"
            ),
            price_boundary_mode=_enum_value(PriceBoundaryMode, values["price_boundary_mode"]),
            lower_boundary_factor=lower_factor,
            upper_boundary_factor=upper_factor,
            boundary_rule_source_id=_string(
                values["boundary_rule_source_id"], "boundary_rule_source_id"
            ),
            boundary_rule_version=_string(values["boundary_rule_version"], "boundary_rule_version"),
            boundary_rule_source_hash=_string(
                values["boundary_rule_source_hash"], "boundary_rule_source_hash"
            ),
            unrestricted_reason_code=_optional_string(
                values["unrestricted_reason_code"], "unrestricted_reason_code"
            ),
            content_hash=(
                _string(values["content_hash"], "content_hash") if "content_hash" in values else ""
            ),
        )
        expected_payload = policy.to_payload()
        input_without_hash = {key: value for key, value in values.items() if key != "content_hash"}
        expected_without_hash = {
            key: value for key, value in expected_payload.items() if key != "content_hash"
        }
        supplied_hash = values.get("content_hash")
        if supplied_hash not in (None, "", policy.content_hash) or (
            input_without_hash != expected_without_hash
        ):
            raise CloseSnapshotSimulationValidationError("policy payload is not canonical")
        return policy


@dataclass(frozen=True, slots=True)
class CloseSnapshotSimulationMarket:
    """Expose closed-session quote evidence without V2's continuous-stage claim."""

    market_evidence_v1: ExecutionMarketEvidence
    latest: QuoteValue
    previous_close: QuoteValue
    price_observation_kind: str = _PRICE_OBSERVATION_KIND
    price_boundary_basis: str = _PRICE_BOUNDARY_BASIS
    security_state_basis: str = _SECURITY_STATE_BASIS
    content_hash: str = ""

    def __post_init__(self) -> None:
        """Require explicit CLOSED, vendor-last provenance, and exact quote binding."""

        if type(self.market_evidence_v1) is not ExecutionMarketEvidence:
            raise CloseSnapshotSimulationValidationError("market evidence is invalid")
        self.market_evidence_v1.__post_init__()
        if self.market_evidence_v1.session_state is not SessionState.CLOSED:
            raise CloseSnapshotSimulationValidationError("close snapshot must remain CLOSED")
        if self.market_evidence_v1.security_state is not SecurityTradingState.TRADING:
            raise CloseSnapshotSimulationValidationError("vendor status is not tradable")
        if self.price_observation_kind != _PRICE_OBSERVATION_KIND:
            raise CloseSnapshotSimulationValidationError("price observation kind is invalid")
        if self.price_boundary_basis != _PRICE_BOUNDARY_BASIS:
            raise CloseSnapshotSimulationValidationError("price boundary basis is invalid")
        if self.security_state_basis != _SECURITY_STATE_BASIS:
            raise CloseSnapshotSimulationValidationError("security state basis is invalid")
        for name, quote in (("latest", self.latest), ("previous_close", self.previous_close)):
            if type(quote) is not QuoteValue:
                raise CloseSnapshotSimulationValidationError(f"{name} quote is invalid")
            quote.__post_init__()
            if quote.state is not QuoteValueState.PRESENT or quote.value is None:
                raise CloseSnapshotSimulationValidationError(f"{name} quote must be present")
        if self.market_evidence_v1.reference_price != self.latest.value:
            raise CloseSnapshotSimulationValidationError("reference price differs from vendor last")
        object.__setattr__(
            self, "content_hash", _seal_hash(self._content_payload(), self.content_hash)
        )

    def _content_payload(self) -> dict[str, object]:
        """Build quote and closed-session evidence fields before hashing."""

        return {
            "market_evidence_v1": self.market_evidence_v1.to_payload(),
            "latest": self.latest.to_payload(),
            "previous_close": self.previous_close.to_payload(),
            "price_observation_kind": self.price_observation_kind,
            "price_boundary_basis": self.price_boundary_basis,
            "security_state_basis": self.security_state_basis,
        }

    def to_payload(self) -> dict[str, object]:
        """Return closed-session market evidence without a fabricated V2 stage."""

        self.__post_init__()
        return {**self._content_payload(), "content_hash": self.content_hash}


@dataclass(frozen=True, slots=True)
class CloseSnapshotSimulationBundle:
    """Retain the actual capture, close calendar, policy, rule, and market hashes."""

    capture: SinaQuoteCapture
    policy: CloseSnapshotSimulationPolicy
    calendar: LocalSimulatedCalendarContext
    execution_rule_content_hash: str
    market: CloseSnapshotSimulationMarket
    purpose: str = _PURPOSE

    def __post_init__(self) -> None:
        """Reject bundles whose captured source and published scopes do not agree."""

        if self.purpose != _PURPOSE:
            raise CloseSnapshotSimulationValidationError("bundle purpose is invalid")
        if type(self.capture) is not SinaQuoteCapture:
            raise CloseSnapshotSimulationValidationError("capture is invalid")
        if type(self.policy) is not CloseSnapshotSimulationPolicy:
            raise CloseSnapshotSimulationValidationError("policy is invalid")
        if type(self.calendar) is not LocalSimulatedCalendarContext:
            raise CloseSnapshotSimulationValidationError("calendar is invalid")
        if type(self.market) is not CloseSnapshotSimulationMarket:
            raise CloseSnapshotSimulationValidationError("close snapshot market is invalid")
        self.capture.__post_init__()
        self.policy.__post_init__()
        self.calendar.__post_init__()
        self.market.__post_init__()
        _digest(self.execution_rule_content_hash, "execution_rule_content_hash")
        evidence = self.market.market_evidence_v1
        if (
            self.capture.asset_code != self.policy.asset_code
            or self.calendar.trading_date != self.policy.trading_date
            or self.calendar.session_state is not SessionState.CLOSED
            or evidence.security_id != self.policy.security_id
            or evidence.market != self.policy.market
            or evidence.board != self.policy.board
            or evidence.trading_date != self.policy.trading_date
            or evidence.calendar_source_hash != self.calendar.calendar_source_hash
            or evidence.market_source_id != self.policy.source_id
            or evidence.session_state is not SessionState.CLOSED
        ):
            raise CloseSnapshotSimulationValidationError("bundle scopes do not match")

    @property
    def content_hash(self) -> str:
        """Return a digest binding raw body, policy, calendar, execution rule, and quote."""

        return _canonical_hash(self._content_payload())

    def _content_payload(self) -> dict[str, object]:
        """Build the retained signed-token body without its outer hash."""

        return {
            "schema": _BUNDLE_SCHEMA,
            "purpose": self.purpose,
            "capture": self.capture.to_payload(),
            "policy": self.policy.to_payload(),
            "calendar": self.calendar.to_payload(),
            "execution_rule_content_hash": self.execution_rule_content_hash,
            "market": self.market.to_payload(),
            "market_available_at_basis": _MARKET_AVAILABLE_AT_BASIS,
        }

    def to_payload(self) -> dict[str, object]:
        """Return the complete close-snapshot source envelope for retained audit."""

        self.__post_init__()
        return {**self._content_payload(), "content_hash": self.content_hash}


@dataclass(frozen=True, slots=True)
class CloseSnapshotSimulationDecision:
    """A content-addressed close-snapshot qualification for local simulation only."""

    status: CloseSnapshotSimulationStatus
    reason_codes: tuple[CloseSnapshotSimulationReason | ExecutionDenyCode, ...]
    account_id: int
    security_id: str
    asset_code: str
    trading_date: date
    requested_price: Decimal | None
    evaluated_at: datetime
    capture_body_sha256: str | None
    policy_content_hash: str | None
    calendar_content_hash: str | None
    execution_rule_content_hash: str | None
    market_content_hash: str | None
    order_id: str | None = None
    order_content_hash: str | None = None
    content_hash: str = ""

    def __post_init__(self) -> None:
        """Validate status/reason consistency and all retained provenance digests."""

        if type(self.status) is not CloseSnapshotSimulationStatus:
            raise CloseSnapshotSimulationValidationError("decision status is invalid")
        if type(self.reason_codes) is not tuple or any(
            type(reason) not in (CloseSnapshotSimulationReason, ExecutionDenyCode)
            for reason in self.reason_codes
        ):
            raise CloseSnapshotSimulationValidationError("decision reason codes are invalid")
        if len(set(self.reason_codes)) != len(self.reason_codes):
            raise CloseSnapshotSimulationValidationError("decision reasons must be unique")
        if self.status is CloseSnapshotSimulationStatus.QUALIFIED and self.reason_codes:
            raise CloseSnapshotSimulationValidationError(
                "qualified decision cannot contain reasons"
            )
        if self.status is CloseSnapshotSimulationStatus.BLOCKED and not self.reason_codes:
            raise CloseSnapshotSimulationValidationError("blocked decision requires a reason")
        if type(self.account_id) is not int or self.account_id <= 0:
            raise CloseSnapshotSimulationValidationError("decision account_id is invalid")
        _token(self.security_id, "security_id")
        _token(self.asset_code, "asset_code")
        if type(self.trading_date) is not date:
            raise CloseSnapshotSimulationValidationError("decision trading_date is invalid")
        if self.requested_price is not None:
            _positive_decimal(self.requested_price, "requested_price")
        _aware(self.evaluated_at, "evaluated_at")
        for name in (
            "capture_body_sha256",
            "policy_content_hash",
            "calendar_content_hash",
            "execution_rule_content_hash",
            "market_content_hash",
        ):
            value = getattr(self, name)
            if value is not None:
                _digest(value, name)
        if self.order_id is not None:
            _token(self.order_id, "order_id")
        if self.order_content_hash is not None:
            _digest(self.order_content_hash, "order_content_hash")
        if (self.order_id is None) != (self.order_content_hash is None):
            raise CloseSnapshotSimulationValidationError("order binding is incomplete")
        object.__setattr__(
            self, "content_hash", _seal_hash(self._content_payload(), self.content_hash)
        )

    def _content_payload(self) -> dict[str, object]:
        """Build the exact decision evidence covered by its digest."""

        return {
            "schema": _DECISION_SCHEMA,
            "purpose": _PURPOSE,
            "status": self.status.value,
            "reason_codes": [reason.value for reason in self.reason_codes],
            "account_id": self.account_id,
            "security_id": self.security_id,
            "asset_code": self.asset_code,
            "trading_date": self.trading_date.isoformat(),
            "requested_price": _decimal_text(self.requested_price),
            "evaluated_at": _utc_text(self.evaluated_at),
            "capture_body_sha256": self.capture_body_sha256,
            "policy_content_hash": self.policy_content_hash,
            "calendar_content_hash": self.calendar_content_hash,
            "execution_rule_content_hash": self.execution_rule_content_hash,
            "market_content_hash": self.market_content_hash,
            "order_id": self.order_id,
            "order_content_hash": self.order_content_hash,
        }

    def to_payload(self) -> dict[str, object]:
        """Return status, stable reasons, clocks, bindings, and the decision hash."""

        self.__post_init__()
        return {**self._content_payload(), "content_hash": self.content_hash}


@dataclass(frozen=True, slots=True)
class CloseSnapshotSimulationEvaluation:
    """Pair the close-only decision with its retained market bundle when qualified."""

    decision: CloseSnapshotSimulationDecision
    bundle: CloseSnapshotSimulationBundle | None

    def __post_init__(self) -> None:
        """Ensure only qualified evaluations carry a source bundle."""

        if type(self.decision) is not CloseSnapshotSimulationDecision:
            raise CloseSnapshotSimulationValidationError("evaluation decision is invalid")
        if self.bundle is not None and type(self.bundle) is not CloseSnapshotSimulationBundle:
            raise CloseSnapshotSimulationValidationError("evaluation bundle is invalid")
        if (self.bundle is None) != (self.decision.status is CloseSnapshotSimulationStatus.BLOCKED):
            raise CloseSnapshotSimulationValidationError("decision and bundle state differ")


def evaluate_close_snapshot_simulation(
    *,
    capture: SinaQuoteCapture | None,
    policy: CloseSnapshotSimulationPolicy | None,
    calendar: LocalSimulatedCalendarContext | None,
    rule: ExecutionSubmissionRuleV2 | None,
    account_id: int,
    security_id: str,
    asset_code: str,
    trading_date: date,
    requested_price: Decimal | None,
    as_of: datetime,
) -> CloseSnapshotSimulationEvaluation:
    """Qualify an exact after-close Sina last quote for one scoped simulation.

    The evaluation preserves both the vendor's source-observation clock and
    local HTTP response-completion clock. It always emits actual CLOSED
    calendar state; successful output is neither a continuous market view nor
    an official exchange closing-price claim.
    """

    reasons: list[CloseSnapshotSimulationReason] = []
    if capture is None:
        reasons.append(CloseSnapshotSimulationReason.CAPTURE_MISSING)
    if policy is None:
        reasons.append(CloseSnapshotSimulationReason.POLICY_MISSING)
    if calendar is None:
        reasons.append(CloseSnapshotSimulationReason.CALENDAR_MISSING)
    if rule is None:
        reasons.append(CloseSnapshotSimulationReason.RULE_MISSING)
    _aware(as_of, "as_of")
    if not _is_positive_int(account_id):
        raise CloseSnapshotSimulationValidationError("account_id must be positive")
    _token(security_id, "security_id")
    _token(asset_code, "asset_code")
    if type(trading_date) is not date:
        raise CloseSnapshotSimulationValidationError("trading_date must be an exact date")
    if requested_price is not None:
        _positive_decimal(requested_price, "requested_price")
    if reasons:
        return _blocked_evaluation(
            reasons,
            account_id=account_id,
            security_id=security_id,
            asset_code=asset_code,
            trading_date=trading_date,
            requested_price=requested_price,
            as_of=as_of,
            capture=capture,
            policy=policy,
            calendar=calendar,
            rule=rule,
        )

    assert capture is not None and policy is not None and calendar is not None and rule is not None
    try:
        capture.__post_init__()
        policy.__post_init__()
        calendar.__post_init__()
        rule.__post_init__()
    except (AttributeError, ArithmeticError, TypeError, ValueError):
        reasons.append(CloseSnapshotSimulationReason.INVALID_INPUT)
        return _blocked_evaluation(
            reasons,
            account_id=account_id,
            security_id=security_id,
            asset_code=asset_code,
            trading_date=trading_date,
            requested_price=requested_price,
            as_of=as_of,
            capture=capture,
            policy=policy,
            calendar=calendar,
            rule=rule,
        )

    if (
        account_id != policy.account_id
        or security_id != policy.security_id
        or asset_code != policy.asset_code
        or trading_date != policy.trading_date
    ):
        reasons.append(CloseSnapshotSimulationReason.POLICY_SCOPE_MISMATCH)
    if policy.source_id != SINA_QUOTE_SOURCE_ID:
        reasons.append(CloseSnapshotSimulationReason.SOURCE_UNSUPPORTED)
    if policy.status_mapping_sha256 != SINA_VENDOR_STATUS_MAPPING_SHA256:
        reasons.append(CloseSnapshotSimulationReason.STATUS_MAPPING_MISMATCH)
    if (
        rule.execution_rule_v1.security_id != policy.security_id
        or rule.execution_rule_v1.market != policy.market
        or rule.execution_rule_v1.board != policy.board
    ):
        reasons.append(CloseSnapshotSimulationReason.RULE_SCOPE_MISMATCH)
    if calendar.session_state is not SessionState.CLOSED:
        reasons.append(CloseSnapshotSimulationReason.CALENDAR_NOT_CLOSED)
    if (
        calendar.trading_date != policy.trading_date
        or calendar.session_timezone != "Asia/Shanghai"
        or calendar.session_open_at.astimezone(_SHANGHAI).date() != policy.trading_date
        or calendar.session_close_at.astimezone(_SHANGHAI).date() != policy.trading_date
    ):
        reasons.append(CloseSnapshotSimulationReason.CALENDAR_SCOPE_MISMATCH)
    if calendar.calendar_available_at > capture.response_completed_at:
        reasons.append(CloseSnapshotSimulationReason.CALENDAR_NOT_AVAILABLE)
    if as_of >= calendar.calendar_valid_until:
        reasons.append(CloseSnapshotSimulationReason.CALENDAR_EXPIRED)
    if capture.asset_code != policy.asset_code or not capture.usable_parse:
        reasons.append(CloseSnapshotSimulationReason.CAPTURE_UNUSABLE)

    quote = capture.quote
    source_at: datetime | None = None
    if quote is None:
        reasons.append(CloseSnapshotSimulationReason.CAPTURE_UNUSABLE)
    else:
        if quote.source_clock_status is SinaQuoteClockStatus.FUTURE:
            reasons.append(CloseSnapshotSimulationReason.SOURCE_CLOCK_FUTURE)
        elif (
            quote.source_clock_status is not SinaQuoteClockStatus.VALID
            or quote.source_observed_at is None
        ):
            reasons.append(CloseSnapshotSimulationReason.SOURCE_CLOCK_UNKNOWN)
        else:
            source_at = quote.source_observed_at
            if source_at.astimezone(_SHANGHAI).date() != policy.trading_date:
                reasons.append(CloseSnapshotSimulationReason.SOURCE_DATE_MISMATCH)
            if source_at < calendar.session_close_at:
                reasons.append(CloseSnapshotSimulationReason.SOURCE_PRE_CLOSE)
        if quote.vendor_status_code not in policy.trusted_vendor_status_codes:
            reasons.append(CloseSnapshotSimulationReason.SOURCE_STATUS_UNTRUSTED)
        if quote.reported_trading_state is not SinaReportedTradingState.TRADING:
            reasons.append(CloseSnapshotSimulationReason.SOURCE_NOT_TRADING)

    if policy.available_from < calendar.session_close_at:
        reasons.append(CloseSnapshotSimulationReason.POLICY_WINDOW_NOT_STARTED)
    if as_of < policy.available_from or capture.response_completed_at < policy.available_from:
        reasons.append(CloseSnapshotSimulationReason.POLICY_WINDOW_NOT_STARTED)
    if as_of >= policy.available_until:
        reasons.append(CloseSnapshotSimulationReason.POLICY_WINDOW_EXPIRED)
    if capture.request_started_at < calendar.session_close_at:
        reasons.append(CloseSnapshotSimulationReason.CAPTURE_NOT_AFTER_CLOSE)
    if capture.response_completed_at > as_of:
        reasons.append(CloseSnapshotSimulationReason.CAPTURE_CLOCK_IN_FUTURE)

    execution_rule = rule.execution_rule_v1
    if execution_rule.source_available_at > capture.response_completed_at:
        reasons.append(CloseSnapshotSimulationReason.RULE_NOT_AVAILABLE)
    if as_of < execution_rule.effective_from or as_of < execution_rule.source_available_at:
        reasons.append(CloseSnapshotSimulationReason.RULE_NOT_AVAILABLE)
    if as_of >= execution_rule.valid_until:
        reasons.append(CloseSnapshotSimulationReason.RULE_EXPIRED)

    if quote is None or quote.last_price is None:
        reasons.append(CloseSnapshotSimulationReason.PRICE_MISSING)
    if quote is None or quote.previous_close is None:
        reasons.append(CloseSnapshotSimulationReason.PREVIOUS_CLOSE_MISSING)
    if requested_price is None:
        reasons.append(CloseSnapshotSimulationReason.PRICE_MISSING)

    if as_of - capture.response_completed_at > timedelta(seconds=policy.usage_ttl_seconds):
        reasons.append(CloseSnapshotSimulationReason.USAGE_TTL_EXPIRED)

    lower: Decimal | None = None
    upper: Decimal | None = None
    if quote is not None and quote.last_price is not None and quote.previous_close is not None:
        tick = execution_rule.price_tick
        if not _is_tick_multiple(quote.last_price, tick) or (
            requested_price is not None and not _is_tick_multiple(requested_price, tick)
        ):
            reasons.append(CloseSnapshotSimulationReason.PRICE_NOT_ON_TICK)
        if requested_price is not None and requested_price != quote.last_price:
            reasons.append(CloseSnapshotSimulationReason.PRICE_DIFFERS_FROM_SNAPSHOT)
        try:
            if policy.price_boundary_mode is PriceBoundaryMode.LIMITED:
                if policy.lower_boundary_factor is None or policy.upper_boundary_factor is None:
                    raise CloseSnapshotSimulationValidationError("paper factors are missing")
                lower = _round_to_tick(
                    Fraction(quote.previous_close) * Fraction(policy.lower_boundary_factor), tick
                )
                upper = _round_to_tick(
                    Fraction(quote.previous_close) * Fraction(policy.upper_boundary_factor), tick
                )
            elif policy.price_boundary_mode is not PriceBoundaryMode.UNRESTRICTED:
                raise CloseSnapshotSimulationValidationError("price boundary is unknown")
        except (ArithmeticError, TypeError, ValueError):
            reasons.append(CloseSnapshotSimulationReason.BOUNDARY_POLICY_UNKNOWN)
        if lower is not None and upper is not None and not lower <= quote.last_price <= upper:
            reasons.append(CloseSnapshotSimulationReason.PRICE_OUTSIDE_PAPER_BOUNDARY)
        if (
            lower is not None
            and upper is not None
            and requested_price is not None
            and not lower <= requested_price <= upper
        ):
            reasons.append(CloseSnapshotSimulationReason.PRICE_OUTSIDE_PAPER_BOUNDARY)

    _deduplicate(reasons)
    if reasons:
        return _blocked_evaluation(
            reasons,
            account_id=account_id,
            security_id=security_id,
            asset_code=asset_code,
            trading_date=trading_date,
            requested_price=requested_price,
            as_of=as_of,
            capture=capture,
            policy=policy,
            calendar=calendar,
            rule=rule,
        )

    assert quote is not None and quote.last_price is not None and quote.previous_close is not None
    assert source_at is not None and requested_price is not None
    valid_until = min(
        policy.available_until,
        capture.response_completed_at + timedelta(seconds=policy.usage_ttl_seconds),
        calendar.calendar_valid_until,
        execution_rule.valid_until,
    )
    if valid_until <= capture.response_completed_at or as_of >= valid_until:
        return _blocked_evaluation(
            [CloseSnapshotSimulationReason.VALIDITY_WINDOW_EMPTY],
            account_id=account_id,
            security_id=security_id,
            asset_code=asset_code,
            trading_date=trading_date,
            requested_price=requested_price,
            as_of=as_of,
            capture=capture,
            policy=policy,
            calendar=calendar,
            rule=rule,
        )

    source_hash = _canonical_hash(
        {
            "capture_body_sha256": capture.body_sha256,
            "policy_content_hash": policy.content_hash,
            "calendar_content_hash": calendar.content_hash,
            "execution_rule_content_hash": rule.content_hash,
            "price_rule_source_hash": policy.price_rule_source_hash,
            "boundary_rule_source_hash": policy.boundary_rule_source_hash,
        }
    )
    evidence = ExecutionMarketEvidence(
        security_id=policy.security_id,
        market=policy.market,
        board=policy.board,
        trading_date=policy.trading_date,
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
        session_state=SessionState.CLOSED,
        security_state=SecurityTradingState.TRADING,
        market_source_id=policy.source_id,
        market_source_version="sina-quote-capture.v1",
        market_source_hash=source_hash,
        price_boundary_mode=policy.price_boundary_mode,
        lower_limit_price=lower,
        upper_limit_price=upper,
        reference_price=quote.last_price,
        market_observed_at=source_at,
        market_available_at=capture.response_completed_at,
        market_valid_until=valid_until,
    )
    market = CloseSnapshotSimulationMarket(
        market_evidence_v1=evidence,
        latest=QuoteValue(QuoteValueState.PRESENT, quote.last_price),
        previous_close=QuoteValue(QuoteValueState.PRESENT, quote.previous_close),
    )
    bundle = CloseSnapshotSimulationBundle(
        capture=capture,
        policy=policy,
        calendar=calendar,
        execution_rule_content_hash=rule.content_hash,
        market=market,
    )
    decision = CloseSnapshotSimulationDecision(
        status=CloseSnapshotSimulationStatus.QUALIFIED,
        reason_codes=(),
        account_id=account_id,
        security_id=security_id,
        asset_code=asset_code,
        trading_date=trading_date,
        requested_price=requested_price,
        evaluated_at=as_of,
        capture_body_sha256=capture.body_sha256,
        policy_content_hash=policy.content_hash,
        calendar_content_hash=calendar.content_hash,
        execution_rule_content_hash=rule.content_hash,
        market_content_hash=market.content_hash,
    )
    return CloseSnapshotSimulationEvaluation(decision=decision, bundle=bundle)


def evaluate_close_snapshot_order(
    *,
    rule: ExecutionSubmissionRuleV2,
    bundle: CloseSnapshotSimulationBundle,
    order: ExecutionOrder,
    as_of: datetime,
) -> CloseSnapshotSimulationDecision:
    """Requalify source evidence and apply common execution terms to one exact order.

    The supplied order must use the exact Sina last quote. This assessment
    reuses A-share scope, effective-rule, calendar, price, lot, and position
    checks, while the close-only source evaluator supplies its own CLOSED,
    after-close, usage-TTL, and purpose restrictions.
    """

    if type(rule) is not ExecutionSubmissionRuleV2:
        raise CloseSnapshotSimulationValidationError("rule must be ExecutionSubmissionRuleV2")
    if type(bundle) is not CloseSnapshotSimulationBundle:
        raise CloseSnapshotSimulationValidationError("bundle must be CloseSnapshotSimulationBundle")
    if type(order) is not ExecutionOrder:
        raise CloseSnapshotSimulationValidationError("order must be ExecutionOrder")
    _aware(as_of, "as_of")
    try:
        rule.__post_init__()
        bundle.__post_init__()
        order.__post_init__()
    except (AttributeError, ArithmeticError, TypeError, ValueError) as error:
        raise CloseSnapshotSimulationValidationError(
            "close-order input failed contract revalidation"
        ) from error
    source_evaluation = evaluate_close_snapshot_simulation(
        capture=bundle.capture,
        policy=bundle.policy,
        calendar=bundle.calendar,
        rule=rule,
        account_id=order.account_id,
        security_id=order.security_id,
        asset_code=bundle.policy.asset_code,
        trading_date=bundle.policy.trading_date,
        requested_price=order.limit_price,
        as_of=as_of,
    )
    source_decision = source_evaluation.decision
    if source_evaluation.bundle is None:
        return _decision_for_order(source_decision, order)
    if rule.content_hash != bundle.execution_rule_content_hash:
        return _decision_for_order(
            source_decision,
            order,
            additional_reasons=(CloseSnapshotSimulationReason.RULE_CONTENT_HASH_MISMATCH,),
            execution_rule_content_hash=bundle.execution_rule_content_hash,
            market_content_hash=bundle.market.content_hash,
        )

    assessment = evaluate_execution_terms(
        rule.execution_rule_v1,
        source_evaluation.bundle.market.market_evidence_v1,
        order,
        as_of,
    )
    reasons: tuple[CloseSnapshotSimulationReason | ExecutionDenyCode, ...] = assessment.reason_codes
    return CloseSnapshotSimulationDecision(
        status=(
            CloseSnapshotSimulationStatus.QUALIFIED
            if not reasons
            else CloseSnapshotSimulationStatus.BLOCKED
        ),
        reason_codes=reasons,
        account_id=source_decision.account_id,
        security_id=source_decision.security_id,
        asset_code=source_decision.asset_code,
        trading_date=source_decision.trading_date,
        requested_price=order.limit_price,
        evaluated_at=as_of,
        capture_body_sha256=source_decision.capture_body_sha256,
        policy_content_hash=source_decision.policy_content_hash,
        calendar_content_hash=source_decision.calendar_content_hash,
        execution_rule_content_hash=source_decision.execution_rule_content_hash,
        market_content_hash=source_decision.market_content_hash,
        order_id=order.order_id,
        order_content_hash=_canonical_hash(order.to_payload()),
    )


def _decision_for_order(
    source_decision: CloseSnapshotSimulationDecision,
    order: ExecutionOrder,
    *,
    additional_reasons: tuple[CloseSnapshotSimulationReason, ...] = (),
    execution_rule_content_hash: str | None = None,
    market_content_hash: str | None = None,
) -> CloseSnapshotSimulationDecision:
    """Bind source blockers to the exact order without treating it as evaluated."""

    return CloseSnapshotSimulationDecision(
        status=CloseSnapshotSimulationStatus.BLOCKED,
        reason_codes=tuple(dict.fromkeys(source_decision.reason_codes + additional_reasons)),
        account_id=order.account_id,
        security_id=order.security_id,
        asset_code=source_decision.asset_code,
        trading_date=source_decision.trading_date,
        requested_price=order.limit_price,
        evaluated_at=source_decision.evaluated_at,
        capture_body_sha256=source_decision.capture_body_sha256,
        policy_content_hash=source_decision.policy_content_hash,
        calendar_content_hash=source_decision.calendar_content_hash,
        execution_rule_content_hash=(
            execution_rule_content_hash or source_decision.execution_rule_content_hash
        ),
        market_content_hash=market_content_hash or source_decision.market_content_hash,
        order_id=order.order_id,
        order_content_hash=_canonical_hash(order.to_payload()),
    )


def _blocked_evaluation(
    reasons: list[CloseSnapshotSimulationReason],
    *,
    account_id: int,
    security_id: str,
    asset_code: str,
    trading_date: date,
    requested_price: Decimal | None,
    as_of: datetime,
    capture: SinaQuoteCapture | None,
    policy: CloseSnapshotSimulationPolicy | None,
    calendar: LocalSimulatedCalendarContext | None,
    rule: ExecutionSubmissionRuleV2 | None,
) -> CloseSnapshotSimulationEvaluation:
    """Return a stable blocked result while preserving hashes for present inputs."""

    _deduplicate(reasons)
    safe_as_of = _aware(as_of, "as_of")
    safe_account_id = account_id
    safe_security_id = _token(security_id, "security_id")
    safe_asset_code = _token(asset_code, "asset_code")
    if type(trading_date) is not date:
        raise CloseSnapshotSimulationValidationError("trading_date must be an exact date")
    safe_trading_date = trading_date
    if requested_price is not None:
        _positive_decimal(requested_price, "requested_price")
    safe_price = requested_price
    decision = CloseSnapshotSimulationDecision(
        status=CloseSnapshotSimulationStatus.BLOCKED,
        reason_codes=tuple(reasons),
        account_id=safe_account_id,
        security_id=safe_security_id,
        asset_code=safe_asset_code,
        trading_date=safe_trading_date,
        requested_price=safe_price,
        evaluated_at=safe_as_of,
        capture_body_sha256=_safe_digest(
            capture.body_sha256 if type(capture) is SinaQuoteCapture else None
        ),
        policy_content_hash=_safe_digest(
            policy.content_hash if type(policy) is CloseSnapshotSimulationPolicy else None
        ),
        calendar_content_hash=_safe_digest(
            calendar.content_hash if type(calendar) is LocalSimulatedCalendarContext else None
        ),
        execution_rule_content_hash=_safe_digest(
            rule.content_hash if type(rule) is ExecutionSubmissionRuleV2 else None
        ),
        market_content_hash=None,
    )
    return CloseSnapshotSimulationEvaluation(decision=decision, bundle=None)


def _round_to_tick(value: Fraction, tick: Decimal) -> Decimal:
    """Round an exact positive fraction to the rule tick using HALF_UP."""

    tick_fraction = Fraction(tick)
    if value <= 0 or tick_fraction <= 0:
        raise CloseSnapshotSimulationValidationError("price and tick must be positive")
    raw_ticks = value / tick_fraction
    ticks = (2 * raw_ticks.numerator + raw_ticks.denominator) // (2 * raw_ticks.denominator)
    if ticks <= 0:
        raise CloseSnapshotSimulationValidationError("paper boundary rounds to zero")
    tick_parts = tick.as_tuple()
    if type(tick_parts.exponent) is not int:
        raise CloseSnapshotSimulationValidationError("price tick exponent is invalid")
    coefficient = int("".join(str(digit) for digit in tick_parts.digits)) * ticks
    return Decimal(
        (0, tuple(int(character) for character in str(coefficient)), tick_parts.exponent)
    )


def _is_tick_multiple(value: Decimal, tick: Decimal) -> bool:
    """Check exact price tick alignment without using rounded Decimal context."""

    return Fraction(value) % Fraction(tick) == 0


def _canonical_hash(payload: dict[str, object]) -> str:
    """Hash one JSON-safe canonical contract payload."""

    try:
        encoded = json.dumps(
            payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
        ).encode("utf-8")
    except (TypeError, ValueError) as error:
        raise CloseSnapshotSimulationValidationError("payload is not canonical JSON") from error
    return hashlib.sha256(encoded).hexdigest()


def _seal_hash(payload: dict[str, object], supplied: object) -> str:
    """Validate a supplied hash or compute it for a new immutable value."""

    if type(supplied) is not str:
        raise CloseSnapshotSimulationValidationError("content hash must be a string")
    actual = _canonical_hash(payload)
    if supplied and supplied != actual:
        raise CloseSnapshotSimulationValidationError("content hash does not match payload")
    return actual


def _token(value: object, name: str) -> str:
    """Require one bounded canonical token without whitespace."""

    if (
        type(value) is not str
        or not value
        or value.strip() != value
        or len(value) > 192
        or any(character.isspace() for character in value)
    ):
        raise CloseSnapshotSimulationValidationError(f"{name} must be a canonical token")
    return value


def _is_token(value: object) -> bool:
    """Return whether a value is safe to place in a blocked decision identity."""

    try:
        _token(value, "token")
    except CloseSnapshotSimulationValidationError:
        return False
    return True


def _digest(value: object, name: str) -> str:
    """Require a bare lowercase SHA-256 digest."""

    if type(value) is not str or _SHA256_RE.fullmatch(value) is None:
        raise CloseSnapshotSimulationValidationError(f"{name} must be SHA-256")
    return value


def _safe_digest(value: object) -> str | None:
    """Retain a digest only when the untrusted input is already canonical."""

    try:
        return _digest(value, "digest")
    except CloseSnapshotSimulationValidationError:
        return None


def _aware(value: object, name: str) -> datetime:
    """Require an exact timezone-aware datetime."""

    if type(value) is not datetime or value.tzinfo is None or value.utcoffset() is None:
        raise CloseSnapshotSimulationValidationError(f"{name} must be timezone-aware")
    return value


def _is_positive_int(value: object) -> bool:
    """Return whether a value is a bounded positive integer identity."""

    return type(value) is int and 0 < value.bit_length() <= 63


def _positive_decimal(value: object, name: str) -> Decimal:
    """Require one exact finite positive Decimal with bounded shape."""

    if type(value) is not Decimal or not value.is_finite() or value <= 0:
        raise CloseSnapshotSimulationValidationError(f"{name} must be a positive Decimal")
    parts = value.as_tuple()
    if len(parts.digits) > _MAX_DECIMAL_DIGITS or type(parts.exponent) is not int:
        raise CloseSnapshotSimulationValidationError(f"{name} exceeds decimal bounds")
    if abs(parts.exponent) > _MAX_DECIMAL_EXPONENT:
        raise CloseSnapshotSimulationValidationError(f"{name} exceeds decimal bounds")
    return value


def _decimal_text(value: Decimal | None) -> str | None:
    """Render an optional exact decimal without exponent notation."""

    if value is None:
        return None
    _positive_decimal(value, "decimal payload")
    return format(value, "f")


def _parse_decimal_or_none(value: object) -> Decimal | None:
    """Parse an optional canonical positive Decimal string."""

    if value is None:
        return None
    if type(value) is not str:
        raise CloseSnapshotSimulationValidationError("decimal payload must be canonical text")
    try:
        parsed = Decimal(value)
    except ArithmeticError as error:
        raise CloseSnapshotSimulationValidationError("decimal payload is invalid") from error
    _positive_decimal(parsed, "decimal payload")
    if _decimal_text(parsed) != value:
        raise CloseSnapshotSimulationValidationError("decimal payload is not canonical")
    return parsed


def _utc_text(value: datetime) -> str:
    """Render an aware time as canonical UTC with a literal Z suffix."""

    return (
        _aware(value, "datetime")
        .astimezone(UTC)
        .isoformat(timespec="microseconds")
        .replace("+00:00", "Z")
    )


def _parse_utc(value: object) -> datetime:
    """Parse one canonical UTC string and reject offsets or precision drift."""

    if type(value) is not str or not value.endswith("Z"):
        raise CloseSnapshotSimulationValidationError("timestamp must be canonical UTC")
    try:
        parsed = datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError as error:
        raise CloseSnapshotSimulationValidationError("timestamp is invalid") from error
    if _utc_text(parsed) != value:
        raise CloseSnapshotSimulationValidationError("timestamp is not canonical")
    return parsed


def _parse_date(value: object) -> date:
    """Parse one canonical ISO calendar date."""

    if type(value) is not str:
        raise CloseSnapshotSimulationValidationError("trading date must be text")
    try:
        parsed = date.fromisoformat(value)
    except ValueError as error:
        raise CloseSnapshotSimulationValidationError("trading date is invalid") from error
    if parsed.isoformat() != value:
        raise CloseSnapshotSimulationValidationError("trading date is not canonical")
    return parsed


def _string(value: object, name: str) -> str:
    """Narrow one JSON string field before construction."""

    if type(value) is not str:
        raise CloseSnapshotSimulationValidationError(f"{name} must be text")
    return value


def _optional_string(value: object, name: str) -> str | None:
    """Narrow one nullable JSON string field."""

    if value is None:
        return None
    return _string(value, name)


def _integer(value: object, name: str) -> int:
    """Narrow one exact JSON integer field."""

    if type(value) is not int:
        raise CloseSnapshotSimulationValidationError(f"{name} must be an integer")
    return value


def _enum_value(enum_type: type[PriceBoundaryMode], value: object) -> PriceBoundaryMode:
    """Parse a recognized price-boundary enum token."""

    if type(value) is not str:
        raise CloseSnapshotSimulationValidationError("price boundary mode must be text")
    try:
        return enum_type(value)
    except ValueError as error:
        raise CloseSnapshotSimulationValidationError("price boundary mode is unknown") from error


def _deduplicate(reasons: list[CloseSnapshotSimulationReason]) -> None:
    """Preserve stable reason order while removing repeated blockers."""

    unique = tuple(dict.fromkeys(reasons))
    reasons.clear()
    reasons.extend(unique)


_POLICY_KEYS = frozenset(
    {
        "schema",
        "purpose",
        "policy_id",
        "policy_version",
        "account_id",
        "security_id",
        "asset_code",
        "market",
        "board",
        "trading_date",
        "source_id",
        "source_name",
        "usage_ttl_seconds",
        "status_mapping_sha256",
        "trusted_vendor_status_codes",
        "available_from",
        "available_until",
        "price_rule",
        "price_rule_source_hash",
        "price_boundary_mode",
        "lower_boundary_factor",
        "upper_boundary_factor",
        "boundary_rule_source_id",
        "boundary_rule_version",
        "boundary_rule_source_hash",
        "unrestricted_reason_code",
        "content_hash",
    }
)
