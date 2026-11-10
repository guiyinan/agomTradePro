"""Contract tests for source-resolved asset classification in revision bindings."""

from __future__ import annotations

import json
from collections.abc import Iterator
from contextlib import AbstractContextManager, contextmanager, nullcontext
from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace
from typing import cast
from unittest.mock import Mock

import pytest

from apps.portfolio.application.transition_plan_event_review import (
    AssessTransitionPlanEventReview,
    TransitionPlanEventSnapshotReadRequest,
    TransitionPlanEventSourceRevisionChanged,
)
from apps.portfolio.application.transition_plan_lifecycle import (
    CreateInitialTransitionPlanRevisionUseCase,
    CreateTransitionPlanSuccessorCommand,
    CreateTransitionPlanSuccessorUseCase,
    GetExactTransitionPlanRevisionQuery,
    GetExactTransitionPlanRevisionUseCase,
    RequestTransitionPlanRevisionReview,
    RequestTransitionPlanRevisionReviewUseCase,
    TransitionPlanEventReviewRequired,
    TransitionPlanRevisionBlocked,
    TransitionPlanRevisionConflict,
    TransitionPlanRevisionCorruption,
    TransitionPlanRevisionRequest,
)
from apps.portfolio.domain.entities import OrderDraft, TransitionPlan
from apps.portfolio.domain.transition_plan_event_review import (
    SECURITY_DISCLOSURE_EVENT_COVERAGE_RECORD_ID,
    SECURITY_DISCLOSURE_EVENT_SOURCE_KIND,
    TransitionPlanEventAssetSnapshot,
    TransitionPlanEventCoverageLeasePolicy,
    TransitionPlanEventCoverageStatus,
    TransitionPlanEventReviewAssessment,
    TransitionPlanEventReviewState,
    TransitionPlanEventRevision,
    transition_plan_event_revision_sha256,
    transition_plan_event_snapshot_sha256,
)
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
    DjangoTransitionPlanRevisionRepository,
)
from apps.simulated_trading.application.rebalance_journey_public import RebalanceJourneyCommand
from apps.simulated_trading.application.rebalance_journey_service import (
    RebalanceJourneyApplication,
)
from core.exceptions import BusinessLogicError
from core.integration.transition_plan_contracts import (
    CANONICAL_TRANSITION_PLAN_FAMILY,
    PORTFOLIO_PLAN_REVISION_FAMILY,
    PORTFOLIO_PLAN_REVISION_MARKER,
)

_NOW = datetime(2026, 11, 5, 9, 30, tzinfo=UTC)
_HASH_A = "a" * 64
_HASH_B = "b" * 64
_HASH_C = "c" * 64


class _EventSnapshotReader:
    """Serve exact immutable source snapshots at controlled point-in-time cutoffs."""

    def __init__(self, snapshots: tuple[TransitionPlanEventAssetSnapshot, ...] = ()) -> None:
        self.snapshots = {item.as_of: item for item in snapshots}
        self.requests: list[TransitionPlanEventSnapshotReadRequest] = []

    def read_snapshot(
        self, request: TransitionPlanEventSnapshotReadRequest
    ) -> TransitionPlanEventAssetSnapshot | None:
        self.requests.append(request)
        return self.snapshots.get(request.as_of)

    def read_latest_snapshot(
        self, request: TransitionPlanEventSnapshotReadRequest
    ) -> TransitionPlanEventAssetSnapshot | None:
        """Serve the explicit action-time latest-proof read from the test snapshot map."""

        return self.read_snapshot(request)


class _ActionTimeEventSnapshotReader:
    """Return an exact historical snapshot and a current proof at its own recorded clock."""

    def __init__(
        self,
        *,
        snapshots_by_request_time: dict[datetime, TransitionPlanEventAssetSnapshot],
    ) -> None:
        self.snapshots = snapshots_by_request_time
        self.requests: list[TransitionPlanEventSnapshotReadRequest] = []

    def read_snapshot(
        self,
        request: TransitionPlanEventSnapshotReadRequest,
    ) -> TransitionPlanEventAssetSnapshot | None:
        """Serve only the selected read while allowing a current proof's own durable time."""

        self.requests.append(request)
        return self.snapshots.get(request.as_of)

    def read_latest_snapshot(
        self,
        request: TransitionPlanEventSnapshotReadRequest,
    ) -> TransitionPlanEventAssetSnapshot | None:
        """Serve a selected proof without moving its durable recorded clock."""

        return self.read_snapshot(request)


class _ChangedLatestEventSnapshotReader(_EventSnapshotReader):
    """Signal a confirmed action-time event revision after serving pinned history."""

    def __init__(
        self,
        snapshots: tuple[TransitionPlanEventAssetSnapshot, ...],
        *,
        latest_snapshot: TransitionPlanEventAssetSnapshot,
    ) -> None:
        super().__init__(snapshots)
        self.latest_snapshot = latest_snapshot

    def read_latest_snapshot(
        self, request: TransitionPlanEventSnapshotReadRequest
    ) -> TransitionPlanEventAssetSnapshot | None:
        self.requests.append(request)
        raise TransitionPlanEventSourceRevisionChanged(
            self.latest_snapshot,
            "new in-window event revision",
        )


class _MultiScopeEventSnapshotReader:
    """Serve two histories, with one confirmed change and a later expired proof."""

    def __init__(
        self,
        *,
        historical_snapshots: tuple[TransitionPlanEventAssetSnapshot, ...],
        current_snapshots: dict[str, TransitionPlanEventAssetSnapshot],
        changed_assets: set[str],
    ) -> None:
        self.historical = {(item.asset_code, item.as_of): item for item in historical_snapshots}
        self.current = current_snapshots
        self.changed_assets = changed_assets
        self.latest_requests: list[TransitionPlanEventSnapshotReadRequest] = []

    def read_snapshot(
        self, request: TransitionPlanEventSnapshotReadRequest
    ) -> TransitionPlanEventAssetSnapshot | None:
        return self.historical.get((request.asset_code, request.as_of))

    def read_latest_snapshot(
        self,
        request: TransitionPlanEventSnapshotReadRequest,
    ) -> TransitionPlanEventAssetSnapshot | None:
        self.latest_requests.append(request)
        snapshot = self.current.get(request.asset_code)
        if request.asset_code in self.changed_assets and snapshot is not None:
            raise TransitionPlanEventSourceRevisionChanged(
                snapshot,
                "confirmed action-time event change",
            )
        return snapshot


class _LockCheckingEventValidator:
    """Assert the final event check runs inside the caller's account transaction."""

    def __init__(self, lock_state: dict[str, bool], assessment: object) -> None:
        self.lock_state = lock_state
        self.assessment = assessment

    def assess(self, revision: TransitionPlanRevision, *, as_of: datetime) -> object:
        assert self.lock_state["active"] is True
        return self.assessment


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


def _event_snapshot(
    *,
    as_of: datetime,
    events: tuple[TransitionPlanEventRevision, ...] = (),
    coverage_status: TransitionPlanEventCoverageStatus = TransitionPlanEventCoverageStatus.COMPLETE,
    source_scope_sha256: str | None = _HASH_A,
    asset_code: str = "600000.SH",
    security_id: str = "SH.TEST.600000",
    source_id: str = "official-exchange-disclosure",
    start_on: date = date(2026, 10, 1),
    end_on: date = date(2026, 11, 5),
    first_observed_at: datetime | None = None,
    source_observed_at: datetime | None = None,
    proof_recorded_at: datetime | None = None,
) -> TransitionPlanEventAssetSnapshot:
    """Build a certified disclosure snapshot for the exact fixture security and source."""

    return TransitionPlanEventAssetSnapshot(
        asset_code=asset_code,
        security_id=security_id,
        source_id=source_id,
        start_on=start_on,
        end_on=end_on,
        as_of=as_of,
        first_observed_at=first_observed_at or min(as_of, _NOW - timedelta(minutes=3)),
        source_observed_at=source_observed_at or min(as_of, _NOW - timedelta(minutes=2)),
        proof_recorded_at=proof_recorded_at or as_of,
        coverage_status=coverage_status,
        source_scope_sha256=source_scope_sha256,
        events=events,
    )


def _event_lease_policy() -> TransitionPlanEventCoverageLeasePolicy:
    """Supply the explicitly injected versioned test lease and maximum policy value."""

    return TransitionPlanEventCoverageLeasePolicy(
        policy_version="event-pin-r1",
        ttl=timedelta(seconds=60),
        maximum_ttl=timedelta(seconds=60),
    )


def _event_revision(
    *,
    source_event_id: str = "sse-event-1",
    source_revision_id: str = "revision-1",
    event_type: str = "cash_dividend",
    body_sha256: str = _HASH_B,
    manifest_sha256: str = _HASH_A,
    available_at: datetime = _NOW - timedelta(minutes=1),
    known_at: datetime = _NOW - timedelta(minutes=1),
) -> TransitionPlanEventRevision:
    """Build one source revision without deriving clocks from the test request time."""

    return TransitionPlanEventRevision(
        asset_code="600000.SH",
        security_id="SH.TEST.600000",
        source_id="official-exchange-disclosure",
        source_event_id=source_event_id,
        source_revision_id=source_revision_id,
        event_type=event_type,
        announced_at=_NOW.date(),
        available_at=available_at,
        known_at=known_at,
        effective_at=None,
        body_sha256=body_sha256,
        manifest_sha256=manifest_sha256,
    )


def _event_coverage_pin(
    snapshot: TransitionPlanEventAssetSnapshot,
) -> TransitionPlanSourceBinding:
    """Bind a complete per-security snapshot, including the explicit empty-event case."""

    return TransitionPlanSourceBinding(
        kind=SECURITY_DISCLOSURE_EVENT_SOURCE_KIND,
        asset_code=snapshot.asset_code,
        security_id=snapshot.security_id,
        source_id=snapshot.source_id,
        source_record_id=SECURITY_DISCLOSURE_EVENT_COVERAGE_RECORD_ID,
        manifest_sha256=snapshot.source_scope_sha256 or _HASH_A,
        body_sha256=transition_plan_event_snapshot_sha256(snapshot),
        observation_precision="timestamp",
        observed_at=snapshot.source_observed_at,
        observed_on=None,
        available_at=snapshot.proof_recorded_at,
        known_at=snapshot.proof_recorded_at,
        decision_cutoff=snapshot.as_of,
        decision_date_cutoff=None,
        source_valid_until=None,
        admission_until=snapshot.as_of + timedelta(seconds=60),
        qualification_proof_hash=_HASH_C,
        source_purpose="official_disclosure_event_coverage",
        requested_purpose="transition_plan",
        allowed_purposes=("transition_plan",),
        restrictions=(),
        coverage_status="complete",
        qualified=True,
        coverage_start_on=snapshot.start_on,
        coverage_end_on=snapshot.end_on,
        coverage_policy_version="event-pin-r1",
        coverage_lease_issued_at=snapshot.proof_recorded_at,
        coverage_lease_ttl_microseconds=60_000_000,
        source_first_observed_at=snapshot.first_observed_at,
    )


def _event_coverage_bindings(
    snapshot: TransitionPlanEventAssetSnapshot,
) -> tuple[TransitionPlanSourceBinding, ...]:
    """Bind exact scope and event rows with their own clocks and revision identities."""

    marker = _event_coverage_pin(snapshot)
    event_bindings = tuple(
        replace(
            marker,
            source_record_id=event.source_event_id,
            manifest_sha256=event.manifest_sha256,
            body_sha256=event.body_sha256,
            observed_at=event.available_at,
            available_at=event.available_at,
            known_at=event.known_at,
            qualification_proof_hash=transition_plan_event_revision_sha256(event),
            source_purpose="official_exchange_disclosure",
            coverage_policy_version=None,
            coverage_lease_issued_at=None,
            coverage_lease_ttl_microseconds=None,
            source_first_observed_at=None,
        )
        for event in snapshot.events
    )
    return (marker, *event_bindings)


def _evidence_document(
    *,
    source: TransitionPlanSourceBinding,
    additional_source_bindings: tuple[TransitionPlanSourceBinding, ...],
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
    source_rows = [item.to_payload() for item in (source, *additional_source_bindings)]
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


def _revision(
    *,
    asset_type: str = "equity",
    classification_hash: str = _HASH_A,
    additional_source_bindings: tuple[TransitionPlanSourceBinding, ...] = (),
) -> TransitionPlanRevision:
    """Build one exact plan revision whose only varying facts are classification pins."""

    expiry = min(
        (_NOW + timedelta(minutes=20),)
        + tuple(item.admission_until for item in additional_source_bindings)
    )
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
        additional_source_bindings=additional_source_bindings,
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
        source_bindings=(source, *additional_source_bindings),
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


def test_event_snapshot_digest_binds_certified_scope_and_visible_revisions_not_query_time() -> None:
    """Empty and populated snapshots are stable across cutoffs but change with source facts."""

    historical = _event_snapshot(as_of=_NOW)
    later_same = _event_snapshot(as_of=_NOW + timedelta(minutes=1))
    event = _event_revision(
        source_event_id="late-event",
        available_at=_NOW + timedelta(seconds=30),
        known_at=_NOW + timedelta(seconds=30),
    )
    later_with_event = _event_snapshot(
        as_of=_NOW + timedelta(minutes=1),
        events=(event,),
    )
    later_new_scope = _event_snapshot(
        as_of=_NOW + timedelta(minutes=1),
        source_scope_sha256=_HASH_C,
    )

    assert transition_plan_event_snapshot_sha256(
        historical
    ) == transition_plan_event_snapshot_sha256(later_same)
    assert transition_plan_event_snapshot_sha256(
        historical
    ) != transition_plan_event_snapshot_sha256(later_with_event)
    assert transition_plan_event_snapshot_sha256(
        historical
    ) != transition_plan_event_snapshot_sha256(later_new_scope)


def test_event_snapshot_hash_tracks_corrected_source_revision_identity() -> None:
    """A correction with unchanged body bytes still creates a distinct event revision."""

    original = _event_snapshot(as_of=_NOW, events=(_event_revision(source_revision_id="r1"),))
    corrected = _event_snapshot(as_of=_NOW, events=(_event_revision(source_revision_id="r2"),))

    assert transition_plan_event_snapshot_sha256(original) != (
        transition_plan_event_snapshot_sha256(corrected)
    )


def test_event_first_observation_cannot_follow_its_durable_knowledge_clock() -> None:
    """An event row cannot label a later first observation as earlier local knowledge."""

    with pytest.raises(ValueError):
        _event_revision(
            available_at=_NOW,
            known_at=_NOW - timedelta(seconds=1),
        )


def test_event_coverage_lease_policy_requires_injected_versioned_bounded_ttl() -> None:
    """Lease duration has no implicit default and cannot exceed the approved ceiling."""

    assert TransitionPlanEventCoverageLeasePolicy(
        policy_version="event-pin-r1",
        ttl=timedelta(seconds=30),
        maximum_ttl=timedelta(seconds=60),
    ).ttl == timedelta(seconds=30)
    for version, ttl in (
        ("event-pin-r1", timedelta(0)),
        ("event-pin-r1", timedelta(seconds=61)),
        ("", timedelta(seconds=30)),
    ):
        with pytest.raises(ValueError):
            TransitionPlanEventCoverageLeasePolicy(
                policy_version=version,
                ttl=ttl,
                maximum_ttl=timedelta(seconds=60),
            )


def test_event_source_identity_keeps_source_and_window_in_deduplication_and_codec() -> None:
    """Independent exchange sources/windows survive basis validation and revision roundtrip."""

    first = _event_snapshot(as_of=_NOW, source_id="source-one")
    second = _event_snapshot(
        as_of=_NOW,
        source_id="source-two",
        start_on=date(2026, 9, 1),
    )
    extra = (*_event_coverage_bindings(first), *_event_coverage_bindings(second))
    revision = _revision(additional_source_bindings=extra)

    decoded = decode_transition_plan_revision(
        encode_transition_plan_revision(revision, idempotency_key=revision.plan.idempotency_key),
        current_status=revision.plan.status,
        idempotency_key=revision.plan.idempotency_key,
    )

    assert decoded.basis.source_bindings == revision.basis.source_bindings
    assert {
        (item.source_id, item.coverage_start_on, item.coverage_end_on)
        for item in decoded.basis.source_bindings
        if item.source_record_id == SECURITY_DISCLOSURE_EVENT_COVERAGE_RECORD_ID
    } == {
        ("source-one", date(2026, 10, 1), date(2026, 11, 5)),
        ("source-two", date(2026, 9, 1), date(2026, 11, 5)),
    }


def test_legacy_marker_window_mismatch_and_expired_lease_fail_closed() -> None:
    """Old unversioned markers and exact scope or lease mismatches cannot pass review."""

    baseline = _event_snapshot(as_of=_NOW)
    marker = _event_coverage_pin(baseline)
    legacy = replace(
        marker,
        coverage_start_on=None,
        coverage_end_on=None,
        coverage_policy_version=None,
        coverage_lease_issued_at=None,
        coverage_lease_ttl_microseconds=None,
        source_first_observed_at=None,
    )
    legacy_revision = _revision(additional_source_bindings=(legacy,))
    validator = AssessTransitionPlanEventReview(
        reader=_EventSnapshotReader((baseline,)),
        lease_policy=_event_lease_policy(),
    )
    assert validator.assess(legacy_revision, as_of=_NOW + timedelta(seconds=10)).state is (
        TransitionPlanEventReviewState.BLOCKED
    )

    revision = _revision(additional_source_bindings=(marker,))
    wrong_window = _event_snapshot(as_of=_NOW, start_on=date(2026, 9, 30))
    wrong_window_result = AssessTransitionPlanEventReview(
        reader=_EventSnapshotReader((wrong_window,)),
        lease_policy=_event_lease_policy(),
    ).assess(revision, as_of=_NOW + timedelta(seconds=10))
    assert wrong_window_result.state is TransitionPlanEventReviewState.BLOCKED

    expired = AssessTransitionPlanEventReview(
        reader=_EventSnapshotReader((baseline,)),
        lease_policy=_event_lease_policy(),
    ).assess(revision, as_of=_NOW + timedelta(seconds=60))
    assert expired.state is TransitionPlanEventReviewState.BLOCKED


def test_event_gate_skips_unrelated_plan_and_requires_reader_for_explicit_event_pin() -> None:
    """Legacy plans retain their path; event-scoped coverage without a reader blocks."""

    unrelated = _revision()
    event_pin = _event_coverage_pin(_event_snapshot(as_of=_NOW))
    event_revision = _revision(additional_source_bindings=(event_pin,))
    validator = AssessTransitionPlanEventReview(reader=None, lease_policy=_event_lease_policy())

    assert validator.assess(unrelated, as_of=_NOW + timedelta(minutes=1)).state is (
        TransitionPlanEventReviewState.UNCHANGED
    )
    missing = validator.assess(event_revision, as_of=_NOW + timedelta(minutes=1))
    assert missing.state is TransitionPlanEventReviewState.BLOCKED
    assert missing.reason_code == "EVENT_SOURCE_READER_UNAVAILABLE"


def test_event_gate_requires_complete_historical_and_current_coverage() -> None:
    """Missing, partial, or unknown event coverage cannot be treated as an empty event set."""

    current_at = _NOW + timedelta(minutes=1)
    baseline = _event_snapshot(as_of=_NOW)
    revision = _revision(additional_source_bindings=_event_coverage_bindings(baseline))
    for status in (
        TransitionPlanEventCoverageStatus.PARTIAL,
        TransitionPlanEventCoverageStatus.UNKNOWN,
        TransitionPlanEventCoverageStatus.MISSING,
    ):
        incomplete_current = _event_snapshot(
            as_of=current_at,
            coverage_status=status,
            source_scope_sha256=None,
        )
        validator = AssessTransitionPlanEventReview(
            reader=_EventSnapshotReader((baseline, incomplete_current)),
            lease_policy=_event_lease_policy(),
        )
        assert validator.assess(revision, as_of=current_at).state is (
            TransitionPlanEventReviewState.BLOCKED
        )

    no_history = AssessTransitionPlanEventReview(
        reader=_EventSnapshotReader(
            (
                _event_snapshot(
                    as_of=_NOW,
                    coverage_status=TransitionPlanEventCoverageStatus.UNKNOWN,
                    source_scope_sha256=None,
                ),
                _event_snapshot(as_of=current_at),
            )
        ),
        lease_policy=_event_lease_policy(),
    )
    assert (
        no_history.assess(revision, as_of=current_at).state
        is TransitionPlanEventReviewState.BLOCKED
    )


def test_latest_proof_clock_renewal_with_stable_manifest_and_revisions_is_unchanged() -> None:
    """A fresh proof timestamp alone does not mean the disclosure facts changed."""

    action_at = _NOW + timedelta(seconds=30)
    renewed_at = _NOW + timedelta(seconds=10)
    event = _event_revision()
    historical = _event_snapshot(as_of=_NOW, events=(event,))
    current = _event_snapshot(
        as_of=renewed_at,
        events=(event,),
        proof_recorded_at=renewed_at,
    )
    revision = _revision(additional_source_bindings=_event_coverage_bindings(historical))
    reader = _ActionTimeEventSnapshotReader(
        snapshots_by_request_time={_NOW: historical, action_at: current}
    )

    result = AssessTransitionPlanEventReview(
        reader=reader,
        lease_policy=_event_lease_policy(),
    ).assess(revision, as_of=action_at)

    assert result.state is TransitionPlanEventReviewState.UNCHANGED
    assert result.reason_code == "EVENTS_UNCHANGED"
    assert reader.requests[-1].as_of == action_at


def test_confirmed_action_time_event_append_requires_successor_review() -> None:
    """Only the dedicated, confirmed source-change signal maps to REVIEW_REQUIRED."""

    action_at = _NOW + timedelta(seconds=30)
    historical = _event_snapshot(as_of=_NOW, events=(_event_revision(),))
    revision = _revision(additional_source_bindings=_event_coverage_bindings(historical))
    reader = _ChangedLatestEventSnapshotReader(
        (historical,),
        latest_snapshot=historical,
    )

    result = AssessTransitionPlanEventReview(
        reader=reader,
        lease_policy=_event_lease_policy(),
    ).assess(revision, as_of=action_at)

    assert result.state is TransitionPlanEventReviewState.REVIEW_REQUIRED
    assert result.reason_code == "EVENT_REVISION_CHANGED"


def test_current_proof_lease_is_checked_independently_from_plan_lease() -> None:
    """An expired latest proof blocks even while the immutable plan lease is still live."""

    action_at = _NOW + timedelta(seconds=30)
    expired_proof_at = _NOW - timedelta(seconds=30)
    event = _event_revision()
    historical = _event_snapshot(as_of=_NOW, events=(event,))
    current = _event_snapshot(
        as_of=expired_proof_at,
        events=(event,),
        proof_recorded_at=expired_proof_at,
    )
    revision = _revision(additional_source_bindings=_event_coverage_bindings(historical))
    reader = _ActionTimeEventSnapshotReader(
        snapshots_by_request_time={_NOW: historical, action_at: current}
    )

    result = AssessTransitionPlanEventReview(
        reader=reader,
        lease_policy=_event_lease_policy(),
    ).assess(revision, as_of=action_at)

    assert result.state is TransitionPlanEventReviewState.BLOCKED
    assert result.reason_code == "EVENT_CURRENT_PROOF_LEASE_INVALID_OR_EXPIRED"


def test_later_scope_lease_failure_blocks_after_earlier_scope_event_change() -> None:
    """A confirmed change cannot short-circuit validation of another scope's lease."""

    action_at = _NOW + timedelta(seconds=30)
    first_history = _event_snapshot(as_of=_NOW)
    second_history = _event_snapshot(
        as_of=_NOW,
        asset_code="000001.SZ",
        security_id="SZ.TEST.000001",
    )
    first_current = _event_snapshot(as_of=_NOW)
    second_current = _event_snapshot(
        as_of=_NOW - timedelta(seconds=30),
        asset_code="000001.SZ",
        security_id="SZ.TEST.000001",
    )
    coverage_pins = (
        *_event_coverage_bindings(first_history),
        *_event_coverage_bindings(second_history),
    )
    revision = _revision(additional_source_bindings=coverage_pins)
    reader = _MultiScopeEventSnapshotReader(
        historical_snapshots=(first_history, second_history),
        current_snapshots={
            first_current.asset_code: first_current,
            second_current.asset_code: second_current,
        },
        changed_assets={first_current.asset_code},
    )

    result = AssessTransitionPlanEventReview(
        reader=reader,
        lease_policy=_event_lease_policy(),
    ).assess(revision, as_of=action_at)

    assert result.state is TransitionPlanEventReviewState.BLOCKED
    assert result.reason_code == "EVENT_CURRENT_PROOF_LEASE_INVALID_OR_EXPIRED"
    assert [item.asset_code for item in reader.latest_requests] == [
        first_history.asset_code,
        second_history.asset_code,
    ]


def test_new_or_corrected_event_requires_successor_review() -> None:
    """Newly available events and changed hashes cannot reuse the old immutable plan."""

    current_at = _NOW + timedelta(seconds=30)
    baseline_event = _event_revision()
    baseline = _event_snapshot(as_of=_NOW, events=(baseline_event,))
    revision = _revision(additional_source_bindings=_event_coverage_bindings(baseline))
    new_event = _event_revision(
        source_event_id="new-event",
        available_at=_NOW + timedelta(seconds=10),
        known_at=_NOW + timedelta(seconds=10),
    )
    corrected_event = _event_revision(
        body_sha256=_HASH_C,
        manifest_sha256=_HASH_C,
    )
    corrected_revision = _event_revision(source_revision_id="revision-2")

    for current in (
        _event_snapshot(as_of=current_at, events=(baseline_event, new_event)),
        _event_snapshot(as_of=current_at, events=(corrected_event,)),
        _event_snapshot(as_of=current_at, events=(corrected_revision,)),
    ):
        result = AssessTransitionPlanEventReview(
            reader=_EventSnapshotReader((baseline, current)),
            lease_policy=_event_lease_policy(),
        ).assess(revision, as_of=current_at)
        assert result.state is TransitionPlanEventReviewState.REVIEW_REQUIRED
        assert result.reason_code == "EVENT_REVISION_CHANGED"


def test_missing_current_event_proof_or_unknown_event_type_blocks() -> None:
    """A vanished source record or UNKNOWN classification is blocked for explicit event plans."""

    current_at = _NOW + timedelta(seconds=30)
    event = _event_revision()
    baseline = _event_snapshot(as_of=_NOW, events=(event,))
    revision = _revision(additional_source_bindings=_event_coverage_bindings(baseline))
    missing_current = _event_snapshot(as_of=current_at)
    unknown = _event_revision(event_type="UNKNOWN")
    unknown_current = _event_snapshot(as_of=current_at, events=(unknown,))

    for current in (missing_current, unknown_current):
        result = AssessTransitionPlanEventReview(
            reader=_EventSnapshotReader((baseline, current)),
            lease_policy=_event_lease_policy(),
        ).assess(revision, as_of=current_at)
        assert result.state is TransitionPlanEventReviewState.BLOCKED


def test_event_change_is_rejected_before_owner_review_status_write() -> None:
    """Changed event evidence blocks the Owner review write and keeps the old plan immutable."""

    current_at = _NOW + timedelta(seconds=30)
    baseline = _event_snapshot(as_of=_NOW)
    revision = _revision(additional_source_bindings=_event_coverage_bindings(baseline))
    newly_available = _event_revision(
        source_event_id="new-event",
        available_at=_NOW + timedelta(seconds=10),
        known_at=_NOW + timedelta(seconds=10),
    )
    current = _event_snapshot(as_of=current_at, events=(newly_available,))
    repository = _LifecycleRepository()
    repository._store(revision, revision.plan.idempotency_key)
    use_case = RequestTransitionPlanRevisionReviewUseCase(
        repository=repository,
        authorizer=_LifecycleAuthorizer(),
        clock=_LifecycleClock(current_at),
        event_review_validator=AssessTransitionPlanEventReview(
            reader=_EventSnapshotReader((baseline, current)),
            lease_policy=_event_lease_policy(),
        ),
    )

    with pytest.raises(TransitionPlanEventReviewRequired):
        use_case.execute(
            RequestTransitionPlanRevisionReview(
                actor_user_id=23,
                account_id=17,
                plan_id=revision.identity.plan_id,
                version=revision.identity.version,
                expected_revision_hash=revision.identity.revision_hash,
            )
        )

    assert repository.review_calls == 0
    assert (
        repository.revisions[(revision.identity.plan_id, revision.identity.version)].plan.status
        == "DRAFT"
    )


def test_event_review_rechecks_lease_after_waiting_for_persistence_lock(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A lease that expires while the repository waits cannot enter review."""

    snapshot = _event_snapshot(as_of=_NOW)
    revision = _revision(additional_source_bindings=_event_coverage_bindings(snapshot))
    row = Mock(
        status="DRAFT",
        expires_at=revision.identity.valid_until,
        approval_request_id=None,
    )
    manager = Mock()
    manager.select_for_update.return_value.get.return_value = row
    validator = Mock()
    validator.assess.return_value = TransitionPlanEventReviewAssessment(
        state=TransitionPlanEventReviewState.UNCHANGED,
        reason_code="EVENTS_UNCHANGED",
    )
    repository = DjangoTransitionPlanRevisionRepository(event_review_validator=validator)
    monkeypatch.setattr(repository, "_manager", lambda: manager)
    monkeypatch.setattr(repository, "_locked_account_revisions", lambda account_id: (revision,))
    monkeypatch.setattr(repository, "now", lambda: revision.identity.valid_until)
    monkeypatch.setattr(
        "apps.portfolio.infrastructure.transition_plan_revision_repository.transaction.atomic",
        lambda using: nullcontext(),
    )

    with pytest.raises(BusinessLogicError) as error:
        repository.submit_for_review(
            revision=revision,
            owner_user_id=revision.identity.owner_user_id,
            review_subject_id="review-1",
            requested_at=_NOW + timedelta(seconds=30),
        )

    assert error.value.code == "TRANSITION_PLAN_REVISION_EXPIRED"
    validator.assess.assert_called_once_with(
        revision,
        as_of=revision.identity.valid_until,
    )
    row.save.assert_not_called()


def test_owner_journey_review_uses_current_event_validator() -> None:
    """The registered journey path blocks review when an event arrives after pinning."""

    current_at = _NOW + timedelta(seconds=30)
    baseline = _event_snapshot(as_of=_NOW)
    revision = _revision(additional_source_bindings=_event_coverage_bindings(baseline))
    changed = _event_snapshot(
        as_of=current_at,
        events=(
            _event_revision(
                source_event_id="new-event",
                available_at=_NOW + timedelta(seconds=10),
                known_at=_NOW + timedelta(seconds=10),
            ),
        ),
    )
    repository = _LifecycleRepository()
    repository._store(revision, revision.plan.idempotency_key)
    journey = RebalanceJourneyApplication(
        repository=repository,
        authorizer=_LifecycleAuthorizer(),
        clock=_LifecycleClock(current_at),
        preparation_factory=Mock(),
        progress_reader=Mock(),
        order_previewer=Mock(),
        event_review_validator=AssessTransitionPlanEventReview(
            reader=_EventSnapshotReader((baseline, changed)),
            lease_policy=_event_lease_policy(),
        ),
    )

    with pytest.raises(TransitionPlanEventReviewRequired):
        journey.execute(
            RebalanceJourneyCommand(
                action="review",
                user_id=23,
                account_id=17,
                plan_id=revision.identity.plan_id,
                plan_version=revision.identity.version,
                revision_hash=revision.identity.revision_hash,
                request_key="review-event-drift",
            )
        )
    assert repository.review_calls == 0


def test_unrelated_owner_review_still_works_without_event_reader() -> None:
    """An unrelated source-bound revision remains reviewable without event infrastructure."""

    revision = _revision()
    repository = _LifecycleRepository()
    repository._store(revision, revision.plan.idempotency_key)
    use_case = RequestTransitionPlanRevisionReviewUseCase(
        repository=repository,
        authorizer=_LifecycleAuthorizer(),
        clock=_LifecycleClock(),
    )

    use_case.execute(
        RequestTransitionPlanRevisionReview(
            actor_user_id=23,
            account_id=17,
            plan_id=revision.identity.plan_id,
            version=revision.identity.version,
            expected_revision_hash=revision.identity.revision_hash,
        )
    )

    assert repository.review_calls == 1


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


def test_event_change_blocks_manual_reservation_inside_locked_account_guard(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The event recheck runs while the action guard still owns the account transaction."""

    revision = _revision(
        additional_source_bindings=_event_coverage_bindings(_event_snapshot(as_of=_NOW))
    )
    lock_state = {"active": False}
    assessment = TransitionPlanEventReviewAssessment(
        state=TransitionPlanEventReviewState.REVIEW_REQUIRED,
        reason_code="EVENT_REVISION_CHANGED",
    )
    validator = _LockCheckingEventValidator(lock_state, assessment)
    guard = DjangoTransitionPlanLockedActionGuard(
        current_policy_pins_validator=_PolicyPinReader(),
        event_review_validator=validator,
    )
    monkeypatch.setattr(
        guard._repository, "_locked_account_revisions", lambda account_id: (revision,)
    )
    monkeypatch.setattr(guard._repository, "_manager", lambda: _RowQuery())
    monkeypatch.setattr(guard, "_approval_repository", _NoReviewArtifacts())

    @contextmanager
    def _atomic(*, using: str) -> Iterator[None]:
        lock_state["active"] = True
        try:
            yield
        finally:
            lock_state["active"] = False

    monkeypatch.setattr(
        "apps.portfolio.infrastructure.transition_plan_revision_repository.transaction.atomic",
        _atomic,
    )
    binding = revision.orders[0].to_execution_binding(
        revision.identity,
        owner_user_id=23,
        action_attempt_key="event-review-manual-attempt",
    )

    with pytest.raises(TransitionPlanEventReviewRequired):
        guard.validate_locked_action(
            binding=binding,
            account_id=17,
            owner_user_id=23,
            as_of=_NOW + timedelta(seconds=30),
        )

    assert lock_state["active"] is False


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


def test_revision_repository_writes_new_family_and_strictly_reads_marked_legacy_rows() -> None:
    revision = _revision()
    repository = DjangoTransitionPlanRevisionRepository(using="default")
    values = repository._model_values(
        revision,
        idempotency_key=revision.plan.idempotency_key,
    )

    assert values["plan_contract_family"] == PORTFOLIO_PLAN_REVISION_FAMILY
    new_row = SimpleNamespace(**values)
    assert repository._revision_from_row(new_row) == revision

    old_marked_values = dict(values)
    old_marked_values["plan_contract_family"] = CANONICAL_TRANSITION_PLAN_FAMILY
    old_marked_row = SimpleNamespace(**old_marked_values)
    assert repository._revision_from_row(old_marked_row) == revision

    old_unmarked_values = dict(old_marked_values)
    old_unmarked_contract = dict(cast(dict[str, object], values["risk_contract"]))
    old_unmarked_contract.pop(PORTFOLIO_PLAN_REVISION_MARKER)
    old_unmarked_values["risk_contract"] = old_unmarked_contract
    assert repository._revision_from_row(SimpleNamespace(**old_unmarked_values)) is None

    missing_new_marker_values = dict(values)
    missing_new_contract = dict(cast(dict[str, object], values["risk_contract"]))
    missing_new_contract.pop(PORTFOLIO_PLAN_REVISION_MARKER)
    missing_new_marker_values["risk_contract"] = missing_new_contract
    with pytest.raises(TransitionPlanRevisionCorruption):
        repository._revision_from_row(SimpleNamespace(**missing_new_marker_values))

    malformed_old_marker_values = dict(old_marked_values)
    malformed_old_contract = dict(cast(dict[str, object], values["risk_contract"]))
    malformed_old_contract[PORTFOLIO_PLAN_REVISION_MARKER] = None
    malformed_old_marker_values["risk_contract"] = malformed_old_contract
    with pytest.raises(TransitionPlanRevisionCorruption):
        repository._revision_from_row(SimpleNamespace(**malformed_old_marker_values))
