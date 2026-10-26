"""Pure Account Application tests for the User/Profile identity boundary."""

from __future__ import annotations

from apps.account.application.owner_profile_identity import (
    AccountOwnerProfileIdentity,
    AccountOwnerProfileIdentityRepository,
    GetAccountOwnerProfileIdentityUseCase,
)


class FakeOwnerProfileRepository(AccountOwnerProfileIdentityRepository):
    """Return an explicit, independent profile key for an authenticated user."""

    def __init__(self, identity: AccountOwnerProfileIdentity | None) -> None:
        """Keep one exact source response for the use-case boundary case."""

        self.identity = identity
        self.calls: list[int] = []

    def get_for_user(self, *, user_id: int) -> AccountOwnerProfileIdentity | None:
        """Return the configured source response for the requested lookup."""

        self.calls.append(user_id)
        return self.identity


def test_profile_lookup_preserves_distinct_authenticated_user_and_profile_ids() -> None:
    """Strategy ownership receives the real profile ID, never a coincidental User ID."""

    use_case = GetAccountOwnerProfileIdentityUseCase(
        FakeOwnerProfileRepository(AccountOwnerProfileIdentity(user_id=1007, profile_id=42))
    )

    result = use_case.execute(user_id=1007)

    assert result is not None
    assert result.user_id == 1007
    assert result.profile_id == 42
    assert result.profile_id != result.user_id


def test_missing_profile_does_not_fallback_to_user_primary_key() -> None:
    """Missing identity remains missing rather than querying Strategy with User.pk."""

    repository = FakeOwnerProfileRepository(None)
    use_case = GetAccountOwnerProfileIdentityUseCase(repository)

    assert use_case.execute(user_id=1007) is None
    assert use_case.execute(user_id=0) is None
    assert repository.calls == [1007]


def test_profile_for_a_different_user_is_not_exposed() -> None:
    """A mismatched repository response cannot leak another user's profile ID."""

    repository = FakeOwnerProfileRepository(
        AccountOwnerProfileIdentity(user_id=1008, profile_id=42)
    )
    use_case = GetAccountOwnerProfileIdentityUseCase(repository)

    assert use_case.execute(user_id=1007) is None
    assert repository.calls == [1007]


def test_non_exact_integer_user_ids_do_not_reach_the_repository() -> None:
    """Booleans and non-positive values are not accepted as User primary keys."""

    repository = FakeOwnerProfileRepository(None)
    use_case = GetAccountOwnerProfileIdentityUseCase(repository)

    assert use_case.execute(user_id=True) is None  # type: ignore[arg-type]
    assert use_case.execute(user_id=-1) is None
    assert repository.calls == []
