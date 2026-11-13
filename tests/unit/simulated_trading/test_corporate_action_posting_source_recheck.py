"""Unit ordering checks; actual atomic rollback is separately tested natively."""

from types import SimpleNamespace

import pytest

from apps.simulated_trading import audited_corporate_action_posting_composition as audited
from apps.simulated_trading.application.corporate_action_posting import (
    CorporateActionPostingBlockedError,
    CorporateActionPostingReceipt,
)
from tests.unit.simulated_trading.test_corporate_action_posting import _request


@pytest.mark.parametrize("replayed", [False, True])
def test_audited_new_writes_recheck_source_after_audit_but_exact_replay_does_not(
    monkeypatch: pytest.MonkeyPatch, replayed: bool
) -> None:
    """Current sources can invalidate a new write without invalidating a retained replay."""
    request = _request()
    receipt = CorporateActionPostingReceipt(
        entry_id=11,
        account_revision=1,
        stage_key=request.stage_key,
        request_payload_sha256=request.payload_sha256,
        replayed=replayed,
    )
    calls: list[str] = []
    authority = SimpleNamespace(user_id=request.owner_user_id, scope=object(), grant=object())
    event = SimpleNamespace(predecessor_hash=None, recorded_at=request.posted_at)

    def post_revision(requests):
        calls.append("post")
        return (receipt,)

    def assert_current_sources(requests):
        assert requests == (request,)
        calls.append("final source")
        raise CorporateActionPostingBlockedError("source changed", code="TEST_SOURCE_CHANGED")

    def append_and_enqueue(value, **kwargs):
        calls.append("audit")
        return SimpleNamespace(event=value)

    repository = object.__new__(audited.DjangoAuditedCorporateActionPostingRepository)
    repository._using = "default"
    repository._posting = SimpleNamespace(
        post_revision=post_revision,
        assert_current_sources=assert_current_sources,
    )
    repository._coordinator = SimpleNamespace(
        get_winner=lambda **kwargs: event if replayed else None,
        get_exact_outbox_winner_targeted=lambda winner: SimpleNamespace(event=winner),
        get_current_head=lambda **kwargs: None,
        append_and_enqueue=append_and_enqueue,
    )
    monkeypatch.setattr(audited, "_locked_owner_user_id", lambda *args, **kwargs: authority.user_id)
    monkeypatch.setattr(audited, "_build_event", lambda *args, **kwargs: event)
    monkeypatch.setattr(repository, "_assert_current_authority", lambda expected: expected)
    monkeypatch.setattr(repository, "_matches_winner", lambda *args, **kwargs: True)
    if replayed:
        assert repository._post_revision_in_atomic((request,), authority=authority) == (receipt,)
        assert calls == ["post"]
    else:
        with pytest.raises(CorporateActionPostingBlockedError) as blocked:
            repository._post_revision_in_atomic((request,), authority=authority)
        assert blocked.value.code == "TEST_SOURCE_CHANGED"
        assert calls == ["post", "audit", "final source"]
