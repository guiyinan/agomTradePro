"""Pure tests for benchmark methodology bundle activation workflow."""

from __future__ import annotations

from contextlib import nullcontext
from dataclasses import fields, replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest

from apps.portfolio.application.policy_benchmark_methodology_activation import (
    ApprovePolicyBenchmarkMethodologyActivation,
    ApprovePolicyBenchmarkMethodologyActivationCommand,
    GetCurrentPolicyBenchmarkMethodologyActivation,
    GetCurrentPolicyBenchmarkMethodologyActivationCommand,
    GetExactPolicyBenchmarkMethodologyActivation,
    GetExactPolicyBenchmarkMethodologyActivationCommand,
    PolicyBenchmarkMethodologyActivationConflict,
    PolicyBenchmarkMethodologyActivationCorruption,
    PolicyBenchmarkMethodologyActivationUnavailable,
    RegisterPolicyBenchmarkMethodologyActivationSubject,
    RegisterPolicyBenchmarkMethodologyActivationSubjectCommand,
)
from apps.portfolio.domain.policy_benchmark_definition import (
    PolicyBenchmarkConstituentDefinition,
    PolicyBenchmarkMethodologyRef,
    PortfolioPolicyBenchmarkDefinition,
)
from apps.portfolio.domain.policy_benchmark_methodology_activation import (
    PolicyBenchmarkMethodologyActivationActor,
    PolicyBenchmarkMethodologyActivationSubject,
    PolicyBenchmarkMethodologyBundleActivation,
)

NOW = datetime(2026, 8, 13, 8, tzinfo=UTC)
VALID = NOW + timedelta(days=30)


def _ref(kind: str, marker: str) -> PolicyBenchmarkMethodologyRef:
    return PolicyBenchmarkMethodologyRef(
        owner="portfolio",
        artifact_type=kind,
        artifact_id=f"{kind}-cn",
        artifact_version="v1",
        content_hash=marker * 64,
        recorded_at=NOW - timedelta(hours=1),
        valid_until=VALID,
    )


def _definition(
    *,
    version: str = "v1",
    price_marker: str = "d",
    recorded_at: datetime = NOW,
) -> PortfolioPolicyBenchmarkDefinition:
    return PortfolioPolicyBenchmarkDefinition(
        definition_id="balanced-benchmark",
        definition_version=version,
        base_currency="CNY",
        constituents=(
            PolicyBenchmarkConstituentDefinition("CSI300", "000300.SH", "CNY", Decimal("0.6"), 0),
            PolicyBenchmarkConstituentDefinition("CGB", "CBA00101.CS", "CNY", Decimal("0.4"), 1),
        ),
        trading_calendar_ref=_ref("trading_calendar_definition", "e"),
        price_fixing_ref=_ref("price_fixing_methodology", price_marker),
        fx_fixing_ref=_ref("fx_fixing_methodology", "c"),
        corporate_action_ref=_ref("corporate_action_methodology", "a"),
        cost_tax_ref=_ref("cost_tax_methodology", "b"),
        valuation_timezone="Asia/Shanghai",
        valuation_cutoff="15:00:00",
        evaluation_window_days=252,
        max_price_age_seconds=86400,
        max_fx_age_seconds=86400,
        missing_price_policy="fail_closed",
        missing_fx_policy="fail_closed",
        recorded_at=recorded_at,
        valid_until=VALID,
    )


def _refs(
    definition: PortfolioPolicyBenchmarkDefinition,
) -> tuple[PolicyBenchmarkMethodologyRef, ...]:
    return (
        definition.corporate_action_ref,
        definition.cost_tax_ref,
        definition.fx_fixing_ref,
        definition.price_fixing_ref,
        definition.trading_calendar_ref,
    )


def _actor(name: str, user_id: int) -> PolicyBenchmarkMethodologyActivationActor:
    return PolicyBenchmarkMethodologyActivationActor(
        actor_id=name,
        user_id=user_id,
        role="benchmark_configurator",
    )


class FakeDefinitionProvider:
    def __init__(self, values: list[PortfolioPolicyBenchmarkDefinition | None]) -> None:
        self.values = values
        self.calls = 0

    def get_exact_current(
        self,
        *,
        definition_id: str,
        definition_version: str,
        as_of: datetime,
    ) -> PortfolioPolicyBenchmarkDefinition | None:
        del definition_id, definition_version, as_of
        index = min(self.calls, len(self.values) - 1)
        self.calls += 1
        return self.values[index]


class FakeMethodologyProvider:
    def __init__(self, definition: PortfolioPolicyBenchmarkDefinition) -> None:
        self.values = {
            (value.artifact_type, value.artifact_id, value.artifact_version): value
            for value in _refs(definition)
        }
        self.substitution: PolicyBenchmarkMethodologyRef | None = None
        self.substitute_after = 10**6
        self.calls = 0

    def get_exact_current(
        self,
        *,
        artifact_type: str,
        artifact_id: str,
        artifact_version: str,
        as_of: datetime,
    ) -> PolicyBenchmarkMethodologyRef | None:
        del as_of
        self.calls += 1
        if self.substitution is not None and self.calls > self.substitute_after:
            return self.substitution
        return self.values.get((artifact_type, artifact_id, artifact_version))


class FakeRepository:
    def __init__(self, now: datetime = NOW + timedelta(hours=1)) -> None:
        self.cutoff = now
        self.subjects: dict[tuple[str, str], PolicyBenchmarkMethodologyActivationSubject] = {}
        self.activations: dict[tuple[str, str], PolicyBenchmarkMethodologyBundleActivation] = {}
        self.heads: dict[str, PolicyBenchmarkMethodologyBundleActivation] = {}
        self.append_subject_calls = 0
        self.append_calls = 0
        self.replace_append = False

    def atomic(self) -> nullcontext[None]:
        return nullcontext()

    def now(self) -> datetime:
        return self.cutoff

    def get_subject_winner(
        self, *, subject_id: str, subject_version: str, as_of: datetime
    ) -> PolicyBenchmarkMethodologyActivationSubject | None:
        del as_of
        return self.subjects.get((subject_id, subject_version))

    def get_activation_winner(
        self, *, activation_id: str, activation_version: str, as_of: datetime
    ) -> PolicyBenchmarkMethodologyBundleActivation | None:
        del as_of
        return self.activations.get((activation_id, activation_version))

    def get_current_head(
        self, *, definition_id: str, as_of: datetime
    ) -> PolicyBenchmarkMethodologyBundleActivation | None:
        del as_of
        return self.heads.get(definition_id)

    def append_subject(
        self,
        subject: PolicyBenchmarkMethodologyActivationSubject,
        *,
        recorded_at: datetime,
    ) -> PolicyBenchmarkMethodologyActivationSubject:
        assert recorded_at == self.cutoff
        self.append_subject_calls += 1
        self.subjects[(subject.subject_id, subject.subject_version)] = subject
        return subject

    def append(
        self,
        activation: PolicyBenchmarkMethodologyBundleActivation,
        *,
        expected_predecessor_hash: str | None,
        recorded_at: datetime,
    ) -> PolicyBenchmarkMethodologyBundleActivation:
        assert recorded_at == self.cutoff
        assert activation.subject.supersedes_activation_hash == expected_predecessor_hash
        self.append_calls += 1
        if self.replace_append:
            return replace(activation, activation_version="substituted", content_hash="")
        self.activations[(activation.activation_id, activation.activation_version)] = activation
        self.heads[activation.subject.definition_id] = activation
        return activation

    def get_exact_by_hash(
        self,
        *,
        activation_id: str,
        activation_version: str,
        expected_content_hash: str,
        as_of: datetime,
    ) -> PolicyBenchmarkMethodologyBundleActivation | None:
        value = self.activations.get((activation_id, activation_version))
        if value is None or value.content_hash != expected_content_hash:
            return None
        return value if value.issued_at <= as_of < value.valid_until else None


def _register(
    definition_provider: FakeDefinitionProvider,
    methodology_provider: FakeMethodologyProvider,
    repository: FakeRepository,
    actor: PolicyBenchmarkMethodologyActivationActor | None = None,
) -> PolicyBenchmarkMethodologyActivationSubject:
    return RegisterPolicyBenchmarkMethodologyActivationSubject(
        definition_provider=definition_provider,
        methodology_provider=methodology_provider,
        repository=repository,
        actor=actor or _actor("requester", 1),
    ).execute(
        RegisterPolicyBenchmarkMethodologyActivationSubjectCommand(
            subject_id="bundle-subject",
            subject_version="v1",
            definition_id="balanced-benchmark",
            definition_version="v1",
        )
    )


def _approve(
    definition_provider: FakeDefinitionProvider,
    methodology_provider: FakeMethodologyProvider,
    repository: FakeRepository,
    actor: PolicyBenchmarkMethodologyActivationActor | None = None,
) -> PolicyBenchmarkMethodologyBundleActivation:
    return ApprovePolicyBenchmarkMethodologyActivation(
        definition_provider=definition_provider,
        methodology_provider=methodology_provider,
        repository=repository,
        actor=actor or _actor("approver", 2),
    ).execute(
        ApprovePolicyBenchmarkMethodologyActivationCommand(
            subject_id="bundle-subject",
            subject_version="v1",
            activation_id="bundle-activation",
            activation_version="v1",
        )
    )


def test_commands_are_id_only_and_happy_path_uses_one_cutoff_double_reads() -> None:
    definition = _definition()
    definitions = FakeDefinitionProvider([definition])
    methods = FakeMethodologyProvider(definition)
    repository = FakeRepository()

    subject = _register(definitions, methods, repository)
    activation = _approve(definitions, methods, repository)

    assert {
        field.name for field in fields(RegisterPolicyBenchmarkMethodologyActivationSubjectCommand)
    } == {
        "subject_id",
        "subject_version",
        "definition_id",
        "definition_version",
    }
    assert subject.bundle.bundle_hash == activation.subject.bundle.bundle_hash
    assert definitions.calls == 4
    assert methods.calls == 20
    assert repository.append_subject_calls == repository.append_calls == 1
    assert activation.daily_valuation_authority is False
    assert activation.broker_execution_authority is False
    assert activation.must_not_execute is True


def test_missing_or_substituted_methodology_fails_before_write() -> None:
    definition = _definition()
    methods = FakeMethodologyProvider(definition)
    methods.values.pop(("price_fixing_methodology", "price_fixing_methodology-cn", "v1"))
    repository = FakeRepository()
    with pytest.raises(PolicyBenchmarkMethodologyActivationUnavailable):
        _register(FakeDefinitionProvider([definition]), methods, repository)
    assert repository.append_subject_calls == 0

    methods = FakeMethodologyProvider(definition)
    methods.substitution = replace(definition.price_fixing_ref, content_hash="f" * 64)
    methods.substitute_after = 5
    with pytest.raises(PolicyBenchmarkMethodologyActivationCorruption):
        _register(FakeDefinitionProvider([definition]), methods, repository)
    assert repository.append_subject_calls == 0


def test_definition_drift_and_naive_server_clock_fail_closed() -> None:
    first = _definition()
    changed = _definition(price_marker="f")
    methods = FakeMethodologyProvider(first)
    methods.values[
        (
            changed.price_fixing_ref.artifact_type,
            changed.price_fixing_ref.artifact_id,
            changed.price_fixing_ref.artifact_version,
        )
    ] = changed.price_fixing_ref
    with pytest.raises(PolicyBenchmarkMethodologyActivationCorruption):
        _register(FakeDefinitionProvider([first, changed]), methods, FakeRepository())
    with pytest.raises(ValueError, match="timezone-aware"):
        _register(
            FakeDefinitionProvider([first]),
            FakeMethodologyProvider(first),
            FakeRepository(NOW.replace(tzinfo=None)),
        )


def test_subject_and_activation_winner_replay_are_actor_bound() -> None:
    definition = _definition()
    repository = FakeRepository()
    subject = _register(
        FakeDefinitionProvider([definition]), FakeMethodologyProvider(definition), repository
    )
    replay = _register(
        FakeDefinitionProvider([definition]), FakeMethodologyProvider(definition), repository
    )
    assert replay == subject
    with pytest.raises(PolicyBenchmarkMethodologyActivationConflict):
        _register(
            FakeDefinitionProvider([definition]),
            FakeMethodologyProvider(definition),
            repository,
            _actor("other-requester", 9),
        )

    activation = _approve(
        FakeDefinitionProvider([definition]), FakeMethodologyProvider(definition), repository
    )
    assert (
        _approve(
            FakeDefinitionProvider([definition]), FakeMethodologyProvider(definition), repository
        )
        == activation
    )
    with pytest.raises(PolicyBenchmarkMethodologyActivationConflict):
        _approve(
            FakeDefinitionProvider([definition]),
            FakeMethodologyProvider(definition),
            repository,
            _actor("other-approver", 10),
        )


def test_approval_requires_persisted_subject_and_exact_current_graph() -> None:
    definition = _definition()
    with pytest.raises(PolicyBenchmarkMethodologyActivationUnavailable):
        _approve(
            FakeDefinitionProvider([definition]),
            FakeMethodologyProvider(definition),
            FakeRepository(),
        )

    repository = FakeRepository()
    _register(FakeDefinitionProvider([definition]), FakeMethodologyProvider(definition), repository)
    methods = FakeMethodologyProvider(definition)
    methods.substitution = replace(definition.cost_tax_ref, content_hash="f" * 64)
    methods.substitute_after = 5
    with pytest.raises(PolicyBenchmarkMethodologyActivationCorruption):
        _approve(FakeDefinitionProvider([definition]), methods, repository)
    assert repository.append_calls == 0


def test_self_approval_and_append_substitution_fail_closed() -> None:
    definition = _definition()
    repository = FakeRepository()
    _register(FakeDefinitionProvider([definition]), FakeMethodologyProvider(definition), repository)
    with pytest.raises(
        PolicyBenchmarkMethodologyActivationUnavailable,
        match="distinct authenticated actor",
    ):
        _approve(
            FakeDefinitionProvider([definition]),
            FakeMethodologyProvider(definition),
            repository,
            _actor("requester", 99),
        )
    repository.replace_append = True
    with pytest.raises(PolicyBenchmarkMethodologyActivationConflict):
        _approve(
            FakeDefinitionProvider([definition]), FakeMethodologyProvider(definition), repository
        )


def test_successor_subject_binds_repository_head_predecessor() -> None:
    first = _definition()
    repository = FakeRepository()
    _register(FakeDefinitionProvider([first]), FakeMethodologyProvider(first), repository)
    root = _approve(FakeDefinitionProvider([first]), FakeMethodologyProvider(first), repository)
    repository.cutoff = NOW + timedelta(hours=3)
    second = _definition(version="v2", price_marker="f", recorded_at=NOW + timedelta(hours=2))
    subject = RegisterPolicyBenchmarkMethodologyActivationSubject(
        definition_provider=FakeDefinitionProvider([second]),
        methodology_provider=FakeMethodologyProvider(second),
        repository=repository,
        actor=_actor("requester", 1),
    ).execute(
        RegisterPolicyBenchmarkMethodologyActivationSubjectCommand(
            subject_id="bundle-subject-v2",
            subject_version="v2",
            definition_id="balanced-benchmark",
            definition_version="v2",
        )
    )
    assert subject.supersedes_activation_hash == root.content_hash


def test_exact_and_current_reads_reject_supersession_and_source_replacement() -> None:
    definition = _definition()
    repository = FakeRepository()
    _register(FakeDefinitionProvider([definition]), FakeMethodologyProvider(definition), repository)
    activation = _approve(
        FakeDefinitionProvider([definition]), FakeMethodologyProvider(definition), repository
    )
    exact = GetExactPolicyBenchmarkMethodologyActivation(repository).execute(
        GetExactPolicyBenchmarkMethodologyActivationCommand(
            activation_id=activation.activation_id,
            activation_version=activation.activation_version,
            expected_content_hash=activation.content_hash,
            as_of=repository.cutoff,
        )
    )
    assert exact == activation
    current_reader = GetCurrentPolicyBenchmarkMethodologyActivation(
        definition_provider=FakeDefinitionProvider([definition]),
        methodology_provider=FakeMethodologyProvider(definition),
        repository=repository,
    )
    command = GetCurrentPolicyBenchmarkMethodologyActivationCommand(
        activation=activation, as_of=repository.cutoff
    )
    assert current_reader.execute(command) == activation
    repository.heads[definition.definition_id] = replace(
        activation, activation_id="successor", activation_version="v2", content_hash=""
    )
    assert current_reader.execute(command) is None

    repository.heads[definition.definition_id] = activation
    methods = FakeMethodologyProvider(definition)
    methods.substitution = replace(definition.fx_fixing_ref, content_hash="f" * 64)
    methods.substitute_after = 0
    with pytest.raises(
        PolicyBenchmarkMethodologyActivationCorruption,
        match="methodology definition selector or content substitution",
    ):
        GetCurrentPolicyBenchmarkMethodologyActivation(
            definition_provider=FakeDefinitionProvider([definition]),
            methodology_provider=methods,
            repository=repository,
        ).execute(command)


def test_application_has_no_orm_or_cross_app_implementation_dependency() -> None:
    source = Path(
        "apps/portfolio/application/policy_benchmark_methodology_activation.py"
    ).read_text(encoding="utf-8")
    assert ".objects" not in source
    assert ".infrastructure" not in source
    assert "apps.risk_center" not in source
    assert "apps.broker_execution" not in source
