"""ID-only owner-reread orchestration for R5 promotion decisions."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, replace
from datetime import datetime, timedelta

import pytest

from apps.fixed_income.application.relative_value_persistence import (
    R5PersistedRelativeValueBundle,
)
from apps.research.application.r5_relative_value_promotion_decision import (
    EvaluateR5RelativeValuePromotion,
    EvaluateR5RelativeValuePromotionCommand,
    R5RelativeValueDecisionAuthorization,
    R5RelativeValuePromotionDecisionBundle,
    R5RelativeValuePromotionEvidenceError,
    R5RelativeValuePromotionRef,
)
from apps.research.domain.r5_relative_value_portfolio_outcome import (
    R5PortfolioOutcomeSeal,
)
from apps.research.domain.r5_relative_value_promotion_decision import (
    r5_relative_value_promotion_decision_valid_until,
)
from apps.research.domain.r5_relative_value_promotion_policy import (
    R5RelativeValuePromotionPolicy,
)
from apps.research.domain.r5_relative_value_promotion_trial import (
    R5RelativeValuePromotionTrial,
    R5RelativeValueTrialObservation,
)
from tests.unit.research.r5_relative_value_promotion_factories import (
    BASE_TIME,
    make_observations,
    make_persisted_bundles,
    make_policy,
    make_trial,
)


@dataclass
class _PolicyProvider:
    item: R5RelativeValuePromotionPolicy | None
    unit_of_work_key: str = "uow"
    calls: int = 0

    def get_exact(
        self,
        policy_ref: R5RelativeValuePromotionRef,
        *,
        as_of: datetime,
    ) -> R5RelativeValuePromotionPolicy | None:
        self.calls += 1
        return self.item


@dataclass
class _TrialProvider:
    item: R5RelativeValuePromotionTrial | None
    unit_of_work_key: str = "uow"
    calls: int = 0

    def get_exact(
        self,
        trial_ref: R5RelativeValuePromotionRef,
        *,
        as_of: datetime,
    ) -> R5RelativeValuePromotionTrial | None:
        self.calls += 1
        return self.item


class _RecordProvider:
    def __init__(
        self,
        bundles: tuple[R5PersistedRelativeValueBundle, ...],
        *,
        unit_of_work_key: str = "uow",
    ) -> None:
        self.unit_of_work_key = unit_of_work_key
        self._bundles = {
            (
                item.result.result_id,
                item.result.result_version,
                item.result.record_hash,
            ): item
            for item in bundles
        }
        self.calls: list[tuple[str, str, str, datetime]] = []

    def get_exact(
        self,
        *,
        result_id: str,
        result_version: str,
        expected_record_hash: str,
        as_of: datetime,
    ) -> R5PersistedRelativeValueBundle | None:
        self.calls.append((result_id, result_version, expected_record_hash, as_of))
        return self._bundles.get((result_id, result_version, expected_record_hash))


class _OutcomeProvider:
    def __init__(
        self,
        outcomes: tuple[R5PortfolioOutcomeSeal, ...],
        *,
        unit_of_work_key: str = "uow",
    ) -> None:
        self.unit_of_work_key = unit_of_work_key
        self._outcomes = {
            (
                item.outcome_id,
                item.outcome_version,
                item.owner_record_hash,
            ): item
            for item in outcomes
        }
        self.calls: list[tuple[str, str, str, datetime]] = []

    def get_exact(
        self,
        *,
        outcome_ref: R5RelativeValuePromotionRef,
        expected_owner_record_hash: str,
        as_of: datetime,
    ) -> R5PortfolioOutcomeSeal | None:
        self.calls.append(
            (
                outcome_ref.stable_id,
                outcome_ref.version,
                expected_owner_record_hash,
                as_of,
            )
        )
        return self._outcomes.get(
            (
                outcome_ref.stable_id,
                outcome_ref.version,
                expected_owner_record_hash,
            )
        )


@dataclass
class _AuthorizationProvider:
    item: R5RelativeValueDecisionAuthorization | None
    unit_of_work_key: str = "uow"
    calls: int = 0

    def get_exact(
        self,
        *,
        authorization_ref: R5RelativeValuePromotionRef,
        policy_ref: R5RelativeValuePromotionRef,
        trial_ref: R5RelativeValuePromotionRef,
        as_of: datetime,
    ) -> R5RelativeValueDecisionAuthorization | None:
        self.calls += 1
        return self.item


class _Repository:
    unit_of_work_key = "uow"

    def __init__(self) -> None:
        self.active = False
        self.items: dict[tuple[str, str], R5RelativeValuePromotionDecisionBundle] = {}

    @contextmanager
    def atomic(self) -> Iterator[None]:
        assert not self.active
        self.active = True
        try:
            yield
        finally:
            self.active = False

    def append_decision_bundle(
        self,
        bundle: R5RelativeValuePromotionDecisionBundle,
    ) -> R5RelativeValuePromotionDecisionBundle:
        assert self.active
        key = (bundle.decision.decision_id, bundle.decision.decision_version)
        existing = self.items.get(key)
        if existing is not None:
            return existing
        self.items[key] = bundle
        return bundle

    def get_decision_bundle(
        self,
        decision_ref: R5RelativeValuePromotionRef,
        *,
        as_of: datetime,
    ) -> R5RelativeValuePromotionDecisionBundle | None:
        item = self.items.get((decision_ref.stable_id, decision_ref.version))
        if item is None or item.decision.recorded_at > as_of:
            return None
        return item


@dataclass(frozen=True)
class _Graph:
    bundles: tuple[R5PersistedRelativeValueBundle, R5PersistedRelativeValueBundle]
    policy: R5RelativeValuePromotionPolicy
    trial: R5RelativeValuePromotionTrial
    authorization: R5RelativeValueDecisionAuthorization
    command: EvaluateR5RelativeValuePromotionCommand


def _graph(monkeypatch: pytest.MonkeyPatch) -> _Graph:
    bundles = make_persisted_bundles(monkeypatch)
    observations = make_observations(monkeypatch, bundles=bundles)
    policy = make_policy()
    trial = make_trial(monkeypatch, policy=policy, observations=observations)
    as_of = BASE_TIME + timedelta(hours=3, minutes=1)
    policy_ref = R5RelativeValuePromotionRef(
        policy.policy_id,
        policy.policy_version,
    )
    trial_ref = R5RelativeValuePromotionRef(trial.trial_id, trial.trial_version)
    authorization = R5RelativeValueDecisionAuthorization.create(
        authorization_version="decision-auth-v1",
        scope_id=policy.scope.scope_id,
        scope_content_hash=policy.scope.content_hash,
        policy_ref=policy_ref,
        trial_ref=trial_ref,
        issued_at=as_of - timedelta(minutes=1),
        recorded_at=as_of,
        decided_at=as_of,
        decision_recorded_at=as_of + timedelta(minutes=1),
        decision_valid_until=r5_relative_value_promotion_decision_valid_until(
            policy=policy,
            trial=trial,
            decided_at=as_of,
        ),
        valid_until=trial.valid_until,
    )
    return _Graph(
        bundles=bundles,
        policy=policy,
        trial=trial,
        authorization=authorization,
        command=EvaluateR5RelativeValuePromotionCommand(
            policy_ref=policy_ref,
            trial_ref=trial_ref,
            authorization_ref=R5RelativeValuePromotionRef(
                authorization.authorization_id,
                authorization.authorization_version,
            ),
            as_of=as_of,
        ),
    )


def _use_case(
    graph: _Graph,
    *,
    policy_provider: _PolicyProvider | None = None,
    trial_provider: _TrialProvider | None = None,
    record_provider: _RecordProvider | None = None,
    outcome_provider: _OutcomeProvider | None = None,
    authorization_provider: _AuthorizationProvider | None = None,
    repository: _Repository | None = None,
) -> tuple[EvaluateR5RelativeValuePromotion, _RecordProvider, _Repository]:
    records = record_provider or _RecordProvider(graph.bundles)
    repo = repository or _Repository()
    return (
        EvaluateR5RelativeValuePromotion(
            policy_provider=policy_provider or _PolicyProvider(graph.policy),
            trial_provider=trial_provider or _TrialProvider(graph.trial),
            owner_record_provider=records,
            portfolio_outcome_provider=outcome_provider
            or _OutcomeProvider(tuple(item.portfolio_outcome for item in graph.trial.observations)),
            authorization_provider=authorization_provider
            or _AuthorizationProvider(graph.authorization),
            repository=repo,
        ),
        records,
        repo,
    )


def test_command_is_id_only_and_every_owner_is_dynamically_reread(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Caller supplies no result hash, gate, metric, outcome or decision ID."""

    graph = _graph(monkeypatch)
    outcomes = _OutcomeProvider(tuple(item.portfolio_outcome for item in graph.trial.observations))
    use_case, records, repository = _use_case(
        graph,
        outcome_provider=outcomes,
    )

    decision = use_case.execute(graph.command)

    assert set(vars(graph.command)) == {
        "policy_ref",
        "trial_ref",
        "authorization_ref",
        "as_of",
    }
    assert len(records.calls) == 2
    assert len(outcomes.calls) == 2
    assert repository.items
    assert decision.research_only
    assert decision.must_not_use_for_decision
    assert decision.must_not_execute


def test_missing_real_result_or_authorization_is_stably_blocked(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """No data and no owner authority remain fail-closed, not synthesized."""

    graph = _graph(monkeypatch)
    use_case, _, repository = _use_case(
        graph,
        record_provider=_RecordProvider(()),
    )
    with pytest.raises(R5RelativeValuePromotionEvidenceError) as missing_result:
        use_case.execute(graph.command)
    assert missing_result.value.reason_code == "r5_promotion.owner_record_missing"
    assert not repository.items

    use_case, _, repository = _use_case(
        graph,
        outcome_provider=_OutcomeProvider(()),
    )
    with pytest.raises(R5RelativeValuePromotionEvidenceError) as missing_outcome:
        use_case.execute(graph.command)
    assert missing_outcome.value.reason_code == "r5_promotion.portfolio_outcome_missing"
    assert not repository.items

    use_case, _, repository = _use_case(
        graph,
        authorization_provider=_AuthorizationProvider(None),
    )
    with pytest.raises(R5RelativeValuePromotionEvidenceError) as missing_auth:
        use_case.execute(graph.command)
    assert missing_auth.value.reason_code == "r5_promotion.authorization_missing"
    assert not repository.items


def test_provider_substitution_and_same_authorization_id_reseal_fail_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Provider labels and public dataclass construction cannot replace evidence."""

    graph = _graph(monkeypatch)
    substituted_policy = make_policy(
        minimum_excess_net_return=graph.policy.minimum_excess_net_return + 1
    )
    use_case, _, _ = _use_case(
        graph,
        policy_provider=_PolicyProvider(substituted_policy),
    )
    with pytest.raises(R5RelativeValuePromotionEvidenceError) as substituted:
        use_case.execute(graph.command)
    assert substituted.value.reason_code == "r5_promotion.evidence_substituted"

    with pytest.raises(ValueError, match="content hash|identity"):
        replace(
            graph.authorization,
            decision_recorded_at=graph.authorization.decision_recorded_at + timedelta(seconds=1),
        )


def test_authorization_cannot_be_reused_or_extend_derived_validity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """One authorization binds one exact decision clock and expiry boundary."""

    graph = _graph(monkeypatch)
    reused = replace(
        graph.command,
        as_of=graph.command.as_of + timedelta(seconds=1),
    )
    use_case, _, repository = _use_case(graph)
    with pytest.raises(R5RelativeValuePromotionEvidenceError) as reuse_error:
        use_case.execute(reused)
    assert reuse_error.value.reason_code == "r5_promotion.evidence_substituted"
    assert not repository.items

    extended = R5RelativeValueDecisionAuthorization.create(
        authorization_version="decision-auth-extended-v1",
        scope_id=graph.policy.scope.scope_id,
        scope_content_hash=graph.policy.scope.content_hash,
        policy_ref=graph.command.policy_ref,
        trial_ref=graph.command.trial_ref,
        issued_at=graph.authorization.issued_at,
        recorded_at=graph.authorization.recorded_at,
        decided_at=graph.authorization.decided_at,
        decision_recorded_at=graph.authorization.decision_recorded_at,
        decision_valid_until=graph.authorization.decision_valid_until + timedelta(seconds=1),
        valid_until=graph.authorization.valid_until,
    )
    command = replace(
        graph.command,
        authorization_ref=R5RelativeValuePromotionRef(
            extended.authorization_id,
            extended.authorization_version,
        ),
    )
    use_case, _, repository = _use_case(
        graph,
        authorization_provider=_AuthorizationProvider(extended),
    )
    with pytest.raises(R5RelativeValuePromotionEvidenceError) as expiry_error:
        use_case.execute(command)
    assert expiry_error.value.reason_code == "r5_promotion.evidence_substituted"
    assert not repository.items


def test_research_trial_provider_cannot_self_attest_portfolio_metrics(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A favorable Research seal is powerless without the owner outcome record."""

    graph = _graph(monkeypatch)
    original = graph.trial.observations[0]
    original_outcome = original.portfolio_outcome
    fabricated_outcome = R5PortfolioOutcomeSeal.create(
        outcome_version="fabricated-outcome-v1",
        owner_record_id="fabricated-owner-record",
        owner_record_version="fabricated-owner-record-v1",
        owner_record_hash="e" * 64,
        observation_id=original.observation_id,
        fixed_income_result_id=original.fixed_income_record.result_id,
        fixed_income_result_version=original.fixed_income_record.result_version,
        fixed_income_result_record_hash=original.fixed_income_record.result_record_hash,
        fixed_income_owner_seal_hash=original.fixed_income_record.content_hash,
        selection_as_of=original_outcome.selection_as_of,
        outcome_observed_at=original_outcome.outcome_observed_at,
        outcome_available_at=original_outcome.outcome_available_at,
        recorded_at=original_outcome.recorded_at,
        valid_until=original_outcome.valid_until,
        target_gross_return=original_outcome.target_gross_return + 1,
        target_cost=original_outcome.target_cost,
        benchmark_gross_return=original_outcome.benchmark_gross_return,
        benchmark_cost=original_outcome.benchmark_cost,
        target_maximum_drawdown=original_outcome.target_maximum_drawdown,
        benchmark_maximum_drawdown=original_outcome.benchmark_maximum_drawdown,
        capacity_utilization=original_outcome.capacity_utilization,
        liquidity_breached=original_outcome.liquidity_breached,
        realized_credit_loss=original_outcome.realized_credit_loss,
    )
    fabricated_observation = R5RelativeValueTrialObservation.create(
        observation_id=original.observation_id,
        fixed_income_record=original.fixed_income_record,
        portfolio_outcome=fabricated_outcome,
    )
    fabricated_trial = R5RelativeValuePromotionTrial.create(
        policy=graph.policy,
        observations=(fabricated_observation, graph.trial.observations[1]),
        evaluated_at=graph.trial.evaluated_at,
    )
    trial_ref = R5RelativeValuePromotionRef(
        fabricated_trial.trial_id,
        fabricated_trial.trial_version,
    )
    authorization = R5RelativeValueDecisionAuthorization.create(
        authorization_version="fabricated-trial-auth-v1",
        scope_id=graph.policy.scope.scope_id,
        scope_content_hash=graph.policy.scope.content_hash,
        policy_ref=graph.command.policy_ref,
        trial_ref=trial_ref,
        issued_at=graph.authorization.issued_at,
        recorded_at=graph.authorization.recorded_at,
        decided_at=graph.authorization.decided_at,
        decision_recorded_at=graph.authorization.decision_recorded_at,
        decision_valid_until=r5_relative_value_promotion_decision_valid_until(
            policy=graph.policy,
            trial=fabricated_trial,
            decided_at=graph.command.as_of,
        ),
        valid_until=graph.authorization.valid_until,
    )
    command = replace(
        graph.command,
        trial_ref=trial_ref,
        authorization_ref=R5RelativeValuePromotionRef(
            authorization.authorization_id,
            authorization.authorization_version,
        ),
    )
    use_case, _, repository = _use_case(
        graph,
        trial_provider=_TrialProvider(fabricated_trial),
        outcome_provider=_OutcomeProvider(
            tuple(item.portfolio_outcome for item in graph.trial.observations)
        ),
        authorization_provider=_AuthorizationProvider(authorization),
    )
    with pytest.raises(R5RelativeValuePromotionEvidenceError) as error:
        use_case.execute(command)
    assert error.value.reason_code == "r5_promotion.portfolio_outcome_missing"
    assert not repository.items


def test_every_dynamic_port_must_share_one_uow(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Decision evaluation rejects a TOCTOU-capable provider composition."""

    graph = _graph(monkeypatch)
    with pytest.raises(ValueError, match="units of work"):
        _use_case(
            graph,
            record_provider=_RecordProvider(graph.bundles, unit_of_work_key="other"),
        )
    with pytest.raises(ValueError, match="units of work"):
        _use_case(
            graph,
            outcome_provider=_OutcomeProvider(
                tuple(item.portfolio_outcome for item in graph.trial.observations),
                unit_of_work_key="other",
            ),
        )
