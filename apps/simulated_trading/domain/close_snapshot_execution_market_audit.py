"""Integrity receipt for one close-snapshot-qualified simulated execution."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal
from typing import TypedDict, cast

from apps.data_center.domain.sina_quote_capture import (
    SINA_VENDOR_STATUS_MAPPING_SHA256 as SINA_VENDOR_STATUS_MAPPING_SHA256,
)
from apps.data_center.domain.sina_quote_capture import SinaQuoteCapture as SinaQuoteCapture
from apps.data_center.domain.sina_quote_capture import SinaQuoteClockStatus as SinaQuoteClockStatus
from apps.data_center.domain.sina_quote_capture import (
    SinaReportedTradingState as SinaReportedTradingState,
)

from .close_snapshot_execution_market_audit_validation import _AUDIT_KEYS as _AUDIT_KEYS
from .close_snapshot_execution_market_audit_validation import _AUDIT_SCHEMA as _AUDIT_SCHEMA
from .close_snapshot_execution_market_audit_validation import (
    _AUDIT_TEXT_FIELDS as _AUDIT_TEXT_FIELDS,
)
from .close_snapshot_execution_market_audit_validation import _BUNDLE_KEYS as _BUNDLE_KEYS
from .close_snapshot_execution_market_audit_validation import _CALENDAR_KEYS as _CALENDAR_KEYS
from .close_snapshot_execution_market_audit_validation import _CAPTURE_KEYS as _CAPTURE_KEYS
from .close_snapshot_execution_market_audit_validation import (
    _CLOSE_DECISION_KEYS as _CLOSE_DECISION_KEYS,
)
from .close_snapshot_execution_market_audit_validation import (
    _CLOSE_MARKET_KEYS as _CLOSE_MARKET_KEYS,
)
from .close_snapshot_execution_market_audit_validation import _EVIDENCE_SCHEMA as _EVIDENCE_SCHEMA
from .close_snapshot_execution_market_audit_validation import (
    _EXECUTION_MARKET_KEYS as _EXECUTION_MARKET_KEYS,
)
from .close_snapshot_execution_market_audit_validation import (
    _MARKET_AVAILABLE_AT_BASIS as _MARKET_AVAILABLE_AT_BASIS,
)
from .close_snapshot_execution_market_audit_validation import (
    _MARKET_PRICE_KIND as _MARKET_PRICE_KIND,
)
from .close_snapshot_execution_market_audit_validation import (
    _PAPER_BOUNDARY_BASIS as _PAPER_BOUNDARY_BASIS,
)
from .close_snapshot_execution_market_audit_validation import _POLICY_KEYS as _POLICY_KEYS
from .close_snapshot_execution_market_audit_validation import _PRICE_RULE as _PRICE_RULE
from .close_snapshot_execution_market_audit_validation import _PURPOSE as _PURPOSE
from .close_snapshot_execution_market_audit_validation import (
    _SECURITY_STATE_BASIS as _SECURITY_STATE_BASIS,
)
from .close_snapshot_execution_market_audit_validation import _SHA256_LENGTH as _SHA256_LENGTH
from .close_snapshot_execution_market_audit_validation import _SHANGHAI as _SHANGHAI
from .close_snapshot_execution_market_audit_validation import _SOURCE_SCHEMA as _SOURCE_SCHEMA
from .close_snapshot_execution_market_audit_validation import (
    _canonical_json_text as _canonical_json_text,
)
from .close_snapshot_execution_market_audit_validation import _decimal_value as _decimal_value
from .close_snapshot_execution_market_audit_validation import _digest as _digest
from .close_snapshot_execution_market_audit_validation import _exact_object as _exact_object
from .close_snapshot_execution_market_audit_validation import _json_hash as _json_hash
from .close_snapshot_execution_market_audit_validation import (
    _nonnegative_decimal_text as _nonnegative_decimal_text,
)
from .close_snapshot_execution_market_audit_validation import _object as _object
from .close_snapshot_execution_market_audit_validation import _parse_date as _parse_date
from .close_snapshot_execution_market_audit_validation import (
    _parse_iso_datetime as _parse_iso_datetime,
)
from .close_snapshot_execution_market_audit_validation import (
    _parse_json_object as _parse_json_object,
)
from .close_snapshot_execution_market_audit_validation import _parse_utc as _parse_utc
from .close_snapshot_execution_market_audit_validation import (
    _positive_database_id as _positive_database_id,
)
from .close_snapshot_execution_market_audit_validation import (
    _positive_decimal_text as _positive_decimal_text,
)
from .close_snapshot_execution_market_audit_validation import _positive_price as _positive_price
from .close_snapshot_execution_market_audit_validation import _quote_value as _quote_value
from .close_snapshot_execution_market_audit_validation import _string as _string
from .close_snapshot_execution_market_audit_validation import _token as _token
from .close_snapshot_execution_market_audit_validation import _utc_datetime as _utc_datetime
from .close_snapshot_execution_market_audit_validation import _utc_text as _utc_text
from .close_snapshot_execution_market_audit_validation import (
    _validate_calendar as _validate_calendar,
)
from .close_snapshot_execution_market_audit_validation import _validate_capture as _validate_capture
from .close_snapshot_execution_market_audit_validation import (
    _validate_close_decision as _validate_close_decision,
)
from .close_snapshot_execution_market_audit_validation import (
    _validate_close_market as _validate_close_market,
)
from .close_snapshot_execution_market_audit_validation import (
    _validate_locked_position as _validate_locked_position,
)
from .close_snapshot_execution_market_audit_validation import (
    _validate_market_bundle as _validate_market_bundle,
)
from .close_snapshot_execution_market_audit_validation import _validate_policy as _validate_policy
from .close_snapshot_execution_market_audit_validation import (
    _validate_runtime_identity as _validate_runtime_identity,
)
from .close_snapshot_execution_market_audit_validation import (
    _verify_nested_hashes as _verify_nested_hashes,
)
from .close_snapshot_execution_market_audit_validation import (
    _verify_object_hash as _verify_object_hash,
)
from .execution_settlement_plan_binding import (
    SettlementPlanBindingValidationError,
    _canonical_hash,
)


class CloseSnapshotExecutionMarketAuditPayload(TypedDict):
    """Exact wire fields for the independent close-snapshot audit variant."""

    schema: str
    purpose: str
    account_id: int
    user_id: int
    idempotency_key: str
    request_payload_hash: str
    security_id: str
    asset_code: str
    side: str
    execution_price: str
    source_id: str
    source_version: str
    source_hash: str
    source_observed_at: str
    source_available_at: str
    source_valid_until: str
    policy_id: str
    policy_version: str
    policy_hash: str
    market_hash: str
    market_bundle_hash: str
    rule_hash: str
    calendar_hash: str
    close_qualification_hash: str
    close_evaluated_at: str
    evidence: dict[str, object]
    evidence_hash: str
    content_hash: str


class CloseSnapshotAuditEvidencePayload(TypedDict):
    """Exact retained evidence body for one close-purpose simulation decision."""

    schema: str
    purpose: str
    retained_source: dict[str, object]
    market_bundle: dict[str, object]
    close_qualification: dict[str, object]
    close_evaluated_at: str
    locked_position: dict[str, object]
    qualification: dict[str, object]


@dataclass(frozen=True, slots=True)
class CloseSnapshotExecutionMarketAuditV1:
    """Bind retained close source evidence to one exact paper stop-loss SELL.

    The receipt distinguishes vendor observation time from local response
    completion and records an explicitly qualified close-snapshot simulation.
    It never claims a continuous or fresh market, an official exchange close,
    a Risk V2 ALLOWED result, or live execution authority.
    """

    account_id: int
    user_id: int
    idempotency_key: str
    request_payload_hash: str
    security_id: str
    asset_code: str
    execution_price: Decimal
    source_id: str
    source_version: str
    source_hash: str
    source_observed_at: datetime
    source_available_at: datetime
    source_valid_until: datetime
    policy_id: str
    policy_version: str
    policy_hash: str
    market_hash: str
    market_bundle_hash: str
    rule_hash: str
    calendar_hash: str
    close_qualification_hash: str
    close_evaluated_at: datetime
    evidence_json: str
    evidence_hash: str = ""
    content_hash: str = ""

    def __post_init__(self) -> None:
        """Validate purpose, exact source-to-market bindings, and nested hashes."""

        _positive_database_id(self.account_id, "account_id")
        _positive_database_id(self.user_id, "user_id")
        for name in ("idempotency_key", "security_id", "asset_code", "source_id", "source_version"):
            _token(getattr(self, name), name)
        for name in (
            "request_payload_hash",
            "source_hash",
            "policy_hash",
            "market_hash",
            "market_bundle_hash",
            "rule_hash",
            "calendar_hash",
            "close_qualification_hash",
        ):
            _digest(getattr(self, name), name)
        _positive_price(self.execution_price, "execution_price")
        observed = _utc_datetime(self.source_observed_at, "source_observed_at")
        available = _utc_datetime(self.source_available_at, "source_available_at")
        valid_until = _utc_datetime(self.source_valid_until, "source_valid_until")
        evaluated_at = _utc_datetime(self.close_evaluated_at, "close_evaluated_at")
        if not observed <= available <= evaluated_at < valid_until:
            raise SettlementPlanBindingValidationError(
                "close market audit source window is invalid"
            )
        if type(self.evidence_json) is not str:
            raise SettlementPlanBindingValidationError("close market audit evidence is invalid")
        evidence = _parse_json_object(self.evidence_json, "close market audit evidence")
        if _canonical_json_text(evidence) != self.evidence_json:
            raise SettlementPlanBindingValidationError(
                "close market audit evidence is not canonical"
            )
        self._validate_evidence(evidence)
        calculated_evidence_hash = _json_hash(evidence)
        if self.evidence_hash and self.evidence_hash != calculated_evidence_hash:
            raise SettlementPlanBindingValidationError("close market audit evidence hash differs")
        object.__setattr__(self, "evidence_hash", calculated_evidence_hash)
        expected_content_hash = _canonical_hash(self._content_payload())
        if self.content_hash and self.content_hash != expected_content_hash:
            raise SettlementPlanBindingValidationError("close market audit content hash differs")
        object.__setattr__(self, "content_hash", expected_content_hash)

    def _validate_evidence(self, evidence: dict[str, object]) -> None:
        """Verify capture, policy, calendar, market, and decision hash chains."""

        expected_keys = frozenset(
            {
                "schema",
                "purpose",
                "retained_source",
                "market_bundle",
                "close_qualification",
                "close_evaluated_at",
                "locked_position",
                "qualification",
            }
        )
        if frozenset(evidence) != expected_keys:
            raise SettlementPlanBindingValidationError(
                "close market audit evidence shape is invalid"
            )
        if evidence.get("schema") != _EVIDENCE_SCHEMA or evidence.get("purpose") != _PURPOSE:
            raise SettlementPlanBindingValidationError("close market audit purpose is invalid")
        retained_source = _object(evidence.get("retained_source"), "retained source")
        market_bundle = _object(evidence.get("market_bundle"), "market bundle")
        close_decision = _object(evidence.get("close_qualification"), "close qualification")
        locked_position = _object(evidence.get("locked_position"), "locked position")
        qualification = _object(evidence.get("qualification"), "qualification")
        qualification_keys = frozenset(
            {
                "purpose",
                "decision_scope",
                "local_simulation_qualified",
                "freshness",
                "reliability",
                "must_not_use_for_decision",
                "must_not_execute",
                "execution_authority",
                "global_identity_restrictions",
                "local_market_permission",
                "market_available_at_basis",
            }
        )
        if frozenset(qualification) != qualification_keys:
            raise SettlementPlanBindingValidationError("close qualification fields are invalid")

        source_fields = frozenset(
            {"purpose", "account_id", "capture", "security_id", "policy_hash", "runtime"}
        )
        if frozenset(retained_source) != source_fields:
            raise SettlementPlanBindingValidationError("close retained source fields are invalid")
        if (
            retained_source.get("purpose") != _PURPOSE
            or retained_source.get("account_id") != self.account_id
            or retained_source.get("security_id") != self.security_id
            or retained_source.get("policy_hash") != self.policy_hash
        ):
            raise SettlementPlanBindingValidationError("close retained source scope differs")
        runtime = _object(retained_source.get("runtime"), "retained policy runtime")
        _validate_runtime_identity(runtime)
        capture = _object(retained_source.get("capture"), "retained Sina capture")

        bundle_capture, policy, calendar, market, bundle_rule_hash = _validate_market_bundle(
            market_bundle
        )
        if capture != bundle_capture.to_payload():
            raise SettlementPlanBindingValidationError(
                "close retained capture differs from the market bundle capture"
            )
        if _string(evidence.get("close_evaluated_at"), "close_evaluated_at") != _utc_text(
            self.close_evaluated_at
        ):
            raise SettlementPlanBindingValidationError("close evaluation clock differs")
        _validate_close_decision(close_decision)
        qualification_payload = qualification

        policy_date = _parse_date(policy.get("trading_date"), "policy trading_date")
        market_evidence = _object(market.get("market_evidence_v1"), "market evidence")
        source_quote = bundle_capture.quote
        if source_quote is None:
            raise SettlementPlanBindingValidationError("close capture has no parsed quote")
        capture_available_at = bundle_capture.response_completed_at
        capture_sha = bundle_capture.body_sha256
        _digest(market_evidence.get("market_source_hash"), "market source hash")
        market_observed = _parse_utc(
            market_evidence.get("market_observed_at"), "market observation"
        )
        market_available = _parse_utc(
            market_evidence.get("market_available_at"), "market availability"
        )
        market_valid_until = _parse_utc(
            market_evidence.get("market_valid_until"), "market validity"
        )
        if (
            capture.get("asset_code") != self.asset_code
            or capture_sha != self.source_hash
            or capture_available_at != self.source_available_at
            or market_observed != self.source_observed_at
            or market_available != self.source_available_at
            or market_valid_until != self.source_valid_until
        ):
            raise SettlementPlanBindingValidationError(
                "close declared source clocks or hash differ from retained capture/market"
            )
        if (
            policy.get("policy_id") != self.policy_id
            or policy.get("policy_version") != self.policy_version
            or policy.get("content_hash") != self.policy_hash
            or policy.get("account_id") != self.account_id
            or policy.get("security_id") != self.security_id
            or policy.get("asset_code") != self.asset_code
            or _parse_date(policy.get("trading_date"), "policy trading_date") != policy_date
        ):
            raise SettlementPlanBindingValidationError("close policy does not match audit scope")
        _digest(market_evidence.get("market_source_hash"), "market source hash")
        if (
            market_evidence.get("security_id") != self.security_id
            or market_evidence.get("market_source_id") != self.source_id
            or market_evidence.get("market_source_version") != self.source_version
            or market_evidence.get("calendar_source_hash") != calendar.get("calendar_source_hash")
            or market_evidence.get("calendar_version") != calendar.get("calendar_version")
            or market_evidence.get("calendar_id") != calendar.get("calendar_id")
            or market_evidence.get("trading_date") != policy_date.isoformat()
            or market_evidence.get("session_state") != "CLOSED"
            or calendar.get("session_state") != "CLOSED"
            or market_evidence.get("security_state") != "TRADING"
            or source_quote.reported_trading_state is not SinaReportedTradingState.TRADING
            or source_quote.source_clock_status is not SinaQuoteClockStatus.VALID
            or source_quote.vendor_status_code
            not in cast(list[str], policy["trusted_vendor_status_codes"])
            or source_quote.source_observed_at != market_observed
        ):
            raise SettlementPlanBindingValidationError(
                "close market identity or closed-session state differs from source"
            )
        if (
            policy.get("purpose") != _PURPOSE
            or policy.get("price_rule") != _PRICE_RULE
            or market_bundle.get("purpose") != _PURPOSE
            or market_bundle.get("market_available_at_basis") != _MARKET_AVAILABLE_AT_BASIS
            or market.get("price_observation_kind") != _MARKET_PRICE_KIND
            or market.get("price_boundary_basis") != _PAPER_BOUNDARY_BASIS
            or market.get("security_state_basis") != _SECURITY_STATE_BASIS
        ):
            raise SettlementPlanBindingValidationError("close market purpose or basis differs")
        if (
            self.source_id != "sina_public_quote"
            or capture.get("schema") != _SOURCE_SCHEMA
            or capture.get("parse_issue") is not None
            or type(capture.get("http_status")) is not int
            or not 200 <= cast(int, capture.get("http_status")) < 300
        ):
            raise SettlementPlanBindingValidationError("close source capture is unusable")
        source_date = market_observed.astimezone(_SHANGHAI).date()
        session_close = _parse_utc(market_evidence.get("session_close_at"), "session close")
        if (
            source_date != policy_date
            or market_observed < session_close
            or market_observed > capture_available_at
            or self.close_evaluated_at < capture_available_at
            or self.close_evaluated_at >= market_valid_until
        ):
            raise SettlementPlanBindingValidationError(
                "close quote source clock is not qualified for its actual session"
            )
        usage_ttl = policy.get("usage_ttl_seconds")
        policy_available_until = _parse_utc(policy.get("available_until"), "policy cutoff")
        calendar_valid_until = _parse_utc(calendar.get("calendar_valid_until"), "calendar cutoff")
        if (
            type(usage_ttl) is not int
            or usage_ttl <= 0
            or self.close_evaluated_at - capture_available_at > timedelta(seconds=usage_ttl)
            or self.source_valid_until > policy_available_until
            or self.source_valid_until > capture_available_at + timedelta(seconds=usage_ttl)
            or self.source_valid_until > calendar_valid_until
            or self.close_evaluated_at >= policy_available_until
        ):
            raise SettlementPlanBindingValidationError("close market usage window is invalid")
        if (
            qualification_payload.get("purpose") != _PURPOSE
            or qualification_payload.get("decision_scope") != "automatic_account_stop_loss"
            or qualification_payload.get("local_simulation_qualified") is not True
            or qualification_payload.get("freshness") != "close_snapshot"
            or qualification_payload.get("reliability") != "vendor_reported_close_snapshot"
            or qualification_payload.get("must_not_use_for_decision") is not True
            or qualification_payload.get("must_not_execute") is not True
            or qualification_payload.get("execution_authority") is not False
            or qualification_payload.get("market_available_at_basis") != _MARKET_AVAILABLE_AT_BASIS
        ):
            raise SettlementPlanBindingValidationError(
                "close qualification restrictions or availability basis differ"
            )
        global_restrictions = _object(
            qualification_payload.get("global_identity_restrictions"),
            "global identity restrictions",
        )
        if global_restrictions != {
            "must_not_use_for_decision": True,
            "must_not_execute": True,
        }:
            raise SettlementPlanBindingValidationError("global identity restrictions were relaxed")
        local_permission = _object(
            qualification_payload.get("local_market_permission"), "local market permission"
        )
        if local_permission != {
            "purpose": _PURPOSE,
            "qualified": True,
            "must_not_execute": True,
            "execution_authority": False,
        }:
            raise SettlementPlanBindingValidationError("close paper permission is invalid")
        _validate_locked_position(
            locked_position,
            account_id=self.account_id,
            security_id=self.security_id,
            execution_price=self.execution_price,
            close_evaluated_at=self.close_evaluated_at,
        )
        _verify_nested_hashes(
            market_bundle=market_bundle,
            policy=policy,
            calendar=calendar,
            market=market,
            qualification=close_decision,
        )
        self._validate_outer_bindings(
            retained_source=retained_source,
            market_bundle=market_bundle,
            close_decision=close_decision,
            policy=policy,
            calendar=calendar,
            market=market,
            rule_hash=bundle_rule_hash,
        )

    def _validate_outer_bindings(
        self,
        *,
        retained_source: dict[str, object],
        market_bundle: dict[str, object],
        close_decision: dict[str, object],
        policy: dict[str, object],
        calendar: dict[str, object],
        market: dict[str, object],
        rule_hash: str,
    ) -> None:
        """Compare every duplicate receipt field with its exact nested source."""

        market_evidence = _object(market.get("market_evidence_v1"), "market evidence")
        capture = _object(market_bundle.get("capture"), "market capture")
        if (
            retained_source.get("security_id") != self.security_id
            or retained_source.get("account_id") != self.account_id
            or retained_source.get("policy_hash") != self.policy_hash
            or capture.get("body_sha256") != self.source_hash
            or market_bundle.get("content_hash") != self.market_bundle_hash
            or market.get("content_hash") != self.market_hash
            or market_bundle.get("execution_rule_content_hash") != self.rule_hash
            or rule_hash != self.rule_hash
            or policy.get("content_hash") != self.policy_hash
            or calendar.get("content_hash") != self.calendar_hash
            or close_decision.get("content_hash") != self.close_qualification_hash
            or close_decision.get("market_content_hash") != self.market_hash
            or close_decision.get("execution_rule_content_hash") != self.rule_hash
            or close_decision.get("calendar_content_hash") != self.calendar_hash
            or close_decision.get("policy_content_hash") != self.policy_hash
            or close_decision.get("capture_body_sha256") != self.source_hash
            or close_decision.get("order_id") != self.idempotency_key
            or close_decision.get("account_id") != self.account_id
            or close_decision.get("security_id") != self.security_id
            or close_decision.get("asset_code") != self.asset_code
            or close_decision.get("requested_price") != str(self.execution_price)
            or _parse_utc(close_decision.get("evaluated_at"), "qualification clock")
            != self.close_evaluated_at
            or _parse_utc(market_evidence.get("market_observed_at"), "market observation")
            != self.source_observed_at
            or _parse_utc(market_evidence.get("market_available_at"), "market availability")
            != self.source_available_at
            or _parse_utc(market_evidence.get("market_valid_until"), "market validity")
            != self.source_valid_until
        ):
            raise SettlementPlanBindingValidationError("close audit outer binding differs")

    def _content_payload(self) -> dict[str, object]:
        """Build the exact close-audit fields before adding its content digest."""

        return {
            "schema": _AUDIT_SCHEMA,
            "purpose": _PURPOSE,
            "account_id": self.account_id,
            "user_id": self.user_id,
            "idempotency_key": self.idempotency_key,
            "request_payload_hash": self.request_payload_hash,
            "security_id": self.security_id,
            "asset_code": self.asset_code,
            "side": "sell",
            "execution_price": str(self.execution_price),
            "source_id": self.source_id,
            "source_version": self.source_version,
            "source_hash": self.source_hash,
            "source_observed_at": _utc_text(self.source_observed_at),
            "source_available_at": _utc_text(self.source_available_at),
            "source_valid_until": _utc_text(self.source_valid_until),
            "policy_id": self.policy_id,
            "policy_version": self.policy_version,
            "policy_hash": self.policy_hash,
            "market_hash": self.market_hash,
            "market_bundle_hash": self.market_bundle_hash,
            "rule_hash": self.rule_hash,
            "calendar_hash": self.calendar_hash,
            "close_qualification_hash": self.close_qualification_hash,
            "close_evaluated_at": _utc_text(self.close_evaluated_at),
            "evidence": json.loads(self.evidence_json),
            "evidence_hash": self.evidence_hash,
        }

    def to_payload(self) -> CloseSnapshotExecutionMarketAuditPayload:
        """Return the exact close audit envelope with a newly checked hash chain."""

        self.__post_init__()
        return cast(
            CloseSnapshotExecutionMarketAuditPayload,
            {**self._content_payload(), "content_hash": self.content_hash},
        )

    @classmethod
    def from_payload(cls, payload: object) -> CloseSnapshotExecutionMarketAuditV1:
        """Strictly decode one close-only audit without accepting V1 Risk fields."""

        fields = _exact_object(payload, _AUDIT_KEYS, "close market audit")
        if fields.get("schema") != _AUDIT_SCHEMA or fields.get("purpose") != _PURPOSE:
            raise SettlementPlanBindingValidationError("close market audit header is invalid")
        if fields.get("side") != "sell":
            raise SettlementPlanBindingValidationError("close market audit side must be sell")
        if any(type(fields.get(name)) is not str for name in _AUDIT_TEXT_FIELDS):
            raise SettlementPlanBindingValidationError("close market audit text fields are invalid")
        account_id = _positive_database_id(fields.get("account_id"), "account_id")
        user_id = _positive_database_id(fields.get("user_id"), "user_id")
        try:
            price = Decimal(cast(str, fields["execution_price"]))
            evidence_json = _canonical_json_text(fields["evidence"])
        except (ArithmeticError, TypeError, ValueError) as error:
            raise SettlementPlanBindingValidationError(
                "close market audit values are invalid"
            ) from error
        audit = cls(
            account_id=account_id,
            user_id=user_id,
            idempotency_key=cast(str, fields["idempotency_key"]),
            request_payload_hash=cast(str, fields["request_payload_hash"]),
            security_id=cast(str, fields["security_id"]),
            asset_code=cast(str, fields["asset_code"]),
            execution_price=price,
            source_id=cast(str, fields["source_id"]),
            source_version=cast(str, fields["source_version"]),
            source_hash=cast(str, fields["source_hash"]),
            source_observed_at=_parse_utc(fields["source_observed_at"], "source_observed_at"),
            source_available_at=_parse_utc(fields["source_available_at"], "source_available_at"),
            source_valid_until=_parse_utc(fields["source_valid_until"], "source_valid_until"),
            policy_id=cast(str, fields["policy_id"]),
            policy_version=cast(str, fields["policy_version"]),
            policy_hash=cast(str, fields["policy_hash"]),
            market_hash=cast(str, fields["market_hash"]),
            market_bundle_hash=cast(str, fields["market_bundle_hash"]),
            rule_hash=cast(str, fields["rule_hash"]),
            calendar_hash=cast(str, fields["calendar_hash"]),
            close_qualification_hash=cast(str, fields["close_qualification_hash"]),
            close_evaluated_at=_parse_utc(fields["close_evaluated_at"], "close_evaluated_at"),
            evidence_json=evidence_json,
            evidence_hash=cast(str, fields["evidence_hash"]),
            content_hash=cast(str, fields["content_hash"]),
        )
        if audit.to_payload() != fields:
            raise SettlementPlanBindingValidationError("close market audit is not canonical")
        return audit
