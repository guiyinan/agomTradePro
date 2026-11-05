"""Public journey calls preserve exact pins and reject scope before composition."""

from dataclasses import replace

import pytest

from apps.simulated_trading.application import rebalance_journey_public as public
from core.exceptions import InvalidInputError


@pytest.fixture(autouse=True)
def isolated_factory(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(public, "_service_factory", None)


def test_unconfigured_journey_is_explicitly_unavailable() -> None:
    with pytest.raises(public.RebalanceJourneyUnavailable):
        public.run_rebalance_journey(public.RebalanceJourneyCommand("list", 11, 22))


@pytest.mark.parametrize("identity", [0, -1, True, "11"])
def test_invalid_scope_never_reaches_the_factory(identity: object) -> None:
    with pytest.raises(public.RebalanceJourneyAccessDenied):
        public.RebalanceJourneyCommand("list", identity, 22)  # type: ignore[arg-type]


@pytest.mark.parametrize("action", ["read", "review", "successor", "reconcile"])
def test_existing_plan_actions_require_exact_revision_pins(action: public.JourneyAction) -> None:
    with pytest.raises(InvalidInputError) as caught:
        public.RebalanceJourneyCommand(action, 11, 22, plan_id="existing")
    assert caught.value.code == "REBALANCE_JOURNEY_VERSION_REQUIRED"


def test_creation_forbids_existing_plan_identity_and_empty_targets() -> None:
    with pytest.raises(InvalidInputError, match="输入") as caught:
        public.RebalanceJourneyCommand("create", 11, 22, request_key="req")
    assert caught.value.code == "REBALANCE_JOURNEY_TARGET_REQUIRED"
    with pytest.raises(InvalidInputError) as caught:
        public.RebalanceJourneyCommand("create", 11, 22, plan_id="old", request_key="req")
    assert caught.value.code == "REBALANCE_JOURNEY_UNEXPECTED_PLAN_PINS"


def test_factory_is_lazy_and_command_preserves_user_intent_and_scope() -> None:
    calls: list[tuple[str, object]] = []

    class Service:
        def execute(self, command: public.RebalanceJourneyCommand) -> dict[str, object]:
            calls.append(("execute", command))
            return {"success": True, "plan": {"must_not_execute": True}}

    def factory(using: str) -> public.RebalanceJourneyService:
        calls.append(("factory", using))
        return Service()

    public.configure_rebalance_journey_service(factory)
    assert not calls
    command = public.RebalanceJourneyCommand(
        "create", 11, 22, request_key="req", target_weights="000001.SZ 0.10\n"
    )
    result = public.run_rebalance_journey(command, using="isolated")
    assert calls == [("factory", "isolated"), ("execute", command)]
    assert command.target_weights == "000001.SZ 0.10\n"
    assert result == {"success": True, "plan": {"must_not_execute": True}}


def test_review_is_exact_and_cannot_smuggle_new_targets() -> None:
    command = public.RebalanceJourneyCommand("review", 11, 22, "plan", 2, "a" * 64, "review-req")
    with pytest.raises(InvalidInputError) as caught:
        replace(command, target_weights="000001.SZ 0.50")
    assert caught.value.code == "REBALANCE_JOURNEY_UNEXPECTED_TARGET"
    with pytest.raises(InvalidInputError) as caught:
        replace(command, revision_hash="A" * 64)
    assert caught.value.code == "REBALANCE_JOURNEY_HASH_REQUIRED"


def test_tampered_frozen_command_is_rechecked_before_composition() -> None:
    command = public.RebalanceJourneyCommand("list", 11, 22)
    object.__setattr__(command, "account_id", True)
    with pytest.raises(public.RebalanceJourneyAccessDenied):
        public.run_rebalance_journey(command)


def test_real_production_journey_factory_constructs_lazily_without_database_or_source_reads() -> (
    None
):
    from apps.simulated_trading.application.rebalance_journey_service import (
        RebalanceJourneyApplication,
    )
    from apps.simulated_trading.transition_plan_journey_composition import (
        build_rebalance_journey_service,
    )

    service = build_rebalance_journey_service(using="default")
    assert isinstance(service, RebalanceJourneyApplication)
