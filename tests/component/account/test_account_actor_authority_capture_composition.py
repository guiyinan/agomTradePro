"""Account composition binds canonical dependencies without database writes."""

from contextlib import nullcontext
from datetime import timedelta
from unittest.mock import Mock

import pytest

from apps.account import account_actor_authority_capture_composition as composition
from apps.account.application.account_owner_assignment_actor_authority_source_v3 import (
    CaptureAccountOwnerAssignmentActorAuthoritySourceV3,
)
from apps.account.infrastructure import (
    account_owner_assignment_actor_authority_bundle_provider as bundle_provider,
)
from tests.unit.account.test_account_owner_assignment_actor_authority_bundle_provider import (
    _Connection,
)
from tests.unit.account.test_account_owner_assignment_actor_authority_source_v3_application import (
    _command,
    _Repository,
)


@pytest.fixture
def factories(monkeypatch: pytest.MonkeyPatch) -> tuple[Mock, Mock]:
    inputs = Mock()
    repository = Mock()
    monkeypatch.setattr(composition, "DjangoAccountActorAuthorityInputBundleProviderV3", inputs)
    monkeypatch.setattr(composition, "DjangoAccountActorAuthorityCaptureBundleProviderV3", inputs)
    monkeypatch.setattr(
        composition, "DjangoAccountOwnerAssignmentActorAuthoritySourceV3Repository", repository
    )
    return inputs, repository


def test_capture_uses_explicit_alias_and_recorder_without_issuing(
    factories: tuple[Mock, Mock],
) -> None:
    inputs, repository = factories
    capture = composition.build_account_actor_authority_capture(
        recorder_service_id="account-attestor",
        validity_period=timedelta(minutes=5),
        using="authority",
    )
    assert isinstance(capture, CaptureAccountOwnerAssignmentActorAuthoritySourceV3)
    inputs.assert_called_once_with(
        using="authority",
        require_capture_transaction=repository.return_value.require_capture_transaction,
    )
    repository.assert_called_once_with(using="authority")
    assert capture._recorder.service_id == "account-attestor"
    assert capture._validity_period == timedelta(minutes=5)
    assert not repository.return_value.method_calls
    assert not inputs.return_value.method_calls


@pytest.mark.parametrize("alias", ["", " default", "default ", "a\nb", "a" * 65, None])
def test_alias_rejected_before_any_dependency_is_created(
    factories: tuple[Mock, Mock], alias: object
) -> None:
    with pytest.raises((ValueError, TypeError)):
        composition.build_account_actor_authority_capture(
            recorder_service_id="account-attestor",
            validity_period=timedelta(minutes=5),
            using=alias,
        )
    with pytest.raises((ValueError, TypeError)):
        composition.build_account_actor_authority_request_reader(
            source_id="source",
            source_version="v1",
            expected_content_hash="a" * 64,
            using=alias,
        )
    assert all(not factory.called for factory in factories)


@pytest.mark.parametrize("period", [timedelta(0), timedelta(seconds=-1), 30, None])
def test_invalid_ttl_never_constructs_repository(
    factories: tuple[Mock, Mock], period: object
) -> None:
    with pytest.raises((ValueError, TypeError)):
        composition.build_account_actor_authority_capture(
            recorder_service_id="account-attestor",
            validity_period=period,
        )
    assert all(not factory.called for factory in factories)


def test_invalid_recorder_never_constructs_repository(factories: tuple[Mock, Mock]) -> None:
    with pytest.raises((ValueError, TypeError)):
        composition.build_account_actor_authority_capture(
            recorder_service_id=" ",
            validity_period=timedelta(minutes=5),
        )
    assert all(not factory.called for factory in factories)


def test_request_factory_is_closed_to_explicit_source_and_same_alias(
    factories: tuple[Mock, Mock],
) -> None:
    inputs, repository = factories
    reader = composition.build_account_actor_authority_request_reader(
        source_id="source",
        source_version="v1",
        expected_content_hash="a" * 64,
        using="authority",
    )
    assert (reader.source_id, reader.source_version, reader.expected_content_hash) == (
        "source",
        "v1",
        "a" * 64,
    )
    inputs.assert_called_once_with(using="authority")
    repository.assert_called_once_with(using="authority")
    assert not repository.return_value.method_calls
    assert not inputs.return_value.method_calls


def test_capture_reaches_raw_factory_before_nested_outer_transaction_guard(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Regression sentinel; the fake connection is not real PostgreSQL."""

    connection = _Connection(alias="authority")
    connection.get_autocommit = lambda: not connection.in_atomic_block
    connection.cursor_value.fetchone = lambda: ("read committed",)
    connection.ops = Mock()
    connection.ops.quote_name.side_effect = lambda name: f'"{name}"'

    class _NestedAtomicRepository(_Repository):
        def require_capture_transaction(self) -> None:
            assert connection.in_atomic_block

        def atomic(self):  # type: ignore[no-untyped-def]
            connection.in_atomic_block = True
            return nullcontext()

    source_repository = _NestedAtomicRepository()
    monkeypatch.setattr(
        composition,
        "DjangoAccountOwnerAssignmentActorAuthoritySourceV3Repository",
        lambda *, using: source_repository,
    )
    monkeypatch.setattr(bundle_provider, "_connection_for_alias", lambda using: connection)

    class _RawRepositoriesFactorySentinel:
        def build(self, *, using: str) -> object:
            del using
            raise AssertionError("raw-repository-factory-sentinel")

    capture = composition.build_account_actor_authority_capture(
        recorder_service_id="account-attestor",
        validity_period=timedelta(minutes=5),
        using="authority",
    )
    capture._inputs._repositories_factory = _RawRepositoriesFactorySentinel()  # type: ignore[assignment]

    with pytest.raises(AssertionError, match="raw-repository-factory-sentinel"):
        capture.execute(_command())
