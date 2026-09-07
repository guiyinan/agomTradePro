"""Request adapter checks over immutable canonical actor authority."""

from datetime import timedelta

import pytest

from apps.account.application.account_actor_authority_request_reader import (
    CanonicalAccountActorAuthorityRequestReader,
)
from apps.account.application.account_owner_assignment_actor_authority_source_v3 import (
    AccountOwnerAssignmentActorAuthoritySourceV3Unavailable,
    GetCurrentAccountOwnerAssignmentActorAuthoritySourceV3Command,
)
from apps.account.application.account_owner_assignment_evidence import (
    AccountOwnerAssignmentCorruption,
)
from apps.account.domain.account_owner_assignment_actor_authority_source_v3 import (
    AccountOwnerAssignmentActorAuthoritySourceV3,
)
from tests.unit.account.test_account_owner_assignment_actor_authority_source_v3 import (
    NOW,
    _source,
)


class CurrentReader:
    def __init__(self, source: AccountOwnerAssignmentActorAuthoritySourceV3 | None) -> None:
        self.source = source
        self.calls: list[GetCurrentAccountOwnerAssignmentActorAuthoritySourceV3Command] = []

    def execute(
        self, command: GetCurrentAccountOwnerAssignmentActorAuthoritySourceV3Command
    ) -> AccountOwnerAssignmentActorAuthoritySourceV3 | None:
        self.calls.append(command)
        return self.source


def adapter(
    current: CurrentReader, source: AccountOwnerAssignmentActorAuthoritySourceV3
) -> CanonicalAccountActorAuthorityRequestReader:
    return CanonicalAccountActorAuthorityRequestReader(
        current_reader=current,
        source_id=source.source_id,
        source_version=source.source_version,
        expected_content_hash=source.content_hash,
    )


def test_projection_rechecks_current_source_each_time_and_binds_content_hash() -> None:
    source = _source()
    current = CurrentReader(source)
    reader = adapter(current, source)
    result = reader.get_exact_current(
        principal_id=source.principal_id,
        user_id=source.user_id,
        expected_authentication_context_hash=source.authentication_context_content_hash,
        as_of=NOW,
    )
    assert result is not None
    assert result.actor_id == source.actor_id
    assert result.authentication_context_hash == source.authentication_context_content_hash
    assert result.source_content_hash == source.content_hash
    assert result.recorded_at == source.recorded_at
    assert result.valid_until == source.valid_until
    current.source = None
    assert (
        reader.get_exact_current(
            principal_id=source.principal_id,
            user_id=source.user_id,
            expected_authentication_context_hash=source.authentication_context_content_hash,
            as_of=NOW,
        )
        is None
    )
    assert len(current.calls) == 2
    assert all(call.expected_content_hash == source.content_hash for call in current.calls)


@pytest.mark.parametrize(
    "principal,user,context_hash",
    [
        ("another-principal", 41, "b" * 64),
        ("principal-41", 42, "b" * 64),
        ("principal-41", 41, "a" * 64),
    ],
)
def test_request_substitution_is_corruption(principal: str, user: int, context_hash: str) -> None:
    source = _source()
    reader = adapter(CurrentReader(source), source)
    with pytest.raises(AccountOwnerAssignmentCorruption):
        reader.get_exact_current(
            principal_id=principal,
            user_id=user,
            expected_authentication_context_hash=context_hash,
            as_of=NOW,
        )


@pytest.mark.parametrize(
    "field,value",
    [("source_id", "other"), ("source_version", "v2"), ("expected_content_hash", "f" * 64)],
)
def test_source_substitution_is_corruption(field: str, value: str) -> None:
    source = _source()
    options = {
        "source_id": source.source_id,
        "source_version": source.source_version,
        "expected_content_hash": source.content_hash,
    }
    options[field] = value
    reader = CanonicalAccountActorAuthorityRequestReader(CurrentReader(source), **options)
    with pytest.raises(AccountOwnerAssignmentCorruption):
        reader.get_exact_current(
            principal_id=source.principal_id,
            user_id=source.user_id,
            expected_authentication_context_hash=source.authentication_context_content_hash,
            as_of=NOW,
        )


def test_future_record_cannot_be_projected_and_expiry_is_exclusive() -> None:
    source = _source()
    reader = adapter(CurrentReader(source), source)
    request = {
        "principal_id": source.principal_id,
        "user_id": source.user_id,
        "expected_authentication_context_hash": source.authentication_context_content_hash,
    }
    with pytest.raises(AccountOwnerAssignmentCorruption):
        reader.get_exact_current(**request, as_of=NOW - timedelta(seconds=1))
    assert reader.get_exact_current(**request, as_of=source.valid_until) is None


@pytest.mark.parametrize("state", ["revoked", "deactivated"])
def test_terminal_source_is_unavailable(state: str) -> None:
    source = _source(authority_state=state, is_active=False, is_authenticated=False)
    reader = adapter(CurrentReader(source), source)
    assert (
        reader.get_exact_current(
            principal_id=source.principal_id,
            user_id=source.user_id,
            expected_authentication_context_hash=source.authentication_context_content_hash,
            as_of=NOW,
        )
        is None
    )


def test_canonical_reader_failure_propagates_without_fallback() -> None:
    class UnavailableReader(CurrentReader):
        def execute(
            self, command: GetCurrentAccountOwnerAssignmentActorAuthoritySourceV3Command
        ) -> AccountOwnerAssignmentActorAuthoritySourceV3 | None:
            raise AccountOwnerAssignmentActorAuthoritySourceV3Unavailable("upstream unavailable")

    source = _source()
    reader = adapter(UnavailableReader(None), source)
    with pytest.raises(AccountOwnerAssignmentActorAuthoritySourceV3Unavailable):
        reader.get_exact_current(
            principal_id=source.principal_id,
            user_id=source.user_id,
            expected_authentication_context_hash=source.authentication_context_content_hash,
            as_of=NOW,
        )
