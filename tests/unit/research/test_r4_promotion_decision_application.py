"""Unit coverage for ID-only exact R4 promotion decision orchestration."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import fields
from datetime import datetime, timedelta

import pytest

from apps.portfolio.application.r4_rolling_research_query import (
    R4RollingResearchOwnerRecord,
)
from apps.portfolio.application.r4_rolling_research_record import (
    R4RollingResearchRecord,
)
from apps.portfolio.domain.r4_rolling_evidence import ExactR3PromotionAttestation
from apps.research.application.r4_promotion_decision import (
    EvaluateR4PromotionCommand,
    EvaluateR4PromotionUseCase,
    R4PromotionDecisionBundle,
    R4PromotionDecisionReceipt,
    R4PromotionEvidenceError,
    R4PromotionVersionRef,
)
from apps.research.domain.r4_promotion_decision import R4PromotionDecisionOutcome
from apps.research.domain.r4_promotion_scope_policy import R4PromotionPolicy
from tests.unit.portfolio.macro_risk_rolling_factories import (
    build_study,
    promotion_attestation,
)
from tests.unit.research.r4_promotion_factories import (
    DECIDED_AT,
    portfolio_record,
    promotion_policy,
)


class PolicyProvider:
    def __init__(
        self,
        policy: R4PromotionPolicy | None,
        events: list[str] | None = None,
    ) -> None:
        self.policy = policy
        self.calls: list[tuple[R4PromotionVersionRef, datetime]] = []
        self.events = events

    def get_exact(
        self,
        policy_ref: R4PromotionVersionRef,
        *,
        as_of: datetime,
    ) -> R4PromotionPolicy | None:
        if self.events is not None:
            self.events.append("policy")
        self.calls.append((policy_ref, as_of))
        return self.policy


class PortfolioQuery:
    unit_of_work_key = "django:default"

    def __init__(
        self,
        owner_record: R4RollingResearchOwnerRecord | None,
        events: list[str] | None = None,
    ) -> None:
        self.owner_record = owner_record
        self.calls: list[tuple[str, str, datetime]] = []
        self.events = events

    def get_exact(
        self,
        *,
        record_id: str,
        expected_record_hash: str,
        as_of: datetime,
    ) -> R4RollingResearchOwnerRecord | None:
        if self.events is not None:
            self.events.append("portfolio")
        self.calls.append((record_id, expected_record_hash, as_of))
        return self.owner_record


class CurrentR3Provider:
    def __init__(
        self,
        attestation: ExactR3PromotionAttestation | None,
        events: list[str] | None = None,
    ) -> None:
        self.attestation = attestation
        self.calls: list[tuple[str, str, str, str, str, str, str, datetime]] = []
        self.events = events

    def get_exact(
        self,
        *,
        capability_key: str,
        artifact_id: str,
        artifact_version: str,
        artifact_content_hash: str,
        decision_id: str,
        decision_version: str,
        decision_content_hash: str,
        as_of: datetime,
    ) -> ExactR3PromotionAttestation | None:
        if self.events is not None:
            self.events.append("r3")
        self.calls.append(
            (
                capability_key,
                artifact_id,
                artifact_version,
                artifact_content_hash,
                decision_id,
                decision_version,
                decision_content_hash,
                as_of,
            )
        )
        return self.attestation


class ReceiptProvider:
    unit_of_work_key = "django:default"

    def __init__(self, events: list[str] | None = None) -> None:
        self.calls = 0
        self.events = events

    def get_exact(
        self,
        *,
        decision_ref: R4PromotionVersionRef,
        trial_ref: R4PromotionVersionRef,
        policy_ref: R4PromotionVersionRef,
        policy_content_hash: str,
        portfolio_record_id: str,
        portfolio_record_hash: str,
        portfolio_owner_record_key: str,
        portfolio_recorded_at: datetime,
        current_r3_content_hash: str,
        decided_at: datetime,
        decision_valid_until: datetime,
    ) -> R4PromotionDecisionReceipt | None:
        if self.events is not None:
            self.events.append("receipt")
        self.calls += 1
        return R4PromotionDecisionReceipt.create(
            receipt_id=f"receipt:{decision_ref.stable_id}",
            receipt_version="receipt.v1",
            decision_ref=decision_ref,
            trial_ref=trial_ref,
            policy_ref=policy_ref,
            policy_content_hash=policy_content_hash,
            portfolio_record_id=portfolio_record_id,
            portfolio_record_hash=portfolio_record_hash,
            portfolio_owner_record_key=portfolio_owner_record_key,
            portfolio_recorded_at=portfolio_recorded_at,
            current_r3_content_hash=current_r3_content_hash,
            decided_at=decided_at,
            recorded_at=decided_at + timedelta(minutes=1),
            decision_valid_until=decision_valid_until,
        )


class Repository:
    unit_of_work_key = "django:default"

    def __init__(self, events: list[str] | None = None) -> None:
        self.bundles: dict[tuple[str, str], R4PromotionDecisionBundle] = {}
        self.events = events

    @contextmanager
    def atomic(self) -> Iterator[None]:
        if self.events is not None:
            self.events.append("atomic-enter")
        try:
            yield
        finally:
            if self.events is not None:
                self.events.append("atomic-exit")

    def append_decision_bundle(
        self,
        bundle: R4PromotionDecisionBundle,
    ) -> R4PromotionDecisionBundle:
        if self.events is not None:
            self.events.append("append")
        key = (bundle.decision.decision_id, bundle.decision.decision_version)
        existing = self.bundles.get(key)
        if existing is not None and existing != bundle:
            raise ValueError("decision conflict")
        self.bundles[key] = bundle
        return bundle

    def get_decision_bundle(
        self,
        decision_ref: R4PromotionVersionRef,
        *,
        as_of: datetime,
    ) -> R4PromotionDecisionBundle | None:
        bundle = self.bundles.get((decision_ref.stable_id, decision_ref.version))
        if bundle is None or bundle.decision.recorded_at > as_of:
            return None
        return bundle


def _command(record: R4RollingResearchRecord) -> EvaluateR4PromotionCommand:
    return EvaluateR4PromotionCommand(
        output_decision_ref=R4PromotionVersionRef("r4-decision-app", "decision.v1"),
        output_trial_ref=R4PromotionVersionRef("r4-trial-app", "trial.v1"),
        policy_ref=R4PromotionVersionRef("r4-promotion-policy-main", "policy.v1"),
        portfolio_record_id=record.record_id,
        expected_portfolio_record_hash=record.record_hash,
        as_of=DECIDED_AT,
    )


def _use_case(
    *,
    policy: R4PromotionPolicy | None,
    owner_record: R4RollingResearchOwnerRecord | None,
    current_r3: ExactR3PromotionAttestation | None,
    receipt_provider: ReceiptProvider | None = None,
    repository: Repository | None = None,
    events: list[str] | None = None,
) -> tuple[EvaluateR4PromotionUseCase, PolicyProvider, PortfolioQuery, CurrentR3Provider]:
    policy_provider = PolicyProvider(policy, events)
    portfolio_query = PortfolioQuery(owner_record, events)
    r3_provider = CurrentR3Provider(current_r3, events)
    use_case = EvaluateR4PromotionUseCase(
        policy_provider=policy_provider,
        portfolio_query=portfolio_query,
        current_r3_provider=r3_provider,
        receipt_provider=receipt_provider or ReceiptProvider(events),
        repository=repository or Repository(events),
    )
    return use_case, policy_provider, portfolio_query, r3_provider


def test_command_is_id_only_and_use_case_rereads_all_exact_owner_evidence() -> None:
    record = portfolio_record()
    owner_record = R4RollingResearchOwnerRecord.create(record)
    policy = promotion_policy()
    use_case, policy_provider, portfolio_query, r3_provider = _use_case(
        policy=policy,
        owner_record=owner_record,
        current_r3=promotion_attestation(),
    )

    decision = use_case.execute(_command(record))

    assert {field.name for field in fields(EvaluateR4PromotionCommand)} == {
        "output_decision_ref",
        "output_trial_ref",
        "policy_ref",
        "portfolio_record_id",
        "expected_portfolio_record_hash",
        "as_of",
    }
    assert decision.outcome is R4PromotionDecisionOutcome.APPROVED
    assert policy_provider.calls == [(_command(record).policy_ref, DECIDED_AT)]
    assert portfolio_query.calls == [(record.record_id, record.record_hash, DECIDED_AT)]
    assert len(r3_provider.calls) == 1
    assert r3_provider.calls[0][0] == "macro_factor_r3"
    assert r3_provider.calls[0][-1] == DECIDED_AT


def test_missing_policy_portfolio_or_current_r3_fails_before_receipt_claim() -> None:
    record = portfolio_record()
    owner_record = R4RollingResearchOwnerRecord.create(record)
    receipt = ReceiptProvider()
    cases = (
        (None, owner_record, promotion_attestation(), "policy"),
        (promotion_policy(), None, promotion_attestation(), "Portfolio"),
        (promotion_policy(), owner_record, None, "current R3"),
    )
    for policy, portfolio, r3, expected in cases:
        use_case, _, _, _ = _use_case(
            policy=policy,
            owner_record=portfolio,
            current_r3=r3,
            receipt_provider=receipt,
        )
        with pytest.raises(R4PromotionEvidenceError, match=expected):
            use_case.execute(_command(record))
    assert receipt.calls == 0


def test_blocked_portfolio_record_is_persisted_as_derived_rejection() -> None:
    record = portfolio_record(study=build_study(minimum_regime_windows=3))
    repository = Repository()
    use_case, _, _, _ = _use_case(
        policy=promotion_policy(),
        owner_record=R4RollingResearchOwnerRecord.create(record),
        current_r3=promotion_attestation(),
        repository=repository,
    )

    decision = use_case.execute(_command(record))

    assert decision.outcome is R4PromotionDecisionOutcome.REJECTED
    assert "trial_ready_not_met" in decision.reason_codes
    assert repository.bundles


def test_receipt_and_repository_must_share_one_unit_of_work() -> None:
    repository = Repository()
    repository.unit_of_work_key = "django:other"

    with pytest.raises(ValueError, match="different units of work"):
        _use_case(
            policy=promotion_policy(),
            owner_record=R4RollingResearchOwnerRecord.create(portfolio_record()),
            current_r3=promotion_attestation(),
            repository=repository,
        )


def test_portfolio_query_receipt_and_repository_share_one_atomic_read_append() -> None:
    events: list[str] = []
    record = portfolio_record()
    use_case, _, _, _ = _use_case(
        policy=promotion_policy(),
        owner_record=R4RollingResearchOwnerRecord.create(record),
        current_r3=promotion_attestation(),
        events=events,
    )

    use_case.execute(_command(record))

    assert events == [
        "atomic-enter",
        "policy",
        "portfolio",
        "r3",
        "receipt",
        "append",
        "atomic-exit",
    ]

    portfolio_query = PortfolioQuery(R4RollingResearchOwnerRecord.create(record))
    portfolio_query.unit_of_work_key = "django:other"
    with pytest.raises(ValueError, match="different units of work"):
        EvaluateR4PromotionUseCase(
            policy_provider=PolicyProvider(promotion_policy()),
            portfolio_query=portfolio_query,
            current_r3_provider=CurrentR3Provider(promotion_attestation()),
            receipt_provider=ReceiptProvider(),
            repository=Repository(),
        )


def test_bundle_rejects_rehashed_receipt_with_substituted_portfolio_recorded_at() -> None:
    record = portfolio_record()
    repository = Repository()
    use_case, _, _, _ = _use_case(
        policy=promotion_policy(),
        owner_record=R4RollingResearchOwnerRecord.create(record),
        current_r3=promotion_attestation(),
        repository=repository,
    )
    use_case.execute(_command(record))
    bundle = next(iter(repository.bundles.values()))
    original = bundle.receipt
    substituted = R4PromotionDecisionReceipt.create(
        receipt_id=original.receipt_id,
        receipt_version=original.receipt_version,
        decision_ref=original.decision_ref,
        trial_ref=original.trial_ref,
        policy_ref=original.policy_ref,
        policy_content_hash=original.policy_content_hash,
        portfolio_record_id=original.portfolio_record_id,
        portfolio_record_hash=original.portfolio_record_hash,
        portfolio_owner_record_key=original.portfolio_owner_record_key,
        portfolio_recorded_at=original.portfolio_recorded_at + timedelta(microseconds=1),
        current_r3_content_hash=original.current_r3_content_hash,
        decided_at=original.decided_at,
        recorded_at=original.recorded_at,
        decision_valid_until=original.decision_valid_until,
    )

    with pytest.raises(ValueError, match="receipt was substituted"):
        R4PromotionDecisionBundle.create(
            decision=bundle.decision,
            receipt=substituted,
        )
