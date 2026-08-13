"""Pure tests for the Account raw identity source capture workflow."""

from contextlib import nullcontext
from dataclasses import fields, replace
from datetime import UTC, datetime, timedelta

import pytest

from apps.account.application.account_identity_raw_source import (
    AccountIdentityRawSourceActor,
    AccountIdentityRawSourceConflict,
    AccountIdentityRawSourceCorruption,
    AccountIdentityRawSourceRepository,
    AccountIdentityRawSourceUnavailable,
    CaptureAccountIdentityRawSource,
    CaptureAccountIdentityRawSourceCommand,
    ExactAccountOwnerAssignmentEvidence,
    ExactUnifiedAccountRowObservation,
    GetCurrentAccountIdentityRawSource,
    GetCurrentAccountIdentityRawSourceCommand,
    GetExactAccountIdentityRawSource,
    GetExactAccountIdentityRawSourceCommand,
    PersistedAccountIdentityRawSource,
)

NOW = datetime(2026, 8, 13, 6, 0, tzinfo=UTC)


def _actor(**changes: object) -> AccountIdentityRawSourceActor:
    values: dict[str, object] = {
        "actor_id": "account-staff-11",
        "user_id": 11,
        "role": "account_identity_issuer",
    }
    values.update(changes)
    return AccountIdentityRawSourceActor(**values)  # type: ignore[arg-type]


def _row(**changes: object) -> ExactUnifiedAccountRowObservation:
    values: dict[str, object] = {
        "source_id": "simulated-account-row-7",
        "source_version": "row-observation.v3",
        "content_hash": "b" * 64,
        "account_namespace": "account",
        "account_id": "real-account-7",
        "underlying_unified_account_namespace": "simulated-account-row",
        "underlying_unified_account_id": 7,
        "row_owner_user_id": 19,
        "account_type": "real",
        "is_active": True,
        "observed_at": NOW - timedelta(seconds=1),
        "valid_until": NOW + timedelta(minutes=10),
    }
    values.update(changes)
    return ExactUnifiedAccountRowObservation(**values)  # type: ignore[arg-type]


def _evidence(**changes: object) -> ExactAccountOwnerAssignmentEvidence:
    values: dict[str, object] = {
        "evidence_id": "owner-assignment-7",
        "evidence_version": "owner-assignment.v1",
        "content_hash": "a" * 64,
        "assignment_state": "authoritative",
        "assigned_owner_user_id": 19,
        "row_source_id": "simulated-account-row-7",
        "row_source_version": "row-observation.v3",
        "row_source_content_hash": "b" * 64,
        "account_namespace": "account",
        "account_id": "real-account-7",
        "underlying_unified_account_namespace": "simulated-account-row",
        "underlying_unified_account_id": 7,
        "recorded_at": NOW - timedelta(minutes=1),
        "valid_until": NOW + timedelta(minutes=8),
    }
    values.update(changes)
    return ExactAccountOwnerAssignmentEvidence(**values)  # type: ignore[arg-type]


def _command(**changes: object) -> CaptureAccountIdentityRawSourceCommand:
    values: dict[str, object] = {
        "source_id": "account-identity-source-7",
        "source_version": "account-identity-source.v1",
        "row_source_id": "simulated-account-row-7",
        "row_source_version": "row-observation.v3",
        "assignment_evidence_id": "owner-assignment-7",
        "assignment_evidence_version": "owner-assignment.v1",
    }
    values.update(changes)
    return CaptureAccountIdentityRawSourceCommand(**values)  # type: ignore[arg-type]


class _RowProvider:
    def __init__(
        self,
        values: list[ExactUnifiedAccountRowObservation | None],
    ) -> None:
        self.values = values
        self.calls: list[tuple[str, str, datetime]] = []

    def get_exact_current(
        self,
        *,
        source_id: str,
        source_version: str,
        as_of: datetime,
    ) -> ExactUnifiedAccountRowObservation | None:
        self.calls.append((source_id, source_version, as_of))
        return self.values.pop(0)


class _EvidenceProvider:
    def __init__(
        self,
        values: list[ExactAccountOwnerAssignmentEvidence | None],
    ) -> None:
        self.values = values
        self.calls: list[tuple[str, str, datetime]] = []

    def get_exact_current(
        self,
        *,
        evidence_id: str,
        evidence_version: str,
        as_of: datetime,
    ) -> ExactAccountOwnerAssignmentEvidence | None:
        self.calls.append((evidence_id, evidence_version, as_of))
        return self.values.pop(0)


class _Repository(AccountIdentityRawSourceRepository):
    def __init__(self, clocks: list[datetime] | None = None) -> None:
        self.clocks = clocks or [NOW, NOW + timedelta(seconds=1)]
        self.by_identity: dict[tuple[str, str], PersistedAccountIdentityRawSource] = {}
        self.heads: dict[tuple[str, str], PersistedAccountIdentityRawSource] = {}
        self.append_calls = 0
        self.expected_predecessors: list[str | None] = []

    def atomic(self) -> nullcontext[None]:
        return nullcontext()

    def now(self) -> datetime:
        return self.clocks.pop(0)

    def get_winner(
        self,
        *,
        source_id: str,
        source_version: str,
        as_of: datetime,
    ) -> PersistedAccountIdentityRawSource | None:
        return self.by_identity.get((source_id, source_version))

    def get_current_head(
        self,
        *,
        account_namespace: str,
        account_id: str,
        as_of: datetime,
    ) -> PersistedAccountIdentityRawSource | None:
        return self.heads.get((account_namespace, account_id))

    def append(
        self,
        record: PersistedAccountIdentityRawSource,
        *,
        expected_predecessor_hash: str | None,
        recorded_at: datetime,
    ) -> PersistedAccountIdentityRawSource:
        self.append_calls += 1
        self.expected_predecessors.append(expected_predecessor_hash)
        key = (record.source.source_id, record.source.source_version)
        logical = (record.source.account_namespace, record.source.account_id)
        if key in self.by_identity:
            raise AccountIdentityRawSourceConflict("first winner")
        current = self.heads.get(logical)
        current_hash = current.source.content_hash if current else None
        if current_hash != expected_predecessor_hash:
            raise AccountIdentityRawSourceConflict("CAS conflict")
        self.by_identity[key] = record
        self.heads[logical] = record
        return record

    def get_exact_by_hash(
        self,
        *,
        source_id: str,
        source_version: str,
        expected_content_hash: str,
        as_of: datetime,
    ) -> PersistedAccountIdentityRawSource | None:
        value = self.by_identity.get((source_id, source_version))
        if value is None or value.source.content_hash != expected_content_hash:
            return None
        return value


def _capture(
    repository: _Repository,
    *,
    rows: list[ExactUnifiedAccountRowObservation | None] | None = None,
    evidence: list[ExactAccountOwnerAssignmentEvidence | None] | None = None,
    actor: AccountIdentityRawSourceActor | None = None,
) -> tuple[CaptureAccountIdentityRawSource, _RowProvider, _EvidenceProvider]:
    row_values = rows or [_row(), _row()]
    evidence_values = evidence or [_evidence(), _evidence()]
    row_provider = _RowProvider(row_values)
    evidence_provider = _EvidenceProvider(evidence_values)
    return (
        CaptureAccountIdentityRawSource(
            row_provider=row_provider,
            assignment_evidence_provider=evidence_provider,
            repository=repository,
            actor=actor or _actor(),
            validity_period=timedelta(minutes=5),
        ),
        row_provider,
        evidence_provider,
    )


def test_capture_is_id_only_and_uses_one_server_cutoff_twice() -> None:
    command_fields = {field.name for field in fields(CaptureAccountIdentityRawSourceCommand)}
    assert command_fields == {
        "source_id",
        "source_version",
        "row_source_id",
        "row_source_version",
        "assignment_evidence_id",
        "assignment_evidence_version",
    }
    forbidden = {"owner_user_id", "content_hash", "account_id", "recorded_at", "is_active"}
    assert not command_fields & forbidden

    repository = _Repository()
    use_case, row_provider, evidence_provider = _capture(repository)
    source = use_case.execute(_command())

    assert source.owner_user_id == 19
    assert source.recorded_at == NOW + timedelta(seconds=1)
    assert source.ttl_valid_until == NOW + timedelta(minutes=5)
    assert [call[2] for call in row_provider.calls] == [NOW, NOW]
    assert [call[2] for call in evidence_provider.calls] == [NOW, NOW]
    assert repository.append_calls == 1


def test_missing_assignment_evidence_is_unknown_and_writes_nothing() -> None:
    repository = _Repository()
    use_case, _, _ = _capture(repository, evidence=[None])

    with pytest.raises(AccountIdentityRawSourceUnavailable, match="assignment evidence"):
        use_case.execute(_command())

    assert repository.append_calls == 0


def test_legacy_hint_without_exact_marker_evidence_writes_nothing() -> None:
    repository = _Repository()
    use_case, _, _ = _capture(repository, rows=[_row(row_owner_user_id=1)], evidence=[None])

    with pytest.raises(AccountIdentityRawSourceUnavailable, match="assignment evidence"):
        use_case.execute(_command())

    assert repository.append_calls == 0


def test_exact_legacy_marker_captures_no_owner_claim() -> None:
    legacy = _evidence(
        assignment_state="legacy_default",
        assigned_owner_user_id=None,
        artifact_type="account_legacy_default_assignment_evidence",
    )
    repository = _Repository()
    use_case, _, _ = _capture(repository, evidence=[legacy, legacy])

    source = use_case.execute(_command())

    assert source.assignment_state == "legacy_default"
    assert source.owner_user_id is None
    assert source.is_issuable_at(NOW + timedelta(seconds=2)) is False


@pytest.mark.parametrize(
    "row",
    [_row(account_type="simulated"), _row(account_type="real", is_active=False)],
)
def test_non_real_is_rejected_but_inactive_is_preserved(
    row: ExactUnifiedAccountRowObservation,
) -> None:
    repository = _Repository()
    use_case, _, _ = _capture(repository, rows=[row, row])

    if row.account_type != "real":
        with pytest.raises(AccountIdentityRawSourceUnavailable, match="real"):
            use_case.execute(_command())
        assert repository.append_calls == 0
    else:
        source = use_case.execute(_command())
        assert source.is_active is False


def test_authoritative_evidence_must_match_row_owner_and_exact_row() -> None:
    for evidence in (
        _evidence(assigned_owner_user_id=20),
        _evidence(row_source_content_hash="c" * 64),
        _evidence(account_id="other-account"),
    ):
        repository = _Repository()
        use_case, _, _ = _capture(repository, evidence=[evidence])
        with pytest.raises(AccountIdentityRawSourceCorruption, match="bind|owner"):
            use_case.execute(_command())
        assert repository.append_calls == 0


def test_first_and_final_row_or_evidence_change_fails_closed() -> None:
    repository = _Repository()
    use_case, _, _ = _capture(
        repository,
        rows=[_row(), _row(content_hash="c" * 64)],
        evidence=[_evidence(), _evidence(row_source_content_hash="c" * 64)],
    )
    with pytest.raises(AccountIdentityRawSourceConflict, match="changed"):
        use_case.execute(_command())
    assert repository.append_calls == 0

    repository = _Repository()
    use_case, _, _ = _capture(
        repository,
        evidence=[_evidence(), _evidence(content_hash="d" * 64)],
    )
    with pytest.raises(AccountIdentityRawSourceConflict, match="changed"):
        use_case.execute(_command())
    assert repository.append_calls == 0


def test_provider_identity_and_type_substitution_fail_closed() -> None:
    repository = _Repository()
    use_case, _, _ = _capture(repository, rows=[_row(source_version="wrong")])
    with pytest.raises(AccountIdentityRawSourceCorruption, match="identity"):
        use_case.execute(_command())

    class _WrongRow:
        pass

    repository = _Repository()
    row_provider = _RowProvider([])
    row_provider.values = [_WrongRow()]  # type: ignore[list-item]
    use_case = CaptureAccountIdentityRawSource(
        row_provider=row_provider,
        assignment_evidence_provider=_EvidenceProvider([_evidence()]),
        repository=repository,
        actor=_actor(),
        validity_period=timedelta(minutes=5),
    )
    with pytest.raises(AccountIdentityRawSourceCorruption, match="type substitution"):
        use_case.execute(_command())


def test_successor_uses_current_head_content_hash_for_cas() -> None:
    repository = _Repository()
    first_use_case, _, _ = _capture(repository)
    first = first_use_case.execute(_command())
    repository.clocks = [NOW + timedelta(minutes=1), NOW + timedelta(minutes=1, seconds=1)]
    next_row = _row(
        source_version="row-observation.v4",
        content_hash="c" * 64,
        observed_at=NOW + timedelta(seconds=30),
        valid_until=NOW + timedelta(minutes=11),
    )
    next_evidence = _evidence(
        evidence_version="owner-assignment.v2",
        content_hash="d" * 64,
        row_source_version="row-observation.v4",
        row_source_content_hash="c" * 64,
        valid_until=NOW + timedelta(minutes=9),
    )
    next_use_case, _, _ = _capture(
        repository,
        rows=[next_row, next_row],
        evidence=[next_evidence, next_evidence],
    )
    successor = next_use_case.execute(
        _command(
            source_version="account-identity-source.v2",
            row_source_version="row-observation.v4",
            assignment_evidence_version="owner-assignment.v2",
        )
    )

    assert successor.supersedes_content_hash == first.content_hash
    assert repository.expected_predecessors[-1] == first.content_hash


def test_original_actor_replays_first_winner_across_server_clocks() -> None:
    repository = _Repository()
    first_use_case, _, _ = _capture(repository)
    first = first_use_case.execute(_command())
    repository.clocks = [NOW + timedelta(minutes=1), NOW + timedelta(minutes=1, seconds=1)]
    replay_use_case, _, _ = _capture(repository)

    assert replay_use_case.execute(_command()) == first
    assert repository.append_calls == 1

    repository.clocks = [NOW + timedelta(minutes=2), NOW + timedelta(minutes=2, seconds=1)]
    other_actor_use_case, _, _ = _capture(repository, actor=_actor(actor_id="other-staff"))
    with pytest.raises(AccountIdentityRawSourceConflict, match="actor"):
        other_actor_use_case.execute(_command())


def test_exact_and_current_readers_are_inactive_and_point_in_time() -> None:
    repository = _Repository()
    use_case, _, _ = _capture(repository)
    source = use_case.execute(_command())
    as_of = NOW + timedelta(seconds=2)

    exact = GetExactAccountIdentityRawSource(repository).execute(
        GetExactAccountIdentityRawSourceCommand(
            source_id=source.source_id,
            source_version=source.source_version,
            expected_content_hash=source.content_hash,
            as_of=as_of,
        )
    )
    current = GetCurrentAccountIdentityRawSource(repository).execute(
        GetCurrentAccountIdentityRawSourceCommand.from_source(source, as_of=as_of)
    )

    assert exact == source
    assert current == source
    assert exact.activation_available is False
    assert exact.must_not_execute is True
    assert (
        GetExactAccountIdentityRawSource(repository).execute(
            GetExactAccountIdentityRawSourceCommand(
                source_id=source.source_id,
                source_version=source.source_version,
                expected_content_hash=source.content_hash,
                as_of=source.valid_until,
            )
        )
        is None
    )


def test_current_reader_closes_semantic_selectors_and_rejects_superseded_source() -> None:
    repository = _Repository()
    use_case, _, _ = _capture(repository)
    source = use_case.execute(_command())
    command = GetCurrentAccountIdentityRawSourceCommand.from_source(
        source,
        as_of=NOW + timedelta(seconds=2),
    )

    assert (
        GetCurrentAccountIdentityRawSource(repository).execute(
            replace(command, row_source_content_hash="f" * 64)
        )
        is None
    )

    repository.heads[(source.account_namespace, source.account_id)] = (
        PersistedAccountIdentityRawSource(
            source=replace(
                source,
                source_version="account-identity-source.v2",
                row_source_version="row-observation.v4",
                row_source_content_hash="c" * 64,
                observed_at=NOW + timedelta(seconds=2),
                recorded_at=NOW + timedelta(seconds=3),
                supersedes_content_hash=source.content_hash,
                identity_hash="",
                content_hash="",
            ),
            captured_by=_actor(),
        )
    )
    assert GetCurrentAccountIdentityRawSource(repository).execute(command) is None
