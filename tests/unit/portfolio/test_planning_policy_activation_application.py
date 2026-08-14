"""Pure Application tests for Portfolio planning-policy activation."""

from contextlib import nullcontext
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest

from apps.portfolio.application.planning_policy_activation import (
    ApprovePlanningPolicyActivation,
    ApprovePlanningPolicyActivationCommand,
    GetCurrentPlanningPolicyActivation,
    GetCurrentPlanningPolicyActivationCommand,
    PlanningPolicyActivationConflict,
    PlanningPolicyActivationCorruption,
    PlanningPolicyActivationUnavailable,
    RegisterPlanningPolicyActivationSubject,
    RegisterPlanningPolicyActivationSubjectCommand,
)
from apps.portfolio.domain.planning_policy_activation import (
    PlanningPolicyActivation,
    PlanningPolicyActivationActor,
    PlanningPolicyActivationSubject,
)
from apps.portfolio.domain.planning_policy_definition import PlanningPolicyDefinition

NOW = datetime(2026, 8, 13, 6, 0, tzinfo=UTC)


def _definition(**changes: object) -> PlanningPolicyDefinition:
    values: dict[str, object] = {
        "policy_id": "portfolio-policy-standard",
        "policy_version": "v1",
        "buy_lot_size": 100,
        "fee_rate": Decimal("0.0003"),
        "slippage_rate": Decimal("0.001"),
        "min_rebalance_value": Decimal("1000"),
        "max_asset_weight": Decimal("0.2"),
        "max_volume_participation": Decimal("0.1"),
        "recorded_at": NOW - timedelta(hours=1),
        "valid_until": NOW + timedelta(days=30),
    }
    values.update(changes)
    return PlanningPolicyDefinition(**values)


def _actor(number: int) -> PlanningPolicyActivationActor:
    return PlanningPolicyActivationActor(
        actor_id=f"portfolio-staff-{number}",
        user_id=number,
        role="portfolio_policy_approver",
    )


class FakeDefinitionProvider:
    def __init__(self, value: PlanningPolicyDefinition | None) -> None:
        self.values: list[PlanningPolicyDefinition | None] = [value]
        self.calls: list[tuple[str, str, datetime]] = []

    def get_exact(
        self, *, policy_id: str, policy_version: str, as_of: datetime
    ) -> PlanningPolicyDefinition | None:
        self.calls.append((policy_id, policy_version, as_of))
        return self.values.pop(0) if len(self.values) > 1 else self.values[0]


class FakeRepository:
    def __init__(self, now: datetime = NOW) -> None:
        self.clock = now
        self.subjects: dict[tuple[str, str], PlanningPolicyActivationSubject] = {}
        self.activations: dict[tuple[str, str], PlanningPolicyActivation] = {}
        self.heads: dict[str, PlanningPolicyActivation] = {}
        self.appended_subjects = 0
        self.appended_activations = 0
        self.substitute_subject: PlanningPolicyActivationSubject | None = None
        self.substitute_activation: PlanningPolicyActivation | None = None

    def atomic(self) -> nullcontext[None]:
        return nullcontext()

    def now(self) -> datetime:
        return self.clock

    def get_subject_winner(
        self, *, subject_id: str, subject_version: str, as_of: datetime
    ) -> PlanningPolicyActivationSubject | None:
        return self.subjects.get((subject_id, subject_version))

    def get_activation_winner(
        self, *, activation_id: str, activation_version: str, as_of: datetime
    ) -> PlanningPolicyActivation | None:
        return self.activations.get((activation_id, activation_version))

    def get_current_head(
        self, *, policy_id: str, as_of: datetime
    ) -> PlanningPolicyActivation | None:
        return self.heads.get(policy_id)

    def append_subject(
        self,
        subject: PlanningPolicyActivationSubject,
        *,
        recorded_at: datetime,
    ) -> PlanningPolicyActivationSubject:
        self.appended_subjects += 1
        value = self.substitute_subject or subject
        self.subjects.setdefault((subject.subject_id, subject.subject_version), value)
        return self.subjects[(subject.subject_id, subject.subject_version)]

    def append(
        self,
        activation: PlanningPolicyActivation,
        *,
        expected_predecessor_hash: str | None,
        recorded_at: datetime,
    ) -> PlanningPolicyActivation:
        actual = self.heads.get(activation.subject.policy_id)
        actual_hash = actual.content_hash if actual is not None else None
        if actual_hash != expected_predecessor_hash:
            raise PlanningPolicyActivationConflict("stale predecessor")
        self.appended_activations += 1
        value = self.substitute_activation or activation
        self.activations.setdefault(
            (activation.activation_id, activation.activation_version), value
        )
        persisted = self.activations[(activation.activation_id, activation.activation_version)]
        self.heads.setdefault(activation.subject.policy_id, persisted)
        return persisted


def _register(
    provider: FakeDefinitionProvider,
    repository: FakeRepository,
    actor: PlanningPolicyActivationActor | None = None,
) -> PlanningPolicyActivationSubject:
    return RegisterPlanningPolicyActivationSubject(
        definition_provider=provider,
        repository=repository,
        actor=actor or _actor(11),
    ).execute(
        RegisterPlanningPolicyActivationSubjectCommand(
            subject_id="request-1",
            subject_version="v1",
            policy_id="portfolio-policy-standard",
            policy_version="v1",
        )
    )


def _approve(
    provider: FakeDefinitionProvider,
    repository: FakeRepository,
    actor: PlanningPolicyActivationActor | None = None,
) -> PlanningPolicyActivation:
    return ApprovePlanningPolicyActivation(
        definition_provider=provider,
        repository=repository,
        actor=actor or _actor(12),
    ).execute(
        ApprovePlanningPolicyActivationCommand(
            subject_id="request-1",
            subject_version="v1",
            activation_id="activation-1",
            activation_version="v1",
        )
    )


def test_register_is_id_only_double_read_and_server_clocked() -> None:
    definition = _definition()
    provider = FakeDefinitionProvider(definition)
    repository = FakeRepository()

    subject = _register(provider, repository)

    assert subject.definition_content_hash == definition.content_hash
    assert subject.requested_at == NOW
    assert len(provider.calls) == 2
    assert {call[2] for call in provider.calls} == {NOW}
    assert repository.appended_subjects == 1


def test_register_rejects_missing_or_drifting_definition_without_write() -> None:
    repository = FakeRepository()
    with pytest.raises(PlanningPolicyActivationUnavailable):
        _register(FakeDefinitionProvider(None), repository)
    assert repository.appended_subjects == 0

    first = _definition()
    provider = FakeDefinitionProvider(first)
    provider.values = [first, _definition(fee_rate=Decimal("0.0004"))]
    with pytest.raises(PlanningPolicyActivationCorruption, match="changed"):
        _register(provider, repository)
    assert repository.appended_subjects == 0


def test_register_is_idempotent_across_server_clocks_only_for_original_actor() -> None:
    definition = _definition()
    repository = FakeRepository()
    first = _register(FakeDefinitionProvider(definition), repository)
    repository.clock += timedelta(hours=1)

    replay = _register(FakeDefinitionProvider(definition), repository)
    assert replay == first
    assert repository.appended_subjects == 1

    with pytest.raises(PlanningPolicyActivationConflict, match="another first winner"):
        _register(FakeDefinitionProvider(definition), repository, _actor(13))


def test_approve_requires_persisted_subject_and_distinct_server_actor() -> None:
    definition = _definition()
    repository = FakeRepository()
    with pytest.raises(PlanningPolicyActivationUnavailable):
        _approve(FakeDefinitionProvider(definition), repository)

    _register(FakeDefinitionProvider(definition), repository)
    with pytest.raises(PlanningPolicyActivationConflict, match="invalid"):
        _approve(FakeDefinitionProvider(definition), repository, _actor(11))
    assert repository.appended_activations == 0


def test_approve_double_reads_subject_and_definition_before_append() -> None:
    definition = _definition()
    provider = FakeDefinitionProvider(definition)
    repository = FakeRepository()
    subject = _register(FakeDefinitionProvider(definition), repository)

    activation = _approve(provider, repository)

    assert activation.subject == subject
    assert activation.approved_by == _actor(12)
    assert activation.issued_at == NOW
    assert activation.must_not_execute is True
    assert len(provider.calls) == 2
    assert repository.appended_activations == 1


def test_approve_rejects_definition_drift_or_subject_substitution() -> None:
    definition = _definition()
    repository = FakeRepository()
    subject = _register(FakeDefinitionProvider(definition), repository)
    provider = FakeDefinitionProvider(definition)
    provider.values = [definition, _definition(fee_rate=Decimal("0.0004"))]
    with pytest.raises(PlanningPolicyActivationCorruption, match="changed"):
        _approve(provider, repository)

    repository.subjects[(subject.subject_id, subject.subject_version)] = replace(
        subject,
        policy_id="other-policy",
        content_hash="",
    )
    with pytest.raises(PlanningPolicyActivationCorruption, match="identity substitution"):
        _approve(FakeDefinitionProvider(definition), repository)


def test_approve_is_actor_bound_idempotent_and_requires_current_head() -> None:
    definition = _definition()
    repository = FakeRepository()
    _register(FakeDefinitionProvider(definition), repository)
    first = _approve(FakeDefinitionProvider(definition), repository)
    repository.clock += timedelta(hours=1)

    replay = _approve(FakeDefinitionProvider(definition), repository)
    assert replay == first
    assert repository.appended_activations == 1
    with pytest.raises(PlanningPolicyActivationConflict, match="another first winner"):
        _approve(FakeDefinitionProvider(definition), repository, _actor(13))


def test_exact_current_reader_rejects_superseded_or_selector_substitution() -> None:
    definition = _definition()
    repository = FakeRepository()
    _register(FakeDefinitionProvider(definition), repository)
    activation = _approve(FakeDefinitionProvider(definition), repository)
    command = GetCurrentPlanningPolicyActivationCommand(
        activation_id=activation.activation_id,
        activation_version=activation.activation_version,
        expected_content_hash=activation.content_hash,
        policy_id=activation.subject.policy_id,
        policy_version=activation.subject.policy_version,
        definition_content_hash=activation.subject.definition_content_hash,
        as_of=activation.issued_at,
    )
    reader = GetCurrentPlanningPolicyActivation(repository)

    assert reader.execute(command) == activation
    assert reader.execute(replace(command, as_of=activation.valid_until)) is None
    with pytest.raises(PlanningPolicyActivationCorruption, match="selector"):
        reader.execute(replace(command, expected_content_hash="a" * 64))

    successor = replace(
        activation,
        activation_id="activation-2",
        activation_version="v2",
        subject=replace(
            activation.subject,
            subject_id="request-2",
            subject_version="v2",
            supersedes_activation_hash=activation.content_hash,
            content_hash="",
        ),
        issued_at=activation.issued_at + timedelta(hours=1),
        content_hash="",
    )
    repository.heads[activation.subject.policy_id] = successor
    assert reader.execute(command) is None


def test_application_has_no_orm_or_infrastructure_imports() -> None:
    source = Path("apps/portfolio/application/planning_policy_activation.py").read_text(
        encoding="utf-8"
    )

    assert ".objects" not in source
    assert ".infrastructure" not in source
    assert "django" not in source
