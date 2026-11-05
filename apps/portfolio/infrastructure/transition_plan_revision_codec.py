"""Strict JSON boundary for full source-bound transition-plan revisions."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Literal, cast

from apps.portfolio.domain.entities import ConstraintDecision, OrderDraft, TransitionPlan
from apps.portfolio.domain.transition_plan_revision import (
    TransitionPlanBasis,
    TransitionPlanOrderBinding,
    TransitionPlanPolicyBinding,
    TransitionPlanPositionBinding,
    TransitionPlanRevision,
    TransitionPlanRevisionIdentity,
    TransitionPlanRiskBinding,
    TransitionPlanSourceBinding,
)
from apps.portfolio.domain.transition_plan_revision_support import _canonical_hash
from core.exceptions import BusinessLogicError


class TransitionPlanRevisionCodecError(BusinessLogicError):
    """Stored plan JSON is missing, malformed, or fails its exact content hash."""

    default_message = "transition plan revision JSON is invalid"
    default_code = "TRANSITION_PLAN_REVISION_CODEC_INVALID"


def encode_transition_plan_revision(
    revision: TransitionPlanRevision, *, idempotency_key: str
) -> dict[str, object]:
    """Return the lossless persisted JSON wrapper for one immutable revision."""

    if type(revision) is not TransitionPlanRevision:
        raise TypeError("revision must be a TransitionPlanRevision")
    if type(idempotency_key) is not str or not idempotency_key:
        raise ValueError("idempotency_key is required")
    return {"revision": revision.to_payload(), "idempotency_key": idempotency_key}


def decode_transition_plan_revision(
    value: object, *, current_status: str, idempotency_key: str
) -> TransitionPlanRevision:
    """Decode and independently revalidate a stored full revision payload."""

    wrapper = _object(value, "stored_revision")
    if set(wrapper) != {"revision", "idempotency_key"}:
        raise TransitionPlanRevisionCodecError("stored revision wrapper keys are invalid")
    if wrapper.get("idempotency_key") != idempotency_key:
        raise TransitionPlanRevisionCodecError("stored idempotency key binding is invalid")
    payload = _object(wrapper.get("revision"), "revision")
    expected_keys = {
        "identity",
        "status",
        "transition_plan",
        "basis",
        "orders",
        "automatic_submission",
    }
    if set(payload) != expected_keys or payload.get("automatic_submission") is not False:
        raise TransitionPlanRevisionCodecError("stored revision schema is invalid")
    identity_payload = _object(payload.get("identity"), "identity")
    identity = _identity(identity_payload)
    basis = _basis(_object(payload.get("basis"), "basis"))
    transition_plan = _object(payload.get("transition_plan"), "transition_plan")
    plan = _plan(
        transition_plan,
        plan_id=identity.plan_id,
        idempotency_key=idempotency_key,
        current_status=current_status,
        version=identity.version,
    )
    orders_value = _sequence(payload.get("orders"), "orders")
    orders = tuple(_order_binding(_object(item, "order")) for item in orders_value)
    revision = TransitionPlanRevision(
        plan=plan,
        identity=identity,
        basis=basis,
        orders=orders,
    )
    # Lifecycle status is mutable in the existing model; all immutable bytes remain exact.
    stored_immutable = dict(payload)
    actual_immutable = revision.to_payload()
    stored_immutable.pop("status", None)
    actual_immutable.pop("status", None)
    if _canonical_hash(stored_immutable) != _canonical_hash(actual_immutable):
        raise TransitionPlanRevisionCodecError("stored plan revision payload changed")
    return revision


def _plan(
    payload: Mapping[str, object],
    *,
    plan_id: str,
    idempotency_key: str,
    current_status: str,
    version: int,
) -> TransitionPlan:
    """Restore canonical-v1 plan data while taking mutable status from the ORM row."""

    order_rows = _sequence(payload.get("orders"), "transition_plan.orders")
    orders = tuple(_order_draft(_object(item, "transition_plan.order")) for item in order_rows)
    constraint_rows = _sequence(payload.get("constraints"), "transition_plan.constraints")
    constraints = tuple(
        _constraint(_object(item, "transition_plan.constraint")) for item in constraint_rows
    )
    planning_version = _text(payload.get("planning_policy_version"), "planning_policy_version")
    return TransitionPlan(
        plan_id=plan_id,
        idempotency_key=idempotency_key,
        account_id=_text(payload.get("account_id"), "account_id"),
        decision_snapshot_id=_text(payload.get("decision_snapshot_id"), "decision_snapshot_id"),
        portfolio_snapshot_id=_text(payload.get("portfolio_snapshot_id"), "portfolio_snapshot_id"),
        target_portfolio_id=_text(payload.get("target_portfolio_id"), "target_portfolio_id"),
        as_of_time=_datetime(payload.get("as_of_time"), "as_of_time"),
        expires_at=_datetime(payload.get("expires_at"), "expires_at"),
        orders=orders,
        constraints=constraints,
        cash_before=_decimal(payload.get("cash_before"), "cash_before"),
        cash_after=_decimal(payload.get("cash_after"), "cash_after"),
        status=current_status,
        version=version,
        metadata={"planning_policy_version": planning_version},
    )


def _identity(value: Mapping[str, object]) -> TransitionPlanRevisionIdentity:
    """Parse exact revision identity and parent lineage."""

    return TransitionPlanRevisionIdentity(
        plan_id=_text(value.get("plan_id"), "identity.plan_id"),
        family_id=_text(value.get("family_id"), "identity.family_id"),
        root_plan_id=_text(value.get("root_plan_id"), "identity.root_plan_id"),
        version=_integer(value.get("version"), "identity.version"),
        parent_plan_id=_optional_text(value.get("parent_plan_id"), "identity.parent_plan_id"),
        parent_version=_optional_integer(value.get("parent_version"), "identity.parent_version"),
        parent_revision_hash=_optional_text(
            value.get("parent_revision_hash"), "identity.parent_revision_hash"
        ),
        account_id=_integer(value.get("account_id"), "identity.account_id"),
        owner_user_id=_integer(value.get("owner_user_id"), "identity.owner_user_id"),
        transition_plan_hash=_text(
            value.get("transition_plan_hash"), "identity.transition_plan_hash"
        ),
        revision_hash=_text(value.get("revision_hash"), "identity.revision_hash"),
        recorded_at=_datetime(value.get("recorded_at"), "identity.recorded_at"),
        valid_until=_datetime(value.get("valid_until"), "identity.valid_until"),
    )


def _basis(value: Mapping[str, object]) -> TransitionPlanBasis:
    """Parse every exact source, policy, snapshot and position binding."""

    account = _object(value.get("account"), "basis.account")
    portfolio = _object(value.get("portfolio_snapshot"), "basis.portfolio_snapshot")
    decision = _object(value.get("decision"), "basis.decision")
    target = _object(value.get("target"), "basis.target")
    sources = tuple(
        _source_binding(_object(item, "basis.source_binding"))
        for item in _sequence(value.get("source_bindings"), "basis.source_bindings")
    )
    current_positions = tuple(
        _position_binding(_object(item, "basis.current_position"))
        for item in _sequence(value.get("current_positions"), "basis.current_positions")
    )
    target_positions = tuple(
        _position_binding(_object(item, "basis.target_position"))
        for item in _sequence(value.get("target_positions"), "basis.target_positions")
    )
    return TransitionPlanBasis(
        account_id=_integer(account.get("account_id"), "basis.account_id"),
        owner_user_id=_integer(account.get("owner_user_id"), "basis.owner_user_id"),
        requested_by_user_id=_integer(
            account.get("requested_by_user_id"), "basis.requested_by_user_id"
        ),
        money_unit=_text(value.get("money_unit"), "basis.money_unit"),
        portfolio_snapshot_id=_text(portfolio.get("id"), "portfolio_snapshot.id"),
        portfolio_snapshot_hash=_text(
            portfolio.get("content_hash"), "portfolio_snapshot.content_hash"
        ),
        portfolio_snapshot_as_of=_datetime(portfolio.get("as_of"), "portfolio_snapshot.as_of"),
        portfolio_source_evidence_hash=_text(
            portfolio.get("source_evidence_hash"), "portfolio_snapshot.source_evidence_hash"
        ),
        decision_snapshot_id=_text(decision.get("id"), "decision.id"),
        decision_snapshot_hash=_text(decision.get("content_hash"), "decision.content_hash"),
        target_portfolio_id=_text(target.get("id"), "target.id"),
        target_content_hash=_text(target.get("content_hash"), "target.content_hash"),
        selection_id=_text(target.get("selection_id"), "target.selection_id"),
        selection_hash=_text(target.get("selection_hash"), "target.selection_hash"),
        planning_policy=_policy_binding(_object(value.get("planning_policy"), "planning_policy")),
        risk=_risk_binding(_object(value.get("risk"), "risk")),
        fee_policy=_policy_binding(_object(value.get("fee_policy"), "fee_policy")),
        quantity_rule=_policy_binding(_object(value.get("quantity_rule"), "quantity_rule")),
        settlement_rule=_policy_binding(_object(value.get("settlement_rule"), "settlement_rule")),
        execution_calendar=_policy_binding(
            _object(value.get("execution_calendar"), "execution_calendar")
        ),
        source_bindings=sources,
        current_positions=current_positions,
        target_positions=target_positions,
        business_date=_date(value.get("business_date"), "business_date"),
        execution_session=_date(value.get("execution_session"), "execution_session"),
        prepared_at=_datetime(value.get("prepared_at"), "prepared_at"),
        valid_until=_datetime(value.get("valid_until"), "valid_until"),
        preparation_evidence_json=_text(
            value.get("preparation_evidence_json"), "basis.preparation_evidence_json"
        ),
    )


def _policy_binding(value: Mapping[str, object]) -> TransitionPlanPolicyBinding:
    """Parse a qualified or explicitly not-applicable policy binding."""

    return TransitionPlanPolicyBinding(
        kind=_text(value.get("kind"), "policy.kind"),
        status=cast(
            Literal["qualified", "not_applicable", "unknown"],
            _literal(
                value.get("status"), ("qualified", "not_applicable", "unknown"), "policy.status"
            ),
        ),
        reference_id=_optional_text(value.get("reference_id"), "policy.reference_id"),
        version=_optional_text(value.get("version"), "policy.version"),
        content_hash=_optional_text(value.get("content_hash"), "policy.content_hash"),
        effective_at=_optional_datetime(value.get("effective_at"), "policy.effective_at"),
        known_at=_optional_datetime(value.get("known_at"), "policy.known_at"),
        valid_until=_optional_datetime(value.get("valid_until"), "policy.valid_until"),
        reason_code=_optional_text(value.get("reason_code"), "policy.reason_code"),
    )


def _risk_binding(value: Mapping[str, object]) -> TransitionPlanRiskBinding:
    """Parse an exact allowed risk output and its complete-binding hash."""

    return TransitionPlanRiskBinding(
        report_content_hash=_text(value.get("report_content_hash"), "risk.report_content_hash"),
        binding_hash=_text(value.get("binding_hash"), "risk.binding_hash"),
        outcome=cast(
            Literal["allowed", "blocked", "partial", "unknown"],
            _literal(
                value.get("outcome"), ("allowed", "blocked", "partial", "unknown"), "risk.outcome"
            ),
        ),
        must_not_use_for_decision=_boolean(
            value.get("must_not_use_for_decision"), "risk.must_not_use_for_decision"
        ),
    )


def _source_binding(value: Mapping[str, object]) -> TransitionPlanSourceBinding:
    """Parse original source clocks without replacing missing values."""

    return TransitionPlanSourceBinding(
        kind=_text(value.get("kind"), "source.kind"),
        asset_code=_text(value.get("asset_code"), "source.asset_code"),
        security_id=_text(value.get("security_id"), "source.security_id"),
        source_id=_text(value.get("source_id"), "source.source_id"),
        source_record_id=_text(value.get("source_record_id"), "source.source_record_id"),
        manifest_sha256=_text(value.get("manifest_sha256"), "source.manifest_sha256"),
        body_sha256=_text(value.get("body_sha256"), "source.body_sha256"),
        observation_precision=cast(
            Literal["timestamp", "date", "unknown"],
            _literal(
                value.get("observation_precision"),
                ("timestamp", "date", "unknown"),
                "source.observation_precision",
            ),
        ),
        observed_at=_optional_datetime(value.get("observed_at"), "source.observed_at"),
        observed_on=_optional_date(value.get("observed_on"), "source.observed_on"),
        available_at=_optional_datetime(value.get("available_at"), "source.available_at"),
        known_at=_optional_datetime(value.get("known_at"), "source.known_at"),
        decision_cutoff=_datetime(value.get("decision_cutoff"), "source.decision_cutoff"),
        decision_date_cutoff=_optional_date(
            value.get("decision_date_cutoff"), "source.decision_date_cutoff"
        ),
        source_valid_until=_optional_datetime(
            value.get("source_valid_until"), "source.source_valid_until"
        ),
        admission_until=_datetime(value.get("admission_until"), "source.admission_until"),
        qualification_proof_hash=_optional_text(
            value.get("qualification_proof_hash"), "source.qualification_proof_hash"
        ),
        source_purpose=_text(value.get("source_purpose"), "source.source_purpose"),
        requested_purpose=_text(value.get("requested_purpose"), "source.requested_purpose"),
        allowed_purposes=_text_tuple(value.get("allowed_purposes"), "source.allowed_purposes"),
        restrictions=_text_tuple(value.get("restrictions"), "source.restrictions"),
        coverage_status=_text(value.get("coverage_status"), "source.coverage_status"),
        qualified=_boolean(value.get("qualified"), "source.qualified"),
        reason_codes=_text_tuple(value.get("reason_codes"), "source.reason_codes"),
    )


def _position_binding(value: Mapping[str, object]) -> TransitionPlanPositionBinding:
    """Parse account or target position facts, preserving unknown values."""

    return TransitionPlanPositionBinding(
        asset_code=_text(value.get("asset_code"), "position.asset_code"),
        security_id=_text(value.get("security_id"), "position.security_id"),
        quantity=_optional_decimal(value.get("quantity"), "position.quantity"),
        available_quantity=_optional_decimal(
            value.get("available_quantity"), "position.available_quantity"
        ),
        target_weight=_optional_decimal(value.get("target_weight"), "position.target_weight"),
        target_quantity=_optional_decimal(value.get("target_quantity"), "position.target_quantity"),
        reference_price=_optional_decimal(value.get("reference_price"), "position.reference_price"),
        market_value=_optional_decimal(value.get("market_value"), "position.market_value"),
        quantity_unit=_text(value.get("quantity_unit"), "position.quantity_unit"),
        money_unit=_text(value.get("money_unit"), "position.money_unit"),
        source_binding_hashes=_text_tuple(
            value.get("source_binding_hashes"), "position.source_binding_hashes"
        ),
    )


def _order_binding(value: Mapping[str, object]) -> TransitionPlanOrderBinding:
    """Parse one exact approved order and its associated unapproved amount."""

    return TransitionPlanOrderBinding(
        ordinal=_integer(value.get("ordinal"), "order.ordinal"),
        order_content_hash=_text(value.get("order_content_hash"), "order.order_content_hash"),
        plan_order_binding_id=_text(
            value.get("plan_order_binding_id"), "order.plan_order_binding_id"
        ),
        asset_code=_text(value.get("asset_code"), "order.asset_code"),
        security_id=_text(value.get("security_id"), "order.security_id"),
        asset_type=_text(value.get("asset_type"), "order.asset_type"),
        classification_content_hash=_text(
            value.get("classification_content_hash"), "order.classification_content_hash"
        ),
        side=cast(
            Literal["buy", "sell"],
            _literal(value.get("side"), ("buy", "sell"), "order.side"),
        ),
        requested_quantity=_integer(value.get("requested_quantity"), "order.requested_quantity"),
        approved_quantity=_integer(value.get("approved_quantity"), "order.approved_quantity"),
        unapproved_quantity=_integer(value.get("unapproved_quantity"), "order.unapproved_quantity"),
        reference_price=_decimal(value.get("reference_price"), "order.reference_price"),
        estimated_fee=_decimal(value.get("estimated_fee"), "order.estimated_fee"),
        approved_limit_price=_optional_decimal(
            value.get("approved_limit_price"), "order.approved_limit_price"
        ),
        quantity_unit=_text(value.get("quantity_unit"), "order.quantity_unit"),
        money_unit=_text(value.get("money_unit"), "order.money_unit"),
        status=_text(value.get("status"), "order.status"),
        reason_codes=_text_tuple(value.get("reason_codes"), "order.reason_codes"),
    )


def _order_draft(value: Mapping[str, object]) -> OrderDraft:
    """Parse one legacy canonical-v1 order row byte-for-byte semantically."""

    return OrderDraft(
        asset_code=_text(value.get("asset_code"), "order.asset_code"),
        side=_text(value.get("side"), "order.side"),
        quantity=_integer(value.get("quantity"), "order.quantity"),
        reference_price=_decimal(value.get("reference_price"), "order.reference_price"),
        estimated_fee=_decimal(value.get("estimated_fee"), "order.estimated_fee"),
        status=_text(value.get("status"), "order.status"),
        remaining_quantity=_integer(value.get("remaining_quantity"), "order.remaining_quantity"),
        constraints=tuple(
            _constraint(_object(item, "order.constraint"))
            for item in _sequence(value.get("constraints"), "order.constraints")
        ),
    )


def _constraint(value: Mapping[str, object]) -> ConstraintDecision:
    """Parse one persisted legacy constraint result."""

    return ConstraintDecision(
        rule_code=_text(value.get("rule_code"), "constraint.rule_code"),
        asset_code=_text(value.get("asset_code"), "constraint.asset_code"),
        allowed=_boolean(value.get("allowed"), "constraint.allowed"),
        original_quantity=_integer(value.get("original_quantity"), "constraint.original_quantity"),
        allowed_quantity=_integer(value.get("allowed_quantity"), "constraint.allowed_quantity"),
        reason=_text(value.get("reason", ""), "constraint.reason"),
    )


def _object(value: object, field_name: str) -> Mapping[str, object]:
    if type(value) is not dict or any(type(key) is not str for key in value):
        raise TransitionPlanRevisionCodecError(f"{field_name} must be a JSON object")
    return dict(value)


def _sequence(value: object, field_name: str) -> tuple[object, ...]:
    if type(value) is not list:
        raise TransitionPlanRevisionCodecError(f"{field_name} must be a JSON array")
    return tuple(value)


def _text(value: object, field_name: str) -> str:
    if type(value) is not str:
        raise TransitionPlanRevisionCodecError(f"{field_name} must be a string")
    return value


def _optional_text(value: object, field_name: str) -> str | None:
    return None if value is None else _text(value, field_name)


def _integer(value: object, field_name: str) -> int:
    if type(value) is not int:
        raise TransitionPlanRevisionCodecError(f"{field_name} must be an integer")
    return value


def _optional_integer(value: object, field_name: str) -> int | None:
    return None if value is None else _integer(value, field_name)


def _boolean(value: object, field_name: str) -> bool:
    if type(value) is not bool:
        raise TransitionPlanRevisionCodecError(f"{field_name} must be a boolean")
    return value


def _decimal(value: object, field_name: str) -> Decimal:
    if type(value) is not str:
        raise TransitionPlanRevisionCodecError(f"{field_name} must be a decimal string")
    try:
        result = Decimal(value)
    except InvalidOperation as error:
        raise TransitionPlanRevisionCodecError(f"{field_name} is not a decimal") from error
    if not result.is_finite():
        raise TransitionPlanRevisionCodecError(f"{field_name} must be finite")
    return result


def _optional_decimal(value: object, field_name: str) -> Decimal | None:
    return None if value is None else _decimal(value, field_name)


def _datetime(value: object, field_name: str) -> datetime:
    if type(value) is not str:
        raise TransitionPlanRevisionCodecError(f"{field_name} must be an ISO datetime")
    try:
        result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise TransitionPlanRevisionCodecError(f"{field_name} is not an ISO datetime") from error
    if result.tzinfo is None or result.utcoffset() is None:
        raise TransitionPlanRevisionCodecError(f"{field_name} must be timezone-aware")
    return result


def _optional_datetime(value: object, field_name: str) -> datetime | None:
    return None if value is None else _datetime(value, field_name)


def _date(value: object, field_name: str) -> date:
    if type(value) is not str:
        raise TransitionPlanRevisionCodecError(f"{field_name} must be an ISO date")
    try:
        result = date.fromisoformat(value)
    except ValueError as error:
        raise TransitionPlanRevisionCodecError(f"{field_name} is not an ISO date") from error
    if type(result) is not date:
        raise TransitionPlanRevisionCodecError(f"{field_name} must be a pure date")
    return result


def _optional_date(value: object, field_name: str) -> date | None:
    return None if value is None else _date(value, field_name)


def _text_tuple(value: object, field_name: str) -> tuple[str, ...]:
    return tuple(_text(item, field_name) for item in _sequence(value, field_name))


def _literal(value: object, allowed: tuple[str, ...], field_name: str) -> str:
    result = _text(value, field_name)
    if result not in allowed:
        raise TransitionPlanRevisionCodecError(f"{field_name} has an unknown value")
    return result


__all__ = [
    "TransitionPlanRevisionCodecError",
    "decode_transition_plan_revision",
    "encode_transition_plan_revision",
]
