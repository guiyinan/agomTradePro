"""Business-boundary tests for sealed transition-plan revisions and evidence."""

from __future__ import annotations

import json
from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Literal, cast

import pytest

from apps.portfolio.domain.entities import TransitionPlan
from apps.portfolio.domain.transition_plan_revision import (
    TransitionPlanOrderSpecification,
    TransitionPlanRevision,
    TransitionPlanRevisionPreparation,
    _order_payload_hash,
    build_transition_plan_revision,
)
from apps.portfolio.domain.transition_plan_revision_basis import (
    ObservationPrecision,
    PlanOutcome,
    TransitionPlanPolicyBinding,
    TransitionPlanPositionBinding,
)
from apps.portfolio.domain.transition_plan_revision_support import _canonical_hash
from tests.unit.portfolio.test_transition_plan_revision_asset_identity import (
    _HASH_A,
    _HASH_B,
    _NOW,
    _preparation,
    _revision,
)


def _sealed_revision() -> TransitionPlanRevision:
    """Return the existing complete, self-consistent synthetic owner revision."""

    return cast(TransitionPlanRevision, _revision())


def _document(revision: TransitionPlanRevision) -> dict[str, object]:
    """Decode the retained canonical evidence for one precise tamper case."""

    return cast(dict[str, object], json.loads(revision.basis.preparation_evidence_json))


def _canonical_json(document: dict[str, object]) -> str:
    """Encode a document exactly as the persisted evidence contract requires."""

    return json.dumps(
        document,
        allow_nan=False,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def test_order_terms_and_execution_binding_reject_unapproved_financial_values() -> None:
    """Keep estimates informational and reject invalid limits, totals, or owner scope."""

    revision = _sealed_revision()
    order = revision.orders[0]
    with pytest.raises(ValueError, match="approved plus unapproved"):
        replace(order, requested_quantity=101)
    with pytest.raises(ValueError, match="order ordinal must be a non-negative integer"):
        replace(order, ordinal=-1)
    with pytest.raises(ValueError, match="order side must be buy or sell"):
        replace(order, side=cast(Literal["buy", "sell"], "hold"))
    with pytest.raises(ValueError, match="approved_quantity must be a non-negative integer"):
        replace(order, approved_quantity=-1)
    with pytest.raises(ValueError, match="reference_price must be positive"):
        replace(order, reference_price=Decimal("0"))
    with pytest.raises(ValueError, match="estimated_fee must be a finite Decimal"):
        replace(order, estimated_fee=Decimal("NaN"))
    with pytest.raises(ValueError, match="estimated_fee must be non-negative"):
        replace(order, estimated_fee=Decimal("-0.01"))
    with pytest.raises(ValueError, match="approved_limit_price must be positive"):
        replace(order, approved_limit_price=Decimal("0"))
    with pytest.raises(ValueError, match="execution binding owner differs"):
        order.to_execution_binding(
            revision.identity,
            owner_user_id=24,
            action_attempt_key="attempt-1",
        )

    binding = order.to_execution_binding(
        revision.identity,
        owner_user_id=revision.identity.owner_user_id,
        action_attempt_key="attempt-1",
    )
    with pytest.raises(ValueError, match="approved_quantity must be a non-negative integer"):
        replace(binding, approved_quantity=-1)
    with pytest.raises(ValueError, match="plan_expires_at must be timezone-aware"):
        replace(binding, plan_expires_at=datetime(2026, 11, 5, 10, 0))
    assert binding.to_payload()["reference_price_is_executable_limit"] is False
    assert binding.to_payload()["estimated_fee_is_actual_fee"] is False

    with pytest.raises(ValueError, match="asset_code must be a bounded canonical token"):
        TransitionPlanOrderSpecification(
            ordinal=0,
            asset_code="600000.SH ",
            security_id="SH.TEST.600000",
            asset_type="equity",
            classification_content_hash=_HASH_A,
            quantity_unit="share",
            money_unit="CNY",
        )
    with pytest.raises(ValueError, match="order ordinal must be a non-negative integer"):
        TransitionPlanOrderSpecification(
            ordinal=-1,
            asset_code="600000.SH",
            security_id="SH.TEST.600000",
            asset_type="equity",
            classification_content_hash=_HASH_A,
            quantity_unit="share",
            money_unit="CNY",
        )
    with pytest.raises(ValueError, match="approved_limit_price must be positive"):
        TransitionPlanOrderSpecification(
            ordinal=0,
            asset_code="600000.SH",
            security_id="SH.TEST.600000",
            asset_type="equity",
            classification_content_hash=_HASH_A,
            quantity_unit="share",
            money_unit="CNY",
            approved_limit_price=Decimal("0"),
        )
    with pytest.raises(ValueError, match="side must be buy or sell"):
        replace(binding, side=cast(Literal["buy", "sell"], "hold"))
    with pytest.raises(ValueError, match="approved_limit_price must be positive"):
        replace(binding, approved_limit_price=Decimal("0"))


def test_revision_identity_rejects_invalid_owner_parentage_and_expiry() -> None:
    """A revision must stay attached to one owner and an unambiguous family lineage."""

    identity = _sealed_revision().identity
    with pytest.raises(ValueError, match="version must be a positive integer"):
        replace(identity, version=0)
    with pytest.raises(ValueError, match="account_id must be a positive integer"):
        replace(identity, account_id=0)
    with pytest.raises(ValueError, match="owner_user_id must be a positive integer"):
        replace(identity, owner_user_id=0)
    with pytest.raises(ValueError, match="partial parent identity"):
        replace(identity, parent_version=0)
    with pytest.raises(ValueError, match="version one and its own root"):
        replace(identity, version=2)
    with pytest.raises(ValueError, match="immediately preceding version"):
        replace(
            identity,
            version=2,
            root_plan_id="family-root",
            parent_plan_id="parent-plan",
            parent_version=0,
            parent_revision_hash=_HASH_A,
        )
    with pytest.raises(ValueError, match="cannot replace its family root"):
        replace(
            identity,
            version=2,
            root_plan_id=identity.plan_id,
            parent_plan_id="parent-plan",
            parent_version=1,
            parent_revision_hash=_HASH_A,
        )
    with pytest.raises(ValueError, match="validity window is empty"):
        replace(identity, valid_until=identity.recorded_at)


def test_revision_rejects_cross_account_clock_and_order_binding_tampering() -> None:
    """A recomputable hash cannot authorize a different account or altered order."""

    revision = _sealed_revision()
    with pytest.raises(ValueError, match="plan account identity"):
        replace(revision, identity=replace(revision.identity, account_id=18))
    with pytest.raises(ValueError, match="plan owner identity"):
        replace(revision, identity=replace(revision.identity, owner_user_id=24))
    with pytest.raises(ValueError, match="recorded_at must equal"):
        replace(
            revision,
            identity=replace(
                revision.identity,
                recorded_at=revision.identity.recorded_at + timedelta(seconds=1),
            ),
        )
    with pytest.raises(ValueError, match="canonical-v1 planning policy marker"):
        replace(
            revision,
            plan=replace(revision.plan, metadata={"planning_policy_version": "invented"}),
        )
    with pytest.raises(ValueError, match="transition-plan hash mismatch"):
        replace(revision, identity=replace(revision.identity, transition_plan_hash=_HASH_B))
    with pytest.raises(ValueError, match="deterministic plan ID"):
        replace(revision, identity=replace(revision.identity, family_id="different-family"))
    with pytest.raises(ValueError, match="revision hash"):
        replace(revision, identity=replace(revision.identity, revision_hash=_HASH_B))

    original_order = revision.orders[0]
    with pytest.raises(ValueError, match="canonical plan order"):
        replace(
            revision,
            orders=(replace(original_order, approved_quantity=99, unapproved_quantity=1),),
        )
    with pytest.raises(ValueError, match="binding ID does not match"):
        replace(revision, orders=(replace(original_order, plan_order_binding_id=_HASH_B),))
    with pytest.raises(TypeError, match="exact TransitionPlan"):
        replace(revision, plan=cast(TransitionPlan, object()))
    with pytest.raises(ValueError, match="plan identity does not match"):
        replace(revision, plan=replace(revision.plan, plan_id="different-plan"))
    with pytest.raises(ValueError, match="decision snapshot does not match"):
        replace(revision, plan=replace(revision.plan, decision_snapshot_id="different-decision"))
    with pytest.raises(ValueError, match="portfolio snapshot does not match"):
        replace(revision, plan=replace(revision.plan, portfolio_snapshot_id="different-ledger"))
    with pytest.raises(ValueError, match="target portfolio does not match"):
        replace(revision, plan=replace(revision.plan, target_portfolio_id="different-target"))
    with pytest.raises(ValueError, match="as_of must preserve"):
        replace(
            revision,
            plan=replace(
                revision.plan,
                as_of_time=revision.plan.as_of_time + timedelta(seconds=1),
            ),
        )
    with pytest.raises(ValueError, match="expiry cannot exceed"):
        replace(
            revision,
            plan=replace(
                revision.plan,
                expires_at=revision.basis.valid_until + timedelta(seconds=1),
            ),
        )
    with pytest.raises(ValueError, match="earliest exact cutoff"):
        replace(
            revision,
            identity=replace(
                revision.identity,
                valid_until=revision.identity.valid_until - timedelta(seconds=1),
            ),
        )
    with pytest.raises(ValueError, match="every plan order"):
        replace(revision, orders=())
    with pytest.raises(ValueError, match="zero-based ordinals"):
        replace(revision, orders=(replace(original_order, ordinal=1),))
    with pytest.raises(ValueError, match="canonical plan order"):
        replace(revision, orders=(replace(original_order, reason_codes=("CHANGED",)),))


def test_preparation_builder_requires_exact_source_asset_and_ledger_unit() -> None:
    """The trusted preparation must match every proposed order to its pinned security."""

    revision = _sealed_revision()
    preparation = _preparation(revision, idempotency_key="coverage-preparation")
    specification = preparation.order_specifications[0]
    with pytest.raises(ValueError, match="asset does not match"):
        build_transition_plan_revision(
            replace(
                preparation,
                order_specifications=(replace(specification, asset_code="601398.SH"),),
            )
        )
    with pytest.raises(ValueError, match="no exact qualified source binding"):
        build_transition_plan_revision(
            replace(
                preparation,
                order_specifications=(replace(specification, security_id="SH.OTHER"),),
            )
        )
    with pytest.raises(ValueError, match="money unit differs"):
        build_transition_plan_revision(
            replace(
                preparation,
                order_specifications=(replace(specification, money_unit="USD"),),
            )
        )
    with pytest.raises(ValueError, match="account differs"):
        build_transition_plan_revision(
            replace(preparation, plan=replace(preparation.plan, account_id="18"))
        )
    with pytest.raises(ValueError, match="decision differs"):
        build_transition_plan_revision(
            replace(
                preparation,
                plan=replace(preparation.plan, decision_snapshot_id="different-decision"),
            )
        )
    with pytest.raises(ValueError, match="snapshot differs"):
        build_transition_plan_revision(
            replace(
                preparation,
                plan=replace(preparation.plan, portfolio_snapshot_id="different-snapshot"),
            )
        )
    with pytest.raises(ValueError, match="target differs"):
        build_transition_plan_revision(
            replace(
                preparation,
                plan=replace(preparation.plan, target_portfolio_id="different-target"),
            )
        )
    invalid_side_plan = replace(
        preparation.plan,
        orders=(replace(preparation.plan.orders[0], side="hold"),),
    )
    with pytest.raises(ValueError, match="plan order side is invalid"):
        build_transition_plan_revision(replace(preparation, plan=invalid_side_plan))
    negative_quantity_plan = replace(
        preparation.plan,
        orders=(replace(preparation.plan.orders[0], quantity=-1),),
    )
    with pytest.raises(ValueError, match="plan order quantities cannot be negative"):
        build_transition_plan_revision(replace(preparation, plan=negative_quantity_plan))
    with pytest.raises(TypeError, match="preparation must be an exact"):
        build_transition_plan_revision(cast(TransitionPlanRevisionPreparation, {}))
    with pytest.raises(ValueError, match="canonical plan order ordinal is unavailable"):
        _order_payload_hash(revision.plan, len(revision.plan.orders))


def test_preparation_lineage_and_order_specifications_are_complete() -> None:
    """Initial and successor inputs carry one complete, contiguous parent chain."""

    revision = _sealed_revision()
    preparation = _preparation(revision, idempotency_key="coverage-lineage")
    with pytest.raises(ValueError, match="family_id must be a bounded canonical token"):
        replace(preparation, family_id=" invalid")
    with pytest.raises(ValueError, match="version must be a positive integer"):
        replace(preparation, version=0)
    with pytest.raises(ValueError, match="partial parent identity"):
        replace(preparation, parent_version=0)
    with pytest.raises(ValueError, match="version one with no supplied root"):
        replace(preparation, version=2)
    with pytest.raises(ValueError, match="immediately preceding parent version"):
        replace(
            preparation,
            version=2,
            root_plan_id="family-root",
            parent_plan_id="parent-plan",
            parent_version=0,
            parent_revision_hash=_HASH_A,
        )
    with pytest.raises(ValueError, match="parent_revision_hash must be"):
        replace(
            preparation,
            version=2,
            root_plan_id="family-root",
            parent_plan_id="parent-plan",
            parent_version=1,
            parent_revision_hash=None,
        )
    with pytest.raises(ValueError, match="contiguous exact ordinals"):
        replace(
            preparation,
            order_specifications=(replace(preparation.order_specifications[0], ordinal=1),),
        )
    with pytest.raises(ValueError, match="every proposed plan order"):
        replace(preparation, order_specifications=())


def test_date_precision_keeps_source_date_and_unknown_vendor_clocks_uninvented() -> None:
    """Date-only evidence stays date-only and missing vendor clocks need proof."""

    source = _sealed_revision().basis.source_bindings[0]
    date_source = replace(
        source,
        observation_precision=cast(ObservationPrecision, "date"),
        observed_at=None,
        observed_on=date(2026, 11, 5),
        available_at=None,
        known_at=None,
        decision_date_cutoff=date(2026, 11, 5),
        source_valid_until=None,
        qualification_proof_hash=_HASH_B,
    )
    assert date_source.observed_on == date(2026, 11, 5)
    assert date_source.observed_at is None
    assert date_source.available_at is None
    assert date_source.known_at is None
    assert date_source.to_payload()["observed_on"] == "2026-11-05"
    assert date_source.to_payload()["observed_at"] is None

    with pytest.raises(ValueError, match="observation date follows"):
        replace(date_source, observed_on=date(2026, 11, 6))
    with pytest.raises(ValueError, match="date-precision source requires"):
        replace(date_source, observed_on=cast(date, datetime(2026, 11, 5, tzinfo=UTC)))
    with pytest.raises(ValueError, match="date source requires date cutoff"):
        replace(date_source, decision_date_cutoff=None)
    with pytest.raises(ValueError, match="missing source clocks require"):
        replace(date_source, qualification_proof_hash=None)
    with pytest.raises(ValueError, match="available_at follows"):
        replace(date_source, available_at=_NOW + timedelta(seconds=1))
    with pytest.raises(ValueError, match="timestamp source cannot also claim"):
        replace(source, observed_on=date(2026, 11, 5))
    with pytest.raises(ValueError, match="source is expired"):
        replace(date_source, source_valid_until=_NOW)
    with pytest.raises(ValueError, match="admission has expired"):
        replace(date_source, admission_until=_NOW)
    with pytest.raises(ValueError, match="does not permit its requested"):
        replace(date_source, requested_purpose="order_submission")
    with pytest.raises(ValueError, match="unqualified source"):
        replace(date_source, qualified=False)


def test_policy_position_and_risk_contracts_preserve_unknown_without_approving_it() -> None:
    """Unknown position values remain null while missing rules and risk block a plan."""

    revision = _sealed_revision()
    basis = revision.basis
    unknown_position = TransitionPlanPositionBinding(
        asset_code="600000.SH",
        security_id="SH.TEST.600000",
        quantity=None,
        available_quantity=None,
        target_weight=None,
        target_quantity=None,
        reference_price=None,
        market_value=None,
        quantity_unit="share",
        money_unit="CNY",
        source_binding_hashes=(_HASH_A,),
    )
    assert unknown_position.to_payload()["quantity"] is None
    assert unknown_position.to_payload()["available_quantity"] is None
    assert unknown_position.to_payload()["market_value"] is None
    with pytest.raises(ValueError, match="available quantity cannot exceed"):
        replace(unknown_position, quantity=Decimal("10"), available_quantity=Decimal("11"))
    with pytest.raises(ValueError, match="target_weight cannot exceed one"):
        replace(unknown_position, target_weight=Decimal("1.01"))

    with pytest.raises(ValueError, match="qualified policy binding cannot have"):
        replace(basis.fee_policy, reason_code="not-proved")
    with pytest.raises(ValueError, match="not-applicable policy cannot carry"):
        replace(basis.fee_policy, status="not_applicable")
    with pytest.raises(ValueError, match="unknown policy binding"):
        replace(
            basis.fee_policy,
            status=cast(Literal["qualified", "not_applicable", "unknown"], "unknown"),
        )
    with pytest.raises(ValueError, match="valid_until must follow effective_at"):
        replace(basis.fee_policy, valid_until=basis.fee_policy.effective_at)
    with pytest.raises(ValueError, match="only qualified risk evidence"):
        replace(basis.risk, outcome=cast(PlanOutcome, "unknown"))


def test_basis_rejects_duplicate_source_and_position_identity_rows() -> None:
    """Persisted evidence cannot repeat a security under ambiguous source or position rows."""

    revision = _sealed_revision()
    basis = revision.basis
    source = basis.source_bindings[0]
    duplicate_sources = (source, source)
    document = _document(revision)
    document["source_bindings"] = [source.to_payload(), source.to_payload()]
    source_hash = _canonical_hash({"source_bindings": document["source_bindings"]})
    portfolio = cast(dict[str, object], document["portfolio_snapshot"])
    portfolio["source_evidence_hash"] = source_hash
    with pytest.raises(ValueError, match="source bindings must be unique"):
        replace(
            basis,
            source_bindings=duplicate_sources,
            portfolio_source_evidence_hash=source_hash,
            preparation_evidence_json=_canonical_json(document),
        )

    position = TransitionPlanPositionBinding(
        asset_code="600000.SH",
        security_id="SH.TEST.600000",
        quantity=Decimal("100"),
        available_quantity=Decimal("100"),
        target_weight=Decimal("1"),
        target_quantity=Decimal("100"),
        reference_price=Decimal("10"),
        market_value=Decimal("1000"),
        quantity_unit="share",
        money_unit="CNY",
        source_binding_hashes=(source.manifest_sha256,),
    )
    document = _document(revision)
    positions = cast(dict[str, object], document["positions"])
    positions["current"] = [position.to_payload(), position.to_payload()]
    with pytest.raises(ValueError, match="contains duplicate security identities"):
        replace(
            basis,
            current_positions=(position, position),
            preparation_evidence_json=_canonical_json(document),
        )


def test_embedded_evidence_hashes_bind_sources_risk_and_canonical_json() -> None:
    """Embedded resource, source, and risk changes cannot be detached from their pins."""

    revision = _sealed_revision()
    basis = revision.basis

    with pytest.raises(ValueError, match="valid JSON"):
        replace(basis, preparation_evidence_json="{")
    with pytest.raises(ValueError, match="JSON object"):
        replace(basis, preparation_evidence_json="[]")
    with pytest.raises(ValueError, match="canonical JSON"):
        replace(basis, preparation_evidence_json=basis.preparation_evidence_json + " ")

    document = _document(revision)
    document["extra"] = "unrecognized"
    with pytest.raises(ValueError, match="schema is invalid"):
        replace(basis, preparation_evidence_json=_canonical_json(document))

    document = _document(revision)
    document["portfolio_snapshot"] = None
    with pytest.raises(ValueError, match="portfolio_snapshot must be a JSON object"):
        replace(basis, preparation_evidence_json=_canonical_json(document))

    document = _document(revision)
    portfolio = cast(dict[str, object], document["portfolio_snapshot"])
    resources = cast(dict[str, object], portfolio["resources"])
    resources["cash"] = "9999"
    with pytest.raises(ValueError, match="portfolio resources do not match"):
        replace(basis, preparation_evidence_json=_canonical_json(document))

    document = _document(revision)
    document["source_bindings"] = []
    with pytest.raises(ValueError, match="source bindings differ"):
        replace(basis, preparation_evidence_json=_canonical_json(document))

    document = _document(revision)
    target = cast(dict[str, object], document["target"])
    target["selection_hash"] = _HASH_B
    with pytest.raises(ValueError, match="target does not match"):
        replace(basis, preparation_evidence_json=_canonical_json(document))

    document = _document(revision)
    decision = cast(dict[str, object], document["decision_snapshot"])
    decision_payload = cast(dict[str, object], decision["payload"])
    decision_payload["selection_hash"] = _HASH_B
    with pytest.raises(ValueError, match="decision does not match"):
        replace(basis, preparation_evidence_json=_canonical_json(document))

    document = _document(revision)
    document["decision_snapshot"] = None
    with pytest.raises(ValueError, match="decision_snapshot must be a JSON object"):
        replace(basis, preparation_evidence_json=_canonical_json(document))

    document = _document(revision)
    decision = cast(dict[str, object], document["decision_snapshot"])
    decision["payload"] = None
    with pytest.raises(ValueError, match="decision payload must be a JSON object"):
        replace(basis, preparation_evidence_json=_canonical_json(document))

    document = _document(revision)
    decision = cast(dict[str, object], document["decision_snapshot"])
    decision["id"] = _HASH_B
    with pytest.raises(ValueError, match="decision does not match"):
        replace(basis, preparation_evidence_json=_canonical_json(document))

    document = _document(revision)
    decision = cast(dict[str, object], document["decision_snapshot"])
    decision["content_hash"] = _HASH_B
    with pytest.raises(ValueError, match="decision does not match"):
        replace(basis, preparation_evidence_json=_canonical_json(document))

    document = _document(revision)
    policy_bindings = cast(dict[str, object], document["policy_bindings"])
    fee_policy = cast(dict[str, object], policy_bindings["fee_policy"])
    fee_policy["version"] = "unbound-version"
    with pytest.raises(ValueError, match="policy bindings differ"):
        replace(basis, preparation_evidence_json=_canonical_json(document))

    document = _document(revision)
    positions = cast(dict[str, object], document["positions"])
    positions["current"] = [{"asset_code": "600000.SH"}]
    with pytest.raises(ValueError, match="positions differ"):
        replace(basis, preparation_evidence_json=_canonical_json(document))

    document = _document(revision)
    document["business_date"] = "2026-11-06"
    with pytest.raises(ValueError, match="preparation clocks differ"):
        replace(basis, preparation_evidence_json=_canonical_json(document))

    wrong_source_hash = _HASH_B
    document = _document(revision)
    portfolio = cast(dict[str, object], document["portfolio_snapshot"])
    portfolio["source_evidence_hash"] = wrong_source_hash
    with pytest.raises(ValueError, match="does not authenticate its bindings"):
        replace(
            basis,
            portfolio_source_evidence_hash=wrong_source_hash,
            preparation_evidence_json=_canonical_json(document),
        )

    document = _document(revision)
    document["risk"] = replace(basis.risk, binding_hash="c" * 64).to_payload()
    with pytest.raises(ValueError, match="risk binding differs"):
        replace(basis, preparation_evidence_json=_canonical_json(document))

    empty_resources_document = _document(revision)
    portfolio = cast(dict[str, object], empty_resources_document["portfolio_snapshot"])
    portfolio["resources"] = None
    with pytest.raises(ValueError, match="portfolio resources must be a JSON object"):
        replace(basis, preparation_evidence_json=_canonical_json(empty_resources_document))

    positions_document = _document(revision)
    positions_document["positions"] = None
    with pytest.raises(ValueError, match="positions must be a JSON object"):
        replace(basis, preparation_evidence_json=_canonical_json(positions_document))


def test_basis_requires_fee_quantity_settlement_and_calendar_bindings() -> None:
    """A plan cannot be sealed when a required execution rule is explicitly unavailable."""

    revision = _sealed_revision()
    basis = revision.basis
    missing_fee = TransitionPlanPolicyBinding(
        kind="fee_policy",
        status="not_applicable",
        reference_id=None,
        version=None,
        content_hash=None,
        effective_at=None,
        known_at=None,
        valid_until=None,
        reason_code="fee_policy_not_available",
    )
    document = _document(revision)
    policy_bindings = cast(dict[str, object], document["policy_bindings"])
    policy_bindings["fee_policy"] = missing_fee.to_payload()
    with pytest.raises(ValueError, match="fee_policy is required to qualify a plan"):
        replace(
            basis,
            fee_policy=missing_fee,
            preparation_evidence_json=_canonical_json(document),
        )


def test_basis_enforces_owner_clock_and_rule_qualification_at_preparation() -> None:
    """A sealed plan needs scoped account identity and rules known at its real cutoff."""

    revision = _sealed_revision()
    basis = revision.basis
    with pytest.raises(ValueError, match="account_id must be a positive integer"):
        replace(basis, account_id=0)
    with pytest.raises(ValueError, match="owner_user_id must be a positive integer"):
        replace(basis, owner_user_id=0)
    with pytest.raises(ValueError, match="requested_by_user_id must be a positive integer"):
        replace(basis, requested_by_user_id=0)
    with pytest.raises(ValueError, match="money_unit must be a bounded canonical token"):
        replace(basis, money_unit=" CNY")
    with pytest.raises(ValueError, match="portfolio_snapshot_hash must be a lowercase"):
        replace(basis, portfolio_snapshot_hash="invalid")
    with pytest.raises(ValueError, match="prepared_at must be timezone-aware"):
        replace(basis, prepared_at=datetime(2026, 11, 5, 9, 30))
    with pytest.raises(ValueError, match="predates its portfolio snapshot"):
        replace(
            basis,
            prepared_at=basis.portfolio_snapshot_as_of - timedelta(seconds=1),
        )
    with pytest.raises(ValueError, match="expired at preparation time"):
        replace(basis, valid_until=basis.prepared_at)

    future_known_policy = replace(
        basis.fee_policy,
        known_at=basis.prepared_at + timedelta(seconds=1),
    )
    document = _document(revision)
    policies = cast(dict[str, object], document["policy_bindings"])
    policies["fee_policy"] = future_known_policy.to_payload()
    with pytest.raises(ValueError, match="not known and effective at preparation"):
        replace(
            basis,
            fee_policy=future_known_policy,
            preparation_evidence_json=_canonical_json(document),
        )

    expired_policy = replace(basis.fee_policy, valid_until=basis.prepared_at)
    document = _document(revision)
    policies = cast(dict[str, object], document["policy_bindings"])
    policies["fee_policy"] = expired_policy.to_payload()
    with pytest.raises(ValueError, match="policy is expired at preparation"):
        replace(
            basis,
            fee_policy=expired_policy,
            preparation_evidence_json=_canonical_json(document),
        )


def test_basis_requires_sources_and_pure_business_dates() -> None:
    """A plan cannot turn a missing source or timestamp into a business date."""

    revision = _sealed_revision()
    basis = revision.basis
    document = _document(revision)
    document["source_bindings"] = []
    empty_source_hash = _canonical_hash({"source_bindings": []})
    portfolio = cast(dict[str, object], document["portfolio_snapshot"])
    portfolio["source_evidence_hash"] = empty_source_hash
    with pytest.raises(ValueError, match="explicit source bindings"):
        replace(
            basis,
            source_bindings=(),
            portfolio_source_evidence_hash=empty_source_hash,
            preparation_evidence_json=_canonical_json(document),
        )

    timestamp = datetime(2026, 11, 5, 9, 30, tzinfo=UTC)
    document = _document(revision)
    document["business_date"] = timestamp.isoformat()
    with pytest.raises(ValueError, match="business_date must be a date"):
        replace(
            basis,
            business_date=cast(date, timestamp),
            preparation_evidence_json=_canonical_json(document),
        )
    document = _document(revision)
    document["execution_session"] = timestamp.isoformat()
    with pytest.raises(ValueError, match="execution_session must be a date"):
        replace(
            basis,
            execution_session=cast(date, timestamp),
            preparation_evidence_json=_canonical_json(document),
        )
