"""Pure Application coverage for inactive account namespace binding workflow."""

from __future__ import annotations

import ast
from contextlib import AbstractContextManager, nullcontext
from dataclasses import fields
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from apps.broker_execution.application.portfolio_broker_account_binding import (
    BrokerAccountNamespaceSourceDefinition,
    BrokerPortfolioAccountBindingConflict,
    BrokerPortfolioAccountBindingCorruption,
    BrokerPortfolioAccountBindingRepository,
    BrokerPortfolioAccountBindingUnavailable,
    GetCurrentBrokerPortfolioAccountBinding,
    GetCurrentBrokerPortfolioAccountBindingCommand,
    GetExactBrokerPortfolioAccountBinding,
    GetExactBrokerPortfolioAccountBindingCommand,
    PortfolioAccountNamespaceSourceDefinition,
    RegisterBrokerPortfolioAccountBinding,
    RegisterBrokerPortfolioAccountBindingCommand,
)
from apps.broker_execution.domain.portfolio_broker_account_binding import (
    ACCOUNT_BINDING_SOURCE_ARTIFACT_TYPE,
    ACCOUNT_BINDING_SOURCE_OWNER,
    BROKER_ACCOUNT_BINDING_SOURCE_ARTIFACT_TYPE,
    BROKER_ACCOUNT_BINDING_SOURCE_OWNER,
    BROKER_PORTFOLIO_ACCOUNT_BINDING_VERSION,
    BrokerPortfolioAccountBindingActor,
    BrokerPortfolioAccountNamespaceBinding,
)

NOW = datetime(2026, 8, 13, 7, tzinfo=UTC)


def _broker_source(**changes: object) -> BrokerAccountNamespaceSourceDefinition:
    values: dict[str, object] = {
        "source_id": "broker-account-source-7",
        "source_version": "broker-account-source.v1",
        "content_hash": "a" * 64,
        "account_namespace": "broker_execution.system_account",
        "account_id": 7,
        "owner_user_id": 19,
        "account_type": "real",
        "is_active": True,
        "recorded_at": NOW - timedelta(minutes=5),
        "valid_until": NOW + timedelta(hours=2),
    }
    values.update(changes)
    return BrokerAccountNamespaceSourceDefinition(**values)  # type: ignore[arg-type]


def _portfolio_source(**changes: object) -> PortfolioAccountNamespaceSourceDefinition:
    values: dict[str, object] = {
        "source_id": "portfolio-account-source-7",
        "source_version": "portfolio-account-source.v1",
        "content_hash": "b" * 64,
        "account_namespace": "portfolio.transition_plan_account",
        "account_id": "portfolio-account-7",
        "owner_user_id": 19,
        "account_type": "real",
        "is_active": True,
        "recorded_at": NOW - timedelta(minutes=4),
        "valid_until": NOW + timedelta(hours=1),
    }
    values.update(changes)
    return PortfolioAccountNamespaceSourceDefinition(**values)  # type: ignore[arg-type]


def _actor(**changes: object) -> BrokerPortfolioAccountBindingActor:
    values: dict[str, object] = {
        "actor_id": "user:19",
        "user_id": 19,
        "role": "broker_account_binding_approver",
    }
    values.update(changes)
    return BrokerPortfolioAccountBindingActor(**values)  # type: ignore[arg-type]


def _command(
    binding_id: str = "broker-portfolio-account-binding-1",
) -> RegisterBrokerPortfolioAccountBindingCommand:
    return RegisterBrokerPortfolioAccountBindingCommand(
        binding_id=binding_id,
        broker_source_id="broker-account-source-7",
        broker_source_version="broker-account-source.v1",
        portfolio_source_id="portfolio-account-source-7",
        portfolio_source_version="portfolio-account-source.v1",
    )


class _BrokerProvider:
    def __init__(self, values: list[BrokerAccountNamespaceSourceDefinition | None]) -> None:
        self.values = values
        self.calls: list[dict[str, object]] = []

    def get_exact_current(
        self, *, source_id: str, source_version: str, as_of: datetime
    ) -> BrokerAccountNamespaceSourceDefinition | None:
        self.calls.append(
            {
                "source_id": source_id,
                "source_version": source_version,
                "as_of": as_of,
            }
        )
        index = min(len(self.calls) - 1, len(self.values) - 1)
        return self.values[index]


class _PortfolioProvider:
    def __init__(self, values: list[PortfolioAccountNamespaceSourceDefinition | None]) -> None:
        self.values = values
        self.calls: list[dict[str, object]] = []

    def get_exact_current(
        self, *, source_id: str, source_version: str, as_of: datetime
    ) -> PortfolioAccountNamespaceSourceDefinition | None:
        self.calls.append(
            {
                "source_id": source_id,
                "source_version": source_version,
                "as_of": as_of,
            }
        )
        index = min(len(self.calls) - 1, len(self.values) - 1)
        return self.values[index]


class _Repository(BrokerPortfolioAccountBindingRepository):
    def __init__(self) -> None:
        self.clock = NOW
        self.by_identity: dict[tuple[str, str], BrokerPortfolioAccountNamespaceBinding] = {}
        self.heads: dict[tuple[str, int], BrokerPortfolioAccountNamespaceBinding] = {}
        self.append_calls: list[tuple[str | None, datetime]] = []

    def atomic(self) -> AbstractContextManager[None]:
        return nullcontext()

    def now(self) -> datetime:
        return self.clock

    def get_binding_winner(
        self, *, binding_id: str, binding_version: str, as_of: datetime
    ) -> BrokerPortfolioAccountNamespaceBinding | None:
        del as_of
        return self.by_identity.get((binding_id, binding_version))

    def get_current_head(
        self,
        *,
        broker_account_namespace: str,
        broker_account_id: int,
        as_of: datetime,
    ) -> BrokerPortfolioAccountNamespaceBinding | None:
        del as_of
        return self.heads.get((broker_account_namespace, broker_account_id))

    def append(
        self,
        binding: BrokerPortfolioAccountNamespaceBinding,
        *,
        expected_predecessor_hash: str | None,
        recorded_at: datetime,
    ) -> BrokerPortfolioAccountNamespaceBinding:
        self.append_calls.append((expected_predecessor_hash, recorded_at))
        key = (binding.broker_account_namespace, binding.broker_account_id)
        current = self.heads.get(key)
        actual = current.content_hash if current else None
        if actual != expected_predecessor_hash:
            raise BrokerPortfolioAccountBindingConflict("CAS conflict")
        identity = (binding.binding_id, binding.binding_version)
        winner = self.by_identity.setdefault(identity, binding)
        if winner == binding:
            self.heads[key] = binding
        return winner

    def get_exact_by_hash(
        self,
        *,
        binding_id: str,
        binding_version: str,
        expected_content_hash: str,
        as_of: datetime,
    ) -> BrokerPortfolioAccountNamespaceBinding | None:
        value = self.by_identity.get((binding_id, binding_version))
        if value is None or value.content_hash != expected_content_hash:
            return None
        return value if value.is_knowable_at(as_of) else None


def _use_case(
    repository: _Repository,
    *,
    brokers: list[BrokerAccountNamespaceSourceDefinition | None] | None = None,
    portfolios: list[PortfolioAccountNamespaceSourceDefinition | None] | None = None,
    actor: BrokerPortfolioAccountBindingActor | None = None,
) -> tuple[
    RegisterBrokerPortfolioAccountBinding,
    _BrokerProvider,
    _PortfolioProvider,
]:
    broker_provider = _BrokerProvider(brokers or [_broker_source()])
    portfolio_provider = _PortfolioProvider(portfolios or [_portfolio_source()])
    return (
        RegisterBrokerPortfolioAccountBinding(
            broker_source_provider=broker_provider,
            portfolio_source_provider=portfolio_provider,
            repository=repository,
            actor=actor or _actor(),
        ),
        broker_provider,
        portfolio_provider,
    )


def test_register_is_id_only_and_double_reads_both_sources_at_one_server_cutoff() -> None:
    repository = _Repository()
    use_case, broker_provider, portfolio_provider = _use_case(repository)

    binding = use_case.execute(_command())

    assert len(broker_provider.calls) == len(portfolio_provider.calls) == 2
    assert {
        call["as_of"]
        for provider in (broker_provider, portfolio_provider)
        for call in provider.calls
    } == {NOW}
    assert binding.broker_account_id == 7
    assert type(binding.broker_account_id) is int
    assert binding.portfolio_account_id == "portfolio-account-7"
    assert type(binding.portfolio_account_id) is str
    assert binding.broker_source_content_hash == "a" * 64
    assert binding.portfolio_source_content_hash == "b" * 64
    assert binding.owner_user_id == 19
    assert binding.account_type == "real"
    assert binding.source_accounts_active is True
    assert binding.issued_at == binding.recorded_at == NOW
    assert binding.valid_until == NOW + timedelta(hours=1)
    assert binding.asserted_by == _actor()
    assert binding.activation_available is False
    assert binding.must_not_execute is True
    assert repository.append_calls == [(None, NOW)]


def test_register_command_excludes_accounts_hashes_clocks_actor_and_permission() -> None:
    names = {field.name for field in fields(RegisterBrokerPortfolioAccountBindingCommand)}

    assert names == {
        "binding_id",
        "binding_version",
        "broker_source_id",
        "broker_source_version",
        "portfolio_source_id",
        "portfolio_source_version",
    }
    assert not names & {
        "broker_account_id",
        "portfolio_account_id",
        "content_hash",
        "recorded_at",
        "valid_until",
        "asserted_by",
        "permission",
        "owner_user_id",
        "account_type",
        "source_accounts_active",
    }


def test_registration_rejects_source_drift_and_missing_source() -> None:
    drift_repository = _Repository()
    drift, _, _ = _use_case(
        drift_repository,
        brokers=[_broker_source(), _broker_source(content_hash="c" * 64)],
    )
    with pytest.raises(BrokerPortfolioAccountBindingCorruption, match="changed"):
        drift.execute(_command())

    missing_repository = _Repository()
    missing, _, _ = _use_case(missing_repository, portfolios=[None])
    with pytest.raises(BrokerPortfolioAccountBindingUnavailable, match="Account-owned"):
        missing.execute(_command())


def test_registration_rejects_different_owner_identities() -> None:
    repository = _Repository()
    use_case, _, _ = _use_case(
        repository,
        portfolios=[_portfolio_source(owner_user_id=20)],
    )

    with pytest.raises(BrokerPortfolioAccountBindingCorruption, match="owner"):
        use_case.execute(_command())


@pytest.mark.parametrize(
    "factory_changes",
    [
        {"account_type": "simulated"},
        {"is_active": False},
        {"owner_user_id": True},
    ],
)
def test_owner_source_dtos_reject_nonreal_inactive_or_invalid_owner(
    factory_changes: dict[str, object],
) -> None:
    with pytest.raises(ValueError):
        _broker_source(**factory_changes)
    with pytest.raises(ValueError):
        _portfolio_source(**factory_changes)


@pytest.mark.parametrize(
    "brokers",
    [
        [_broker_source(source_id="substituted")],
        [_broker_source(valid_until=NOW)],
    ],
)
def test_broker_source_identity_type_and_currentness_fail_closed(
    brokers: list[BrokerAccountNamespaceSourceDefinition | None],
) -> None:
    repository = _Repository()
    use_case, _, _ = _use_case(repository, brokers=brokers)

    with pytest.raises(
        (BrokerPortfolioAccountBindingCorruption, BrokerPortfolioAccountBindingUnavailable)
    ):
        use_case.execute(_command())


def test_same_identity_is_idempotent_across_server_clock_for_original_actor() -> None:
    repository = _Repository()
    first_use_case, _, _ = _use_case(repository)
    winner = first_use_case.execute(_command())
    repository.clock = NOW + timedelta(minutes=5)

    replay, _, _ = _use_case(repository, actor=winner.asserted_by)

    assert replay.execute(_command()) == winner
    assert len(repository.append_calls) == 1


def test_same_identity_replay_by_another_actor_conflicts() -> None:
    repository = _Repository()
    first_use_case, _, _ = _use_case(repository)
    first_use_case.execute(_command())
    repository.clock = NOW + timedelta(minutes=5)

    replay, _, _ = _use_case(
        repository,
        actor=_actor(actor_id="user:20", user_id=20),
    )
    with pytest.raises(BrokerPortfolioAccountBindingConflict, match="actor"):
        replay.execute(_command())


def test_same_broker_namespace_account_forms_one_cas_supersession_chain() -> None:
    repository = _Repository()
    first_use_case, _, _ = _use_case(repository)
    first = first_use_case.execute(_command())
    repository.clock = NOW + timedelta(minutes=1)
    second_use_case, _, _ = _use_case(
        repository,
        portfolios=[
            _portfolio_source(
                source_id="portfolio-account-source-8",
                account_id="portfolio-account-8",
            )
        ],
    )
    second_command = RegisterBrokerPortfolioAccountBindingCommand(
        binding_id="broker-portfolio-account-binding-2",
        broker_source_id="broker-account-source-7",
        broker_source_version="broker-account-source.v1",
        portfolio_source_id="portfolio-account-source-8",
        portfolio_source_version="portfolio-account-source.v1",
    )

    second = second_use_case.execute(second_command)

    assert second.supersedes_binding_hash == first.content_hash
    assert repository.append_calls[-1] == (first.content_hash, repository.clock)


def _current_command(
    binding: BrokerPortfolioAccountNamespaceBinding,
    **changes: object,
) -> GetCurrentBrokerPortfolioAccountBindingCommand:
    values: dict[str, object] = {
        "binding_id": binding.binding_id,
        "expected_content_hash": binding.content_hash,
        "broker_source_owner": binding.broker_source_owner,
        "broker_source_artifact_type": binding.broker_source_artifact_type,
        "broker_source_id": binding.broker_source_id,
        "broker_source_version": binding.broker_source_version,
        "broker_source_content_hash": binding.broker_source_content_hash,
        "broker_account_namespace": binding.broker_account_namespace,
        "broker_account_id": binding.broker_account_id,
        "owner_user_id": binding.owner_user_id,
        "account_type": binding.account_type,
        "source_accounts_active": binding.source_accounts_active,
        "portfolio_source_owner": binding.portfolio_source_owner,
        "portfolio_source_artifact_type": binding.portfolio_source_artifact_type,
        "portfolio_source_id": binding.portfolio_source_id,
        "portfolio_source_version": binding.portfolio_source_version,
        "portfolio_source_content_hash": binding.portfolio_source_content_hash,
        "portfolio_account_namespace": binding.portfolio_account_namespace,
        "portfolio_account_id": binding.portfolio_account_id,
        "as_of": NOW,
    }
    values.update(changes)
    return GetCurrentBrokerPortfolioAccountBindingCommand(**values)  # type: ignore[arg-type]


def test_exact_and_logical_current_reads_remain_inactive_and_closed_selector() -> None:
    repository = _Repository()
    use_case, _, _ = _use_case(repository)
    binding = use_case.execute(_command())

    exact = GetExactBrokerPortfolioAccountBinding(repository).execute(
        GetExactBrokerPortfolioAccountBindingCommand(
            binding_id=binding.binding_id,
            expected_content_hash=binding.content_hash,
            as_of=NOW,
        )
    )
    current = GetCurrentBrokerPortfolioAccountBinding(repository).execute(_current_command(binding))

    assert exact == current == binding
    assert exact is not None and exact.activation_available is False
    assert exact.must_not_execute is True


@pytest.mark.parametrize(
    ("field_name", "replacement"),
    [
        ("broker_source_content_hash", "0" * 64),
        ("broker_account_id", 8),
        ("portfolio_source_content_hash", "1" * 64),
        ("portfolio_account_id", "portfolio-account-8"),
    ],
)
def test_current_reader_rejects_complete_selector_substitution(
    field_name: str, replacement: object
) -> None:
    repository = _Repository()
    use_case, _, _ = _use_case(repository)
    binding = use_case.execute(_command())

    with pytest.raises(BrokerPortfolioAccountBindingCorruption, match="selector"):
        GetCurrentBrokerPortfolioAccountBinding(repository).execute(
            _current_command(binding, **{field_name: replacement})
        )


@pytest.mark.parametrize(
    "changes",
    [
        {"owner_user_id": 20},
        {"account_type": "simulated"},
        {"source_accounts_active": False},
    ],
)
def test_current_selector_cannot_upgrade_or_substitute_owner_account_state(
    changes: dict[str, object]
) -> None:
    repository = _Repository()
    use_case, _, _ = _use_case(repository)
    binding = use_case.execute(_command())

    if changes.get("owner_user_id") == 20:
        with pytest.raises(BrokerPortfolioAccountBindingCorruption, match="selector"):
            GetCurrentBrokerPortfolioAccountBinding(repository).execute(
                _current_command(binding, **changes)
            )
    else:
        with pytest.raises(ValueError, match="active real"):
            _current_command(binding, **changes)


def test_current_reader_does_not_return_superseded_binding() -> None:
    repository = _Repository()
    first_use_case, _, _ = _use_case(repository)
    first = first_use_case.execute(_command())
    repository.clock = NOW + timedelta(minutes=1)
    second_use_case, _, _ = _use_case(
        repository,
        portfolios=[
            _portfolio_source(
                source_id="portfolio-account-source-8",
                account_id="portfolio-account-8",
            )
        ],
    )
    second_use_case.execute(
        RegisterBrokerPortfolioAccountBindingCommand(
            binding_id="broker-portfolio-account-binding-2",
            broker_source_id="broker-account-source-7",
            broker_source_version="broker-account-source.v1",
            portfolio_source_id="portfolio-account-source-8",
            portfolio_source_version="portfolio-account-source.v1",
        )
    )

    assert (
        GetCurrentBrokerPortfolioAccountBinding(repository).execute(
            _current_command(first, as_of=repository.clock)
        )
        is None
    )


def test_application_has_no_other_app_or_infrastructure_dependency() -> None:
    path = Path("apps/broker_execution/application/portfolio_broker_account_binding.py")
    tree = ast.parse(path.read_text(encoding="utf-8"))
    imported = {
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    } | {node.module or "" for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)}

    assert not any(".infrastructure" in name for name in imported)
    assert not any(
        name.startswith("apps.") and not name.startswith("apps.broker_execution.domain")
        for name in imported
    )
