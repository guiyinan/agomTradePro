from __future__ import annotations

import ast
from contextlib import nullcontext
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from apps.account.application.account_actor_authority_raw_source_primitives_v3 import (
    AccountActorAuthorityRawSourceV3Corruption,
    AccountActorAuthorityRawSourceV3Recorder,
    AccountActorAuthorityRawSourceV3Selector,
)
from apps.account.application.account_user_authority_source_v3 import (
    GetCurrentAccountUserAuthoritySourceV3,
    GetExactAccountUserAuthoritySourceV3,
    PersistedAccountUserAuthoritySourceV3,
)
from apps.account.domain.account_actor_authority_raw_source_primitives_v3 import (
    AccountAuthorityRawSourceChainV3,
    AccountAuthorityRawSourceIdentityV3,
)
from apps.account.domain.account_user_authority_source_v3 import (
    AccountUserAuthoritySourceV3,
    root_claim_hash_for_account_user_authority_source_v3,
)
from tests.unit.account.test_account_user_authority_source_v3 import _source, _successor

NOW = datetime(2026, 8, 14, 10, tzinfo=UTC)


def _record(source: AccountUserAuthoritySourceV3) -> PersistedAccountUserAuthoritySourceV3:
    return PersistedAccountUserAuthoritySourceV3(
        source,
        AccountActorAuthorityRawSourceV3Recorder("account-user-authority-recorder-v3"),
    )


def _selector(
    source: AccountUserAuthoritySourceV3, as_of: datetime = NOW
) -> AccountActorAuthorityRawSourceV3Selector:
    return AccountActorAuthorityRawSourceV3Selector(
        source.identity.source_id,
        source.identity.source_version,
        source.content_hash,
        as_of,
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
        self.exact_calls: list[dict[str, object]] = []
        self.head_calls: list[dict[str, object]] = []

    def atomic(self) -> nullcontext[None]:
        return nullcontext()

    def now(self) -> datetime:
        return NOW

    def get_winner(self, **kwargs: object) -> object:
        del kwargs
        return None

    def get_exact_by_hash(self, **kwargs: object) -> object:
        self.exact_calls.append(kwargs)
        return self.exact

    def get_current_head(self, **kwargs: object) -> object:
        self.head_calls.append(kwargs)
        return self.head

    def append(self, record: object, **kwargs: object) -> object:
        del kwargs
        return record


def test_get_exact_uses_only_scalar_selector_and_is_historically_permanent() -> None:
    source = _source()
    repository = _Repository(exact=_record(source))
    reader = GetExactAccountUserAuthoritySourceV3(repository)  # type: ignore[arg-type]

    assert reader.execute(_selector(source, NOW + timedelta(days=10))) == source
    assert repository.exact_calls == [
        {
            "source_id": source.identity.source_id,
            "source_version": source.identity.source_version,
            "expected_content_hash": source.content_hash,
            "as_of": NOW + timedelta(days=10),
        }
    ]


def test_get_exact_returns_none_for_missing_and_rejects_future_repository_row() -> None:
    source = _source()
    assert (
        GetExactAccountUserAuthoritySourceV3(  # type: ignore[arg-type]
            _Repository(exact=None)
        ).execute(_selector(source))
        is None
    )
    with pytest.raises(AccountActorAuthorityRawSourceV3Corruption, match="future"):
        GetExactAccountUserAuthoritySourceV3(  # type: ignore[arg-type]
            _Repository(exact=_record(source))
        ).execute(_selector(source, NOW - timedelta(microseconds=1)))


def test_get_current_requires_exact_final_head_equality() -> None:
    source = _source()
    repository = _Repository(exact=_record(source), head=_record(source))

    assert (
        GetCurrentAccountUserAuthoritySourceV3(repository).execute(  # type: ignore[arg-type]
            _selector(source)
        )
        == source
    )
    assert repository.head_calls == [{"source_id": source.identity.source_id, "as_of": NOW}]


def test_get_current_never_falls_back_from_superseded_terminal_or_expired() -> None:
    source = _source()
    successor = _successor(source, is_staff=True)
    terminal = _successor(source, authority_state="deactivated", is_active=False)
    expired_at = source.clock.valid_until

    superseded = _Repository(exact=_record(source), head=_record(successor))
    assert (
        GetCurrentAccountUserAuthoritySourceV3(superseded).execute(  # type: ignore[arg-type]
            _selector(source, successor.clock.recorded_at)
        )
        is None
    )
    terminal_repository = _Repository(exact=_record(terminal), head=_record(terminal))
    assert (
        GetCurrentAccountUserAuthoritySourceV3(terminal_repository).execute(  # type: ignore[arg-type]
            _selector(terminal, terminal.clock.recorded_at)
        )
        is None
    )
    expired = _Repository(exact=_record(source), head=_record(source))
    assert (
        GetCurrentAccountUserAuthoritySourceV3(expired).execute(  # type: ignore[arg-type]
            _selector(source, expired_at)
        )
        is None
    )
    assert terminal_repository.head_calls == []
    assert expired.head_calls == []


def test_selector_hash_and_repository_type_substitution_raise_corruption() -> None:
    source = _source()
    other = _source(identity=type(source.identity)(source.identity.source_id, "other-version"))
    reader = GetExactAccountUserAuthoritySourceV3(  # type: ignore[arg-type]
        _Repository(exact=_record(other))
    )
    with pytest.raises(AccountActorAuthorityRawSourceV3Corruption):
        reader.execute(_selector(source))
    with pytest.raises(AccountActorAuthorityRawSourceV3Corruption):
        reader.execute(object())  # type: ignore[arg-type]
    with pytest.raises(AccountActorAuthorityRawSourceV3Corruption):
        GetExactAccountUserAuthoritySourceV3(  # type: ignore[arg-type]
            _Repository(exact=source)
        ).execute(_selector(source))


def test_current_rejects_source_and_recorder_head_substitution() -> None:
    source = _source()
    other_source = _source(
        identity=AccountAuthorityRawSourceIdentityV3(
            "other-user-authority", source.identity.source_version
        ),
        chain=AccountAuthorityRawSourceChainV3(
            root_claim_hash=root_claim_hash_for_account_user_authority_source_v3(
                source_id="other-user-authority",
                user_id=source.user_id,
                actor_id=source.actor_id,
            )
        ),
    )
    for head in (
        _record(other_source),
        PersistedAccountUserAuthoritySourceV3(
            source,
            AccountActorAuthorityRawSourceV3Recorder("other-user-authority-recorder-v3"),
        ),
    ):
        with pytest.raises(AccountActorAuthorityRawSourceV3Corruption):
            GetCurrentAccountUserAuthoritySourceV3(  # type: ignore[arg-type]
                _Repository(exact=_record(source), head=head)
            ).execute(_selector(source))


def test_application_contract_has_no_capture_provider_orm_or_live_user_dependency() -> None:
    path = Path("apps/account/application/account_user_authority_source_v3.py")
    source = path.read_text(encoding="utf-8")
    tree = ast.parse(source)
    imports = {node.module or "" for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)}

    assert all(not name.startswith(("django", "apps.account.infrastructure")) for name in imports)
    assert ".objects" not in source
    assert "Provider" not in source
    assert "Capture" not in source
    assert "django.contrib.auth" not in source
