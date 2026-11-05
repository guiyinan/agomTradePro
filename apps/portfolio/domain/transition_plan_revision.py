"""Immutable, source-bound revisions for complete simulated transition plans."""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime
from decimal import Decimal
from typing import Literal

from apps.portfolio.domain.entities import TransitionPlan
from apps.portfolio.domain.transition_plan_integrity import (
    canonical_transition_plan_payload_v1,
    transition_plan_content_hash_v1,
)
from apps.portfolio.domain.transition_plan_revision_basis import (
    ObservationPrecision,
    TransitionPlanBasis,
    TransitionPlanPolicyBinding,
    TransitionPlanPositionBinding,
    TransitionPlanRiskBinding,
    TransitionPlanSourceBinding,
)
from apps.portfolio.domain.transition_plan_revision_support import (
    PlanOutcome,
    _canonical_hash,
    _datetime_text,
    _decimal_text,
    _require_aware,
    _require_decimal,
    _require_digest,
    _require_token,
)


@dataclass(frozen=True, slots=True)
class TransitionPlanOrderSpecification:
    """Server-resolved identity, classification and units for one order ordinal."""

    ordinal: int
    asset_code: str
    security_id: str
    asset_type: str
    classification_content_hash: str
    quantity_unit: str
    money_unit: str
    approved_limit_price: Decimal | None = None

    def __post_init__(self) -> None:
        """Validate the exact security and optional explicit execution limit."""

        if type(self.ordinal) is not int or self.ordinal < 0:
            raise ValueError("order ordinal must be a non-negative integer")
        _require_token(self.asset_code, "asset_code", maximum=32)
        _require_token(self.security_id, "security_id")
        _require_token(self.asset_type, "asset_type", maximum=20)
        _require_digest(self.classification_content_hash, "classification_content_hash")
        _require_token(self.quantity_unit, "quantity_unit")
        _require_token(self.money_unit, "money_unit")
        if self.approved_limit_price is not None:
            _require_decimal(self.approved_limit_price, "approved_limit_price")
            if self.approved_limit_price <= 0:
                raise ValueError("approved_limit_price must be positive")

    def to_payload(self) -> dict[str, object]:
        """Return exact, server-resolved order identity metadata."""

        return {
            "ordinal": self.ordinal,
            "asset_code": self.asset_code,
            "security_id": self.security_id,
            "asset_type": self.asset_type,
            "classification_content_hash": self.classification_content_hash,
            "quantity_unit": self.quantity_unit,
            "money_unit": self.money_unit,
            "approved_limit_price": _decimal_text(self.approved_limit_price),
        }


@dataclass(frozen=True, slots=True)
class TransitionPlanOrderBinding:
    """Immutable order identity, classification pin and approved terms within one revision."""

    ordinal: int
    order_content_hash: str
    plan_order_binding_id: str
    asset_code: str
    security_id: str
    asset_type: str
    classification_content_hash: str
    side: Literal["buy", "sell"]
    requested_quantity: int
    approved_quantity: int
    unapproved_quantity: int
    reference_price: Decimal
    estimated_fee: Decimal
    approved_limit_price: Decimal | None
    quantity_unit: str
    money_unit: str
    status: str
    reason_codes: tuple[str, ...]

    def __post_init__(self) -> None:
        """Validate approved quantities and keep reference prices informational."""

        if type(self.ordinal) is not int or self.ordinal < 0:
            raise ValueError("order ordinal must be a non-negative integer")
        _require_digest(self.order_content_hash, "order_content_hash")
        _require_digest(self.plan_order_binding_id, "plan_order_binding_id")
        _require_token(self.asset_code, "asset_code", maximum=32)
        _require_token(self.security_id, "security_id")
        _require_token(self.asset_type, "asset_type", maximum=20)
        _require_digest(self.classification_content_hash, "classification_content_hash")
        if self.side not in {"buy", "sell"}:
            raise ValueError("order side must be buy or sell")
        for name in ("requested_quantity", "approved_quantity", "unapproved_quantity"):
            value = getattr(self, name)
            if type(value) is not int or value < 0:
                raise ValueError(f"{name} must be a non-negative integer")
        if self.requested_quantity != self.approved_quantity + self.unapproved_quantity:
            raise ValueError("requested order quantity must equal approved plus unapproved")
        _require_decimal(self.reference_price, "reference_price")
        if self.reference_price <= 0:
            raise ValueError("reference_price must be positive")
        _require_decimal(self.estimated_fee, "estimated_fee")
        if self.approved_limit_price is not None:
            _require_decimal(self.approved_limit_price, "approved_limit_price")
            if self.approved_limit_price <= 0:
                raise ValueError("approved_limit_price must be positive")
        _require_token(self.quantity_unit, "quantity_unit")
        _require_token(self.money_unit, "money_unit")
        _require_token(self.status, "status")
        for reason in self.reason_codes:
            _require_token(reason, "reason_code")

    def to_payload(self) -> dict[str, object]:
        """Return all approved terms; estimates are labeled and never executable prices."""

        return {
            "ordinal": self.ordinal,
            "order_content_hash": self.order_content_hash,
            "plan_order_binding_id": self.plan_order_binding_id,
            "asset_code": self.asset_code,
            "security_id": self.security_id,
            "asset_type": self.asset_type,
            "classification_content_hash": self.classification_content_hash,
            "side": self.side,
            "requested_quantity": self.requested_quantity,
            "approved_quantity": self.approved_quantity,
            "unapproved_quantity": self.unapproved_quantity,
            "reference_price": _decimal_text(self.reference_price),
            "reference_price_is_executable_limit": False,
            "estimated_fee": _decimal_text(self.estimated_fee),
            "estimated_fee_is_actual_fee": False,
            "approved_limit_price": _decimal_text(self.approved_limit_price),
            "quantity_unit": self.quantity_unit,
            "money_unit": self.money_unit,
            "status": self.status,
            "reason_codes": list(self.reason_codes),
        }

    def to_execution_binding(
        self,
        identity: TransitionPlanRevisionIdentity,
        *,
        owner_user_id: int,
        action_attempt_key: str,
    ) -> TransitionPlanOrderExecutionBinding:
        """Create one exact action link without granting execution permission."""

        if owner_user_id != identity.owner_user_id:
            raise ValueError("execution binding owner differs from the exact plan owner")
        return TransitionPlanOrderExecutionBinding(
            plan_id=identity.plan_id,
            family_id=identity.family_id,
            root_plan_id=identity.root_plan_id,
            plan_version=identity.version,
            revision_hash=identity.revision_hash,
            order_ordinal=self.ordinal,
            plan_order_binding_id=self.plan_order_binding_id,
            order_content_hash=self.order_content_hash,
            account_id=identity.account_id,
            owner_user_id=owner_user_id,
            action_attempt_key=action_attempt_key,
            asset_code=self.asset_code,
            security_id=self.security_id,
            asset_type=self.asset_type,
            classification_content_hash=self.classification_content_hash,
            side=self.side,
            approved_quantity=self.approved_quantity,
            approved_limit_price=self.approved_limit_price,
            quantity_unit=self.quantity_unit,
            money_unit=self.money_unit,
            plan_expires_at=identity.valid_until,
        )


@dataclass(frozen=True, slots=True)
class TransitionPlanRevisionIdentity:
    """Stable exact identity and lineage for one immutable transition-plan version."""

    plan_id: str
    family_id: str
    root_plan_id: str
    version: int
    parent_plan_id: str | None
    parent_version: int | None
    parent_revision_hash: str | None
    account_id: int
    owner_user_id: int
    transition_plan_hash: str
    revision_hash: str
    recorded_at: datetime
    valid_until: datetime

    def __post_init__(self) -> None:
        """Reject ambiguous parentage, nonpositive identity, and invalid clocks."""

        for name in ("plan_id", "family_id", "root_plan_id"):
            _require_token(getattr(self, name), name, maximum=64)
        if type(self.version) is not int or self.version <= 0:
            raise ValueError("version must be a positive integer")
        if type(self.account_id) is not int or self.account_id <= 0:
            raise ValueError("account_id must be a positive integer")
        if type(self.owner_user_id) is not int or self.owner_user_id <= 0:
            raise ValueError("owner_user_id must be a positive integer")
        _require_digest(self.transition_plan_hash, "transition_plan_hash")
        _require_digest(self.revision_hash, "revision_hash")
        _require_aware(self.recorded_at, "recorded_at")
        _require_aware(self.valid_until, "valid_until")
        initial = self.parent_plan_id is None
        if initial:
            if self.parent_version is not None or self.parent_revision_hash is not None:
                raise ValueError("initial revision cannot have partial parent identity")
            if self.version != 1 or self.root_plan_id != self.plan_id:
                raise ValueError("initial revision must be version one and its own root")
        else:
            _require_token(self.parent_plan_id, "parent_plan_id", maximum=64)
            if type(self.parent_version) is not int or self.parent_version != self.version - 1:
                raise ValueError("successor must point to the immediately preceding version")
            _require_digest(self.parent_revision_hash, "parent_revision_hash")
            if self.root_plan_id == self.plan_id:
                raise ValueError("successor cannot replace its family root identity")
        if self.recorded_at >= self.valid_until:
            raise ValueError("revision validity window is empty")

    def to_payload(self) -> dict[str, object]:
        """Return exact persisted identity, lineage, hashes, and validity clocks."""

        return {
            "plan_id": self.plan_id,
            "family_id": self.family_id,
            "root_plan_id": self.root_plan_id,
            "version": self.version,
            "parent_plan_id": self.parent_plan_id,
            "parent_version": self.parent_version,
            "parent_revision_hash": self.parent_revision_hash,
            "account_id": self.account_id,
            "owner_user_id": self.owner_user_id,
            "transition_plan_hash": self.transition_plan_hash,
            "revision_hash": self.revision_hash,
            "recorded_at": _datetime_text(self.recorded_at),
            "valid_until": _datetime_text(self.valid_until),
        }


@dataclass(frozen=True, slots=True)
class TransitionPlanRevision:
    """Full immutable plan revision with the evidence that made it trustworthy."""

    plan: TransitionPlan
    identity: TransitionPlanRevisionIdentity
    basis: TransitionPlanBasis
    orders: tuple[TransitionPlanOrderBinding, ...]

    def __post_init__(self) -> None:
        """Recompute all plan, basis, and revision hashes and check exact identities."""

        if type(self.plan) is not TransitionPlan:
            raise TypeError("plan must be an exact TransitionPlan")
        if self.plan.plan_id != self.identity.plan_id or self.plan.version != self.identity.version:
            raise ValueError("plan identity does not match revision identity")
        if (
            self.plan.account_id != str(self.identity.account_id)
            or self.basis.account_id != self.identity.account_id
        ):
            raise ValueError("plan account identity does not match its basis")
        if self.basis.owner_user_id != self.identity.owner_user_id:
            raise ValueError("plan owner identity does not match its basis")
        expected_legacy_policy_version = (
            self.basis.planning_policy.version
            if self.basis.planning_policy.status == "qualified"
            else "not_applicable"
        )
        if self.plan.metadata != {"planning_policy_version": expected_legacy_policy_version}:
            raise ValueError("canonical-v1 planning policy marker differs from the typed basis")
        if self.plan.decision_snapshot_id != self.basis.decision_snapshot_id:
            raise ValueError("plan decision snapshot does not match its basis")
        if self.plan.portfolio_snapshot_id != self.basis.portfolio_snapshot_id:
            raise ValueError("plan portfolio snapshot does not match its basis")
        if self.plan.target_portfolio_id != self.basis.target_portfolio_id:
            raise ValueError("plan target portfolio does not match its basis")
        if self.plan.as_of_time != self.basis.portfolio_snapshot_as_of:
            raise ValueError("plan as_of must preserve the portfolio source snapshot clock")
        source_deadlines = tuple(item.admission_until for item in self.basis.source_bindings)
        effective_deadlines = tuple(
            item.valid_until
            for item in (
                self.basis.planning_policy,
                self.basis.fee_policy,
                self.basis.quantity_rule,
                self.basis.settlement_rule,
                self.basis.execution_calendar,
            )
            if item.valid_until is not None
        )
        all_deadlines = (self.basis.valid_until, *source_deadlines, *effective_deadlines)
        if self.plan.expires_at > min(all_deadlines):
            raise ValueError("plan expiry cannot exceed the earliest exact source/policy cutoff")
        if self.identity.recorded_at != self.basis.prepared_at:
            raise ValueError("revision recorded_at must equal its server preparation cutoff")
        if self.identity.valid_until != min(self.plan.expires_at, self.basis.valid_until):
            raise ValueError("revision valid_until must be the earliest exact cutoff")
        if len(self.orders) != len(self.plan.orders):
            raise ValueError("every plan order must have one exact binding")
        if tuple(item.ordinal for item in self.orders) != tuple(range(len(self.orders))):
            raise ValueError("plan order bindings must follow exact zero-based ordinals")
        for binding, draft in zip(self.orders, self.plan.orders, strict=True):
            if (
                binding.order_content_hash != _order_payload_hash(self.plan, binding.ordinal)
                or binding.asset_code != draft.asset_code
                or binding.side != draft.side
                or binding.approved_quantity != draft.quantity
                or binding.unapproved_quantity != draft.remaining_quantity
                or binding.reference_price != draft.reference_price
                or binding.estimated_fee != draft.estimated_fee
                or binding.status != draft.status
                or binding.reason_codes != tuple(item.rule_code for item in draft.constraints)
                or binding.requested_quantity != draft.quantity + draft.remaining_quantity
            ):
                raise ValueError("order binding does not reproduce the canonical plan order")
        if transition_plan_content_hash_v1(self.plan) != self.identity.transition_plan_hash:
            raise ValueError("canonical transition-plan hash mismatch")
        if self._expected_plan_id() != self.identity.plan_id:
            raise ValueError("deterministic plan ID does not bind the complete basis")
        if self._expected_revision_hash() != self.identity.revision_hash:
            raise ValueError("full transition-plan revision hash mismatch")
        for order in self.orders:
            specification = TransitionPlanOrderSpecification(
                ordinal=order.ordinal,
                asset_code=order.asset_code,
                security_id=order.security_id,
                asset_type=order.asset_type,
                classification_content_hash=order.classification_content_hash,
                quantity_unit=order.quantity_unit,
                money_unit=order.money_unit,
                approved_limit_price=order.approved_limit_price,
            )
            if order.plan_order_binding_id != _binding_id(
                revision_hash=self.identity.revision_hash,
                order_content_hash=order.order_content_hash,
                specification=specification,
            ):
                raise ValueError("plan order binding ID does not match the full revision hash")

    def _expected_plan_id(self) -> str:
        """Recompute the content-derived plan ID used by inactive approval artifacts."""

        specifications = [
            {
                "ordinal": order.ordinal,
                "asset_code": order.asset_code,
                "security_id": order.security_id,
                "asset_type": order.asset_type,
                "classification_content_hash": order.classification_content_hash,
                "quantity_unit": order.quantity_unit,
                "money_unit": order.money_unit,
                "approved_limit_price": _decimal_text(order.approved_limit_price),
            }
            for order in self.orders
        ]
        return _canonical_hash(
            {
                "family_id": self.identity.family_id,
                "root_plan_id": (
                    self.identity.root_plan_id
                    if self.identity.parent_plan_id is not None
                    else "$SELF"
                ),
                "version": self.identity.version,
                "parent_plan_id": self.identity.parent_plan_id,
                "parent_version": self.identity.parent_version,
                "parent_revision_hash": self.identity.parent_revision_hash,
                "plan_payload_without_id": canonical_transition_plan_payload_v1(self.plan),
                "basis": self.basis.to_payload(),
                "order_specifications": specifications,
            }
        )

    def _expected_revision_hash(self) -> str:
        """Recompute the full basis digest independently from canonical-v1 plan bytes."""

        return _canonical_hash(
            {
                "identity": {
                    "plan_id": self.identity.plan_id,
                    "family_id": self.identity.family_id,
                    "root_plan_id": self.identity.root_plan_id,
                    "version": self.identity.version,
                    "parent_plan_id": self.identity.parent_plan_id,
                    "parent_version": self.identity.parent_version,
                    "parent_revision_hash": self.identity.parent_revision_hash,
                    "account_id": self.identity.account_id,
                    "owner_user_id": self.identity.owner_user_id,
                    "transition_plan_hash": self.identity.transition_plan_hash,
                    "recorded_at": _datetime_text(self.identity.recorded_at),
                    "valid_until": _datetime_text(self.identity.valid_until),
                },
                "basis": self.basis.to_payload(),
                "orders": [
                    {
                        key: value
                        for key, value in item.to_payload().items()
                        if key != "plan_order_binding_id"
                    }
                    for item in self.orders
                ],
            }
        )

    def to_payload(self) -> dict[str, object]:
        """Return the explicit public plan contract with original clock semantics."""

        return {
            "identity": self.identity.to_payload(),
            "status": self.plan.status,
            "transition_plan": canonical_transition_plan_payload_v1(self.plan),
            "basis": self.basis.to_payload(),
            "orders": [item.to_payload() for item in self.orders],
            "automatic_submission": False,
        }


@dataclass(frozen=True, slots=True)
class TransitionPlanOrderExecutionBinding:
    """Exact order, classification and approved terms attached to one action attempt."""

    plan_id: str
    family_id: str
    root_plan_id: str
    plan_version: int
    revision_hash: str
    order_ordinal: int
    plan_order_binding_id: str
    order_content_hash: str
    account_id: int
    owner_user_id: int
    action_attempt_key: str
    asset_code: str
    security_id: str
    asset_type: str
    classification_content_hash: str
    side: Literal["buy", "sell"]
    approved_quantity: int
    approved_limit_price: Decimal | None
    quantity_unit: str
    money_unit: str
    plan_expires_at: datetime

    def __post_init__(self) -> None:
        """Validate the exact plan, order, owner, quantity, and attempt identity."""

        for name in ("plan_id", "family_id", "root_plan_id", "action_attempt_key"):
            _require_token(getattr(self, name), name, maximum=128)
        for name in ("revision_hash", "plan_order_binding_id", "order_content_hash"):
            _require_digest(getattr(self, name), name)
        if type(self.plan_version) is not int or self.plan_version <= 0:
            raise ValueError("plan_version must be a positive integer")
        if type(self.order_ordinal) is not int or self.order_ordinal < 0:
            raise ValueError("order_ordinal must be a non-negative integer")
        if type(self.account_id) is not int or self.account_id <= 0:
            raise ValueError("account_id must be a positive integer")
        if type(self.owner_user_id) is not int or self.owner_user_id <= 0:
            raise ValueError("owner_user_id must be a positive integer")
        _require_token(self.asset_code, "asset_code", maximum=32)
        _require_token(self.security_id, "security_id")
        _require_token(self.asset_type, "asset_type", maximum=20)
        _require_digest(self.classification_content_hash, "classification_content_hash")
        if self.side not in {"buy", "sell"}:
            raise ValueError("side must be buy or sell")
        if type(self.approved_quantity) is not int or self.approved_quantity < 0:
            raise ValueError("approved_quantity must be a non-negative integer")
        if self.approved_limit_price is not None:
            _require_decimal(self.approved_limit_price, "approved_limit_price")
            if self.approved_limit_price <= 0:
                raise ValueError("approved_limit_price must be positive")
        _require_token(self.quantity_unit, "quantity_unit")
        _require_token(self.money_unit, "money_unit")
        _require_aware(self.plan_expires_at, "plan_expires_at")

    def to_payload(self) -> dict[str, object]:
        """Return the typed reservation-link payload with unchanged plan semantics."""

        return {
            "plan_id": self.plan_id,
            "family_id": self.family_id,
            "root_plan_id": self.root_plan_id,
            "plan_version": self.plan_version,
            "revision_hash": self.revision_hash,
            "order_ordinal": self.order_ordinal,
            "plan_order_binding_id": self.plan_order_binding_id,
            "order_content_hash": self.order_content_hash,
            "account_id": self.account_id,
            "owner_user_id": self.owner_user_id,
            "action_attempt_key": self.action_attempt_key,
            "asset_code": self.asset_code,
            "security_id": self.security_id,
            "asset_type": self.asset_type,
            "classification_content_hash": self.classification_content_hash,
            "side": self.side,
            "approved_quantity": self.approved_quantity,
            "approved_limit_price": _decimal_text(self.approved_limit_price),
            "quantity_unit": self.quantity_unit,
            "money_unit": self.money_unit,
            "plan_expires_at": _datetime_text(self.plan_expires_at),
            "reference_price_is_executable_limit": False,
            "estimated_fee_is_actual_fee": False,
        }

    @property
    def content_hash(self) -> str:
        """Return a digest of this one exact order-action binding."""

        return _canonical_hash(self.to_payload())


@dataclass(frozen=True, slots=True)
class TransitionPlanRevisionPreparation:
    """Server-only facts and order identity supplied by a trusted preparation bridge."""

    plan: TransitionPlan
    basis: TransitionPlanBasis
    family_id: str
    root_plan_id: str | None
    version: int
    parent_plan_id: str | None
    parent_version: int | None
    parent_revision_hash: str | None
    order_specifications: tuple[TransitionPlanOrderSpecification, ...]

    def __post_init__(self) -> None:
        """Reject incomplete lineage before deterministic revision identity creation."""

        _require_token(self.family_id, "family_id", maximum=64)
        if type(self.version) is not int or self.version <= 0:
            raise ValueError("version must be a positive integer")
        if self.parent_plan_id is None:
            if self.parent_version is not None or self.parent_revision_hash is not None:
                raise ValueError("initial revision cannot have partial parent identity")
            if self.version != 1 or self.root_plan_id is not None:
                raise ValueError("initial revision must be version one with no supplied root")
        else:
            _require_token(self.parent_plan_id, "parent_plan_id", maximum=64)
            if self.parent_version != self.version - 1:
                raise ValueError("successor must name the immediately preceding parent version")
            _require_digest(self.parent_revision_hash, "parent_revision_hash")
            _require_token(self.root_plan_id, "root_plan_id", maximum=64)
        ordinals = tuple(item.ordinal for item in self.order_specifications)
        if ordinals != tuple(range(len(ordinals))) or len(ordinals) != len(set(ordinals)):
            raise ValueError("order specifications must cover contiguous exact ordinals")
        if len(self.order_specifications) != len(self.plan.orders):
            raise ValueError("every proposed plan order requires a server-resolved identity")


def _specification_payloads(
    specifications: tuple[TransitionPlanOrderSpecification, ...],
) -> list[dict[str, object]]:
    """Build deterministic identity input for exact ordinal and security bindings."""

    return [item.to_payload() for item in specifications]


def _order_payload_hash(plan: TransitionPlan, ordinal: int) -> str:
    """Hash exactly the canonical-v1 order row expected by the active-order reader."""

    payload = canonical_transition_plan_payload_v1(plan)
    orders = payload.get("orders")
    if type(orders) is not list or ordinal >= len(orders):
        raise ValueError("canonical plan order ordinal is unavailable")
    order_payload = orders[ordinal]
    if type(order_payload) is not dict:
        raise ValueError("canonical plan order row is malformed")
    return _canonical_hash(order_payload)


def _binding_id(
    *,
    revision_hash: str,
    order_content_hash: str,
    specification: TransitionPlanOrderSpecification,
) -> str:
    """Bind one canonical order row to its exact security and approved quantities."""

    return _canonical_hash(
        {
            "revision_hash": revision_hash,
            "ordinal": specification.ordinal,
            "order_content_hash": order_content_hash,
            "asset_code": specification.asset_code,
            "security_id": specification.security_id,
            "asset_type": specification.asset_type,
            "classification_content_hash": specification.classification_content_hash,
            "quantity_unit": specification.quantity_unit,
            "money_unit": specification.money_unit,
            "approved_limit_price": _decimal_text(specification.approved_limit_price),
        }
    )


def build_transition_plan_revision(
    preparation: TransitionPlanRevisionPreparation,
) -> TransitionPlanRevision:
    """Seal a trusted server preparation without changing canonical-v1 plan bytes."""

    if type(preparation) is not TransitionPlanRevisionPreparation:
        raise TypeError("preparation must be an exact trusted plan preparation")
    plan = replace(preparation.plan, plan_id="", version=preparation.version)
    if plan.account_id != str(preparation.basis.account_id):
        raise ValueError("prepared plan account differs from trusted basis")
    if plan.decision_snapshot_id != preparation.basis.decision_snapshot_id:
        raise ValueError("prepared plan decision differs from trusted basis")
    if plan.portfolio_snapshot_id != preparation.basis.portfolio_snapshot_id:
        raise ValueError("prepared plan snapshot differs from trusted basis")
    if plan.target_portfolio_id != preparation.basis.target_portfolio_id:
        raise ValueError("prepared plan target differs from trusted basis")
    for order, specification in zip(plan.orders, preparation.order_specifications, strict=True):
        if order.asset_code != specification.asset_code:
            raise ValueError("order specification asset does not match the exact plan order")
        if order.side != "buy" and order.side != "sell":
            raise ValueError("plan order side is invalid")
        matching_sources = tuple(
            source
            for source in preparation.basis.source_bindings
            if source.asset_code == specification.asset_code
            and source.security_id == specification.security_id
        )
        if not matching_sources:
            raise ValueError("plan order security has no exact qualified source binding")
        if specification.money_unit != preparation.basis.money_unit:
            raise ValueError("order money unit differs from the account ledger unit")
    plan_payload = canonical_transition_plan_payload_v1(plan)
    id_input = {
        "family_id": preparation.family_id,
        "root_plan_id": preparation.root_plan_id or "$SELF",
        "version": preparation.version,
        "parent_plan_id": preparation.parent_plan_id,
        "parent_version": preparation.parent_version,
        "parent_revision_hash": preparation.parent_revision_hash,
        "plan_payload_without_id": plan_payload,
        "basis": preparation.basis.to_payload(),
        "order_specifications": _specification_payloads(preparation.order_specifications),
    }
    plan_id = _canonical_hash(id_input)
    if preparation.root_plan_id is not None and plan_id == preparation.root_plan_id:
        raise ValueError("successor cannot reuse its family root plan id")
    plan = replace(plan, plan_id=plan_id)
    plan_hash = transition_plan_content_hash_v1(plan)
    recorded_at = preparation.basis.prepared_at
    valid_until = min(plan.expires_at, preparation.basis.valid_until)
    root_plan_id: str | None
    if preparation.parent_plan_id is None:
        root_plan_id = plan_id
    else:
        root_plan_id = preparation.root_plan_id
    if root_plan_id is None:
        raise ValueError("trusted plan family root is unavailable")
    raw_orders: list[dict[str, object]] = []
    for specification in preparation.order_specifications:
        order = plan.orders[specification.ordinal]
        if order.quantity < 0 or order.remaining_quantity < 0:
            raise ValueError("plan order quantities cannot be negative")
        requested_quantity = order.quantity + order.remaining_quantity
        order_content_hash = _order_payload_hash(plan, specification.ordinal)
        raw_orders.append(
            {
                "ordinal": specification.ordinal,
                "order_content_hash": order_content_hash,
                "asset_code": specification.asset_code,
                "security_id": specification.security_id,
                "asset_type": specification.asset_type,
                "classification_content_hash": specification.classification_content_hash,
                "side": order.side,
                "requested_quantity": requested_quantity,
                "approved_quantity": order.quantity,
                "unapproved_quantity": order.remaining_quantity,
                "reference_price": _decimal_text(order.reference_price),
                "estimated_fee": _decimal_text(order.estimated_fee),
                "approved_limit_price": _decimal_text(specification.approved_limit_price),
                "quantity_unit": specification.quantity_unit,
                "money_unit": specification.money_unit,
                "status": order.status,
                "reason_codes": [constraint.rule_code for constraint in order.constraints],
                "reference_price_is_executable_limit": False,
                "estimated_fee_is_actual_fee": False,
            }
        )
    identity_payload = {
        "plan_id": plan_id,
        "family_id": preparation.family_id,
        "root_plan_id": root_plan_id,
        "version": preparation.version,
        "parent_plan_id": preparation.parent_plan_id,
        "parent_version": preparation.parent_version,
        "parent_revision_hash": preparation.parent_revision_hash,
        "account_id": preparation.basis.account_id,
        "owner_user_id": preparation.basis.owner_user_id,
        "transition_plan_hash": plan_hash,
        "recorded_at": _datetime_text(recorded_at),
        "valid_until": _datetime_text(valid_until),
    }
    revision_hash = _canonical_hash(
        {
            "identity": identity_payload,
            "basis": preparation.basis.to_payload(),
            "orders": raw_orders,
        }
    )
    bindings: list[TransitionPlanOrderBinding] = []
    for specification, raw in zip(preparation.order_specifications, raw_orders, strict=True):
        order = plan.orders[specification.ordinal]
        side: Literal["buy", "sell"]
        if order.side == "buy":
            side = "buy"
        elif order.side == "sell":
            side = "sell"
        else:
            raise ValueError("plan order side is invalid")
        order_content_hash = str(raw["order_content_hash"])
        bindings.append(
            TransitionPlanOrderBinding(
                ordinal=specification.ordinal,
                order_content_hash=order_content_hash,
                plan_order_binding_id=_binding_id(
                    revision_hash=revision_hash,
                    order_content_hash=order_content_hash,
                    specification=specification,
                ),
                asset_code=specification.asset_code,
                security_id=specification.security_id,
                asset_type=specification.asset_type,
                classification_content_hash=specification.classification_content_hash,
                side=side,
                requested_quantity=order.quantity + order.remaining_quantity,
                approved_quantity=order.quantity,
                unapproved_quantity=order.remaining_quantity,
                reference_price=order.reference_price,
                estimated_fee=order.estimated_fee,
                approved_limit_price=specification.approved_limit_price,
                quantity_unit=specification.quantity_unit,
                money_unit=specification.money_unit,
                status=order.status,
                reason_codes=tuple(constraint.rule_code for constraint in order.constraints),
            )
        )
    identity = TransitionPlanRevisionIdentity(
        plan_id=plan_id,
        family_id=preparation.family_id,
        root_plan_id=root_plan_id,
        version=preparation.version,
        parent_plan_id=preparation.parent_plan_id,
        parent_version=preparation.parent_version,
        parent_revision_hash=preparation.parent_revision_hash,
        account_id=preparation.basis.account_id,
        owner_user_id=preparation.basis.owner_user_id,
        transition_plan_hash=plan_hash,
        revision_hash=revision_hash,
        recorded_at=recorded_at,
        valid_until=valid_until,
    )
    return TransitionPlanRevision(
        plan=plan,
        identity=identity,
        basis=preparation.basis,
        orders=tuple(bindings),
    )


__all__ = [
    "ObservationPrecision",
    "PlanOutcome",
    "TransitionPlanBasis",
    "TransitionPlanOrderBinding",
    "TransitionPlanOrderExecutionBinding",
    "TransitionPlanOrderSpecification",
    "TransitionPlanPolicyBinding",
    "TransitionPlanPositionBinding",
    "TransitionPlanRevision",
    "TransitionPlanRevisionIdentity",
    "TransitionPlanRevisionPreparation",
    "TransitionPlanRiskBinding",
    "TransitionPlanSourceBinding",
    "build_transition_plan_revision",
]
