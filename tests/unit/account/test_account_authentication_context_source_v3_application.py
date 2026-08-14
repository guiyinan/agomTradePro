from __future__ import annotations

import ast
from contextlib import AbstractContextManager, nullcontext
from dataclasses import FrozenInstanceError
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from apps.account.application.account_actor_authority_raw_source_primitives_v3 import (
    AccountActorAuthorityRawSourceV3Corruption,
    AccountActorAuthorityRawSourceV3Recorder,
    AccountActorAuthorityRawSourceV3Selector,
)
from apps.account.application.account_authentication_context_source_v3 import (
    GetCurrentAccountAuthenticationContextSourceV3,
    GetExactAccountAuthenticationContextSourceV3,
    PersistedAccountAuthenticationContextSourceV3,
)
from apps.account.domain.account_actor_authority_raw_source_primitives_v3 import (
    AccountAuthorityRawSourceChainV3,
    AccountAuthorityRawSourceIdentityV3,
)
from apps.account.domain.account_authentication_context_source_v3 import (
    AccountAuthenticationContextSourceV3,
    root_claim_hash_for_account_authentication_context_source_v3,
)
from tests.unit.account.test_account_authentication_context_source_v3 import (
    NOW,
    _source,
    _successor,
)


class _Repository:
    def __init__(
        self,
        *,
        exact: object = None,
        head: object = None,
    ) -> None:
        self.exact = exact
        self.head = head
        self.exact_calls: list[tuple[str, str, str, datetime]] = []
        self.head_calls: list[tuple[str, datetime]] = []

    def atomic(self) -> AbstractContextManager[None]:
        return nullcontext()

    def now(self) -> datetime:
        return NOW

    def get_winner(
        self, *, source_id: str, source_version: str, as_of: datetime
    ) -> PersistedAccountAuthenticationContextSourceV3 | None:
        return None

    def get_current_head(
        self, *, source_id: str, as_of: datetime
    ) -> PersistedAccountAuthenticationContextSourceV3 | None:
        self.head_calls.append((source_id, as_of))
        return self.head  # type: ignore[return-value]

    def get_exact_by_hash(
        self,
        *,
        source_id: str,
        source_version: str,
        expected_content_hash: str,
        as_of: datetime,
    ) -> PersistedAccountAuthenticationContextSourceV3 | None:
        self.exact_calls.append((source_id, source_version, expected_content_hash, as_of))
        return self.exact  # type: ignore[return-value]

    def append(
        self,
        record: PersistedAccountAuthenticationContextSourceV3,
        *,
        expected_predecessor_hash: str | None,
        recorded_at: datetime,
    ) -> PersistedAccountAuthenticationContextSourceV3:
        return record


def _record(
    source: AccountAuthenticationContextSourceV3,
) -> PersistedAccountAuthenticationContextSourceV3:
    return PersistedAccountAuthenticationContextSourceV3(
        source,
        AccountActorAuthorityRawSourceV3Recorder("account-auth-context-recorder-v3"),
    )


def _selector(
    source: AccountAuthenticationContextSourceV3, *, as_of: datetime | None = None
) -> AccountActorAuthorityRawSourceV3Selector:
    return AccountActorAuthorityRawSourceV3Selector(
        source.identity.source_id,
        source.identity.source_version,
        source.content_hash,
        as_of or source.clock.recorded_at,
    )


def test_persisted_wrapper_is_exact_frozen_and_revalidates_recorder() -> None:
    record = _record(_source())

    assert record.source.identity.source_id == "session-41"
    assert record.recorded_by.role == "account_actor_authority_raw_recorder"
    with pytest.raises(FrozenInstanceError):
        record.source = _source()  # type: ignore[misc]
    with pytest.raises(TypeError):
        PersistedAccountAuthenticationContextSourceV3(
            object(),
            record.recorded_by,  # type: ignore[arg-type]
        )


def test_exact_returns_permanent_historical_version_and_forwards_scalar_selector() -> None:
    source = _source()
    cutoff = source.clock.valid_until + timedelta(days=10)
    selector = _selector(source, as_of=cutoff)
    repository = _Repository(exact=_record(source))

    result = GetExactAccountAuthenticationContextSourceV3(repository).execute(selector)

    assert result == source
    assert repository.exact_calls == [
        (
            source.identity.source_id,
            source.identity.source_version,
            source.content_hash,
            cutoff,
        )
    ]


def test_unavailable_is_only_none_and_never_falls_back() -> None:
    source = _source()
    repository = _Repository(exact=None, head=_record(source))

    assert (
        GetExactAccountAuthenticationContextSourceV3(repository).execute(_selector(source)) is None
    )
    assert (
        GetCurrentAccountAuthenticationContextSourceV3(repository).execute(_selector(source))
        is None
    )
    assert repository.head_calls == []


@pytest.mark.parametrize("substitution", ["type", "version", "hash"])
def test_exact_rejects_repository_type_selector_and_hash_substitution(
    substitution: str,
) -> None:
    source = _source()
    if substitution == "type":
        returned: object = object()
    elif substitution == "version":
        returned = _record(_successor(source))
    else:
        returned = _record(_source(is_authenticated=False, authority_state="revoked"))
    repository = _Repository(exact=returned)

    with pytest.raises(AccountActorAuthorityRawSourceV3Corruption):
        GetExactAccountAuthenticationContextSourceV3(repository).execute(_selector(source))


def test_exact_rejects_future_record_returned_for_pit_cutoff() -> None:
    source = _source()
    repository = _Repository(exact=_record(source))

    with pytest.raises(AccountActorAuthorityRawSourceV3Corruption):
        GetExactAccountAuthenticationContextSourceV3(repository).execute(
            _selector(source, as_of=source.clock.recorded_at - timedelta(microseconds=1))
        )


def test_current_returns_only_exact_live_final_head() -> None:
    source = _source()
    record = _record(source)
    repository = _Repository(exact=record, head=record)

    assert (
        GetCurrentAccountAuthenticationContextSourceV3(repository).execute(_selector(source))
        == source
    )
    assert repository.head_calls == [(source.identity.source_id, source.clock.recorded_at)]


def test_current_terminal_expired_and_superseded_return_none_without_fallback() -> None:
    source = _source()
    terminal = _source(is_authenticated=False, authority_state="revoked")
    successor = _successor(source)

    terminal_repo = _Repository(exact=_record(terminal), head=_record(terminal))
    assert (
        GetCurrentAccountAuthenticationContextSourceV3(terminal_repo).execute(_selector(terminal))
        is None
    )
    assert terminal_repo.head_calls == []

    expired_at = source.clock.valid_until
    expired_repo = _Repository(exact=_record(source), head=_record(source))
    assert (
        GetCurrentAccountAuthenticationContextSourceV3(expired_repo).execute(
            _selector(source, as_of=expired_at)
        )
        is None
    )
    assert expired_repo.head_calls == []

    superseded_repo = _Repository(exact=_record(source), head=_record(successor))
    assert (
        GetCurrentAccountAuthenticationContextSourceV3(superseded_repo).execute(
            _selector(source, as_of=successor.clock.recorded_at)
        )
        is None
    )
    assert len(superseded_repo.head_calls) == 1


@pytest.mark.parametrize("substitution", ["type", "source", "same_version_hash", "recorder"])
def test_current_rejects_head_repository_substitution(substitution: str) -> None:
    source = _source()
    if substitution == "type":
        head: object = object()
    elif substitution == "source":
        other_source_id = "other-session"
        other = _source(
            identity=AccountAuthorityRawSourceIdentityV3(other_source_id, "v1"),
            chain=AccountAuthorityRawSourceChainV3(
                root_claim_hash=root_claim_hash_for_account_authentication_context_source_v3(
                    source_id=other_source_id,
                    principal_id="principal-41",
                    user_id=41,
                    actor_id="django-user:41",
                )
            ),
        )
        head = _record(other)
    elif substitution == "same_version_hash":
        head = _record(_source(is_authenticated=False, authority_state="revoked"))
    else:
        head = PersistedAccountAuthenticationContextSourceV3(
            source,
            AccountActorAuthorityRawSourceV3Recorder("other-auth-context-recorder-v3"),
        )
    repository = _Repository(exact=_record(source), head=head)

    with pytest.raises(AccountActorAuthorityRawSourceV3Corruption):
        GetCurrentAccountAuthenticationContextSourceV3(repository).execute(_selector(source))


def test_use_cases_require_exact_common_selector() -> None:
    repository = _Repository()
    with pytest.raises(AccountActorAuthorityRawSourceV3Corruption):
        GetExactAccountAuthenticationContextSourceV3(repository).execute(
            object()  # type: ignore[arg-type]
        )


def test_application_contract_has_no_orm_provider_capture_or_mutable_source() -> None:
    path = Path("apps/account/application/account_authentication_context_source_v3.py")
    source = path.read_text(encoding="utf-8")
    tree = ast.parse(source)
    imports = {node.module or "" for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)} | {
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    }

    assert all(not name.startswith(("django", "apps.account.infrastructure")) for name in imports)
    assert ".objects" not in source
    assert "Provider" not in source
    assert "Capture" not in source
