"""Contract tests for source-resolved asset classification in revision bindings."""

from __future__ import annotations

import json
from contextlib import AbstractContextManager, nullcontext
from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace
from typing import cast

import pytest

from apps.portfolio.application.transition_plan_lifecycle import (
    CreateInitialTransitionPlanRevisionUseCase,
    CreateTransitionPlanSuccessorCommand,
    CreateTransitionPlanSuccessorUseCase,
    GetExactTransitionPlanRevisionQuery,
    GetExactTransitionPlanRevisionUseCase,
    RequestTransitionPlanRevisionReview,
    RequestTransitionPlanRevisionReviewUseCase,
    TransitionPlanRevisionBlocked,
    TransitionPlanRevisionConflict,
    TransitionPlanRevisionCorruption,
    TransitionPlanRevisionRequest,
)
from apps.portfolio.domain.entities import OrderDraft, TransitionPlan
from apps.portfolio.domain.transition_plan_revision import (
    TransitionPlanOrderSpecification,
    TransitionPlanRevision,
    TransitionPlanRevisionIdentity,
    TransitionPlanRevisionPreparation,
    build_transition_plan_revision,
)
from apps.portfolio.domain.transition_plan_revision_basis import (
    TransitionPlanBasis,
    TransitionPlanPolicyBinding,
    TransitionPlanRiskBinding,
    TransitionPlanSourceBinding,
)
from apps.portfolio.domain.transition_plan_revision_support import _canonical_hash
from apps.portfolio.infrastructure.transition_plan_revision_codec import (
    decode_transition_plan_revision,
    encode_transition_plan_revision,
)
from apps.portfolio.infrastructure.transition_plan_revision_repository import (
    DjangoTransitionPlanLockedActionGuard,
)

_NOW = datetime(2026, 11, 5, 9, 30, tzinfo=UTC)
_HASH_A = "a" * 64
_HASH_B = "b" * 64


class _NoReviewArtifacts:
    """Provide the existing read-only staff artifact port with no submitted artifacts."""

    def get_subject_winner(self, *, subject_id: str, subject_version: str, as_of: datetime) -> None:
        return None

    def get_receipt_winner(self, *, receipt_id: str, receipt_version: str, as_of: datetime) -> None:
        return None


class _PolicyPinReader:
    """Record mandatory current-policy revalidation without adding database behavior."""

    def __init__(self) -> None:
        self.checked_revision_hashes: list[str] = []

    def validate_current_policy_pins(
        self, checked: TransitionPlanRevision, *, as_of: datetime
    ) -> None:
        self.checked_revision_hashes.append(checked.identity.revision_hash)


class _RowQuery:
    """Return one exact plan row without opening a database connection."""

    def select_for_update(self) -> _RowQuery:
        return self

    def filter(self, **kwargs: object) -> _RowQuery:
        return self

    def first(self) -> SimpleNamespace:
        return SimpleNamespace(approval_request_id="")


def _policy(kind: str, *, valid_until: datetime) -> TransitionPlanPolicyBinding:
    """Build one explicit server-owned policy binding for the focused test."""

    return TransitionPlanPolicyBinding(
        kind=kind,
        status="qualified",
        reference_id=f"{kind}-ref",
        version="test-r1",
        content_hash=_HASH_A,
        effective_at=_NOW - timedelta(minutes=30),
        known_at=_NOW - timedelta(minutes=30),
        valid_until=valid_until,
    )


def _evidence_document(
    *,
    source: TransitionPlanSourceBinding,
    planning_policy: TransitionPlanPolicyBinding,
    risk: TransitionPlanRiskBinding,
    fee_policy: TransitionPlanPolicyBinding,
    quantity_rule: TransitionPlanPolicyBinding,
    settlement_rule: TransitionPlanPolicyBinding,
    execution_calendar: TransitionPlanPolicyBinding,
    selection_id: str,
    selection_hash: str,
    prepared_at: datetime,
) -> tuple[str, str, str, str, str, str]:
    """Build a self-consistent embedded evidence document for codec contract tests."""

    resources: dict[str, object] = {
        "account_id": 17,
        "owner_user_id": 23,
        "snapshot_id": "ledger-snapshot-test",
        "read_at": (_NOW - timedelta(minutes=1)).isoformat(),
        "cash": "10000",
        "money_unit": "CNY",
        "holdings": [],
        "active_orders": [],
        "executed_usage": [],
    }
    portfolio_hash = _canonical_hash(resources)
    portfolio_id = portfolio_hash
    target_payload: dict[str, object] = {"weights": ["600000.SH:100%"]}
    target_content = _canonical_hash(target_payload)
    target_portfolio_id = target_content
    target_content_hash = target_content
    source_rows = [source.to_payload()]
    source_hash = _canonical_hash({"source_bindings": source_rows})
    policy_rows = {
        "planning_policy": planning_policy.to_payload(),
        "fee_policy": fee_policy.to_payload(),
        "quantity_rule": quantity_rule.to_payload(),
        "settlement_rule": settlement_rule.to_payload(),
        "execution_calendar": execution_calendar.to_payload(),
    }
    decision_payload: dict[str, object] = {
        "portfolio_snapshot_id": portfolio_id,
        "portfolio_snapshot_hash": portfolio_hash,
        "target_portfolio_id": target_portfolio_id,
        "target_content_hash": target_content_hash,
        "selection_id": selection_id,
        "selection_hash": selection_hash,
        "captured_preview": {"status": "ready", "asset_items": []},
        "prepared_resources": resources,
    }
    decision_hash = _canonical_hash(decision_payload)
    document: dict[str, object] = {
        "schema": "ash08.plan_preparation.v1",
        "portfolio_snapshot": {
            "id": portfolio_id,
            "content_hash": portfolio_hash,
            "source_evidence_hash": source_hash,
            "as_of": (_NOW - timedelta(minutes=1)).isoformat(),
            "resources": resources,
        },
        "decision_snapshot": {
            "id": decision_hash,
            "content_hash": decision_hash,
            "payload": decision_payload,
        },
        "target": {
            "id": target_portfolio_id,
            "content_hash": target_content_hash,
            "selection_id": selection_id,
            "selection_hash": selection_hash,
            "payload": target_payload,
        },
        "policy_bindings": policy_rows,
        "risk": risk.to_payload(),
        "source_bindings": source_rows,
        "positions": {"current": [], "target": []},
        "business_date": "2026-11-05",
        "execution_session": "2026-11-05",
        "prepared_at": prepared_at.isoformat(),
    }
    encoded = json.dumps(document, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return encoded, portfolio_id, portfolio_hash, source_hash, decision_hash, target_content_hash


def _revision(*, asset_type: str = "equity", classification_hash: str = _HASH_A):
    """Build one exact plan revision whose only varying facts are classification pins."""

    expiry = _NOW + timedelta(minutes=20)
    source = TransitionPlanSourceBinding(
        kind="valuation",
        asset_code="600000.SH",
        security_id="SH.TEST.600000",
        source_id="synthetic-source",
        source_record_id="synthetic-record",
        manifest_sha256=_HASH_A,
        body_sha256=_HASH_B,
        observation_precision="timestamp",
        observed_at=_NOW - timedelta(minutes=2),
        observed_on=None,
        available_at=_NOW - timedelta(minutes=1),
        known_at=_NOW - timedelta(minutes=1),
        decision_cutoff=_NOW,
        decision_date_cutoff=None,
        source_valid_until=_NOW + timedelta(hours=1),
        admission_until=expiry,
        qualification_proof_hash=None,
        source_purpose="valuation_snapshot",
        requested_purpose="transition_plan",
        allowed_purposes=("transition_plan",),
        restrictions=(),
        coverage_status="complete",
        qualified=True,
    )
    planning_policy = TransitionPlanPolicyBinding(
        kind="planning_policy",
        status="not_applicable",
        reference_id=None,
        version=None,
        content_hash=None,
        effective_at=None,
        known_at=None,
        valid_until=None,
        reason_code="preview_has_no_separate_planning_policy",
    )
    risk = TransitionPlanRiskBinding(
        report_content_hash=_HASH_A,
        binding_hash=_HASH_B,
        outcome="allowed",
        must_not_use_for_decision=False,
    )
    fee_policy = _policy("fee_policy", valid_until=expiry)
    quantity_rule = _policy("quantity_rule", valid_until=expiry)
    settlement_rule = _policy("settlement_rule", valid_until=expiry)
    execution_calendar = _policy("execution_calendar", valid_until=expiry)
    selection_id = "selection-1"
    selection_hash = _HASH_A
    (
        preparation_evidence_json,
        portfolio_snapshot_id,
        portfolio_snapshot_hash,
        portfolio_source_evidence_hash,
        decision_snapshot_hash,
        target_content_hash,
    ) = _evidence_document(
        source=source,
        planning_policy=planning_policy,
        risk=risk,
        fee_policy=fee_policy,
        quantity_rule=quantity_rule,
        settlement_rule=settlement_rule,
        execution_calendar=execution_calendar,
        selection_id=selection_id,
        selection_hash=selection_hash,
        prepared_at=_NOW,
    )
    target_portfolio_id = target_content_hash
    basis = TransitionPlanBasis(
        account_id=17,
        owner_user_id=23,
        requested_by_user_id=23,
        money_unit="CNY",
        portfolio_snapshot_id=portfolio_snapshot_id,
        portfolio_snapshot_hash=portfolio_snapshot_hash,
        portfolio_snapshot_as_of=_NOW - timedelta(minutes=1),
        portfolio_source_evidence_hash=portfolio_source_evidence_hash,
        decision_snapshot_id=decision_snapshot_hash,
        decision_snapshot_hash=decision_snapshot_hash,
        target_portfolio_id=target_portfolio_id,
        target_content_hash=target_content_hash,
        selection_id=selection_id,
        selection_hash=selection_hash,
        planning_policy=planning_policy,
        risk=risk,
        fee_policy=fee_policy,
        quantity_rule=quantity_rule,
        settlement_rule=settlement_rule,
        execution_calendar=execution_calendar,
        source_bindings=(source,),
        current_positions=(),
        target_positions=(),
        business_date=date(2026, 11, 5),
        execution_session=date(2026, 11, 5),
        prepared_at=_NOW,
        valid_until=expiry,
        preparation_evidence_json=preparation_evidence_json,
    )
    plan = TransitionPlan(
        plan_id="pending-plan-id",
        idempotency_key="revision-asset-identity-test",
        account_id="17",
        decision_snapshot_id=basis.decision_snapshot_id,
        portfolio_snapshot_id=basis.portfolio_snapshot_id,
        target_portfolio_id=basis.target_portfolio_id,
        as_of_time=basis.portfolio_snapshot_as_of,
        expires_at=expiry,
        orders=(
            OrderDraft(
                asset_code="600000.SH",
                side="buy",
                quantity=100,
                reference_price=Decimal("10.00"),
                estimated_fee=Decimal("1.00"),
                status="draft",
            ),
        ),
        constraints=(),
        cash_before=Decimal("10000"),
        cash_after=Decimal("8999"),
        status="DRAFT",
        metadata={"planning_policy_version": "not_applicable"},
    )
    return build_transition_plan_revision(
        TransitionPlanRevisionPreparation(
            plan=plan,
            basis=basis,
            family_id="family-1",
            root_plan_id=None,
            version=1,
            parent_plan_id=None,
            parent_version=None,
            parent_revision_hash=None,
            order_specifications=(
                TransitionPlanOrderSpecification(
                    ordinal=0,
                    asset_code="600000.SH",
                    security_id="SH.TEST.600000",
                    asset_type=asset_type,
                    classification_content_hash=classification_hash,
                    quantity_unit="share",
                    money_unit="CNY",
                ),
            ),
        )
    )


def _preparation(
    revision: TransitionPlanRevision,
    *,
    idempotency_key: str,
    parent: TransitionPlanRevision | None = None,
) -> TransitionPlanRevisionPreparation:
    """Recreate the exact server preparation for an initial or child revision."""

    specifications = tuple(
        TransitionPlanOrderSpecification(
            ordinal=order.ordinal,
            asset_code=order.asset_code,
            security_id=order.security_id,
            asset_type=order.asset_type,
            classification_content_hash=order.classification_content_hash,
            quantity_unit=order.quantity_unit,
            money_unit=order.money_unit,
            approved_limit_price=order.approved_limit_price,
        )
        for order in revision.orders
    )
    return TransitionPlanRevisionPreparation(
        plan=replace(revision.plan, idempotency_key=idempotency_key),
        basis=revision.basis,
        family_id=revision.identity.family_id,
        root_plan_id=parent.identity.root_plan_id if parent is not None else None,
        version=(parent.identity.version + 1) if parent is not None else 1,
        parent_plan_id=parent.identity.plan_id if parent is not None else None,
        parent_version=parent.identity.version if parent is not None else None,
        parent_revision_hash=parent.identity.revision_hash if parent is not None else None,
        order_specifications=specifications,
    )


class _LifecycleClock:
    """Supply a controlled aware time to lifecycle use cases."""

    def __init__(self, value: datetime = _NOW) -> None:
        self.value = value

    def now(self) -> datetime:
        return self.value


class _LifecycleAuthorizer:
    """Keep the test actor scoped to the one source-bound owner account."""

    def require_read(self, *, actor_user_id: int, account_id: int) -> int:
        assert (actor_user_id, account_id) == (23, 17)
        return 23

    def require_write(self, *, actor_user_id: int, account_id: int) -> int:
        assert (actor_user_id, account_id) == (23, 17)
        return 23


class _LifecycleProvider:
    """Return one prebuilt typed preparation and record any recomputation."""

    def __init__(self, preparation: TransitionPlanRevisionPreparation) -> None:
        self.preparation = preparation
        self.calls: list[tuple[datetime, TransitionPlanRevision | None]] = []

    def prepare(
        self,
        request: TransitionPlanRevisionRequest,
        *,
        prepared_at: datetime,
        parent: TransitionPlanRevision | None,
    ) -> TransitionPlanRevisionPreparation:
        assert request.account_id == self.preparation.basis.account_id
        assert prepared_at == self.preparation.basis.prepared_at
        assert (parent is None) == (self.preparation.parent_plan_id is None)
        self.calls.append((prepared_at, parent))
        return self.preparation


class _LifecycleRepository:
    """Model only the existing revision repository contract in memory."""

    def __init__(self) -> None:
        self.revisions: dict[tuple[str, int], TransitionPlanRevision] = {}
        self.idempotency_keys: dict[str, TransitionPlanRevision] = {}
        self.append_initial_calls = 0
        self.append_successor_calls = 0
        self.review_calls = 0
        self.review_subject_ids: list[str] = []

    def get_by_idempotency_key(
        self, *, idempotency_key: str, as_of: datetime
    ) -> TransitionPlanRevision | None:
        revision = self.idempotency_keys.get(idempotency_key)
        return revision if revision is not None and revision.identity.recorded_at <= as_of else None

    def get_exact(
        self,
        *,
        plan_id: str,
        version: int,
        expected_revision_hash: str,
        as_of: datetime,
    ) -> TransitionPlanRevision | None:
        revision = self.revisions.get((plan_id, version))
        if (
            revision is None
            or revision.identity.recorded_at > as_of
            or revision.identity.revision_hash != expected_revision_hash
        ):
            return None
        return revision

    def get_family_head(
        self, *, account_id: int, family_id: str, as_of: datetime
    ) -> TransitionPlanRevision | None:
        matches = tuple(
            item
            for item in self.revisions.values()
            if item.identity.account_id == account_id
            and item.identity.family_id == family_id
            and item.identity.recorded_at <= as_of
        )
        return max(matches, key=lambda item: item.identity.version) if matches else None

    def append_initial(
        self, revision: TransitionPlanRevision, *, idempotency_key: str
    ) -> TransitionPlanRevision:
        self.append_initial_calls += 1
        existing = self.idempotency_keys.get(idempotency_key)
        if existing is not None:
            if existing.identity.revision_hash != revision.identity.revision_hash:
                raise TransitionPlanRevisionConflict("initial revision first winner differs")
            return existing
        self._store(revision, idempotency_key)
        return revision

    def append_successor(
        self,
        revision: TransitionPlanRevision,
        *,
        expected_parent: TransitionPlanRevisionIdentity,
        idempotency_key: str,
    ) -> TransitionPlanRevision:
        self.append_successor_calls += 1
        parent = self.get_family_head(
            account_id=revision.identity.account_id,
            family_id=revision.identity.family_id,
            as_of=revision.identity.recorded_at,
        )
        if (
            parent is None
            or parent.identity != expected_parent
            or parent.identity.revision_hash != revision.identity.parent_revision_hash
        ):
            raise TransitionPlanRevisionConflict("successor parent is no longer the family head")
        self._store(revision, idempotency_key)
        return revision

    def submit_for_review(
        self,
        *,
        revision: TransitionPlanRevision,
        owner_user_id: int,
        review_subject_id: str,
        requested_at: datetime,
    ) -> TransitionPlanRevision:
        self.review_calls += 1
        assert revision.identity.owner_user_id == owner_user_id
        assert review_subject_id
        assert requested_at < revision.identity.valid_until
        self.review_subject_ids.append(review_subject_id)
        wrapper = encode_transition_plan_revision(
            revision,
            idempotency_key=revision.plan.idempotency_key,
        )
        pending = decode_transition_plan_revision(
            wrapper,
            current_status="APPROVAL_PENDING",
            idempotency_key=revision.plan.idempotency_key,
        )
        self.revisions[(pending.identity.plan_id, pending.identity.version)] = pending
        self.idempotency_keys[revision.plan.idempotency_key] = pending
        return pending

    def _store(self, revision: TransitionPlanRevision, idempotency_key: str) -> None:
        self.revisions[(revision.identity.plan_id, revision.identity.version)] = revision
        self.idempotency_keys[idempotency_key] = revision


def _request(
    revision: TransitionPlanRevision,
    *,
    idempotency_key: str,
) -> TransitionPlanRevisionRequest:
    """Create client intent using only the target and selection pins."""

    return TransitionPlanRevisionRequest(
        actor_user_id=23,
        account_id=17,
        target_portfolio_id=revision.basis.target_portfolio_id,
        selection_id=revision.basis.selection_id,
        expected_selection_hash=revision.basis.selection_hash,
        idempotency_key=idempotency_key,
    )


def test_asset_type_and_classification_hash_are_part_of_all_revision_bindings() -> None:
    """A changed server classification produces a different exact revision and order binding."""

    equity = _revision()
    fund = _revision(asset_type="fund")
    changed_classification = _revision(classification_hash=_HASH_B)

    assert equity.orders[0].asset_type == "equity"
    assert equity.orders[0].classification_content_hash == _HASH_A
    assert fund.orders[0].asset_type == "fund"
    assert equity.identity.plan_id != fund.identity.plan_id
    assert equity.identity.revision_hash != fund.identity.revision_hash
    assert equity.orders[0].plan_order_binding_id != fund.orders[0].plan_order_binding_id
    assert equity.identity.plan_id != changed_classification.identity.plan_id
    assert (
        equity.orders[0].plan_order_binding_id
        != changed_classification.orders[0].plan_order_binding_id
    )
    equity_action = equity.orders[0].to_execution_binding(
        equity.identity, owner_user_id=23, action_attempt_key="attempt-1"
    )
    fund_action = fund.orders[0].to_execution_binding(
        fund.identity, owner_user_id=23, action_attempt_key="attempt-1"
    )
    assert equity_action.to_payload()["asset_type"] == "equity"
    assert equity_action.content_hash != fund_action.content_hash


def test_rehashed_order_binding_cannot_change_its_resolved_asset_classification() -> None:
    """Changing classification without rebuilding the trusted revision is rejected."""

    revision = _revision()
    tampered_order = replace(revision.orders[0], asset_type="fund")

    with pytest.raises(ValueError, match="deterministic plan ID"):
        replace(revision, orders=(tampered_order,))


def test_asset_classification_hash_requires_a_plain_sha256_digest() -> None:
    """Malformed or missing classification identity cannot enter a plan specification."""

    with pytest.raises(ValueError, match="classification_content_hash"):
        TransitionPlanOrderSpecification(
            ordinal=0,
            asset_code="600000.SH",
            security_id="SH.TEST.600000",
            asset_type="equity",
            classification_content_hash="sha256:" + _HASH_A,
            quantity_unit="share",
            money_unit="CNY",
        )


def test_codec_round_trip_preserves_and_authenticates_classification_pins() -> None:
    """The persisted revision carries both classification facts in its immutable order row."""

    revision = _revision(asset_type="fund", classification_hash=_HASH_B)
    encoded = encode_transition_plan_revision(
        revision,
        idempotency_key=revision.plan.idempotency_key,
    )
    decoded = decode_transition_plan_revision(
        encoded,
        current_status=revision.plan.status,
        idempotency_key=revision.plan.idempotency_key,
    )

    assert decoded.orders[0].asset_type == "fund"
    assert decoded.orders[0].classification_content_hash == _HASH_B
    assert decoded.identity.revision_hash == revision.identity.revision_hash
    assert decoded.basis.preparation_evidence_json == revision.basis.preparation_evidence_json

    wrapper = cast(dict[str, object], dict(encoded))
    stored_revision = cast(dict[str, object], dict(cast(dict[str, object], encoded["revision"])))
    stored_orders = cast(list[object], list(cast(list[object], stored_revision["orders"])))
    stored_order = cast(dict[str, object], dict(cast(dict[str, object], stored_orders[0])))
    stored_order["classification_content_hash"] = _HASH_A
    stored_orders[0] = stored_order
    stored_revision["orders"] = stored_orders
    wrapper["revision"] = stored_revision

    with pytest.raises(ValueError, match="deterministic plan ID|revision hash"):
        decode_transition_plan_revision(
            wrapper,
            current_status=revision.plan.status,
            idempotency_key=revision.plan.idempotency_key,
        )


def test_embedded_preparation_resources_cannot_change_under_the_saved_snapshot_hash() -> None:
    """The embedded source context and snapshot digest must remain the same bytes."""

    revision = _revision()
    document = json.loads(revision.basis.preparation_evidence_json)
    portfolio = document["portfolio_snapshot"]
    resources = portfolio["resources"]
    resources["cash"] = "999999"
    altered = json.dumps(document, ensure_ascii=False, sort_keys=True, separators=(",", ":"))

    with pytest.raises(ValueError, match="embedded portfolio resources"):
        replace(revision.basis, preparation_evidence_json=altered)


@pytest.mark.parametrize(
    ("section", "expected_error"),
    (
        ("target", "embedded target"),
        ("decision", "embedded decision"),
        ("source", "embedded source bindings"),
        ("policy", "embedded policy bindings"),
        ("positions", "embedded positions"),
        ("clock", "embedded preparation clocks"),
    ),
)
def test_embedded_plan_evidence_sections_reject_self_inconsistent_mutation(
    section: str,
    expected_error: str,
) -> None:
    """Target, decision, source, policy, position and clock copies stay basis-bound."""

    revision = _revision()
    document = cast(dict[str, object], json.loads(revision.basis.preparation_evidence_json))
    if section == "target":
        target = cast(dict[str, object], document["target"])
        payload = cast(dict[str, object], target["payload"])
        payload["weights"] = ["600000.SH:0%"]
    elif section == "decision":
        decision = cast(dict[str, object], document["decision_snapshot"])
        payload = cast(dict[str, object], decision["payload"])
        payload["selection_hash"] = _HASH_B
    elif section == "source":
        sources = cast(list[object], document["source_bindings"])
        source = cast(dict[str, object], sources[0])
        source["body_sha256"] = _HASH_A
    elif section == "policy":
        policies = cast(dict[str, object], document["policy_bindings"])
        fee = cast(dict[str, object], policies["fee_policy"])
        fee["content_hash"] = _HASH_B
    elif section == "positions":
        positions = cast(dict[str, object], document["positions"])
        positions["target"] = [{"asset_code": "600000.SH", "quantity": "100"}]
    else:
        document["prepared_at"] = (_NOW + timedelta(seconds=1)).isoformat()
    altered = json.dumps(document, ensure_ascii=False, sort_keys=True, separators=(",", ":"))

    with pytest.raises(ValueError, match=expected_error):
        replace(revision.basis, preparation_evidence_json=altered)


def test_source_admission_keeps_manifest_and_body_hashes_separate_and_unknown_clocks_explicit() -> (
    None
):
    """A proof may justify missing vendor clocks without rewriting either hash or clock."""

    source = _revision().basis.source_bindings[0]
    assert source.manifest_sha256 == _HASH_A
    assert source.body_sha256 == _HASH_B
    assert source.manifest_sha256 != source.body_sha256
    assert source.observed_at == _NOW - timedelta(minutes=2)
    assert source.available_at == _NOW - timedelta(minutes=1)

    proof_backed_unknown = replace(
        source,
        available_at=None,
        known_at=None,
        source_valid_until=None,
        qualification_proof_hash=_HASH_B,
    )
    assert proof_backed_unknown.available_at is None
    assert proof_backed_unknown.known_at is None
    assert proof_backed_unknown.source_valid_until is None
    assert proof_backed_unknown.qualification_proof_hash == _HASH_B
    assert proof_backed_unknown.admission_until == _NOW + timedelta(minutes=20)

    with pytest.raises(ValueError, match="unknown source observation precision"):
        replace(source, observation_precision="unknown")
    with pytest.raises(ValueError, match="observation follows"):
        replace(source, observed_at=_NOW + timedelta(seconds=1))
    with pytest.raises(ValueError, match="source is expired"):
        replace(source, source_valid_until=_NOW)
    with pytest.raises(ValueError, match="unqualified source"):
        replace(source, qualified=False, reason_codes=("SOURCE_NOT_QUALIFIED",))
    with pytest.raises(ValueError, match="does not permit its requested plan purpose"):
        replace(source, requested_purpose="unapproved_purpose")


def test_basis_and_qualified_policy_reject_expiry_and_future_known_clock() -> None:
    """Plan admission cannot outlive evidence or use a policy before it was known."""

    basis = _revision().basis
    with pytest.raises(ValueError, match="basis is expired at preparation"):
        replace(basis, valid_until=_NOW)

    future_fee = replace(basis.fee_policy, known_at=_NOW + timedelta(seconds=1))
    document = cast(dict[str, object], json.loads(basis.preparation_evidence_json))
    policies = cast(dict[str, object], document["policy_bindings"])
    policies["fee_policy"] = future_fee.to_payload()
    evidence = json.dumps(document, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    with pytest.raises(ValueError, match="policy was not known and effective"):
        replace(basis, fee_policy=future_fee, preparation_evidence_json=evidence)


def test_successor_preserves_exact_parent_and_rejects_wrong_ordering() -> None:
    """A successor is a new immutable revision whose exact parent and ordinal remain pinned."""

    parent = _revision()
    preparation = _preparation(parent, idempotency_key="successor-request", parent=parent)
    successor = build_transition_plan_revision(preparation)

    assert successor.identity.version == parent.identity.version + 1
    assert successor.identity.parent_plan_id == parent.identity.plan_id
    assert successor.identity.parent_revision_hash == parent.identity.revision_hash
    assert successor.identity.root_plan_id == parent.identity.root_plan_id
    assert successor.identity.plan_id != parent.identity.plan_id
    assert successor.identity.revision_hash != parent.identity.revision_hash

    changed_parent = replace(successor.identity, parent_revision_hash=_HASH_B)
    with pytest.raises(ValueError, match="deterministic plan ID|revision hash"):
        replace(successor, identity=changed_parent)

    with pytest.raises(ValueError, match="contiguous exact ordinals"):
        replace(
            preparation,
            order_specifications=(replace(preparation.order_specifications[0], ordinal=1),),
        )


def test_initial_lifecycle_replays_its_original_revision_and_rejects_key_rebinding() -> None:
    """Retries return original clocks; a reused key cannot be rebound to another target."""

    expected = _revision()
    repository = _LifecycleRepository()
    provider = _LifecycleProvider(
        _preparation(expected, idempotency_key=expected.plan.idempotency_key)
    )
    clock = _LifecycleClock()
    use_case = CreateInitialTransitionPlanRevisionUseCase(
        repository=repository,
        preparation_provider=provider,
        authorizer=_LifecycleAuthorizer(),
        clock=clock,
    )
    request = _request(expected, idempotency_key=expected.plan.idempotency_key)

    created = use_case.execute(request)
    assert created.identity.revision_hash == expected.identity.revision_hash
    assert len(provider.calls) == 1
    assert repository.append_initial_calls == 1

    clock.value = expected.identity.valid_until + timedelta(minutes=1)
    replayed = use_case.execute(request)
    assert replayed.identity.revision_hash == created.identity.revision_hash
    assert replayed.identity.recorded_at == created.identity.recorded_at == _NOW
    assert replayed.basis.source_bindings == created.basis.source_bindings
    assert len(provider.calls) == 1

    conflicting = replace(request, expected_selection_hash=_HASH_B)
    with pytest.raises(TransitionPlanRevisionConflict, match="another plan request"):
        use_case.execute(conflicting)
    assert len(provider.calls) == 1


def test_successor_lifecycle_compare_and_set_replays_only_exact_parent_first_winner() -> None:
    """A single family head advances; retries replay and a stale parent cannot fork it."""

    parent = _revision()
    repository = _LifecycleRepository()
    repository._store(parent, parent.plan.idempotency_key)
    child_key = "successor-request"
    provider = _LifecycleProvider(_preparation(parent, idempotency_key=child_key, parent=parent))
    clock = _LifecycleClock()
    use_case = CreateTransitionPlanSuccessorUseCase(
        repository=repository,
        preparation_provider=provider,
        authorizer=_LifecycleAuthorizer(),
        clock=clock,
    )
    request = _request(parent, idempotency_key=child_key)
    command = CreateTransitionPlanSuccessorCommand(
        request=request,
        expected_parent_plan_id=parent.identity.plan_id,
        expected_parent_version=parent.identity.version,
        expected_parent_revision_hash=parent.identity.revision_hash,
    )

    child = use_case.execute(command)
    assert child.identity.parent_plan_id == parent.identity.plan_id
    assert child.identity.parent_revision_hash == parent.identity.revision_hash
    assert repository.append_successor_calls == 1
    assert len(provider.calls) == 1
    assert use_case.execute(command).identity.revision_hash == child.identity.revision_hash
    assert len(provider.calls) == 1

    stale_parent_command = replace(
        command,
        request=replace(request, idempotency_key="stale-parent-new-key"),
    )
    with pytest.raises(TransitionPlanRevisionConflict, match="family head"):
        use_case.execute(stale_parent_command)
    assert len(provider.calls) == 1


def test_owner_review_request_only_enters_pending_state_and_never_issues_authority() -> None:
    """Owner review submission is a request; it does not create an executable approval."""

    revision = _revision()
    repository = _LifecycleRepository()
    repository._store(revision, revision.plan.idempotency_key)
    use_case = RequestTransitionPlanRevisionReviewUseCase(
        repository=repository,
        authorizer=_LifecycleAuthorizer(),
        clock=_LifecycleClock(),
    )

    submission = use_case.execute(
        RequestTransitionPlanRevisionReview(
            actor_user_id=23,
            account_id=17,
            plan_id=revision.identity.plan_id,
            version=revision.identity.version,
            expected_revision_hash=revision.identity.revision_hash,
        )
    )

    assert repository.review_calls == 1
    assert submission.revision.plan.status == "APPROVAL_PENDING"
    assert submission.artifact_identity.revision_hash == revision.identity.revision_hash
    assert submission.revision.to_payload()["automatic_submission"] is False
    assert repository.review_subject_ids == [submission.artifact_identity.subject_id]
    assert not hasattr(submission, "approval_receipt")
    assert not hasattr(submission, "execution_permission")


def test_expired_revision_remains_exactly_readable_but_cannot_enter_review() -> None:
    """Expiry blocks new approval workflow without hiding the original immutable evidence."""

    revision = _revision()
    repository = _LifecycleRepository()
    repository._store(revision, revision.plan.idempotency_key)
    clock = _LifecycleClock(revision.identity.valid_until + timedelta(seconds=1))
    authorizer = _LifecycleAuthorizer()

    exact = GetExactTransitionPlanRevisionUseCase(
        repository=repository,
        authorizer=authorizer,
        clock=clock,
    ).execute(
        GetExactTransitionPlanRevisionQuery(
            actor_user_id=23,
            account_id=17,
            plan_id=revision.identity.plan_id,
            version=revision.identity.version,
            expected_revision_hash=revision.identity.revision_hash,
        )
    )
    assert exact is revision
    assert exact.identity.valid_until < clock.value
    assert exact.identity.recorded_at == revision.identity.recorded_at
    assert exact.basis.preparation_evidence_json == revision.basis.preparation_evidence_json

    review_use_case = RequestTransitionPlanRevisionReviewUseCase(
        repository=repository,
        authorizer=authorizer,
        clock=clock,
    )
    with pytest.raises(TransitionPlanRevisionBlocked, match="expired plan revisions"):
        review_use_case.execute(
            RequestTransitionPlanRevisionReview(
                actor_user_id=23,
                account_id=17,
                plan_id=revision.identity.plan_id,
                version=revision.identity.version,
                expected_revision_hash=revision.identity.revision_hash,
            )
        )
    assert repository.review_calls == 0


def test_owner_manual_guard_accepts_exact_unapproved_revision_without_staff_receipt(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A plan binding is an extra context pin; ordinary Owner execution keeps its existing gates."""

    revision = _revision()

    policy_reader = _PolicyPinReader()
    guard = DjangoTransitionPlanLockedActionGuard(
        current_policy_pins_validator=policy_reader,
    )
    monkeypatch.setattr(
        guard._repository, "_locked_account_revisions", lambda account_id: (revision,)
    )
    monkeypatch.setattr(guard._repository, "_manager", lambda: _RowQuery())
    monkeypatch.setattr(guard, "_approval_repository", _NoReviewArtifacts())

    def _atomic(*, using: str) -> AbstractContextManager[None]:
        return nullcontext()

    monkeypatch.setattr(
        "apps.portfolio.infrastructure.transition_plan_revision_repository.transaction.atomic",
        _atomic,
    )
    binding = revision.orders[0].to_execution_binding(
        revision.identity,
        owner_user_id=23,
        action_attempt_key="owner-manual-attempt",
    )

    accepted = guard.validate_locked_action(
        binding=binding,
        account_id=17,
        owner_user_id=23,
        as_of=_NOW,
    )

    assert accepted.identity.revision_hash == revision.identity.revision_hash
    assert policy_reader.checked_revision_hashes == [revision.identity.revision_hash]


def test_owner_manual_guard_rejects_wrong_classification_and_nonactive_plan_states(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The exact classification is immutable and rejected plans never provide manual context."""

    revision = _revision()
    guard = DjangoTransitionPlanLockedActionGuard(
        current_policy_pins_validator=_PolicyPinReader(),
    )
    monkeypatch.setattr(
        guard._repository, "_locked_account_revisions", lambda account_id: (revision,)
    )
    monkeypatch.setattr(guard._repository, "_manager", lambda: _RowQuery())
    monkeypatch.setattr(guard, "_approval_repository", _NoReviewArtifacts())
    monkeypatch.setattr(
        "apps.portfolio.infrastructure.transition_plan_revision_repository.transaction.atomic",
        lambda *, using: nullcontext(),
    )
    binding = revision.orders[0].to_execution_binding(
        revision.identity,
        owner_user_id=23,
        action_attempt_key="owner-manual-attempt",
    )

    with pytest.raises(TransitionPlanRevisionCorruption, match="classification"):
        guard.validate_locked_action(
            binding=replace(binding, classification_content_hash=_HASH_B),
            account_id=17,
            owner_user_id=23,
            as_of=_NOW,
        )

    rejected_revision = replace(revision, plan=replace(revision.plan, status="REJECTED"))
    monkeypatch.setattr(
        guard._repository,
        "_locked_account_revisions",
        lambda account_id: (rejected_revision,),
    )
    with pytest.raises(TransitionPlanRevisionBlocked, match="not available for Owner review"):
        guard.validate_locked_action(
            binding=binding,
            account_id=17,
            owner_user_id=23,
            as_of=_NOW,
        )
