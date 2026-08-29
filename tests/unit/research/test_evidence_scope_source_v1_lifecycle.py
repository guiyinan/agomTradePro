"""Pure tests for the dormant Evidence scope-source lifecycle contract."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta

import pytest

from apps.research.application.evidence_scope_source_v1_lifecycle import (
    EvidenceScopeSourceV1LifecycleCorruption,
    EvidenceScopeSourceV1LifecycleUnavailable,
    EvidenceScopeSourceV1Observation,
    IssueEvidenceScopeSourceV1,
    IssueEvidenceScopeSourceV1Command,
)
from apps.research.domain.evidence_contracts import ArtifactRef
from apps.research.domain.evidence_scope_source_v1 import (
    EvidenceScopeSourceV1,
    root_claim_hash_for_evidence_scope_source_v1,
)

NOW = datetime(2026, 8, 23, 12, 0, tzinfo=UTC)


def _artifact() -> ArtifactRef:
    return ArtifactRef(
        owner="research",
        artifact_type="policy",
        artifact_id="policy-1",
        artifact_version="v1",
        content_hash="a" * 64,
    )


def _observation(*, recorded_at: datetime = NOW) -> EvidenceScopeSourceV1Observation:
    return EvidenceScopeSourceV1Observation(
        observation_id="owner-observation-1",
        observation_version="v1",
        owner_id="owner-1",
        tenant_id="tenant-1",
        account_id="account-1",
        actor_id="actor-1",
        artifact=_artifact(),
        status="active",
        recorded_at=recorded_at,
        valid_until=recorded_at + timedelta(hours=2),
    )


def _source(*, version: str = "v1", recorded_at: datetime = NOW) -> EvidenceScopeSourceV1:
    observation = _observation(recorded_at=recorded_at)
    return EvidenceScopeSourceV1(
        source_id="scope-source-1",
        source_version=version,
        owner_id=observation.owner_id,
        tenant_id=observation.tenant_id,
        account_id=observation.account_id,
        actor_id=observation.actor_id,
        artifact=observation.artifact,
        status="active",
        recorded_at=recorded_at,
        valid_until=recorded_at + timedelta(hours=2),
        root_claim_hash=(
            root_claim_hash_for_evidence_scope_source_v1(
                source_id="scope-source-1",
                owner_id=observation.owner_id,
                tenant_id=observation.tenant_id,
                account_id=observation.account_id,
                actor_id=observation.actor_id,
                artifact=observation.artifact,
            )
            if version == "v1"
            else None
        ),
        supersedes_content_hash=None if version == "v1" else _source().content_hash,
    )


class _Provider:
    unit_of_work_key = "fake:default"

    def __init__(self, observation: EvidenceScopeSourceV1Observation | None) -> None:
        self.observation = observation
        self.calls = 0

    def get_exact_current(
        self,
        *,
        observation_id: str,
        observation_version: str,
        expected_content_hash: str,
        as_of: datetime,
    ) -> EvidenceScopeSourceV1Observation | None:
        del observation_id, observation_version, expected_content_hash, as_of
        self.calls += 1
        return self.observation


class _Repository:
    unit_of_work_key = "fake:default"

    def __init__(
        self,
        *,
        winner: EvidenceScopeSourceV1 | None = None,
        head: EvidenceScopeSourceV1 | None = None,
    ) -> None:
        self.winner = winner
        self.head = head
        self.winner_calls = 0
        self.head_calls = 0
        self.appended: list[EvidenceScopeSourceV1] = []

    @contextmanager
    def atomic(self) -> Iterator[None]:
        yield

    def now(self) -> datetime:
        return NOW

    def get_winner(
        self,
        *,
        source_id: str,
        source_version: str,
        as_of: datetime,
    ) -> EvidenceScopeSourceV1 | None:
        del source_id, source_version, as_of
        self.winner_calls += 1
        return self.winner

    def get_current_head(
        self,
        *,
        source_id: str,
        as_of: datetime,
    ) -> EvidenceScopeSourceV1 | None:
        del source_id, as_of
        self.head_calls += 1
        return self.head

    def append(
        self,
        source: EvidenceScopeSourceV1,
        *,
        expected_predecessor_hash: str | None,
        recorded_at: datetime,
    ) -> EvidenceScopeSourceV1:
        del expected_predecessor_hash, recorded_at
        self.appended.append(source)
        return source


def _command() -> IssueEvidenceScopeSourceV1Command:
    return IssueEvidenceScopeSourceV1Command(
        source_id="scope-source-1",
        source_version="v1",
        observation_id="owner-observation-1",
        observation_version="v1",
        expected_observation_content_hash=_observation().content_hash,
    )


def _use_case(
    provider: _Provider,
    repository: _Repository,
) -> IssueEvidenceScopeSourceV1:
    return IssueEvidenceScopeSourceV1(
        observation_provider=provider,
        repository=repository,
        validity_period=timedelta(hours=1),
    )


def test_existing_winner_replays_before_reading_current_observation() -> None:
    winner = _source()
    provider = _Provider(None)
    repository = _Repository(winner=winner, head=_source(version="v2"))

    result = _use_case(provider, repository).execute(_command())

    assert result == winner
    assert provider.calls == 0
    assert repository.winner_calls == 1
    assert repository.head_calls == 0
    assert repository.appended == []


def test_expired_winner_remains_historically_replayable() -> None:
    winner = _source(recorded_at=NOW - timedelta(hours=4))
    provider = _Provider(None)
    repository = _Repository(winner=winner)

    result = _use_case(provider, repository).execute(_command())

    assert result == winner
    assert provider.calls == 0


def test_missing_winner_reads_observation_twice_before_append() -> None:
    provider = _Provider(_observation())
    repository = _Repository()

    result = _use_case(provider, repository).execute(_command())

    assert result == repository.appended[0]
    assert provider.calls == 2
    assert repository.winner_calls == 1
    assert repository.head_calls == 1
    assert result.recorded_at == NOW


def test_observation_identity_drift_aborts_without_append() -> None:
    first = _observation()
    second = EvidenceScopeSourceV1Observation(
        observation_id=first.observation_id,
        observation_version=first.observation_version,
        owner_id="owner-2",
        tenant_id=first.tenant_id,
        account_id=first.account_id,
        actor_id=first.actor_id,
        artifact=first.artifact,
        status=first.status,
        recorded_at=first.recorded_at,
        valid_until=first.valid_until,
    )

    class _DriftingProvider(_Provider):
        def get_exact_current(
            self,
            *,
            observation_id: str,
            observation_version: str,
            expected_content_hash: str,
            as_of: datetime,
        ) -> EvidenceScopeSourceV1Observation | None:
            del observation_id, observation_version, expected_content_hash, as_of
            self.calls += 1
            return first if self.calls == 1 else second

    provider = _DriftingProvider(first)
    repository = _Repository()

    with pytest.raises(EvidenceScopeSourceV1LifecycleCorruption):
        _use_case(provider, repository).execute(_command())

    assert repository.appended == []


def test_observation_content_hash_substitution_fails_closed() -> None:
    expected = _observation()
    substituted = EvidenceScopeSourceV1Observation(
        observation_id=expected.observation_id,
        observation_version=expected.observation_version,
        owner_id="owner-2",
        tenant_id=expected.tenant_id,
        account_id=expected.account_id,
        actor_id=expected.actor_id,
        artifact=expected.artifact,
        status=expected.status,
        recorded_at=expected.recorded_at,
        valid_until=expected.valid_until,
    )
    provider = _Provider(substituted)
    repository = _Repository()

    with pytest.raises(EvidenceScopeSourceV1LifecycleCorruption):
        _use_case(provider, repository).execute(
            IssueEvidenceScopeSourceV1Command(
                source_id="scope-source-1",
                source_version="v1",
                observation_id=expected.observation_id,
                observation_version=expected.observation_version,
                expected_observation_content_hash=expected.content_hash,
            )
        )

    assert repository.appended == []


def test_expired_active_final_head_can_receive_a_fresh_successor() -> None:
    predecessor = _source(recorded_at=NOW - timedelta(hours=4))
    observation = _observation()
    provider = _Provider(observation)
    repository = _Repository(head=predecessor)

    command = IssueEvidenceScopeSourceV1Command(
        source_id="scope-source-1",
        source_version="v2",
        observation_id=observation.observation_id,
        observation_version=observation.observation_version,
        expected_observation_content_hash=observation.content_hash,
    )
    result = _use_case(provider, repository).execute(command)

    assert result.supersedes_content_hash == predecessor.content_hash
    assert result.recorded_at == NOW
    assert repository.appended == [result]


def test_observation_and_repository_must_share_one_unit_of_work() -> None:
    provider = _Provider(_observation())

    class _DifferentAliasRepository(_Repository):
        unit_of_work_key = "fake:other"

    with pytest.raises(ValueError, match="share one unit of work"):
        _use_case(provider, _DifferentAliasRepository())


def test_unit_of_work_key_must_be_a_bounded_canonical_token() -> None:
    class _BlankKeyProvider(_Provider):
        unit_of_work_key = " fake:default"

    with pytest.raises(ValueError, match="bounded canonical token"):
        _use_case(_BlankKeyProvider(_observation()), _Repository())


def test_unit_of_work_key_drift_before_execute_fails_closed() -> None:
    provider = _Provider(_observation())
    repository = _Repository()
    use_case = _use_case(provider, repository)
    provider.unit_of_work_key = "fake:other"

    with pytest.raises(EvidenceScopeSourceV1LifecycleUnavailable, match="unit of work"):
        use_case.execute(_command())

    assert provider.calls == 0
    assert repository.winner_calls == 0
    assert repository.appended == []


def test_unit_of_work_key_drift_between_reads_rolls_back_before_append() -> None:
    class _DriftingProvider(_Provider):
        def get_exact_current(
            self,
            *,
            observation_id: str,
            observation_version: str,
            expected_content_hash: str,
            as_of: datetime,
        ) -> EvidenceScopeSourceV1Observation | None:
            result = super().get_exact_current(
                observation_id=observation_id,
                observation_version=observation_version,
                expected_content_hash=expected_content_hash,
                as_of=as_of,
            )
            self.unit_of_work_key = "fake:other"
            return result

    provider = _DriftingProvider(_observation())
    repository = _Repository()

    with pytest.raises(EvidenceScopeSourceV1LifecycleUnavailable, match="unit of work"):
        _use_case(provider, repository).execute(_command())

    assert provider.calls == 1
    assert repository.head_calls == 0
    assert repository.appended == []


def test_unit_of_work_key_drift_during_append_rolls_back_transaction() -> None:
    class _TransactionalDriftingRepository(_Repository):
        @contextmanager
        def atomic(self) -> Iterator[None]:
            snapshot = list(self.appended)
            try:
                yield
            except Exception:
                self.appended = snapshot
                raise

        def append(
            self,
            source: EvidenceScopeSourceV1,
            *,
            expected_predecessor_hash: str | None,
            recorded_at: datetime,
        ) -> EvidenceScopeSourceV1:
            result = super().append(
                source,
                expected_predecessor_hash=expected_predecessor_hash,
                recorded_at=recorded_at,
            )
            self.unit_of_work_key = "fake:other"
            return result

    provider = _Provider(_observation())
    repository = _TransactionalDriftingRepository()

    with pytest.raises(EvidenceScopeSourceV1LifecycleUnavailable, match="unit of work"):
        _use_case(provider, repository).execute(_command())

    assert repository.appended == []
