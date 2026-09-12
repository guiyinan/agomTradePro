from __future__ import annotations

import base64
import hashlib
import json
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta

import pytest

from apps.account.application.account_owner_assignment_evidence import (
    AccountOwnerAssignmentConflict,
    AccountOwnerAssignmentCorruption,
    AccountOwnerAssignmentUnavailable,
)
from apps.account.application.owner_policy_authorization_source import (
    OwnerPolicyAuthorizationSource,
)
from apps.account.application.single_owner_policy_publication import (
    PublishSingleOwnerAuthorityPolicyV1,
    PublishSingleOwnerAuthorityPolicyV1Command,
)
from apps.account.application.single_owner_policy_publication_settings import (
    SINGLE_OWNER_POLICY_PUBLICATION_SETTINGS_SCHEMA_VERSION,
    SingleOwnerPolicyPublicationSettings,
)
from apps.account.domain.canonical_account_creation import CanonicalAccountCreationRequester
from apps.account.domain.single_owner_authority_policy_v1 import (
    SingleOwnerAuthorityPolicyV1,
)

NOW = datetime(2026, 9, 11, 12, tzinfo=UTC)
TTL = 300


def _source(
    *,
    username: str = "configured-owner",
    user_id: int = 17,
    recorded_at: datetime = NOW - timedelta(minutes=1),
    answer: str = "yes",
) -> OwnerPolicyAuthorizationSource:
    """Build one valid declaration source for the publisher tests."""

    document = {
        "owner_account": {
            "binding_basis": "explicit_user_designation",
            "role": "project_owner_and_human_approver",
            "user_id": user_id,
            "username": username,
        },
        "recorded_at": recorded_at.astimezone(UTC).isoformat().replace("+00:00", "Z"),
        "schema": "sprint-owner-account-authorization.v1",
        "source": {
            "account_binding_answer": answer,
            "kind": "interactive_user_declaration",
        },
    }
    raw = json.dumps(document, ensure_ascii=False, separators=(",", ":"), sort_keys=True).encode(
        "utf-8"
    )
    return OwnerPolicyAuthorizationSource(
        source_id="owner-policy-declaration",
        source_version="v1",
        content_hash=hashlib.sha256(raw).hexdigest(),
        document_base64=base64.b64encode(raw).decode("ascii"),
    )


def _settings(
    source: OwnerPolicyAuthorizationSource,
    **changes: object,
) -> SingleOwnerPolicyPublicationSettings:
    """Build one complete settings snapshot bound to the supplied source."""

    values: dict[str, object] = {
        "schema_version": SINGLE_OWNER_POLICY_PUBLICATION_SETTINGS_SCHEMA_VERSION,
        "owner_username": source.owner_username,
        "tenant_id": "tenant-a",
        "owner_id": "owner-a",
        "authorization_source_id": source.source_id,
        "authorization_source_version": source.source_version,
        "authorization_content_hash": source.content_hash,
        "ttl_seconds": TTL,
    }
    values.update(changes)
    return SingleOwnerPolicyPublicationSettings(**values)  # type: ignore[arg-type]


def _requester(
    *, user_id: int = 17, actor_id: str | None = None
) -> CanonicalAccountCreationRequester:
    """Build the server-owned requester passed after real authentication."""

    return CanonicalAccountCreationRequester(
        actor_id=actor_id or f"django-user:{user_id}",
        user_id=user_id,
    )


def _command(**changes: object) -> PublishSingleOwnerAuthorityPolicyV1Command:
    """Build the server-resolved four-field publication command."""

    values: dict[str, object] = {
        "policy_id": "policy-account-a",
        "policy_version": "v1",
        "account_namespace": "account",
        "account_id": "account-a",
    }
    values.update(changes)
    return PublishSingleOwnerAuthorityPolicyV1Command(**values)  # type: ignore[arg-type]


def _policy(
    source: OwnerPolicyAuthorizationSource,
    settings: SingleOwnerPolicyPublicationSettings,
    *,
    observed_at: datetime = NOW,
    policy_id: str = "policy-account-a",
    policy_version: str = "v1",
    valid_until: datetime | None = None,
    **changes: object,
) -> SingleOwnerAuthorityPolicyV1:
    """Build one fully sealed active policy for replay and collision tests."""

    values: dict[str, object] = {
        "policy_id": policy_id,
        "policy_version": policy_version,
        "tenant_id": settings.tenant_id,
        "owner_id": settings.owner_id,
        "account_namespace": "account",
        "account_id": "account-a",
        "owner_user_id": source.declared_user_id,
        "authorization_content_hash": source.content_hash,
        "observed_at": observed_at,
        "valid_from": observed_at,
        "valid_until": valid_until or observed_at + settings.as_timedelta(),
    }
    values.update(changes)
    return SingleOwnerAuthorityPolicyV1(**values)  # type: ignore[arg-type]


class _Inputs:
    """Return complete settings/source snapshots in a deterministic sequence."""

    def __init__(self, *snapshots: object) -> None:
        self.snapshots = list(snapshots)
        self.calls = 0

    def read_current(self) -> object:
        """Return the next configured complete snapshot."""

        index = min(self.calls, len(self.snapshots) - 1)
        self.calls += 1
        return self.snapshots[index]


class _Repository:
    """Observe the publisher UOW and return configured current policy heads."""

    def __init__(
        self,
        *,
        now_values: tuple[object, ...] = (NOW,),
        current: object = (),
        head: object = None,
        append_result: object = None,
    ) -> None:
        self.now_values = list(now_values)
        self.current = current
        self.head = head
        self.append_result = append_result
        self.events: list[object] = []
        self.appended: list[object] = []

    @contextmanager
    def atomic(self) -> Iterator[None]:
        """Provide the private UOW expected by the Application protocol."""

        self.events.append("atomic.enter")
        try:
            yield
        finally:
            self.events.append("atomic.exit")

    def lock_scope(self, *, account_namespace: str, account_id: str) -> None:
        """Record the scope lock and reject no valid test selector."""

        self.events.append(("lock_scope", account_namespace, account_id))

    def now(self) -> object:
        """Return the next injected server clock value."""

        self.events.append("now")
        return self.now_values.pop(0) if len(self.now_values) > 1 else self.now_values[0]

    def get_current_for_scope(
        self, *, account_namespace: str, account_id: str, as_of: datetime
    ) -> object:
        """Return all current heads without an owner filter."""

        self.events.append(("current", account_namespace, account_id, as_of))
        return self.current

    def get_head(self, *, policy_id: str, as_of: datetime) -> object:
        """Return the configured immutable policy head."""

        self.events.append(("head", policy_id, as_of))
        return self.head

    def append(
        self,
        *,
        policy: SingleOwnerAuthorityPolicyV1,
        expected_previous_content_hash: str | None,
    ) -> object:
        """Capture one root append with its explicit predecessor selector."""

        self.events.append(("append", expected_previous_content_hash))
        self.appended.append(policy)
        return policy if self.append_result is None else self.append_result


def _publisher(
    source: OwnerPolicyAuthorizationSource,
    settings: SingleOwnerPolicyPublicationSettings,
    repository: _Repository,
    *,
    snapshots: tuple[object, ...] | None = None,
) -> tuple[PublishSingleOwnerAuthorityPolicyV1, _Inputs]:
    """Build a publisher with a complete source snapshot reader."""

    inputs = _Inputs(*(snapshots or ((settings, source), (settings, source))))
    return (
        PublishSingleOwnerAuthorityPolicyV1(
            current_inputs=inputs,
            repository=repository,
        ),
        inputs,
    )


def test_first_root_uses_server_scope_and_requester_without_client_owner_fields() -> None:
    source = _source()
    settings = _settings(source)
    repository = _Repository()
    publisher, inputs = _publisher(source, settings, repository)

    result = publisher.execute(_command(), _requester())

    assert type(result) is SingleOwnerAuthorityPolicyV1
    assert result.policy_id == "policy-account-a"
    assert result.policy_version == "v1"
    assert result.account_namespace == "account"
    assert result.account_id == "account-a"
    assert result.tenant_id == "tenant-a"
    assert result.owner_id == "owner-a"
    assert result.owner_user_id == 17
    assert result.authorization_content_hash == source.content_hash
    assert result.observed_at == NOW
    assert result.valid_from == NOW
    assert result.valid_until == NOW + timedelta(seconds=TTL)
    assert result.identity_hash and result.content_hash
    assert inputs.calls == 4
    assert repository.events == [
        "atomic.enter",
        ("lock_scope", "account", "account-a"),
        "now",
        ("current", "account", "account-a", NOW),
        ("head", "policy-account-a", NOW),
        "now",
        ("append", None),
        "now",
        "atomic.exit",
    ]


def test_scope_lock_precedes_collision_read_and_no_owner_filter_is_used() -> None:
    source = _source()
    settings = _settings(source)
    repository = _Repository()
    publisher, _ = _publisher(source, settings, repository)

    publisher.execute(_command(), _requester())

    lock_index = repository.events.index(("lock_scope", "account", "account-a"))
    current_index = next(
        index
        for index, event in enumerate(repository.events)
        if isinstance(event, tuple) and event[0] == "current"
    )
    assert lock_index < current_index
    assert all(
        not (isinstance(event, tuple) and event and event[0] == "current" and len(event) > 4)
        for event in repository.events
    )


def test_missing_inputs_fail_closed_before_opening_repository_uow() -> None:
    source = _source()
    settings = _settings(source)
    repository = _Repository()
    publisher, inputs = _publisher(source, settings, repository, snapshots=(None,))

    with pytest.raises(AccountOwnerAssignmentUnavailable, match="settings and source"):
        publisher.execute(_command(), _requester())

    assert inputs.calls == 1
    assert repository.events == []


def test_source_declared_user_id_must_match_authenticated_requester() -> None:
    source = _source(user_id=18)
    settings = _settings(source)
    repository = _Repository()
    publisher, _ = _publisher(source, settings, repository)

    with pytest.raises(AccountOwnerAssignmentConflict, match="declared user"):
        publisher.execute(_command(), _requester(user_id=17))

    assert repository.appended == []


@pytest.mark.parametrize(
    "changed",
    [
        {"authorization_source_id": "other-source"},
        {"authorization_source_version": "other-version"},
        {"authorization_content_hash": "b" * 64},
        {"owner_username": "other-owner"},
    ],
)
def test_source_and_settings_selectors_must_match_exactly(changed: dict[str, object]) -> None:
    source = _source()
    settings = _settings(source, **changed)
    repository = _Repository()
    publisher, _ = _publisher(source, settings, repository)

    with pytest.raises(AccountOwnerAssignmentCorruption, match="source.*settings"):
        publisher.execute(_command(), _requester())

    assert repository.appended == []


def test_future_source_declaration_is_corruption() -> None:
    source = _source(recorded_at=NOW + timedelta(seconds=1))
    settings = _settings(source)
    repository = _Repository()
    publisher, _ = _publisher(source, settings, repository)

    with pytest.raises(AccountOwnerAssignmentCorruption, match="future"):
        publisher.execute(_command(), _requester())

    assert repository.appended == []


def test_settings_and_source_change_after_scope_lock_is_conflict() -> None:
    first_source = _source()
    first_settings = _settings(first_source)
    second_source = _source(answer="changed declaration")
    second_settings = _settings(second_source)
    repository = _Repository()
    publisher, inputs = _publisher(
        first_source,
        first_settings,
        repository,
        snapshots=((first_settings, first_source), (second_settings, second_source)),
    )

    with pytest.raises(AccountOwnerAssignmentConflict, match="settings/source snapshot"):
        publisher.execute(_command(), _requester())

    assert inputs.calls == 2
    assert ("lock_scope", "account", "account-a") in repository.events
    assert "current" not in repository.events
    assert repository.appended == []


def test_settings_and_source_change_during_head_read_is_rejected_before_append() -> None:
    first_source = _source()
    first_settings = _settings(first_source)
    changed_source = _source(answer="changed while reading the durable head")
    changed_settings = _settings(changed_source)
    repository = _Repository()
    publisher, inputs = _publisher(
        first_source,
        first_settings,
        repository,
        snapshots=(
            (first_settings, first_source),
            (first_settings, first_source),
            (changed_settings, changed_source),
        ),
    )

    with pytest.raises(AccountOwnerAssignmentConflict, match="settings/source snapshot"):
        publisher.execute(_command(), _requester())

    assert inputs.calls == 3
    assert repository.appended == []


def test_replay_is_rejected_if_fresh_clock_crosses_existing_policy_expiry() -> None:
    source = _source()
    settings = _settings(source, ttl_seconds=1)
    existing = _policy(source, settings, valid_until=NOW + timedelta(seconds=1))
    repository = _Repository(
        now_values=(NOW, NOW + timedelta(seconds=2)),
        current=(existing,),
    )
    publisher, inputs = _publisher(source, settings, repository)

    with pytest.raises(AccountOwnerAssignmentConflict, match="replay|current"):
        publisher.execute(_command(), _requester())

    assert inputs.calls == 3
    assert repository.appended == []


def test_multiple_current_heads_are_a_scope_conflict_before_owner_selection() -> None:
    source = _source()
    settings = _settings(source)
    other = _policy(
        source,
        settings,
        policy_id="policy-account-a-other",
        policy_version="v1",
        owner_user_id=18,
        owner_id="owner-b",
    )
    current = _policy(source, settings)
    repository = _Repository(current=(current, other))
    publisher, _ = _publisher(source, settings, repository)

    with pytest.raises(AccountOwnerAssignmentConflict, match="multiple current"):
        publisher.execute(_command(), _requester())

    assert repository.appended == []
    current_events = [
        event for event in repository.events if isinstance(event, tuple) and event[0] == "current"
    ]
    assert current_events and len(current_events[0]) == 4


def test_different_current_policy_for_same_scope_is_conflict() -> None:
    source = _source()
    settings = _settings(source)
    current = _policy(source, settings, policy_id="other-policy")
    repository = _Repository(current=(current,))
    publisher, _ = _publisher(source, settings, repository)

    with pytest.raises(AccountOwnerAssignmentConflict, match="another current .*policy"):
        publisher.execute(_command(), _requester())

    assert repository.appended == []


def test_exact_current_head_replays_without_new_timestamp_or_append() -> None:
    source = _source()
    settings = _settings(source)
    existing = _policy(source, settings, observed_at=NOW - timedelta(minutes=2))
    repository = _Repository(current=(existing,))
    publisher, _ = _publisher(source, settings, repository)

    result = publisher.execute(_command(), _requester())

    assert result == existing
    assert result.observed_at == existing.observed_at
    assert result.valid_until == existing.valid_until
    assert repository.appended == []
    assert "head" not in repository.events
    assert "now" in repository.events


def test_current_replay_requires_the_configured_ttl_duration() -> None:
    source = _source()
    settings = _settings(source, ttl_seconds=TTL)
    existing = _policy(source, settings, valid_until=NOW + timedelta(seconds=TTL + 1))
    repository = _Repository(current=(existing,))
    publisher, _ = _publisher(source, settings, repository)

    with pytest.raises(AccountOwnerAssignmentConflict, match="TTL"):
        publisher.execute(_command(), _requester())

    assert repository.appended == []


@pytest.mark.parametrize(
    "changed",
    [
        {"tenant_id": "tenant-b"},
        {"owner_id": "owner-b"},
        {"owner_user_id": 18},
        {"authorization_content_hash": "b" * 64},
    ],
)
def test_current_replay_requires_all_immutable_settings_to_match(
    changed: dict[str, object],
) -> None:
    source = _source()
    settings = _settings(source)
    existing = _policy(source, settings, **changed)
    repository = _Repository(current=(existing,))
    publisher, _ = _publisher(source, settings, repository)

    with pytest.raises(AccountOwnerAssignmentConflict, match="replay"):
        publisher.execute(_command(), _requester())

    assert repository.appended == []


@pytest.mark.parametrize(
    "head",
    [
        _policy(
            _source(),
            _settings(_source()),
            observed_at=NOW - timedelta(hours=2),
            valid_until=NOW - timedelta(hours=1),
        ),
        _policy(_source(), _settings(_source()), status="revoked"),
    ],
)
def test_expired_or_revoked_same_policy_id_cannot_be_recreated(
    head: SingleOwnerAuthorityPolicyV1,
) -> None:
    source = _source()
    settings = _settings(source)
    repository = _Repository(head=head)
    publisher, _ = _publisher(source, settings, repository)

    with pytest.raises(AccountOwnerAssignmentConflict, match="durable head"):
        publisher.execute(_command(), _requester())

    assert repository.appended == []


def test_existing_head_same_id_different_version_is_still_a_conflict() -> None:
    source = _source()
    settings = _settings(source)
    head = _policy(
        source,
        settings,
        policy_version="old-v1",
        observed_at=NOW - timedelta(hours=1),
    )
    repository = _Repository(head=head)
    publisher, _ = _publisher(source, settings, repository)

    with pytest.raises(AccountOwnerAssignmentConflict, match="durable head"):
        publisher.execute(_command(policy_version="new-v2"), _requester())

    assert repository.appended == []


def test_malformed_current_policy_seal_is_corruption() -> None:
    source = _source()
    settings = _settings(source)
    existing = _policy(source, settings)
    object.__setattr__(existing, "content_hash", "b" * 64)
    repository = _Repository(current=(existing,))
    publisher, _ = _publisher(source, settings, repository)

    with pytest.raises(AccountOwnerAssignmentCorruption, match="policy.*seal"):
        publisher.execute(_command(), _requester())

    assert repository.appended == []


def test_append_result_type_must_be_the_exact_policy_type() -> None:
    source = _source()
    settings = _settings(source)
    repository = _Repository(append_result=object())
    publisher, _ = _publisher(source, settings, repository)

    with pytest.raises(AccountOwnerAssignmentCorruption, match="append|policy"):
        publisher.execute(_command(), _requester())


def test_append_result_fields_must_match_the_new_root() -> None:
    source = _source()
    settings = _settings(source)
    wrong = _policy(source, settings, owner_id="other-owner")
    repository = _Repository(append_result=wrong)
    publisher, _ = _publisher(source, settings, repository)

    with pytest.raises(AccountOwnerAssignmentConflict, match="first winner|append"):
        publisher.execute(_command(), _requester())


def test_invalid_repository_clock_fails_closed_without_append() -> None:
    source = _source()
    settings = _settings(source)
    repository = _Repository(now_values=(datetime(2026, 9, 11, 12),))
    publisher, _ = _publisher(source, settings, repository)

    with pytest.raises(AccountOwnerAssignmentCorruption, match="clock"):
        publisher.execute(_command(), _requester())

    assert repository.appended == []


def test_invalid_command_or_requester_is_rejected_before_reader() -> None:
    source = _source()
    settings = _settings(source)
    repository = _Repository()
    publisher, inputs = _publisher(source, settings, repository)

    with pytest.raises(TypeError, match="command"):
        publisher.execute(object(), _requester())  # type: ignore[arg-type]
    with pytest.raises(TypeError, match="requester"):
        publisher.execute(_command(), object())  # type: ignore[arg-type]

    assert inputs.calls == 0
    assert repository.events == []


def test_public_command_has_only_server_resolved_scope_and_identity_selectors() -> None:
    command = _command()

    assert set(command.__slots__) == {
        "policy_id",
        "policy_version",
        "account_namespace",
        "account_id",
    }
    assert not hasattr(command, "owner_user_id")
    assert not hasattr(command, "ttl_seconds")
    assert not hasattr(command, "authorization_content_hash")


@pytest.mark.parametrize(
    "field_name",
    ["policy_id", "policy_version", "account_namespace", "account_id"],
)
def test_command_rejects_noncanonical_selector(field_name: str) -> None:
    values: dict[str, object] = {
        "policy_id": "policy-account-a",
        "policy_version": "v1",
        "account_namespace": "account",
        "account_id": "account-a",
    }
    values[field_name] = True

    with pytest.raises(TypeError):
        PublishSingleOwnerAuthorityPolicyV1Command(**values)  # type: ignore[arg-type]
