from __future__ import annotations

import pytest

from apps.account.application.account_actor_authority_raw_source_primitives_v3 import (
    AccountActorAuthorityRawSourceV3Corruption,
    AccountActorAuthorityRawSourceV3Unavailable,
)
from apps.account.application.account_owner_assignment_actor_authority_source_v3 import (
    AccountOwnerAssignmentActorAuthoritySourceV3,
    AccountOwnerAssignmentActorAuthoritySourceV3Corruption,
    AccountOwnerAssignmentActorAuthoritySourceV3Unavailable,
    GetCurrentAccountOwnerAssignmentActorAuthoritySourceV3,
    GetCurrentAccountOwnerAssignmentActorAuthoritySourceV3Command,
)
from tests.unit.account.test_account_owner_assignment_actor_authority_source_v3_application import (
    _at,
    _bundle,
    _capture,
    _command,
    _Provider,
    _Repository,
)


class _RaisingProvider:
    def __init__(self, error: Exception) -> None:
        self.error = error

    def get_exact_current(self, **kwargs: object) -> object | None:
        del kwargs
        raise self.error


def _current_command(
    source: AccountOwnerAssignmentActorAuthoritySourceV3,
) -> GetCurrentAccountOwnerAssignmentActorAuthoritySourceV3Command:
    return GetCurrentAccountOwnerAssignmentActorAuthoritySourceV3Command(
        source_id=source.source_id,
        source_version=source.source_version,
        expected_content_hash=source.content_hash,
        as_of=_at(11),
    )


def _seed_source() -> tuple[
    _Repository,
    AccountOwnerAssignmentActorAuthoritySourceV3,
]:
    repository = _Repository()
    source = _capture(_Provider([_bundle()]), repository).execute(_command())
    return repository, source


def test_raw_unavailable_is_actor_unavailable_during_initial_capture() -> None:
    with pytest.raises(AccountOwnerAssignmentActorAuthoritySourceV3Unavailable):
        _capture(
            _RaisingProvider(AccountActorAuthorityRawSourceV3Unavailable("raw unavailable")),
            _Repository(),
        ).execute(_command())


def test_raw_unavailable_is_none_in_current_reader() -> None:
    repository, source = _seed_source()
    reader = GetCurrentAccountOwnerAssignmentActorAuthoritySourceV3(
        input_bundle_provider=_RaisingProvider(
            AccountActorAuthorityRawSourceV3Unavailable("raw unavailable")
        ),
        repository=repository,
    )

    assert reader.execute(_current_command(source)) is None


def test_raw_corruption_is_never_coerced_to_none() -> None:
    repository, source = _seed_source()
    reader = GetCurrentAccountOwnerAssignmentActorAuthoritySourceV3(
        input_bundle_provider=_RaisingProvider(
            AccountActorAuthorityRawSourceV3Corruption("raw corruption")
        ),
        repository=repository,
    )

    with pytest.raises(
        (
            AccountOwnerAssignmentActorAuthoritySourceV3Corruption,
            AccountActorAuthorityRawSourceV3Corruption,
        )
    ):
        reader.execute(_current_command(source))
