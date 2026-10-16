"""Version-two composition of execution constraints and submission price cages."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import assert_never

from apps.risk_center.domain.execution_trading_constraints import (
    AShareExecutionRule,
    ExecutionContractValidationError,
    ExecutionDecisionStatus,
    ExecutionDenyCode,
    ExecutionMarketEvidence,
    ExecutionOrder,
    ExecutionSide,
    ExecutionTradingDecision,
    PriceBoundaryMode,
    evaluate_execution_order,
)
from apps.risk_center.domain.price_submission_range import (
    PriceSubmissionRangeDecision,
    PriceSubmissionRangeReason,
    PriceSubmissionRangeRule,
    PriceSubmissionRangeStatus,
    PriceSubmissionStage,
    QuoteValue,
    calculate_price_submission_range,
)


class ExecutionSubmissionV2ValidationError(ExecutionContractValidationError):
    """Raised when a version-two execution submission contract is malformed."""


class SubmissionV2DenyCode(StrEnum):
    """Stable version-two reasons that extend the version-one deny vocabulary."""

    SUBMISSION_STAGE_NOT_ALLOWED = "SUBMISSION_STAGE_NOT_ALLOWED"
    PRICE_CAGE_INVALID_RULE = "PRICE_CAGE_INVALID_RULE"
    PRICE_CAGE_INVALID_QUOTE = "PRICE_CAGE_INVALID_QUOTE"
    SUBMISSION_REFERENCE_QUOTE_UNKNOWN = "SUBMISSION_REFERENCE_QUOTE_UNKNOWN"
    SUBMISSION_REFERENCE_QUOTE_MISSING = "SUBMISSION_REFERENCE_QUOTE_MISSING"
    SUBMISSION_REFERENCE_PRICE_NOT_ON_TICK = "SUBMISSION_REFERENCE_PRICE_NOT_ON_TICK"
    SUBMISSION_REFERENCE_PRICE_OUTSIDE_BOUNDARY = "SUBMISSION_REFERENCE_PRICE_OUTSIDE_BOUNDARY"
    PRICE_CAGE_BOUNDARY_INVALID = "PRICE_CAGE_BOUNDARY_INVALID"
    LIMIT_PRICE_OUTSIDE_SUBMISSION_RANGE = "LIMIT_PRICE_OUTSIDE_SUBMISSION_RANGE"


def _canonical_hash(payload: dict[str, object]) -> str:
    """Return the SHA-256 digest of a canonical JSON payload."""

    try:
        encoded = json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError) as error:
        raise ExecutionSubmissionV2ValidationError(
            "version-two content is not canonical JSON"
        ) from error
    return hashlib.sha256(encoded).hexdigest()


def _seal_content_hash(payload: dict[str, object], supplied: object) -> str:
    """Validate a supplied outer hash or compute it when no hash was supplied."""

    if type(supplied) is not str:
        raise ExecutionSubmissionV2ValidationError("content_hash must be a string")
    expected = _canonical_hash(payload)
    if supplied and supplied != expected:
        raise ExecutionSubmissionV2ValidationError("content_hash does not match payload")
    return expected


@dataclass(frozen=True, slots=True)
class ExecutionSubmissionRuleV2:
    """Combine immutable v1 execution terms with explicit price-cage stages."""

    execution_rule_v1: AShareExecutionRule
    price_submission_range: PriceSubmissionRangeRule
    allowed_stages: tuple[PriceSubmissionStage, ...]
    content_hash: str = ""

    def __post_init__(self) -> None:
        """Validate the composition, stage allowlist, and outer content hash."""

        if type(self.execution_rule_v1) is not AShareExecutionRule:
            raise ExecutionSubmissionV2ValidationError(
                "execution_rule_v1 must be AShareExecutionRule"
            )
        if type(self.price_submission_range) is not PriceSubmissionRangeRule:
            raise ExecutionSubmissionV2ValidationError(
                "price_submission_range must be PriceSubmissionRangeRule"
            )
        try:
            self.execution_rule_v1.__post_init__()
            self.price_submission_range.__post_init__()
        except ExecutionContractValidationError:
            raise
        except (ArithmeticError, TypeError, ValueError) as error:
            raise ExecutionSubmissionV2ValidationError(
                "execution rule failed contract revalidation"
            ) from error
        if (
            self.execution_rule_v1.market != self.price_submission_range.market
            or self.execution_rule_v1.board != self.price_submission_range.board
            or self.execution_rule_v1.price_tick != self.price_submission_range.price_tick
        ):
            raise ExecutionSubmissionV2ValidationError(
                "v1 and price-cage market, board, and price_tick must match exactly"
            )
        if type(self.allowed_stages) is not tuple:
            raise ExecutionSubmissionV2ValidationError("allowed_stages must be an explicit tuple")
        if any(type(stage) is not PriceSubmissionStage for stage in self.allowed_stages):
            raise ExecutionSubmissionV2ValidationError(
                "allowed_stages contains an unknown stage value"
            )
        if len(set(self.allowed_stages)) != len(self.allowed_stages):
            raise ExecutionSubmissionV2ValidationError("allowed_stages must not contain duplicates")
        if any(stage is not PriceSubmissionStage.CONTINUOUS for stage in self.allowed_stages):
            raise ExecutionSubmissionV2ValidationError(
                "only CONTINUOUS may be enabled by version two"
            )
        object.__setattr__(
            self,
            "content_hash",
            _seal_content_hash(self._content_payload(), self.content_hash),
        )

    def _content_payload(self) -> dict[str, object]:
        return {
            "execution_rule_v1": self.execution_rule_v1.to_payload(),
            "price_submission_range": self.price_submission_range.to_payload(),
            "allowed_stages": [stage.value for stage in self.allowed_stages],
        }

    def to_payload(self) -> dict[str, object]:
        """Return all v2 rule fields, nested v1 hashes, and the outer hash."""

        self.__post_init__()
        return {**self._content_payload(), "content_hash": self.content_hash}


@dataclass(frozen=True, slots=True)
class ExecutionSubmissionMarketV2:
    """Bind v1 market evidence, one phase, and its four quote observations."""

    market_evidence_v1: ExecutionMarketEvidence
    stage: PriceSubmissionStage
    ask: QuoteValue
    bid: QuoteValue
    latest: QuoteValue
    previous_close: QuoteValue
    content_hash: str = ""

    def __post_init__(self) -> None:
        """Validate market evidence and quote values before sealing the payload."""

        if type(self.market_evidence_v1) is not ExecutionMarketEvidence:
            raise ExecutionSubmissionV2ValidationError(
                "market_evidence_v1 must be ExecutionMarketEvidence"
            )
        if type(self.stage) is not PriceSubmissionStage:
            raise ExecutionSubmissionV2ValidationError(
                "stage must be a recognized PriceSubmissionStage"
            )
        quote_values = (self.ask, self.bid, self.latest, self.previous_close)
        if any(type(quote) is not QuoteValue for quote in quote_values):
            raise ExecutionSubmissionV2ValidationError(
                "all quote fields must be QuoteValue instances"
            )
        try:
            self.market_evidence_v1.__post_init__()
            for quote in quote_values:
                quote.__post_init__()
        except ExecutionContractValidationError:
            raise
        except (ArithmeticError, TypeError, ValueError) as error:
            raise ExecutionSubmissionV2ValidationError(
                "market evidence failed contract revalidation"
            ) from error
        object.__setattr__(
            self,
            "content_hash",
            _seal_content_hash(self._content_payload(), self.content_hash),
        )

    def _content_payload(self) -> dict[str, object]:
        return {
            "market_evidence_v1": self.market_evidence_v1.to_payload(),
            "stage": self.stage.value,
            "ask": self.ask.to_payload(),
            "bid": self.bid.to_payload(),
            "latest": self.latest.to_payload(),
            "previous_close": self.previous_close.to_payload(),
        }

    def to_payload(self) -> dict[str, object]:
        """Return all v2 market fields and the source-bound outer hash."""

        self.__post_init__()
        return {**self._content_payload(), "content_hash": self.content_hash}


@dataclass(frozen=True, slots=True)
class ExecutionSubmissionDecisionV2:
    """Version-two result bound to outer rule and quote-evidence hashes."""

    status: ExecutionDecisionStatus
    reason_codes: tuple[ExecutionDenyCode | SubmissionV2DenyCode, ...]
    order_id: str
    rule_content_hash: str
    market_evidence_content_hash: str
    evaluated_at: datetime

    def __post_init__(self) -> None:
        """Validate decision status, reason vocabulary, and bound hashes."""

        if type(self.status) is not ExecutionDecisionStatus:
            raise ExecutionSubmissionV2ValidationError("status must be ExecutionDecisionStatus")
        if type(self.reason_codes) is not tuple or any(
            type(reason) not in (ExecutionDenyCode, SubmissionV2DenyCode)
            for reason in self.reason_codes
        ):
            raise ExecutionSubmissionV2ValidationError(
                "reason_codes must be an exact tuple of recognized deny codes"
            )
        if len(set(self.reason_codes)) != len(self.reason_codes):
            raise ExecutionSubmissionV2ValidationError("reason_codes must not contain duplicates")
        if self.status is ExecutionDecisionStatus.ALLOWED and self.reason_codes:
            raise ExecutionSubmissionV2ValidationError(
                "ALLOWED decision cannot contain deny reasons"
            )
        if self.status is ExecutionDecisionStatus.DENIED and not self.reason_codes:
            raise ExecutionSubmissionV2ValidationError(
                "DENIED decision requires at least one reason"
            )
        if (
            type(self.order_id) is not str
            or not self.order_id
            or self.order_id.strip() != self.order_id
            or len(self.order_id) > 192
            or any(character.isspace() for character in self.order_id)
        ):
            raise ExecutionSubmissionV2ValidationError("order_id must be a bounded canonical token")
        digests: tuple[tuple[str, str], ...] = (
            ("rule_content_hash", self.rule_content_hash),
            ("market_evidence_content_hash", self.market_evidence_content_hash),
        )
        for field_name, digest in digests:
            if type(digest) is not str or len(digest) != 64:
                raise ExecutionSubmissionV2ValidationError(f"{field_name} must be a SHA-256 digest")
            if any(character not in "0123456789abcdef" for character in digest):
                raise ExecutionSubmissionV2ValidationError(
                    f"{field_name} must be a lowercase SHA-256 digest"
                )
        _require_aware_datetime(self.evaluated_at, "evaluated_at")

    def to_payload(self) -> dict[str, object]:
        """Return the compatible five-key decision envelope with v2 hashes."""

        self.__post_init__()
        return {
            "status": self.status.value,
            "reason_codes": [reason.value for reason in self.reason_codes],
            "order_id": self.order_id,
            "rule_content_hash": self.rule_content_hash,
            "market_evidence_content_hash": self.market_evidence_content_hash,
        }


def _require_aware_datetime(value: object, field_name: str) -> None:
    if type(value) is not datetime or value.tzinfo is None or value.utcoffset() is None:
        raise ExecutionSubmissionV2ValidationError(
            f"{field_name} must be a timezone-aware datetime"
        )


def _submission_reason_for_cage(
    reason: PriceSubmissionRangeReason,
) -> SubmissionV2DenyCode:
    if reason is PriceSubmissionRangeReason.PRICE_CAGE_NOT_APPLICABLE:
        return SubmissionV2DenyCode.SUBMISSION_STAGE_NOT_ALLOWED
    if reason is PriceSubmissionRangeReason.STAGE_UNKNOWN:
        return SubmissionV2DenyCode.SUBMISSION_STAGE_NOT_ALLOWED
    if reason is PriceSubmissionRangeReason.INVALID_RULE:
        return SubmissionV2DenyCode.PRICE_CAGE_INVALID_RULE
    if reason is PriceSubmissionRangeReason.INVALID_QUOTE:
        return SubmissionV2DenyCode.PRICE_CAGE_INVALID_QUOTE
    if reason is PriceSubmissionRangeReason.REFERENCE_QUOTE_UNKNOWN:
        return SubmissionV2DenyCode.SUBMISSION_REFERENCE_QUOTE_UNKNOWN
    if reason is PriceSubmissionRangeReason.NO_REFERENCE_QUOTE:
        return SubmissionV2DenyCode.SUBMISSION_REFERENCE_QUOTE_MISSING
    if reason is PriceSubmissionRangeReason.REFERENCE_PRICE_NOT_ON_TICK:
        return SubmissionV2DenyCode.SUBMISSION_REFERENCE_PRICE_NOT_ON_TICK
    if reason is PriceSubmissionRangeReason.CALCULATED_BOUNDARY_OUT_OF_RANGE:
        return SubmissionV2DenyCode.PRICE_CAGE_BOUNDARY_INVALID
    assert_never(reason)


def _cage_reasons(
    result: PriceSubmissionRangeDecision,
) -> tuple[SubmissionV2DenyCode, ...]:
    if result.status is PriceSubmissionRangeStatus.CALCULATED:
        if result.boundary_price is None:
            raise ExecutionSubmissionV2ValidationError("calculated price cage has no boundary")
        return ()
    if result.reason_code is None:
        raise ExecutionSubmissionV2ValidationError(
            "denied or inapplicable price cage has no reason"
        )
    return (_submission_reason_for_cage(result.reason_code),)


def evaluate_execution_submission(
    rule: ExecutionSubmissionRuleV2,
    market: ExecutionSubmissionMarketV2,
    order: ExecutionOrder,
    as_of: datetime,
) -> ExecutionSubmissionDecisionV2:
    """Evaluate v1 execution terms and the v2 continuous price cage together.

    The four quote values use the source identity and freshness window carried by
    ``market_evidence_v1``. This domain function does not assert provider trust.
    """

    if type(rule) is not ExecutionSubmissionRuleV2:
        raise ExecutionSubmissionV2ValidationError("rule must be ExecutionSubmissionRuleV2")
    if type(market) is not ExecutionSubmissionMarketV2:
        raise ExecutionSubmissionV2ValidationError("market must be ExecutionSubmissionMarketV2")
    if type(order) is not ExecutionOrder:
        raise ExecutionSubmissionV2ValidationError("order must be ExecutionOrder")
    _require_aware_datetime(as_of, "as_of")
    try:
        rule.__post_init__()
        market.__post_init__()
        order.__post_init__()
    except ExecutionContractValidationError:
        raise
    except (AttributeError, ArithmeticError, TypeError, ValueError) as error:
        raise ExecutionSubmissionV2ValidationError(
            "version-two evaluation input failed revalidation"
        ) from error

    base_decision: ExecutionTradingDecision = evaluate_execution_order(
        rule.execution_rule_v1,
        market.market_evidence_v1,
        order,
        as_of,
    )
    reasons: list[ExecutionDenyCode | SubmissionV2DenyCode] = list(base_decision.reason_codes)

    if (
        market.stage is not PriceSubmissionStage.CONTINUOUS
        or market.stage not in rule.allowed_stages
    ):
        reasons.append(SubmissionV2DenyCode.SUBMISSION_STAGE_NOT_ALLOWED)

    cage = calculate_price_submission_range(
        rule.price_submission_range,
        side=order.side,
        stage=market.stage,
        ask=market.ask,
        bid=market.bid,
        latest=market.latest,
        previous_close=market.previous_close,
    )
    reasons.extend(_cage_reasons(cage))
    if cage.status is PriceSubmissionRangeStatus.CALCULATED:
        boundary = cage.boundary_price
        if boundary is None:
            raise ExecutionSubmissionV2ValidationError("calculated price cage has no boundary")
        cage_reference = cage.reference_price
        if cage_reference is None:
            raise ExecutionSubmissionV2ValidationError(
                "calculated price cage has no selected reference"
            )
        base_market = market.market_evidence_v1
        if base_market.price_boundary_mode is PriceBoundaryMode.LIMITED:
            lower_limit = base_market.lower_limit_price
            upper_limit = base_market.upper_limit_price
            if lower_limit is None or upper_limit is None:
                raise ExecutionSubmissionV2ValidationError(
                    "LIMITED market evidence has no daily boundary"
                )
            if not lower_limit <= cage_reference <= upper_limit:
                reasons.append(SubmissionV2DenyCode.SUBMISSION_REFERENCE_PRICE_OUTSIDE_BOUNDARY)
        outside_range = (
            order.limit_price > boundary
            if order.side is ExecutionSide.BUY
            else order.limit_price < boundary
        )
        if outside_range:
            reasons.append(SubmissionV2DenyCode.LIMIT_PRICE_OUTSIDE_SUBMISSION_RANGE)

    stable_reasons = tuple(dict.fromkeys(reasons))
    status = ExecutionDecisionStatus.DENIED if stable_reasons else ExecutionDecisionStatus.ALLOWED
    return ExecutionSubmissionDecisionV2(
        status=status,
        reason_codes=stable_reasons,
        order_id=order.order_id,
        rule_content_hash=rule.content_hash,
        market_evidence_content_hash=market.content_hash,
        evaluated_at=as_of,
    )


__all__: tuple[str, ...] = (
    "ExecutionSubmissionDecisionV2",
    "ExecutionSubmissionMarketV2",
    "ExecutionSubmissionRuleV2",
    "ExecutionSubmissionV2ValidationError",
    "SubmissionV2DenyCode",
    "evaluate_execution_submission",
)
