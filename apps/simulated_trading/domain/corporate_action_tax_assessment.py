"""Immutable, recalculated tax-assessment facts and observation provenance.

This Domain validates consistency only. Its values do not qualify an official
source, activate a policy, prove current ownership, grant authority, or post a
financial entry. Trusted Application/Infrastructure adapters must establish
those facts before constructing or persisting an assessment.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from decimal import Decimal, localcontext

from apps.simulated_trading.domain.corporate_action_deferred_tax import (
    DeferredDividendTaxAssessment as DeferredTaxCalculation,
)
from apps.simulated_trading.domain.corporate_action_deferred_tax import (
    DeferredDividendTaxPolicy,
    DeferredDividendTaxValidationError,
    TaxableDispositionEvidence,
    TaxLotAllocation,
    TaxLotEvidence,
    _require_account_id,
    _require_date,
    _require_digest,
    _require_token,
    calculate_deferred_dividend_tax,
)
from apps.simulated_trading.domain.corporate_action_tax_settlement_bridge import (
    DeferredDividendTaxSettlementBridgeResult,
    build_deferred_dividend_tax_history_request,
)
from apps.simulated_trading.domain.corporate_action_tax_settlement_evidence import (
    QualifiedTaxSettlementHistory,
    TaxSettlementDayEvidence,
)
from apps.simulated_trading.domain.corporate_action_tax_source_evidence import (
    TaxAssessmentStatutorySourceBundle,
)
from apps.simulated_trading.domain.simulated_tax_settlement_history import (
    SimulatedTaxSettlementHistoryObservation,
)

_SCHEMA = "corporate-action-deferred-tax-assessment.v1"


def _canonical_json(payload: dict[str, object]) -> str:
    """Encode a JSON-compatible payload deterministically without float values."""

    try:
        return json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
    except (TypeError, ValueError) as error:
        raise DeferredDividendTaxValidationError(
            "assessment payload contains a noncanonical value"
        ) from error


def _sha256_text(value: str) -> str:
    """Return the lowercase SHA-256 for one canonical UTF-8 payload."""

    try:
        encoded = value.encode("utf-8")
    except UnicodeEncodeError as error:
        raise DeferredDividendTaxValidationError(
            "assessment payload must be valid UTF-8"
        ) from error
    return hashlib.sha256(encoded).hexdigest()


def _require_utf8_token(value: object, field_name: str, limit: int) -> str:
    """Apply the legacy token contract and reject strings that cannot be UTF-8 sealed."""

    if type(value) is not str:
        raise DeferredDividendTaxValidationError(f"{field_name} must be valid text")
    _require_token(value, field_name, limit)
    try:
        value.encode("utf-8")
    except UnicodeEncodeError as error:
        raise DeferredDividendTaxValidationError(f"{field_name} must be valid UTF-8") from error
    return value


def _decimal_text(value: Decimal) -> str:
    """Return context-independent canonical finite decimal text without exponent notation."""

    if type(value) is not Decimal or not value.is_finite():
        raise DeferredDividendTaxValidationError("assessment Decimal must be finite")
    sign, raw_digits, exponent = value.as_tuple()
    if type(exponent) is not int:
        raise DeferredDividendTaxValidationError("assessment Decimal exponent must be finite")
    digits = list(raw_digits)
    if not any(digits):
        return "0"
    while digits[-1] == 0:
        digits.pop()
        exponent += 1
    coefficient = "".join(str(digit) for digit in digits)
    if exponent >= 0:
        text = coefficient + ("0" * exponent)
    else:
        decimal_places = -exponent
        if len(coefficient) > decimal_places:
            split = len(coefficient) - decimal_places
            text = f"{coefficient[:split]}.{coefficient[split:]}"
        else:
            text = f"0.{('0' * (decimal_places - len(coefficient)))}{coefficient}"
    return f"-{text}" if sign else text


def _share_text(value: Decimal) -> str:
    """Encode a supported share value at the tax Domain's six-place precision."""

    if type(value) is not Decimal or not value.is_finite():
        raise DeferredDividendTaxValidationError("assessment share quantity must be finite")
    with localcontext() as context:
        context.prec = 80
        return format(value.quantize(Decimal("0.000001")), "f")


def _instant_text(value: datetime, *, field_name: str) -> str:
    """Return an aware instant in UTC or reject an unrepresentable timestamp."""

    if type(value) is not datetime or value.tzinfo is None or value.utcoffset() is None:
        raise DeferredDividendTaxValidationError(f"{field_name} must be timezone-aware")
    try:
        return value.astimezone(UTC).isoformat(timespec="microseconds")
    except (OverflowError, ValueError) as error:
        raise DeferredDividendTaxValidationError(
            f"{field_name} must be representable in UTC"
        ) from error


@dataclass(frozen=True, slots=True)
class QualifiedCorporateActionTaxFacts:
    """Account-scoped native action facts supplied by a trusted qualifier.

    Stable source identifiers and hashes are part of semantic identity. This
    DTO does not independently prove that the issuer or qualifier is trusted.
    """

    account_id: int
    owner_user_id: int
    security_id: str
    asset_code: str
    corporate_action_id: str
    source_namespace: str
    source_record_id: str
    source_event_id: str
    source_revision_id: str
    source_revision_sha256: str
    source_payload_sha256: str
    record_date: date
    effective_date: date
    dividend_per_share: Decimal

    def __post_init__(self) -> None:
        """Validate the exact action scope, source revision, dates, and value."""

        _require_account_id(self.account_id, "action.account_id")
        _require_account_id(self.owner_user_id, "action.owner_user_id")
        for value, name, limit in (
            (self.security_id, "action.security_id", 96),
            (self.asset_code, "action.asset_code", 96),
            (self.corporate_action_id, "action.corporate_action_id", 128),
            (self.source_namespace, "action.source_namespace", 128),
            (self.source_record_id, "action.source_record_id", 192),
            (self.source_event_id, "action.source_event_id", 192),
            (self.source_revision_id, "action.source_revision_id", 192),
        ):
            _require_utf8_token(value, name, limit)
        _require_digest(self.source_revision_sha256, "action.source_revision_sha256")
        _require_digest(self.source_payload_sha256, "action.source_payload_sha256")
        _require_date(self.record_date, "action.record_date")
        _require_date(self.effective_date, "action.effective_date")
        if type(self.dividend_per_share) is not Decimal or not self.dividend_per_share.is_finite():
            raise DeferredDividendTaxValidationError(
                "action.dividend_per_share must be an exact finite Decimal"
            )
        if self.dividend_per_share < Decimal("0"):
            raise DeferredDividendTaxValidationError("action.dividend_per_share cannot be negative")
        exponent = self.dividend_per_share.as_tuple().exponent
        if (
            type(exponent) is not int
            or exponent < -12
            or exponent > 17
            or self.dividend_per_share.adjusted() >= 18
        ):
            raise DeferredDividendTaxValidationError(
                "action.dividend_per_share exceeds the calculator's exact capacity"
            )


def _action_payload(action: QualifiedCorporateActionTaxFacts) -> dict[str, object]:
    """Serialize stable action and publisher revision facts."""

    return {
        "account_id": action.account_id,
        "owner_user_id": action.owner_user_id,
        "security_id": action.security_id,
        "asset_code": action.asset_code,
        "corporate_action_id": action.corporate_action_id,
        "source_namespace": action.source_namespace,
        "source_record_id": action.source_record_id,
        "source_event_id": action.source_event_id,
        "source_revision_id": action.source_revision_id,
        "source_revision_sha256": action.source_revision_sha256,
        "source_payload_sha256": action.source_payload_sha256,
        "record_date": action.record_date.isoformat(),
        "effective_date": action.effective_date.isoformat(),
        "dividend_per_share": _decimal_text(action.dividend_per_share),
    }


def _policy_payload(policy: DeferredDividendTaxPolicy) -> dict[str, object]:
    """Serialize every explicit policy term used by the existing calculator."""

    return {
        "policy_id": policy.policy_id,
        "version": policy.version,
        "effective_from": policy.effective_from.isoformat(),
        "effective_through": (
            policy.effective_through.isoformat() if policy.effective_through is not None else None
        ),
        "source_identity": policy.source_identity,
        "source_sha256": policy.source_sha256,
        "bands": [
            {
                "band_id": band.band_id,
                "maximum_holding_months": band.maximum_holding_months,
                "taxable_dividend_ratio": _decimal_text(band.taxable_dividend_ratio),
                "withholding_rate": _decimal_text(band.withholding_rate),
            }
            for band in policy.bands
        ],
        "currency_quantum": _decimal_text(policy.currency_quantum),
        "rounding_mode": policy.rounding_mode.value,
        "policy_sha256": policy.policy_sha256,
    }


def _tax_lot_semantic_payload(lot: TaxLotEvidence) -> dict[str, object]:
    """Serialize calculator lot facts while excluding proof-observation-derived refs."""

    return {
        "account_id": lot.account_id,
        "security_id": lot.security_id,
        "lot_id": lot.lot_id,
        "acquired_on": lot.acquired_on.isoformat(),
        "acquisition_order": lot.acquisition_order,
        "origin": lot.origin.value,
        "acquired_quantity": _share_text(lot.acquired_quantity),
        "acquisition_evidence_id": lot.acquisition_evidence_id,
        "acquisition_evidence_sha256": lot.acquisition_evidence_sha256,
        "record_date": lot.record_date.isoformat(),
        "position_quantity_at_record_date": _share_text(lot.position_quantity_at_record_date),
        "record_date_quantity": _share_text(lot.record_date_quantity),
        "dividend_per_share": _decimal_text(lot.dividend_per_share),
        "origin_transfer_evidence_id": lot.origin_transfer_evidence_id,
        "origin_transfer_evidence_sha256": lot.origin_transfer_evidence_sha256,
    }


def _disposition_payload(row: TaxableDispositionEvidence) -> dict[str, object]:
    """Serialize a verified daily-net disposition and its stable source evidence."""

    return {
        "account_id": row.account_id,
        "security_id": row.security_id,
        "disposition_id": row.disposition_id,
        "settlement_date": (
            row.transfer_settlement_date.isoformat()
            if row.transfer_settlement_date is not None
            else None
        ),
        "quantity": _share_text(row.quantity),
        "transfer_evidence_id": row.transfer_evidence_id,
        "transfer_evidence_sha256": row.transfer_evidence_sha256,
    }


def _allocation_payload(allocation: object) -> dict[str, object]:
    """Serialize one existing calculator FIFO allocation without changing values."""

    if type(allocation) is not TaxLotAllocation:
        raise DeferredDividendTaxValidationError("calculator returned an untyped allocation")
    return {
        "lot_id": allocation.lot_id,
        "sold_quantity": _share_text(allocation.sold_quantity),
        "entitled_quantity": _share_text(allocation.entitled_quantity),
        "acquired_on": allocation.acquired_on.isoformat(),
        "holding_period_end": allocation.holding_period_end.isoformat(),
        "holding_period_months": allocation.holding_period_months,
        "holding_period_band_id": allocation.holding_period_band_id,
        "gross_dividend_contribution": _decimal_text(allocation.gross_dividend_contribution),
        "taxable_dividend_contribution": _decimal_text(allocation.taxable_dividend_contribution),
        "withholding_contribution": _decimal_text(allocation.withholding_contribution),
    }


def _settlement_day_payload(day: object) -> dict[str, object]:
    """Serialize a covered session, including zero-change coverage and source revision."""

    if type(day) is not TaxSettlementDayEvidence:
        raise DeferredDividendTaxValidationError("settlement history contains an untyped day")
    return {
        "settlement_date": day.settlement_date.isoformat(),
        "account_id": day.account_id,
        "owner_user_id": day.owner_user_id,
        "security_id": day.security_id,
        "asset_code": day.asset_code,
        "opening_eod_quantity": _share_text(day.opening_eod_quantity),
        "gross_purchase_quantity": _share_text(day.gross_purchase_quantity),
        "gross_sale_quantity": _share_text(day.gross_sale_quantity),
        "non_trade_quantity_delta": _share_text(day.non_trade_quantity_delta),
        "closing_eod_quantity": _share_text(day.closing_eod_quantity),
        "purchase_origin": day.purchase_origin.value,
        "evidence_id": day.evidence_id,
        "evidence_sha256": day.evidence_sha256,
        "source_revision_id": day.source_revision_id,
        "source_revision_sha256": day.source_revision_sha256,
    }


def _semantic_payload(
    *,
    action: QualifiedCorporateActionTaxFacts,
    history: QualifiedTaxSettlementHistory,
    target_settlement_date: date,
    policy: DeferredDividendTaxPolicy,
    statutory_source_bundle: TaxAssessmentStatutorySourceBundle,
    bridge: DeferredDividendTaxSettlementBridgeResult,
    calculation: DeferredTaxCalculation,
    semantic_schema_version: int,
) -> dict[str, object]:
    """Build semantic facts independent of capture and ownership observation clocks."""

    proof = history.record_date_ownership_proof
    anchor = history.opening_anchor
    entitlement = history.record_date_entitlement
    request = bridge.request
    prefix_days = tuple(
        day for day in history.settlement_days if day.settlement_date <= target_settlement_date
    )
    payload: dict[str, object] = {
        "schema": (
            _SCHEMA
            if semantic_schema_version == 1
            else "corporate-action-deferred-tax-assessment.v2"
        ),
        "assessment_scope": {
            "account_id": history.account_id,
            "owner_user_id": history.owner_user_id,
            "asset_code": history.asset_code,
            "security_id": history.security_id,
            "corporate_action_id": action.corporate_action_id,
            "action_source_namespace": action.source_namespace,
            "action_source_record_id": action.source_record_id,
            "action_source_event_id": action.source_event_id,
            "action_source_revision_id": action.source_revision_id,
            "record_date": history.record_date.isoformat(),
            "target_settlement_date": target_settlement_date.isoformat(),
        },
        "action_revision": _action_payload(action),
        "policy": _policy_payload(policy),
        "statutory_source_revision_set": {
            "schema": "statutory-revision-set.v1",
            "source_revision_set_sha256": statutory_source_bundle.source_revision_set_sha256,
            "native_revisions": [
                {
                    "issuer": item.revision.issuer,
                    "document_id": item.revision.document_id,
                    "source_version": item.revision.source_version,
                    "source_revision_sha256": item.revision.source_revision_sha256,
                    "body_sha256": item.revision.body_sha256,
                    "body_size_bytes": item.revision.body_size_bytes,
                }
                for item in statutory_source_bundle.captures
            ],
        },
        "settlement_history": {
            "source_revision_id": history.source_revision_id,
            "source_revision_sha256": history.source_revision_sha256,
            "date_rule": {
                "id": history.settlement_date_rule_id,
                "sha256": history.settlement_date_rule_sha256,
            },
            "calendar": {
                "id": history.settlement_calendar_id,
                "sha256": history.settlement_calendar_sha256,
                "covered_sessions": [
                    day.isoformat()
                    for day in history.covered_session_dates
                    if day <= target_settlement_date
                ],
            },
            "record_ownership": {
                "exchange": proof.exchange,
                "exchange_timezone_name": proof.exchange_timezone_name,
                "ownership_snapshot_as_of_date": proof.ownership_snapshot_as_of_date.isoformat(),
                "record_date_end_exclusive": _instant_text(
                    proof.record_date_end_exclusive,
                    field_name="record_date_end_exclusive",
                ),
                "eligible_quantity": _share_text(proof.eligible_quantity),
                **(
                    {
                        "cutoff_policy_id": proof.cutoff_policy_id,
                        "cutoff_policy_sha256": proof.cutoff_policy_sha256,
                    }
                    if semantic_schema_version == 1
                    else {}
                ),
            },
            "zero_origin_anchor": {
                "anchor_id": anchor.anchor_id,
                "anchor_kind": anchor.anchor_kind.value,
                "quantity": _share_text(anchor.quantity),
                "effective_at": _instant_text(
                    anchor.effective_at, field_name="anchor.effective_at"
                ),
                "evidence_sha256": anchor.evidence_sha256,
            },
            "record_date_entitlement": {
                "kind": entitlement.kind.value,
                "rule_source_id": entitlement.rule_source_id,
                "rule_source_sha256": entitlement.rule_source_sha256,
                "qualified_total_quantity": _share_text(entitlement.qualified_total_quantity),
                "total_evidence_id": entitlement.total_evidence_id,
                "total_evidence_sha256": entitlement.total_evidence_sha256,
            },
            "settlement_days": [_settlement_day_payload(day) for day in prefix_days],
            "fifo_lots": [_tax_lot_semantic_payload(lot) for lot in request.lots],
            "daily_net_dispositions": [_disposition_payload(row) for row in request.dispositions],
        },
        "calculation": {
            "idempotency_key": calculation.idempotency_key,
            "settlement_date": calculation.settlement_date.isoformat(),
            "allocations": [_allocation_payload(row) for row in calculation.allocations],
            "gross_dividend_amount": _decimal_text(calculation.gross_dividend_amount),
            "taxable_dividend_amount": _decimal_text(calculation.taxable_dividend_amount),
            "withholding_amount": _decimal_text(calculation.withholding_amount),
        },
    }
    return payload


def _observation_manifest(
    *,
    history: QualifiedTaxSettlementHistory,
    bridge: DeferredDividendTaxSettlementBridgeResult,
    calculation: DeferredTaxCalculation,
    statutory_source_bundle: TaxAssessmentStatutorySourceBundle,
    simulated_tax_date_observation: SimulatedTaxSettlementHistoryObservation | None,
    semantic_schema_version: int,
) -> dict[str, object]:
    """Retain actual ownership/source capture observations and legacy evidence hashes."""

    proof = history.record_date_ownership_proof
    anchor = history.opening_anchor
    captures: list[dict[str, object]] = []
    for capture in statutory_source_bundle.captures:
        captures.append(
            {
                "capture_id": str(capture.capture_id),
                "source_revision_sha256": capture.revision.source_revision_sha256,
                "captured_at": _instant_text(capture.captured_at, field_name="capture.captured_at"),
                "content_type": capture.content_type,
                "body_reference": capture.body_reference,
                "body_sha256": capture.body_sha256,
                "body_size_bytes": capture.body_size_bytes,
            }
        )
    payload: dict[str, object] = {
        "schema": "corporate-action-tax-observation-manifest.v1",
        "ownership_proof": {
            "ownership_snapshot_id": proof.ownership_snapshot_id,
            "ownership_snapshot_sha256": proof.ownership_snapshot_sha256,
            "ownership_snapshot_observed_at": _instant_text(
                proof.ownership_snapshot_observed_at,
                field_name="ownership_snapshot_observed_at",
            ),
            "record_date_end_exclusive": _instant_text(
                proof.record_date_end_exclusive,
                field_name="record_date_end_exclusive",
            ),
            **(
                {
                    "cutoff_policy_id": proof.cutoff_policy_id,
                    "cutoff_policy_sha256": proof.cutoff_policy_sha256,
                }
                if semantic_schema_version == 2
                else {}
            ),
        },
        "opening_anchor_observation": {
            "anchor_id": anchor.anchor_id,
            "evidence_sha256": anchor.evidence_sha256,
            "observed_at": _instant_text(anchor.observed_at, field_name="anchor.observed_at"),
        },
        "source_capture_manifest": {
            "bundle_id": statutory_source_bundle.bundle_id,
            "version": statutory_source_bundle.version,
            "source_bundle_sha256": statutory_source_bundle.source_bundle_sha256,
            "capture_manifest_sha256": statutory_source_bundle.capture_manifest_sha256,
            "captures": captures,
        },
        "legacy_calculator_evidence": {
            "history_snapshot_id": bridge.history_snapshot_id,
            "history_snapshot_sha256": bridge.history_snapshot_sha256,
            "request_history_snapshot_id": bridge.request.history_snapshot_id,
            "request_history_snapshot_sha256": bridge.request.history_snapshot_sha256,
            "calculator_evidence_sha256": calculation.evidence_sha256,
            "calculator_assessment_sha256": calculation.assessment_sha256,
        },
    }
    if simulated_tax_date_observation is not None:
        payload["simulated_tax_settlement_observation"] = (
            simulated_tax_date_observation.to_payload()
        )
    return payload


@dataclass(frozen=True, slots=True)
class CorporateActionTaxAssessment:
    """Recalculate and seal one immutable tax evaluation and its observations.

    ``assessment_revision_id`` and ``supersedes_assessment_revision_id`` are
    append-only ledger identities. Corrections must append a new explicit
    revision; they never overwrite the earlier assessment or alter holdings.
    """

    assessment_revision_id: str
    supersedes_assessment_revision_id: str | None
    action: QualifiedCorporateActionTaxFacts
    history: QualifiedTaxSettlementHistory
    target_settlement_date: date
    policy: DeferredDividendTaxPolicy
    statutory_source_bundle: TaxAssessmentStatutorySourceBundle
    simulated_tax_date_observation: SimulatedTaxSettlementHistoryObservation | None = None
    semantic_schema_version: int = 1
    bridge: DeferredDividendTaxSettlementBridgeResult = field(init=False)
    calculation: DeferredTaxCalculation = field(init=False)
    semantic_payload_json: str = field(init=False)
    semantic_sha256: str = field(init=False)
    observation_manifest_json: str = field(init=False)
    observation_manifest_sha256: str = field(init=False)

    def __post_init__(self) -> None:
        """Validate all bound inputs, run the existing calculator, and derive hashes."""

        if type(self.semantic_schema_version) is not int or self.semantic_schema_version not in (
            1,
            2,
        ):
            raise DeferredDividendTaxValidationError("assessment semantic schema is unsupported")

        _require_utf8_token(self.assessment_revision_id, "assessment_revision_id", 192)
        if self.supersedes_assessment_revision_id is not None:
            _require_utf8_token(
                self.supersedes_assessment_revision_id,
                "supersedes_assessment_revision_id",
                192,
            )
            if self.supersedes_assessment_revision_id == self.assessment_revision_id:
                raise DeferredDividendTaxValidationError(
                    "an assessment revision cannot supersede itself"
                )
        if type(self.action) is not QualifiedCorporateActionTaxFacts:
            raise DeferredDividendTaxValidationError("assessment requires exact action facts")
        if type(self.history) is not QualifiedTaxSettlementHistory:
            raise DeferredDividendTaxValidationError(
                "assessment requires qualified settlement history"
            )
        if type(self.policy) is not DeferredDividendTaxPolicy:
            raise DeferredDividendTaxValidationError("assessment requires an explicit tax policy")
        if type(self.statutory_source_bundle) is not TaxAssessmentStatutorySourceBundle:
            raise DeferredDividendTaxValidationError("assessment requires a retained source bundle")
        if self.simulated_tax_date_observation is not None:
            if (
                type(self.simulated_tax_date_observation)
                is not SimulatedTaxSettlementHistoryObservation
            ):
                raise DeferredDividendTaxValidationError(
                    "simulated tax history observation has an unsupported type"
                )
            self.simulated_tax_date_observation.verify_for(self.history)

        self.action.__post_init__()
        self.history.__post_init__()
        self.policy.__post_init__()
        self.statutory_source_bundle.__post_init__()
        _require_date(self.target_settlement_date, "target_settlement_date")
        if (
            self.action.account_id != self.history.account_id
            or self.action.owner_user_id != self.history.owner_user_id
            or self.action.security_id != self.history.security_id
            or self.action.asset_code != self.history.asset_code
            or self.action.record_date != self.history.record_date
        ):
            raise DeferredDividendTaxValidationError(
                "action facts cross settlement-history scope or record date"
            )
        if self.policy.source_identity != self.statutory_source_bundle.source_revision_set_identity:
            raise DeferredDividendTaxValidationError(
                "policy source identity differs from the native revision set"
            )
        if self.policy.source_sha256 != self.statutory_source_bundle.source_revision_set_sha256:
            raise DeferredDividendTaxValidationError(
                "policy source digest differs from the native revision set"
            )

        bridge = build_deferred_dividend_tax_history_request(
            self.history,
            target_settlement_date=self.target_settlement_date,
            corporate_action_id=self.action.corporate_action_id,
            dividend_per_share=self.action.dividend_per_share,
        )
        if (
            bridge.account_id != self.action.account_id
            or bridge.owner_user_id != self.action.owner_user_id
            or bridge.security_id != self.action.security_id
            or bridge.asset_code != self.action.asset_code
            or bridge.record_date != self.action.record_date
            or bridge.request.corporate_action_id != self.action.corporate_action_id
            or bridge.request.complete_through != self.target_settlement_date
        ):
            raise DeferredDividendTaxValidationError(
                "calculated settlement bridge differs from action scope"
            )
        calculation = calculate_deferred_dividend_tax(bridge.request, self.policy)
        semantic_payload = _semantic_payload(
            action=self.action,
            history=self.history,
            target_settlement_date=self.target_settlement_date,
            policy=self.policy,
            statutory_source_bundle=self.statutory_source_bundle,
            bridge=bridge,
            calculation=calculation,
            semantic_schema_version=self.semantic_schema_version,
        )
        observation_payload = _observation_manifest(
            history=self.history,
            bridge=bridge,
            calculation=calculation,
            statutory_source_bundle=self.statutory_source_bundle,
            simulated_tax_date_observation=self.simulated_tax_date_observation,
            semantic_schema_version=self.semantic_schema_version,
        )
        semantic_json = _canonical_json(semantic_payload)
        observation_json = _canonical_json(observation_payload)
        object.__setattr__(self, "bridge", bridge)
        object.__setattr__(self, "calculation", calculation)
        object.__setattr__(self, "semantic_payload_json", semantic_json)
        object.__setattr__(self, "semantic_sha256", _sha256_text(semantic_json))
        object.__setattr__(self, "observation_manifest_json", observation_json)
        object.__setattr__(
            self,
            "observation_manifest_sha256",
            _sha256_text(observation_json),
        )

    @property
    def account_id(self) -> int:
        """Return the physical simulated account identity bound by the history."""

        return self.history.account_id

    @property
    def owner_user_id(self) -> int:
        """Return the owner identity bound by the qualified account history."""

        return self.history.owner_user_id

    @property
    def asset_code(self) -> str:
        """Return the canonical asset identity bound by the history."""

        return self.history.asset_code

    @property
    def security_id(self) -> str:
        """Return the security identity bound by the action and history."""

        return self.history.security_id

    def verify_integrity(self) -> CorporateActionTaxAssessment:
        """Recompute all derived results and digests before application persistence."""

        rebuilt = CorporateActionTaxAssessment(
            assessment_revision_id=self.assessment_revision_id,
            supersedes_assessment_revision_id=self.supersedes_assessment_revision_id,
            action=self.action,
            history=self.history,
            target_settlement_date=self.target_settlement_date,
            policy=self.policy,
            statutory_source_bundle=self.statutory_source_bundle,
            simulated_tax_date_observation=self.simulated_tax_date_observation,
            semantic_schema_version=self.semantic_schema_version,
        )
        if (
            rebuilt.bridge != self.bridge
            or rebuilt.calculation != self.calculation
            or rebuilt.semantic_payload_json != self.semantic_payload_json
            or rebuilt.semantic_sha256 != self.semantic_sha256
            or rebuilt.observation_manifest_json != self.observation_manifest_json
            or rebuilt.observation_manifest_sha256 != self.observation_manifest_sha256
        ):
            raise DeferredDividendTaxValidationError(
                "assessment derived values or hashes no longer match its inputs"
            )
        return rebuilt


__all__ = [
    "CorporateActionTaxAssessment",
    "QualifiedCorporateActionTaxFacts",
]
