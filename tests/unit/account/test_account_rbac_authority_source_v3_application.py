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
from apps.account.application.account_rbac_authority_source_v3 import (
    GetCurrentAccountRbacAuthoritySourceV3,
    GetExactAccountRbacAuthoritySourceV3,
    PersistedAccountRbacAuthoritySourceV3,
)
from apps.account.domain.account_actor_authority_raw_source_primitives_v3 import (
    AccountAuthorityRawSourceChainV3,
    AccountAuthorityRawSourceClockV3,
    AccountAuthorityRawSourceIdentityV3,
)
from apps.account.domain.account_rbac_authority_source_v3 import (
    AccountRbacAuthoritySourceV3,
    root_claim_hash_for_account_rbac_authority_source_v3,
)

NOW = datetime(2026, 8, 14, 12, tzinfo=UTC)
RECORDER = AccountActorAuthorityRawSourceV3Recorder("account-rbac-recorder-v3")


def _source(
    *, version: str = "v1", role: str = "owner", state: str = "current", start: datetime = NOW
) -> AccountRbacAuthoritySourceV3:
    source_id = "rbac-user-41"
    return AccountRbacAuthoritySourceV3(
        identity=AccountAuthorityRawSourceIdentityV3(source_id, version),
        clock=AccountAuthorityRawSourceClockV3(
            start - timedelta(minutes=1), start, start + timedelta(hours=1)
        ),
        chain=AccountAuthorityRawSourceChainV3(
            root_claim_hash=root_claim_hash_for_account_rbac_authority_source_v3(
                source_id=source_id, user_id=41, actor_id="django-user:41"
            )
        ),
        user_id=41,
        actor_id="django-user:41",
        rbac_role=role,
        authority_state=state,
    )


class FakeRepository:
    def __init__(self, exact: object | None, head: object | None = None) -> None:
        self.exact = exact
        self.head = exact if head is None else head

    def atomic(self):  # type: ignore[no-untyped-def]
        return nullcontext()

    def now(self) -> datetime:
        return NOW

    def get_winner(self, **kwargs: object) -> object | None:
        return self.exact

    def get_exact_by_hash(self, **kwargs: object) -> object | None:
        return self.exact

    def get_current_head(self, **kwargs: object) -> object | None:
        return self.head

    def append(self, record: object, **kwargs: object) -> object:
        return record


def _persisted(source: AccountRbacAuthoritySourceV3) -> PersistedAccountRbacAuthoritySourceV3:
    return PersistedAccountRbacAuthoritySourceV3(source, RECORDER)


def _selector(source: AccountRbacAuthoritySourceV3, *, as_of: datetime = NOW):
    return AccountActorAuthorityRawSourceV3Selector(
        source.identity.source_id, source.identity.source_version, source.content_hash, as_of
    )


def test_exact_history_survives_expiry_and_terminal_role_state() -> None:
    revoked = _source(role="read_only", state="revoked")
    cutoff = revoked.clock.valid_until + timedelta(days=1)

    assert (
        GetExactAccountRbacAuthoritySourceV3(FakeRepository(_persisted(revoked))).execute(
            _selector(revoked, as_of=cutoff)
        )
        == revoked
    )


def test_current_requires_final_equal_head_and_temporal_currentness() -> None:
    source = _source(role="admin")
    use_case = GetCurrentAccountRbacAuthoritySourceV3(FakeRepository(_persisted(source)))

    assert use_case.execute(_selector(source)) == source
    assert use_case.execute(_selector(source, as_of=source.clock.valid_until)) is None


def test_revoked_or_superseded_final_head_never_falls_back() -> None:
    old = _source()
    revoked = _source(
        version="v2", role="read_only", state="revoked", start=NOW + timedelta(minutes=2)
    )

    assert (
        GetCurrentAccountRbacAuthoritySourceV3(
            FakeRepository(_persisted(old), _persisted(revoked))
        ).execute(_selector(old, as_of=revoked.clock.recorded_at))
        is None
    )
    assert (
        GetCurrentAccountRbacAuthoritySourceV3(FakeRepository(_persisted(revoked))).execute(
            _selector(revoked, as_of=revoked.clock.recorded_at)
        )
        is None
    )


def test_repository_type_and_selector_substitution_are_corruption() -> None:
    source = _source()
    with pytest.raises(AccountActorAuthorityRawSourceV3Corruption):
        GetExactAccountRbacAuthoritySourceV3(FakeRepository(object())).execute(_selector(source))

    replacement = _source(version="v2")
    with pytest.raises(AccountActorAuthorityRawSourceV3Corruption, match="selector"):
        GetExactAccountRbacAuthoritySourceV3(FakeRepository(_persisted(replacement))).execute(
            _selector(source)
        )


def test_current_rejects_source_and_recorder_head_substitution() -> None:
    source = _source()
    other_source_id = "other-rbac-authority"
    other_source = AccountRbacAuthoritySourceV3(
        identity=AccountAuthorityRawSourceIdentityV3(other_source_id, "v1"),
        clock=source.clock,
        chain=AccountAuthorityRawSourceChainV3(
            root_claim_hash=root_claim_hash_for_account_rbac_authority_source_v3(
                source_id=other_source_id,
                user_id=source.user_id,
                actor_id=source.actor_id,
            )
        ),
        user_id=source.user_id,
        actor_id=source.actor_id,
        rbac_role=source.rbac_role,
        authority_state=source.authority_state,
    )
    for head in (
        _persisted(other_source),
        PersistedAccountRbacAuthoritySourceV3(
            source,
            AccountActorAuthorityRawSourceV3Recorder("other-rbac-recorder-v3"),
        ),
    ):
        with pytest.raises(AccountActorAuthorityRawSourceV3Corruption):
            GetCurrentAccountRbacAuthoritySourceV3(
                FakeRepository(_persisted(source), head)
            ).execute(_selector(source))


def test_missing_is_none_and_future_repository_row_is_corruption() -> None:
    source = _source()
    before = source.clock.recorded_at - timedelta(microseconds=1)

    assert (
        GetExactAccountRbacAuthoritySourceV3(FakeRepository(None)).execute(_selector(source))
        is None
    )
    with pytest.raises(AccountActorAuthorityRawSourceV3Corruption, match="future"):
        GetExactAccountRbacAuthoritySourceV3(FakeRepository(_persisted(source))).execute(
            _selector(source, as_of=before)
        )


def test_application_is_pure_and_has_no_capture_or_live_profile_dependency() -> None:
    path = Path("apps/account/application/account_rbac_authority_source_v3.py")
    text = path.read_text(encoding="utf-8")
    tree = ast.parse(text)
    imports = {node.module or "" for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)}

    assert all(not name.startswith(("django", "apps.account.infrastructure")) for name in imports)
    assert ".objects" not in text
    assert "AccountProfile" not in text
    assert "normalize_role" not in text
    assert "CaptureAccountRbac" not in text
