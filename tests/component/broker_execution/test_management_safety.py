"""Safety contracts for broker execution administrative writes."""

from datetime import timedelta
from decimal import Decimal
from typing import cast

import pytest
from django.contrib.auth.models import User
from django.db.models.query import QuerySet
from django.utils import timezone

from apps.broker_execution.application.management_use_cases import (
    ManageAgentBindingUseCase,
    RotateAgentCredentialUseCase,
)
from apps.broker_execution.application.use_case_errors import (
    BrokerExecutionConflictError,
    BrokerExecutionValidationError,
)
from apps.broker_execution.infrastructure.models import (
    BrokerAccountBindingModel,
    BrokerAgentCredentialModel,
    BrokerAgentModel,
)
from apps.broker_execution.infrastructure.repositories import (
    DjangoBrokerExecutionRepository,
)
from apps.simulated_trading.application.query_services import AccountBindingIdentity


def _admin(username: str) -> User:
    user = User.objects.create_superuser(
        username=username,
        password="test123",
        email=f"{username}@example.com",
    )
    user.account_profile.rbac_role = "admin"
    user.account_profile.save(update_fields=["rbac_role", "updated_at"])
    return user


@pytest.mark.django_db
def test_binding_use_case_rejects_string_boolean() -> None:
    """The text ``false`` must not activate a live binding."""

    actor = _admin("binding-string-bool-admin")
    with pytest.raises(BrokerExecutionValidationError, match="is_active must be boolean"):
        ManageAgentBindingUseCase(
            repository=object(),
            account_binding_identity_provider=lambda **_kwargs: None,
        ).execute(
            actor=actor,
            payload={
                "user_id": actor.id,
                "account_id": 1,
                "agent_id": "agent-1",
                "is_active": "false",
                "reason": "invalid boolean",
            },
            preview_only=True,
        )


@pytest.mark.parametrize(
    ("identity_overrides", "expected_error"),
    [
        ({"owner_user_id": 0}, "The account does not belong to the selected user"),
        ({"owner_user_id": True}, "The account does not belong to the selected user"),
        ({"owner_user_id": 999999}, "The account does not belong to the selected user"),
        ({"account_id": 0}, "The account does not belong to the selected user"),
        ({"account_id": True}, "The account does not belong to the selected user"),
        ({"account_id": 999999}, "The account does not belong to the selected user"),
        ({"account_type": "unknown"}, "Only an active unified real account can be bound to QMT"),
        ({"account_type": None}, "The account binding identity is invalid"),
        ({"account_type": "simulated"}, "Only an active unified real account can be bound to QMT"),
        ({"is_active": 1}, "The account binding identity is invalid"),
        ({"is_active": False}, "Only an active unified real account can be bound to QMT"),
    ],
)
@pytest.mark.django_db
def test_binding_requires_exact_active_real_account_identity(
    identity_overrides: dict[str, object],
    expected_error: str,
) -> None:
    """A privileged actor cannot replace exact owner and account eligibility evidence."""

    actor = _admin("binding-identity-admin")
    owner = User.objects.create_user(username="binding-identity-owner")
    account_id = 205
    identity: dict[str, object] = {
        "owner_user_id": owner.id,
        "account_id": account_id,
        "account_type": "real",
        "is_active": True,
    }
    identity.update(identity_overrides)

    with pytest.raises(BrokerExecutionValidationError, match=expected_error):
        ManageAgentBindingUseCase(
            repository=object(),
            account_binding_identity_provider=lambda **_kwargs: cast(
                AccountBindingIdentity,
                identity,
            ),
        ).execute(
            actor=actor,
            payload={
                "user_id": owner.id,
                "account_id": account_id,
                "agent_id": "binding-identity-agent",
                "broker_account_ref": "broker-205",
                "is_active": True,
                "reason": "verify exact owner identity",
            },
            preview_only=True,
        )


@pytest.mark.django_db
def test_credential_rotation_rechecks_account_scope_under_lock(monkeypatch) -> None:
    """A binding deactivated before lock acquisition cannot enter a credential."""

    admin = _admin("credential-scope-admin")
    owner = User.objects.create_user(username="credential-scope-owner")
    agent = BrokerAgentModel.objects.create(
        user=owner,
        agent_id="credential-scope-agent",
        display_name="Credential Scope Agent",
    )
    binding = BrokerAccountBindingModel.objects.create(
        user=owner,
        account_id=201,
        agent=agent,
        broker_account_ref="broker-201",
        allowed_symbols=["510300.SH"],
        max_single_order_amount=Decimal("100000"),
        daily_order_amount_limit=Decimal("500000"),
    )
    original_select_for_update = QuerySet.select_for_update
    binding_deactivated = False

    def _deactivate_before_binding_lock(self, *args, **kwargs):
        nonlocal binding_deactivated
        if self.model is BrokerAccountBindingModel and not binding_deactivated:
            BrokerAccountBindingModel.objects.filter(pk=binding.pk).update(is_active=False)
            binding_deactivated = True
        return original_select_for_update(self, *args, **kwargs)

    monkeypatch.setattr(
        QuerySet,
        "select_for_update",
        _deactivate_before_binding_lock,
    )

    with pytest.raises(BrokerExecutionConflictError, match="inactive or unbound"):
        RotateAgentCredentialUseCase().execute(
            actor=admin,
            agent_id=agent.agent_id,
            scopes=["agent.heartbeat.write"],
            account_ids=[binding.account_id],
            expires_at=(timezone.now() + timedelta(days=1)).isoformat(),
            preview_only=False,
            idempotency_key="credential-stale-scope",
        )

    assert binding_deactivated is True
    assert not BrokerAgentCredentialModel.objects.filter(agent=agent).exists()


@pytest.mark.django_db
def test_credential_rotation_rechecks_idempotency_after_lock(monkeypatch) -> None:
    """A concurrent credential winner is replayed without issuing another secret."""

    admin = _admin("credential-replay-admin")
    owner = User.objects.create_user(username="credential-replay-owner")
    agent = BrokerAgentModel.objects.create(
        user=owner,
        agent_id="credential-replay-agent",
        display_name="Credential Replay Agent",
    )
    binding = BrokerAccountBindingModel.objects.create(
        user=owner,
        account_id=203,
        agent=agent,
        broker_account_ref="broker-203",
    )
    repository = DjangoBrokerExecutionRepository()
    replay_calls = 0
    stored = {
        "credential_id": "stored",
        "token": "",
        "shown_once": False,
    }

    def _replay_after_lock(**_kwargs):
        nonlocal replay_calls
        replay_calls += 1
        return None if replay_calls == 1 else stored

    monkeypatch.setattr(repository, "_replay_or_conflict", _replay_after_lock)
    result = repository.rotate_agent_credential(
        actor_id=admin.id,
        agent_id=agent.agent_id,
        scopes=["agent.heartbeat.write"],
        allowed_account_ids=[binding.account_id],
        expires_at=(timezone.now() + timedelta(days=1)).isoformat(),
        idempotency_key="credential-lock-replay",
        request_digest="credential-lock-replay-digest",
    )

    assert result == stored
    assert replay_calls == 2
    assert not BrokerAgentCredentialModel.objects.filter(agent=agent).exists()


@pytest.mark.django_db
def test_execution_settings_reject_string_boolean() -> None:
    """Repository callers cannot turn the string ``false`` into True."""

    admin = _admin("settings-string-bool-admin")
    owner = User.objects.create_user(username="settings-string-bool-owner")
    agent = BrokerAgentModel.objects.create(
        user=owner,
        agent_id="settings-string-bool-agent",
        display_name="Settings Boolean Agent",
    )
    binding = BrokerAccountBindingModel.objects.create(
        user=owner,
        account_id=202,
        agent=agent,
        broker_account_ref="broker-202",
        auto_execution_enabled=False,
    )

    with pytest.raises(BrokerExecutionConflictError, match="must be boolean"):
        DjangoBrokerExecutionRepository().update_account_settings(
            actor_id=admin.id,
            account_id=binding.account_id,
            payload={"auto_execution_enabled": "false", "reason": "invalid"},
            idempotency_key="settings-string-bool",
            request_digest="settings-string-bool-digest",
        )

    binding.refresh_from_db()
    assert binding.auto_execution_enabled is False
