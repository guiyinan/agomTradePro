"""Composition roots for canonical Account actor authority capture and reads."""

from __future__ import annotations

from datetime import timedelta

from apps.account.application.account_actor_authority_request_reader import (
    CanonicalAccountActorAuthorityRequestReader,
)
from apps.account.application.account_owner_assignment_actor_authority_source_v3 import (
    AccountOwnerAssignmentActorAuthoritySourceV3Recorder,
    CaptureAccountOwnerAssignmentActorAuthoritySourceV3,
    GetCurrentAccountOwnerAssignmentActorAuthoritySourceV3,
)
from apps.account.infrastructure.account_actor_authority_capture_snapshot import (
    DjangoAccountActorAuthorityCaptureBundleProviderV3,
)
from apps.account.infrastructure.account_owner_assignment_actor_authority_bundle_provider import (
    DjangoAccountActorAuthorityInputBundleProviderV3,
)
from apps.account.infrastructure.account_owner_assignment_actor_authority_source_v3_repository import (
    DjangoAccountOwnerAssignmentActorAuthoritySourceV3Repository,
)


def build_account_actor_authority_capture(
    *,
    recorder_service_id: str,
    validity_period: timedelta,
    using: str = "default",
) -> CaptureAccountOwnerAssignmentActorAuthoritySourceV3:
    """Build the canonical actor-source writer for one validated alias.

    The existing writer remains dormant until its caller explicitly invokes
    ``execute`` with a canonical selector command.  This factory only wires
    the existing read bundle, repository, recorder identity, and TTL.
    """

    alias = _validate_using(using)
    _validate_token(recorder_service_id, "recorder_service_id")
    _validate_validity_period(validity_period)
    recorder = AccountOwnerAssignmentActorAuthoritySourceV3Recorder(recorder_service_id)
    repository = DjangoAccountOwnerAssignmentActorAuthoritySourceV3Repository(using=alias)
    return CaptureAccountOwnerAssignmentActorAuthoritySourceV3(
        input_bundle_provider=DjangoAccountActorAuthorityCaptureBundleProviderV3(
            using=alias, require_capture_transaction=repository.require_capture_transaction
        ),
        repository=repository,
        recorder=recorder,
        validity_period=validity_period,
    )


def build_account_actor_authority_request_reader(
    *,
    source_id: str,
    source_version: str,
    expected_content_hash: str,
    using: str = "default",
) -> CanonicalAccountActorAuthorityRequestReader:
    """Build the exact-current request reader on one canonical source alias."""

    alias = _validate_using(using)
    _validate_token(source_id, "source_id")
    _validate_token(source_version, "source_version")
    _validate_digest(expected_content_hash, "expected_content_hash")
    input_bundle_provider = DjangoAccountActorAuthorityInputBundleProviderV3(using=alias)
    repository = DjangoAccountOwnerAssignmentActorAuthoritySourceV3Repository(using=alias)
    current_reader = GetCurrentAccountOwnerAssignmentActorAuthoritySourceV3(
        input_bundle_provider=input_bundle_provider,
        repository=repository,
    )
    return CanonicalAccountActorAuthorityRequestReader(
        current_reader=current_reader,
        source_id=source_id,
        source_version=source_version,
        expected_content_hash=expected_content_hash,
    )


def _validate_using(value: object) -> str:
    """Validate one exact bounded Django database alias."""

    if (
        type(value) is not str
        or not value
        or value.strip() != value
        or len(value) > 64
        or any(character.isspace() for character in value)
    ):
        raise ValueError("using must be one exact database alias")
    return value


def _validate_token(value: object, name: str) -> None:
    """Validate one canonical bounded token before composition."""

    if (
        type(value) is not str
        or not value
        or value.strip() != value
        or len(value) > 192
        or any(character.isspace() for character in value)
    ):
        raise ValueError(f"{name} must be a bounded canonical token")


def _validate_digest(value: object, name: str) -> None:
    """Validate one lowercase SHA-256 selector digest."""

    if (
        type(value) is not str
        or len(value) != 64
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise ValueError(f"{name} must be a lowercase SHA-256 digest")


def _validate_validity_period(value: object) -> None:
    """Validate one positive exact capture TTL before dependency construction."""

    if type(value) is not timedelta or value <= timedelta(0):
        raise ValueError("validity_period must be an exact positive timedelta")


__all__ = [
    "build_account_actor_authority_capture",
    "build_account_actor_authority_request_reader",
]
