"""Publish one current source-bound single-owner policy root.

This Application boundary consumes a complete configuration/source snapshot and
a requester that was produced inside the real authentication transaction.  It
does not authenticate HTTP input, resolve a Binding-v2 scope, or grant any
later authority.  The composition root must perform those checks before
calling :meth:`PublishSingleOwnerAuthorityPolicyV1.execute`.
"""

from __future__ import annotations

from contextlib import AbstractContextManager
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from apps.account.application.account_owner_assignment_evidence import (
    AccountOwnerAssignmentConflict,
    AccountOwnerAssignmentCorruption,
    AccountOwnerAssignmentUnavailable,
)
from apps.account.application.owner_policy_authorization_source import (
    OwnerPolicyAuthorizationSource,
)
from apps.account.application.single_owner_policy_publication_settings import (
    SingleOwnerPolicyPublicationSettings,
)
from apps.account.domain.canonical_account_creation import CanonicalAccountCreationRequester
from apps.account.domain.single_owner_authority_policy_v1 import (
    SingleOwnerAuthorityPolicyV1,
)


def _token(value: object, field_name: str) -> str:
    """Validate one server-resolved canonical token."""

    if type(value) is not str:
        raise TypeError(f"{field_name} must be an exact string")
    if (
        not value
        or value.strip() != value
        or len(value) > 192
        or any(character.isspace() for character in value)
    ):
        raise ValueError(f"{field_name} must be a bounded canonical token")
    return value


def _aware(value: object, field_name: str) -> datetime:
    """Validate one timezone-aware server timestamp."""

    if type(value) is not datetime or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware")
    return value


def _digest(value: object, field_name: str) -> str:
    """Validate one non-empty lowercase SHA-256 seal."""

    if type(value) is not str:
        raise TypeError(f"{field_name} must be an exact string")
    if len(value) != 64 or any(character not in "0123456789abcdef" for character in value):
        raise ValueError(f"{field_name} must be a lowercase SHA-256 digest")
    return value


@dataclass(frozen=True, slots=True)
class PublishSingleOwnerAuthorityPolicyV1Command:
    """Server-resolved policy identity and canonical Account scope selectors.

    The command deliberately contains no owner, tenant, source, TTL, actor,
    mode, or status fields.  The composition root resolves this scope from the
    exact permanent Binding-v2 selector before invoking the publisher.
    """

    policy_id: str
    policy_version: str
    account_namespace: str
    account_id: str

    def __post_init__(self) -> None:
        """Reject substituted or non-canonical server selectors."""

        for field_name in (
            "policy_id",
            "policy_version",
            "account_namespace",
            "account_id",
        ):
            _token(getattr(self, field_name), field_name)


class CurrentSingleOwnerPolicyPublicationInputs(Protocol):
    """Read one complete active settings/source configuration snapshot."""

    def read_current(
        self,
    ) -> tuple[SingleOwnerPolicyPublicationSettings, OwnerPolicyAuthorizationSource] | None:
        """Return the complete settings and declaration source, or no snapshot."""

        ...


class SingleOwnerAuthorityPolicyV1Repository(Protocol):
    """Persist policy roots while preserving scope and first-winner semantics."""

    def atomic(self) -> AbstractContextManager[None]:
        """Open the private policy UOW inside any caller-owned outer transaction."""

        ...

    def now(self) -> datetime:
        """Return the authoritative timezone-aware repository clock."""

        ...

    def lock_scope(self, *, account_namespace: str, account_id: str) -> None:
        """Serialize all policy publishers for one canonical Account scope."""

        ...

    def get_current_for_scope(
        self,
        *,
        account_namespace: str,
        account_id: str,
        as_of: datetime,
    ) -> tuple[SingleOwnerAuthorityPolicyV1, ...]:
        """Return every current policy head for the exact scope."""

        ...

    def get_head(
        self,
        *,
        policy_id: str,
        as_of: datetime,
    ) -> SingleOwnerAuthorityPolicyV1 | None:
        """Return the durable head for a policy identity without fallback."""

        ...

    def append(
        self,
        *,
        policy: SingleOwnerAuthorityPolicyV1,
        expected_previous_content_hash: str | None,
    ) -> SingleOwnerAuthorityPolicyV1:
        """Append one sealed root or return the exact repository replay."""

        ...


class PublishSingleOwnerAuthorityPolicyV1:
    """Publish or replay one source-bound single-owner policy root.

    ``requester`` must come from the real authenticated single-owner policy
    transaction and the command scope must already have been resolved from an
    exact permanent Binding-v2 selector.  This class does not authenticate the
    requester or prove that Binding-v2 relationship itself.
    """

    def __init__(
        self,
        *,
        current_inputs: CurrentSingleOwnerPolicyPublicationInputs,
        repository: SingleOwnerAuthorityPolicyV1Repository,
    ) -> None:
        """Inject the complete runtime input reader and durable policy repository."""

        if not callable(getattr(current_inputs, "read_current", None)):
            raise TypeError("current_inputs must implement read_current")
        for method_name in (
            "atomic",
            "now",
            "lock_scope",
            "get_current_for_scope",
            "get_head",
            "append",
        ):
            if not callable(getattr(repository, method_name, None)):
                raise TypeError(f"repository must implement {method_name}")
        self._inputs = current_inputs
        self._repository = repository

    def execute(
        self,
        command: PublishSingleOwnerAuthorityPolicyV1Command,
        requester: CanonicalAccountCreationRequester,
    ) -> SingleOwnerAuthorityPolicyV1:
        """Publish a root or return its exact current replay after revalidation.

        The caller must already hold the real authentication and permanent
        Binding-v2 scope transaction.  A private repository UOW is still used
        for the policy lock, collision read, final source read, and append.
        """

        if type(command) is not PublishSingleOwnerAuthorityPolicyV1Command:
            raise TypeError("command must be an exact policy publication command")
        command.__post_init__()
        if type(requester) is not CanonicalAccountCreationRequester:
            raise TypeError("requester must be an exact authenticated requester")
        requester.__post_init__()

        first_inputs = self._read_inputs()
        if first_inputs is None:
            raise AccountOwnerAssignmentUnavailable(
                "single-owner policy settings and source are unavailable"
            )

        with self._repository.atomic():
            self._repository.lock_scope(
                account_namespace=command.account_namespace,
                account_id=command.account_id,
            )
            cutoff = self._clock(self._repository.now())
            second_inputs = self._read_inputs()
            if second_inputs is None:
                raise AccountOwnerAssignmentUnavailable(
                    "single-owner policy settings and source are unavailable"
                )
            if first_inputs != second_inputs:
                raise AccountOwnerAssignmentConflict(
                    "single-owner policy settings/source snapshot changed"
                )
            settings, source = second_inputs
            self._validate_snapshot(settings, source, requester, cutoff)

            current = self._current_for_scope(command, cutoff)
            if len(current) > 1:
                raise AccountOwnerAssignmentConflict(
                    "multiple current single-owner policies cover one Account scope"
                )
            if current:
                policy = current[0]
                if (
                    policy.policy_id != command.policy_id
                    or policy.policy_version != command.policy_version
                ):
                    raise AccountOwnerAssignmentConflict(
                        "another current single-owner policy covers the Account scope"
                    )
                final_settings, final_source, final_cutoff = self._final_inputs(
                    (settings, source),
                    requester=requester,
                    previous_cutoff=cutoff,
                )
                return self._replay(
                    policy,
                    command=command,
                    requester=requester,
                    settings=final_settings,
                    source=final_source,
                    cutoff=final_cutoff,
                )

            head = self._optional_policy(
                self._repository.get_head(policy_id=command.policy_id, as_of=cutoff),
                "single-owner policy head",
            )
            if head is not None:
                if head.observed_at > cutoff:
                    raise AccountOwnerAssignmentCorruption(
                        "repository returned a future single-owner policy head"
                    )
                raise AccountOwnerAssignmentConflict(
                    "single-owner policy identity already has a durable head"
                )

            final_settings, final_source, final_cutoff = self._final_inputs(
                (settings, source),
                requester=requester,
                previous_cutoff=cutoff,
            )
            candidate = self._build(
                command,
                requester=requester,
                settings=final_settings,
                cutoff=final_cutoff,
            )
            persisted = self._repository.append(
                policy=candidate,
                expected_previous_content_hash=None,
            )
            checked = self._sealed_policy(persisted, "single-owner policy append")
            if checked != candidate:
                raise AccountOwnerAssignmentConflict(
                    "single-owner policy append first winner differs"
                )
            _, _, returned_at = self._final_inputs(
                (final_settings, final_source),
                requester=requester,
                previous_cutoff=final_cutoff,
            )
            if not checked.is_current_at(returned_at):
                raise AccountOwnerAssignmentConflict(
                    "single-owner policy expired before publication returned"
                )
            return checked

    def _read_inputs(
        self,
    ) -> tuple[SingleOwnerPolicyPublicationSettings, OwnerPolicyAuthorizationSource] | None:
        """Read and validate one complete settings/source tuple."""

        value = self._inputs.read_current()
        if value is None:
            return None
        if type(value) is not tuple or len(value) != 2:
            raise AccountOwnerAssignmentCorruption(
                "policy inputs reader returned a substituted snapshot"
            )
        settings, source = value
        if type(settings) is not SingleOwnerPolicyPublicationSettings:
            raise AccountOwnerAssignmentCorruption(
                "policy inputs reader returned a substituted settings type"
            )
        if type(source) is not OwnerPolicyAuthorizationSource:
            raise AccountOwnerAssignmentCorruption(
                "policy inputs reader returned a substituted source type"
            )
        try:
            settings.__post_init__()
            source.__post_init__()
        except (TypeError, ValueError) as error:
            raise AccountOwnerAssignmentCorruption(
                "policy inputs reader returned an invalid settings/source snapshot"
            ) from error
        return settings, source

    @staticmethod
    def _validate_snapshot(
        settings: SingleOwnerPolicyPublicationSettings,
        source: OwnerPolicyAuthorizationSource,
        requester: CanonicalAccountCreationRequester,
        cutoff: datetime,
    ) -> None:
        """Bind selectors and declaration facts to the trusted requester."""

        if (
            source.source_id != settings.authorization_source_id
            or source.source_version != settings.authorization_source_version
            or source.content_hash != settings.authorization_content_hash
            or source.owner_username != settings.owner_username
        ):
            raise AccountOwnerAssignmentCorruption(
                "authorization source does not match publication settings"
            )
        try:
            declared_at = _aware(source.declared_at, "authorization source declared_at")
        except (TypeError, ValueError) as error:
            raise AccountOwnerAssignmentCorruption(
                "authorization source declaration clock is invalid"
            ) from error
        if declared_at > cutoff:
            raise AccountOwnerAssignmentCorruption(
                "authorization source declaration is from the future"
            )
        if source.declared_user_id != requester.user_id:
            raise AccountOwnerAssignmentConflict(
                "authorization source declared user differs from authenticated requester"
            )

    def _final_inputs(
        self,
        expected: tuple[SingleOwnerPolicyPublicationSettings, OwnerPolicyAuthorizationSource],
        *,
        requester: CanonicalAccountCreationRequester,
        previous_cutoff: datetime,
    ) -> tuple[SingleOwnerPolicyPublicationSettings, OwnerPolicyAuthorizationSource, datetime]:
        """Re-read inputs and clock immediately before a replay or return."""

        value = self._read_inputs()
        if value is None:
            raise AccountOwnerAssignmentUnavailable(
                "single-owner policy settings and source are unavailable"
            )
        cutoff = self._clock(self._repository.now())
        if cutoff < previous_cutoff:
            raise AccountOwnerAssignmentCorruption(
                "single-owner policy repository clock moved backwards"
            )
        if value != expected:
            raise AccountOwnerAssignmentConflict(
                "single-owner policy settings/source snapshot changed"
            )
        settings, source = value
        self._validate_snapshot(settings, source, requester, cutoff)
        return settings, source, cutoff

    def _current_for_scope(
        self,
        command: PublishSingleOwnerAuthorityPolicyV1Command,
        cutoff: datetime,
    ) -> tuple[SingleOwnerAuthorityPolicyV1, ...]:
        """Validate every current head returned for the locked scope."""

        value = self._repository.get_current_for_scope(
            account_namespace=command.account_namespace,
            account_id=command.account_id,
            as_of=cutoff,
        )
        if type(value) is not tuple:
            raise AccountOwnerAssignmentCorruption(
                "policy repository returned a substituted current-head collection"
            )
        checked: list[SingleOwnerAuthorityPolicyV1] = []
        for item in value:
            policy = self._sealed_policy(item, "current single-owner policy")
            if (
                policy.account_namespace != command.account_namespace
                or policy.account_id != command.account_id
            ):
                raise AccountOwnerAssignmentCorruption(
                    "current policy scope differs from the locked Account scope"
                )
            if not policy.is_current_at(cutoff):
                raise AccountOwnerAssignmentCorruption(
                    "repository returned an expired, revoked, or future current policy"
                )
            checked.append(policy)
        return tuple(checked)

    def _replay(
        self,
        policy: SingleOwnerAuthorityPolicyV1,
        *,
        command: PublishSingleOwnerAuthorityPolicyV1Command,
        requester: CanonicalAccountCreationRequester,
        settings: SingleOwnerPolicyPublicationSettings,
        source: OwnerPolicyAuthorizationSource,
        cutoff: datetime,
    ) -> SingleOwnerAuthorityPolicyV1:
        """Return only a full immutable replay matching current settings and TTL."""

        expected = self._build(
            command,
            requester=requester,
            settings=settings,
            cutoff=policy.observed_at,
        )
        if policy.valid_until - policy.observed_at != settings.as_timedelta():
            raise AccountOwnerAssignmentConflict(
                "current single-owner policy replay TTL differs from settings"
            )
        if expected != policy:
            if (
                policy.authorization_content_hash != source.content_hash
                or policy.owner_user_id != requester.user_id
                or policy.tenant_id != settings.tenant_id
                or policy.owner_id != settings.owner_id
            ):
                raise AccountOwnerAssignmentConflict(
                    "current single-owner policy replay differs from settings"
                )
            raise AccountOwnerAssignmentConflict(
                "current single-owner policy replay payload differs"
            )
        if not policy.is_current_at(cutoff):
            raise AccountOwnerAssignmentConflict(
                "current single-owner policy became non-current during replay"
            )
        return policy

    @staticmethod
    def _build(
        command: PublishSingleOwnerAuthorityPolicyV1Command,
        *,
        requester: CanonicalAccountCreationRequester,
        settings: SingleOwnerPolicyPublicationSettings,
        cutoff: datetime,
    ) -> SingleOwnerAuthorityPolicyV1:
        """Construct one fully sealed active policy from trusted facts."""

        try:
            valid_until = settings.deadline_at(cutoff)
            return SingleOwnerAuthorityPolicyV1(
                policy_id=command.policy_id,
                policy_version=command.policy_version,
                tenant_id=settings.tenant_id,
                owner_id=settings.owner_id,
                account_namespace=command.account_namespace,
                account_id=command.account_id,
                owner_user_id=requester.user_id,
                authorization_content_hash=settings.authorization_content_hash,
                observed_at=cutoff,
                valid_from=cutoff,
                valid_until=valid_until,
            )
        except (TypeError, ValueError) as error:
            raise AccountOwnerAssignmentCorruption(
                "single-owner policy candidate is invalid"
            ) from error

    @staticmethod
    def _sealed_policy(value: object, field_name: str) -> SingleOwnerAuthorityPolicyV1:
        """Require an exact persisted policy with both pre-existing seals."""

        if type(value) is not SingleOwnerAuthorityPolicyV1:
            raise AccountOwnerAssignmentCorruption(f"{field_name} type substitution")
        policy = value
        try:
            _digest(policy.identity_hash, f"{field_name} identity_hash")
            _digest(policy.content_hash, f"{field_name} content_hash")
            policy.__post_init__()
        except (TypeError, ValueError) as error:
            raise AccountOwnerAssignmentCorruption(f"{field_name} seal is invalid") from error
        return policy

    @classmethod
    def _optional_policy(
        cls,
        value: object | None,
        field_name: str,
    ) -> SingleOwnerAuthorityPolicyV1 | None:
        """Validate an optional durable policy response without computing seals."""

        return None if value is None else cls._sealed_policy(value, field_name)

    @staticmethod
    def _clock(value: object) -> datetime:
        """Require a monotonic-aware repository cutoff value."""

        try:
            return _aware(value, "repository clock")
        except (TypeError, ValueError) as error:
            raise AccountOwnerAssignmentCorruption("repository clock is invalid") from error


__all__ = [
    "CurrentSingleOwnerPolicyPublicationInputs",
    "PublishSingleOwnerAuthorityPolicyV1",
    "PublishSingleOwnerAuthorityPolicyV1Command",
    "SingleOwnerAuthorityPolicyV1Repository",
]
