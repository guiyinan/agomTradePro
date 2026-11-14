"""Confirmation refreshes source observations without renewing owner authority."""

from dataclasses import replace
from types import SimpleNamespace

import pytest

from apps.account.domain.simulated_corporate_action_write_capabilities import (
    SimulatedCorporateActionWriteCapability as Capability,
)
from apps.simulated_trading import corporate_action_owner_confirmation_window as confirmation
from core.exceptions import AuthorizationError, BusinessLogicError
from tests.unit.simulated_trading.test_corporate_action_owner_intent_codec import _intent


@pytest.fixture
def context(monkeypatch):
    intent = _intent()
    account = SimpleNamespace(
        owner_user_id=intent.owner_user_id,
        grant=SimpleNamespace(selector=intent.selector),
        asset_codes=(intent.source_reference.asset_code,),
        security_id=intent.source_reference.security_id,
    )
    calls = []
    monkeypatch.setattr(confirmation, "has_retained_owner_posting", lambda value: False)
    monkeypatch.setattr(
        confirmation, "read_owner_corporate_action_account", lambda *a, **k: account
    )
    monkeypatch.setattr(confirmation.timezone, "now", lambda: intent.prepared_at)
    monkeypatch.setattr(
        confirmation,
        "build_current_reference_identity_reader",
        lambda **k: SimpleNamespace(
            resolve_current_reference_identity=lambda **k: SimpleNamespace(
                security_id=account.security_id,
            )
        ),
    )
    monkeypatch.setattr(
        confirmation,
        "build_official_szse_distribution_refresher",
        lambda **k: SimpleNamespace(refresh=lambda **kwargs: calls.append(kwargs)),
    )
    return intent, account, calls


def test_new_posting_refreshes_only_exact_server_bound_source_after_current_consent(context):
    intent, _, calls = context
    original = (intent.selector, intent.prepared_at, intent.valid_until, intent.requests)
    confirmation.refresh_new_owner_posting_window(
        object(), intent=intent, capability=Capability.CASH_STAGE_WRITE, environment="test"
    )
    assert len(calls) == 1
    assert calls[0]["asset_identities"][0].asset_code == intent.source_reference.asset_code
    assert calls[0]["request_scope"].owner_user_id == intent.owner_user_id
    assert (intent.selector, intent.prepared_at, intent.valid_until, intent.requests) == original


def test_any_retained_original_defers_replay_and_corruption_checks_to_financial_uow(
    context, monkeypatch
):
    intent, _, calls = context
    monkeypatch.setattr(confirmation, "has_retained_owner_posting", lambda value: True)
    monkeypatch.setattr(
        confirmation,
        "read_owner_corporate_action_account",
        lambda *a, **k: pytest.fail("exact replay must not refresh or require current source"),
    )
    confirmation.refresh_new_owner_posting_window(
        object(), intent=intent, capability=Capability.CASH_STAGE_WRITE, environment="test"
    )
    assert calls == []


@pytest.mark.parametrize("denial", (AuthorizationError, BusinessLogicError))
def test_current_owner_role_or_consent_denial_precedes_source_capture(context, monkeypatch, denial):
    intent, _, calls = context

    def deny(*args, **kwargs):
        raise denial()

    monkeypatch.setattr(confirmation, "read_owner_corporate_action_account", deny)
    with pytest.raises(denial):
        confirmation.refresh_new_owner_posting_window(
            object(), intent=intent, capability=Capability.CASH_STAGE_WRITE, environment="test"
        )
    assert calls == []


def test_changed_current_consent_cannot_trigger_capture_from_an_old_intent(context):
    intent, account, calls = context
    account.grant = None
    with pytest.raises(BusinessLogicError):
        confirmation.refresh_new_owner_posting_window(
            object(), intent=intent, capability=Capability.CASH_STAGE_WRITE, environment="test"
        )
    assert calls == []


@pytest.mark.parametrize("action", ("tax_assess", "tax_recognize", "tax_collect"))
def test_new_tax_operation_captures_current_window_without_rewriting_assessment(context, action):
    _, account, calls = context
    intent = replace(_intent(tax=True, simulated=True), action=action)
    account.owner_user_id = intent.owner_user_id
    account.grant = SimpleNamespace(selector=intent.selector)
    account.asset_codes = (intent.source_reference.asset_code,)
    account.security_id = intent.source_reference.security_id
    original = (intent.assessment, intent.selector, intent.prepared_at, intent.valid_until)
    confirmation.refresh_new_owner_posting_window(
        object(), intent=intent, capability=Capability.TAX_ASSESS, environment="test"
    )
    assert len(calls) == 1
    assert (intent.assessment, intent.selector, intent.prepared_at, intent.valid_until) == original


@pytest.mark.parametrize("action", ("tax_assess", "tax_recognize", "tax_collect"))
def test_retained_tax_operation_skips_current_capture_and_defers_exact_replay(
    context, monkeypatch, action
):
    _, _, calls = context
    intent = replace(_intent(tax=True, simulated=True), action=action)
    monkeypatch.setattr(confirmation, "has_retained_owner_posting", lambda value: True)
    monkeypatch.setattr(
        confirmation,
        "read_owner_corporate_action_account",
        lambda *a, **k: pytest.fail("retained operation must reach exact financial replay checks"),
    )
    confirmation.refresh_new_owner_posting_window(
        object(), intent=intent, capability=Capability.TAX_ASSESS, environment="test"
    )
    assert calls == []


@pytest.mark.parametrize("action", ("tax_assess", "tax_recognize", "tax_collect"))
def test_tax_replay_presence_uses_owner_scoped_operation_identity(monkeypatch, action):
    intent = replace(_intent(tax=True, simulated=True), action=action)
    queries = []

    class PresenceQuery:
        def using(self, alias):
            assert alias == confirmation.DEFAULT_DB_ALIAS
            return self

        def filter(self, **scope):
            queries.append(scope)
            return self

        def exists(self):
            return True

    expected_model = (
        "CorporateActionTaxAssessmentHeaderModel"
        if action == "tax_assess"
        else "CorporateActionTaxLiabilityOperationModel"
    )
    other_model = (
        "CorporateActionTaxLiabilityOperationModel"
        if action == "tax_assess"
        else "CorporateActionTaxAssessmentHeaderModel"
    )
    monkeypatch.setattr(
        confirmation, expected_model, SimpleNamespace(_base_manager=PresenceQuery())
    )
    monkeypatch.setattr(confirmation, other_model, object())
    assert confirmation.has_retained_owner_posting(intent) is True
    identity = (
        {"idempotency_key": intent.assessment.calculation.idempotency_key}
        if action == "tax_assess"
        else {"operation_id": intent.operation_id}
    )
    assert queries == [
        {
            "account_id": intent.account_id,
            "owner_user_id": intent.owner_user_id,
            **identity,
        }
    ]
