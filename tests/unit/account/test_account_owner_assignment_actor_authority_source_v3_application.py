from __future__ import annotations

import ast
from contextlib import nullcontext
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from apps.account.application.account_owner_assignment_actor_authority_source_v3 import (
    AccountOwnerAssignmentActorAuthoritySourceV3Conflict,
    AccountOwnerAssignmentActorAuthoritySourceV3Corruption,
    AccountOwnerAssignmentActorAuthoritySourceV3Recorder,
    AccountOwnerAssignmentActorAuthoritySourceV3Unavailable,
    CaptureAccountOwnerAssignmentActorAuthoritySourceV3,
    CaptureAccountOwnerAssignmentActorAuthoritySourceV3Command,
    ExactCurrentAccountRbacAuthorityV3,
    ExactCurrentAccountUserAuthorityV3,
    ExactCurrentActorAuthorityInputBundleV3,
    ExactCurrentAuthenticationContextV3,
    GetCurrentAccountOwnerAssignmentActorAuthoritySourceV3,
    GetCurrentAccountOwnerAssignmentActorAuthoritySourceV3Command,
    GetExactAccountOwnerAssignmentActorAuthoritySourceV3,
    GetExactAccountOwnerAssignmentActorAuthoritySourceV3Command,
    PersistedAccountOwnerAssignmentActorAuthoritySourceV3,
)


def _at(hour: int) -> datetime:
    return datetime(2026, 8, 14, hour, tzinfo=UTC)


def _bundle(
    *, authenticated: bool = True, active: bool = True, recorded_hour: int = 8
) -> ExactCurrentActorAuthorityInputBundleV3:
    return ExactCurrentActorAuthorityInputBundleV3(
        ExactCurrentAuthenticationContextV3(
            "session-a",
            "g1",
            "a" * 64,
            "b" * 64,
            "principal-41",
            41,
            authenticated,
            _at(7),
            _at(recorded_hour),
            _at(18),
        ),
        ExactCurrentAccountUserAuthorityV3(
            "user-41",
            "v1",
            "c" * 64,
            "d" * 64,
            41,
            "django-user:41",
            active,
            False,
            False,
            _at(recorded_hour),
            _at(18),
        ),
        ExactCurrentAccountRbacAuthorityV3(
            "rbac-41",
            "v1",
            "e" * 64,
            "f" * 64,
            41,
            "owner",
            _at(recorded_hour),
            _at(18),
        ),
    )


def _command(version: str = "v1") -> CaptureAccountOwnerAssignmentActorAuthoritySourceV3Command:
    return CaptureAccountOwnerAssignmentActorAuthoritySourceV3Command(
        "authority-41",
        version,
        "principal-41",
        41,
        "session-a",
        "g1",
        "b" * 64,
        "user-41",
        "v1",
        "d" * 64,
        "rbac-41",
        "v1",
        "f" * 64,
    )


class _Provider:
    def __init__(self, values: list[ExactCurrentActorAuthorityInputBundleV3 | None]) -> None:
        self.values = values
        self.calls: list[dict[str, object]] = []

    def get_exact_current(self, **kwargs: object) -> ExactCurrentActorAuthorityInputBundleV3 | None:
        self.calls.append(kwargs)
        return self.values.pop(0) if len(self.values) > 1 else self.values[0]


class _Repository:
    def __init__(self) -> None:
        self.clocks = [_at(10), _at(11)]
        self.winner: PersistedAccountOwnerAssignmentActorAuthoritySourceV3 | None = None
        self.head: PersistedAccountOwnerAssignmentActorAuthoritySourceV3 | None = None
        self.exact: PersistedAccountOwnerAssignmentActorAuthoritySourceV3 | None = None
        self.predecessor: str | None = "unset"

    def atomic(self):  # type: ignore[no-untyped-def]
        return nullcontext()

    def now(self) -> datetime:
        return self.clocks.pop(0) if len(self.clocks) > 1 else self.clocks[0]

    def get_winner(
        self, **kwargs: object
    ) -> PersistedAccountOwnerAssignmentActorAuthoritySourceV3 | None:
        return self.winner

    def get_current_head(
        self, **kwargs: object
    ) -> PersistedAccountOwnerAssignmentActorAuthoritySourceV3 | None:
        return self.head

    def get_exact_by_hash(
        self, **kwargs: object
    ) -> PersistedAccountOwnerAssignmentActorAuthoritySourceV3 | None:
        return self.exact

    def append(
        self,
        record: PersistedAccountOwnerAssignmentActorAuthoritySourceV3,
        *,
        expected_predecessor_hash: str | None,
        recorded_at: datetime,
    ) -> PersistedAccountOwnerAssignmentActorAuthoritySourceV3:
        self.predecessor = expected_predecessor_hash
        self.winner = self.head = self.exact = record
        return record


def _capture(
    provider: _Provider, repository: _Repository
) -> CaptureAccountOwnerAssignmentActorAuthoritySourceV3:
    return CaptureAccountOwnerAssignmentActorAuthoritySourceV3(
        input_bundle_provider=provider,
        repository=repository,
        recorder=AccountOwnerAssignmentActorAuthoritySourceV3Recorder("authority-attestor"),
        validity_period=timedelta(hours=2),
    )


def test_capture_command_is_id_selector_only_and_reads_atomic_bundle_three_times() -> None:
    provider = _Provider([_bundle(), _bundle(), _bundle()])
    repository = _Repository()

    source = _capture(provider, repository).execute(_command())

    assert len(provider.calls) == 3
    assert [call["as_of"] for call in provider.calls] == [_at(10), _at(10), _at(11)]
    assert source.recorded_at == _at(11)
    assert source.root_claim_hash is not None
    assert repository.predecessor is None
    assert "context" not in _command().__dataclass_fields__


def test_first_winner_replay_precedes_all_current_bundle_reads() -> None:
    repository = _Repository()
    first = _capture(_Provider([_bundle(), _bundle(), _bundle()]), repository).execute(_command())
    provider = _Provider([None])
    repository.clocks = [_at(17)]

    assert _capture(provider, repository).execute(_command()) == first
    assert provider.calls == []


def test_missing_bundle_is_unavailable() -> None:
    with pytest.raises(AccountOwnerAssignmentActorAuthoritySourceV3Unavailable):
        _capture(_Provider([None]), _Repository()).execute(_command())


@pytest.mark.parametrize(
    "values",
    [
        [_bundle(), None],
        [_bundle(), _bundle(), None],
    ],
)
def test_bundle_disappearing_after_first_read_is_a_conflict(
    values: list[ExactCurrentActorAuthorityInputBundleV3 | None],
) -> None:
    with pytest.raises(AccountOwnerAssignmentActorAuthoritySourceV3Conflict):
        _capture(_Provider(values), _Repository()).execute(_command())


def test_bundle_rejects_member_type_substitution() -> None:
    bundle = object.__new__(ExactCurrentActorAuthorityInputBundleV3)
    object.__setattr__(bundle, "context", object())
    object.__setattr__(bundle, "user", _bundle().user)
    object.__setattr__(bundle, "rbac", _bundle().rbac)

    with pytest.raises(AccountOwnerAssignmentActorAuthoritySourceV3Corruption):
        _capture(_Provider([bundle]), _Repository()).execute(_command())


def test_successor_uses_same_session_head_and_predecessor_cas() -> None:
    repository = _Repository()
    first = _capture(_Provider([_bundle(), _bundle(), _bundle()]), repository).execute(_command())
    repository.winner = None
    repository.clocks = [_at(12), _at(13)]
    second = _capture(
        _Provider(
            [
                _bundle(recorded_hour=12),
                _bundle(recorded_hour=12),
                _bundle(recorded_hour=12),
            ]
        ),
        repository,
    ).execute(_command("v2"))

    assert second.supersedes_content_hash == first.content_hash
    assert repository.predecessor == first.content_hash


def test_exact_is_historical_but_current_requires_temporal_head_and_live_bundle() -> None:
    repository = _Repository()
    source = _capture(_Provider([_bundle(), _bundle(), _bundle()]), repository).execute(_command())
    exact = GetExactAccountOwnerAssignmentActorAuthoritySourceV3(repository)
    assert (
        exact.execute(
            GetExactAccountOwnerAssignmentActorAuthoritySourceV3Command(
                source.source_id, source.source_version, source.content_hash, _at(17)
            )
        )
        == source
    )
    current = GetCurrentAccountOwnerAssignmentActorAuthoritySourceV3(
        input_bundle_provider=_Provider([_bundle()]), repository=repository
    )
    assert (
        current.execute(
            GetCurrentAccountOwnerAssignmentActorAuthoritySourceV3Command(
                source.source_id, source.source_version, source.content_hash, _at(11)
            )
        )
        == source
    )
    assert (
        GetCurrentAccountOwnerAssignmentActorAuthoritySourceV3(
            input_bundle_provider=_Provider([None]), repository=repository
        ).execute(
            GetCurrentAccountOwnerAssignmentActorAuthoritySourceV3Command(
                source.source_id, source.source_version, source.content_hash, _at(11)
            )
        )
        is None
    )


def test_terminal_preserves_authentication_fact_and_never_becomes_current() -> None:
    repository = _Repository()
    source = _capture(
        _Provider([_bundle(active=False), _bundle(active=False), _bundle(active=False)]),
        repository,
    ).execute(_command())
    assert source.authority_state == "deactivated"
    assert source.is_authenticated is True
    assert not source.is_temporally_current_at(_at(12))


def test_application_has_no_django_orm_or_infrastructure_import() -> None:
    source = (
        Path(__file__).parents[3]
        / "apps/account/application/account_owner_assignment_actor_authority_source_v3.py"
    ).read_text(encoding="utf-8")
    modules = {
        node.module
        for node in ast.walk(ast.parse(source))
        if isinstance(node, ast.ImportFrom) and node.module is not None
    }
    assert ".objects" not in source
    assert not any(module.startswith("django") or "infrastructure" in module for module in modules)
