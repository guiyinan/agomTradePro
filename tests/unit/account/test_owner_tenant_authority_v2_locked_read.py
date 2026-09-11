"""Contract tests for the owner transaction callback; no database proof implied."""

from contextlib import contextmanager
from datetime import timedelta
from types import SimpleNamespace

import pytest

from apps.account import owner_tenant_authority_v2_composition as composition
from tests.unit.account.test_owner_tenant_authority_v2_application import _selector, _World


def _facade(monkeypatch):
    world = _World()
    service = world.service()
    root = service.issue(world.issue_command())
    events = []

    @contextmanager
    def atomic(*, using):
        assert using == "owner-test"
        events.append("transaction-enter")
        try:
            yield
        finally:
            events.append("transaction-exit")

    @contextmanager
    def actors_atomic():
        events.append("actors-enter")
        try:
            yield
        finally:
            events.append("actors-exit")

    def lock(*, using, policy_id):
        assert using == "owner-test" and policy_id == world.policy.policy_id
        events.append("locked")

    monkeypatch.setattr(
        composition, "connections", {"owner-test": SimpleNamespace(vendor="postgresql")}
    )
    monkeypatch.setattr(composition.transaction, "atomic", atomic)
    monkeypatch.setattr(composition, "lock_owner_tenant_authority_v2_sources", lock)
    facade = composition.OwnerTenantAuthorityV2Facade(
        using="owner-test",
        policy_id=world.policy.policy_id,
        actors=SimpleNamespace(atomic=actors_atomic),
        service=service,
    )
    return world, facade, _selector(root), events


def test_callback_and_final_current_read_remain_inside_source_transaction(monkeypatch):
    world, facade, selector, events = _facade(monkeypatch)
    initial_reads = world.people_reads

    def read(current):
        assert current.authority.content_hash == selector.expected_content_hash
        assert events == ["transaction-enter", "locked", "actors-enter"]
        events.append("read")
        return ("materialized-evidence",)

    assert facade.unit_of_work_key == "django:owner-test"
    assert facade.with_current(selector, read) == ("materialized-evidence",)
    assert world.people_reads - initial_reads >= 4
    assert events == [
        "transaction-enter",
        "locked",
        "actors-enter",
        "read",
        "actors-exit",
        "transaction-exit",
    ]


def test_unavailable_current_never_calls_reader(monkeypatch):
    world, facade, selector, _ = _facade(monkeypatch)
    world.physical_changes = {"user_id": None}

    def read(current):
        pytest.fail("unavailable ownership must not reach evidence")

    assert facade.with_current(selector, read) is None


@pytest.mark.parametrize("change", ["expiry", "authentication", "physical", "extended-window"])
def test_source_change_during_read_discards_materialized_result(monkeypatch, change):
    world, facade, selector, events = _facade(monkeypatch)
    if change == "extended-window":
        world.participant_limit = world.repository.clock + timedelta(seconds=30)

    def read(current):
        events.append("read")
        if change == "expiry":
            world.repository.clock = current.valid_until
        elif change == "authentication":
            world.reauthenticate()
        elif change == "extended-window":
            world.participant_limit = None
        else:
            world.repository.clock += timedelta(seconds=1)
            world.physical_changes = {"row_updated_at": world.repository.clock}
        return "must-not-escape"

    assert facade.with_current(selector, read) is None
    assert events.count("read") == 1
    assert events[-1] == "transaction-exit"


def test_callback_exception_unwinds_both_transaction_contexts(monkeypatch):
    _, facade, selector, events = _facade(monkeypatch)

    def read(current):
        raise RuntimeError("read failed")

    with pytest.raises(RuntimeError, match="read failed"):
        facade.with_current(selector, read)
    assert events[-2:] == ["actors-exit", "transaction-exit"]
