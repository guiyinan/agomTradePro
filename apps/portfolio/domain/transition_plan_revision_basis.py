"""Typed trusted snapshot and evidence basis for plan revisions."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from typing import Literal, cast

from apps.portfolio.domain.transition_plan_revision_support import (
    ObservationPrecision,
    PlanOutcome,
    _canonical_hash,
    _date_text,
    _datetime_text,
    _decimal_text,
    _require_aware,
    _require_decimal,
    _require_digest,
    _require_token,
)


@dataclass(frozen=True, slots=True)
class TransitionPlanPolicyBinding:
    """Exact policy identity and clocks used to derive one plan revision."""

    kind: str
    status: Literal["qualified", "not_applicable", "unknown"]
    reference_id: str | None
    version: str | None
    content_hash: str | None
    effective_at: datetime | None
    known_at: datetime | None
    valid_until: datetime | None
    reason_code: str | None = None

    def __post_init__(self) -> None:
        """Preserve genuinely unconsumed policy fields without inventing a binding."""

        _require_token(self.kind, "kind")
        if self.status == "qualified":
            _require_token(self.reference_id, "reference_id")
            _require_token(self.version, "version")
            _require_digest(self.content_hash, "content_hash")
            _require_aware(self.effective_at, "effective_at")
            _require_aware(self.known_at, "known_at")
            if self.reason_code is not None:
                raise ValueError("qualified policy binding cannot have a missing reason")
        elif self.status == "not_applicable":
            if any(
                value is not None
                for value in (
                    self.reference_id,
                    self.version,
                    self.content_hash,
                    self.effective_at,
                    self.known_at,
                    self.valid_until,
                )
            ):
                raise ValueError("not-applicable policy cannot carry invented binding values")
            _require_token(self.reason_code, "reason_code")
        else:
            raise ValueError("unknown policy binding cannot back a trusted plan")
        if self.valid_until is not None:
            _require_aware(self.valid_until, "valid_until")
            if self.effective_at is not None and self.valid_until <= self.effective_at:
                raise ValueError("policy valid_until must follow effective_at")

    def to_payload(self) -> dict[str, object]:
        """Return the exact identity and source clocks for a public plan view."""

        return {
            "kind": self.kind,
            "status": self.status,
            "reference_id": self.reference_id,
            "version": self.version,
            "content_hash": self.content_hash,
            "effective_at": _datetime_text(self.effective_at),
            "known_at": _datetime_text(self.known_at),
            "valid_until": _datetime_text(self.valid_until),
            "reason_code": self.reason_code,
        }


@dataclass(frozen=True, slots=True)
class TransitionPlanSourceBinding:
    """One exact retained source pin and its original observation/use clocks."""

    kind: str
    asset_code: str
    security_id: str
    source_id: str
    source_record_id: str
    manifest_sha256: str
    body_sha256: str
    observation_precision: ObservationPrecision
    observed_at: datetime | None
    observed_on: date | None
    available_at: datetime | None
    known_at: datetime | None
    decision_cutoff: datetime
    decision_date_cutoff: date | None
    source_valid_until: datetime | None
    admission_until: datetime
    qualification_proof_hash: str | None
    source_purpose: str
    requested_purpose: str
    allowed_purposes: tuple[str, ...]
    restrictions: tuple[str, ...]
    coverage_status: str
    qualified: bool
    reason_codes: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        """Require an exact successful source admission with untouched clocks."""

        for name in (
            "kind",
            "asset_code",
            "security_id",
            "source_id",
            "source_record_id",
            "source_purpose",
            "requested_purpose",
            "coverage_status",
        ):
            _require_token(getattr(self, name), name)
        _require_digest(self.manifest_sha256, "manifest_sha256")
        _require_digest(self.body_sha256, "body_sha256")
        _require_aware(self.decision_cutoff, "decision_cutoff")
        _require_aware(self.admission_until, "admission_until")
        if self.source_valid_until is not None:
            _require_aware(self.source_valid_until, "source_valid_until")
        if self.qualification_proof_hash is not None:
            _require_digest(self.qualification_proof_hash, "qualification_proof_hash")
        if self.observation_precision == "timestamp":
            _require_aware(self.observed_at, "observed_at")
            if self.observed_on is not None:
                raise ValueError("timestamp source cannot also claim observed_on")
        elif self.observation_precision == "date":
            if type(self.observed_on) is not date or type(self.observed_on) is datetime:
                raise ValueError("date-precision source requires a pure observed_on date")
            if self.observed_at is not None or self.decision_date_cutoff is None:
                raise ValueError("date source requires date cutoff and no observed_at")
        else:
            raise ValueError("unknown source observation precision cannot qualify a plan")
        if self.observed_at is not None:
            _require_aware(self.observed_at, "observed_at")
            if self.observed_at > self.decision_cutoff:
                raise ValueError("source observation follows its decision cutoff")
        if self.observed_on is not None and self.decision_date_cutoff is not None:
            if self.observed_on > self.decision_date_cutoff:
                raise ValueError("source observation date follows its date cutoff")
        for field_name in ("available_at", "known_at"):
            value = getattr(self, field_name)
            if value is not None:
                _require_aware(value, field_name)
            if value is not None and value > self.decision_cutoff:
                raise ValueError(f"{field_name} follows the source decision cutoff")
        if self.source_valid_until is not None and self.source_valid_until <= self.decision_cutoff:
            raise ValueError("source is expired at its decision cutoff")
        if self.admission_until <= self.decision_cutoff:
            raise ValueError("qualified source admission has expired at its cutoff")
        if self.qualification_proof_hash is None and (
            self.available_at is None or self.known_at is None or self.source_valid_until is None
        ):
            raise ValueError("missing source clocks require an exact qualifying proof reference")
        if self.requested_purpose not in self.allowed_purposes:
            raise ValueError("source does not permit its requested plan purpose")
        if not self.qualified or self.reason_codes:
            raise ValueError("unqualified source cannot bind a trusted plan")
        for purpose in self.allowed_purposes:
            _require_token(purpose, "allowed_purpose")
        for restriction in self.restrictions:
            _require_token(restriction, "restriction")

    def to_payload(self) -> dict[str, object]:
        """Return a JSON-safe view without replacing vendor or decision clocks."""

        return {
            "kind": self.kind,
            "asset_code": self.asset_code,
            "security_id": self.security_id,
            "source_id": self.source_id,
            "source_record_id": self.source_record_id,
            "manifest_sha256": self.manifest_sha256,
            "body_sha256": self.body_sha256,
            "observation_precision": self.observation_precision,
            "observed_at": _datetime_text(self.observed_at),
            "observed_on": _date_text(self.observed_on),
            "available_at": _datetime_text(self.available_at),
            "known_at": _datetime_text(self.known_at),
            "decision_cutoff": _datetime_text(self.decision_cutoff),
            "decision_date_cutoff": _date_text(self.decision_date_cutoff),
            "source_valid_until": _datetime_text(self.source_valid_until),
            "admission_until": _datetime_text(self.admission_until),
            "qualification_proof_hash": self.qualification_proof_hash,
            "source_purpose": self.source_purpose,
            "requested_purpose": self.requested_purpose,
            "allowed_purposes": list(self.allowed_purposes),
            "restrictions": list(self.restrictions),
            "coverage_status": self.coverage_status,
            "qualified": self.qualified,
            "reason_codes": list(self.reason_codes),
        }


@dataclass(frozen=True, slots=True)
class TransitionPlanPositionBinding:
    """One current or target position retained for explanation and replay."""

    asset_code: str
    security_id: str
    quantity: Decimal | None
    available_quantity: Decimal | None
    target_weight: Decimal | None
    target_quantity: Decimal | None
    reference_price: Decimal | None
    market_value: Decimal | None
    quantity_unit: str
    money_unit: str
    source_binding_hashes: tuple[str, ...]

    def __post_init__(self) -> None:
        """Validate exact security identity, units, and known numeric values."""

        _require_token(self.asset_code, "asset_code", maximum=32)
        _require_token(self.security_id, "security_id")
        _require_token(self.quantity_unit, "quantity_unit")
        _require_token(self.money_unit, "money_unit")
        for field_name in (
            "quantity",
            "available_quantity",
            "target_weight",
            "target_quantity",
            "reference_price",
            "market_value",
        ):
            value = getattr(self, field_name)
            if value is not None:
                _require_decimal(value, field_name)
        if self.target_weight is not None and self.target_weight > 1:
            raise ValueError("target_weight cannot exceed one")
        if (
            self.quantity is not None
            and self.available_quantity is not None
            and self.available_quantity > self.quantity
        ):
            raise ValueError("available quantity cannot exceed total quantity")
        for digest in self.source_binding_hashes:
            _require_digest(digest, "source_binding_hash")

    def to_payload(self) -> dict[str, object]:
        """Return a stable representation with every unknown kept null."""

        return {
            "asset_code": self.asset_code,
            "security_id": self.security_id,
            "quantity": _decimal_text(self.quantity),
            "available_quantity": _decimal_text(self.available_quantity),
            "target_weight": _decimal_text(self.target_weight),
            "target_quantity": _decimal_text(self.target_quantity),
            "reference_price": _decimal_text(self.reference_price),
            "market_value": _decimal_text(self.market_value),
            "quantity_unit": self.quantity_unit,
            "money_unit": self.money_unit,
            "source_binding_hashes": list(self.source_binding_hashes),
        }


@dataclass(frozen=True, slots=True)
class TransitionPlanRiskBinding:
    """A qualified full risk result and exact risk input identity."""

    report_content_hash: str
    binding_hash: str
    outcome: PlanOutcome
    must_not_use_for_decision: bool

    def __post_init__(self) -> None:
        """Require a decision-usable risk report before plan persistence."""

        _require_digest(self.report_content_hash, "report_content_hash")
        _require_digest(self.binding_hash, "binding_hash")
        if self.outcome != "allowed" or self.must_not_use_for_decision:
            raise ValueError("only qualified risk evidence can back a trusted plan")

    def to_payload(self) -> dict[str, object]:
        """Return the exact risk report and input-binding digests."""

        return {
            "report_content_hash": self.report_content_hash,
            "binding_hash": self.binding_hash,
            "outcome": self.outcome,
            "must_not_use_for_decision": self.must_not_use_for_decision,
        }


@dataclass(frozen=True, slots=True)
class TransitionPlanBasis:
    """All trusted facts and active rules used to prepare a plan revision."""

    account_id: int
    owner_user_id: int
    requested_by_user_id: int
    money_unit: str
    portfolio_snapshot_id: str
    portfolio_snapshot_hash: str
    portfolio_snapshot_as_of: datetime
    portfolio_source_evidence_hash: str
    decision_snapshot_id: str
    decision_snapshot_hash: str
    target_portfolio_id: str
    target_content_hash: str
    selection_id: str
    selection_hash: str
    planning_policy: TransitionPlanPolicyBinding
    risk: TransitionPlanRiskBinding
    fee_policy: TransitionPlanPolicyBinding
    quantity_rule: TransitionPlanPolicyBinding
    settlement_rule: TransitionPlanPolicyBinding
    execution_calendar: TransitionPlanPolicyBinding
    source_bindings: tuple[TransitionPlanSourceBinding, ...]
    current_positions: tuple[TransitionPlanPositionBinding, ...]
    target_positions: tuple[TransitionPlanPositionBinding, ...]
    business_date: date
    execution_session: date
    prepared_at: datetime
    valid_until: datetime
    preparation_evidence_json: str

    def __post_init__(self) -> None:
        """Reject missing identity, ambiguous bindings, and impossible clocks."""

        if type(self.account_id) is not int or self.account_id <= 0:
            raise ValueError("account_id must be a positive integer")
        if type(self.owner_user_id) is not int or self.owner_user_id <= 0:
            raise ValueError("owner_user_id must be a positive integer")
        if type(self.requested_by_user_id) is not int or self.requested_by_user_id <= 0:
            raise ValueError("requested_by_user_id must be a positive integer")
        for name in (
            "money_unit",
            "portfolio_snapshot_id",
            "decision_snapshot_id",
            "target_portfolio_id",
            "selection_id",
        ):
            _require_token(getattr(self, name), name)
        for name in (
            "portfolio_snapshot_hash",
            "portfolio_source_evidence_hash",
            "decision_snapshot_hash",
            "target_content_hash",
            "selection_hash",
        ):
            _require_digest(getattr(self, name), name)
        for name in ("portfolio_snapshot_as_of", "prepared_at", "valid_until"):
            _require_aware(getattr(self, name), name)
        if self.prepared_at < self.portfolio_snapshot_as_of:
            raise ValueError("plan preparation predates its portfolio snapshot")
        if self.valid_until <= self.prepared_at:
            raise ValueError("plan basis is expired at preparation time")
        self._validate_preparation_evidence()
        if type(self.business_date) is not date or type(self.business_date) is datetime:
            raise ValueError("business_date must be a date")
        if type(self.execution_session) is not date or type(self.execution_session) is datetime:
            raise ValueError("execution_session must be a date")
        if not self.source_bindings:
            raise ValueError("a trusted plan requires explicit source bindings")
        source_keys = tuple(
            (item.kind, item.asset_code, item.security_id, item.source_record_id)
            for item in self.source_bindings
        )
        if len(source_keys) != len(set(source_keys)):
            raise ValueError("plan source bindings must be unique")
        self._validate_rows(self.current_positions, "current_positions")
        self._validate_rows(self.target_positions, "target_positions")
        for policy in (
            self.planning_policy,
            self.fee_policy,
            self.quantity_rule,
            self.settlement_rule,
            self.execution_calendar,
        ):
            if policy.status == "qualified":
                if policy.known_at is None or policy.effective_at is None:
                    raise ValueError(
                        "qualified plan policy requires its real known/effective clocks"
                    )
                if policy.known_at > self.prepared_at or policy.effective_at > self.prepared_at:
                    raise ValueError("plan policy was not known and effective at preparation")
                if policy.valid_until is not None and policy.valid_until <= self.prepared_at:
                    raise ValueError("plan policy is expired at preparation")
        if self.planning_policy.status not in {"qualified", "not_applicable"}:
            raise ValueError("planning policy must be qualified or explicitly not applicable")
        for policy in (
            self.fee_policy,
            self.quantity_rule,
            self.settlement_rule,
            self.execution_calendar,
        ):
            if policy.status != "qualified":
                raise ValueError(f"{policy.kind} is required to qualify a plan")

    @staticmethod
    def _validate_rows(values: tuple[TransitionPlanPositionBinding, ...], field_name: str) -> None:
        """Reject duplicate or noncanonical position identity ordering."""

        identities = tuple((item.asset_code, item.security_id) for item in values)
        if len(identities) != len(set(identities)):
            raise ValueError(f"{field_name} contains duplicate security identities")
        if identities != tuple(sorted(identities)):
            raise ValueError(f"{field_name} must be sorted by asset/security identity")

    def _validate_preparation_evidence(self) -> None:
        """Authenticate embedded resources, decision, policies, and source bindings."""

        if type(self.preparation_evidence_json) is not str or not self.preparation_evidence_json:
            raise ValueError("preparation_evidence_json is required")
        try:
            decoded: object = json.loads(self.preparation_evidence_json)
        except (TypeError, ValueError) as error:
            raise ValueError("preparation evidence must be valid JSON") from error
        if type(decoded) is not dict or any(type(key) is not str for key in decoded):
            raise ValueError("preparation evidence must be a JSON object")
        document = cast(dict[str, object], decoded)
        expected_keys = {
            "schema",
            "portfolio_snapshot",
            "decision_snapshot",
            "target",
            "policy_bindings",
            "risk",
            "source_bindings",
            "positions",
            "business_date",
            "execution_session",
            "prepared_at",
        }
        if set(document) != expected_keys or document.get("schema") != "ash08.plan_preparation.v1":
            raise ValueError("preparation evidence schema is invalid")
        canonical = json.dumps(
            document,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
        if canonical != self.preparation_evidence_json:
            raise ValueError("preparation evidence must use canonical JSON")

        portfolio = _evidence_object(document.get("portfolio_snapshot"), "portfolio_snapshot")
        resource_payload = _evidence_object(portfolio.get("resources"), "portfolio resources")
        if (
            portfolio.get("id") != self.portfolio_snapshot_id
            or portfolio.get("content_hash") != self.portfolio_snapshot_hash
            or portfolio.get("source_evidence_hash") != self.portfolio_source_evidence_hash
            or portfolio.get("as_of") != _datetime_text(self.portfolio_snapshot_as_of)
            or _canonical_hash(resource_payload) != self.portfolio_snapshot_hash
        ):
            raise ValueError("embedded portfolio resources do not match their exact snapshot pins")

        target = _evidence_object(document.get("target"), "target")
        target_payload = _evidence_object(target.get("payload"), "target payload")
        if (
            target.get("id") != self.target_portfolio_id
            or target.get("content_hash") != self.target_content_hash
            or _canonical_hash(target_payload) != self.target_content_hash
            or target.get("selection_id") != self.selection_id
            or target.get("selection_hash") != self.selection_hash
        ):
            raise ValueError("embedded target does not match its exact selection pins")

        decision = _evidence_object(document.get("decision_snapshot"), "decision_snapshot")
        decision_payload = _evidence_object(decision.get("payload"), "decision payload")
        if (
            decision.get("id") != self.decision_snapshot_id
            or decision.get("content_hash") != self.decision_snapshot_hash
            or _canonical_hash(decision_payload) != self.decision_snapshot_hash
            or decision_payload.get("portfolio_snapshot_id") != self.portfolio_snapshot_id
            or decision_payload.get("portfolio_snapshot_hash") != self.portfolio_snapshot_hash
            or decision_payload.get("target_portfolio_id") != self.target_portfolio_id
            or decision_payload.get("target_content_hash") != self.target_content_hash
            or decision_payload.get("selection_id") != self.selection_id
            or decision_payload.get("selection_hash") != self.selection_hash
        ):
            raise ValueError("embedded decision does not match its exact snapshot and target pins")

        expected_sources = [item.to_payload() for item in self.source_bindings]
        if document.get("source_bindings") != expected_sources:
            raise ValueError("embedded source bindings differ from the qualified basis sources")
        expected_source_hash = _canonical_hash({"source_bindings": expected_sources})
        if expected_source_hash != self.portfolio_source_evidence_hash:
            raise ValueError("portfolio source evidence hash does not authenticate its bindings")

        expected_policies = {
            "planning_policy": self.planning_policy.to_payload(),
            "fee_policy": self.fee_policy.to_payload(),
            "quantity_rule": self.quantity_rule.to_payload(),
            "settlement_rule": self.settlement_rule.to_payload(),
            "execution_calendar": self.execution_calendar.to_payload(),
        }
        if document.get("policy_bindings") != expected_policies:
            raise ValueError("embedded policy bindings differ from the qualified basis policies")
        if document.get("risk") != self.risk.to_payload():
            raise ValueError("embedded risk binding differs from the qualified risk basis")
        positions = _evidence_object(document.get("positions"), "positions")
        if positions.get("current") != [
            item.to_payload() for item in self.current_positions
        ] or positions.get("target") != [item.to_payload() for item in self.target_positions]:
            raise ValueError("embedded positions differ from their exact basis rows")
        if (
            document.get("business_date") != _date_text(self.business_date)
            or document.get("execution_session") != _date_text(self.execution_session)
            or document.get("prepared_at") != _datetime_text(self.prepared_at)
        ):
            raise ValueError("embedded preparation clocks differ from their exact basis values")

    def to_payload(self) -> dict[str, object]:
        """Return the complete trusted basis with original source and policy clocks."""

        return {
            "account": {
                "account_id": self.account_id,
                "owner_user_id": self.owner_user_id,
                "requested_by_user_id": self.requested_by_user_id,
            },
            "money_unit": self.money_unit,
            "portfolio_snapshot": {
                "id": self.portfolio_snapshot_id,
                "content_hash": self.portfolio_snapshot_hash,
                "as_of": _datetime_text(self.portfolio_snapshot_as_of),
                "source_evidence_hash": self.portfolio_source_evidence_hash,
            },
            "decision": {
                "id": self.decision_snapshot_id,
                "content_hash": self.decision_snapshot_hash,
            },
            "target": {
                "id": self.target_portfolio_id,
                "content_hash": self.target_content_hash,
                "selection_id": self.selection_id,
                "selection_hash": self.selection_hash,
            },
            "planning_policy": self.planning_policy.to_payload(),
            "risk": self.risk.to_payload(),
            "fee_policy": self.fee_policy.to_payload(),
            "quantity_rule": self.quantity_rule.to_payload(),
            "settlement_rule": self.settlement_rule.to_payload(),
            "execution_calendar": self.execution_calendar.to_payload(),
            "source_bindings": [item.to_payload() for item in self.source_bindings],
            "current_positions": [item.to_payload() for item in self.current_positions],
            "target_positions": [item.to_payload() for item in self.target_positions],
            "business_date": _date_text(self.business_date),
            "execution_session": _date_text(self.execution_session),
            "prepared_at": _datetime_text(self.prepared_at),
            "valid_until": _datetime_text(self.valid_until),
            "preparation_evidence_json": self.preparation_evidence_json,
        }


def _evidence_object(value: object, field_name: str) -> dict[str, object]:
    """Narrow one parsed preparation-evidence object without dynamic leakage."""

    if type(value) is not dict or any(type(key) is not str for key in value):
        raise ValueError(f"{field_name} must be a JSON object")
    return cast(dict[str, object], value)


__all__ = [
    "ObservationPrecision",
    "PlanOutcome",
    "TransitionPlanBasis",
    "TransitionPlanPolicyBinding",
    "TransitionPlanPositionBinding",
    "TransitionPlanRiskBinding",
    "TransitionPlanSourceBinding",
]
