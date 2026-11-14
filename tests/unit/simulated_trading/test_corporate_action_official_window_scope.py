"""Current empty coverage is genuine scope evidence, never a fabricated event."""

from datetime import timedelta

import pytest

from apps.simulated_trading.application.corporate_action_current_official_window import (
    CorporateActionCurrentOfficialWindowReason as Reason,
)
from apps.simulated_trading.application.corporate_action_official_window_scope import (
    CorporateActionOfficialWindowScope,
)
from tests.unit.simulated_trading.test_corporate_action_current_official_window import (
    _ASSET,
    _NOW,
    _BodyVerifier,
    _Clock,
    _event,
    _policy,
    _reader,
    _request,
    _snapshot,
)


def _scope():
    return CorporateActionOfficialWindowScope(
        account_id=17, owner_user_id=23, asset_code=_ASSET, security_id=_ASSET
    )


def test_empty_complete_window_has_no_selected_or_fabricated_event():
    reader, snapshots, bodies = _reader(snapshots=(_snapshot(events=()),))
    proof = reader.read_current_scope(_scope(), as_of=_NOW)
    assert proof.window_ready is True
    assert proof.must_not_use_for_decision is True
    assert proof.scope == _scope()
    assert proof.snapshot.events == ()
    assert proof.expires_at == _snapshot(events=()).source_observed_at + timedelta(seconds=60)
    assert len(snapshots.requests) == 3
    assert bodies.calls == []
    # The legacy financial route still needs the actual selected event.
    assert reader.read_current(_request(), as_of=_NOW).window_ready is False


def test_scope_checks_every_actual_body_without_client_source_selector():
    event2 = _event(event_id="second")
    bodies = _BodyVerifier(frozenset({event2.source_event_id}))
    reader, _, _ = _reader(snapshots=(_snapshot(events=(_event(), event2)),), verifier=bodies)
    proof = reader.read_current_scope(_scope(), as_of=_NOW)
    assert proof.window_ready is False
    assert proof.reason_code is Reason.ORIGINAL_BODY_UNVERIFIED
    assert {row[0] for row in bodies.calls} == {_event().source_event_id, event2.source_event_id}


@pytest.mark.parametrize("change", ["policy", "snapshot", "expiry", "backwards"])
def test_scope_uses_same_final_policy_snapshot_expiry_and_clock_fences(change):
    kwargs = {"snapshots": (_snapshot(events=()),)}
    if change == "policy":
        from dataclasses import replace

        kwargs["policies"] = (_policy(), replace(_policy(), policy_content_hash="9" * 64))
    elif change == "snapshot":
        kwargs["snapshots"] = (_snapshot(events=()), _snapshot(events=(_event(),)))
    elif change == "expiry":
        kwargs["clock"] = _Clock((_NOW, _NOW + timedelta(seconds=50)))
    else:
        kwargs["clock"] = _Clock((_NOW, _NOW - timedelta(seconds=1)))
    reader, _, _ = _reader(**kwargs)
    assert reader.read_current_scope(_scope(), as_of=_NOW).window_ready is False


@pytest.mark.parametrize(
    "changes",
    [
        {"account_id": True},
        {"owner_user_id": 0},
        {"asset_code": "AAPL.US"},
        {"security_id": "foreign"},
    ],
)
def test_scope_rejects_coercive_or_inconsistent_owner_security(changes):
    from dataclasses import replace

    with pytest.raises(ValueError):
        replace(_scope(), **changes)
