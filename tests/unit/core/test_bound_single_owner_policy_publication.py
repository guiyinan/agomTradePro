"""Bound publication orchestration preserves identity, scope and retry selectors."""

from contextlib import contextmanager
from datetime import UTC, datetime, timedelta

import pytest

from apps.account.domain.single_owner_authority_policy_v1 import SingleOwnerAuthorityPolicyV1
from core.exceptions import ExternalServiceError
from core.integration import bound_single_owner_policy_publication as subject
from tests.unit.account.test_canonical_account_creation_binding_v2 import _binding


def _setup(monkeypatch):
    binding = _binding()
    inputs = (object(), object())
    events = []
    commands = []
    now = datetime.now(UTC)
    result = SingleOwnerAuthorityPolicyV1(
        policy_id="test-policy",
        policy_version="v1",
        tenant_id="tenant",
        owner_id="owner",
        account_namespace=binding.account_namespace_claim,
        account_id=binding.account_id_claim,
        owner_user_id=binding.allocation.requested_by.user_id,
        authorization_content_hash="a" * 64,
        observed_at=now,
        valid_from=now,
        valid_until=now + timedelta(minutes=5),
    )

    @contextmanager
    def authenticate(**kwargs):
        events.append(("authenticate", kwargs))
        yield binding.allocation.requested_by
        events.append(("commit", None))

    def resolve(**kwargs):
        events.append(("binding", kwargs))
        assert kwargs["requester"] == binding.allocation.requested_by
        return binding

    class Publisher:
        def execute(self, command, *, requester):
            commands.append(command)
            assert requester == binding.allocation.requested_by
            events.append(("publish", None))
            return result

    monkeypatch.setattr(subject, "_current_inputs", lambda _: inputs)
    monkeypatch.setattr(subject, "authenticated_policy_publication_transaction", authenticate)
    monkeypatch.setattr(subject, "resolve_policy_publication_binding", resolve)
    monkeypatch.setattr(subject, "build_single_owner_policy_publisher", lambda **_: Publisher())
    command = subject.PublishBoundSingleOwnerPolicyCommand(
        idempotency_key="retry-key",
        binding_id=binding.binding_id,
        binding_version=binding.binding_version,
        binding_content_hash=binding.content_hash,
    )
    options = {
        "request": object(),
        "command": command,
        "environment": "staging",
        "using": "bound-alias",
    }
    return binding, inputs, events, commands, result, options


def test_authentication_wraps_exact_binding_and_stable_server_identity(monkeypatch):
    binding, _, events, commands, result, options = _setup(monkeypatch)
    assert subject.publish_bound_single_owner_policy(**options) is result
    assert [name for name, _ in events] == [
        "authenticate",
        "binding",
        "publish",
        "binding",
        "commit",
    ]
    assert commands[0].account_namespace == binding.account_namespace_claim
    assert commands[0].account_id == binding.account_id_claim
    subject.publish_bound_single_owner_policy(**options)
    assert commands[0] == commands[1]
    assert "retry-key" not in commands[0].policy_id


def test_same_request_key_changed_binding_keeps_policy_id_but_changes_version(monkeypatch):
    _, _, _, commands, _, options = _setup(monkeypatch)
    subject.publish_bound_single_owner_policy(**options)
    old = options["command"]
    options["command"] = subject.PublishBoundSingleOwnerPolicyCommand(
        idempotency_key=old.idempotency_key,
        binding_id="changed-binding",
        binding_version=old.binding_version,
        binding_content_hash=old.binding_content_hash,
    )
    subject.publish_bound_single_owner_policy(**options)
    assert commands[0].policy_id == commands[1].policy_id
    assert commands[0].policy_version != commands[1].policy_version


def test_configuration_change_after_publish_raises_inside_authentication_transaction(monkeypatch):
    _, inputs, events, _, _, options = _setup(monkeypatch)
    reads = iter([inputs, None])
    monkeypatch.setattr(subject, "_current_inputs", lambda _: next(reads))
    with pytest.raises(ExternalServiceError, match="changed before commit"):
        subject.publish_bound_single_owner_policy(**options)
    assert [name for name, _ in events] == ["authenticate", "binding", "publish", "binding"]


def test_missing_configuration_never_authenticates_or_writes(monkeypatch):
    _, _, events, _, _, options = _setup(monkeypatch)
    monkeypatch.setattr(subject, "_current_inputs", lambda _: None)
    with pytest.raises(ExternalServiceError):
        subject.publish_bound_single_owner_policy(**options)
    assert events == []


def test_policy_expiring_before_outer_commit_is_rejected(monkeypatch):
    _, _, events, _, result, options = _setup(monkeypatch)

    class ExpiredClock:
        @staticmethod
        def now(_timezone):
            return result.valid_until

    monkeypatch.setattr(subject, "datetime", ExpiredClock)
    with pytest.raises(ExternalServiceError, match="no longer current"):
        subject.publish_bound_single_owner_policy(**options)
    assert "commit" not in [name for name, _ in events]


@pytest.mark.parametrize("key", ["", "has space", True, "a" * 193])
def test_invalid_idempotency_key_is_rejected(key):
    with pytest.raises(ValueError):
        subject.PublishBoundSingleOwnerPolicyCommand(
            idempotency_key=key,
            binding_id="binding",
            binding_version="v1",
            binding_content_hash="a" * 64,
        )
