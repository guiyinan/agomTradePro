"""Terminal chat router response and answer-chain regression tests."""

from datetime import date
from unittest.mock import patch

from apps.policy.domain.entities import PolicyLevel
from apps.regime.application.current_regime import CurrentRegimeResult
from apps.terminal.application.chat_router import (
    TerminalChatRouterService,
    TerminalIntentDecision,
)


def _regime_result() -> CurrentRegimeResult:
    return CurrentRegimeResult(
        dominant_regime="Recovery",
        confidence=0.75,
        observed_at=date(2026, 7, 27),
        data_source="data-center",
        warnings=[],
    )


def test_regime_response_uses_the_declared_data_source() -> None:
    service = TerminalChatRouterService()
    decision = TerminalIntentDecision(intent="market_regime", confidence=0.95)
    repository = type(
        "_PolicyRepository",
        (),
        {"get_current_policy_level": lambda self: PolicyLevel.P1},
    )()

    with (
        patch(
            "apps.terminal.application.chat_router.resolve_current_regime",
            return_value=_regime_result(),
        ),
        patch(
            "apps.terminal.application.chat_router.get_current_policy_repository",
            return_value=repository,
        ),
    ):
        response = service._build_regime_response(
            session_id="session-1",
            decision=decision,
            answer_chain_enabled=True,
            user_is_admin=False,
        )

    assert "- **Source**: `data-center`" in response["reply"]
    answer_chain = response["metadata"]["answer_chain"]
    assert answer_chain["visibility"] == "masked"
    assert all("technical_details" not in step for step in answer_chain["steps"])


def test_admin_regime_chain_contains_typed_technical_details() -> None:
    service = TerminalChatRouterService()

    chain = service._build_regime_chain(
        TerminalIntentDecision(intent="market_regime", confidence=0.95),
        _regime_result(),
        PolicyLevel.P1,
        True,
    )

    details = chain["steps"][1]["technical_details"]
    assert "CurrentRegimeResult.data_source=data-center" in details
    assert "PolicyLevel.value=P1" in details
