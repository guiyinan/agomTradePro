from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from apps.account.application.account_owner_assignment_evidence import (
    AccountOwnerAssignmentConflict,
    AccountOwnerAssignmentCorruption,
)
from apps.account.application.single_owner_actor_authority import (
    SingleOwnerPolicyBinding,
)
from apps.account.application.single_owner_policy_resolution import (
    ResolveCurrentSingleOwnerPolicyBinding,
)
from apps.account.domain.single_owner_authority_policy_v1 import (
    SingleOwnerAuthorityPolicyV1,
)

NOW = datetime(2026, 9, 11, 12, tzinfo=UTC)


def _policy(**changes: object) -> SingleOwnerAuthorityPolicyV1:
    """Build one fully sealed active policy for the resolver tests."""

    values: dict[str, object] = {
        "policy_id": "policy-account-a",
        "policy_version": "v1",
        "tenant_id": "tenant-a",
        "owner_id": "owner-a",
        "account_namespace": "account",
        "account_id": "account-a",
        "owner_user_id": 17,
        "authorization_content_hash": "a" * 64,
        "observed_at": NOW,
        "valid_from": NOW,
        "valid_until": NOW + timedelta(hours=1),
    }
    values.update(changes)
    return SingleOwnerAuthorityPolicyV1(**values)  # type: ignore[arg-type]


class _Reader:
    """Capture the complete scope request and return a configured policy set."""

    def __init__(self, value: object) -> None:
        self.value = value
        self.calls: list[dict[str, object]] = []

    def get_current_for_scope(self, **selector: object) -> object:
        """Return the configured result without filtering by owner user."""

        self.calls.append(selector)
        return self.value


def _resolver(value: object) -> tuple[ResolveCurrentSingleOwnerPolicyBinding, _Reader]:
    """Build a resolver and its observable policy reader."""

    reader = _Reader(value)
    return ResolveCurrentSingleOwnerPolicyBinding(reader), reader


def _resolve(
    resolver: ResolveCurrentSingleOwnerPolicyBinding,
    *,
    as_of: datetime = NOW,
    owner_user_id: int = 17,
) -> SingleOwnerPolicyBinding | None:
    """Resolve the canonical test scope through the public Application method."""

    return resolver.resolve(
        account_namespace="account",
        account_id="account-a",
        owner_user_id=owner_user_id,
        as_of=as_of,
    )


def test_one_current_policy_becomes_an_exact_existing_binding() -> None:
    policy = _policy()
    resolver, reader = _resolver((policy,))

    binding = _resolve(resolver)

    assert type(binding) is SingleOwnerPolicyBinding
    assert binding is not None
    assert binding.policy_id == policy.policy_id
    assert binding.policy_version == policy.policy_version
    assert binding.expected_content_hash == policy.content_hash
    assert binding.tenant_id == policy.tenant_id
    assert binding.owner_id == policy.owner_id
    assert binding.account_namespace == policy.account_namespace
    assert binding.account_id == policy.account_id
    assert reader.calls == [
        {
            "account_namespace": "account",
            "account_id": "account-a",
            "as_of": NOW,
        }
    ]


def test_no_current_policy_returns_none_without_inventing_scope_facts() -> None:
    resolver, reader = _resolver(())

    assert _resolve(resolver) is None
    assert len(reader.calls) == 1


def test_all_current_heads_are_checked_before_scope_resolution() -> None:
    other_owner = _policy(
        policy_id="policy-account-a-other-owner",
        owner_id="owner-b",
        owner_user_id=18,
        authorization_content_hash="b" * 64,
    )
    resolver, reader = _resolver((_policy(), other_owner))

    with pytest.raises(AccountOwnerAssignmentConflict, match="multiple"):
        _resolve(resolver)

    assert "owner_user_id" not in reader.calls[0]


@pytest.mark.parametrize(
    ("field_name", "value"),
    [
        ("account_namespace", "other"),
        ("account_id", "account-b"),
        ("owner_user_id", 18),
    ],
)
def test_returned_policy_must_match_the_requested_scope_and_owner(
    field_name: str,
    value: object,
) -> None:
    resolver, _ = _resolver((_policy(**{field_name: value}),))

    with pytest.raises(AccountOwnerAssignmentCorruption, match="scope or owner"):
        _resolve(resolver)


@pytest.mark.parametrize(
    "policy",
    [
        _policy(
            observed_at=NOW - timedelta(hours=2),
            valid_from=NOW - timedelta(hours=2),
            valid_until=NOW,
        ),
        _policy(status="revoked"),
        _policy(
            observed_at=NOW + timedelta(seconds=1),
            valid_from=NOW + timedelta(seconds=1),
            valid_until=NOW + timedelta(hours=1),
        ),
    ],
)
def test_reader_must_not_return_expired_revoked_or_future_policy(
    policy: SingleOwnerAuthorityPolicyV1,
) -> None:
    resolver, _ = _resolver((policy,))

    with pytest.raises(AccountOwnerAssignmentCorruption, match="expired, revoked, or future"):
        _resolve(resolver)


def test_bad_policy_seal_is_corruption_and_missing_seal_is_not_computed() -> None:
    bad_hash = _policy()
    object.__setattr__(bad_hash, "content_hash", "b" * 64)
    resolver, _ = _resolver((bad_hash,))

    with pytest.raises(AccountOwnerAssignmentCorruption, match="bad seal"):
        _resolve(resolver)

    missing_hash = _policy()
    object.__setattr__(missing_hash, "content_hash", "")
    resolver, _ = _resolver((missing_hash,))
    with pytest.raises(AccountOwnerAssignmentCorruption, match="exact digest"):
        _resolve(resolver)


@pytest.mark.parametrize("value", [{"policy_id": "policy-account-a"}, [_policy()]])
def test_reader_must_return_an_exact_policy_tuple(value: object) -> None:
    resolver, _ = _resolver(value)

    with pytest.raises(AccountOwnerAssignmentCorruption, match="substituted collection"):
        _resolve(resolver)


def test_reader_conflict_is_preserved_instead_of_being_masked() -> None:
    class FailingReader:
        """Raise the stable conflict used by a durable reader."""

        def get_current_for_scope(self, **_: object) -> tuple[SingleOwnerAuthorityPolicyV1, ...]:
            raise AccountOwnerAssignmentConflict("scope collision")

    resolver = ResolveCurrentSingleOwnerPolicyBinding(FailingReader())

    with pytest.raises(AccountOwnerAssignmentConflict, match="scope collision"):
        _resolve(resolver)


@pytest.mark.parametrize("owner_user_id", [True, 0, -1])
def test_owner_user_selector_rejects_bool_and_non_positive_ids(
    owner_user_id: object,
) -> None:
    resolver, reader = _resolver((_policy(),))

    with pytest.raises(AccountOwnerAssignmentCorruption, match="owner_user_id"):
        _resolve(resolver, owner_user_id=owner_user_id)  # type: ignore[arg-type]
    assert not reader.calls


def test_naive_cutoff_and_invalid_scope_are_rejected_before_reader_call() -> None:
    resolver, reader = _resolver((_policy(),))

    with pytest.raises(AccountOwnerAssignmentCorruption, match="timezone-aware"):
        _resolve(resolver, as_of=NOW.replace(tzinfo=None))
    with pytest.raises(AccountOwnerAssignmentCorruption, match="canonical token"):
        resolver.resolve(
            account_namespace=" ",
            account_id="account-a",
            owner_user_id=17,
            as_of=NOW,
        )
    assert not reader.calls


def test_execute_is_the_same_typed_resolution_seam() -> None:
    policy = _policy()
    resolver, _ = _resolver((policy,))

    binding = resolver.execute(
        account_namespace="account",
        account_id="account-a",
        owner_user_id=17,
        as_of=NOW,
    )

    assert binding == _resolve(_resolver((policy,))[0])
