"""Application coverage for ID-only R1 promotion decision materialization."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import fields, replace
from datetime import datetime, timedelta

import pytest

from apps.research.application.r1_forecast_promotion import (
    EvaluateR1ForecastPromotionCommand,
    EvaluateR1ForecastPromotionUseCase,
    ExactEquityTrialResultEvidence,
    R1ForecastPromotionDecisionBundle,
    R1PromotionDecisionReceipt,
    R1PromotionEvidenceError,
    R1PromotionLifecycleEventBundle,
    R1PromotionScopeRef,
    R1PromotionVersionRef,
    _equity_trial_record_hash_values,
)
from apps.research.domain.r1_forecast_promotion import (
    R1ForecastPromotionPolicy,
    R1PromotionLifecycleEvent,
)
from tests.unit.research.test_r1_forecast_promotion import (
    _decision,
    _eligible_result,
    _policy,
)


class _PolicyProvider:
    def __init__(self, policy: R1ForecastPromotionPolicy | None) -> None:
        self.policy = policy
        self.calls: list[tuple[R1PromotionVersionRef, datetime]] = []

    def get_exact(
        self,
        policy_ref: R1PromotionVersionRef,
        *,
        as_of: datetime,
    ) -> R1ForecastPromotionPolicy | None:
        self.calls.append((policy_ref, as_of))
        return self.policy


class _TrialProvider:
    def __init__(self, evidence: ExactEquityTrialResultEvidence | None) -> None:
        self.evidence = evidence
        self.calls: list[tuple[R1PromotionVersionRef, datetime]] = []

    def get_exact(
        self,
        result_ref: R1PromotionVersionRef,
        *,
        as_of: datetime,
    ) -> ExactEquityTrialResultEvidence | None:
        self.calls.append((result_ref, as_of))
        return self.evidence


class _ReceiptProvider:
    def __init__(self, receipt: R1PromotionDecisionReceipt | None) -> None:
        self.receipt = receipt
        self.calls: list[
            tuple[
                R1PromotionVersionRef,
                R1PromotionVersionRef,
                str,
                R1PromotionVersionRef,
                str,
                datetime,
                str,
                datetime,
                datetime,
            ]
        ] = []

    @property
    def unit_of_work_key(self) -> str:
        return "fake:r1"

    def get_exact(
        self,
        *,
        decision_ref: R1PromotionVersionRef,
        policy_ref: R1PromotionVersionRef,
        policy_content_hash: str,
        result_ref: R1PromotionVersionRef,
        result_content_hash: str,
        equity_result_recorded_at: datetime,
        equity_result_record_hash: str,
        decided_at: datetime,
        decision_valid_until: datetime,
    ) -> R1PromotionDecisionReceipt | None:
        self.calls.append(
            (
                decision_ref,
                policy_ref,
                policy_content_hash,
                result_ref,
                result_content_hash,
                equity_result_recorded_at,
                equity_result_record_hash,
                decided_at,
                decision_valid_until,
            )
        )
        return self.receipt


class _Repository:
    def __init__(
        self,
        *,
        append_override: R1ForecastPromotionDecisionBundle | None = None,
        lifecycle_append_override: R1PromotionLifecycleEventBundle | None = None,
    ) -> None:
        self.records: dict[tuple[str, str], R1ForecastPromotionDecisionBundle] = {}
        self.appended: list[R1ForecastPromotionDecisionBundle] = []
        self.append_override = append_override
        self.lifecycle_bundles: dict[tuple[str, str], R1PromotionLifecycleEventBundle] = {}
        self.lifecycle_appended: list[R1PromotionLifecycleEventBundle] = []
        self.lifecycle_append_override = lifecycle_append_override

    @property
    def unit_of_work_key(self) -> str:
        return "fake:r1"

    @contextmanager
    def atomic(self) -> Iterator[None]:
        records = dict(self.records)
        appended = list(self.appended)
        lifecycle_bundles = dict(self.lifecycle_bundles)
        lifecycle_appended = list(self.lifecycle_appended)
        try:
            yield
        except Exception:
            self.records = records
            self.appended = appended
            self.lifecycle_bundles = lifecycle_bundles
            self.lifecycle_appended = lifecycle_appended
            raise

    def append_decision_bundle(
        self,
        bundle: R1ForecastPromotionDecisionBundle,
    ) -> R1ForecastPromotionDecisionBundle:
        self.appended.append(bundle)
        if self.append_override is not None:
            return self.append_override
        key = (bundle.decision.decision_id, bundle.decision.decision_version)
        return self.records.setdefault(key, bundle)

    def get_decision_bundle(
        self,
        decision_ref: R1PromotionVersionRef,
        *,
        as_of: datetime,
    ) -> R1ForecastPromotionDecisionBundle | None:
        candidate = self.records.get((decision_ref.stable_id, decision_ref.version))
        if candidate is None or candidate.decision.recorded_at > as_of:
            return None
        return candidate

    def load_lifecycle_history(
        self,
        scope_ref: R1PromotionScopeRef,
        *,
        as_of: datetime,
    ) -> tuple[R1PromotionLifecycleEvent, ...]:
        return tuple(
            sorted(
                (
                    event
                    for bundle in self.lifecycle_bundles.values()
                    for event in (bundle.event,)
                    if event.promotion_scope.scope_id == scope_ref.scope_id
                    and event.recorded_at <= as_of
                ),
                key=lambda event: event.sequence,
            )
        )

    def get_lifecycle_event_bundle(
        self,
        event_ref: R1PromotionVersionRef,
    ) -> R1PromotionLifecycleEventBundle | None:
        return self.lifecycle_bundles.get((event_ref.stable_id, event_ref.version))

    def load_lifecycle_stream(
        self,
        scope_ref: R1PromotionScopeRef,
    ) -> tuple[R1PromotionLifecycleEvent, ...]:
        return tuple(
            sorted(
                (
                    event
                    for bundle in self.lifecycle_bundles.values()
                    for event in (bundle.event,)
                    if event.promotion_scope.scope_id == scope_ref.scope_id
                ),
                key=lambda event: event.sequence,
            )
        )

    def append_lifecycle_event_bundle(
        self,
        bundle: R1PromotionLifecycleEventBundle,
    ) -> R1PromotionLifecycleEventBundle:
        self.lifecycle_appended.append(bundle)
        if self.lifecycle_append_override is not None:
            return self.lifecycle_append_override
        key = (bundle.event.event_id, bundle.event.event_version)
        return self.lifecycle_bundles.setdefault(key, bundle)


def _inputs(
    *,
    trial_recorded_at: datetime | None = None,
    receipt_recorded_at: datetime | None = None,
) -> tuple[
    EvaluateR1ForecastPromotionCommand,
    R1ForecastPromotionPolicy,
    ExactEquityTrialResultEvidence,
    R1PromotionDecisionReceipt,
]:
    result = _eligible_result()
    policy = _policy(result=result)
    as_of = result.evaluated_at + timedelta(hours=1)
    command = EvaluateR1ForecastPromotionCommand(
        output_decision_ref=R1PromotionVersionRef(
            "research-r1-promotion:application",
            "decision.v1",
        ),
        policy_ref=R1PromotionVersionRef(policy.policy_id, policy.policy_version),
        equity_result_ref=R1PromotionVersionRef(result.result_id, result.result_version),
        as_of=as_of,
    )
    evidence = ExactEquityTrialResultEvidence.create(
        result=result,
        recorded_at=trial_recorded_at or result.evaluated_at + timedelta(minutes=1),
    )
    receipt = R1PromotionDecisionReceipt.create(
        receipt_id="research-r1-promotion-receipt:application",
        receipt_version="receipt.v1",
        decision_ref=command.output_decision_ref,
        policy_ref=command.policy_ref,
        policy_content_hash=policy.content_hash,
        result_ref=command.equity_result_ref,
        result_content_hash=result.content_hash,
        equity_result_recorded_at=evidence.recorded_at,
        equity_result_record_hash=evidence.record_hash,
        decided_at=command.as_of,
        recorded_at=receipt_recorded_at or command.as_of + timedelta(minutes=1),
        decision_valid_until=min(
            evidence.result.valid_until,
            policy.active_until,
            command.as_of + timedelta(seconds=policy.decision_validity_seconds),
        ),
    )
    return command, policy, evidence, receipt


def _use_case(
    *,
    command: EvaluateR1ForecastPromotionCommand,
    policy: R1ForecastPromotionPolicy | None,
    evidence: ExactEquityTrialResultEvidence | None,
    receipt: R1PromotionDecisionReceipt | None,
    repository: _Repository | None = None,
) -> tuple[
    EvaluateR1ForecastPromotionUseCase,
    _PolicyProvider,
    _TrialProvider,
    _ReceiptProvider,
    _Repository,
]:
    del command
    policy_provider = _PolicyProvider(policy)
    trial_provider = _TrialProvider(evidence)
    receipt_provider = _ReceiptProvider(receipt)
    ledger = repository or _Repository()
    return (
        EvaluateR1ForecastPromotionUseCase(
            policy_provider=policy_provider,
            trial_result_provider=trial_provider,
            receipt_provider=receipt_provider,
            repository=ledger,
        ),
        policy_provider,
        trial_provider,
        receipt_provider,
        ledger,
    )


def test_evaluate_command_is_id_only_and_rereads_all_owner_evidence() -> None:
    command, policy, evidence, receipt = _inputs()
    use_case, policy_provider, trial_provider, receipt_provider, repository = _use_case(
        command=command,
        policy=policy,
        evidence=evidence,
        receipt=receipt,
    )

    decision = use_case.execute(command)

    assert tuple(item.name for item in fields(EvaluateR1ForecastPromotionCommand)) == (
        "output_decision_ref",
        "policy_ref",
        "equity_result_ref",
        "as_of",
    )
    assert policy_provider.calls == [(command.policy_ref, command.as_of)]
    assert trial_provider.calls == [(command.equity_result_ref, command.as_of)]
    assert receipt_provider.calls == [
        (
            command.output_decision_ref,
            command.policy_ref,
            policy.content_hash,
            command.equity_result_ref,
            evidence.result.content_hash,
            evidence.recorded_at,
            evidence.record_hash,
            command.as_of,
            receipt.decision_valid_until,
        )
    ]
    assert decision.recorded_at == receipt.recorded_at
    assert decision.policy == policy
    assert decision.trial.result_content_hash == evidence.result.content_hash
    assert repository.appended[0].decision == decision
    assert repository.appended[0].receipt == receipt


def test_repeat_uses_stable_owner_receipt_and_returns_exact_replay() -> None:
    command, policy, evidence, receipt = _inputs()
    use_case, _, _, receipt_provider, repository = _use_case(
        command=command,
        policy=policy,
        evidence=evidence,
        receipt=receipt,
    )

    first = use_case.execute(command)
    second = use_case.execute(command)

    assert first == second
    assert len(receipt_provider.calls) == 2
    assert (
        repository.records[
            (command.output_decision_ref.stable_id, command.output_decision_ref.version)
        ].decision
        == first
    )


@pytest.mark.parametrize("missing", ["policy", "trial", "receipt"])
def test_missing_exact_owner_evidence_fails_closed(missing: str) -> None:
    command, policy, evidence, receipt = _inputs()
    use_case, *_ = _use_case(
        command=command,
        policy=None if missing == "policy" else policy,
        evidence=None if missing == "trial" else evidence,
        receipt=None if missing == "receipt" else receipt,
    )

    with pytest.raises(R1PromotionEvidenceError, match="exact|owner"):
        use_case.execute(command)


def test_late_owner_row_cannot_be_backfilled_into_an_earlier_decision() -> None:
    command, policy, original_evidence, receipt = _inputs()
    evidence = ExactEquityTrialResultEvidence.create(
        result=original_evidence.result,
        recorded_at=command.as_of + timedelta(seconds=1),
    )
    use_case, *_ = _use_case(
        command=command,
        policy=policy,
        evidence=evidence,
        receipt=receipt,
    )

    with pytest.raises(R1PromotionEvidenceError, match="owner receipt is invalid"):
        use_case.execute(command)


def test_provider_cannot_substitute_policy_or_result_identity() -> None:
    command, policy, evidence, receipt = _inputs()
    wrong_policy_command = EvaluateR1ForecastPromotionCommand(
        output_decision_ref=command.output_decision_ref,
        policy_ref=R1PromotionVersionRef("research-r1-policy:other", "policy.v1"),
        equity_result_ref=command.equity_result_ref,
        as_of=command.as_of,
    )
    policy_use_case, *_ = _use_case(
        command=wrong_policy_command,
        policy=policy,
        evidence=evidence,
        receipt=receipt,
    )
    with pytest.raises(R1PromotionEvidenceError, match="policy is unavailable"):
        policy_use_case.execute(wrong_policy_command)

    wrong_result_command = EvaluateR1ForecastPromotionCommand(
        output_decision_ref=command.output_decision_ref,
        policy_ref=command.policy_ref,
        equity_result_ref=R1PromotionVersionRef("r1-trial-result:other", "trial-result.v1"),
        as_of=command.as_of,
    )
    result_use_case, *_ = _use_case(
        command=wrong_result_command,
        policy=policy,
        evidence=evidence,
        receipt=receipt,
    )
    with pytest.raises(R1PromotionEvidenceError, match="identity or owner receipt"):
        result_use_case.execute(wrong_result_command)


def test_canonical_but_wrong_self_signed_receipt_is_rejected() -> None:
    command, policy, evidence, _ = _inputs()
    fabricated = R1PromotionDecisionReceipt.create(
        receipt_id="research-r1-promotion-receipt:fabricated",
        receipt_version="receipt.v1",
        decision_ref=command.output_decision_ref,
        policy_ref=command.policy_ref,
        policy_content_hash="f" * 64,
        result_ref=command.equity_result_ref,
        result_content_hash=evidence.result.content_hash,
        equity_result_recorded_at=evidence.recorded_at,
        equity_result_record_hash=evidence.record_hash,
        decided_at=command.as_of,
        recorded_at=command.as_of + timedelta(minutes=1),
        decision_valid_until=min(
            evidence.result.valid_until,
            policy.active_until,
            command.as_of + timedelta(seconds=policy.decision_validity_seconds),
        ),
    )
    use_case, *_ = _use_case(
        command=command,
        policy=policy,
        evidence=evidence,
        receipt=fabricated,
    )

    with pytest.raises(R1PromotionEvidenceError, match="owner decision receipt"):
        use_case.execute(command)


def test_repository_must_return_the_exact_appended_decision() -> None:
    command, policy, evidence, receipt = _inputs()
    other_decision = _decision()
    repository = _Repository(
        append_override=R1ForecastPromotionDecisionBundle.create(
            decision=other_decision,
            receipt=R1PromotionDecisionReceipt.create(
                receipt_id="research-r1-promotion-receipt:other",
                receipt_version="receipt.v1",
                decision_ref=R1PromotionVersionRef(
                    other_decision.decision_id,
                    other_decision.decision_version,
                ),
                policy_ref=R1PromotionVersionRef(
                    other_decision.policy.policy_id,
                    other_decision.policy.policy_version,
                ),
                policy_content_hash=other_decision.policy.content_hash,
                result_ref=R1PromotionVersionRef(
                    other_decision.trial.result_id,
                    other_decision.trial.result_version,
                ),
                result_content_hash=other_decision.trial.result_content_hash,
                equity_result_recorded_at=evidence.recorded_at,
                equity_result_record_hash=evidence.record_hash,
                decided_at=other_decision.decided_at,
                recorded_at=other_decision.recorded_at,
                decision_valid_until=other_decision.valid_until,
            ),
        )
    )
    use_case, *_ = _use_case(
        command=command,
        policy=policy,
        evidence=evidence,
        receipt=receipt,
        repository=repository,
    )

    with pytest.raises(R1PromotionEvidenceError, match="preserve the exact decision bundle"):
        use_case.execute(command)


def test_receipt_time_and_hash_substitution_is_rejected_before_append() -> None:
    command, policy, evidence, _ = _inputs()
    substituted_evidence = ExactEquityTrialResultEvidence.create(
        result=evidence.result,
        recorded_at=evidence.recorded_at + timedelta(seconds=1),
    )
    substituted_receipt = R1PromotionDecisionReceipt.create(
        receipt_id="research-r1-promotion-receipt:substituted-equity-row",
        receipt_version="receipt.v1",
        decision_ref=command.output_decision_ref,
        policy_ref=command.policy_ref,
        policy_content_hash=policy.content_hash,
        result_ref=command.equity_result_ref,
        result_content_hash=evidence.result.content_hash,
        equity_result_recorded_at=substituted_evidence.recorded_at,
        equity_result_record_hash=substituted_evidence.record_hash,
        decided_at=command.as_of,
        recorded_at=command.as_of + timedelta(minutes=1),
        decision_valid_until=min(
            evidence.result.valid_until,
            policy.active_until,
            command.as_of + timedelta(seconds=policy.decision_validity_seconds),
        ),
    )
    use_case, *_ = _use_case(
        command=command,
        policy=policy,
        evidence=evidence,
        receipt=substituted_receipt,
    )

    with pytest.raises(R1PromotionEvidenceError, match="owner decision receipt"):
        use_case.execute(command)


def test_direct_bundle_rejects_late_equity_receipt_and_raw_hash_tamper() -> None:
    command, policy, evidence, receipt = _inputs()
    late_evidence = ExactEquityTrialResultEvidence.create(
        result=evidence.result,
        recorded_at=command.as_of + timedelta(seconds=1),
    )
    with pytest.raises(ValueError, match="receipt knowledge-time chain"):
        R1PromotionDecisionReceipt.create(
            receipt_id="research-r1-promotion-receipt:late-equity-row",
            receipt_version="receipt.v1",
            decision_ref=command.output_decision_ref,
            policy_ref=command.policy_ref,
            policy_content_hash=policy.content_hash,
            result_ref=command.equity_result_ref,
            result_content_hash=evidence.result.content_hash,
            equity_result_recorded_at=late_evidence.recorded_at,
            equity_result_record_hash=late_evidence.record_hash,
            decided_at=command.as_of,
            recorded_at=command.as_of + timedelta(minutes=1),
            decision_valid_until=receipt.decision_valid_until,
        )

    use_case, *_, repository = _use_case(
        command=command,
        policy=policy,
        evidence=evidence,
        receipt=receipt,
    )
    decision = use_case.execute(command)
    bundle = repository.appended[0]
    early_equity_recorded_at = decision.trial.evaluated_at - timedelta(seconds=1)
    early_receipt = R1PromotionDecisionReceipt.create(
        receipt_id="research-r1-promotion-receipt:early-equity-row",
        receipt_version="receipt.v1",
        decision_ref=command.output_decision_ref,
        policy_ref=command.policy_ref,
        policy_content_hash=policy.content_hash,
        result_ref=command.equity_result_ref,
        result_content_hash=evidence.result.content_hash,
        equity_result_recorded_at=early_equity_recorded_at,
        equity_result_record_hash=_equity_trial_record_hash_values(
            result_id=decision.trial.result_id,
            result_version=decision.trial.result_version,
            result_content_hash=decision.trial.result_content_hash,
            owner="equity",
            recorded_at=early_equity_recorded_at,
        ),
        decided_at=decision.decided_at,
        recorded_at=decision.recorded_at,
        decision_valid_until=decision.valid_until,
    )

    with pytest.raises(ValueError, match="knowledge-time chain"):
        R1ForecastPromotionDecisionBundle.create(
            decision=decision,
            receipt=early_receipt,
        )
    with pytest.raises(ValueError, match="bundle content hash mismatch"):
        replace(bundle, content_hash="0" * 64)
